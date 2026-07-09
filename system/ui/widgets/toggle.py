import pyray as rl
from collections.abc import Callable
from openpilot.system.ui.lib.application import MousePos
from openpilot.system.ui.widgets import Widget

# ORBIT pill toggle: GREEN_DEEP/GREEN track when on, NAVY/HAIRLINE track when off.
ON_COLOR = rl.Color(22, 163, 74, 255)  # GREEN_DEEP
ON_BORDER_COLOR = rl.Color(74, 222, 128, 255)  # GREEN
OFF_COLOR = rl.Color(22, 35, 58, 255)  # NAVY
OFF_BORDER_COLOR = rl.Color(43, 62, 95, 255)  # HAIRLINE
KNOB_COLOR = rl.WHITE
DISABLED_ON_COLOR = rl.Color(27, 44, 72, 255)  # PANEL
DISABLED_OFF_COLOR = rl.Color(22, 35, 58, 255)  # NAVY
DISABLED_KNOB_COLOR = rl.Color(92, 117, 153, 255)  # MUTED_DIM
WIDTH, HEIGHT = 160, 80
BG_HEIGHT = 60
KNOB_PADDING = 5
ANIMATION_SPEED = 8.0


class Toggle(Widget):
  def __init__(self, initial_state: bool = False, callback: Callable[[bool], None] | None = None):
    super().__init__()
    self._state = initial_state
    self._callback = callback
    self._enabled = True
    self._progress = 1.0 if initial_state else 0.0
    self._target = self._progress
    self._clicked = False

  def set_rect(self, rect: rl.Rectangle):
    self._rect = rl.Rectangle(rect.x, rect.y, WIDTH, HEIGHT)

  def _handle_mouse_release(self, mouse_pos: MousePos):
    if not self._enabled:
      return

    self._clicked = True
    self._state = not self._state
    self._target = 1.0 if self._state else 0.0
    if self._callback:
      self._callback(self._state)

  def get_state(self) -> bool:
    return self._state

  def set_state(self, state: bool):
    self._state = state
    self._target = 1.0 if state else 0.0

  def is_enabled(self):
    return self._enabled

  def update(self):
    if abs(self._progress - self._target) > 0.01:
      delta = rl.get_frame_time() * ANIMATION_SPEED
      self._progress += delta if self._progress < self._target else -delta
      self._progress = max(0.0, min(1.0, self._progress))

  def _render(self, rect: rl.Rectangle):
    self.update()

    if self._enabled:
      bg_color = self._blend_color(OFF_COLOR, ON_COLOR, self._progress)
      border_color = self._blend_color(OFF_BORDER_COLOR, ON_BORDER_COLOR, self._progress)
      knob_color = KNOB_COLOR
    else:
      bg_color = self._blend_color(DISABLED_OFF_COLOR, DISABLED_ON_COLOR, self._progress)
      border_color = OFF_BORDER_COLOR
      knob_color = DISABLED_KNOB_COLOR

    # Rounded pill track (with a right margin so it isn't flush against the card edge)
    bg_rect = rl.Rectangle(self._rect.x, self._rect.y + (HEIGHT - BG_HEIGHT) / 2, WIDTH - 24, BG_HEIGHT)
    rl.draw_rectangle_rounded(bg_rect, 1.0, 10, bg_color)
    rl.draw_rectangle_rounded_lines_ex(bg_rect, 1.0, 10, 3, border_color)

    # Knob slides between the track ends
    knob_radius = BG_HEIGHT / 2 - KNOB_PADDING
    min_knob_x = bg_rect.x + KNOB_PADDING + knob_radius
    max_knob_x = bg_rect.x + bg_rect.width - KNOB_PADDING - knob_radius
    knob_x = min_knob_x + (max_knob_x - min_knob_x) * self._progress
    knob_y = bg_rect.y + BG_HEIGHT / 2
    rl.draw_circle(int(knob_x), int(knob_y), knob_radius, knob_color)

    # TODO: use click callback
    clicked = self._clicked
    self._clicked = False
    return clicked

  def _blend_color(self, c1, c2, t):
    return rl.Color(int(c1.r + (c2.r - c1.r) * t), int(c1.g + (c2.g - c1.g) * t), int(c1.b + (c2.b - c1.b) * t), 255)
