"""
integration test for the web viz: pretends to be the payload subsystems and
posts to the web viz continuously, the way the real scripts will.

    AQ    sensor readings every second, plus a heartbeat log
    TAIP  camera frames with targets (valve, gauge, aruco), plus a heartbeat
    EDM   drill events. it watches the gauge reading TAIP sends and starts
          drilling when it drops below 2 bar, like the real drill will

every 10 s it prints how many posts each subsystem sent and how fast the web
viz answered. at the end it reads everything back from the web viz and prints
PASS / FAIL for each integration check.

    python examples/integration_test.py                          # all three, 2 minutes
    python examples/integration_test.py --seconds 300            # longer
    python examples/integration_test.py --only edm               # just the drill
    python examples/integration_test.py --only aq,taip --fps 10  # pick subsystems, faster video
    python examples/integration_test.py --url http://<pi ip>     # from another computer

the data goes into the web viz like real data, into mariadb too if it is on.
needs: requests, numpy, opencv-python (pip install requests numpy opencv-python)
"""

import argparse
import json
import math
import random
import statistics
import threading
import time
from datetime import datetime

import cv2
import numpy as np
import requests

DRILL_BAR = 2.0          # the drill fires below this (REQ-F-09)
LAG_LIMIT = 4.0          # data must reach the web viz within 4 s of capture (REQ-M-19)
HEARTBEAT_SECONDS = 10


class Stats:
    # what one subsystem sent and how the web viz answered

    def __init__(self, name):
        self.name = name
        self.lock = threading.Lock()
        self.sent = 0
        self.ok = 0
        self.rejected = 0      # 2xx but some data refused, the reply says why
        self.http_errors = 0   # 4xx / 5xx
        self.no_reply = 0      # could not connect or timed out
        self.times = []        # seconds per request
        self.last_error = ""

    def record(self, seconds, reply=None, error=None):
        with self.lock:
            self.sent += 1
            if error is not None:
                self.no_reply += 1
                self.last_error = str(error)[:120]
                return
            self.times.append(seconds)
            if reply.status_code >= 400:
                self.http_errors += 1
                self.last_error = "%d %s" % (reply.status_code, reply.text[:120])
                return
            try:
                body = reply.json()
            except ValueError:
                body = {}
            if body.get("problems") or body.get("rejected"):
                self.rejected += 1
                self.last_error = json.dumps(body.get("problems"))[:120]
            else:
                self.ok += 1

    def line(self):
        with self.lock:
            ms = [t * 1000 for t in self.times]
            avg = "%.0f" % statistics.mean(ms) if ms else "-"
            worst = "%.0f" % max(ms) if ms else "-"
            return "%-5s sent %5d  ok %5d  rejected %3d  http errors %3d  no reply %3d  avg %4s ms  max %4s ms" % (
                self.name, self.sent, self.ok, self.rejected, self.http_errors, self.no_reply, avg, worst)


class Payload:
    # the shared state the fake subsystems react to, like the real payload

    def __init__(self, base):
        self.base = base.rstrip("/")
        self.stop = threading.Event()
        self.gauge_bar = 2.8
        self.gauge_from_taip = False   # without taip, the drill makes up its own gauge reading
        self.lock = threading.Lock()

    def post(self, session, stats, path, **kwargs):
        start = time.time()
        try:
            reply = session.post(self.base + path, timeout=2, **kwargs)
            stats.record(time.time() - start, reply=reply)
            return reply
        except requests.RequestException as err:
            stats.record(time.time() - start, error=err)
            return None

    def heartbeat(self, session, stats, component, text):
        self.post(session, stats, "/api/ingest/log", json={"component": component, "message": text})


