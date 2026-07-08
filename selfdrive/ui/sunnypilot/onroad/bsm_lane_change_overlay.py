"""
Copyright (c) 2021-, Haibin Wen, sunnypilot, and a number of other contributors.

This file is part of sunnypilot and is licensed under the MIT License.
See the LICENSE.md file in the root directory for more details.

Onroad BSM lane-change alert badge for SIC-UEM / Orbit.

Port of AnnotatedCameraWidgetSP::drawBsmLaneChangeAlert
(selfdrive/ui/sunnypilot/qt/onroad/annotated_camera.cc:851-936). Reads the
"bsmLaneChangeStatus" param and shows a center badge while a commanded lane change
is checking/blocked/clear. Distinct from the JetsonObstacle BSM_BLOCKED badge
(different param and states). Emoji prefixes are dropped (font support).

Center badge a bit below the overtake indicator. Param read throttled (~0.5s).
"""
import pyray as rl

from openpilot.selfdrive.ui.ui_state import ui_state
from openpilot.system.ui.lib.application import gui_app, FontWeight
from openpilot.system.ui.lib.text_measure import measure_text_cached

PARAM_READ_INTERVAL_FRAMES = 30  # ~0.5s at 60fps
FONT_SIZE = 55

_BLACK = rl.Color(0, 0, 0, 255)
_WHITE = rl.Color(255, 255, 255, 255)

# status -> (text, fill, border, text_color)
STATUS_STYLES = {
  "REVISANDO_BSM_IZQ": ("REVISANDO BSM...", rl.Color(255, 200, 0, 230), rl.Color(255, 255, 0, 255), _BLACK),
  "REVISANDO_BSM_DER": ("REVISANDO BSM...", rl.Color(255, 200, 0, 230), rl.Color(255, 255, 0, 255), _BLACK),
  "CARRIL_OCUPADO_IZQ": ("CARRIL IZQ OCUPADO", rl.Color(200, 0, 0, 230), rl.Color(255, 0, 0, 255), _WHITE),
  "CARRIL_OCUPADO_DER": ("CARRIL DER OCUPADO", rl.Color(200, 0, 0, 230), rl.Color(255, 0, 0, 255), _WHITE),
  "CARRIL_LIBRE_IZQ": ("CARRIL IZQ LIBRE", rl.Color(0, 180, 0, 230), rl.Color(0, 255, 0, 255), _WHITE),
  "CARRIL_LIBRE_DER": ("CARRIL DER LIBRE", rl.Color(0, 180, 0, 230), rl.Color(0, 255, 0, 255), _WHITE),
}


class BsmLaneChangeRenderer:
  def __init__(self):
    self.font = gui_app.font(FontWeight.BOLD)
    self._frame = 0
    self._status = ""

  def update(self):
    self._frame += 1
    if self._frame % PARAM_READ_INTERVAL_FRAMES != 0:
      return
    status = ui_state.params.get("bsmLaneChangeStatus")
    self._status = status if status else ""

  def render(self, rect: rl.Rectangle):
    style = STATUS_STYLES.get(self._status)
    if style is None:
      return

    text, fill, border, text_color = style
    text_size = measure_text_cached(self.font, text, FONT_SIZE)
    pad_x, pad_y = 25, 15
    box_w = text_size.x + pad_x * 2
    box_h = text_size.y + pad_y * 2
    box_x = rect.x + rect.width / 2 - box_w / 2
    box_y = rect.y + 100

    box_rect = rl.Rectangle(box_x, box_y, box_w, box_h)
    rl.draw_rectangle_rounded(box_rect, 0.3, 10, fill)
    rl.draw_rectangle_rounded_lines_ex(box_rect, 0.3, 10, 4, border)

    text_pos = rl.Vector2(box_x + (box_w - text_size.x) / 2, box_y + (box_h - text_size.y) / 2)
    rl.draw_text_ex(self.font, text, text_pos, FONT_SIZE, 0, text_color)
