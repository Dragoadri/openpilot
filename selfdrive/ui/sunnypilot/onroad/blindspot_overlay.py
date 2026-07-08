"""
Copyright (c) 2021-, Haibin Wen, sunnypilot, and a number of other contributors.

This file is part of sunnypilot and is licensed under the MIT License.
See the LICENSE.md file in the root directory for more details.

Onroad blind-spot ("Angulo Muerto") status block for SIC-UEM / Orbit.

Port of the blind-spot block in AnnotatedCameraWidgetSP::drawHud
(selfdrive/ui/sunnypilot/qt/onroad/annotated_camera.cc:990-1036). Gated by the
"show_blindspot" param (this is the consumer the migrated UEM toggle was missing,
so the toggle in uem.py was previously a no-op in the sunnypilot HUD). Reads the
live blind-spot state from carState.leftBlindspot / rightBlindspot and shows a
colored status line plus side dots.

Placed bottom-left so it does not collide with the bottom-right CT/AT/JT torque
HUD. Param read throttled (~0.5s); carState read every frame for responsiveness.
"""
import pyray as rl

from openpilot.selfdrive.ui.ui_state import ui_state
from openpilot.system.ui.lib.application import gui_app, FontWeight
from openpilot.system.ui.lib.text_measure import measure_text_cached

PARAM_READ_INTERVAL_FRAMES = 30  # ~0.5s at 60fps

LABEL = "A. Muerto: "
LABEL_FONT_SIZE = 36
STATE_FONT_SIZE = 44

COLOR_WHITE = rl.Color(255, 255, 255, 255)
COLOR_FREE = rl.Color(0, 255, 0, 255)
COLOR_OCCUPIED = rl.Color(255, 128, 0, 255)
COLOR_BLOCKED = rl.Color(255, 0, 0, 255)
COLOR_DOT_LEFT = rl.Color(255, 128, 0, 255)
COLOR_DOT_RIGHT = rl.Color(0, 128, 255, 255)


class BlindspotRenderer:
  def __init__(self):
    self.font_label = gui_app.font(FontWeight.BOLD)
    self.font_state = gui_app.font(FontWeight.BOLD)
    self._frame = 0
    self._enabled = False
    self._left = False
    self._right = False

  def update(self):
    self._frame += 1
    if self._frame % PARAM_READ_INTERVAL_FRAMES == 0:
      self._enabled = ui_state.params.get_bool("show_blindspot")
    if not self._enabled:
      return
    try:
      cs = ui_state.sm['carState']
      self._left = bool(cs.leftBlindspot)
      self._right = bool(cs.rightBlindspot)
    except (KeyError, AttributeError):
      self._left = False
      self._right = False

  def _state(self) -> tuple[str, rl.Color]:
    if self._left and self._right:
      return "OBSTRUIDO", COLOR_BLOCKED
    if self._left:
      return "IZQ OCUPADO", COLOR_OCCUPIED
    if self._right:
      return "DER OCUPADO", COLOR_OCCUPIED
    return "LIBRE", COLOR_FREE

  def render(self, rect: rl.Rectangle):
    if not self._enabled:
      return

    state_text, state_color = self._state()
    label_size = measure_text_cached(self.font_label, LABEL, LABEL_FONT_SIZE)

    x = rect.x + 50
    y = rect.y + rect.height - 120

    rl.draw_text_ex(self.font_label, LABEL, rl.Vector2(x, y), LABEL_FONT_SIZE, 0, COLOR_WHITE)
    state_x = x + label_size.x + 4
    rl.draw_text_ex(self.font_state, state_text, rl.Vector2(state_x, y - 6), STATE_FONT_SIZE, 0, state_color)

    state_size = measure_text_cached(self.font_state, state_text, STATE_FONT_SIZE)
    dot_y = int(y + STATE_FONT_SIZE / 2)
    dot_x = int(state_x + state_size.x + 40)
    if self._left:
      rl.draw_circle(dot_x, dot_y, 14, COLOR_DOT_LEFT)
    if self._right:
      rl.draw_circle(dot_x + 40, dot_y, 14, COLOR_DOT_RIGHT)