def run_aq(payload, stats, every):
    # the enviro+ board: a reading every `every` seconds, values drifting slowly
    session = requests.Session()
    payload.heartbeat(session, stats, "AQ", "integration test started")
    start = time.time()
    last_beat = start
    while not payload.stop.is_set():
        t = time.time() - start
        payload.post(session, stats, "/api/ingest/reading", json={
            "temperature": round(24 + 1.5 * math.sin(t / 30), 2),
            "pressure": round(1012 + 0.8 * math.sin(t / 60), 1),
            "humidity": round(42 + 4 * math.sin(t / 40), 1),
            "light": round(360 + 40 * math.sin(t / 20)),
            # gas as sensor resistance in ohms, the way AQ's main.py sends it
            "oxidising_ohms": round(21500 + 3000 * math.sin(t / 16)),
            "reducing_ohms": round(312000 + 40000 * math.sin(t / 24)),
            "ammonia_ohms": round(98000 + 12000 * math.sin(t / 18)),
            "captured_at": time.time(),
        })
        if time.time() - last_beat >= HEARTBEAT_SECONDS:
            payload.heartbeat(session, stats, "AQ", "running, readings every %.1f s (test)" % every)
            last_beat = time.time()
        payload.stop.wait(every)


def make_frame():
    # a 640 x 480 scene with a valve, a gauge and aruco marker 7 in it
    img = np.full((480, 640, 3), (70, 75, 80), np.uint8)
    cv2.rectangle(img, (0, 300), (640, 480), (55, 60, 62), -1)
    cv2.rectangle(img, (220, 160), (320, 240), (200, 120, 40), -1)
    cv2.circle(img, (470, 160), 60, (235, 235, 235), -1)
    cv2.line(img, (470, 160), (430, 190), (20, 20, 20), 3)
    marker = cv2.aruco.generateImageMarker(cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_5X5_100), 7, 80)
    img[320:400, 100:180] = cv2.cvtColor(marker, cv2.COLOR_GRAY2BGR)
    ok, jpg = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 70])
    return jpg.tobytes()


def gauge_at(t):
    # the gauge reading t seconds into the test: 2.8 bar falling to 0.8 bar over 40 s, then again
    return round(2.8 - 2.0 * ((t % 40) / 40), 2)


def run_taip(payload, stats, fps):
    # the image processing: every frame with what was found in it.
    # the gauge falls from 2.8 to 0.8 bar over 40 s and starts again, so the drill gets triggered
    session = requests.Session()
    jpg = make_frame()
    payload.heartbeat(session, stats, "TAIP", "integration test started")
    start = time.time()
    last_beat = start
    frame = 0
    while not payload.stop.is_set():
        t = time.time() - start
        gauge = gauge_at(t)
        with payload.lock:
            payload.gauge_bar = gauge

        targets = [{"type": "gauge", "gauge_value": gauge, "gauge_units": "bar",
                    "confidence": 0.86, "box": [406, 96, 534, 224]}]
        if (t % 8) < 6:
            targets.append({"type": "valve", "valve_state": "open" if (t % 60) < 30 else "closed",
                            "confidence": 0.91, "box": [216, 156, 324, 244]})
        if (t % 12) < 10:
            z = 1.2 - 0.2 * math.sin(t / 6)
            x = -0.3 + 0.6 * ((t % 20) / 20)
            targets.append({"type": "aruco", "id": 7, "x": round(x, 3), "y": 0.18, "z": round(z, 3),
                            "uav": {"x": round(-x, 3), "y": -0.18, "z": round(z, 3)},
                            "corners": [[100, 320], [180, 320], [180, 400], [100, 400]]})

        payload.post(session, stats, "/api/ingest/frame",
                     files={"frame": ("frame.jpg", jpg, "image/jpeg")},
                     data={"targets": json.dumps(targets), "captured_at": time.time(),
                           "camera": "OAK-D Lite RGB", "model": "integration test",
                           "inference_ms": round(random.uniform(25, 45), 1)})
        frame += 1
        if time.time() - last_beat >= HEARTBEAT_SECONDS:
            payload.heartbeat(session, stats, "TAIP", "running, %d frames sent (test)" % frame)
            last_beat = time.time()
        payload.stop.wait(1.0 / fps)


