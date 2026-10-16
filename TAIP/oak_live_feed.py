import cv2
import depthai as dai

# Create DepthAI pipeline
with dai.Pipeline() as pipeline:

    # Build RGB camera (CAM_A)
    camera = pipeline.create(dai.node.Camera).build(
        dai.CameraBoardSocket.CAM_A
    )

    # Request RGB output at 640 x 480
    rgb_output = camera.requestOutput(
        (640, 480),
        type=dai.ImgFrame.Type.BGR888p
    )

    # Create queue for receiving frames
    rgb_queue = rgb_output.createOutputQueue()

    # Start pipeline
    pipeline.start()

    print("OAK-D Lite live feed started.")
    print("Press Q to quit.")

    while pipeline.isRunning():

        frame_data = rgb_queue.get()
        frame = frame_data.getCvFrame()

        cv2.imshow("OAK-D Lite RGB", frame)

        if cv2.waitKey(1) & 0xFF == ord("q"):
            break

cv2.destroyAllWindows()