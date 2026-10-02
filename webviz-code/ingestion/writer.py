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


def write_row(kind, row):
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
