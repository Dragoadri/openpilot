"""
SectionHeaderSP - cabecera de seccion para los paneles de ajustes ORBIT.

Etiqueta corta en MAYUSCULAS (cian apagado) + hairline hasta el borde derecho.
No es interactiva y no dibuja tarjeta, para que las secciones se distingan de
las filas (los ListItemSP renderizan como tarjetas NAVY y parecen pulsables).
Uso: elemento normal de un Scroller, igual que Spacer/LineSeparatorSP.
"""
import pyray as rl

from openpilot.selfdrive.ui.layouts.settings import settings as OP
from openpilot.system.ui.lib.application import gui_app, FontWeight
from openpilot.system.ui.lib.text_measure import measure_text_cached
from openpilot.system.ui.widgets import Widget

_HEADER_HEIGHT = 96
_FONT_SIZE = 36
_LETTER_SPACING = 3


class SectionHeaderSP(Widget):
  def __init__(self, text: str):
    super().__init__()
    self._text = text
    self._font = gui_app.font(FontWeight.BOLD)
    self._rect = rl.Rectangle(0, 0, 0, _HEADER_HEIGHT)

  def set_parent_rect(self, parent_rect: rl.Rectangle) -> None:
    super().set_parent_rect(parent_rect)
    self._rect.width = parent_rect.width

  def _render(self, _):
    size = measure_text_cached(self._font, self._text, _FONT_SIZE, _LETTER_SPACING)
    # Etiqueta pegada abajo: separa mas de la seccion anterior que de sus filas.
    text_y = self._rect.y + self._rect.height - size.y - 12
    color = rl.Color(OP.ORBIT_CYAN.r, OP.ORBIT_CYAN.g, OP.ORBIT_CYAN.b, 210)
    rl.draw_text_ex(self._font, self._text, rl.Vector2(self._rect.x + 8, text_y), _FONT_SIZE, _LETTER_SPACING, color)

    line_x = self._rect.x + 8 + size.x + 28
    line_y = text_y + size.y / 2 + 2
    line_end = self._rect.x + self._rect.width - 12
    if line_x < line_end:
      rl.draw_line_ex(rl.Vector2(line_x, line_y), rl.Vector2(line_end, line_y), 2, OP.ORBIT_HAIRLINE)
