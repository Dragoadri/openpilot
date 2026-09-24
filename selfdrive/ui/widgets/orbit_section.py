"""
SectionHeaderSP - cabecera de seccion para los paneles de ajustes ORBIT.

Etiqueta corta en MAYUSCULAS (color de seccion) + hairline hasta el borde
derecho. Con `seccion`, ademas dibuja a la izquierda el icono propio de esa
seccion (con orbita+satelite, unico sitio del panel offroad donde se mueve)
y un filete corto en el color de la seccion bajo el titulo. Sin seccion, la
cabecera queda igual que antes de la Tarea 8 (solo texto + hairline).
No es interactiva y no dibuja tarjeta, para que las secciones se distingan de
las filas (los ListItemSP renderizan como tarjetas NAVY y parecen pulsables).
Uso: elemento normal de un Scroller, igual que Spacer/LineSeparatorSP.
"""
import time

import pyray as rl

from openpilot.selfdrive.ui import orbit_theme as t
from openpilot.selfdrive.ui.widgets import orbit_icons
from openpilot.system.ui.lib.application import gui_app, FontWeight
from openpilot.system.ui.lib.text_measure import measure_text_cached
from openpilot.system.ui.widgets import Widget

_HEADER_HEIGHT = 96
_FONT_SIZE = 36
_LETTER_SPACING = 3
_ICONO_TAM = 40
_ICONO_MARGEN = 12
_FILETE_ANCHO = 24
_FILETE_ALTO = 4

# Con orbita=True el dibujo ocupa una caja de lado tam*44/24 centrada en la
# caja nominal (orbit_icons.py:67-69): sobresale tam*10/24 a cada lado.
_ICONO_SOBRESALE = _ICONO_TAM * 10 / 24

# Glifo por seccion (tabla de la Tarea 8): mismo nombre que la seccion salvo cabina.
_GLIFO_POR_SECCION = {'cabina': 'enlace'}


def _geometria_cabecera(x0: float) -> tuple[float, float]:
  """x del icono (caja nominal) y x del titulo para que el borde izquierdo
  real de la orbita quede en `x0` y el satelite no toque el titulo."""
  icon_x = x0 + _ICONO_SOBRESALE
  title_x = icon_x + _ICONO_TAM + _ICONO_SOBRESALE + _ICONO_MARGEN
  return icon_x, title_x


class SectionHeaderSP(Widget):
  def __init__(self, text: str, seccion: str | None = None):
    super().__init__()
    self._text = text
    self._seccion = seccion
    self._font = gui_app.font(FontWeight.BOLD)
    self._rect = rl.Rectangle(0, 0, 0, _HEADER_HEIGHT)
    self._acento = t.SECCION[seccion] if seccion else t.PULSO
    self._color = t.con_alfa(self._acento, 210 / 255)

  def set_parent_rect(self, parent_rect: rl.Rectangle) -> None:
    super().set_parent_rect(parent_rect)
    self._rect.width = parent_rect.width

  def _render(self, _):
    size = measure_text_cached(self._font, self._text, _FONT_SIZE, _LETTER_SPACING)
    # Etiqueta pegada abajo: separa mas de la seccion anterior que de sus filas.
    text_y = self._rect.y + self._rect.height - size.y - 12
    text_x = self._rect.x + 8

    if self._seccion:
      glifo = _GLIFO_POR_SECCION.get(self._seccion, self._seccion)
      icon_x, text_x = _geometria_cabecera(text_x)
      icono_y = text_y + size.y / 2 - _ICONO_TAM / 2
      orbit_icons.draw_orbit_icon(glifo, icon_x, icono_y, _ICONO_TAM, self._acento, orbita=True, t=time.monotonic())

    rl.draw_text_ex(self._font, self._text, rl.Vector2(text_x, text_y), _FONT_SIZE, _LETTER_SPACING, self._color)

    if self._seccion:
      filete_y = text_y + size.y + 6
      rl.draw_rectangle_rounded(rl.Rectangle(text_x, filete_y, _FILETE_ANCHO, _FILETE_ALTO), 1.0, 8, self._acento)

    line_x = text_x + size.x + 28
    line_y = text_y + size.y / 2 + 2
    line_end = self._rect.x + self._rect.width - 12
    if line_x < line_end:
      rl.draw_line_ex(rl.Vector2(line_x, line_y), rl.Vector2(line_end, line_y), 2, t.BORDE)
