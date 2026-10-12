import threading
from datetime import datetime

import config
from db import conn as dbconn

# all the sql lives here. if the database is off the rows go to memory instead

lock = threading.Lock()
mem = {"readings": [], "detections": [], "system_log": [], "frames": []}

writer_conn = None
db_ok = False


def start_store():
    # called once when the app boots
    global db_ok
    db_ok = dbconn.db_is_up()
    if db_ok:
        print("[store] using mariadb at %s/%s" % (config.DB_HOST, config.DB_NAME))
    else:
        print("[store] no database, keeping rows in memory only")
    return db_ok


def using_db():
    return db_ok


def writer_cursor():
    # only one writer, so it keeps one connection and reopens it if dropped
    global writer_conn
    if writer_conn is None:
        writer_conn = dbconn.get_conn()
    else:
        try:
            writer_conn.ping(reconnect=True)
        except Exception:
            writer_conn = dbconn.get_conn()
    return writer_conn.cursor()


def keep_in_memory(table, row):
    with lock:
        mem[table].append(row)
        if len(mem[table]) > config.MEM_ROWS:
            mem[table] = mem[table][-config.MEM_ROWS:]


def save_reading(row):
    keep_in_memory("readings", row)
    if not db_ok:
        return
    sql = ("INSERT INTO readings (ts, temperature, pressure, humidity, light, "
           "oxidising_ohms, oxidising_ppm, reducing_ohms, reducing_ppm, "
           "ammonia_ohms, ammonia_ppm, capture_lag) "
           "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)")
    vals = (row["ts"], row["temperature"], row["pressure"], row["humidity"], row["light"],
            row["oxidising_ohms"], row["oxidising_ppm"], row["reducing_ohms"],
            row["reducing_ppm"], row["ammonia_ohms"], row["ammonia_ppm"], row["capture_lag"])
    run_insert(sql, vals)


def save_detection(row):
    keep_in_memory("detections", row)
    if not db_ok:
        return
    sql = ("INSERT INTO detections (ts, type, valve_state, gauge_value, gauge_units, "
           "aruco_id, x, y, z, uav_x, uav_y, uav_z, confidence, frame_path, frame_id, "
           "capture_lag) "
           "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)")
    vals = (row["ts"], row["type"], row["valve_state"], row["gauge_value"], row["gauge_units"],
            row["aruco_id"], row["x"], row["y"], row["z"], row["uav_x"], row["uav_y"],
            row["uav_z"], row["confidence"], row["frame_path"], row["frame_id"],
            row["capture_lag"])
    run_insert(sql, vals)


def save_frame(row):
    # one saved jpeg. the id is picked by video/capture.py so the file name
    # and the row agree before the row is written
    keep_in_memory("frames", row)
    if not db_ok:
        return
    sql = ("INSERT INTO frames (id, ts, path, n_targets, types, bytes, capture_lag) "
           "VALUES (%s,%s,%s,%s,%s,%s,%s)")
    vals = (row["id"], row["ts"], row["path"], row["n_targets"], row["types"],
            row["bytes"], row["capture_lag"])
    run_insert(sql, vals)


def prune_frames(max_id):
    # the jpegs up to max_id are gone, so their rows go and detections stop pointing at them
    with lock:
        mem["frames"] = [r for r in mem["frames"] if r["id"] > max_id]
        for r in mem["detections"]:
            if r.get("frame_id") is not None and r["frame_id"] <= max_id:
                r["frame_id"] = None
    if not db_ok:
        return
    run_insert("DELETE FROM frames WHERE id <= %s", (max_id,))
    run_insert("UPDATE detections SET frame_id = NULL WHERE frame_id <= %s", (max_id,))


def save_log(row):
    keep_in_memory("system_log", row)
    if not db_ok:
        return
    sql = ("INSERT INTO system_log (ts, level, component, message, drill_state, "
           "hole_depth, trigger_pressure) VALUES (%s,%s,%s,%s,%s,%s,%s)")
    vals = (row["ts"], row["level"], row["component"], row["message"],
            row["drill_state"], row["hole_depth"], row["trigger_pressure"])
    run_insert(sql, vals)


