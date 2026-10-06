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
| `component` | VARCHAR(64) | no | who sent it, `drill` for drill events |
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
{ "level": "warning", "component": "nav", "message": "gps fix lost, holding position" }
```

### Drill - `POST /api/ingest/drill`

Stored as a `system_log` row with `component` = `drill`.

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

### Frame - `POST /api/ingest/frame`

Not JSON. The body is a JPEG, max 2 MB (`WVS_FRAME_MAX`). It can be sent as
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
| `GET /api/status` | database in use, clients, writer counters, video, row counts |
| `GET /healthz` | `{"ok": true}` |

## Running

```bash
pip install -r requirements.txt
python -m db.init          # once, needs the MariaDB root login (WVS_DB_ROOT_PASS)
python app.py              # dev server on :8000
```

`WVS_USE_DB=0` keeps everything in memory. All settings are in
[config.py](config.py) and can be set with `WVS_*` environment variables.