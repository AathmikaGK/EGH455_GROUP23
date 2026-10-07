'''
Put on Terminal - connect camera to pc:-
py pose_estimation.py --K_Matrix oak_calibration_matrix_640x480.npy --D_Coeff oak_distortion_coefficients_640x480.npy --type DICT_5X5_100
'''

# TEMPORARY: calibration_matrix.npy and distortion_coefficients.npy
# are from the example repo.
# Replace with OAK-D Lite EEPROM calibration values during hardware testing.

import numpy as np
import cv2
import sys
from utils import ARUCO_DICT
import argparse
import time
import depthai as dai


def pose_estimation(frame, aruco_dict_type, matrix_coefficients, distortion_coefficients):

    '''
    frame - Frame from the video stream
    matrix_coefficients - Intrinsic matrix of the calibrated camera
    distortion_coefficients - Distortion coefficients associated with your camera

    return:-
    frame - The frame with the axis drawn on it
    '''

    # values used by other subsystems
    detected_markers = []

    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    aruco_dict = cv2.aruco.getPredefinedDictionary(aruco_dict_type)     #new vers
    parameters = cv2.aruco.DetectorParameters()                         #new vers

    detector = cv2.aruco.ArucoDetector(aruco_dict, parameters)

    corners, ids, rejected_img_points = detector.detectMarkers(gray)

    # If markers are detected
    if len(corners) > 0:
        # updated: QUT marker is 200mm = 0.20m
        marker_size = 0.20  # 200 mm = 0.20 m        
        for i in range(0, len(ids)):
            # Estimate pose of each marker and return the values rvec and tvec---(different from those of camera coefficients)

            object_points = np.array([
                [-marker_size / 2,  marker_size / 2, 0],
                [ marker_size / 2,  marker_size / 2, 0],
                [ marker_size / 2, -marker_size / 2, 0],
                [-marker_size / 2, -marker_size / 2, 0]
            ], dtype=np.float32)

            image_points = corners[i].reshape(4, 2).astype(np.float32)

            success, rvec, tvec = cv2.solvePnP(
                object_points,
                image_points,
                matrix_coefficients,
                distortion_coefficients,
                flags=cv2.SOLVEPNP_IPPE_SQUARE
            )

            if not success:
                continue

            # Draw a square around the markers
            cv2.aruco.drawDetectedMarkers(frame, corners) 

            # Draw Axis
            cv2.drawFrameAxes(
                frame,
                matrix_coefficients,
                distortion_coefficients,
                rvec,
                tvec,
                0.10
            )

            # Show Marker ID
            marker_id = int(ids[i])

            corner = corners[i][0]
            top_left = corner[0].astype(int)

            cv2.putText(
                frame,
                str(marker_id),
                (top_left[0], top_left[1] - 10),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.7,
                (0, 255, 0),
                2
            )

            # Output the marker ID and x, y, z position
            x = float(tvec[0][0])
            y = float(tvec[1][0])
            z = float(tvec[2][0])

            detected_markers.append({
                "id": marker_id,
                "x": x,
                "y": y,
                "z": z
            })

            print(
                f"Marker ID: {marker_id} | "
                f"x: {x:.3f} m, y: {y:.3f} m, z: {z:.3f} m"
            )

    return frame, detected_markers

if __name__ == '__main__':

    ap = argparse.ArgumentParser()
    ap.add_argument("-k", "--K_Matrix", required=True, help="Path to calibration matrix (numpy file)")
    ap.add_argument("-d", "--D_Coeff", required=True, help="Path to distortion coefficients (numpy file)")
    ap.add_argument("-t", "--type", type=str, default="DICT_ARUCO_ORIGINAL", help="Type of ArUCo tag to detect")
    args = vars(ap.parse_args())

    
    if ARUCO_DICT.get(args["type"], None) is None:
        print(f"ArUCo tag type '{args['type']}' is not supported")
        sys.exit(0)

    aruco_dict_type = ARUCO_DICT[args["type"]]
    calibration_matrix_path = args["K_Matrix"]
    distortion_coefficients_path = args["D_Coeff"]
    
    k = np.load(calibration_matrix_path)
    d = np.load(distortion_coefficients_path)

    # UNCOMMMENT and REPLACE TO TEST EACH IMAGE - testing on img files
    #frame = cv2.imread("Images/color.png")
    #frame = cv2.imread("Images/test_image_1.png")
    #frame = cv2.imread("Images/generated_aruco_ID0.png")
    #frame = cv2.imread("Images/generated_aruco_ID22.png")
    #if frame is None:
    #    print("Image could not be loaded.")
    #    sys.exit()

    #output, marker_data = pose_estimation(
    #    frame,
    #    aruco_dict_type,
    #    k,
    #    d
    #)
    #print(marker_data)      

    # Live OAK-D Lite feed
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

        print("Live ArUCO pose estimation started.")
        print("Press Q to quit.")

        while pipeline.isRunning():

            frame_data = rgb_queue.get()
            frame = frame_data.getCvFrame()

            gray_test = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

            aruco_dict_test = cv2.aruco.getPredefinedDictionary(
                cv2.aruco.DICT_5X5_100
            )

            params_test = cv2.aruco.DetectorParameters()

            detector_test = cv2.aruco.ArucoDetector(
                aruco_dict_test,
                params_test
            )

            test_corners, test_ids, _ = detector_test.detectMarkers(gray_test)

            print("Detected IDs:", test_ids)

            # Run existing ArUCO pose estimation
            output, marker_data = pose_estimation(
                frame,
                aruco_dict_type,
                k,
                d
            )

            # Print results only when a marker is detected
            if marker_data:
                print(marker_data)

            cv2.imshow("OAK-D Lite ArUCO Pose", output)

            if cv2.waitKey(1) & 0xFF == ord("q"):
                break

    cv2.destroyAllWindows()


    cv2.imshow("Estimated Pose", output)
    cv2.waitKey(0)
    cv2.destroyAllWindows()
    