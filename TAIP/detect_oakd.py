"""
Bench test for the YOLO model on its own: OAK-D Lite -> on-device YOLO -> printed detections.
No window, no WVS, so it works over SSH. Run from the repo root:

    python3 -m TAIP.detect_oakd

Point the camera at a valve and a gauge; expect lines like
    valve_closed conf=0.87 box=(212,140,301,260)
Ctrl+C to stop. Don't run it while main.py is running (one process per camera).
"""
import time

import depthai as dai

try:
    from TAIP.yolo_detection import LABELS, add_yolo
except ImportError:
    from yolo_detection import LABELS, add_yolo

with dai.Pipeline() as pipeline:
    camera = pipeline.create(dai.node.Camera).build(dai.CameraBoardSocket.CAM_A)
    det_queue = add_yolo(pipeline, camera)
    pipeline.start()
    print("YOLO bench test running. Ctrl+C to stop.")

    try:
        while pipeline.isRunning():
            msg = det_queue.tryGet()
            if msg is None:
                time.sleep(0.01)
                continue
            for d in msg.detections:
                print(f"{LABELS[d.label]} conf={d.confidence:.2f} "
                      f"box=({d.xmin * 640:.0f},{d.ymin * 640:.0f},{d.xmax * 640:.0f},{d.ymax * 640:.0f})")
    except KeyboardInterrupt:
        pass