def run_edm(payload, stats):
    # the drill: idle until the gauge drops below 2 bar, drills 15 mm over 6 s,
    # reports done, then waits for the gauge to go back above 2 bar before the next hole
    session = requests.Session()

    def event(state, depth, message=None):
        body = {"drill_state": state, "hole_depth": depth, "trigger_pressure": DRILL_BAR}
        if message:
            body["message"] = message
        payload.post(session, stats, "/api/ingest/drill", json=body)

    payload.heartbeat(session, stats, "EDM", "integration test started")
    event("idle", 0.0)
    state = "idle"
    depth = 0.0
    start = time.time()
    last_beat = start
    while not payload.stop.is_set():
        with payload.lock:
            gauge = payload.gauge_bar if payload.gauge_from_taip else gauge_at(time.time() - start)

        if state == "idle" and gauge < DRILL_BAR:
            state = "drilling"
            depth = 0.0
            event(state, depth, "Gauge at %.2f bar, below %.1f bar, drilling started" % (gauge, DRILL_BAR))
        elif state == "drilling":
            depth = round(min(depth + 0.0025, 0.015), 4)
            if depth >= 0.015:
                state = "done"
                event(state, depth, "Hole complete, 15 mm, drill retracted")
            else:
                event(state, depth)
        elif state == "done" and gauge >= DRILL_BAR:
            state = "idle"
            event(state, depth, "Ready for the next sample")

        if time.time() - last_beat >= HEARTBEAT_SECONDS:
            payload.heartbeat(session, stats, "EDM", "running, drill %s (test)" % state)
            last_beat = time.time()
        payload.stop.wait(1.0)


def check(results, name, passed, detail):
    results.append((name, passed, detail))


def verify(base, started, chosen, stats):
    # reads everything back from the web viz to prove the data went through
    results = []
    window = "from=%d&to=%d" % (started - 1, time.time() + 1)

    def get(path):
        reply = requests.get(base + path, timeout=5)
        reply.raise_for_status()
        return reply.json()

    try:
        status = get("/api/status")
    except (requests.RequestException, ValueError) as err:
        check(results, "web viz reachable", False, str(err))
        return results
    check(results, "web viz reachable", True, "database: %s" % ("mariadb" if status.get("using_db") else "memory only"))

    for name, s in stats.items():
        check(results, "%s posts accepted" % name, s.sent > 0 and s.ok == s.sent,
              "%d of %d ok%s" % (s.ok, s.sent, (", last problem: " + s.last_error) if s.last_error else ""))

    logs = get("/api/history?type=system_log&limit=5000&" + window)["rows"]

    if "aq" in chosen:
        rows = get("/api/history?type=readings&limit=5000&" + window)["rows"]
        lags = [r["capture_lag"] for r in rows if r.get("capture_lag") is not None]
        check(results, "AQ readings stored", len(rows) > 0, "%d rows in the test window" % len(rows))
        check(results, "AQ readings within %.0f s of capture" % LAG_LIMIT,
              bool(lags) and max(lags) <= LAG_LIMIT,
              "worst capture lag %.2f s" % max(lags) if lags else "no capture lag recorded")

    if "taip" in chosen:
        rows = get("/api/history?type=detections&limit=5000&" + window)["rows"]
        kinds = sorted(set(r["type"] for r in rows))
        lags = [r["capture_lag"] for r in rows if r.get("capture_lag") is not None]
        check(results, "TAIP detections stored", set(kinds) >= {"valve", "gauge", "aruco"},
              "%d rows, types: %s" % (len(rows), ", ".join(kinds) or "none"))
        check(results, "ArUco UAV position stored", any(r.get("uav_z") is not None for r in rows),
              "uav x, y, z present" if any(r.get("uav_z") is not None for r in rows) else "no uav position")
        check(results, "TAIP detections within %.0f s of capture" % LAG_LIMIT,
              bool(lags) and max(lags) <= LAG_LIMIT,
              "worst capture lag %.2f s" % max(lags) if lags else "no capture lag recorded")
        frames = get("/api/frames?only_targets=1&limit=2000&" + window)
        check(results, "detection images saved", frames["count"] > 0, "%d saved frames with targets" % frames["count"])
        if frames["rows"]:
            image = requests.get(base + frames["rows"][-1]["url"], timeout=5)
            check(results, "saved image can be opened", image.status_code == 200 and image.content[:2] == b"\xff\xd8",
                  "%d bytes" % len(image.content))
        video = status.get("video", {})
        check(results, "live video feed received frames", video.get("total", 0) > 0,
              "%s frames, %.1f fps measured" % (video.get("total"), video.get("fps") or 0))

    if "edm" in chosen:
        drill = [r for r in logs if r.get("drill_state")]
        states = [r["drill_state"] for r in drill]
        check(results, "EDM drill events stored", len(drill) > 0, "%d events" % len(drill))
        check(results, "drill went idle -> drilling -> done", "drilling" in states and "done" in states,
              "states seen: %s" % ", ".join(sorted(set(states))) if states else "none")
        done = [r for r in drill if r["drill_state"] == "done"]
        if done:
            check(results, "hole depth reported", abs((done[-1].get("hole_depth") or 0) - 0.015) < 1e-6,
                  "%.1f mm" % ((done[-1].get("hole_depth") or 0) * 1000))

    for name, component in [("aq", "AQ"), ("taip", "TAIP"), ("edm", "EDM")]:
        if name in chosen:
            beats = [r for r in logs if r.get("component") == component]
            check(results, "%s log messages stored" % component, len(beats) > 0, "%d log rows" % len(beats))

    return results


