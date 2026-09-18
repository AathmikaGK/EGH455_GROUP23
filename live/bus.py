import json
import queue
import threading
import time
from datetime import datetime

import config
from db import store
from video import frames

# the live push channel, every new row goes straight out to the browsers

lock = threading.Lock()
clients = []

# whatever the dashboard needs to paint itself the moment it connects
latest = {
    "reading": None,
    "valve": None,
    "gauge": None,
    "aruco": {},
    "drill": None,
    "log": None,
    "updated": None,
    "updated_at": None,   # time.time() the last row landed, used for "quiet"
}

LOG_KEEP = 25
recent_logs = []


def to_json_row(row):
    # datetimes cannot go into json so the ts becomes a string here
    return store.clean_row(row)


def remember(kind, row):
    # keeps the snapshot up to date so a new client sees numbers straight away
    item = to_json_row(row)

    if kind == "reading":
        latest["reading"] = item
    elif kind == "detection":
        if item["type"] == "aruco":
            # one entry per marker id, newest wins
            latest["aruco"][str(item["aruco_id"])] = item
        elif item["type"] == "valve":
            latest["valve"] = item
        else:
            latest["gauge"] = item
    else:
        latest["log"] = item
        recent_logs.append(item)
        if len(recent_logs) > LOG_KEEP:
            del recent_logs[0]
        if item["drill_state"] is not None:
            latest["drill"] = item

    latest["updated"] = item["ts"]
    latest["updated_at"] = time.time()
    return item


def publish(kind, row):
    with lock:
        item = remember(kind, row)
        send_to_all(make_event(kind, item))


def note_frame(meta):
    # frames get no database row, this just says one landed
    with lock:
        send_to_all(make_event("frame", meta))


def send_to_all(packet):
    # caller already holds the lock
    dead = []
    for q in clients:
        try:
            q.put_nowait(packet)
        except queue.Full:
            # a browser that cannot keep up gets cut off
            dead.append(q)
    for q in dead:
        clients.remove(q)


def make_event(name, data):
    # the sse wire format, event name then one data line then a blank line
    return "event: %s\ndata: %s\n\n" % (name, json.dumps(data))


def snapshot():
    with lock:
        markers = []
        for key in sorted(latest["aruco"], key=int):
            markers.append(latest["aruco"][key])
        return {
            "reading": latest["reading"],
            "valve": latest["valve"],
            "gauge": latest["gauge"],
            "aruco": markers,
            "drill": latest["drill"],
            "logs": list(recent_logs),
            "frame": frames.frame_info(),
            "samples": store.count_rows("readings"),
            "updated": latest["updated"],
            # seconds since the last row, so an old database does not look live
            "quiet": quiet_seconds(),
            "server_time": store.to_iso(datetime.now()),
            "payload_ip": config.PAYLOAD_IP,
            "cadence": config.CADENCE_SECONDS,
            "drill_bar": config.DRILL_PRESSURE_BAR,
            "using_db": store.using_db(),
        }


def quiet_seconds():
    if latest["updated_at"] is None:
        return None
    return round(time.time() - latest["updated_at"], 2)


def subscribe():
    q = queue.Queue(maxsize=config.SSE_QUEUE_SIZE)
    with lock:
        clients.append(q)
    return q


def unsubscribe(q):
    with lock:
        if q in clients:
            clients.remove(q)


def client_count():
    with lock:
        return len(clients)


def feed(q):
    # blocks on the queue so a new row goes out the moment it is published
    yield make_event("snapshot", snapshot())
    last_ping = time.time()
    while True:
        try:
            yield q.get(timeout=1.0)
        except queue.Empty:
            pass
        # a comment line every so often keeps proxies from closing the socket
        if time.time() - last_ping > config.SSE_PING_SECONDS:
            last_ping = time.time()
            yield ": ping\n\n"
