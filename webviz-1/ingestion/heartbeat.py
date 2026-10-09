import threading
import time

import config
from db import store
from ingestion import writer
from live import bus
from video import capture, frames

# the web viz logs that it is working every HEARTBEAT_SECONDS. this is its part
# of the 10 minute operation log before the acceptance test (REQ-M-15)

running = False


def beat_message():
    # one line saying how the web viz is doing, and a level to match
    cap = capture.stats()
    video = "video live" if frames.is_fresh() else "no video"
    text = "running, %d viewers, %s, %s, writer queue %d, frames saved %d, disk free %d MB" % (
        bus.client_count(),
        "mariadb" if store.using_db() else "memory only",
        video,
        writer.stats()["queued"],
        cap["saved"],
        cap["free_mb"],
    )
    level = "warning" if cap["low_disk"] else "info"
    return level, text


def beat_loop():
    writer.send_to_writer("log", {"component": "WVS", "message": "web viz started"})
    while running:
        time.sleep(config.HEARTBEAT_SECONDS)
        try:
            level, text = beat_message()
            writer.send_to_writer("log", {"component": "WVS", "level": level, "message": text})
        except Exception as err:
            # the heartbeat must never take anything else down
            print("[heartbeat] skipped:", err)


def start_heartbeat():
    global running
    if running or config.HEARTBEAT_SECONDS <= 0:
        return
    running = True
    t = threading.Thread(target=beat_loop, name="heartbeat", daemon=True)
    t.start()
