"""
Copyright (c) 2021-, Haibin Wen, sunnypilot, and a number of other contributors.

This file is part of sunnypilot and is licensed under the MIT License.
See the LICENSE.md file in the root directory for more details.

Onroad "esquive" (obstacle dodge) badge for the SIC-UEM / Orbit COMMA+JETSON
mode. Port of the overlay drawn in the old Qt AnnotatedCameraWidgetSP
(selfdrive/ui/sunnypilot/qt/onroad/annotated_camera.cc, ESQUIVANDO / BSM BLOQUEA).

Only shows in COMMA+JETSON mode (SteerTorqueMode == 3) when the Jetson is
actively dodging an obstacle (DODGING_*) or when the BSM blocked a dodge
(BSM_BLOCKED_*). CANCELED_* is not considered an active dodge.

Param reads are throttled (~0.5s).
"""
import pyray as rl

from openpilot.selfdrive.ui.ui_state import ui_state
from openpilot.system.ui.lib.application import gui_app, FontWeight
from openpilot.system.ui.lib.text_measure import measure_text_cached

PARAM_READ_INTERVAL_FRAMES = 30  # ~0.5s at 60fps

# label text + (is_bsm_block)
DODGE_LABELS = {
  "DODGING_LEFT": ("ESQUIVANDO  <-", False),
  "DODGING_RIGHT": ("ESQUIVANDO  ->", False),
  "DODGING_HOLD": ("ESQUIVANDO  - NEUTRO", False),
  "BSM_BLOCKED_LEFT": ("BSM BLOQUEA  <-", True),
  "BSM_BLOCKED_RIGHT": ("BSM BLOQUEA  ->", True),
}

# Orange for active dodge, red (more urgent) for BSM block.
COLOR_DODGE_BORDER = rl.Color(245, 158, 11, 255)
COLOR_DODGE_FILL = rl.Color(245, 158, 11, 180)
COLOR_BSM_BORDER = rl.Color(220, 38, 38, 255)
COLOR_BSM_FILL = rl.Color(220, 38, 38, 180)
COLOR_TEXT = rl.Color(255, 255, 255, 255)

FONT_SIZE = 46


class JetsonObstacleRenderer:
  def __init__(self):
    self.font = gui_app.font(FontWeight.BOLD)
    self._frame = 0
    self._steer_mode = 0
    self._obstacle_status = ""

  def update(self):
    self._frame += 1
    if self._frame % PARAM_READ_INTERVAL_FRAMES != 0:
      return
    raw_mode = ui_state.params.get("SteerTorqueMode")
    try:
      self._steer_mode = int(raw_mode) if raw_mode else 0
    except (ValueError, TypeError):
      self._steer_mode = 0
    obs = ui_state.params.get("JetsonObstacleStatus")
    self._obstacle_status = obs if obs else ""

  def render(self, rect: rl.Rectangle):
    if self._steer_mode != 3:
      return
    entry = DODGE_LABELS.get(self._obstacle_status)
    if entry is None:
      return

    label, is_bsm = entry
    text_size = measure_text_cached(self.font, label, FONT_SIZE)

    pad_x, pad_y = 28, 14
    box_w = text_size.x + pad_x * 2
    box_h = text_size.y + pad_y * 2
    box_x = rect.x + rect.width / 2 - box_w / 2
    box_y = rect.y + 30  # top band, does not block the HUD

    box_rect = rl.Rectangle(box_x, box_y, box_w, box_h)
    fill = COLOR_BSM_FILL if is_bsm else COLOR_DODGE_FILL
    border = COLOR_BSM_BORDER if is_bsm else COLOR_DODGE_BORDER
    rl.draw_rectangle_rounded(box_rect, 0.35, 10, fill)
    rl.draw_rectangle_rounded_lines_ex(box_rect, 0.35, 10, 3, border)

    text_pos = rl.Vector2(box_x + (box_w - text_size.x) / 2, box_y + (box_h - text_size.y) / 2)
    rl.draw_text_ex(self.font, label, text_pos, FONT_SIZE, 0, COLOR_TEXT)
