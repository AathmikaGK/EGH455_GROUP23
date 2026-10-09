import os
import queue
import shutil
import threading
import time
from datetime import datetime

import config
from ingestion import writer

# saves the kept frames to disk for the image history (REQ-F-07).
# its own thread, so a slow disk never holds up the live video

jobs = queue.Queue(maxsize=config.CAPTURE_QUEUE)
running = False

id_lock = threading.Lock()
last_id = 0
last_idle_save = 0.0
low_disk = False
counts = {"saved": 0, "skipped_disk": 0, "dropped": 0, "failed": 0, "deleted": 0}

CLEANUP_SECONDS = 60
MB = 1024 * 1024


def next_id():
    # milliseconds since 1970, bumped by one if two frames land in the same ms.
    # doubles as the file name, so the id alone finds the jpeg
    global last_id
    with id_lock:
        last_id = max(int(time.time() * 1000), last_id + 1)
        return last_id


def path_for(frame_id):
    # relative path, one folder per day: 2026-10-09/1791450000412.jpg
    day = datetime.fromtimestamp(frame_id / 1000.0).strftime("%Y-%m-%d")
    return day + "/" + "%d.jpg" % frame_id


def full_path(frame_id):
    return os.path.join(config.CAPTURE_DIR, *path_for(frame_id).split("/"))


def free_mb():
    # the capture folder may not exist yet, so ask about the closest folder that does
    where = config.CAPTURE_DIR
    while not os.path.isdir(where):
        parent = os.path.dirname(where)
        if parent == where:
            break
        where = parent
    try:
        return shutil.disk_usage(where).free / MB
    except OSError:
        return 0.0


def should_keep(has_targets):
    # frames with a target are always kept, the rest at most every SAVE_IDLE_SECONDS
    global last_idle_save, low_disk
    if not config.SAVE_FRAMES:
        return False

    if free_mb() < config.MIN_FREE_MB:
        if not low_disk:
            print("[capture] disk below %d MB free, not saving frames" % config.MIN_FREE_MB)
        low_disk = True
        counts["skipped_disk"] = counts["skipped_disk"] + 1
        return False
    low_disk = False

    if has_targets:
        return True
    if config.SAVE_IDLE_SECONDS <= 0:
        return False
    now = time.time()
    if now - last_idle_save >= config.SAVE_IDLE_SECONDS:
        last_idle_save = now
        return True
    return False


def save(frame_id, jpeg, rows, lag):
    # hands the frame to the saver thread. returns False if it had to be dropped
    types = sorted(set(row["type"] for row in rows))
    try:
        jobs.put_nowait((frame_id, jpeg, len(rows), ",".join(types), lag))
    except queue.Full:
        counts["dropped"] = counts["dropped"] + 1
        return False
    return True


def write_one(frame_id, jpeg, n_targets, types, lag):
    path = full_path(frame_id)
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as f:
            f.write(jpeg)
    except OSError as err:
        counts["failed"] = counts["failed"] + 1
        print("[capture] could not save frame:", err)
        # a half written file is worse than none
        try:
            os.remove(path)
        except OSError:
            pass
        return

    counts["saved"] = counts["saved"] + 1
    stamp = datetime.fromtimestamp(frame_id / 1000.0)
    writer.queue_job("frame", {
        "id": frame_id,
        "ts": stamp.replace(microsecond=(stamp.microsecond // 1000) * 1000),
        "path": path_for(frame_id),
        "n_targets": n_targets,
        "types": types,
        "bytes": len(jpeg),
        "capture_lag": lag,
    })


def cleanup():
    # deletes jpegs older than CAPTURE_KEEP_HOURS, then the oldest until under CAPTURE_MAX_MB
    root = config.CAPTURE_DIR
    if not os.path.isdir(root):
        return

    found = []
    for day in os.listdir(root):
        folder = os.path.join(root, day)
        if not os.path.isdir(folder):
            continue
        for name in os.listdir(folder):
            if not name.endswith(".jpg") or not name[:-4].isdigit():
                continue
            path = os.path.join(folder, name)
            try:
                found.append((int(name[:-4]), path, os.path.getsize(path)))
            except OSError:
                continue
    found.sort()

    total = sum(size for _, _, size in found)
    keep_from = (time.time() - config.CAPTURE_KEEP_HOURS * 3600) * 1000
    cap = config.CAPTURE_MAX_MB * MB
    gone = 0
    for frame_id, path, size in found:
        if frame_id >= keep_from and total <= cap:
            break
        try:
            os.remove(path)
        except OSError:
            continue
        total = total - size
        gone = frame_id
        counts["deleted"] = counts["deleted"] + 1

    # empty day folders go too
    for day in os.listdir(root):
        folder = os.path.join(root, day)
        if os.path.isdir(folder) and not os.listdir(folder):
            try:
                os.rmdir(folder)
            except OSError:
                pass

    if gone:
        writer.queue_job("frame_prune", {"max_id": gone})


def saver_loop():
    last_clean = 0.0
    while running:
        try:
            job = jobs.get(timeout=1.0)
        except queue.Empty:
            job = None
        if job is not None:
            try:
                write_one(*job)
            finally:
                jobs.task_done()

        if time.time() - last_clean > CLEANUP_SECONDS:
            last_clean = time.time()
            try:
                cleanup()
            except Exception as err:
                print("[capture] cleanup failed:", err)


def start_saver():
    global running
    if running or not config.SAVE_FRAMES:
        return
    running = True
    t = threading.Thread(target=saver_loop, name="frame-saver", daemon=True)
    t.start()
    print("[capture] saving frames to %s" % config.CAPTURE_DIR)


def stats():
    out = dict(counts)
    out["queued"] = jobs.qsize()
    out["low_disk"] = low_disk
    out["free_mb"] = round(free_mb())
    out["enabled"] = config.SAVE_FRAMES
    return out
