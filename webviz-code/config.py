import os

# every setting lives here, each one can be overridden with an environment variable

def env(name, default):
    return os.environ.get(name, default)


# database
DB_HOST = env("WVS_DB_HOST", "localhost")
DB_PORT = int(env("WVS_DB_PORT", "3306"))
DB_USER = env("WVS_DB_USER", "webviz")
DB_PASS = env("WVS_DB_PASS", "webviz")
DB_NAME = env("WVS_DB_NAME", "wvs")

# only db/init.py uses the root login
DB_ROOT_USER = env("WVS_DB_ROOT_USER", "root")
DB_ROOT_PASS = env("WVS_DB_ROOT_PASS", "")

# turn this off to keep everything in memory instead of mariadb
USE_DB = env("WVS_USE_DB", "1") == "1"

# how many rows the memory fallback keeps
MEM_ROWS = int(env("WVS_MEM_ROWS", "20000"))

# frames arrive on /api/ingest/frame, "device" reads a local camera for testing
VIDEO_SOURCE = env("WVS_VIDEO_SOURCE", "ingest")
CAMERA_INDEX = int(env("WVS_CAMERA_INDEX", "0"))
CAMERA_LABEL = env("WVS_CAMERA_LABEL", "CAM 0 - RGB")
VIDEO_FPS = int(env("WVS_VIDEO_FPS", "10"))
VIDEO_WIDTH = int(env("WVS_VIDEO_WIDTH", "640"))
VIDEO_HEIGHT = int(env("WVS_VIDEO_HEIGHT", "480"))
VIDEO_QUALITY = int(env("WVS_VIDEO_QUALITY", "70"))

# stops a broken sender filling up the pi memory
FRAME_MAX_BYTES = int(env("WVS_FRAME_MAX", "2097152"))
# how long before a quiet feed counts as dead
FRAME_STALE_SECONDS = float(env("WVS_FRAME_STALE", "5.0"))

# stuff the dashboard header shows
PAYLOAD_IP = env("WVS_PAYLOAD_IP", "192.168.4.21")
CADENCE_SECONDS = float(env("WVS_CADENCE", "4.0"))

# the drill fires when the gauge reads this or more
DRILL_PRESSURE_BAR = float(env("WVS_DRILL_BAR", "2.0"))

# server
HOST = env("WVS_HOST", "0.0.0.0")
PORT = int(env("WVS_PORT", "8000"))

# safety limits
MAX_HISTORY_ROWS = int(env("WVS_MAX_HISTORY", "5000"))
SSE_QUEUE_SIZE = 100
SSE_PING_SECONDS = 15