def main():
    ap = argparse.ArgumentParser(description="continuous http post integration test for the web viz")
    ap.add_argument("--url", default="http://127.0.0.1:8000", help="web viz address")
    ap.add_argument("--seconds", type=int, default=120, help="how long to send for, default 120")
    ap.add_argument("--only", default="aq,taip,edm", help="which subsystems to run, e.g. edm or aq,taip")
    ap.add_argument("--fps", type=float, default=5.0, help="TAIP frames per second, default 5")
    ap.add_argument("--aq-every", type=float, default=1.0, help="seconds between AQ readings, default 1")
    args = ap.parse_args()

    chosen = [c.strip().lower() for c in args.only.split(",") if c.strip()]
    unknown = [c for c in chosen if c not in ["aq", "taip", "edm"]]
    if unknown:
        ap.error("unknown subsystem: %s (use aq, taip, edm)" % ", ".join(unknown))

    base = args.url.rstrip("/")
    try:
        requests.get(base + "/healthz", timeout=3).raise_for_status()
    except requests.RequestException as err:
        print("cannot reach the web viz at %s: %s" % (base, err))
        print("start it first (python app.py), and run this from the same network")
        raise SystemExit(1)

    payload = Payload(base)
    stats = {}
    threads = []
    if "aq" in chosen:
        stats["AQ"] = Stats("AQ")
        threads.append(threading.Thread(target=run_aq, args=(payload, stats["AQ"], args.aq_every), daemon=True))
    if "taip" in chosen:
        payload.gauge_from_taip = True
        stats["TAIP"] = Stats("TAIP")
        threads.append(threading.Thread(target=run_taip, args=(payload, stats["TAIP"], args.fps), daemon=True))
    if "edm" in chosen:
        stats["EDM"] = Stats("EDM")
        threads.append(threading.Thread(target=run_edm, args=(payload, stats["EDM"]), daemon=True))

    started = time.time()
    print("integration test against %s for %d s: %s" % (base, args.seconds, ", ".join(s for s in stats)))
    print("open %s in a browser to watch, ctrl+c stops early" % base)
    print()
    for t in threads:
        t.start()

    try:
        while time.time() - started < args.seconds:
            time.sleep(min(10, max(0.1, args.seconds - (time.time() - started))))
            print("[%s] %3d s" % (datetime.now().strftime("%H:%M:%S"), time.time() - started))
            for s in stats.values():
                print("   " + s.line())
    except KeyboardInterrupt:
        print("stopped early")
    payload.stop.set()
    for t in threads:
        t.join(timeout=3)

    # the web viz writes in the background, give it a moment before reading back
    time.sleep(2)
    print()
    print("checking the web viz has everything")
    results = verify(base, started, chosen, stats)
    failed = 0
    for name, passed, detail in results:
        print("  %s  %-42s %s" % ("PASS" if passed else "FAIL", name, detail))
        failed += 0 if passed else 1
    print()
    print("%d passed, %d failed" % (len(results) - failed, failed))
    raise SystemExit(1 if failed else 0)


if __name__ == "__main__":
    main()
