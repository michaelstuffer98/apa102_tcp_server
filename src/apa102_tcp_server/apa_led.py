import logging
import threading
import time
from typing import List

from apa102_pi.driver import apa102

from apa102_tcp_server.config_laoder import ConfigLoader
from apa102_tcp_server.inet_utils import ServerOperationMode as Mode


class LedStrip:
    # color
    r: float = 0.0
    g: float = 0.0
    b: float = 0.0
    r_desired: float = 0.0
    g_desired: float = 0.0
    b_desired: float = 0.0
    # brightness
    brightness: float = 0.0
    desired_brightness: float = 0.0
    running: bool = False
    # Peak variables
    intensity: float = 0.0
    new_value: bool = False
    peak_table: List[float] = []
    peak_progress: int = 0
    mode: Mode = Mode.NORMAL
    looper_thread: threading.Thread

    def __init__(self, cl: ConfigLoader) -> None:
        # stripe setup
        self.strip = apa102.APA102(num_led=cl['strip.num_led'], mosi=cl['strip.mosi'],
                                   sclk=cl['strip.sclk'], order=cl['strip.color_order'])
        self.strip.set_global_brightness(31)
        self.strip.clear_strip()
        # passed to constructor, stored in seconds
        self.tick_rate: float = cl['visual.tick_rate_ms'] / 1000
        # Update-Thread variables
        self.read_table_file('./data/table_peak')
        self.paused = False
        self.condition_paused = threading.Condition()
        self.r_desired = 100
        self.g_desired = 100
        self.b_desired = 100

        # interpolation step-size in each loop of duration 'tick-rate'
        self.color_interpolation_speed: float = cl['visual.color_interpolation_speed']
        self.brightness_interpolation_speed: float = cl['visual.brightness_interpolation_speed']
        self.color_equal_th: float = cl['visual.color_equal_threshold']
        # peak
        self.peak_step_size: int = cl['visual.peak_step_size']
        self.min_intensity_sound: float = cl['visual.min_intensity_sound']
        # initial values
        self.initial_brightness = cl['visual.initial_brightness']
        self.initial_color = cl['visual.initial_color']

        self.log = logging.getLogger('APA_LED')

    # Worker thread at fixed time interval (synchronous), allows interpolation
    def loop(self) -> None:
        self.log.info('Start LED Looping')
        while self.running:
            counter = 0
            start_time = time.process_time()
            working = self.update()
            if self.paused and not working:
                self.paused = False
                with self.condition_paused:
                    self.condition_paused.wait()
            # Wait until loop time expired, synchronous worker
            while (time.process_time() - start_time) <= self.tick_rate:
                counter = counter + 1
            # Update step took linger than the specified tick_rate
            if counter == 0:
                self.log.warning('tick rate is too fast!')
                if self.mode == Mode.SOUND:
                    self.peak_step_size = self.peak_step_size + 1
                    self.log.info(f' ==> Increased step size ({self.peak_step_size})')
                if self.mode == Mode.NORMAL:
                    # TODO handle too fast loop speed
                    pass
        self.log.info('Stop LED Looping')
        return

    def change_mode(self, mode: Mode) -> None:
        self.mode = mode
        if mode == Mode.BC or mode == Mode.OFF:
            self.stop()
        elif mode == Mode.NORMAL:
            self.start()
            with self.condition_paused:
                self.condition_paused.notify()
        elif mode == Mode.SOUND:
            with self.condition_paused:
                self.condition_paused.notify()

    # Linear interpolation between desired and current value
    def interpolate_brightness(self) -> bool:
        # Avoid toggeling at the end of interpolation
        if abs(self.desired_brightness - self.brightness) <= self.brightness_interpolation_speed:
            # Goto loop pause mode
            self.brightness = self.desired_brightness
            return False
        if self.desired_brightness > self.brightness:
            self.brightness = self.brightness + self.brightness_interpolation_speed
        elif self.desired_brightness < self.brightness:
            self.brightness = self.brightness - self.brightness_interpolation_speed
        return True

    # Linear interpolation between desired and current value
    def interpolate_rgb_color(self) -> bool:
        dif_r = self.r_desired - self.r
        dif_g = self.g_desired - self.g
        dif_b = self.b_desired - self.b
        if dif_r <= self.color_equal_th and dif_g <= self.color_equal_th and dif_b <= self.color_equal_th:
            # Goto loop pause mode
            self.r = self.r_desired
            self.g = self.g_desired
            self.b = self.b_desired
            return False
        self.r = (dif_r) * self.color_interpolation_speed + self.r
        self.g = (dif_g) * self.color_interpolation_speed + self.g
        self.b = (dif_b) * self.color_interpolation_speed + self.b
        return True

    def set_brightness(self, b: int) -> bool:
        self.desired_brightness = (b / 100.0)
        try:
            with self.condition_paused:
                self.condition_paused.notify()
        except RuntimeError:
            # TODO: Log exception occurance
            return False
        return True

    def set_color(self, color: int) -> bool:
        self.r_desired, self.g_desired, self.b_desired = self.get_rgb_from_scaled_color(color, scaled=False)
        try:
            with self.condition_paused:
                self.condition_paused.notify()
        except RuntimeError:
            # TODO: Log exception occurance
            return False
        return True

    # Performs one interpolation step between desired and current LED values and applies changes to the stripe
    def update(self) -> bool:
        working = True
        if self.mode == Mode.NORMAL:
            working = self.interpolate_brightness() or self.interpolate_rgb_color()
            if not working:
                self.paused = True
        elif self.mode == Mode.SOUND:
            if self.peak_progress >= -1:
                self.peak()
            if self.brightness < self.min_intensity_sound:
                self.brightness = self.min_intensity_sound
        self.update_strip()
        return working

    def update_strip(self):
        color = self.get_scaled_color_from_rgb(self.r, self.g, self.b)
        for i in range(1, self.strip.num_led + 1):
            self.strip.set_pixel_rgb(i, color)
        self.strip.show()

    def get_strip_info(self) -> tuple[int, int]:
        return (int(self.desired_brightness), self.get_color_as_int())

    def get_color_as_int(self, scaled: bool = False) -> int:
        r = self.r
        g = self.g
        b = self.b
        if scaled:
            r = r * self.brightness
            g = g * self.brightness
            b = b * self.brightness
        return int(r) + (int(g) << 8) + (int(b) << 16)

    # Convert R, G, B, to a single color Integer value
    # Set scaled=True to apply brightness multiplicator
    def get_scaled_color_from_rgb(self, r: int, g: int, b: int, scaled: bool = True) -> int:
        if scaled:
            r = r * self.brightness
            g = g * self.brightness
            b = b * self.brightness
        return int(r) + (int(g) << 8) + (int(b) << 16)

    # Use scaled property to apply brightness multiplicator
    # Extracts R, G, B from an color integer (without alpha)
    def get_rgb_from_scaled_color(self, color: int, scaled: bool = True) -> tuple[int, int, int]:
        if self.brightness == 0:
            return 0, 0, 0
        r = color & 0xFF
        g = (color & 0xFF00) >> 8
        b = (color & 0xFF0000) >> 16
        if scaled:
            return int(r / self.brightness), int(g / self.brightness), int(b / self.brightness)
        else:
            return int(r), int(g), int(b)

    def stop(self, force_stop: bool = False) -> bool:
        # Reset color LED setup
        self.brightness = self.r = self.g = self.b = 0
        error = False
        self.update_strip()
        # Stop the thread
        self.running = False
        try:
            with self.condition_paused:
                self.condition_paused.notify()
        except RuntimeError:
            # TODO: Log exception
            error = True
        time.sleep(self.tick_rate)
        self.looper_thread = None
        return error

    def get_status(self) -> tuple[str, float, int]:
        return {'modes': self.mode.name,
                'brightness': self.desired_brightness * 100.0,
                'color': self.get_color_as_int()}

    def start(self) -> bool:
        # check if thread is already/still running
        if self.running:
            self.log.warning('Tried to invoke startup, but thread is already running!')
            return True
        # start the thread and initialize values to default
        self.looper_thread = threading.Thread(target=self.loop, name='LED_stripe_updater', args=(), daemon=True)
        self.running = True
        self.looper_thread.start()
        # Init color white
        self.r = self.g = self.b = 0
        self.r_desired, self.g_desired, self.b_desired = self.initial_color
        self.brightness = 0.0
        self.desired_brightness = self.initial_brightness
        return self.looper_thread.is_alive()

    def read_table_file(self, filename: str) -> bool:
        try:
            for line in open(filename, 'r', encoding='utf-8'):
                self.peak_table.append(float(line))
        except OSError:
            self.log.exception('Error while reading in peak table file!')
            return False
        except ValueError:
            self.log.exception("Error while converting peak table file content!")
            return False
        return True

    # interface to publish stream data to strip
    def set_intensity(self, value: int) -> None:
        value_f = value / 100.0
        if value_f > 1.0:
            value_f = 1
        # Peak is not currently executed
        if self.intensity == 0.0:
            self.intensity = value_f
            self.peak_progress = 0
            return
        # Peak is currently, running, update intensity if higher
        if self.brightness < value_f:
            self.intensity = value_f
            self.peak_progress = 0

    def peak(self) -> None:
        self.brightness = self.peak_table[self.peak_progress] * self.intensity
        self.peak_progress = self.peak_progress + self.peak_step_size
        if self.peak_progress >= len(self.peak_table):
            self.intensity = 0.0
            self.peak_progress = -1
        return

    def __str__(self) -> str:
        status = self.get_status()
        return f"Mode: {status['mode']}, Brightness: {status['brightness']}, Color RGB: {status['color']}"

