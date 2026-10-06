from datetime import datetime, timedelta

from flask import Blueprint, jsonify, request

import config
from db import store
from ingestion import writer
from live import bus
from video import frames

# all the http endpoints, data in and data out. the json is in the README

api_bp = Blueprint("api", __name__, url_prefix="/api")

TABLES = {
    "reading": "readings",
    "readings": "readings",
    "detection": "detections",
    "detections": "detections",
    "log": "system_log",
    "logs": "system_log",
    "system_log": "system_log",
}

# both spellings, easy to get wrong when writing the sender
KINDS = {
    "reading": "reading",
    "readings": "reading",
    "detection": "detection",
    "detections": "detection",
    "log": "log",
    "logs": "log",
    "drill": "drill",
}


def parse_time(text, fallback):
    # takes an iso string or a unix time, anything else falls back
    if text is None or text.strip() == "":
        return fallback
    text = text.strip()

    try:
        return datetime.fromtimestamp(float(text))
    except ValueError:
        pass

    text = text.replace("Z", "").replace("T", " ")
    for shape in ["%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"]:
        try:
            return datetime.strptime(text, shape)
        except ValueError:
            continue
    return fallback


# data manager, reading out
@api_bp.route("/live")
def live():
    # the same snapshot the sse stream sends on connect
    return jsonify(bus.snapshot())


@api_bp.route("/history")
def history():
    wanted = (request.args.get("type") or "readings").lower()
    if wanted not in TABLES:
        return jsonify({"ok": False,
                        "error": "type must be readings, detections or system_log"}), 400
    table = TABLES[wanted]

    end = parse_time(request.args.get("to"), datetime.now())
    start = parse_time(request.args.get("from"), end - timedelta(minutes=10))
    if start > end:
        start, end = end, start

    limit = config.MAX_HISTORY_ROWS
    try:
        asked = int(request.args.get("limit", limit))
        limit = max(1, min(asked, config.MAX_HISTORY_ROWS))
    except ValueError:
        pass

    rows = store.get_history(table, start, end, limit)
    return jsonify({
        "ok": True,
        "type": table,
        "from": store.to_iso(start),
        "to": store.to_iso(end),
        "count": len(rows),
        "rows": rows,
    })


@api_bp.route("/status")
def status():
    # check the subsystem is alive without opening the dashboard
    return jsonify({
        "ok": True,
        "using_db": store.using_db(),
        "clients": bus.client_count(),
        "payload_ip": config.PAYLOAD_IP,
        "cadence": config.CADENCE_SECONDS,
        "writer": writer.stats(),
        "video": frames.frame_info(),
        "rows": {
            "readings": store.count_rows("readings"),
            "detections": store.count_rows("detections"),
            "system_log": store.count_rows("system_log"),
        },
        "server_time": store.to_iso(datetime.now()),
    })


# ingestion layer, writing in
@api_bp.route("/ingest/<kind>", methods=["POST"])
def ingest(kind):
    # the way into the single writer, json body
    kind = kind.lower()
    if kind not in KINDS:
        return jsonify({"ok": False, "error": "unknown ingest type " + kind}), 404

    msg = request.get_json(silent=True)
    if msg is None and KINDS[kind] == "detection" and request.data.strip() == b"null":
        # the taq has None for a frame with no markers, json null means the same
        msg = []
    if msg is None:
        return jsonify({"ok": False, "error": "body must be json"}), 400

    # the taq posts one list per camera frame, so a detection list is a frame
    if isinstance(msg, list) and KINDS[kind] == "detection":
        return ingest_targets(msg)

    # a subsystem can send a list in one post instead of one at a time
    if isinstance(msg, list):
        return ingest_many(KINDS[kind], msg)

    ok, err = writer.send_to_writer(KINDS[kind], msg)
    if not ok:
        return jsonify({"ok": False, "error": err}), 400
    return jsonify({"ok": True, "accepted": 1}), 202


def ingest_many(kind, items):
    taken = 0
    problems = []
    for i, msg in enumerate(items):
        ok, err = writer.send_to_writer(kind, msg)
        if ok:
            taken = taken + 1
        else:
            problems.append({"index": i, "error": err})

    body = {"ok": len(problems) == 0, "accepted": taken, "rejected": len(problems)}
    if problems:
        body["problems"] = problems[:10]
    if taken == 0:
        return jsonify(body), 400
    return jsonify(body), 202


def ingest_targets(items):
    # an empty list is a frame with nothing in it, that is fine, not an error
    taken, problems = writer.send_targets(items)
    body = {"ok": len(problems) == 0, "accepted": taken, "rejected": len(problems)}
    if problems:
        body["problems"] = problems[:10]
    if taken == 0 and problems:
        return jsonify(body), 400
    return jsonify(body), 202


@api_bp.route("/ingest/frame", methods=["POST"])
def ingest_frame():
    # jpeg frames. skips the writer, goes to the buffer not the database
    data = read_frame_body()
    if data is None:
        return jsonify({"ok": False, "error": "post the jpeg as the body or as a 'frame' file"}), 400

    ok, err = frames.put_frame(data, read_frame_meta())
    if not ok:
        return jsonify({"ok": False, "error": err}), 400

    # tell the dashboards a frame landed
    bus.note_frame(frames.frame_info())
    return jsonify({"ok": True, "bytes": len(data)}), 202


def read_frame_body():
    # raw body is normal, a multipart file is easier to test with curl -F
    if "frame" in request.files:
        return request.files["frame"].read()
    if request.data:
        return request.data
    return None


def read_frame_meta():
    # comes as query string or form fields, only used for the line under the video
    src = {}
    src.update(request.args.to_dict())
    src.update(request.form.to_dict())

    meta = {}
    if "camera" in src:
        meta["camera"] = str(src["camera"])[:32]
    if "model" in src:
        meta["model"] = str(src["model"])[:32]

    for key in ["inference_ms", "conf"]:
        if key in src:
            try:
                meta[key] = float(src[key])
            except ValueError:
                pass

    if "detections" in src:
        try:
            meta["detections"] = int(src["detections"])
        except ValueError:
            pass
    return meta
