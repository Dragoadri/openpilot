"""
ORBIT boot splash.

A full-screen branding screen shown once each time the UI starts. It is pushed
on top of the widget nav stack (so on big_ui only it renders), fades in, holds,
then auto-dismisses after a few seconds (or on tap) by popping itself.

ORBIT — Open Remote Bidirectional IoV Telemetry.
"""
import math
import time

import pyray as rl

from openpilot.system.ui.lib.application import gui_app, FontWeight
from openpilot.system.ui.lib.text_measure import measure_text_cached
from openpilot.system.ui.widgets import Widget

LOGO_PATH = "img_orbit_logo.png"   # resolved under selfdrive/assets/

DURATION = 4.5   # seconds on screen before auto-dismiss
FADE = 0.6       # fade in / fade out seconds

# ORBIT palette (from the logo) — mirrors the home screen.
VOID = (11, 18, 32)       # #0B1220 background
INK = (226, 236, 255)     # #E2ECFF near-white
MUTED = (147, 180, 230)   # #93B4E6
CYAN = (34, 211, 238)     # #22D3EE live pulse accent
BLUE = (125, 180, 255)    # #7DB4FF uplink
GREEN = (74, 222, 128)    # #4ADE80 commands/downlink

LOGO_FRAC = 0.26          # logo width as a fraction of the screen width
WORDMARK_SIZE = 150
WORDMARK_SPACING = 26
TAGLINE_SIZE = 40
TAGLINE = "Open Remote Bidirectional IoV Telemetry"


def _col(rgb, alpha):
  return rl.Color(rgb[0], rgb[1], rgb[2], int(alpha))


class OrbitSplash(Widget):
  def __init__(self):
    super().__init__()
    self._start: float | None = None
    self._done = False

  def _dismiss(self):
    # Pop by identity: never pop another widget if something got pushed on top.
    if self._done:
      return
    if gui_app.get_active_widget() is self:
      self._done = True
      gui_app.pop_widget()
      return
    stack = getattr(gui_app, "_nav_stack", None)
    if stack and self in stack:
      self._done = True
      gui_app.pop_widget(stack.index(self))

  def _handle_mouse_release(self, mouse_pos):
    self._dismiss()

  def _alpha(self, elapsed: float) -> float:
    if elapsed < FADE:
      return max(0.0, elapsed / FADE)
    if elapsed > DURATION - FADE:
      return max(0.0, (DURATION - elapsed) / FADE)
    return 1.0

  def _render(self, rect: rl.Rectangle):
    now = time.monotonic()
    if self._start is None:
      self._start = now
    elapsed = now - self._start
    a = self._alpha(elapsed) * 255.0

    cx = rect.x + rect.width / 2.0

    # Background + ORBIT accent bars (top/bottom)
    rl.draw_rectangle_rec(rect, _col(VOID, 255))
    bar_h = 14
    rl.draw_rectangle(int(rect.x), int(rect.y), int(rect.width), bar_h, _col(CYAN, a))
    rl.draw_rectangle(int(rect.x), int(rect.y + rect.height - bar_h), int(rect.width), bar_h, _col(BLUE, a))

    # Stacked hero block (logo + wordmark + tagline), vertically centered.
    bold = gui_app.font(FontWeight.BOLD)
    normal = gui_app.font(FontWeight.NORMAL)

    logo_w = int(min(rect.width * LOGO_FRAC, 460))
    wordmark_size = measure_text_cached(bold, "ORBIT", WORDMARK_SIZE, WORDMARK_SPACING)
    tagline_size = measure_text_cached(normal, TAGLINE, TAGLINE_SIZE)

    gap_logo = 34
    gap_wordmark = 24

    logo_h = logo_w  # the logo asset is square
    block_h = logo_h + gap_logo + wordmark_size.y + gap_wordmark + tagline_size.y
    y = rect.y + max((rect.height - block_h) / 2.0, rect.height * 0.14)

    # Animated orbit around the logo: pulsing cyan glow + a rotating tri-color ring.
    logo_cx, logo_cy = cx, y + logo_h / 2.0
    pulse = 0.5 + 0.5 * math.sin(elapsed * 2.6)
    rl.draw_circle(int(logo_cx), int(logo_cy), logo_h * 0.52, _col(CYAN, a * (0.08 + 0.16 * pulse)))
    ring_r = logo_h * 0.64
    spin = (elapsed * 80.0) % 360.0
    for k, col in enumerate((CYAN, BLUE, GREEN)):
      start = spin + k * 120.0
      rl.draw_ring(rl.Vector2(logo_cx, logo_cy), ring_r - 5, ring_r, start, start + 80, 48, _col(col, a * 0.85))

    # Logo (true colors)
    try:
      tex = gui_app.texture(LOGO_PATH, logo_w, logo_h, keep_aspect_ratio=True)
      rl.draw_texture_ex(tex, rl.Vector2(cx - tex.width / 2.0, y), 0.0, 1.0, _col((255, 255, 255), a))
    except Exception:
      pass
    y += logo_h + gap_logo

    # Wordmark + cyan accent underline that sweeps in from the center
    rl.draw_text_ex(bold, "ORBIT", rl.Vector2(int(cx - wordmark_size.x / 2.0), int(y)),
                    WORDMARK_SIZE, WORDMARK_SPACING, _col(INK, a))
    uw = wordmark_size.x * min(1.0, elapsed / (FADE + 0.5))
    rl.draw_rectangle(int(cx - uw / 2.0), int(y + wordmark_size.y + 10), int(uw), 4, _col(CYAN, a))
    y += wordmark_size.y + gap_wordmark

    # Tagline
    rl.draw_text_ex(normal, TAGLINE, rl.Vector2(int(cx - tagline_size.x / 2.0), int(y)),
                    TAGLINE_SIZE, 0, _col(MUTED, a))

    # Hint near the bottom (gently pulsing)
    hint = "toca la pantalla para continuar"
    hfont = gui_app.font(FontWeight.NORMAL)
    hw = measure_text_cached(hfont, hint, 30).x
    rl.draw_text_ex(hfont, hint, rl.Vector2(cx - hw / 2.0, rect.y + rect.height - 70), 30, 0,
                    _col(MUTED, a * (0.5 + 0.5 * pulse)))

    # Auto-dismiss
    if elapsed >= DURATION:
      self._dismiss()
