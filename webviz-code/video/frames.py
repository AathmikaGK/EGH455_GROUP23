import threading
import time

import config

# holds the newest camera frame and nothing else. never touches mariadb

try:
    import cv2
    import numpy as np
    have_cv2 = True
except ImportError:
    have_cv2 = False

# new frames wake up every open /video_feed connection
changed = threading.Condition()

latest = {
    "jpeg": None,
    "at": 0.0,        # time.time() the frame arrived
    "seq": 0,         # bumped on every frame so watchers know it is a new one
    "total": 0,       # frames since boot
    "fps": 0.0,       # measured, not the configured rate
    "meta": {},       # detections, inference_ms, model, conf from the sender
}

cached = {}
device_running = False


def put_frame(data, meta):
    # called by the ingest endpoint. returns (ok, error)
    if not data:
        return False, "frame body is empty"
    if len(data) > config.FRAME_MAX_BYTES:
        return False, "frame is bigger than %d bytes" % config.FRAME_MAX_BYTES
    # jpeg files start with these two bytes, catches a sender posting junk
    if data[:2] != b"\xff\xd8":
        return False, "body does not look like a jpeg"

    with changed:
        now = time.time()
        gap = now - latest["at"]
        if latest["at"] > 0 and gap > 0:
            latest["fps"] = round(1.0 / gap, 1)

        latest["jpeg"] = data
        latest["at"] = now
        latest["seq"] = latest["seq"] + 1
        latest["total"] = latest["total"] + 1
        latest["meta"] = meta or {}
        changed.notify_all()

    return True, None


def is_fresh():
    return latest["at"] > 0 and (time.time() - latest["at"]) <= config.FRAME_STALE_SECONDS


def frame_info():
    # what the dashboard prints under the video panel
    meta = dict(latest["meta"])
    meta["camera"] = meta.get("camera") or config.CAMERA_LABEL
    meta["live"] = is_fresh()
    meta["fps"] = latest["fps"]
    meta["total"] = latest["total"]
    meta["source"] = config.VIDEO_SOURCE
    if latest["at"] > 0:
        meta["age"] = round(time.time() - latest["at"], 2)
    else:
        meta["age"] = None
    return meta


def wait_for_frame(last_seq, timeout):
    # blocks until a newer frame turns up instead of spinning
    with changed:
        if latest["seq"] == last_seq:
            changed.wait(timeout)
        return latest["seq"], latest["jpeg"]


def placeholder(line1, line2):
    # a status card for when the camera is quiet, no made up video in it
    if not have_cv2:
        return None

    key = line1 + "|" + line2
    if key in cached:
        return cached[key]

    w = config.VIDEO_WIDTH
    h = config.VIDEO_HEIGHT
    img = np.zeros((h, w, 3), dtype=np.uint8)
    img[:, :] = (14, 18, 17)

    cv2.rectangle(img, (20, 20), (w - 20, h - 20), (40, 55, 50), 1)
    cv2.putText(img, line1, (40, h // 2 - 10),
                cv2.FONT_HERSHEY_SIMPLEX, 0.9, (90, 120, 110), 2, cv2.LINE_AA)
    cv2.putText(img, line2, (40, h // 2 + 22),
                cv2.FONT_HERSHEY_SIMPLEX, 0.45, (70, 95, 88), 1, cv2.LINE_AA)
    cv2.putText(img, config.CAMERA_LABEL, (40, 50),
                cv2.FONT_HERSHEY_SIMPLEX, 0.5, (70, 95, 88), 1, cv2.LINE_AA)

    ok, buf = cv2.imencode(".jpg", img, [int(cv2.IMWRITE_JPEG_QUALITY), config.VIDEO_QUALITY])
    if not ok:
        return None
    cached[key] = buf.tobytes()
    return cached[key]


def no_signal():
    if config.VIDEO_SOURCE == "device":
        return placeholder("NO SIGNAL", "camera on index %d is not sending" % config.CAMERA_INDEX)
    return placeholder("NO SIGNAL", "waiting for frames on POST /api/ingest/frame")


def device_loop():
    # testing fallback, pushes into the same buffer the ingest endpoint fills
    cam = cv2.VideoCapture(config.CAMERA_INDEX)
    cam.set(cv2.CAP_PROP_FRAME_WIDTH, config.VIDEO_WIDTH)
    cam.set(cv2.CAP_PROP_FRAME_HEIGHT, config.VIDEO_HEIGHT)
    gap = 1.0 / max(config.VIDEO_FPS, 1)

    while device_running:
        ok, img = cam.read()
        if ok:
            good, buf = cv2.imencode(".jpg", img,
                                     [int(cv2.IMWRITE_JPEG_QUALITY), config.VIDEO_QUALITY])
            if good:
                put_frame(buf.tobytes(), {"camera": config.CAMERA_LABEL})
        time.sleep(gap)

    cam.release()


def start_device():
    global device_running
    if device_running or not have_cv2:
        return
    device_running = True
    t = threading.Thread(target=device_loop, name="camera", daemon=True)
    t.start()
    print("[video] reading camera index %d" % config.CAMERA_INDEX)
