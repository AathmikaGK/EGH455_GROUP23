# WVS - Web Visualisation Subsystem

Flask dashboard for the UAV payload ground station. Received data is pushed live to the dashboard over Server-Sent Events (`/stream`). Camera
frames skip the database and are streamed as MJPEG on `/video_feed`.

subsystem --POST json--> /api/ingest/<type> --> checks --> writer queue --> MariaDB (or memory)
\--> SSE /stream --> dashboard
camera    --POST jpeg--> /api/ingest/frame  --> latest frame buffer --> MJPEG /video_feed

## Database schema

Database `wvs` (MariaDB, InnoDB, utf8mb4), created by `python -m db.init` from
[db/schema.sql](db/schema.sql). The app logs in as `webviz` with
SELECT/INSERT/UPDATE/DELETE only. If MariaDB is not reachable the same rows are kept in memory (last `WVS_MEM_ROWS` per table, default 20000).

Every table has a `ts DATETIME(3)` column. It is stamped by the Pi when the
message arrives, so senders do not send a time.

### `readings` - air quality from the Enviro+ board

| Column | Type | Null | Unit / notes |

| `id` | BIGINT AUTO_INCREMENT | no | primary key |
| `ts` | DATETIME(3) | no | arrival time, indexed (`idx_readings_ts`) |
| `temperature` | FLOAT | yes | degrees C |
| `pressure` | FLOAT | yes | hPa |
| `humidity` | FLOAT | yes | % RH |
| `light` | FLOAT | yes | lux |
| `oxidising_ohms` | FLOAT | yes | raw resistance, ohms |
| `oxidising_ppm` | FLOAT | yes | estimated ppm |
| `reducing_ohms` | FLOAT | yes | ohms |
| `reducing_ppm` | FLOAT | yes | ppm |
| `ammonia_ohms` | FLOAT | yes | ohms |
| `ammonia_ppm` | FLOAT | yes | ppm |

### `detections` - one row per target found by the detection subsystem

| Column | Type | Null | Unit / notes |

| `id` | BIGINT AUTO_INCREMENT | no | primary key |
| `ts` | DATETIME(3) | no | arrival time, indexed |
| `type` | ENUM('valve','gauge','aruco') | no | default `aruco`, indexed with `ts` (`idx_detections_type_ts`) |
| `valve_state` | ENUM('open','closed') | yes | valve rows only |
| `gauge_value` | FLOAT | yes | gauge rows only |
| `gauge_units` | VARCHAR(16) | yes | gauge rows only, defaults to `bar` |
| `aruco_id` | INT | yes | aruco rows only, the TAQ's `id`, indexed with `ts` (`idx_detections_aruco_ts`) |
| `x` | DOUBLE | yes | metres, camera frame, right |
| `y` | DOUBLE | yes | metres, camera frame, down |
| `z` | DOUBLE | yes | metres, camera frame, distance out of the lens |
| `confidence` | FLOAT | yes | 0 to 1 |
| `frame_path` | VARCHAR(255) | yes | optional path of the saved frame |

Every marker in one TAQ frame is one row, and all rows of a frame share the
same `ts`. A frame with no markers writes no row. Running `python -m db.init`
again updates a `detections` table made from the old schema (FLOAT x/y/z
become DOUBLE, the `aruco_id` index is added); no rows are lost.

### `system_log` - messages from any subsystem, also carries the drill state

| Column | Type | Null | Unit / notes |

| `id` | BIGINT AUTO_INCREMENT | no | primary key |
| `ts` | DATETIME(3) | no | arrival time, indexed |
| `level` | ENUM('info','warning','error') | no | default `info`, indexed with `ts` |
| `component` | VARCHAR(64) | no | who sent it: `WVS`, `AQ`, `TAIP` or `EDM` (`EDM` for drill events) |
| `message` | VARCHAR(255) | no | |
| `drill_state` | ENUM('idle','drilling','done') | yes | set on drill events |
| `hole_depth` | FLOAT | yes | metres |
| `trigger_pressure` | FLOAT | yes | bar |

## Ingestion - JSON the subsystems send

