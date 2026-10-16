import math

# checks every message before it reaches the database, returns (row, error)

READING_LIMITS = {
    "temperature": (-40.0, 85.0),
    "pressure": (300.0, 1100.0),
    "humidity": (0.0, 100.0),
    "light": (0.0, 100000.0),
    "oxidising_ohms": (0.0, 10000000.0),
    "oxidising_ppm": (0.0, 1000.0),
    "reducing_ohms": (0.0, 10000000.0),
    "reducing_ppm": (0.0, 1000.0),
    "ammonia_ohms": (0.0, 10000000.0),
    "ammonia_ppm": (0.0, 1000.0),
}

DETECTION_TYPES = ["valve", "gauge", "aruco"]
VALVE_STATES = ["open", "closed"]
LOG_LEVELS = ["info", "warning", "error"]
DRILL_STATES = ["idle", "drilling", "done"]

# a pose further than this from the camera is a bad solve, not a marker
POSE_LIMIT_M = 20.0

# box and corner pixels, bigger than any frame the oak sends
PIXEL_LIMIT = 10000


def as_float(msg, key):
    # a number from the message, None if missing or not a number
    if key not in msg or msg[key] is None:
        return None
    try:
        value = float(msg[key])
    except (TypeError, ValueError):
        return None
    # python json lets NaN through and mariadb refuses it, so drop it here
    if not math.isfinite(value):
        return None
    return value


def as_int(msg, key):
    if key not in msg or msg[key] is None:
        return None
    try:
        return int(msg[key])
    except (TypeError, ValueError):
        return None


def as_text(msg, key, limit):
    if key not in msg or msg[key] is None:
        return None
    text = str(msg[key]).strip()
    if text == "":
        return None
    return text[:limit]


def as_time(msg, key):
    # unix seconds from the sender's clock, milliseconds are allowed too.
    # a missing or silly value just means no capture time, not a bad message
    value = as_float(msg, key)
    if value is None:
        return None
    if value > 1e12:
        value = value / 1000.0
    if value < 1e9 or value > 1e10:
        return None
    return value


def in_range(value, low, high):
    return value is None or (low <= value <= high)


def as_pixels(value, count):
    # a flat list of pixel numbers, None if it is not one
    if not isinstance(value, (list, tuple)) or len(value) != count:
        return None
    out = []
    for v in value:
        try:
            v = float(v)
        except (TypeError, ValueError):
            return None
        if not math.isfinite(v) or v < -PIXEL_LIMIT or v > PIXEL_LIMIT:
            return None
        out.append(round(v, 1))
    return out


def check_box(msg):
    # [x1, y1, x2, y2] in pixels of the frame it came with. returns (box, error)
    if msg.get("box") is None:
        return None, None
    box = as_pixels(msg["box"], 4)
    if box is None or box[2] <= box[0] or box[3] <= box[1]:
        return None, "box must be [x1, y1, x2, y2] in pixels, top-left then bottom-right"
    return box, None


def check_corners(msg):
    # the four marker corners from detectMarkers, [[x, y], ...] in pixels
    if msg.get("corners") is None:
        return None, None
    raw = msg["corners"]
    bad = "corners must be four [x, y] pixel points"
    if not isinstance(raw, (list, tuple)) or len(raw) != 4:
        return None, bad
    out = []
    for point in raw:
        pair = as_pixels(point, 2)
        if pair is None:
            return None, bad
        out.append(pair)
    return out, None


def check_uav(msg):
    # the uav position worked out from the marker pose, sent as
    # {"uav": {"x":, "y":, "z":}} or flat uav_x / uav_y / uav_z. returns (xyz, error)
    src = msg.get("uav") if isinstance(msg.get("uav"), dict) else msg
    prefix = "" if src is not msg else "uav_"
    xyz = [as_float(src, prefix + axis) for axis in ["x", "y", "z"]]
    for v in xyz:
        if not in_range(v, -POSE_LIMIT_M, POSE_LIMIT_M):
            return None, "uav position out of range (-%g to %g m)" % (POSE_LIMIT_M, POSE_LIMIT_M)
    return xyz, None


def check_reading(msg):
    if not isinstance(msg, dict):
        return None, "reading must be an object"

    row = {}
    for key in READING_LIMITS:
        row[key] = as_float(msg, key)

    got_one = False
    for key in READING_LIMITS:
        low, high = READING_LIMITS[key]
        if not in_range(row[key], low, high):
            return None, "%s out of range (%g to %g)" % (key, low, high)
        if row[key] is not None:
            got_one = True

    if not got_one:
        return None, "reading has no values in it"
    row["captured_at"] = as_time(msg, "captured_at")
    return row, None


