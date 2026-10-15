"""
TAIP process: OAK-D Lite -> ArUco pose + YOLO valves/gauges + gauge reading -> WVS.

Runs alongside main.py (air quality, LCD) and the WVS web server:
    TAIP_SHOW=0 python3 main-TAIP.py
Air quality is not read here, so the two processes never share the
Enviro+ sensors or LCD.
"""
from TAIP.pose_estimation import pose_estimation, send_frame_to_webviz
from TAIP.yolo_detection import add_yolo, to_targets
from TAIP.gauge_processing import detect_gauge_type, process_gauge
from EDM.auto_trigger import DrillTrigger, THRESHOLD_BAR

import cv2
import depthai as dai
import numpy as np
import os
import threading
import time


# camera frame + targets to WVS /api/ingest/frame
FRAME_INTERVAL_SECONDS = float(os.environ.get("WVS_FRAME_INTERVAL", "0.25"))

# TAIP_SHOW=0 for headless runs (SSH without X, systemd on the drone)
SHOW_WINDOW = os.environ.get("TAIP_SHOW", "1") != "0"

FRAME_SIZE = (640, 480)  # matches the ArUco calibration files

# One rate for both camera outputs (frames and YOLO): different rates on two
# outputs of one camera stalled the pipeline after the first frame on the Pi.
# 5 fps is near the model's ~7.5 fps limit, plenty at 2 m/s, and keeps the
# OAK-D cooler (no fan; it shuts down above 105 C).
CAMERA_FPS = float(os.environ.get("TAIP_CAMERA_FPS", "5"))
TEMP_LOG_SECONDS = 30
TEMP_WARN_C = 95.0

# gauge crops smaller than this are too small to read a needle from
MIN_GAUGE_CROP = 40

BOX_COLOURS = {"open": (0, 200, 0), "closed": (0, 0, 255), "gauge": (255, 160, 0)}


class FrameSender:
    """
    Sends frames to WVS from a background thread so the camera loop never
    waits on the upload (WVS decodes, draws, re-encodes and saves each frame
    before it replies). Holds only the newest frame: if WVS is slower than
    the camera, older frames are dropped instead of queuing up delay.
    """

    def __init__(self):
        self.pending = None
        self.ready = threading.Condition()
        self.sent = 0
        threading.Thread(target=self.run, name="wvs-sender", daemon=True).start()

    def put(self, frame, targets, captured_at):
        with self.ready:
            self.pending = (frame, targets, captured_at)
            self.ready.notify()

    def run(self):
        while True:
            with self.ready:
                while self.pending is None:
                    self.ready.wait()
                frame, targets, captured_at = self.pending
                self.pending = None
            send_frame_to_webviz(frame, targets, captured_at)
            self.sent += 1


def read_gauges(frame, targets):
    # adds gauge_value to each YOLO gauge box; WVS rejects a gauge without
    # one, so gauges whose needle can't be read are left out
    kept = []
    height, width = frame.shape[:2]

    for target in targets:
        if target["type"] != "gauge":
            kept.append(target)
            continue

        x1, y1, x2, y2 = target["box"]
        # pad 10% so the whole dial circle is inside the crop
        pad_x, pad_y = (x2 - x1) * 0.1, (y2 - y1) * 0.1
        x1, y1 = int(max(0, x1 - pad_x)), int(max(0, y1 - pad_y))
        x2, y2 = int(min(width, x2 + pad_x)), int(min(height, y2 + pad_y))
        crop = frame[y1:y2, x1:x2]

        if min(crop.shape[:2]) < MIN_GAUGE_CROP:
            print("Gauge too small to read: %dx%d px" % (crop.shape[1], crop.shape[0]))
            continue

        gauge_type = detect_gauge_type(crop)
        _, pressure = process_gauge(crop, gauge_type)

        if pressure is None:
            continue

        target["gauge_value"] = round(float(pressure), 2)
        target["gauge_units"] = "bar"
        kept.append(target)

    return kept