All ingestion is `POST` with `Content-Type: application/json`, to
`http://<pi>/api/ingest/<kind>`. The body is either **one object** or **a list
of objects** of the same kind (batch). Unknown fields are ignored. Numbers may
be sent as JSON numbers or numeric strings. Do not send a timestamp, the Pi adds
it.

| Kind | URL | Stored in |

| reading | `/api/ingest/reading` | `readings` |
| detection | `/api/ingest/detection` | `detections` |
| log | `/api/ingest/log` | `system_log` |
| drill | `/api/ingest/drill` | `system_log` (component `drill`) |
| frame | `/api/ingest/frame` | not stored, JPEG body (see below) |

### Reading - `POST /api/ingest/reading`

Every field is optional but at least one must be present. Values outside the
range are rejected.

| Field | Type | Range |

| `temperature` | number | -40 to 85 |
| `pressure` | number | 300 to 1100 |
| `humidity` | number | 0 to 100 |
| `light` | number | 0 to 100000 |
| `oxidising_ohms`, `reducing_ohms`, `ammonia_ohms` | number | 0 to 10000000 |
| `oxidising_ppm`, `reducing_ppm`, `ammonia_ppm` | number | 0 to 1000 |

```json
{
  "temperature": 24.3,
  "pressure": 1012.6,
  "humidity": 41.2,
  "light": 356.0,
  "oxidising_ohms": 21540.0,
  "oxidising_ppm": 0.82,
  "reducing_ohms": 312000.0,
  "reducing_ppm": 2.10,
  "ammonia_ohms": 98000.0,
  "ammonia_ppm": 0.64
}
```

### Detection - `POST /api/ingest/detection`

#### TAQ ArUco frames

The TAQ posts the marker list it prints, as it is, once per camera frame:

```json
[{ "id": 22, "x": 0.020056089636047512, "y": -0.05093316065253747, "z": 0.48600508787079516 }]
```

- `id` is taken as `aruco_id`, and a missing `type` means `aruco`.
- A list of ArUco markers is **the whole view**. Markers that were in the last
  frame but not this one show as lost on the dashboard.
- A frame with nothing in it (`Detected IDs: None`) is sent as `[]` or `null`.
  It writes no row but clears the view. Send it, otherwise the dashboard keeps
  the old markers until they go stale (3 s).
- `x`, `y`, `z` must be within -20 to 20 m. NaN is rejected.

```python
import requests
# markers is the list the script prints, or None when nothing was detected
requests.post("http://<pi>/api/ingest/detection", json=markers or [], timeout=0.5)
```

#### All detection fields

| Field | Type | Required | Notes |

| `type` | string | no | `valve`, `gauge` or `aruco`. Defaults to `aruco` when `id`/`aruco_id` is sent |
| `valve_state` | string | if `type` = valve | `open` or `closed` |
| `gauge_value` | number | if `type` = gauge | -100 to 1000 |
| `gauge_units` | string | no | max 16 chars, default `bar` |
| `aruco_id` (or `id`) | integer | if `type` = aruco | 0 to 1023 |
| `x`, `y`, `z` | number | no | metres, -20 to 20 |
| `confidence` | number | no | 0 to 1 |
| `frame_path` | string | no | max 255 chars |

Fields that belong to another type are ignored (a valve row never stores a
`gauge_value`).

```json
{ "type": "valve", "valve_state": "open", "confidence": 0.93 }
```

```json
{ "type": "gauge", "gauge_value": 2.4, "gauge_units": "bar", "confidence": 0.88 }
```

```json
{ "type": "aruco", "aruco_id": 7, "x": 0.412, "y": -0.035, "z": 1.207, "confidence": 0.99 }
```

### Log - `POST /api/ingest/log`

| Field | Type | Required | Notes |
| `component` | string | yes | max 64 chars |
| `message` | string | yes | max 255 chars |
| `level` | string | no | `info` (default), `warning`, `error` |
| `drill_state` | string | no | `idle`, `drilling`, `done` |
| `hole_depth` | number | no | metres, 0 to 5 |
| `trigger_pressure` | number | no | bar, 0 to 100 |

A log that includes `drill_state` also updates the drill panel. Prefer the
drill endpoint below for drill events.

```json
{ "level": "warning", "component": "AQ", "message": "gas sensor warming up" }
```

### Drill - `POST /api/ingest/drill`

