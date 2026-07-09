"""
Copyright (c) 2021-, Haibin Wen, sunnypilot, and a number of other contributors.

This file is part of sunnypilot and is licensed under the MIT License.
See the LICENSE.md file in the root directory for more details.
"""
from collections.abc import Callable

import pyray as rl
from openpilot.common.params import Params
from openpilot.system.ui.lib.application import MousePos
from openpilot.system.ui.widgets.toggle import Toggle
from openpilot.system.ui.sunnypilot.lib.styles import style

KNOB_PADDING = 5
KNOB_RADIUS = style.TOGGLE_BG_HEIGHT / 2 - KNOB_PADDING


class ToggleSP(Toggle):
  def __init__(self, initial_state=False, callback: Callable[[bool], None] | None = None, param: str | None = None):
    self.param_key = param
    self.params = Params()
    if self.param_key:
      initial_state = self.params.get_bool(self.param_key)
    Toggle.__init__(self, initial_state, callback)

  def set_rect(self, rect: rl.Rectangle):
    self._rect = rl.Rectangle(rect.x, rect.y, style.TOGGLE_WIDTH, style.TOGGLE_HEIGHT)

  def _handle_mouse_release(self, mouse_pos: MousePos):
    super()._handle_mouse_release(mouse_pos)
    if self._enabled and self.param_key:
      self.params.put_bool(self.param_key, self._state)

  def _render(self, rect: rl.Rectangle):
    self.update()
    self._rect.y -= style.ITEM_PADDING / 2

    on = self._progress > 0.5
    if self._enabled:
      on_color = style.TOGGLE_ON_COLOR
      off_color = style.TOGGLE_OFF_COLOR
    else:
      on_color = style.TOGGLE_DISABLED_ON_COLOR
      off_color = style.TOGGLE_DISABLED_OFF_COLOR

    # Square checkbox, right-aligned inside the widget rect (with a right margin
    # so it isn't flush against the card edge).
    s = style.TOGGLE_BG_HEIGHT
    bx = self._rect.x + style.TOGGLE_WIDTH - s - 24
    by = self._rect.y + (style.TOGGLE_HEIGHT - s) / 2
    box = rl.Rectangle(bx, by, s, s)
    roundness = 0.25
    check_color = rl.Color(11, 18, 32, 255)  # VOID

    if on:
      # Filled square + check mark
      rl.draw_rectangle_rounded(box, roundness, 10, on_color)
      p1 = rl.Vector2(bx + s * 0.24, by + s * 0.52)
      p2 = rl.Vector2(bx + s * 0.42, by + s * 0.72)
      p3 = rl.Vector2(bx + s * 0.78, by + s * 0.28)
      rl.draw_line_ex(p1, p2, 5, check_color)
      rl.draw_line_ex(p2, p3, 5, check_color)
    else:
      # Empty rounded-square outline
      rl.draw_rectangle_rounded_lines_ex(box, roundness, 10, 3, off_color)

    clicked = self._clicked
    self._clicked = False
    return clicked
