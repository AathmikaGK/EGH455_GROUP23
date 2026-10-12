# TAIP: YOLO valve/gauge detection

YOLOv5s, 3 classes (`valve_open`, `valve_closed`, `gauge`), runs on the OAK-D
Lite VPU (no Pi CPU inference). Trained at 640x640 on Roboflow
`egh455-epcw7-vi0yr` v3, 100 epochs.

Held-out test split (159 images, never used in training):

| Class | mAP50 | mAP50-95 |
|---|---|---|
| all | 0.982 | 0.716 |
| valve_open | 0.995 | 0.620 |
| valve_closed | 0.955 | 0.585 |
| gauge | 0.995 | 0.943 |

All 28 test gauge boxes come from one video, so the gauge figure is a small sample.

## Files

| Path | What |
|---|---|
| `models/best_openvino_2022.1_6shave.blob` | Model for the OAK-D (three raw YOLO heads, decoded on the VPU) |
| `models/best.pt` | PyTorch weights, master copy |
| `yolo_detection.py` | `add_yolo(pipeline, camera)` and `to_targets()`, used by `main.py` |
| `detect_oakd.py` | Standalone bench test, prints detections |
| `gauge_processing.py` | Needle reading; `detect_gauge_type()` picks blue/white from the crop colour |
| `training/` | Class-strip script, blob export script, Colab notebook with full log, training curves |

## On the Pi

Requires depthai 3.x (same API as `pose_estimation.py`). From the repo root:

```bash
source ~/egh455/bin/activate
python3 -c "import depthai; print(depthai.__version__)"

# 1. model alone, works over SSH
python3 -m TAIP.detect_oakd

# 2. everything: AQ + ArUco + YOLO + gauge reading -> WVS
#    start WVS first (see WVS/README.md); TAIP_SHOW=0 if there's no screen
TAIP_SHOW=0 python3 main.py
```

Only one process can open the camera: stop `main.py` before running `detect_oakd.py`.

## How main.py uses it

One camera, two outputs: 640x480 for ArUco (matches the calibration files),
WVS and display, and 640x640 stretched for YOLO (the same resize used in
training). Both keep the full field of view, so YOLO boxes scale straight
onto the 640x480 frame. Each frame's targets (ArUco markers, valves with
`valve_state`, gauges with `gauge_value`) go to `POST /api/ingest/frame`
every `WVS_FRAME_INTERVAL` seconds (default 0.25).

WVS rejects a gauge without a value, so a gauge whose needle can't be read is
left out of that frame.

## To check / tune on real footage

- `CONFIDENCE_THRESHOLD` in `yolo_detection.py` (0.5). valve_closed has the most false positives.
- `BLUE_FRACTION_THRESHOLD` in `gauge_processing.py`: it prints the blue fraction per crop. Set it between the blue and white gauges' values.
- Gauge crops from a 640x480 frame are small. In synthetic tests, reading worked from about 200 px crops; at 120 px the white gauge failed. If real crops are too small, crop gauges from a higher-res camera output.
- Blue gauge needle direction: on a synthetic dial at 7 bar, the blue tip/tail check picked the tail and read 0.33 bar. The original code does the same, so this is not new. Worth testing on real blue-gauge frames across the range.