Stored as a `system_log` row with `component` = `EDM`.

| Field | Type | Required | Notes |
| `drill_state` | string | yes | `idle`, `drilling`, `done` |
| `hole_depth` | number | no | metres, 0 to 5 (the dashboard shows mm) |
| `trigger_pressure` | number | no | bar, 0 to 100. The gauge mark follows this; if missing, `WVS_DRILL_BAR` is used |
| `message` | string | no | default `drill state <drill_state>` |
| `level` | string | no | `info` (default), `warning`, `error` |

Send a new event on every state change. Each event replaces the one before on
the dashboard, so include `hole_depth` and `trigger_pressure` every time you
know them.

```json
{ "drill_state": "drilling", "hole_depth": 0.045, "trigger_pressure": 2.0 }
```

```json
{ "drill_state": "done", "hole_depth": 0.120, "trigger_pressure": 2.0, "message": "hole complete" }
```

### Batch

Any of the JSON kinds can be sent as a list. A detection list is one camera
frame: its rows share one `ts`, and if it holds only ArUco markers it also sets
which markers are in view.

```json
[
  { "type": "valve", "valve_state": "closed", "confidence": 0.9 },
  { "type": "aruco", "aruco_id": 3, "x": 0.1, "y": 0.2, "z": 1.1 }
]
```

### Frame + targets - `POST /api/ingest/frame` (what the TAQ should send)

One request per camera frame: the JPEG and the targets found in it, together,
so the boxes are drawn on the right picture. Send it as multipart form data:

| Part | Type | Required | Notes |
|---|---|---|---|
| `frame` | JPEG file | yes | the 640 x 480 image the pixels below belong to, max 2 MB |
| `targets` | JSON text | no | list of targets in this frame, `[]` when nothing was seen. Leave the field out for a frame-only post |
| `captured_at` | number | recommended | unix seconds when the frame was grabbed, for the 4 s check (REQ-M-19). The payload clock must be synced to the web viz |
| `camera`, `model`, `inference_ms` | | no | shown under the video |

Each target takes the detection fields below plus where it is in the image:

| Field | For | Notes |
|---|---|---|
| `box` | valve, gauge | `[x1, y1, x2, y2]` pixels, top-left then bottom-right |
| `corners` | aruco | the four `[x, y]` pixel corners from `detectMarkers` |
| `uav` | aruco | `{"x":, "y":, "z":}` metres, the UAV position w.r.t. the marker (or flat `uav_x`, `uav_y`, `uav_z`) |

```python
targets = [{"type": "valve", "valve_state": "open", "confidence": 0.93, "box": [212, 140, 318, 251]},
           {"id": 7, "x": 0.41, "y": -0.03, "z": 1.21, "uav": {"x": -0.38, "y": 0.12, "z": 1.17},
            "corners": [[101, 300], [161, 302], [159, 361], [99, 359]]}]
ok, jpg = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 70])
requests.post("http://<web viz>:8000/api/ingest/frame",
              files={"frame": ("f.jpg", jpg.tobytes(), "image/jpeg")},
              data={"targets": json.dumps(targets), "captured_at": time.time()},
              timeout=0.5)
```

The web viz draws the boxes and labels (turn off with `WVS_DRAW_BOXES=0` if the
TAQ draws them itself), streams the frame on `/video_feed`, logs every target
in `detections` with the frame's id, and saves the frame for the image history.
A bad target is rejected and listed in `problems`; the frame still goes through.
The reply is `{"ok", "bytes", "frame_id", "saved", "accepted", "rejected"}`.

`captured_at` is also accepted on readings and detections sent as JSON, and is
stored as `capture_lag` (seconds from capture to arrival).

### Frame only

The body can also be just a JPEG, max 2 MB (`WVS_FRAME_MAX`), sent as
the raw body (`Content-Type: image/jpeg`) or as a multipart file field named
`frame`. Optional details go in the query string or form fields and are shown
under the video:

| Field | Type | Notes |

| `camera` | string | label, max 32 chars |
| `model` | string | detector model name, max 32 chars |
| `inference_ms` | number | |
| `conf` | number | |
| `detections` | integer | detections in this frame |

