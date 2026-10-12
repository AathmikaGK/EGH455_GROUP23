from TAIP.pose_estimation import pose_estimation, send_frame_to_webviz

import cv2
import depthai as dai
import numpy as np
import time


#ArUCO setup
k = np.load("TAIP/oak_calibration_matrix_640x480.npy")
d = np.load("TAIP/oak_distortion_coefficients_640x480.npy")
aruco_dict_type = cv2.aruco.DICT_5X5_100


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

    print("ArUCO + WEBVIZ test started")
    print("Press Q to quit")

    while pipeline.isRunning():

        frame_data = rgb_queue.get()
        frame = frame_data.getCvFrame()

        captured_at = time.time()

        # Detect ArUCO
        aruco_output, marker_data = pose_estimation(
            frame.copy(),
            aruco_dict_type,
            k,
            d
        )

        if marker_data:
            print("ArUCO:", marker_data)

        # Send EVERY frame to WEBVIZ
        send_frame_to_webviz(
            frame,
            marker_data,
            captured_at
        )

        # Local preview
        cv2.imshow("ArUCO + WEBVIZ Test", aruco_output)

        if cv2.waitKey(1) & 0xFF == ord("q"):
            break


cv2.destroyAllWindows()