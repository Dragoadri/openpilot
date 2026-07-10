"""
Pantalla "sobre drago" — se abre al pulsar el badge "powered by DRAGO"
(esquina inferior derecha de la home y del splash). Un toque en cualquier
punto la cierra.
"""
import time

import pyray as rl

from openpilot.selfdrive.ui.widgets import orbit_fx as fx
from openpilot.system.ui.lib.application import gui_app, FontWeight
from openpilot.system.ui.lib.text_measure import measure_text_cached
from openpilot.system.ui.widgets import Widget

DRAGO_ASPECT = 469 / 640   # logo-drago.png es vertical
DRAGON_H = 300

NAME = "Adrian Canadas"
ALIAS = "DRAGO"
ROLE = "Creador y desarrollador de ORBIT"
PROJECT = "Telemetria IoV bidireccional sobre openpilot / sunnypilot"
LINK_GITHUB = "github.com/Dragoadri"
LINK_MAIL = "dragoadri@gmail.com"
HINT = "toca la pantalla para volver"


class AboutDragoDialog(Widget):
  def __init__(self):
    super().__init__()
    self._stars = fx.Starfield(n=70, seed=7)
    self._shown_at: float | None = None
    try:
      self._dragon = gui_app.texture("img_drago_logo.png", int(DRAGON_H * DRAGO_ASPECT) + 6, DRAGON_H,
                                     keep_aspect_ratio=True)
    except Exception:
      self._dragon = None

  def show_event(self):
    self._shown_at = None

  def _handle_mouse_release(self, mouse_pos):
    gui_app.pop_widget()

  def _render(self, rect: rl.Rectangle):
    now = time.monotonic()
    if self._shown_at is None:
      self._shown_at = now
    t = now - self._shown_at
    a = fx.clamp01(t / 0.35)   # fundido de entrada corto

    rl.draw_rectangle_rec(rect, fx.VOID)
    self._stars.render(rect, t, intensity=0.45 * a)

    bold = gui_app.font(FontWeight.BOLD)
    normal = gui_app.font(FontWeight.NORMAL)
    cx = rect.x + rect.width / 2.0

    # Columna central: dragon, alias, nombre, hairline, rol, proyecto, links.
    alias_s = measure_text_cached(bold, ALIAS, 96, 6)
    name_s = measure_text_cached(normal, NAME, 44)
    role_s = measure_text_cached(bold, ROLE, 36)
    proj_s = measure_text_cached(normal, PROJECT, 30)
    gh_s = measure_text_cached(normal, LINK_GITHUB, 32)
    mail_s = measure_text_cached(normal, LINK_MAIL, 32)

    dragon_h = self._dragon.height if self._dragon is not None else 0
    block_h = dragon_h + 26 + alias_s.y + 8 + name_s.y + 34 + role_s.y + 14 + proj_s.y + 40 + gh_s.y + 12 + mail_s.y
    y = rect.y + max((rect.height - block_h) / 2.0, rect.height * 0.08)

    if self._dragon is not None:
      fx.draw_glow_circle(cx, y + dragon_h / 2.0, dragon_h * 0.52, fx.GREEN, 0.30 * a)
      rl.draw_texture_ex(self._dragon, rl.Vector2(int(cx - self._dragon.width / 2.0), int(y)), 0.0, 1.0,
                         rl.Color(255, 255, 255, int(255 * a)))
      y += dragon_h + 26

    rl.draw_text_ex(bold, ALIAS, rl.Vector2(int(cx - alias_s.x / 2.0), int(y)), 96, 6, fx.col(fx.GREEN, a))
    y += alias_s.y + 8
    rl.draw_text_ex(normal, NAME, rl.Vector2(int(cx - name_s.x / 2.0), int(y)), 44, 0, fx.col(fx.INK, a))
    y += name_s.y + 16

    line_w = max(alias_s.x, role_s.x) * 0.72
    rl.draw_rectangle(int(cx - line_w / 2.0), int(y), int(line_w), 2, fx.col(fx.HAIRLINE, a))
    y += 18

    rl.draw_text_ex(bold, ROLE, rl.Vector2(int(cx - role_s.x / 2.0), int(y)), 36, 0, fx.col(fx.INK, 0.92 * a))
    y += role_s.y + 14
    rl.draw_text_ex(normal, PROJECT, rl.Vector2(int(cx - proj_s.x / 2.0), int(y)), 30, 0, fx.col(fx.MUTED, a))
    y += proj_s.y + 40

    rl.draw_text_ex(normal, LINK_GITHUB, rl.Vector2(int(cx - gh_s.x / 2.0), int(y)), 32, 0, fx.col(fx.CYAN, a))
    y += gh_s.y + 12
    rl.draw_text_ex(normal, LINK_MAIL, rl.Vector2(int(cx - mail_s.x / 2.0), int(y)), 32, 0, fx.col(fx.CYAN, a))

    hint_a = (0.45 + 0.4 * fx.pulse01(t, 1.8)) * a
    hint_s = measure_text_cached(normal, HINT, 28)
    rl.draw_text_ex(normal, HINT, rl.Vector2(int(cx - hint_s.x / 2.0), int(rect.y + rect.height - 84)),
                    28, 0, fx.col(fx.MUTED_DIM, hint_a))
