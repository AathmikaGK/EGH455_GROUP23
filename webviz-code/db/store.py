import threading
from datetime import datetime

import config
from db import conn as dbconn

# all the sql lives here. if the database is off the rows go to memory instead

lock = threading.Lock()
mem = {"readings": [], "detections": [], "system_log": []}

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
           "ammonia_ohms, ammonia_ppm) "
           "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)")
    vals = (row["ts"], row["temperature"], row["pressure"], row["humidity"], row["light"],
            row["oxidising_ohms"], row["oxidising_ppm"], row["reducing_ohms"],
            row["reducing_ppm"], row["ammonia_ohms"], row["ammonia_ppm"])
    run_insert(sql, vals)


def save_detection(row):
    keep_in_memory("detections", row)
    if not db_ok:
        return
    sql = ("INSERT INTO detections (ts, type, valve_state, gauge_value, gauge_units, "
           "aruco_id, x, y, z, confidence, frame_path) "
           "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)")
    vals = (row["ts"], row["type"], row["valve_state"], row["gauge_value"], row["gauge_units"],
            row["aruco_id"], row["x"], row["y"], row["z"], row["confidence"], row["frame_path"])
    run_insert(sql, vals)


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


def clean_row(row):
    # turn the row into something json can handle
    out = {}
    for k, v in row.items():
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
