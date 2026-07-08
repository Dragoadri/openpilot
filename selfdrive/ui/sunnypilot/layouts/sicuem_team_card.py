"""
Copyright (c) 2021-, Haibin Wen, sunnypilot, and a number of other contributors.

This file is part of sunnypilot and is licensed under the MIT License.
See the LICENSE.md file in the root directory for more details.

SIC-UEM team card for the offroad home screen.

Replaces the stock "comma prime" advertisement (PrimeWidget) in the left column
with SIC-UEM / Orbit research-group branding: logo, group + university,
the TFG project, and author/director credits. Palette matches sicuem_splash.py.
Text avoids accents to stay consistent with the splash and dodge missing glyphs.
"""
import pyray as rl

from openpilot.system.ui.lib.application import gui_app, FontWeight
from openpilot.system.ui.lib.text_measure import measure_text_cached
from openpilot.system.ui.lib.wrap_text import wrap_text
from openpilot.system.ui.widgets import Widget

# gui_app.texture() resuelve sobre selfdrive/assets/ -> 2 niveles (no usa el prefijo icons/)
LOGO_PATH = "../../sunnypilot/selfdrive/assets/offroad/uem_logo.png"  # 200x200 (cuadrado)

UEM_RED = rl.Color(236, 22, 22, 255)
CARD_BG = rl.Color(51, 51, 51, 255)
WHITE = rl.Color(255, 255, 255, 255)
SOFT = rl.Color(180, 184, 196, 255)
DIM = rl.Color(140, 144, 156, 255)

PAD = 72
LOGO_SIZE = 150


class SicuemTeamCard(Widget):
  """SIC-UEM / Orbit branding card (left column of the home screen)."""

  def _render(self, rect: rl.Rectangle):
    rl.draw_rectangle_rounded(rect, 0.025, 10, CARD_BG)

    x = int(rect.x + PAD)
    w = int(rect.width - 2 * PAD)
    y = int(rect.y + 56)

    # Logo (cuadrado 200x200 -> no se estira al pedir cuadrado)
    try:
      tex = gui_app.texture(LOGO_PATH, LOGO_SIZE, LOGO_SIZE, keep_aspect_ratio=True)
      rl.draw_texture_ex(tex, rl.Vector2(x, y), 0.0, 1.0, WHITE)
      y += tex.height + 30
    except Exception:
      y += LOGO_SIZE + 30

    # Grupo
    bold = gui_app.font(FontWeight.BOLD)
    medium = gui_app.font(FontWeight.MEDIUM)
    normal = gui_app.font(FontWeight.NORMAL)

    rl.draw_text_ex(bold, "SIC-UEM", rl.Vector2(x, y), 88, 0, UEM_RED)
    y += 88 + 8
    rl.draw_text_ex(medium, "Sistemas Inteligentes de Control", rl.Vector2(x, y), 38, 0, SOFT)
    y += 38 + 4
    rl.draw_text_ex(medium, "Universidad Europea de Madrid", rl.Vector2(x, y), 38, 0, SOFT)
    y += 38 + 40

    # Separador rojo
    rl.draw_rectangle(x, y, w, 4, UEM_RED)
    y += 4 + 40

    # Proyecto
    rl.draw_text_ex(bold, "Orbit  -  TFG", rl.Vector2(x, y), 60, 0, WHITE)
    y += 60 + 14
    desc = "Conduccion asistida con telemetria y control remoto"
    for line in wrap_text(normal, desc, 38, w):
      rl.draw_text_ex(normal, line, rl.Vector2(x, y), 38, 0, DIM)
      y += 38 + 6
    y += 40

    # Creditos (etiqueta atenuada + nombre en blanco, alineados)
    label_x = x
    name_x = x + 220
    for label, name in (("Autor", "Adrian Canadas"), ("Director", "Sergio Bemposta")):
      rl.draw_text_ex(medium, label, rl.Vector2(label_x, y), 44, 0, DIM)
      rl.draw_text_ex(bold, name, rl.Vector2(name_x, y), 44, 0, WHITE)
      y += 44 + 16
