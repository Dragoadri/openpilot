"""
Copyright (c) 2021-, Haibin Wen, sunnypilot, and a number of other contributors.

This file is part of sunnypilot and is licensed under the MIT License.
See the LICENSE.md file in the root directory for more details.

Onroad CT/AT/JT numeric torque HUD for SIC-UEM / Orbit.

Port of the bottom-right torque readout in AnnotatedCameraWidgetSP::drawHud
(selfdrive/ui/sunnypilot/qt/onroad/annotated_camera.cc:1227-1270). Three stacked
lines in the bottom-right corner:
  - CT (yellow): theoretical Comma-model steer torque  (param CommaSteerTorque)
  - AT (white):  FINAL applied steer torque            (param AppliedSteerTorque)
  - JT (cyan):   torque received from the Jetson        (param JetsonTorque)

Each line only renders when its param holds a parseable float. This is NOT the
mici steering TorqueBar arc (a different element wired separately in
hud_renderer.py). Param reads are throttled (~0.5s).
"""
import pyray as rl

from openpilot.selfdrive.ui.ui_state import ui_state
from openpilot.system.ui.lib.application import gui_app, FontWeight

PARAM_READ_INTERVAL_FRAMES = 30  # ~0.5s at 60fps
FONT_SIZE = 64
LINE_GAP = FONT_SIZE + 12
MARGIN_BOTTOM = 30
RIGHT_OFFSET = 420

COLOR_CT = rl.Color(255, 220, 80, 220)   # yellow (Comma - informative)
COLOR_AT = rl.Color(255, 255, 255, 230)  # white (real applied value)
COLOR_JT = rl.Color(0, 255, 200, 220)    # cyan (Jetson)


def _read_torque(name: str):
  raw = ui_state.params.get(name)
  if not raw:
    return None
  try:
    return float(raw)
  except (ValueError, TypeError):
    return None


class TorqueHudRenderer:
  def __init__(self):
    self.font = gui_app.font(FontWeight.SEMI_BOLD)
    self._frame = 0
    self._comma_torque = None
    self._applied_torque = None
    self._jetson_torque = None

  def update(self):
    self._frame += 1
    if self._frame % PARAM_READ_INTERVAL_FRAMES != 0:
      return
    self._comma_torque = _read_torque("CommaSteerTorque")
    self._applied_torque = _read_torque("AppliedSteerTorque")
    self._jetson_torque = _read_torque("JetsonTorque")

  def render(self, rect: rl.Rectangle):
    x_pos = rect.x + rect.width - RIGHT_OFFSET
    y_jt = rect.y + rect.height - MARGIN_BOTTOM - FONT_SIZE
    y_at = y_jt - LINE_GAP
    y_ct = y_at - LINE_GAP

    if self._comma_torque is not None:
      rl.draw_text_ex(self.font, f"CT: {self._comma_torque:.2f}", rl.Vector2(x_pos, y_ct), FONT_SIZE, 0, COLOR_CT)
    if self._applied_torque is not None:
      rl.draw_text_ex(self.font, f"AT: {self._applied_torque:.2f}", rl.Vector2(x_pos, y_at), FONT_SIZE, 0, COLOR_AT)
    if self._jetson_torque is not None:
      rl.draw_text_ex(self.font, f"JT: {self._jetson_torque:.2f}", rl.Vector2(x_pos, y_jt), FONT_SIZE, 0, COLOR_JT)
