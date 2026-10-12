import socket
import colorsys
import time
import json
import os
from urllib.request import urlopen

import st7735

from fonts.ttf import RobotoMedium as UserFont
from PIL import Image, ImageDraw, ImageFont


# Web viz endpoint holding the LCD screen picked on the dashboard (HLO-M-5).
# Defaults to the WVS server on this Pi. WVS_LCD_URL points it elsewhere.
LCD_URL = os.environ.get("WVS_LCD_URL", "http://127.0.0.1:8000/api/lcd")
LCD_POLL_SECONDS = float(os.environ.get("WVS_LCD_POLL", "2.0"))

# WVS names the screens, this class numbers them. Maps a name from
# GET /api/lcd to the mode used by update().
LCD_MODES = {"ip": 0, "temperature": 1, "detection": 2}


class DisplayController:

    def __init__(self, initial_mode=0):

        self.mode = initial_mode

        self.last_mode_change = 0
        self.proximity_threshold = 1500
        self.debounce_time = 0.5

        # Time of the last GET /api/lcd, so the web viz is asked every
        # LCD_POLL_SECONDS rather than on every 0.1 s update().
        self.last_lcd_poll = 0.0
        # "changed" timestamp of the last dashboard pick already applied. Each
        # pick is applied once, so the proximity sensor can still cycle after it.
        self.last_lcd_change = None

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

        # Smaller font so the Enviro and Pi temperatures fit as two lines
        # above the graph on the 160x80 screen.
        self.small_font = ImageFont.truetype(
            UserFont,
            14
        )

        # Graph starts below the two temperature lines (2 x 15 px + gap).
        self.graph_top = 32

        self.temperature_history = [1] * self.width

    def update(self, reading):

        # Apply a dashboard pick before the proximity check, so a hand wave
        # in the same cycle still takes priority.
        self._poll_web()

        self._handle_proximity(
            reading["proximity"]
        )

        if self.mode == 0:
            self.show_ip_address()

        elif self.mode == 1:
            self.show_temperature_graph(
                reading["temperature"],
                reading.get("cpu_temperature")
            )
            
        elif self.mode == 2:
            self.show_taq_placeholder()

    def set_mode(self, mode):
        """
        Future web-interface entry point.
        """
        self.mode = mode

    def _fetch_lcd_choice(self):
        """
        The LCD screen picked on the web interface, as (mode, changed),
        or None when the web viz cannot be reached.
        """
        try:
            # 0.5 s timeout: if WVS hangs, the LCD loop stalls for at most half a second.
            with urlopen(LCD_URL, timeout=0.5) as response:
                state = json.loads(response.read().decode("utf-8"))
        except (OSError, ValueError):
            # WVS not running, unreachable or sent bad JSON.
            return None

        return state.get("mode"), state.get("changed")

    def _poll_web(self):
        """
        Every LCD_POLL_SECONDS, switches to the screen picked on the web
        dashboard if it is a new pick. "changed" is None until someone picks,
        so at start-up the LCD keeps initial_mode.
        """
        if time.monotonic() - self.last_lcd_poll < LCD_POLL_SECONDS:
            return

        choice = self._fetch_lcd_choice()
        self.last_lcd_poll = time.monotonic()

        if choice is None:
            # Keep showing the current screen while WVS is unavailable.
            return

        mode, changed = choice
        # Same timestamp means the pick was already applied; an unknown
        # screen name is ignored.
        if changed is not None and changed != self.last_lcd_change and mode in LCD_MODES:
            self.set_mode(LCD_MODES[mode])
            self.last_lcd_change = changed
            print("[webviz] lcd set to %s" % mode)

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

    def show_temperature_graph(self, temperature, cpu_temperature=None):

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

        # Both temperatures required on the LCD (REQ-U-12, HLO-M-5): the
        # calibrated Enviro air temperature, which the graph tracks, and the
        # Pi SoC temperature. "--" if the Pi value is missing from the reading.
        self.draw.text(
            (2, 0),
            f"Enviro: {temperature:.1f} C",
            font=self.small_font,
            fill=(0, 0, 0)
        )

        pi_text = "--" if cpu_temperature is None else f"{cpu_temperature:.1f} C"
        self.draw.text(
            (2, 15),
            f"Pi CPU: {pi_text}",
            font=self.small_font,
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
