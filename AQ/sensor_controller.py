from AQ.sensor_interface import SensorInterface
from datetime import datetime


class SensorController:

    def __init__(self):
        self.sensor_interface = SensorInterface()

    def get_reading(self):
        """
        Retrieve a complete sensor sample and
        package it into a standard format.
        """

        data = self.sensor_interface.read_all()

        return {
            "timestamp": datetime.now().isoformat(),
            "temperature": data["temperature"],
            "cpu_temperature": data["cpu_temperature"],
            "humidity": data["humidity"],
            "pressure": data["pressure"],
            "light": data["light"],
            "proximity": data["proximity"],
            "oxidising": data["oxidising"],
            "reducing": data["reducing"],
            "nh3": data["nh3"]
        }
