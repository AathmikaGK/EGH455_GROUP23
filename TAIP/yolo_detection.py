"""
YOLOv5s valve/gauge detection on the OAK-D Lite VPU (depthai 3.x).

Model: 3 classes (valve_open, valve_closed, gauge), trained at 640x640 on
Roboflow egh455-epcw7-vi0yr v3. Held-out test split: mAP50 0.982.
The blob has three raw output heads. The VPU runs the model; decode() turns the
heads into boxes on the host with ANCHORS below (default YOLOv5 anchors,
AutoAnchor kept them). Training details and the
export script are in TAIP/training/.

add_yolo() hangs the detector off an existing Camera node, so it can share the
camera with the ArUco stream in main.py (only one process can open the OAK-D).
"""
from pathlib import Path
from types import SimpleNamespace

import cv2
import depthai as dai
import numpy as np

BLOB_PATH = str(Path(__file__).parent / "models" / "best_openvino_2022.1_6shave.blob")
INPUT_SIZE = (640, 640)
LABELS = ["valve_open", "valve_closed", "gauge"]
CONFIDENCE_THRESHOLD = 0.5  # tune on live arena footage
IOU_THRESHOLD = 0.5
ANCHORS = [10, 13, 16, 30, 33, 23, 30, 61, 62, 45, 59, 119, 116, 90, 156, 198, 373, 326]
ANCHOR_MASKS = {"side80": [0, 1, 2], "side40": [3, 4, 5], "side20": [6, 7, 8]}  # reference only, decode() uses ANCHORS directly
OUTPUT_NAMES = ["output1_yolov5", "output2_yolov5", "output3_yolov5"]


NN_FPS = 10  # the model tops out around 7.5 fps on the OAK-D Lite at 640


def decode(heads):
    """
    Decode the three raw YOLOv5 heads into depthai-style detections
    (label, confidence, normalised xmin/ymin/xmax/ymax), the same maths
    YOLOv5 uses: sigmoid already applied in the blob, conf = obj * cls,
    then per-class NMS.
    """
    boxes, scores, labels = [], [], []
    nc = len(LABELS)
    for i, head in enumerate(heads):
        stride = 8 * 2 ** i
        ny = nx = INPUT_SIZE[0] // stride
        o = np.asarray(head, dtype=np.float32).reshape(3, 5 + nc, ny, nx).transpose(0, 2, 3, 1)
        anchors = np.array(ANCHORS[i * 6:(i + 1) * 6], dtype=np.float32).reshape(3, 1, 1, 2)
        gy, gx = np.meshgrid(np.arange(ny), np.arange(nx), indexing="ij")
        xy = (o[..., :2] * 2 - 0.5 + np.stack([gx, gy], -1)) * stride
        wh = (o[..., 2:4] * 2) ** 2 * anchors
        conf = o[..., 4:5] * o[..., 5:]
        best, cls = conf.max(-1), conf.argmax(-1)
        keep = best >= CONFIDENCE_THRESHOLD
        for (cx, cy), (w, h), score, c in zip(xy[keep], wh[keep], best[keep], cls[keep]):
            boxes.append([float(cx - w / 2), float(cy - h / 2), float(w), float(h)])
            scores.append(float(score))
            labels.append(int(c))

    detections = []
    for c in range(nc):
        idx = [i for i, label in enumerate(labels) if label == c]
        if not idx:
            continue
        kept = cv2.dnn.NMSBoxes([boxes[i] for i in idx], [scores[i] for i in idx],
                                CONFIDENCE_THRESHOLD, IOU_THRESHOLD)
        for k in np.array(kept).flatten():
            x, y, w, h = boxes[idx[k]]
            detections.append(SimpleNamespace(
                label=c, confidence=scores[idx[k]],
                xmin=x / INPUT_SIZE[0], ymin=y / INPUT_SIZE[1],
                xmax=(x + w) / INPUT_SIZE[0], ymax=(y + h) / INPUT_SIZE[1]))
    return detections


class DetectionQueue:
    """Wraps the raw NN output queue; tryGet() returns an object with .detections like depthai's."""

    def __init__(self, queue):
        self.queue = queue

    def tryGet(self):
        msg = self.queue.tryGet()
        if msg is None:
            return None
        order = dai.TensorInfo.StorageOrder.NCHW
        heads = [msg.getTensor(name, order, dequantize=True) for name in OUTPUT_NAMES]
        return SimpleNamespace(detections=decode(heads))


def add_yolo(pipeline, camera):
    """Add the detector to a pipeline; returns a DetectionQueue (call before pipeline.start())."""
    # STRETCH matches the Roboflow "Stretch to 640x640" preprocessing used in
    # training and keeps the full field of view, so normalised boxes line up
    # with any other full-view output of the same camera (e.g. 640x480).
    # BGR planar matches the blob (converted with --reverse_input_channel).
    nn_input = camera.requestOutput(INPUT_SIZE, type=dai.ImgFrame.Type.BGR888p,
                                    resizeMode=dai.ImgResizeMode.STRETCH, fps=NN_FPS)

    # The model runs on the VPU; its three output heads are decoded on the
    # host (decode() above). depthai 3.10's on-device YOLO parser
    # (DetectionNetwork + detectionParser) crashed the OAK-D with this blob,
    # while the bare NeuralNetwork node ran cleanly, so decoding moved here.
    nn = pipeline.create(dai.node.NeuralNetwork)
    nn.setBlobPath(BLOB_PATH)
    nn.input.setBlocking(False)

    nn_input.link(nn.input)
    return DetectionQueue(nn.out.createOutputQueue(maxSize=4, blocking=False))


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
