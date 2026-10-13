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


def check_frame(data):
    # the error for a bad frame body, None when it is fine
    if not data:
        return "frame body is empty"
    if len(data) > config.FRAME_MAX_BYTES:
        return "frame is bigger than %d bytes" % config.FRAME_MAX_BYTES
    # jpeg files start with these two bytes, catches a sender posting junk
    if data[:2] != b"\xff\xd8":
        return "body does not look like a jpeg"
    return None


def put_frame(data, meta):
    # called by the ingest endpoint. returns (ok, error)
    err = check_frame(data)
    if err:
        return False, err

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


# one colour per target type, bgr because that is what opencv wants
COLOURS = {
    "valve": (230, 120, 20),
    "gauge": (40, 40, 220),
    "aruco": (40, 170, 40),
}
WHITE = (255, 255, 255)
FONT = cv2.FONT_HERSHEY_SIMPLEX if have_cv2 else None
TEXT_SCALE = 0.45
LINE_GAP = 16


def label_lines(row):
    # what gets written next to a target, every number with its unit
    conf = ""
    if row.get("confidence") is not None:
        conf = "  %d%%" % round(row["confidence"] * 100)

    if row["type"] == "valve":
        return ["VALVE %s%s" % (row["valve_state"].upper(), conf)]

    if row["type"] == "gauge":
        return ["GAUGE %.2f %s%s" % (row["gauge_value"], row["gauge_units"] or "bar", conf)]

    lines = ["ARUCO %d" % row["aruco_id"]]
    if row.get("z") is not None:
        lines.append("cam x %.2f y %.2f z %.2f m" % (row["x"] or 0.0, row["y"] or 0.0, row["z"]))
    if row.get("uav_z") is not None:
        lines.append("UAV x %.2f y %.2f z %.2f m" % (row["uav_x"] or 0.0, row["uav_y"] or 0.0, row["uav_z"]))
    return lines


def put_label(img, lines, x, y, colour):
    # filled tag above the point, or below it when there is no room up top
    width = 0
    for line in lines:
        (w, _), _ = cv2.getTextSize(line, FONT, TEXT_SCALE, 1)
        width = max(width, w)
    height = LINE_GAP * len(lines) + 4

    top = y - height - 2
    if top < 0:
        top = y + 2
    x = max(0, min(x, img.shape[1] - width - 8))

    cv2.rectangle(img, (x, top), (x + width + 8, top + height), colour, -1)
    for i, line in enumerate(lines):
        cv2.putText(img, line, (x + 4, top + LINE_GAP * (i + 1) - 2),
                    FONT, TEXT_SCALE, WHITE, 1, cv2.LINE_AA)


def draw_targets(data, rows):
    # boxes and labels on the jpeg the taq sent. the pixels must belong to
    # this exact image. any problem and the frame goes out undrawn
    if not have_cv2 or not rows:
        return data
    img = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        return data

    loose = []
    for row in rows:
        colour = COLOURS.get(row["type"], WHITE)
        lines = label_lines(row)

        if row.get("corners"):
            pts = np.array(row["corners"], np.int32)
            cv2.polylines(img, [pts], True, colour, 2, cv2.LINE_AA)
            put_label(img, lines, int(pts[:, 0].min()), int(pts[:, 1].min()), colour)
        elif row.get("box"):
            x1, y1, x2, y2 = [int(v) for v in row["box"]]
            cv2.rectangle(img, (x1, y1), (x2, y2), colour, 2, cv2.LINE_AA)
            put_label(img, lines, x1, y1, colour)
        else:
            # found but no position sent, still worth saying on the picture
            loose.append((lines, colour))

    # stacked up from the bottom left corner
    y = img.shape[0] - 2
    for lines, colour in reversed(loose):
        put_label(img, lines, 6, y, colour)
        y = y - (LINE_GAP * len(lines) + 8)

    ok, buf = cv2.imencode(".jpg", img, [int(cv2.IMWRITE_JPEG_QUALITY), config.VIDEO_QUALITY])
    if not ok:
        return data
    return buf.tobytes()


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
    # reads a local camera into the same buffer the ingest endpoint fills.
    # disabled for now (WVS_VIDEO_SOURCE=ingest), the image processing
    # subsystem sends the live feed instead. kept for testing with a webcam
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
