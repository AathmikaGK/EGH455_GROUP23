from AQ.sensor_controller import SensorController
from AQ.display_controller import DisplayController
from TAIP.pose_estimation import pose_estimation, send_frame_to_webviz
from TAIP.yolo_detection import add_yolo, to_targets
from TAIP.gauge_processing import detect_gauge_type, process_gauge

import cv2
import depthai as dai
import numpy as np
import json
import os
import threading
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


INGEST_URL = os.environ.get(
    "WVS_INGEST_URL", "http://127.0.0.1:8000/api/ingest/reading"
)
INGEST_INTERVAL_SECONDS = float(os.environ.get("WVS_INGEST_INTERVAL", "4.0"))

# camera frame + targets to WVS /api/ingest/frame
FRAME_INTERVAL_SECONDS = float(os.environ.get("WVS_FRAME_INTERVAL", "0.25"))

# TAIP_SHOW=0 for headless runs (SSH without X, systemd on the drone)
SHOW_WINDOW = os.environ.get("TAIP_SHOW", "1") != "0"

FRAME_SIZE = (640, 480)  # matches the ArUco calibration files

# gauge crops smaller than this are too small to read a needle from
MIN_GAUGE_CROP = 40

BOX_COLOURS = {"open": (0, 200, 0), "closed": (0, 0, 255), "gauge": (255, 160, 0)}


def send_reading(reading):
    payload = {
        "temperature": reading["temperature"],
        "humidity": reading["humidity"],
        "pressure": reading["pressure"],
        "light": reading["light"],
        "oxidising_ohms": reading["oxidising"],
        "reducing_ohms": reading["reducing"],
        "ammonia_ohms": reading["nh3"],
        # lets the web viz show how long the reading took to arrive
        "captured_at": time.time(),
    }
    request = Request(
        INGEST_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urlopen(request, timeout=2) as response:
            if response.status != 202:
                print("[webviz] unexpected response: %s" % response.status)
    except HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")
        print("[webviz] rejected reading: %s" % detail)
    except URLError as error:
        print("[webviz] could not send reading: %s" % error.reason)
    except OSError as error:
        # a read timeout is not wrapped in URLError, it must not stop the sensor loop
        print("[webviz] could not send reading: %s" % error)


def aq_loop(stop):
    # AQ sensor, LCD and reading upload run in their own thread so slow
    # sensor reads / HTTP calls don't hold up the camera loop (REQ 4 s lag)

    sensor_controller = SensorController()

    # 0 = IP
    # 1 = Temperature
    # 2 = Image Feed (not implemented)

    # also follows the screen picked on the web interface (see DisplayController._poll_web)
    display_controller = DisplayController(0)
    last_ingest = float("-inf")  # send on the first pass whatever the clock starts at

    while not stop.is_set():
        reading = sensor_controller.get_reading()
        print(reading)

        display_controller.update(reading)

        if time.monotonic() - last_ingest >= INGEST_INTERVAL_SECONDS:
            send_reading(reading)
            last_ingest = time.monotonic()

        time.sleep(0.1)


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

    stop = threading.Event()
    threading.Thread(target=aq_loop, args=(stop,), name="aq", daemon=True).start()

    # ArUCO setup
    k = np.load("TAIP/oak_calibration_matrix_640x480.npy")
    d = np.load("TAIP/oak_distortion_coefficients_640x480.npy")
    aruco_dict_type = cv2.aruco.DICT_5X5_100

    last_frame_sent = float("-inf")  # send on the first pass whatever the clock starts at
    detections = []

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
            type=dai.ImgFrame.Type.BGR888p
        )

        # small non-blocking queue: always process a recent frame instead of
        # falling behind if a loop iteration is slow
        rgb_queue = rgb_output.createOutputQueue(maxSize=4, blocking=False)
        det_queue = add_yolo(pipeline, camera)

        pipeline.start()

        try:
            while pipeline.isRunning():

                # Get camera frame
                frame_data = rgb_queue.get()
                frame = frame_data.getCvFrame()
                captured_at = time.time()

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

                # Send the clean frame and every target to WVS; WVS draws the boxes
                if time.monotonic() - last_frame_sent >= FRAME_INTERVAL_SECONDS:
                    send_frame_to_webviz(frame, marker_data + yolo_targets, captured_at)
                    last_frame_sent = time.monotonic()

                if SHOW_WINDOW:
                    draw_yolo(aruco_output, yolo_targets)
                    cv2.imshow("TAIP: ArUCO + YOLO", aruco_output)
                    if cv2.waitKey(1) & 0xFF == ord("q"):
                        break
        except KeyboardInterrupt:
            pass
        finally:
            stop.set()
            if SHOW_WINDOW:
                cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
