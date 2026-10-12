"""
YOLOv5s valve/gauge detection on the OAK-D Lite VPU (depthai 3.x).

Model: 3 classes (valve_open, valve_closed, gauge), trained at 640x640 on
Roboflow egh455-epcw7-vi0yr v3. Held-out test split: mAP50 0.982.
The blob has three raw output heads; the VPU decodes boxes with ANCHORS below
(default YOLOv5 anchors, AutoAnchor kept them). Training details and the
export script are in TAIP/training/.

add_yolo() hangs the detector off an existing Camera node, so it can share the
camera with the ArUco stream in main.py (only one process can open the OAK-D).
"""
from pathlib import Path

import depthai as dai

BLOB_PATH = str(Path(__file__).parent / "models" / "best_openvino_2022.1_6shave.blob")
INPUT_SIZE = (640, 640)
LABELS = ["valve_open", "valve_closed", "gauge"]
CONFIDENCE_THRESHOLD = 0.5  # tune on live arena footage
IOU_THRESHOLD = 0.5
ANCHORS = [10, 13, 16, 30, 33, 23, 30, 61, 62, 45, 59, 119, 116, 90, 156, 198, 373, 326]
ANCHOR_MASKS = {"side80": [0, 1, 2], "side40": [3, 4, 5], "side20": [6, 7, 8]}


def add_yolo(pipeline, camera):
    """Add the detector to a pipeline; returns its output queue (call before pipeline.start())."""
    # STRETCH matches the Roboflow "Stretch to 640x640" preprocessing used in
    # training and keeps the full field of view, so normalised boxes line up
    # with any other full-view output of the same camera (e.g. 640x480).
    # BGR planar matches the blob (converted with --reverse_input_channel).
    nn_input = camera.requestOutput(INPUT_SIZE, type=dai.ImgFrame.Type.BGR888p,
                                    resizeMode=dai.ImgResizeMode.STRETCH)

    # depthai 3.x has no YoloDetectionNetwork node: YOLO decoding is set on
    # DetectionNetwork's detectionParser instead.
    detector = pipeline.create(dai.node.DetectionNetwork)
    detector.setBlobPath(BLOB_PATH)
    detector.setConfidenceThreshold(CONFIDENCE_THRESHOLD)
    parser = detector.detectionParser
    parser.setNNFamily(dai.DetectionNetworkType.YOLO)
    parser.setSubtype("yolov5")
    parser.setNumClasses(len(LABELS))
    parser.setCoordinateSize(4)
    parser.setAnchors(ANCHORS)
    parser.setAnchorMasks(ANCHOR_MASKS)
    parser.setIouThreshold(IOU_THRESHOLD)
    detector.input.setBlocking(False)

    nn_input.link(detector.input)
    return detector.out.createOutputQueue(maxSize=4, blocking=False)


def to_targets(detections, width, height):
    """
    Turn depthai detections into WVS-style dicts, boxes in pixels of a
    width x height full-view frame:
        {"type": "valve", "valve_state": "open"|"closed", "confidence", "box": [x1, y1, x2, y2]}
        {"type": "gauge", "confidence", "box"}   (caller adds gauge_value)
    """
    targets = []
    for d in detections:
        label = LABELS[d.label]
        box = [
            round(min(max(d.xmin, 0.0), 1.0) * width, 1),
            round(min(max(d.ymin, 0.0), 1.0) * height, 1),
            round(min(max(d.xmax, 0.0), 1.0) * width, 1),
            round(min(max(d.ymax, 0.0), 1.0) * height, 1),
        ]
        if box[2] <= box[0] or box[3] <= box[1]:
            continue
        target = {"type": "gauge" if label == "gauge" else "valve",
                  "confidence": round(float(d.confidence), 3),
                  "box": box}
        if label != "gauge":
            target["valve_state"] = "open" if label == "valve_open" else "closed"
        targets.append(target)
    return targets


if __name__ == "__main__":
    # self-check of the box/label conversion (no camera needed)
    class D:
        def __init__(self, label, conf, x1, y1, x2, y2):
            self.label, self.confidence = label, conf
            self.xmin, self.ymin, self.xmax, self.ymax = x1, y1, x2, y2

    got = to_targets([D(0, .9, .1, .2, .3, .4), D(1, .8, -.1, .5, .2, 1.2),
                      D(2, .7, .5, .5, .75, .75), D(2, .6, .4, .4, .4, .5)], 640, 480)
    assert got == [
        {"type": "valve", "confidence": 0.9, "box": [64.0, 96.0, 192.0, 192.0], "valve_state": "open"},
        {"type": "valve", "confidence": 0.8, "box": [0.0, 240.0, 128.0, 480.0], "valve_state": "closed"},
        {"type": "gauge", "confidence": 0.7, "box": [320.0, 240.0, 480.0, 360.0]},
    ], got
    print("self-check ok")
