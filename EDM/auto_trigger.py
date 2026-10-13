"""
Starts the drill automatically when the gauge reads below the threshold.

REQ (System Requirements): drill only after landing on the kinetic sand and
once the gauge reads below 2 bar, then retract.

main-TAIP.py feeds every gauge reading into DrillTrigger.update(). After
CONFIRM_READINGS readings in a row below THRESHOLD_BAR (so one misread can't
fire it) it asks WVS to run the drill through POST /api/drill/activate, the
same route as the dashboard button. WVS calls activate_drill() in
drill_controller.py, so only one process ever drives the servo.

The drill fires once per run. Restart main-TAIP.py to arm it again.
"""
import json
import os
import threading
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

THRESHOLD_BAR = float(os.environ.get("WVS_DRILL_BAR", "2.0"))  # same setting WVS shows on the dashboard
CONFIRM_READINGS = int(os.environ.get("DRILL_CONFIRM_READINGS", "3"))
WVS_URL = os.environ.get("WVS_URL", "http://127.0.0.1:8000")
# activate_drill() returns once drilling and retraction are done
DRILL_TIMEOUT_SECONDS = 120


def post(path, body, timeout):
    request = Request(WVS_URL + path, data=json.dumps(body).encode("utf-8"),
                      headers={"Content-Type": "application/json"}, method="POST")
    with urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8") or "{}")


def run_drill(pressure):
    # drill panel on the dashboard: drilling -> done (or an error in the log)
    try:
        post("/api/ingest/drill", {"drill_state": "drilling", "trigger_pressure": round(pressure, 2),
                                   "message": "auto drill: gauge %.2f bar < %.1f bar" % (pressure, THRESHOLD_BAR)}, 2)
        result = post("/api/drill/activate", {}, DRILL_TIMEOUT_SECONDS)
        print("[drill] activate result:", result)
        post("/api/ingest/drill", {"drill_state": "done", "trigger_pressure": round(pressure, 2),
                                   "message": "auto drill finished"}, 2)
    except HTTPError as error:
        print("[drill] WVS refused: %s" % error.read().decode("utf-8", errors="replace"))
    except (URLError, OSError) as error:
        print("[drill] could not reach WVS to run the drill: %s" % error)


class DrillTrigger:

    def __init__(self, start=None):
        self.start = start or (lambda p: threading.Thread(target=run_drill, args=(p,), daemon=True).start())
        self.low_count = 0
        self.fired = False

    def update(self, pressures):
        """pressures: gauge readings (bar) from one frame. Frames with no reading change nothing."""
        if self.fired or not pressures:
            return False
        lowest = min(pressures)
        if lowest < THRESHOLD_BAR:
            self.low_count += 1
        else:
            self.low_count = 0
        if self.low_count >= CONFIRM_READINGS:
            self.fired = True
            print("[drill] gauge %.2f bar < %.1f bar for %d readings: starting drill"
                  % (lowest, THRESHOLD_BAR, self.low_count))
            self.start(lowest)
            return True
        return False


if __name__ == "__main__":
    # self-check of the trigger logic, no WVS needed
    fired = []
    t = DrillTrigger(start=fired.append)
    for frame in [[3.1], [1.5], [], [2.4], [1.9], [1.8], [], [1.7]]:  # misread at 1.5 resets on 2.4
        t.update(frame)
    assert fired == [1.7], fired
    t.update([0.5])
    assert fired == [1.7], "fires only once"
    print("self-check ok")