def check_detection(msg):
    if not isinstance(msg, dict):
        return None, "detection must be an object"

    kind = as_text(msg, "type", 16)
    if kind is None and ("aruco_id" in msg or "id" in msg):
        # the taq aruco script sends {"id", "x", "y", "z"} with no type
        kind = "aruco"
    if kind is None:
        return None, "detection needs a type"
    kind = kind.lower()
    if kind not in DETECTION_TYPES:
        return None, "type must be one of " + ", ".join(DETECTION_TYPES)

    row = {
        "type": kind,
        "valve_state": None,
        "gauge_value": None,
        "gauge_units": None,
        "aruco_id": None,
        "x": as_float(msg, "x"),
        "y": as_float(msg, "y"),
        "z": as_float(msg, "z"),
        "confidence": as_float(msg, "confidence"),
        "frame_path": as_text(msg, "frame_path", 255),
        "frame_id": None,
        "captured_at": as_time(msg, "captured_at"),
    }

    if not in_range(row["confidence"], 0.0, 1.0):
        return None, "confidence must be between 0 and 1"

    for axis in ["x", "y", "z"]:
        if not in_range(row[axis], -POSE_LIMIT_M, POSE_LIMIT_M):
            return None, "%s out of range (-%g to %g m)" % (axis, POSE_LIMIT_M, POSE_LIMIT_M)

    # where to draw it on the frame, not stored in the database
    row["box"], err = check_box(msg)
    if err:
        return None, err
    row["corners"], err = check_corners(msg)
    if err:
        return None, err

    uav, err = check_uav(msg)
    if err:
        return None, err
    row["uav_x"], row["uav_y"], row["uav_z"] = uav

    # each target type carries its own extra field
    if kind == "valve":
        state = as_text(msg, "valve_state", 8)
        if state is None:
            return None, "valve detection needs valve_state"
        state = state.lower()
        if state not in VALVE_STATES:
            return None, "valve_state must be open or closed"
        row["valve_state"] = state

    if kind == "gauge":
        value = as_float(msg, "gauge_value")
        if value is None:
            return None, "gauge detection needs gauge_value"
        if not in_range(value, -100.0, 1000.0):
            return None, "gauge_value out of range"
        row["gauge_value"] = value
        row["gauge_units"] = as_text(msg, "gauge_units", 16) or "bar"

    if kind == "aruco":
        marker = as_int(msg, "aruco_id")
        if marker is None:
            marker = as_int(msg, "id")
        if marker is None:
            return None, "aruco detection needs aruco_id (or id)"
        if marker < 0 or marker > 1023:
            return None, "aruco_id out of range"
        row["aruco_id"] = marker

    return row, None


def check_log(msg):
    if not isinstance(msg, dict):
        return None, "log must be an object"

    level = (as_text(msg, "level", 8) or "info").lower()
    if level not in LOG_LEVELS:
        return None, "level must be one of " + ", ".join(LOG_LEVELS)

    component = as_text(msg, "component", 64)
    if component is None:
        return None, "log needs a component"

    text = as_text(msg, "message", 255)
    if text is None:
        return None, "log needs a message"

    drill = as_text(msg, "drill_state", 8)
    if drill is not None:
        drill = drill.lower()
        if drill not in DRILL_STATES:
            return None, "drill_state must be one of " + ", ".join(DRILL_STATES)

    # same limits as check_drill, a log with drill fields updates the drill panel too
    depth = as_float(msg, "hole_depth")
    if not in_range(depth, 0.0, 5.0):
        return None, "hole_depth out of range (0 to 5 m)"

    trigger = as_float(msg, "trigger_pressure")
    if not in_range(trigger, 0.0, 100.0):
        return None, "trigger_pressure out of range"

    row = {
        "level": level,
        "component": component,
        "message": text,
        "drill_state": drill,
        "hole_depth": depth,
        "trigger_pressure": trigger,
        "captured_at": None,
    }
    return row, None


def check_drill(msg):
    # a drill event is a log row with the drill fields filled in
    if not isinstance(msg, dict):
        return None, "drill event must be an object"

    state = as_text(msg, "drill_state", 8)
    if state is None:
        return None, "drill event needs drill_state"
    state = state.lower()
    if state not in DRILL_STATES:
        return None, "drill_state must be one of " + ", ".join(DRILL_STATES)

    depth = as_float(msg, "hole_depth")
    if not in_range(depth, 0.0, 5.0):
        return None, "hole_depth out of range (0 to 5 m)"

    trigger = as_float(msg, "trigger_pressure")
    if not in_range(trigger, 0.0, 100.0):
        return None, "trigger_pressure out of range"

    text = as_text(msg, "message", 255)
    if text is None:
        text = "Drill state changed to " + state

    level = (as_text(msg, "level", 8) or "info").lower()
    if level not in LOG_LEVELS:
        return None, "level must be one of " + ", ".join(LOG_LEVELS)

    row = {
        "level": level,
        "component": "EDM",
        "message": text,
        "drill_state": state,
        "hole_depth": depth,
        "trigger_pressure": trigger,
        "captured_at": None,
    }
    return row, None


def check_message(kind, msg):
    # one door for all the kinds so the writer does not need an if chain
    if kind == "reading":
        return check_reading(msg)
    if kind == "detection":
        return check_detection(msg)
    if kind == "log":
        return check_log(msg)
    if kind == "drill":
        return check_drill(msg)
    return None, "unknown message kind " + str(kind)
