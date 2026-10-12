import time
import logging
from gpiozero import Servo

logging.basicConfig(
    level=logging.INFO,
    format='%(levelname)s: %(message)s'
)

SERVO_PIN = 13

def activate_drill():
    logging.info(f"Initiating continuous servo on GPIO {SERVO_PIN}...")

    servo = Servo(SERVO_PIN)

    try:
        logging.info("Running servo forward")
        servo.value = 1.0
        time.sleep(5)

        logging.info("Stopping/reversing servo")
        servo.value = 0.0
        time.sleep(5)

        logging.info("Running servo in reverse")
        servo.value = -1.0
        time.sleep(5)

    except KeyboardInterrupt:
        logging.info("Interrupted by User")

    finally:
        logging.info("Cleaning Up")
        servo.value = None
        servo.close()
        logging.info("Done.")


if __name__ == "__main__":
    activate_drill()