def run_insert(sql, vals):
    global db_ok
    try:
        cur = writer_cursor()
        cur.execute(sql, vals)
        cur.close()
    except Exception as err:
        # the memory copy already has the row, do not kill the writer thread
        print("[store] insert failed:", err)
        print("[store] if a column is missing, run python -m db.init to update the tables")
        db_ok = False


def get_history(table, start, end, limit):
    if table not in mem:
        raise ValueError("unknown table " + table)
    if db_ok:
        try:
            return read_from_db(table, start, end, limit)
        except Exception as err:
            print("[store] history query failed:", err)
    return read_from_memory(table, start, end, limit)


def read_from_db(table, start, end, limit):
    c = dbconn.get_conn()
    try:
        cur = c.cursor()
        # newest first for the limit, then flipped because charts want oldest first
        sql = "SELECT * FROM %s WHERE ts BETWEEN %%s AND %%s ORDER BY ts DESC LIMIT %%s" % table
        cur.execute(sql, (start, end, limit))
        rows = list(cur.fetchall())
        rows.reverse()
        cur.close()
        return [clean_row(r) for r in rows]
    finally:
        c.close()


def read_from_memory(table, start, end, limit):
    with lock:
        rows = [r for r in mem[table] if start <= r["ts"] <= end]
    return [clean_row(r) for r in rows[-limit:]]


def get_frames(start, end, limit, only_targets=False, kind=None):
    # saved frames in a time range, oldest first. kind keeps frames holding that target type
    if db_ok:
        try:
            return frames_from_db(start, end, limit, only_targets, kind)
        except Exception as err:
            print("[store] frames query failed:", err)
    with lock:
        rows = [r for r in mem["frames"] if start <= r["ts"] <= end]
    if only_targets:
        rows = [r for r in rows if r["n_targets"] > 0]
    if kind:
        rows = [r for r in rows if kind in r["types"].split(",")]
    return [clean_row(r) for r in rows[-limit:]]


def frames_from_db(start, end, limit, only_targets, kind):
    sql = "SELECT * FROM frames WHERE ts BETWEEN %s AND %s"
    vals = [start, end]
    if only_targets:
        sql += " AND n_targets > 0"
    if kind:
        sql += " AND FIND_IN_SET(%s, types)"
        vals.append(kind)
    sql += " ORDER BY ts DESC LIMIT %s"
    vals.append(limit)

    c = dbconn.get_conn()
    try:
        cur = c.cursor()
        cur.execute(sql, vals)
        rows = list(cur.fetchall())
        rows.reverse()
        cur.close()
        return [clean_row(r) for r in rows]
    finally:
        c.close()


def get_targets_for(frame_ids):
    # the detection rows drawn on these saved frames
    if not frame_ids:
        return []
    if db_ok:
        try:
            c = dbconn.get_conn()
            try:
                cur = c.cursor()
                marks = ",".join(["%s"] * len(frame_ids))
                cur.execute("SELECT * FROM detections WHERE frame_id IN (%s) ORDER BY id" % marks,
                            list(frame_ids))
                rows = list(cur.fetchall())
                cur.close()
                return [clean_row(r) for r in rows]
            finally:
                c.close()
        except Exception as err:
            print("[store] targets query failed:", err)
    wanted = set(frame_ids)
    with lock:
        rows = [r for r in mem["detections"] if r.get("frame_id") in wanted]
    return [clean_row(r) for r in rows]


def clean_row(row):
    # turn the row into something json can handle
    out = {}
    for k, v in row.items():
        if k in ("box", "corners") and v is None:
            continue
        if isinstance(v, datetime):
            out[k] = to_iso(v)
        else:
            out[k] = v
    return out


def to_iso(t):
    # millisecond precision iso string, e.g. 2026-09-15T10:22:03.417
    return t.isoformat(timespec="milliseconds")


def count_rows(table):
    # the dashboard shows how many samples have been logged so far
    if table not in mem:
        return 0
    if db_ok:
        try:
            return count_in_db(table)
        except Exception as err:
            print("[store] count failed:", err)
    with lock:
        return len(mem[table])


def count_in_db(table):
    c = dbconn.get_conn()
    try:
        cur = c.cursor()
        cur.execute("SELECT COUNT(*) AS n FROM " + table)
        n = cur.fetchone()["n"]
        cur.close()
        return n
    finally:
        c.close()
