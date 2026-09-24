"""
Tokens del rediseño «Órbita · Grafito»: la misma identidad que la app ORBIT.

Módulo hoja (solo importa pyray): es la ÚNICA fuente de color de la UI ORBIT
del firmware. Antes la paleta navy estaba copiada a mano en cinco ficheros.
Los colores de sección orientan («estás en el Mando»); nunca son relleno de
botón, texto de estado ni borde con significado.
"""
from __future__ import annotations

import pyray as rl


def _c(rgb: int, a: int = 255) -> rl.Color:
  return rl.Color((rgb >> 16) & 0xFF, (rgb >> 8) & 0xFF, rgb & 0xFF, a)


FONDO = _c(0x0A0E14)
SUP1 = _c(0x131A24)          # tarjeta
SUP2 = _c(0x19222F)          # fila abierta, input
SUP3 = _c(0x212C3C)          # pulsado, hoja, diálogo
BORDE = _c(0x263243)         # decorativo
BORDE_FUERTE = _c(0x6E7F97)  # límite de un control (≥ 3:1)
TEXTO1 = _c(0xE8EEF6)
TEXTO2 = _c(0xA2B1C6)
TEXTO3 = _c(0x93A2B8)
PULSO = _c(0x22D3EE)         # marca, foco, «en vivo»
ACCION = _c(0x86B9F7)        # botón principal
SOBRE_ACCION = _c(0x05141E)  # texto sobre ACCION
OK = _c(0x4ADE80)            # solo «el coche lo confirmó» (y la bajada del logo)
OK_PROFUNDO = _c(0x16A34A)   # solo degradado de la bajada del logo
AVISO = _c(0xF5C842)
PELIGRO = _c(0xFF8A8A)       # tinta de fallo
FRENO = _c(0xB91C1C)         # ÚNICO relleno rojo (freno, destructivo)
SOBRE_FRENO = _c(0xFFFFFF)
AZUL_PROFUNDO = _c(0x2563EB)  # solo degradado de la subida del logo

SECCION: dict[str, rl.Color] = {
  'vehiculo': _c(0x86B9F7),
  'mapa': _c(0x86DCCB),
  'viajes': _c(0xF2BE9E),
  'cabina': PULSO,
  'mando': _c(0xB3A7F2),
  'registro': _c(0xE9A3CF),
  'ajustes': _c(0xB5C0CE),
  'cuenta': _c(0xD9B6F2),
  'ayuda': _c(0xF4CDDF),
  'desarrollo': _c(0xCDD5DF),
}


def con_alfa(c: rl.Color, a01: float) -> rl.Color:
  a01 = 0.0 if a01 < 0.0 else (1.0 if a01 > 1.0 else a01)
  return rl.Color(c.r, c.g, c.b, int(255 * a01))


def mezcla(fg: rl.Color, alfa: float, fondo: rl.Color) -> rl.Color:
  """fg al `alfa` compuesto sobre un fondo opaco."""
  m = lambda a, b: round(alfa * a + (1 - alfa) * b)
  return rl.Color(m(fg.r, fondo.r), m(fg.g, fondo.g), m(fg.b, fondo.b), 255)


def _luminancia(c: rl.Color) -> float:
  def canal(v: int) -> float:
    s = v / 255
    return s / 12.92 if s <= 0.04045 else ((s + 0.055) / 1.055) ** 2.4
  return 0.2126 * canal(c.r) + 0.7152 * canal(c.g) + 0.0722 * canal(c.b)


def contraste(a: rl.Color, b: rl.Color) -> float:
  la, lb = _luminancia(a), _luminancia(b)
  claro, oscuro = max(la, lb), min(la, lb)
  return (claro + 0.05) / (oscuro + 0.05)
