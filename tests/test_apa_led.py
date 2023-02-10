#import apa102_tcp_server.apa_led as apa_led


# def test_interpolation():
#     INTERPOL_SPEED = 0.01
#     strip = apa_led.LedStrip()
#     strip.r, strip.g, strip.b = (50, 100, 150)
#     strip.r_desired, strip.g_desired, strip.b_desired = (100, 150, 50)
#     strip.color_interpolation_speed = INTERPOL_SPEED

#     max_iters = round(1/INTERPOL_SPEED)
#     while strip.interpolate_rgb_color():
#         max_iters -= 1
#         assert max_iters > 0

#     assert strip.r == strip.r_desired and strip.g == strip.g_desired and strip.b == strip.b_desired

