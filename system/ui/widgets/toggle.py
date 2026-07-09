import pyray as rl
from collections.abc import Callable
from openpilot.system.ui.lib.application import MousePos
from openpilot.system.ui.widgets import Widget

ON_COLOR = rl.Color(51, 171, 76, 255)
OFF_COLOR = rl.Color(0x39, 0x39, 0x39, 255)
KNOB_COLOR = rl.WHITE
DISABLED_ON_COLOR = rl.Color(0x22, 0x77, 0x22, 255)  # Dark green when disabled + on
DISABLED_OFF_COLOR = rl.Color(0x39, 0x39, 0x39, 255)
DISABLED_KNOB_COLOR = rl.Color(0x88, 0x88, 0x88, 255)
WIDTH, HEIGHT = 160, 80
BG_HEIGHT = 60
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

    on = self._progress > 0.5
    if self._enabled:
      on_color = ON_COLOR
      off_color = OFF_COLOR
    else:
      on_color = DISABLED_ON_COLOR
      off_color = DISABLED_OFF_COLOR

    # Square checkbox, right-aligned inside the widget rect (with a right margin
    # so it isn't flush against the card edge).
    s = HEIGHT - 8
    bx = self._rect.x + WIDTH - s - 24
    by = self._rect.y + (HEIGHT - s) / 2
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

    # TODO: use click callback
    clicked = self._clicked
    self._clicked = False
    return clicked

  def _blend_color(self, c1, c2, t):
    return rl.Color(int(c1.r + (c2.r - c1.r) * t), int(c1.g + (c2.g - c1.g) * t), int(c1.b + (c2.b - c1.b) * t), 255)
