#!/usr/bin/env python3
import json
from apa102_pi.driver import apa102
import time
import threading
from inet_utils import ServerOperationMode as Mode

class LedStrip:
    # color
    r: float = 0.0
    g: float = 0.0
    b: float = 0.0
    r_desired: float = 0.0
    g_desired: float = 0.0
    b_desired: float = 0.0
    # brightness
    brightness = 0.0
    desired_brightness = 0.0
    running: bool = False
    # Peak variables
    intensity: float = 0.0
    new_value: bool = False
    peak_table = []
    peak_progress: int = 0
    peak_Step_size: int = 1
    min_intensity_sound: float = 0.05
    mode: Mode = Mode.NORMAL
    looper_thread = threading.Thread
    # interpolation step-size in each loop of duration 'tick-rate'
    color_interpolation_speed = 0.075
    brightness_interpolation_speed = 0.01
    condition_paused = threading.Condition()


    def __init__(self, tick_rate_ms=10, num_led=120):
        # stripe setup
        self.strip = apa102.APA102(num_led=num_led, mosi=10, sclk=11, order='rgb')
        self.strip.set_global_brightness(31)
        self.strip.clear_strip()
        # passed to constructor, stored in seconds
        self.tick_rate: float = tick_rate_ms / 1000
        # Update-Thread variables
        self.read_table_file('table_peak')
        self.paused = False
        self.condition_pause = threading.Condition()

    # Worker thread at fixed time interval (synchronous), allows interpolation
    def loop(self):
        print("[LED Stripe] Start LED Looping")
        while self.running:
            if self.pause:
                self.pause = False
                print("Pause...")
                with self.condition_paused:
                    self.condition_paused.wait()
            start_time = time.process_time()
            self.update()
            counter = 0
            # Wait until loop time expired, synchronous worker
            while (time.process_time() - start_time) <= self.tick_rate:
                counter = counter + 1
                pass
            # Update step took linger than the specified tick_rate
            if counter == 0:
                print('[LED STRIPE] WARNING: tick rate is too fast!')
                if self.mode == Mode.SOUND:
                    self.peak_Step_size = self.peak_Step_size + 1 
                    print('[LED STRIPE] ==> Increased step size (', self.peak_Step_size,')')
                if self.mode == Mode.NORMAL:
                    self.brightness_interpolation_speed = self.brightness_interpolation_speed * 1.2
                    self.color_interpolation_speed = self.color_interpolation_speed * 1.2
                    self.tick_rate = self.tick_rate * 1.2
        print("[LED Stripe] Stop LED Looping")
        return

    def change_mode(self, mode: Mode):
        self.mode = mode
        if mode == Mode.BC or mode == Mode.OFF:
            self.paused = True
        elif mode == Mode.NORMAL:
            with self.condition_pause:
                self.condition_pause.notify()
        elif mode == Mode.SOUND:
            with self.condition_pause:
                self.condition_pause.notify()

    # Linear interpolation between desired and current value
    def interpolate_brightness(self) -> bool:
        # Avoid toggeling at the end of interpolation
        if abs(self.desired_brightness - self.brightness) <= self.brightness_interpolation_speed:
            self.brightness = self.desired_brightness
            return False
        if self.desired_brightness > self.brightness:
            self.brightness = self.brightness + self.brightness_interpolation_speed
        elif self.desired_brightness < self.brightness:
            self.brightness = self.brightness - self.brightness_interpolation_speed
        return True

    # Linear interpolation between desired and current value
    def interpolate_rgb_color(self) -> bool:
        dif_r = self.r_desired-self.r
        dif_g = self.g_desired-self.g
        dif_b = self.b_desired-self.b
        if dif_r == 0 and dif_g == 0 and dif_b == 0:
            return False
        self.r = (dif_r)*self.color_interpolation_speed + self.r
        self.g = (dif_g)*self.color_interpolation_speed + self.g
        self.b = (dif_b)*self.color_interpolation_speed + self.b
        return True
        
    def set_brightness(self, b: int):
        self.desired_brightness = (b / 100.0)
        with self.condition_paused:
            self.condition_paused.notify()

    def set_color(self, color: int):
        self.r_desired, self.g_desired, self.b_desired = self.get_rgb_from_scaled_color(color, scaled=False)
        with self.condition_paused:
            self.condition_paused.notify()

    # Performs one interpolation step between desired and current LED values and applies changes to the stripe
    def update(self):
        if self.mode == Mode.NORMAL:
            if not self.interpolate_brightness() and not self.interpolate_rgb_color():
                self.pause = True
        elif self.mode == Mode.SOUND:
            if self.peak_progress >= -1:
                self.peak()
            if self.brightness < self.min_intensity_sound:
                self.brightness = self.min_intensity_sound
        color = self.get_scaled_color_from_rgb(self.r, self.g, self.b)
        for i in range(1, self.strip.num_led+1):
            self.strip.set_pixel_rgb(i, color)
        self.strip.show()
        return

    def get_strip_info(self):
        return (int(self.desired_brightness), self.get_color())
        
    def get_color(self, scaled: bool = False) -> int:
        r = self.r
        g = self.g
        b = self.b
        if scaled:
            r = r*self.brightness
            g = g*self.brightness
            b = b*self.brightness
        return int(r) + (int(g) << 8) + (int(b) << 16)

    # Convert R, G, B, to a single color Integer value
    # Set scaled=True to apply brightness multiplicator
    def get_scaled_color_from_rgb(self, r, g, b, scaled: bool = True)->int:
        if scaled:
            r = r*self.brightness
            g = g*self.brightness
            b = b*self.brightness
        return int(r) + (int(g) << 8) + (int(b) << 16)

    # Use scaled property to apply brightness multiplicator
    # Extracts R, G, B from an color integer (without alpha)
    def get_rgb_from_scaled_color(self, color: int, scaled: bool = True):
        if self.brightness == 0:
            return 0, 0, 0
        r = color & 0xFF
        g = (color & 0xFF00) >> 8
        b = (color & 0xFF0000) >> 16
        if scaled:
            return int(r/self.brightness), int(g/self.brightness), int(b/self.brightness)
        else:
            return int(r), int(g), int(b)

    def stop(self):
        # Stop the thread
        self.running = False
        with self.condition_pause:
            self.condition_pause.notify()
        time.sleep(self.tick_rate)
        self.looper_thread = None
        # Reset color LED setup
        self.r = self.g = self.b = self.brightness = 0

    def get_status(self):
        return (self.mode.name, 
                (self.desired_brightness*100),
                self.get_color())
        
    def start(self) -> bool:
        # check if thread is already/still running
        if self.running:
            print('[LED stripe] Loop is already running!')
            return True
        # start the thread and initialize values to default
        self.looper_thread = threading.Thread(target=self.loop, name='LED_stripe_updater', args=(), daemon=True)
        self.running = True
        self.looper_thread.start()
        # Init color white
        self.r = self.g = self.b = 255
        self.brightness = 0.0
        self.desired_brightness = 0.5
        return self.looper_thread.is_alive()

    def read_table_file(self, filename: str):
        try:
            for line in open(filename, encoding='utf-8'):
                self.peak_table.append(float(line))
        except OSError as e:
            print("Error while reading file: ", e)
            return
        except ValueError as e:
            print("Error while converting file content: ", e)
            return

    # interface to publish stream data to strip
    def set_intensity(self, value: int):
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

    def peak(self):
        self.brightness = self.peak_table[self.peak_progress] * self.intensity
        self.peak_progress = self.peak_progress + self.peak_Step_size
        if self.peak_progress >= len(self.peak_table):
            self.intensity = 0.0
            self.peak_progress = -1
        return


class Status:
    brightness: int
    color: int

    def __init__(self, brightness, color) -> None:
        self.brightness = brightness
        self.color = color