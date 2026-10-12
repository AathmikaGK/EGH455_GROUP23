import time

from bme280 import BME280

try:
    from ltr559 import LTR559
    ltr559 = LTR559()
except ImportError:
    import ltr559

from enviroplus import gas


class SensorInterface:
    def __init__(self):
        self.bme280 = BME280()

    def get_cpu_temperature(self):
        with open("/sys/class/thermal/thermal_zone0/temp", "r") as f:
            return int(f.read()) / 1000.0

    def get_temperature(self):
        factor = 2.25

        cpu_temp = self.get_cpu_temperature()
        raw_temp = self.bme280.get_temperature()

        corrected_temp = raw_temp - (
            (cpu_temp - raw_temp) / factor
        )

        return round(corrected_temp, 2)

    def get_humidity(self):
        return round(self.bme280.get_humidity(), 2)

    def get_pressure(self):
        return round(self.bme280.get_pressure(), 2)

    def get_light(self):
        return round(ltr559.get_lux(), 2)

    def get_proximity(self):
        return ltr559.get_proximity()

    def get_gases(self):
        readings = gas.read_all()

        return {
            "oxidising": round(readings.oxidising, 2),
            "reducing": round(readings.reducing, 2),
            "nh3": round(readings.nh3, 2)
        }

    def read_all(self):
        gases = self.get_gases()

        return {
            "temperature": self.get_temperature(),
            # Pi SoC temperature, shown next to the Enviro reading on the LCD (REQ-U-12)
            "cpu_temperature": round(self.get_cpu_temperature(), 1),
            "humidity": self.get_humidity(),
            "pressure": self.get_pressure(),
            "light": self.get_light(),
            "proximity": self.get_proximity(),
            "oxidising": gases["oxidising"],
            "reducing": gases["reducing"],
            "nh3": gases["nh3"]
        }


if __name__ == "__main__":
    sensor = SensorInterface()

    while True:
        print(sensor.read_all())
        time.sleep(1)