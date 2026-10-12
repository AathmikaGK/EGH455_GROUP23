from AQ.sensor_controller import SensorController
from AQ.display_controller import DisplayController
from TAIP.pose_estimation import pose_estimation

import cv2
import depthai as dai
import numpy as np
import json
import os
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


INGEST_URL = os.environ.get(
    "WVS_INGEST_URL", "http://127.0.0.1:8000/api/ingest/reading"
)
INGEST_INTERVAL_SECONDS = float(os.environ.get("WVS_INGEST_INTERVAL", "4.0"))


def send_reading(reading):
    payload = {
        "temperature": reading["temperature"],
        "humidity": reading["humidity"],
        "pressure": reading["pressure"],
        "light": reading["light"],
        "oxidising_ohms": reading["oxidising"],
        "reducing_ohms": reading["reducing"],
        "ammonia_ohms": reading["nh3"],
    }
    request = Request(
        INGEST_URL,
        data=json.dumps(reading).encode("utf-8"),
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


def main():

    sensor_controller = SensorController()

    # ArUCO setup
    k = np.load("TAIP/oak_calibration_matrix_640x480.npy")
    d = np.load("TAIP/oak_distortion_coefficients_640x480.npy")
    aruco_dict_type = cv2.aruco.DICT_5X5_100

    # 0 = IP
    # 1 = Temperature
    # 2 = Image Feed (not implemented)

    display_controller = DisplayController(0)
    last_ingest = 0.0

    # OAK-D Lite camera setup
    with dai.Pipeline() as pipeline:

        camera = pipeline.create(dai.node.Camera).build(
            dai.CameraBoardSocket.CAM_A
        )

        rgb_output = camera.requestOutput(
            (640, 480),
            type=dai.ImgFrame.Type.BGR888p
        )

        rgb_queue = rgb_output.createOutputQueue()

        pipeline.start()
        
        while pipeline.isRunning():

            # Get camera frame
            frame_data = rgb_queue.get()
            frame = frame_data.getCvFrame()

            # Run ArUCO processing
            aruco_output, marker_data = pose_estimation(
                frame.copy(),
                aruco_dict_type,
                k,
                d
            )

            if marker_data:
                print("ArUCO:", marker_data)

            # temporarily display the camera
            cv2.imshow("ArUCO Integration Test", aruco_output)
            if cv2.waitKey(1) & 0xFF == ord("q"):
                break

            # Existing AQ code
            reading = sensor_controller.get_reading()
            print(reading)

            display_controller.update(reading)

            if time.monotonic() - last_ingest >= INGEST_INTERVAL_SECONDS:
                send_reading(reading)
                last_ingest = time.monotonic()

            time.sleep(0.1)
        cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
