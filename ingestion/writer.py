import queue
import threading
import time
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
counts = {"reading": 0, "detection": 0, "log": 0, "frame": 0, "dropped": 0, "bad": 0}


def now_ms():
    # server clock, cut to milliseconds because that is what DATETIME(3) holds
    t = datetime.now()
    return t.replace(microsecond=(t.microsecond // 1000) * 1000)


def lag_of(captured_at):
    # seconds from capture on the payload to arrival here, the REQ-M-19 number.
    # only right when the payload clock is synced to this one
    if captured_at is None:
        return None
    return round(time.time() - captured_at, 3)


def stamp_lag(row, fallback=None):
    # swaps the sender's capture time for the delay it worked out to
    captured_at = row.pop("captured_at", None)
    lag = lag_of(captured_at)
    row["capture_lag"] = lag if lag is not None else fallback


def send_to_writer(kind, msg):
    # stamp first so the time is close to the sensor, then check, then queue
    if kind not in WRITE_AS:
        return False, "unknown message kind " + str(kind)

    row, err = checks.check_message(kind, msg)
    if row is None:
        counts["bad"] = counts["bad"] + 1
        return False, err

    row["ts"] = now_ms()
    stamp_lag(row)

    if not queue_job(WRITE_AS[kind], row):
        return False, "writer queue is full"
    return True, None


def queue_job(kind, row):
    # better to lose a sample than to block the subsystem that sent it
    try:
        inbox.put_nowait((kind, row))
    except queue.Full:
        counts["dropped"] = counts["dropped"] + 1
        return False
    return True


def check_targets(items):
    # checks every target of one frame, returns (rows, problems)
    rows = []
    problems = []
    for i, msg in enumerate(items):
        row, err = checks.check_detection(msg)
        if row is None:
            counts["bad"] = counts["bad"] + 1
            problems.append({"index": i, "error": err})
            continue
        rows.append(row)
    return rows, problems


def send_targets(items):
    rows, problems = check_targets(items)
    return queue_targets(rows, problems)


def queue_targets(rows, problems, frame_id=None, lag=None):
    # one camera frame from the taq. every target gets the same ts, so the
    # rows of one frame line up in the history. returns (taken, problems)
    stamp = now_ms()
    for row in rows:
        row["ts"] = stamp
        row["frame_id"] = frame_id
        stamp_lag(row, lag)

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

    # a saved jpeg for the image history, the file is already on disk
    if kind == "frame":
        store.save_frame(row)
        counts["frame"] = counts["frame"] + 1
        if row["n_targets"] > 0:
            bus.note_capture(row)
        return

    # old jpegs were deleted, their rows go too
    if kind == "frame_prune":
        store.prune_frames(row["max_id"])
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
