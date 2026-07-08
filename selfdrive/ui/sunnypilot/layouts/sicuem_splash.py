"""
Copyright (c) 2021-, Haibin Wen, sunnypilot, and a number of other contributors.

This file is part of sunnypilot and is licensed under the MIT License.
See the LICENSE.md file in the root directory for more details.

SIC-UEM / Orbit boot splash.

A full-screen credits/branding screen shown once each time the UI starts. It is
pushed on top of the widget nav stack (so on big_ui only it renders), fades in,
holds, then auto-dismisses after a few seconds (or on tap) by popping itself.

States who modified this branch: Adrian Canadas, grupo de investigacion SIC-UEM,
Universidad Europea de Madrid (TFG), with the UEM logo.
"""
import time

import pyray as rl

from openpilot.system.ui.lib.application import gui_app, FontWeight
from openpilot.system.ui.lib.text_measure import measure_text_cached
from openpilot.system.ui.widgets import Widget

LOGO_PATH = "../../sunnypilot/selfdrive/assets/offroad/uem_logo_completo.png"
LOGO_AR = 820 / 182  # proporción real de uem_logo_completo.png (no estirar)

DURATION = 6.0   # seconds on screen before auto-dismiss
FADE = 0.6       # fade in / fade out seconds

# Palette
UEM_RED = (236, 22, 22)
BG = (10, 11, 14)
WHITE = (255, 255, 255)
SOFT = (180, 184, 196)
DIM = (130, 134, 146)

# (text, font_weight, size, color_rgb, gap_after_px)
LINES = [
  ("SIC-UEM", FontWeight.BOLD, 104, UEM_RED, 6),
  ("Sistemas Inteligentes de Control", FontWeight.MEDIUM, 40, SOFT, 46),
  ("Rama de openpilot / sunnypilot modificada por", FontWeight.NORMAL, 38, DIM, 14),
  ("Adrian Canadas", FontWeight.BOLD, 76, WHITE, 10),
  ("Grupo de Investigacion SIC-UEM", FontWeight.MEDIUM, 44, SOFT, 4),
  ("Universidad Europea de Madrid", FontWeight.MEDIUM, 44, SOFT, 40),
  ("TFG - Conduccion asistida con telemetria y control remoto", FontWeight.NORMAL, 34, DIM, 0),
]


def _col(rgb, alpha):
  return rl.Color(rgb[0], rgb[1], rgb[2], int(alpha))


class SicuemSplash(Widget):
  def __init__(self):
    super().__init__()
    self._start: float | None = None
    self._done = False

  def _dismiss(self):
    if not self._done:
      self._done = True
      gui_app.pop_widget()

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

    # Background + UEM red accent bars (top/bottom)
    rl.draw_rectangle_rec(rect, _col(BG, 255))
    bar_h = 14
    rl.draw_rectangle(int(rect.x), int(rect.y), int(rect.width), bar_h, _col(UEM_RED, a))
    rl.draw_rectangle(int(rect.x), int(rect.y + rect.height - bar_h), int(rect.width), bar_h, _col(UEM_RED, a))

    # Logo (banner ancho 820x182): pedir la textura con su proporción real para que
    # no se estire (con scale!=1.0 texture() fija tex.width/height a lo solicitado).
    logo_w = int(min(rect.width * 0.62, 1200))
    logo_h = int(logo_w / LOGO_AR)
    logo_y = rect.y + rect.height * 0.10
    try:
      tex = gui_app.texture(LOGO_PATH, logo_w, logo_h, keep_aspect_ratio=True)
      rl.draw_texture_ex(tex, rl.Vector2(cx - tex.width / 2.0, logo_y), 0.0, 1.0, _col(WHITE, a))
      logo_bottom = logo_y + tex.height
    except Exception:
      logo_bottom = logo_y + 200

    # Credit text block, centered, stacked under the logo
    y = logo_bottom + 48
    for text, weight, size, rgb, gap in LINES:
      font = gui_app.font(weight)
      tw = measure_text_cached(font, text, size).x
      rl.draw_text_ex(font, text, rl.Vector2(cx - tw / 2.0, y), size, 0, _col(rgb, a))
      y += size + gap

    # Hint near the bottom
    hint = "toca la pantalla para continuar"
    hfont = gui_app.font(FontWeight.NORMAL)
    hw = measure_text_cached(hfont, hint, 30).x
    rl.draw_text_ex(hfont, hint, rl.Vector2(cx - hw / 2.0, rect.y + rect.height - 70), 30, 0, _col(DIM, a))

    # Auto-dismiss
    if elapsed >= DURATION:
      self._dismiss()
