import depthai as dai
import numpy as np
import os

# Connect to OAK-D Lite
with dai.Device() as device:

    # Read factory calibration stored in EEPROM
    calib = device.readCalibration()

    # RGB camera on CAM_A
    socket = dai.CameraBoardSocket.CAM_A

    # Read intrinsics for RGB camera
    intrinsics = np.array(
        calib.getCameraIntrinsics(socket, 640, 480)
    )

    # Read distortion coefficients
    distortion = np.array(
        calib.getDistortionCoefficients(socket)
    )

    print("RGB Camera Matrix:")
    print(intrinsics)

    print("\nRGB Distortion Coefficients:")
    print(distortion)

    # Save in the same format your pose_estimation.py already uses
    np.save("oak_calibration_matrix_640x480.npy", intrinsics)
    np.save("oak_distortion_coefficients_640x480.npy", distortion)

    print("\nSaved to:")
    print(os.path.abspath("oak_calibration_matrix_640x480.npy"))
    print(os.path.abspath("oak_distortion_coefficients_640x480.npy"))