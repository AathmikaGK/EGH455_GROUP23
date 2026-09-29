import socket
import colorsys
import time

import st7735

from fonts.ttf import RobotoMedium as UserFont
from PIL import Image, ImageDraw, ImageFont


class DisplayController:

    def __init__(self, initial_mode=0):

        self.mode = initial_mode

        self.last_mode_change = 0
        self.proximity_threshold = 1500
        self.debounce_time = 0.5

        self.display = st7735.ST7735(
            port=0,
            cs=1,
            dc="GPIO9",
            backlight="GPIO12",
            rotation=270,
            spi_speed_hz=10000000
        )

        self.display.begin()

        self.width = self.display.width
        self.height = self.display.height

        self.image = Image.new(
            "RGB",
            (self.width, self.height),
            color=(0, 0, 0)
        )

        self.draw = ImageDraw.Draw(self.image)

        self.font = ImageFont.truetype(
            UserFont,
            20
        )

        self.graph_top = 25

        self.temperature_history = [1] * self.width

    def update(self, reading):

        self._handle_proximity(
            reading["proximity"]
        )

        if self.mode == 0:
            self.show_ip_address()

        elif self.mode == 1:
            self.show_temperature_graph(
                reading["temperature"]
            )
            
        elif self.mode == 2:
            self.show_taq_placeholder()

    def set_mode(self, mode):
        """
        Future web-interface entry point.
        """
        self.mode = mode

    def _handle_proximity(self, proximity):

        if (
            proximity > self.proximity_threshold
            and
            time.time() - self.last_mode_change
            > self.debounce_time
        ):

            self.mode += 1
            self.mode %= 3

            self.last_mode_change = time.time()

    def _get_ip_address(self):

        s = socket.socket(
            socket.AF_INET,
            socket.SOCK_DGRAM
        )

        try:
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
        except Exception:
            ip = "Unavailable"
        finally:
            s.close()

        return ip

    def show_ip_address(self):

        self.draw.rectangle(
            (0, 0, self.width, self.height),
            fill=(0, 0, 0)
        )

        self.draw.text(
            (5, 20),
            "IP Address",
            font=self.font,
            fill=(255, 255, 255)
        )

        self.draw.text(
            (5, 60),
            self._get_ip_address(),
            font=self.font,
            fill=(255, 255, 255)
        )

        self.display.display(self.image)

    def show_temperature_graph(self, temperature):

        self.temperature_history = (
            self.temperature_history[1:]
            + [temperature]
        )

        vmin = min(self.temperature_history)
        vmax = max(self.temperature_history)

        colours = [
            (v - vmin + 1) / (vmax - vmin + 1)
            for v in self.temperature_history
        ]

        self.draw.rectangle(
            (0, 0, self.width, self.height),
            fill=(255, 255, 255)
        )

        for i in range(len(colours)):

            colour = (1.0 - colours[i]) * 0.6

            r, g, b = [
                int(x * 255.0)
                for x in colorsys.hsv_to_rgb(
                    colour,
                    1.0,
                    1.0
                )
            ]

            self.draw.rectangle(
                (i, self.graph_top, i + 1, self.height),
                fill=(r, g, b)
            )

            line_y = (
                self.height
                - (
                    self.graph_top
                    + colours[i]
                    * (self.height - self.graph_top)
                )
                + self.graph_top
            )

            self.draw.rectangle(
                (i, line_y, i + 1, line_y + 1),
                fill=(0, 0, 0)
            )

        self.draw.text(
            (0, 0),
            f"Temp: {temperature:.1f} C",
            font=self.font,
            fill=(0, 0, 0)
        )

        self.display.display(self.image)
        
    def show_taq_placeholder(self):
        
        self.draw.rectangle(
            (0, 0, self.width, self.height),
            fill=(0, 0, 0)
        )
        
        self.draw.text(
            (5, 20),
            "TAQ Feed",
            font=self.font,
            fill=(255, 255, 255)
        )
        
        self.draw.text(
            (5, 60),
            "Unavailable",
            font=self.font,
            fill=(255, 255, 255)
        )
        
        self.display.display(self.image)