def draw_yolo(image, targets):
    for target in targets:
        x1, y1, x2, y2 = [int(v) for v in target["box"]]
        key = target.get("valve_state", "gauge")
        text = key if key == "gauge" else "valve " + key
        if "gauge_value" in target:
            text += " %.2f bar" % target["gauge_value"]
        cv2.rectangle(image, (x1, y1), (x2, y2), BOX_COLOURS[key], 2)
        cv2.putText(image, "%s %.2f" % (text, target["confidence"]), (x1, max(15, y1 - 6)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, BOX_COLOURS[key], 2)


def main():

    # ArUCO setup
    k = np.load("TAIP/oak_calibration_matrix_640x480.npy")
    d = np.load("TAIP/oak_distortion_coefficients_640x480.npy")
    aruco_dict_type = cv2.aruco.DICT_5X5_100

    last_frame_sent = float("-inf")  # send on the first pass whatever the clock starts at
    last_temp_log = float("-inf")
    detections = []
    drill = DrillTrigger()
    sender = FrameSender()
    loops = 0
    last_rates = (time.monotonic(), 0, 0)

    # OAK-D Lite camera setup: one camera, two outputs
    #   640x480 frames for ArUco (calibrated size), WVS and display
    #   640x640 stretched input for YOLO on the VPU (see TAIP/yolo_detection.py)
    # Both keep the full field of view, so YOLO's normalised boxes map
    # straight onto the 640x480 frame.
    with dai.Pipeline() as pipeline:

        camera = pipeline.create(dai.node.Camera).build(
            dai.CameraBoardSocket.CAM_A
        )

        rgb_output = camera.requestOutput(
            FRAME_SIZE,
            type=dai.ImgFrame.Type.BGR888p,
            fps=CAMERA_FPS
        )

        # small non-blocking queue: always process a recent frame instead of
        # falling behind if a loop iteration is slow
        rgb_queue = rgb_output.createOutputQueue(maxSize=4, blocking=False)
        det_queue = add_yolo(pipeline, camera, fps=CAMERA_FPS)

        pipeline.start()
        device = pipeline.getDefaultDevice()
        print("TAIP running: ArUco + YOLO -> WVS. Drill fires below %.1f bar. Ctrl+C to stop." % THRESHOLD_BAR)

        try:
            while pipeline.isRunning():

                if time.monotonic() - last_temp_log >= TEMP_LOG_SECONDS:
                    chip_c = device.getChipTemperature().average
                    print("[OAK-D] chip temperature %.0f C%s" % (
                        chip_c, "  -- TOO HOT, check airflow" if chip_c >= TEMP_WARN_C else ""))
                    # loop rate vs frames actually delivered to WVS since the last log
                    then, loops_then, sent_then = last_rates
                    span = max(time.monotonic() - then, 1e-6)
                    print("[TAIP] loop %.1f fps, sent to WVS %.1f fps" % (
                        (loops - loops_then) / span, (sender.sent - sent_then) / span))
                    last_rates = (time.monotonic(), loops, sender.sent)
                    last_temp_log = time.monotonic()

                # Get camera frame
                frame_data = rgb_queue.get()
                frame = frame_data.getCvFrame()
                captured_at = time.time()
                loops += 1

                # ponytail: newest YOLO result is paired with this frame, may be
                # one frame apart; sync on sequence numbers if boxes visibly lag
                det_msg = det_queue.tryGet()
                if det_msg is not None:
                    detections = det_msg.detections

                # Run ArUCO processing
                aruco_output, marker_data = pose_estimation(
                    frame.copy(),
                    aruco_dict_type,
                    k,
                    d
                )

                if marker_data:
                    print("ArUCO:", marker_data)

                # Valves / gauges from YOLO, gauge needle read on the crop
                yolo_targets = read_gauges(frame, to_targets(detections, *FRAME_SIZE))

                if yolo_targets:
                    print("YOLO:", yolo_targets)

                # Auto drill once the gauge stays below the threshold
                drill.update([t["gauge_value"] for t in yolo_targets if "gauge_value" in t])

                # Send the clean frame and every target to WVS; WVS draws the boxes
                if time.monotonic() - last_frame_sent >= FRAME_INTERVAL_SECONDS:
                    sender.put(frame, marker_data + yolo_targets, captured_at)
                    last_frame_sent = time.monotonic()

                if SHOW_WINDOW:
                    draw_yolo(aruco_output, yolo_targets)
                    cv2.imshow("TAIP: ArUCO + YOLO", aruco_output)
                    if cv2.waitKey(1) & 0xFF == ord("q"):
                        break
        except KeyboardInterrupt:
            pass
        finally:
            if SHOW_WINDOW:
                cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
