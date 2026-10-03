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


def send_reading(reading):
    payload = {
        "temperature": reading["temperature"],
        "humidity": reading["humidity"],
        "pressure": reading["pressure"],
        "light": reading["light"],
        "oxidising_ohms": reading["oxidising"],
        "reducing_ohms": reading["reducing"],
        "ammonia_ohms": reading["nh3"],
    }
    request = Request(
        INGEST_URL,
        data=json.dumps(reading).encode("utf-8"),
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


def main():

    sensor_controller = SensorController()

    # 0 = IP
    # 1 = Temperature
    # 2 = Image Feed (not implemented)

    display_controller = DisplayController(0)
    last_ingest = 0.0

    while True:

        reading = sensor_controller.get_reading()
        print(reading)

        display_controller.update(reading)

        if time.monotonic() - last_ingest >= INGEST_INTERVAL_SECONDS:
            send_reading(reading)
            last_ingest = time.monotonic()

        time.sleep(0.1)


if __name__ == "__main__":
    main()
