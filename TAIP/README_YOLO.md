# TAIP: YOLO valve/gauge detection

YOLOv5s, 3 classes (`valve_open`, `valve_closed`, `gauge`), runs on the OAK-D
Lite VPU (no Pi CPU inference). Trained at 640x640 on Roboflow
`egh455-epcw7-vi0yr` v4 "real-data-v3 (new valves, no FE)" (extra open/closed
valve images, fire extinguisher images removed), 100 epochs.

Held-out test split (97 images, never used in training):

| Class | mAP50 | mAP50-95 |
|---|---|---|
| all | 0.985 | 0.720 |
| valve_open | 0.995 | 0.612 |
| valve_closed | 0.964 | 0.626 |
| gauge | 0.995 | 0.921 |

The new valve images went mostly into the training split, so these numbers say
little about the demo valves; check those on the Pi. All 28 test gauge boxes
come from one video, so the gauge figure is a small sample.

Previous model (Roboflow v3, 159 test images): all 0.982 / 0.716,
valve_closed 0.955 / 0.585.

## Files

| Path | What |
|---|---|
| `models/best_openvino_2022.1_6shave.blob` | Model for the OAK-D (three raw YOLO heads, decoded on the VPU) |
| `models/best.pt` | PyTorch weights, master copy |
| `yolo_detection.py` | `add_yolo(pipeline, camera)`, `decode()` and `to_targets()`, used by `main-TAIP.py` |
| `detect_oakd.py` | Standalone bench test, prints detections |
| `gauge_processing.py` | Needle reading; `detect_gauge_type()` picks blue/white from the crop colour |
| `training/` | Class-strip script, blob export script, Colab notebook with full log, training curves |

## On the Pi

Requires depthai 3.x (same API as `pose_estimation.py`). The model runs on the
OAK-D; its three output heads are decoded on the Pi in `yolo_detection.decode()`
(depthai 3.10's on-device YOLO parser crashed the camera with this blob).
The model runs at about 7.5 fps on the OAK-D Lite.

Three processes, one SSH window each (all from the repo root):

```bash
# 1. web server (any venv with Flask)
source ~/egh455/bin/activate
cd WVS && WVS_USE_DB=0 python3 app.py        # WVS_USE_DB=0: no MariaDB, rows kept in memory

# 2. air quality + LCD (needs the Enviro+ libraries)
source ~/enviroplus/env/bin/activate
python3 main.py

# 3. camera: ArUco + YOLO + gauge reading -> WVS
source ~/enviroplus/env/bin/activate
python3 main-TAIP.py
```

Bench test of the model alone, prints detections: `python3 -m TAIP.detect_oakd`.
Only one process can open the camera: stop `main-TAIP.py` before running it.

`main-TAIP.py` prints the OAK-D chip temperature every 30 s. The camera has no
fan and shuts down above 105 C; give it airflow on the bench. Both camera
outputs run at `TAIP_CAMERA_FPS` (default 5). Keep them equal: different
rates on the two outputs stalled the pipeline after the first frame.

## How main-TAIP.py uses it

**Auto drill:** after 3 gauge readings in a row below 2.0 bar (`WVS_DRILL_BAR`,
System Requirements), `main-TAIP.py` asks WVS to run the drill once through
`POST /api/drill/activate` (see `EDM/auto_trigger.py`). The servo code itself
goes in `EDM/drill_controller.py`, which is still a placeholder.

One camera, two outputs: 640x480 for ArUco (matches the calibration files),
WVS and display, and 640x640 stretched for YOLO (the same resize used in
training). Both keep the full field of view, so YOLO boxes scale straight
onto the 640x480 frame. Each frame's targets (ArUco markers, valves with
`valve_state`, gauges with `gauge_value`) go to `POST /api/ingest/frame`
every frame by default (`WVS_FRAME_INTERVAL`, default 0); a background
sender drops frames if WVS is slower, so this never adds delay.
`TAIP_SHOW=1` opens a local preview window.

WVS rejects a gauge without a value, so a gauge whose needle can't be read is
left out of that frame.

## To check / tune on real footage

- `CONFIDENCE_THRESHOLD` in `yolo_detection.py` (0.5). valve_closed has the most false positives.
- `BLUE_FRACTION_THRESHOLD` in `gauge_processing.py`: it prints the blue fraction per crop. Set it between the blue and white gauges' values.
- Gauge crops from a 640x480 frame are small. In synthetic tests, reading worked from about 200 px crops; at 120 px the white gauge failed. If real crops are too small, crop gauges from a higher-res camera output.
- Blue gauge needle direction: on a synthetic dial at 7 bar, the blue tip/tail check picked the tail and read 0.33 bar. The original code does the same, so this is not new. Worth testing on real blue-gauge frames across the range.
