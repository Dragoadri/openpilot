"""
ORBIT boot splash — «La órbita se cierra».

Pantalla de arranque, empujada una vez al iniciar la UI (por encima del resto
del stack de widgets, así que solo se ve en big_ui). El logo Dúplex se dibuja
solo en 1,4 s (`orbit_duplex.draw_orbit_logo`), luego aparece el wordmark
«ORBIT» con su subrayado y el lema; el badge «powered by drago» cierra la
secuencia. Se autocierra a los `DURACION` segundos o al tocar la pantalla
(popeándose a sí misma).

ORBIT — Open Remote Bidirectional IoV Telemetry.
"""
import time

import pyray as rl

from openpilot.selfdrive.ui import orbit_theme as orbit_t
from openpilot.selfdrive.ui.widgets import orbit_duplex
from openpilot.selfdrive.ui.widgets import orbit_fx as fx
from openpilot.system.ui.lib.application import gui_app, FontWeight
from openpilot.system.ui.lib.text_measure import measure_text_cached
from openpilot.system.ui.widgets import Widget

DURACION = 2.2     # segundos en pantalla antes de autocerrarse
LOGO_DUR = 1.4     # duración de draw_orbit_logo (spec «Órbita · Grafito»)
LOGO_TAM = 340

WORDMARK_SIZE = 150
WORDMARK_SPACING = 26
TAGLINE = "Open Remote Bidirectional IoV Telemetry"
TAGLINE_SIZE = 40
TAGLINE_SPACING = 13

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
    t_anim = fx.clamp01(t / LOGO_DUR)

    rl.draw_rectangle_rec(rect, orbit_t.FONDO)

    cx = rect.x + rect.width / 2.0
    xbold = gui_app.font(FontWeight.EXTRA_BOLD)   # wordmark: Inter 800, como el mockup
    bold = gui_app.font(FontWeight.BOLD)
    normal = gui_app.font(FontWeight.NORMAL)

    wm_size = measure_text_cached(xbold, "ORBIT", WORDMARK_SIZE, WORDMARK_SPACING)
    tg_size = measure_text_cached(normal, TAGLINE, TAGLINE_SIZE, TAGLINE_SPACING)
    gap_logo, gap_wordmark = 78, 48
    block_h = LOGO_TAM + gap_logo + wm_size.y + gap_wordmark + tg_size.y
    y = rect.y + max((rect.height - block_h) / 2.0, rect.height * 0.14)
    logo_cx, logo_cy = cx, y + LOGO_TAM / 2.0

    # El logo Dúplex se dibuja solo en LOGO_DUR (1,4 s).
    orbit_duplex.draw_orbit_logo(logo_cx, logo_cy, LOGO_TAM, t_anim)
    y += LOGO_TAM + gap_logo

    # Wordmark «ORBIT»: aparece con opacidad, sin degradado ni tracking animado.
    wm_a = fx.ease_out_cubic(_win(t_anim, 0.75, 0.93))
    if wm_a > 0.0:
      rl.draw_text_ex(xbold, "ORBIT", rl.Vector2(int(cx - wm_size.x / 2.0), int(y)),
                      WORDMARK_SIZE, WORDMARK_SPACING, orbit_t.con_alfa(orbit_t.TEXTO1, wm_a))
      uw = wm_size.x * fx.ease_out_cubic(_win(t_anim, 0.82, 0.98))
      if uw > 1.0:
        rl.draw_rectangle(int(cx - uw / 2.0), int(y + wm_size.y + 18), int(uw), 4, orbit_t.PULSO)
    y += wm_size.y + gap_wordmark

    # Lema
    tg_a = fx.ease_out_cubic(_win(t_anim, 0.9, 1.0))
    if tg_a > 0.0:
      rl.draw_text_ex(normal, TAGLINE, rl.Vector2(int(cx - tg_size.x / 2.0), int(y)),
                      TAGLINE_SIZE, TAGLINE_SPACING, orbit_t.con_alfa(orbit_t.TEXTO2, tg_a))

    # Badge "powered by DRAGO" (inferior derecha; tap -> pantalla sobre drago)
    ba = _win(t, 1.5, 2.1)
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
                      POWERED_SIZE, 0, orbit_t.con_alfa(orbit_t.TEXTO2, ba))
      rl.draw_text_ex(bold, "DRAGO", rl.Vector2(int(text_x + s1.x), int(text_y)),
                      POWERED_SIZE, 0, orbit_t.con_alfa(orbit_t.OK, ba))
      pad = 18
      self._badge_rect = rl.Rectangle(text_x - pad, dragon_y - pad,
                                      right - text_x + 2 * pad, self._drago.height + 2 * pad)

    # Autocierre
    if t >= DURACION:
      self._dismiss()