```bash
curl -X POST "http://<pi>/api/ingest/frame?camera=CAM0&model=yolov8n&inference_ms=41&detections=2" \
     -H "Content-Type: image/jpeg" --data-binary @frame.jpg
```

### Responses

| Case | Status | Body |

| accepted | 202 | `{"ok": true, "accepted": 1}` (frame: `{"ok": true, "bytes": 48213}`) |
| batch, some rejected | 202 | `{"ok": false, "accepted": 4, "rejected": 1, "problems": [{"index": 2, "error": "..."}]}` |
| failed check / not JSON / all rejected | 400 | `{"ok": false, "error": "valve_state must be open or closed"}` |
| unknown kind | 404 | `{"ok": false, "error": "unknown ingest type ..."}` |

If the writer queue (2000 messages) is full, the message is rejected with
`writer queue is full` and not written, so the sender is never blocked.

## Reading data out

| Endpoint | What it returns |

| `GET /` | the dashboard |
| `GET /stream` | SSE: `snapshot` on connect, then `reading`, `detection`, `aruco_view` (ids in the last TAQ frame), `log`, `frame` events |
| `GET /video_feed` | MJPEG stream of the latest frame, "NO SIGNAL" card when quiet |
| `GET /api/live` | the same snapshot `/stream` sends on connect |
| `GET /api/history?type=readings\|detections\|system_log&from=&to=&limit=` | rows in a time range, oldest first. `from`/`to` are ISO or unix time, default the last 10 minutes, `limit` max 5000 |
| `GET /api/frames?from=&to=&only_targets=1&type=valve\|gauge\|aruco&limit=` | saved frames in a time range with their `url` and `targets`, `limit` max 2000 |
| `GET /frames/<id>.jpg` | one saved frame |
| `GET /api/lcd` | the LCD display the operator picked (`ip`, `detection`, `temperature`). The payload polls this (HLO-M-5) |
| `POST /api/lcd` | `{"mode": "temperature"}`, what the dashboard selector sends |
| `GET /api/status` | database in use, clients, writer counters, video, saved frames, row counts |
| `GET /healthz` | `{"ok": true}` |

## Running

```bash
pip install -r requirements.txt
python -m db.init          # once, needs the MariaDB root login (WVS_DB_ROOT_PASS)
python app.py              # dev server on :8000
```

To check everything works, with sample data for every subsystem:

```bash
bash examples/test_webviz.sh                              # PASS/FAIL for every endpoint
bash examples/test_webviz.sh http://127.0.0.1:8000 stream   # no checks, 2 min of live sample data to watch
```

To test the integration the way the payload will use it, with AQ, TAIP and EDM
posting at the same time and the drill reacting to the gauge:

```bash
python examples/integration_test.py                 # all three for 2 minutes, then PASS/FAIL checks
python examples/integration_test.py --only edm      # one subsystem: aq, taip or edm
```

`WVS_USE_DB=0` keeps everything in memory. All settings are in
[config.py](config.py) and can be set with `WVS_*` environment variables.
After pulling this version, run `python -m db.init` again: it adds the new
columns (`uav_x/y/z`, `frame_id`, `capture_lag`) and the `frames` table without
losing rows.

| Setting | Default | What it does |
|---|---|---|
| `WVS_DRAW_BOXES` | `1` | draw target boxes and labels on frames |
| `WVS_SAVE_FRAMES` | `1` | save frames for the image history, in `WVS_CAPTURE_DIR` (`captures/`) |
| `WVS_SAVE_IDLE` | `1.0` | frames with targets are always saved, others at most this often (s). `0` = targets only |
| `WVS_CAPTURE_KEEP_HOURS` / `WVS_CAPTURE_MAX_MB` | `24` / `2000` | old frames are deleted past either limit |
| `WVS_MIN_FREE_MB` | `200` | stop saving frames below this much free disk |
| `WVS_DRILL_BAR` | `2.0` | the drill fires when the gauge drops **below** this (REQ-F-09) |
| `WVS_GAUGE_MAX` | `10.0` | top of the gauge meter, bar |
| `WVS_AGE_LIMIT` | `4.0` | capture lag over this shows red (REQ-M-19) |
| `WVS_HEARTBEAT` | `10` | seconds between web viz "running" log rows (REQ-M-15) |