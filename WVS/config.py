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

# where the live video comes from. "ingest" (the default) = the image processing
# subsystem posts its frames to /api/ingest/frame, which is how it runs now.
# "device" reads a local camera from video/frames.py; it is kept but off, the
# oak-d lite can only be opened by one program and the taq script owns it
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

# draw the target boxes and labels on each frame. turn off if the taq sends
# frames that already have them drawn
DRAW_BOXES = env("WVS_DRAW_BOXES", "1") == "1"

# saved frames for the image history, one jpeg per kept frame
SAVE_FRAMES = env("WVS_SAVE_FRAMES", "1") == "1"
CAPTURE_DIR = env("WVS_CAPTURE_DIR", os.path.join(os.path.dirname(os.path.abspath(__file__)), "captures"))
# a frame with a target is always kept, a frame without one at most this often.
# 0 keeps only frames with targets
SAVE_IDLE_SECONDS = float(env("WVS_SAVE_IDLE", "1.0"))
CAPTURE_KEEP_HOURS = float(env("WVS_CAPTURE_KEEP_HOURS", "24"))
CAPTURE_MAX_MB = int(env("WVS_CAPTURE_MAX_MB", "2000"))
# stop saving frames when the disk gets this low, the database needs room too
MIN_FREE_MB = int(env("WVS_MIN_FREE_MB", "200"))
CAPTURE_QUEUE = 200
MAX_FRAME_ROWS = 2000

# stuff the dashboard header shows
PAYLOAD_IP = env("WVS_PAYLOAD_IP", "192.168.4.21")
CADENCE_SECONDS = float(env("WVS_CADENCE", "4.0"))

# the drill fires when the gauge drops below this (REQ-F-09)
DRILL_PRESSURE_BAR = float(env("WVS_DRILL_BAR", "2.0"))
# top of the gauge meter on the dashboard, bar
GAUGE_MAX_BAR = float(env("WVS_GAUGE_MAX", "10.0"))

# live data has to reach the web server within this many seconds of capture (REQ-M-19)
AGE_LIMIT_SECONDS = float(env("WVS_AGE_LIMIT", "4.0"))

# the web viz logs that it is alive this often, for the 10 minute operation log
HEARTBEAT_SECONDS = float(env("WVS_HEARTBEAT", "10"))

# what the payload lcd can show, picked from the dashboard (HLO-M-5)
LCD_MODES = ["ip", "detection", "temperature"]

# server
HOST = env("WVS_HOST", "0.0.0.0")
PORT = int(env("WVS_PORT", "8000"))

# safety limits
MAX_HISTORY_ROWS = int(env("WVS_MAX_HISTORY", "5000"))
SSE_QUEUE_SIZE = 100
SSE_PING_SECONDS = 15
