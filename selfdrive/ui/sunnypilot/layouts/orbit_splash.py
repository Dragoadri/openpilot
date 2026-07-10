"""
ORBIT boot splash — cinematic phased intro.

A full-screen branding screen shown once each time the UI starts. It is pushed
on top of the widget nav stack (so on big_ui only it renders), plays a phased
boot sequence (starfield -> tri-color ring draw-in + logo bloom -> wordmark
tracking-in -> tagline), shows a thin orbital progress arc, then auto-dismisses
(or dismisses on tap) by popping itself.

ORBIT — Open Remote Bidirectional IoV Telemetry.
"""
import math
import time

import pyray as rl

from openpilot.selfdrive.ui.widgets import orbit_fx as fx
from openpilot.system.ui.lib.application import gui_app, FontWeight
from openpilot.system.ui.lib.text_measure import measure_text_cached
from openpilot.system.ui.widgets import Widget

LOGO_PATH = "img_orbit_logo_round.png"   # variante circular: dentro del anillo, un
                                         # logo cuadrado desentona y sus esquinas
                                         # cruzaban el anillo giratorio

DURATION = 5.5     # seconds on screen before auto-dismiss
EXIT_FADE = 0.5    # global fade/zoom-out at the very end

LOGO_FRAC = 0.26   # logo width as a fraction of the screen width
WORDMARK_SIZE = 150
WORDMARK_SPACING = 26         # final tracking
WORDMARK_SPACING_WIDE = 64    # tracking animates in from this
TAGLINE = "Open Remote Bidirectional IoV Telemetry"
TAGLINE_SIZE = 40
RING_SPIN_DPS = 40.0          # continuous ring rotation, deg/s

# Badge "powered by DRAGO" (esquina inferior derecha; tap -> pantalla sobre drago)
DRAGO_LOGO_H = 64
DRAGO_ASPECT = 469 / 640
POWERED_SIZE = 26


def _win(t: float, a: float, b: float) -> float:
  """0..1 progress of t through the window [a, b]."""
  if b <= a:
    return 1.0
  return fx.clamp01((t - a) / (b - a))


