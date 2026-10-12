from AQ.sensor_controller import SensorController
from AQ.display_controller import DisplayController

import json
import os
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


INGEST_URL = os.environ.get(
    "WVS_INGEST_URL", "http://127.0.0.1:8000/api/ingest/reading"
)
INGEST_INTERVAL_SECONDS = float(os.environ.get("WVS_INGEST_INTERVAL", "4.0"))

LCD_URL = os.environ.get("WVS_LCD_URL", "http://127.0.0.1:8000/api/lcd")
LCD_POLL_SECONDS = float(os.environ.get("WVS_LCD_POLL", "2.0"))

# web interface lcd choice -> DisplayController mode
LCD_MODES = {"ip": 0, "temperature": 1, "detection": 2}


def fetch_lcd_choice():
    """
    The LCD display picked on the web interface, as (mode, changed),
    or None when the web viz cannot be reached.
    """
    try:
        with urlopen(LCD_URL, timeout=0.5) as response:
            state = json.loads(response.read().decode("utf-8"))
    except (OSError, ValueError):
        return None

    return state.get("mode"), state.get("changed")


def send_reading(reading):
    payload = {
        "temperature": reading["temperature"],
        "humidity": reading["humidity"],
        "pressure": reading["pressure"],
        "light": reading["light"],
        "oxidising_ohms": reading["oxidising"],
        "reducing_ohms": reading["reducing"],
        "ammonia_ohms": reading["nh3"],
        # lets the web viz show how long the reading took to arrive
        "captured_at": time.time(),
    }
    request = Request(
        INGEST_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urlopen(request, timeout=2) as response:
            if response.status != 202:
                print("[webviz] unexpected response: %s" % response.status)
    except HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")
        print("[webviz] rejected reading: %s" % detail)
    except URLError as error:
        print("[webviz] could not send reading: %s" % error.reason)
    except OSError as error:
        # a read timeout is not wrapped in URLError, it must not stop the sensor loop
        print("[webviz] could not send reading: %s" % error)


def main():

    sensor_controller = SensorController()

    # 0 = IP
    # 1 = Temperature
    # 2 = Image Feed (not implemented)

    display_controller = DisplayController(0)
    last_ingest = 0.0
    last_lcd_poll = 0.0
    last_lcd_change = None

    while True:

        # a new pick on the web interface sets the lcd once, the proximity
        # sensor can still cycle it after that
        if time.monotonic() - last_lcd_poll >= LCD_POLL_SECONDS:
            choice = fetch_lcd_choice()
            last_lcd_poll = time.monotonic()

            if choice is not None:
                mode, changed = choice
                if changed is not None and changed != last_lcd_change and mode in LCD_MODES:
                    display_controller.set_mode(LCD_MODES[mode])
                    last_lcd_change = changed
                    print("[webviz] lcd set to %s" % mode)

        reading = sensor_controller.get_reading()
        print(reading)

        display_controller.update(reading)

        if time.monotonic() - last_ingest >= INGEST_INTERVAL_SECONDS:
            send_reading(reading)
            last_ingest = time.monotonic()

        time.sleep(0.1)


if __name__ == "__main__":
    main()
