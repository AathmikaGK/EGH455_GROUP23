# drill controller (EDM). DF15RSMG 360 (continuous rotation) servo on GPIO 13,
# same wiring and gpiozero calls as the team's servo test script.
#
# activate_drill() is called by the web viz: the dashboard "Activate drill"
# button and the automatic trigger in main-TAIP.py (gauge below 2 bar) both go
# through POST /api/drill/activate, so only the WVS process drives the servo.
#
# REQ: drill a 15 mm deep x 15 mm hole into the kinetic sand, then retract to
# the original position.

import os
import threading
import time

# CALIBRATE on the real mechanism. Which sign drives the tube down, and how
# long gives a 15 mm hole. Retract should run as long as the drill-down so the
# tube ends up back where it started.
SERVO_PIN = int(os.environ.get("DRILL_SERVO_PIN", "13"))
DRILL_SPEED = float(os.environ.get("DRILL_SPEED", "1.0"))        # -1.0 .. 1.0, sign = direction
DRILL_SECONDS = float(os.environ.get("DRILL_SECONDS", "5"))
PAUSE_SECONDS = float(os.environ.get("DRILL_PAUSE_SECONDS", "1"))
RETRACT_SPEED = float(os.environ.get("RETRACT_SPEED", "-1.0"))
RETRACT_SECONDS = float(os.environ.get("RETRACT_SECONDS", "5"))

# one drill run at a time (button pressed twice, or button + auto trigger)
_running = threading.Lock()


def activate_drill():
    # raises if the drill can't run; the dashboard shows the error message
    if not _running.acquire(blocking=False):
        raise RuntimeError("drill is already running")

    servo = None
    try:
        from gpiozero import Servo  # imported here so WVS still starts on a machine without GPIO

        print("[drill] down: speed %.1f for %.1f s on GPIO %d" % (DRILL_SPEED, DRILL_SECONDS, SERVO_PIN))
        servo = Servo(SERVO_PIN)
        servo.value = DRILL_SPEED
        time.sleep(DRILL_SECONDS)

        servo.value = 0.0
        time.sleep(PAUSE_SECONDS)

        print("[drill] retract: speed %.1f for %.1f s" % (RETRACT_SPEED, RETRACT_SECONDS))
        servo.value = RETRACT_SPEED
        time.sleep(RETRACT_SECONDS)

        servo.value = 0.0
        print("[drill] done")
    finally:
        if servo is not None:
            servo.value = None  # stop sending PWM so the servo can't creep
            servo.close()       # release GPIO 13
        _running.release()


if __name__ == "__main__":
    # run the drill once from the command line (stop WVS first, it owns the pin)
    activate_drill()