class OrbitSplash(Widget):
  def __init__(self):
    super().__init__()
    self._start: float | None = None
    self._done = False
    self._stars = fx.Starfield(n=90, seed=42)
    self._badge_rect = rl.Rectangle(0, 0, 0, 0)
    self._badge_visible = False
    try:
      self._drago = gui_app.texture("img_drago_logo.png", int(DRAGO_LOGO_H * DRAGO_ASPECT) + 4, DRAGO_LOGO_H,
                                    keep_aspect_ratio=True)
    except Exception:
      self._drago = None

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
    # El badge powered-by abre la pantalla sobre drago; cualquier otro punto salta el splash.
    if self._badge_visible and rl.check_collision_point_rec(mouse_pos, self._badge_rect):
      from openpilot.selfdrive.ui.widgets.about_drago import AboutDragoDialog
      gui_app.push_widget(AboutDragoDialog())
      return
    self._dismiss()

  def _render(self, rect: rl.Rectangle):
    now = time.monotonic()
    if self._start is None:
      self._start = now
    t = now - self._start
    exit_a = fx.clamp01((DURATION - t) / EXIT_FADE)   # 1 -> 0 during the exit

    rl.draw_rectangle_rec(rect, fx.VOID)

    # Phase 0 (0.0-0.6): the starfield fades in
    self._stars.render(rect, t, intensity=_win(t, 0.0, 0.6) * exit_a)

    # Top edge light (replaces the old solid 14px bars)
    g = _win(t, 0.2, 1.0) * exit_a
    rl.draw_rectangle(int(rect.x), int(rect.y), int(rect.width), 2, fx.col(fx.CYAN, 0.45 * g))
    rl.draw_rectangle_gradient_v(int(rect.x), int(rect.y) + 2, int(rect.width), 26,
                                 fx.col(fx.CYAN, 0.10 * g), fx.col(fx.CYAN, 0.0))

    cx = rect.x + rect.width / 2.0
    bold = gui_app.font(FontWeight.BOLD)
    normal = gui_app.font(FontWeight.NORMAL)

    logo_w = int(min(rect.width * LOGO_FRAC, 460))
    wm_size = measure_text_cached(bold, "ORBIT", WORDMARK_SIZE, WORDMARK_SPACING)
    tg_size = measure_text_cached(normal, TAGLINE, TAGLINE_SIZE)
    gap_logo, gap_wordmark = 34, 24
    logo_h = logo_w  # square asset
    block_h = logo_h + gap_logo + wm_size.y + gap_wordmark + tg_size.y
    y = rect.y + max((rect.height - block_h) / 2.0, rect.height * 0.14)
    logo_cx, logo_cy = cx, y + logo_h / 2.0

    # Phase 1 (0.3-1.2 staggered): the tri-color ring draws itself in, then spins
    ring_r = logo_h * 0.64
    spin = (t * RING_SPIN_DPS) % 360.0
    for k, color in enumerate((fx.CYAN, fx.BLUE_HI, fx.GREEN)):
      sweep = 80.0 * fx.ease_out_cubic(_win(t, 0.3 + 0.15 * k, 1.2 + 0.15 * k))
      if sweep <= 0.5:
        continue
      start = spin + k * 120.0
      rl.draw_ring(rl.Vector2(logo_cx, logo_cy), ring_r - 5, ring_r, start, start + sweep,
                   48, fx.col(color, 0.85 * exit_a))

    # Satellite dot + fading trail traveling the ring (after the draw-in)
    if t > 1.2:
      sat_a = _win(t, 1.2, 1.6) * exit_a
      ang = math.radians(spin * 2.2)
      sx = logo_cx + ring_r * math.cos(ang)
      sy = logo_cy + ring_r * math.sin(ang)
      fx.draw_glow_circle(sx, sy, 7.0, fx.CYAN, 0.5 * sat_a)
      rl.draw_circle(int(sx), int(sy), 6.0, fx.col(fx.CYAN, 0.9 * sat_a))
      for lag, aa, rr in ((7.0, 0.45, 4.5), (14.0, 0.2, 3.0)):
        ang2 = math.radians(spin * 2.2 - lag)
        rl.draw_circle(int(logo_cx + ring_r * math.cos(ang2)),
                       int(logo_cy + ring_r * math.sin(ang2)), rr, fx.col(fx.CYAN, aa * sat_a))

    # Phase 1b (0.4-1.1): logo scales in with a spring + breathing cyan bloom
    lg = _win(t, 0.4, 1.1)
    la = lg * exit_a
    scale = (0.7 + 0.3 * fx.ease_out_back(lg)) * (1.0 + 0.06 * (1.0 - exit_a))
    fx.draw_glow_circle(logo_cx, logo_cy, logo_h * 0.55, fx.CYAN,
                        (0.35 + 0.35 * fx.pulse01(t, 2.4)) * la)
    try:
      tex = gui_app.texture(LOGO_PATH, logo_w, logo_h, keep_aspect_ratio=True)
      dw, dh = tex.width * scale, tex.height * scale
      rl.draw_texture_pro(tex, rl.Rectangle(0, 0, tex.width, tex.height),
                          rl.Rectangle(logo_cx - dw / 2.0, logo_cy - dh / 2.0, dw, dh),
                          rl.Vector2(0, 0), 0.0, rl.Color(255, 255, 255, int(255 * fx.clamp01(la))))
    except Exception:
      pass
    y += logo_h + gap_logo

    # Phase 2 (1.1-1.8): wordmark tracking-in + center-out cyan underline
    wg = _win(t, 1.1, 1.8)
    if wg > 0.0:
      spacing = int(WORDMARK_SPACING_WIDE + (WORDMARK_SPACING - WORDMARK_SPACING_WIDE) * fx.ease_out_cubic(wg))
      cur = measure_text_cached(bold, "ORBIT", WORDMARK_SIZE, spacing)
      rl.draw_text_ex(bold, "ORBIT", rl.Vector2(int(cx - cur.x / 2.0), int(y)),
                      WORDMARK_SIZE, spacing, fx.col(fx.INK, wg * exit_a))
      uw = wm_size.x * fx.ease_out_cubic(_win(t, 1.4, 2.0))
      if uw > 1.0:
        rl.draw_rectangle(int(cx - uw / 2.0), int(y + wm_size.y + 10), int(uw), 4,
                          fx.col(fx.CYAN, wg * exit_a))
    y += wm_size.y + gap_wordmark

    # Phase 3 (1.7-2.3): tagline rises in
    tgp = fx.ease_out_cubic(_win(t, 1.7, 2.3))
    if tgp > 0.0:
      rl.draw_text_ex(normal, TAGLINE,
                      rl.Vector2(int(cx - tg_size.x / 2.0), int(y + 12.0 * (1.0 - tgp))),
                      TAGLINE_SIZE, 0, fx.col(fx.MUTED, tgp * exit_a))

    # Orbital progress arc (bottom-center) + pulsing tap hint
    pa = _win(t, 0.6, 1.2) * exit_a
    if pa > 0.0:
      ctr = rl.Vector2(cx, rect.y + rect.height - 158)
      rl.draw_ring(ctr, 23, 26, 0, 360, 48, fx.col(fx.HAIRLINE, 0.8 * pa))
      rl.draw_ring(ctr, 23, 26, -90, -90 + 360.0 * fx.clamp01(t / DURATION), 48,
                   fx.col(fx.CYAN, 0.85 * pa))
    if t > 2.2:
      hint = "toca la pantalla para continuar"
      ha = _win(t, 2.2, 2.8) * (0.5 + 0.5 * fx.pulse01(t, 1.8)) * exit_a
      hw = measure_text_cached(normal, hint, 30).x
      rl.draw_text_ex(normal, hint, rl.Vector2(cx - hw / 2.0, rect.y + rect.height - 96),
                      30, 0, fx.col(fx.MUTED, ha))

    # Badge "powered by DRAGO" (inferior derecha; tap -> pantalla sobre drago)
    ba = _win(t, 1.5, 2.1) * exit_a
    self._badge_visible = ba > 0.4
    if self._drago is not None and ba > 0.0:
      s1 = measure_text_cached(normal, "powered by ", POWERED_SIZE)
      s2 = measure_text_cached(bold, "DRAGO", POWERED_SIZE)
      right = rect.x + rect.width - 56
      dragon_x = right - self._drago.width
      dragon_y = rect.y + rect.height - 40 - self._drago.height
      rl.draw_texture_ex(self._drago, rl.Vector2(int(dragon_x), int(dragon_y)), 0.0, 1.0,
                         rl.Color(255, 255, 255, int(255 * ba)))
      text_x = dragon_x - 16 - (s1.x + s2.x)
      text_y = dragon_y + (self._drago.height - max(s1.y, s2.y)) / 2
      rl.draw_text_ex(normal, "powered by ", rl.Vector2(int(text_x), int(text_y)),
                      POWERED_SIZE, 0, fx.col(fx.MUTED, ba))
      rl.draw_text_ex(bold, "DRAGO", rl.Vector2(int(text_x + s1.x), int(text_y)),
                      POWERED_SIZE, 0, fx.col(fx.GREEN, ba))
      pad = 18
      self._badge_rect = rl.Rectangle(text_x - pad, dragon_y - pad,
                                      right - text_x + 2 * pad, self._drago.height + 2 * pad)

    # Auto-dismiss
    if t >= DURATION:
      self._dismiss()
