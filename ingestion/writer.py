import queue
import threading
from datetime import datetime

from db import store
from ingestion import checks
from live import bus

# the single writer. stamp the time, check it, write one row, tell the bus

# drill events are just log rows with the drill columns filled in
WRITE_AS = {
    "reading": "reading",
    "detection": "detection",
    "log": "log",
    "drill": "log",
}

inbox = queue.Queue(maxsize=2000)
running = False
counts = {"reading": 0, "detection": 0, "log": 0, "dropped": 0, "bad": 0}


def now_ms():
    # pi clock, cut to milliseconds because that is what DATETIME(3) holds
    t = datetime.now()
    return t.replace(microsecond=(t.microsecond // 1000) * 1000)


def send_to_writer(kind, msg):
    # stamp first so the time is close to the sensor, then check, then queue
    if kind not in WRITE_AS:
        return False, "unknown message kind " + str(kind)

    row, err = checks.check_message(kind, msg)
    if row is None:
        counts["bad"] = counts["bad"] + 1
        return False, err

    row["ts"] = now_ms()

    try:
        inbox.put_nowait((WRITE_AS[kind], row))
    except queue.Full:
        # better to lose a sample than to block the subsystem that sent it
        counts["dropped"] = counts["dropped"] + 1
        return False, "writer queue is full"
    return True, None


def send_targets(items):
    # one camera frame from the taq. every target gets the same ts, so the
    # rows of one frame line up in the history. returns (taken, problems)
    stamp = now_ms()
    rows = []
    problems = []
    for i, msg in enumerate(items):
        row, err = checks.check_detection(msg)
        if row is None:
            counts["bad"] = counts["bad"] + 1
            problems.append({"index": i, "error": err})
            continue
        row["ts"] = stamp
        rows.append(row)

    jobs = [("detection", row) for row in rows]
    # a list of only aruco markers (or an empty one) is the whole view, so the
    # dashboard can drop markers that left it. mixed batches leave it alone
    if len(problems) == 0 and all(row["type"] == "aruco" for row in rows):
        jobs.append(("aruco_view", {"ts": stamp, "ids": [row["aruco_id"] for row in rows]}))

    taken = 0
    for job in jobs:
        try:
            inbox.put_nowait(job)
        except queue.Full:
            counts["dropped"] = counts["dropped"] + 1
            problems.append({"index": None, "error": "writer queue is full"})
            break
        if job[0] == "detection":
            taken = taken + 1
    return taken, problems


def write_row(kind, row):
    # no table for this one, it only tells the dashboards which markers are in view
    if kind == "aruco_view":
        bus.note_aruco_view(row)
        return

    # one message, one row, then the dashboards get told about it
    if kind == "reading":
        store.save_reading(row)
    elif kind == "detection":
        store.save_detection(row)
    else:
        store.save_log(row)

    counts[kind] = counts[kind] + 1
    bus.publish(kind, row)


def writer_loop():
    while running:
        try:
            kind, row = inbox.get(timeout=0.5)
        except queue.Empty:
            continue
        try:
            write_row(kind, row)
        except Exception as err:
            # a bad row should never take the writer thread down with it
            print("[writer] could not write %s: %s" % (kind, err))
        finally:
            inbox.task_done()


def start_writer():
    global running
    if running:
        return
    running = True
    t = threading.Thread(target=writer_loop, name="db-writer", daemon=True)
    t.start()
    print("[writer] single writer thread started")


def stats():
    out = dict(counts)
    out["queued"] = inbox.qsize()
    return out
