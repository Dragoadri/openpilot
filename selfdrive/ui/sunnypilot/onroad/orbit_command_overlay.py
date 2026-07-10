"""
Copyright (c) 2021-, Haibin Wen, sunnypilot, and a number of other contributors.

This file is part of sunnypilot and is licensed under the MIT License.
See the LICENSE.md file in the root directory for more details.

Onroad indicator for ORBIT remote commands (SIC-UEM).

Safety requirement: the driver must always know when the companion app is
issuing remote commands. Watches the Params written by
orbit/mqtt_comandos.py; they are transient triggers that the consumer
(controlsd/card) clears, so rising edges are latched on screen for ~3s.
Regular commands show as a top-center pill in the ORBIT palette; the remote
emergency brake shows as a full-width red banner drawn on top of everything.

The overtake command ("sic_adelantar") is intentionally not handled here: it
already has its own badge in overtake_overlay.py. Param reads are throttled
(~4 Hz).
"""
import time

import pyray as rl

from openpilot.selfdrive.ui.ui_state import ui_state
from openpilot.system.ui.lib.application import gui_app, FontWeight
from openpilot.system.ui.lib.text_measure import measure_text_cached

PARAM_POLL_INTERVAL = 0.25  # seconds (~4 Hz)
LATCH_DURATION = 3.0  # seconds a notification stays on screen
FONT_SIZE = 50
BANNER_FONT_SIZE = 66
BANNER_HEIGHT = 110

# ORBIT palette (values from system/ui/sunnypilot/lib/styles.py)
_NAVY_TRANSLUCENT = rl.Color(0x16, 0x23, 0x3A, 220)  # NAVY pill fill
_HAIRLINE = rl.Color(0x2B, 0x3E, 0x5F, 255)  # pill border
_BLUE = rl.Color(0x7D, 0xB4, 0xFF, 255)  # telemetry blue text
_GREEN = rl.Color(0x4A, 0xDE, 0x80, 255)  # command green text
_CYAN = rl.Color(0x22, 0xD3, 0xEE, 255)  # pulse dot
# Emergency banner: standard critical alert colors, deliberately not palette
_BANNER_FILL = rl.Color(0xC9, 0x22, 0x31, 0xF1)
_BANNER_TEXT = rl.Color(255, 255, 255, 255)

# param -> (label, text_color); insertion order is the stacking order
PILL_COMMANDS = {
  "ForceLaneChangeLeft": ("ORBIT - CAMBIO DE CARRIL IZQ", _BLUE),
  "ForceLaneChangeRight": ("ORBIT - CAMBIO DE CARRIL DER", _BLUE),
  "orbit_speed_increase": ("ORBIT - VELOCIDAD +", _GREEN),
  "orbit_speed_decrease": ("ORBIT - VELOCIDAD -", _GREEN),
  "orbit_steering_pulse": ("ORBIT - PULSO DE DIRECCION", _BLUE),
}
_BOOL_PILL_PARAMS = tuple(p for p in PILL_COMMANDS if p != "orbit_steering_pulse")

BANNER_LABEL = "ORBIT - FRENADO REMOTO"


class OrbitCommandOverlay:
  def __init__(self):
    self.font = gui_app.font(FontWeight.BOLD)
    self._last_poll = 0.0
    self._prev_bools = dict.fromkeys(_BOOL_PILL_PARAMS, False)
    self._prev_pulse = ""
    self._pill_deadlines: dict[str, float] = {}
    self._brutebreak_active = False
    self._banner_deadline = 0.0

  def _poll_params(self, now: float):
    if now - self._last_poll < PARAM_POLL_INTERVAL:
      return
    self._last_poll = now
    params = ui_state.params

    for name in _BOOL_PILL_PARAMS:
      cur = params.get_bool(name)
      if cur and not self._prev_bools[name]:
        self._pill_deadlines[name] = now + LATCH_DURATION
      self._prev_bools[name] = cur

    # "direction:start_ms" string; a new start_ms means a new pulse
    pulse = params.get("orbit_steering_pulse") or ""
    if pulse and pulse != self._prev_pulse:
      self._pill_deadlines["orbit_steering_pulse"] = now + LATCH_DURATION
    self._prev_pulse = pulse

    brute = params.get_bool("brutebreak_active")
    if brute and not self._brutebreak_active:
      self._banner_deadline = now + LATCH_DURATION
    self._brutebreak_active = brute

  def _draw_pill(self, label: str, text_color: rl.Color, rect: rl.Rectangle, y: float) -> float:
    text_size = measure_text_cached(self.font, label, FONT_SIZE)
    pad_x, pad_y = 30, 12
    dot_radius, dot_gap = 9, 18
    box_w = pad_x + dot_radius * 2 + dot_gap + text_size.x + pad_x
    box_h = text_size.y + pad_y * 2
    box_x = rect.x + rect.width / 2 - box_w / 2

    box_rect = rl.Rectangle(box_x, y, box_w, box_h)
    rl.draw_rectangle_rounded(box_rect, 0.5, 10, _NAVY_TRANSLUCENT)
    rl.draw_rectangle_rounded_lines_ex(box_rect, 0.5, 10, 3, _HAIRLINE)

    rl.draw_circle(int(box_x + pad_x + dot_radius), int(y + box_h / 2), dot_radius, _CYAN)
    text_pos = rl.Vector2(box_x + pad_x + dot_radius * 2 + dot_gap, y + (box_h - text_size.y) / 2)
    rl.draw_text_ex(self.font, label, text_pos, FONT_SIZE, 0, text_color)
    return box_h

  def _draw_banner(self, rect: rl.Rectangle):
    rl.draw_rectangle(int(rect.x), int(rect.y), int(rect.width), BANNER_HEIGHT, _BANNER_FILL)
    text_size = measure_text_cached(self.font, BANNER_LABEL, BANNER_FONT_SIZE)
    text_pos = rl.Vector2(rect.x + (rect.width - text_size.x) / 2, rect.y + (BANNER_HEIGHT - text_size.y) / 2)
    rl.draw_text_ex(self.font, BANNER_LABEL, text_pos, BANNER_FONT_SIZE, 0, _BANNER_TEXT)

  def render(self, rect: rl.Rectangle):
    now = time.monotonic()
    self._poll_params(now)

    banner_visible = self._brutebreak_active or now < self._banner_deadline
    y = rect.y + (BANNER_HEIGHT + 20 if banner_visible else 20)
    for name, (label, text_color) in PILL_COMMANDS.items():
      if now < self._pill_deadlines.get(name, 0.0):
        y += self._draw_pill(label, text_color, rect, y) + 12

    # drawn last so the emergency banner always sits on top
    if banner_visible:
      self._draw_banner(rect)
