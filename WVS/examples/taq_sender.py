"""
example sender for the image processing (taq) subsystem.

reads the oak-d lite, finds aruco markers, and posts every frame with the
targets found in it to the web viz running on the same pi.

    python taq_sender.py --K oak_calibration_matrix_640x480.npy --D oak_distortion_coefficients_640x480.npy

valve and gauge detection are stubs (find_valves, find_gauges) for the team's
own model and gauge reading code. needs: opencv-contrib-python, numpy,
requests, depthai
"""

import argparse
import json
import os
import queue
import threading
import time

import cv2
import numpy as np
import requests

# the web viz is on the same pi, so this never changes with the wi-fi ip
WVS_URL = os.environ.get("WVS_URL", "http://127.0.0.1:8000")

MARKER_SIZE_M = 0.20           # the qut markers are 200 x 200 mm
ARUCO_DICT = cv2.aruco.DICT_5X5_100
JPEG_QUALITY = 70
HEARTBEAT_SECONDS = 10


class WebVizSender:
    # posts frames from a background thread so detection never waits on the network.
    # the queue holds one frame: if the last one is still sending, the new one is skipped

    def __init__(self, url=WVS_URL):
        self.url = url.rstrip("/")
        self.outbox = queue.Queue(maxsize=1)
        self.sent = 0
        self.skipped = 0
        self.failed = 0
        threading.Thread(target=self.run, daemon=True).start()

    def send(self, frame_bgr, targets, captured_at, **extra):
        # call this from the detection loop with the clean frame (no boxes drawn on it)
        ok, jpg = cv2.imencode(".jpg", frame_bgr, [cv2.IMWRITE_JPEG_QUALITY, JPEG_QUALITY])
        if not ok:
            return
        try:
            self.outbox.put_nowait((jpg.tobytes(), targets, captured_at, extra))
        except queue.Full:
            self.skipped += 1

    def run(self):
        session = requests.Session()   # one connection, reused for every frame
        while True:
            jpg, targets, captured_at, extra = self.outbox.get()
            data = {"targets": json.dumps(targets), "captured_at": captured_at}
            data.update(extra)
            try:
                r = session.post(self.url + "/api/ingest/frame",
                                 files={"frame": ("frame.jpg", jpg, "image/jpeg")},
                                 data=data, timeout=0.5)
                body = r.json()
                if body.get("problems"):
                    # a target the web viz did not accept, the message says why
                    print("[wvs] rejected:", body["problems"])
                self.sent += 1
            except (requests.RequestException, ValueError) as err:
                self.failed += 1
                if self.failed % 50 == 1:
                    print("[wvs] could not reach the web viz:", err)

    def log(self, message, level="info"):
        # heartbeat and warnings, they show on the web viz system log page
        try:
            requests.post(self.url + "/api/ingest/log",
                          json={"component": "TAIP", "level": level, "message": message},
                          timeout=0.5)
        except requests.RequestException:
            pass


def find_aruco(frame, K, D, detector):
    # every marker in the frame, in the format the web viz takes
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    corners, ids, _ = detector.detectMarkers(gray)
    if ids is None:
        return []

    half = MARKER_SIZE_M / 2
    object_points = np.array([[-half, half, 0], [half, half, 0],
                              [half, -half, 0], [-half, -half, 0]], dtype=np.float32)
    targets = []
    for c, marker_id in zip(corners, ids.flatten()):
        image_points = c.reshape(4, 2).astype(np.float32)
        ok, rvec, tvec = cv2.solvePnP(object_points, image_points, K, D,
                                      flags=cv2.SOLVEPNP_IPPE_SQUARE)
        if not ok:
            continue

        # tvec = the marker seen from the camera (HLO-M-2).
        # -R^T tvec = the uav (camera) position relative to the marker (HLO-M-3 3b)
        R, _ = cv2.Rodrigues(rvec)
        uav = (-R.T @ tvec).flatten()
        t = tvec.flatten()

        targets.append({
            "type": "aruco",
            "id": int(marker_id),
            "x": float(t[0]), "y": float(t[1]), "z": float(t[2]),
            "uav": {"x": float(uav[0]), "y": float(uav[1]), "z": float(uav[2])},
            "corners": image_points.round(1).tolist(),
        })
    return targets


def find_valves(frame):
    # plug the valve model in here. return a list like
    # [{"type": "valve", "valve_state": "open", "confidence": 0.93, "box": [x1, y1, x2, y2]}]
    return []


def find_gauges(frame):
    # plug the gauge detector and needle reading in here. return a list like
    # [{"type": "gauge", "gauge_value": 1.85, "gauge_units": "bar", "confidence": 0.88, "box": [x1, y1, x2, y2]}]
    return []


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--K", required=True, help="camera matrix .npy from read_oak_calibration.py")
    ap.add_argument("--D", required=True, help="distortion coefficients .npy")
    ap.add_argument("--url", default=WVS_URL, help="web viz address, default " + WVS_URL)
    args = ap.parse_args()

    K = np.load(args.K)
    D = np.load(args.D)
    detector = cv2.aruco.ArucoDetector(cv2.aruco.getPredefinedDictionary(ARUCO_DICT),
                                       cv2.aruco.DetectorParameters())
    wvs = WebVizSender(args.url)

    import depthai as dai   # only needed with the camera plugged in

    with dai.Pipeline() as pipeline:
        camera = pipeline.create(dai.node.Camera).build(dai.CameraBoardSocket.CAM_A)
        # same size as the calibration, so the corner pixels and the pose agree
        frames_out = camera.requestOutput((640, 480), type=dai.ImgFrame.Type.BGR888p).createOutputQueue()
        pipeline.start()

        wvs.log("taq started")
        print("sending to", args.url, "- ctrl+c to stop")
        last_beat = time.time()
        count = 0
        try:
            while pipeline.isRunning():
                frame = frames_out.get().getCvFrame()
                captured_at = time.time()

                start = time.time()
                targets = find_aruco(frame, K, D, detector) + find_valves(frame) + find_gauges(frame)
                inference_ms = (time.time() - start) * 1000

                wvs.send(frame, targets, captured_at,
                         camera="OAK-D Lite RGB", inference_ms=round(inference_ms, 1))

                count += 1
                if time.time() - last_beat >= HEARTBEAT_SECONDS:
                    fps = count / (time.time() - last_beat)
                    wvs.log("running, %.1f fps, sent %d, skipped %d, failed %d"
                            % (fps, wvs.sent, wvs.skipped, wvs.failed))
                    last_beat = time.time()
                    count = 0
        except KeyboardInterrupt:
            pass
        wvs.log("taq stopped")


if __name__ == "__main__":
    main()
