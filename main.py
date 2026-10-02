from AQ.sensor_controller import SensorController
from AQ.display_controller import DisplayController

import time


def main():

    sensor_controller = SensorController()

    # 0 = IP
    # 1 = Temperature
    # 2 = Image Feed (not implemented)

    display_controller = DisplayController(0)

    while True:

        reading = sensor_controller.get_reading()
        print(reading)

        display_controller.update(reading)

        time.sleep(0.1)


if __name__ == "__main__":
    main()
