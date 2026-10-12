import json
import sys
from pathlib import Path
from datetime import datetime, timedelta

from flask import Blueprint, jsonify, request

import config
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from EDM.activate_drill import activate_drill
from AQ.display_controller import DisplayController
from db import store
from ingestion import checks, writer
from live import bus
from video import capture, frames

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


def time_range():
    # from / to out of the query string, the last 10 minutes when missing
    end = parse_time(request.args.get("to"), datetime.now())
    start = parse_time(request.args.get("from"), end - timedelta(minutes=10))
    if start > end:
        start, end = end, start
    return start, end


def row_limit(most):
    try:
        asked = int(request.args.get("limit", most))
        return max(1, min(asked, most))
    except ValueError:
        return most


@api_bp.route("/history")
def history():
    wanted = (request.args.get("type") or "readings").lower()
    if wanted not in TABLES:
        return jsonify({"ok": False,
                        "error": "type must be readings, detections or system_log"}), 400
    table = TABLES[wanted]

    start, end = time_range()
    limit = row_limit(config.MAX_HISTORY_ROWS)

    rows = store.get_history(table, start, end, limit)
    return jsonify({
        "ok": True,
        "type": table,
        "from": store.to_iso(start),
        "to": store.to_iso(end),
        "count": len(rows),
        "rows": rows,
    })


@api_bp.route("/frames")
def frame_list():
    # saved frames in a time range for the image history, each with its targets
    start, end = time_range()
    limit = row_limit(config.MAX_FRAME_ROWS)
    only_targets = (request.args.get("only_targets") or "").lower() in ["1", "true", "yes"]

    kind = (request.args.get("type") or "").lower() or None
    if kind is not None and kind not in checks.DETECTION_TYPES:
        return jsonify({"ok": False,
                        "error": "type must be one of " + ", ".join(checks.DETECTION_TYPES)}), 400

    rows = store.get_frames(start, end, limit, only_targets, kind)
    by_frame = {}
    for target in store.get_targets_for([row["id"] for row in rows]):
        by_frame.setdefault(target["frame_id"], []).append(target)
    for row in rows:
        row["url"] = "/frames/%d.jpg" % row["id"]
        row["targets"] = by_frame.get(row["id"], [])

    return jsonify({
        "ok": True,
        "from": store.to_iso(start),
        "to": store.to_iso(end),
        "count": len(rows),
        "rows": rows,
    })


@api_bp.route("/lcd", methods=["GET"])
def lcd_get():
    # the payload asks this to know what its lcd should show (HLO-M-5)
    state = bus.lcd_state()
    state["ok"] = True
    state["modes"] = config.LCD_MODES
    return jsonify(state)


@api_bp.route("/lcd", methods=["POST"])
def lcd_set():
    # the dashboard picks the lcd display, json {"mode": "ip"} or a form field
    msg = request.get_json(silent=True)
    if not isinstance(msg, dict):
        msg = request.form.to_dict()
    mode = str(msg.get("mode") or "").strip().lower()
    if mode not in config.LCD_MODES:
        return jsonify({"ok": False,
                        "error": "mode must be one of " + ", ".join(config.LCD_MODES)}), 400

    state = bus.set_lcd(mode)
    #if mode == "ip":
#	display_controller = DisplayController(0)
 #   elif mode == "temperature":
  #  	display_controller = DisplayController(1)
   # elif mode == "detection":
    #	display_controller = DisplayController(2)

    writer.send_to_writer("log", {"component": "WVS", "message": "payload lcd display set to " + mode})
    sta
    return jsonify(state)


@api_bp.route("/drill/activate", methods=["POST"])
def drill_activate():
    # the dashboard "Activate drill" button. runs the drill straight away, the
    # request returns once activate_drill() has finished
    try:
        activate_drill()
    except Exception as error:
        writer.send_to_writer("log", {"component": "WVS", "level": "error",
                                      "message": "activate drill failed: %s" % error})
        return jsonify({"ok": False, "error": "activate drill failed: %s" % error}), 500

    writer.send_to_writer("log", {"component": "WVS", "message": "drill activated from the dashboard"})
    return jsonify({"ok": True})


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
        "capture": capture.stats(),
        "lcd": bus.lcd_state(),
        "rows": {
            "readings": store.count_rows("readings"),
            "detections": store.count_rows("detections"),
            "system_log": store.count_rows("system_log"),
            "frames": store.count_rows("frames"),
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
    # one camera frame, and optionally the targets found in it. the targets
    # come with the jpeg so the boxes are drawn on the right picture
    data = read_frame_body()
    if data is None:
        return jsonify({"ok": False, "error": "post the jpeg as the body or as a 'frame' file"}), 400
    err = frames.check_frame(data)
    if err:
        return jsonify({"ok": False, "error": err}), 400

    fields = frame_fields()
    given, items, err = read_targets(fields)
    if err:
        return jsonify({"ok": False, "error": err}), 400

    lag = writer.lag_of(checks.as_time(fields, "captured_at"))
    rows, problems = writer.check_targets(items)

    frame_id = capture.next_id()
    keep = capture.should_keep(len(rows) > 0)
    if config.DRAW_BOXES and rows:
        data = frames.draw_targets(data, rows)

    meta = read_frame_meta()
    meta["frame_id"] = frame_id
    meta["capture_lag"] = lag
    if given:
        meta["detections"] = len(rows)
    frames.put_frame(data, meta)

    saved = keep and capture.save(frame_id, data, rows, lag)

    taken = 0
    if given:
        # targets of a frame that is not kept are still logged, just without a picture
        taken, problems = writer.queue_targets(rows, problems, frame_id if saved else None, lag)

    # tell the dashboards a frame landed
    bus.note_frame(frames.frame_info())

    body = {"ok": len(problems) == 0, "bytes": len(data), "frame_id": frame_id, "saved": saved}
    if given:
        body["accepted"] = taken
        body["rejected"] = len(problems)
    if problems:
        body["problems"] = problems[:10]
    return jsonify(body), 202


def frame_fields():
    # the extra fields of a frame post, from the query string or the form
    src = {}
    src.update(request.args.to_dict())
    src.update(request.form.to_dict())
    return src


def read_targets(fields):
    # the 'targets' field is a json list, [] or null for a frame with nothing in it.
    # returns (given, items, error), given is False when the field is not sent at all
    if "targets" not in fields:
        return False, [], None
    raw = fields["targets"].strip()
    if raw in ["", "null", "None"]:
        return True, [], None
    try:
        items = json.loads(raw)
    except ValueError:
        return True, [], "targets must be a json list"
    if items is None:
        items = []
    if isinstance(items, dict):
        items = [items]
    if not isinstance(items, list):
        return True, [], "targets must be a json list"
    return True, items, None


def read_frame_body():
    # raw body is normal, a multipart file is easier to test with curl -F
    if "frame" in request.files:
        return request.files["frame"].read()
    if request.data:
        return request.data
    return None


def read_frame_meta():
    # comes as query string or form fields, only used for the line under the video
    src = frame_fields()

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
