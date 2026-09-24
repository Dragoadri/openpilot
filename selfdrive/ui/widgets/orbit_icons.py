"""
Iconos propios de ORBIT en raylib (spec «Órbita · Grafito» §3.5, puerto de
app/lib/theme/orbit_icon.dart, función `_dibujarGlifo`). Rejilla de 24×24,
trazo 1,75 escalado a `tam`, tinta en TEXTO1 por defecto y acento en el color
de la sección. Con `orbita` se añade la elipse orbital (rx19 ry7 −24°) con un
satélite que sobresale de la caja del glifo — mismo lenguaje visual que
`orbit_duplex`, en miniatura.

Hoja: solo importa `orbit_theme`.
"""
from __future__ import annotations

import math

import pyray as rl

from openpilot.selfdrive.ui import orbit_theme as ot

GLIFOS = ('vehiculo', 'mapa', 'cuenta', 'cabina', 'mando', 'registro',
          'viajes', 'ajustes', 'ayuda', 'desarrollo', 'enlace')

_ORBITA_RX = 19.0
_ORBITA_RY = 7.0
_ORBITA_GRADOS = -24.0
_ORBITA_ROT = math.radians(_ORBITA_GRADOS)


def posicion_satelite(angulo: float) -> tuple[float, float]:
  """Punto del satélite sobre la órbita de un icono (rejilla 24, centro 12,12)."""
  x = math.cos(angulo) * _ORBITA_RX
  y = math.sin(angulo) * _ORBITA_RY
  cr, sr = math.cos(_ORBITA_ROT), math.sin(_ORBITA_ROT)
  return (12 + x * cr - y * sr, 12 + x * sr + y * cr)


def _bezier(p0: tuple[float, float], p1: tuple[float, float],
           p2: tuple[float, float], p3: tuple[float, float],
           pasos: int = 12) -> list[tuple[float, float]]:
  """Muestrea una cúbica de Bézier en `pasos` segmentos (sin incluir p0)."""
  pts = []
  for i in range(1, pasos + 1):
    tt = i / pasos
    mt = 1 - tt
    x = mt**3 * p0[0] + 3 * mt * mt * tt * p1[0] + 3 * mt * tt * tt * p2[0] + tt**3 * p3[0]
    y = mt**3 * p0[1] + 3 * mt * mt * tt * p1[1] + 3 * mt * tt * tt * p2[1] + tt**3 * p3[1]
    pts.append((x, y))
  return pts


# Puntos (dx, dy) de la elipse orbital ya rotados y escalados, cacheados por
# `s` (== tam/24): el offset (cx, cy) del icono se aplica en el draw, no aqui.
_CACHE_ELIPSE_ORBITA: dict[float, list[tuple[float, float]]] = {}


def _puntos_elipse_orbita(s: float) -> list[tuple[float, float]]:
  pts = _CACHE_ELIPSE_ORBITA.get(s)
  if pts is None:
    cr, sr = math.cos(_ORBITA_ROT), math.sin(_ORBITA_ROT)
    n = 64
    pts = []
    for i in range(n + 1):
      a = 2 * math.pi * i / n
      lx, ly = math.cos(a) * _ORBITA_RX, math.sin(a) * _ORBITA_RY
      rx_, ry_ = lx * cr - ly * sr, lx * sr + ly * cr
      pts.append((rx_ * s, ry_ * s))
    _CACHE_ELIPSE_ORBITA[s] = pts
  return pts


def _elipse_orbita(cx: float, cy: float, s: float, acento: rl.Color) -> None:
  color = ot.con_alfa(acento, 0.35)
  grosor = 1.0 * s
  pts = [rl.Vector2(cx + dx, cy + dy) for dx, dy in _puntos_elipse_orbita(s)]
  for a, b in zip(pts, pts[1:], strict=False):
    rl.draw_line_ex(a, b, grosor, color)


def draw_orbit_icon(glifo: str, x: float, y: float, tam: float, acento: rl.Color,
                    tinta: rl.Color = ot.TEXTO1, orbita: bool = False, t: float = 0.0) -> None:
  """Dibuja `glifo` en la caja de lado `tam` con esquina superior izquierda
  (x, y). Con `orbita`, la elipse orbital y el satélite sobresalen de esa
  caja (caja efectiva `tam*44/24`, centrada en el mismo punto que la caja
  del glifo — el centro de la rejilla no se mueve)."""
  s = tam / 24.0
  cx, cy = x + tam / 2, y + tam / 2
  grosor = 1.75 * s

  def p(lx: float, ly: float) -> rl.Vector2:
    return rl.Vector2(cx + (lx - 12) * s, cy + (ly - 12) * s)

  def linea(x1: float, y1: float, x2: float, y2: float, color: rl.Color, g: float = grosor) -> None:
    a, b = p(x1, y1), p(x2, y2)
    rl.draw_line_ex(a, b, g, color)
    rl.draw_circle_v(a, g / 2, color)
    rl.draw_circle_v(b, g / 2, color)

  def trazo(puntos: list[tuple[float, float]], color: rl.Color, g: float = grosor) -> None:
    """Polilínea (ya con las cúbicas muestreadas) con extremos y uniones
    redondeados, como el trazo `round` de Flutter."""
    pts = [p(lx, ly) for lx, ly in puntos]
    for a, b in zip(pts, pts[1:], strict=False):
      rl.draw_line_ex(a, b, g, color)
    for v in pts:
      rl.draw_circle_v(v, g / 2, color)

  def circulo_lleno(lx: float, ly: float, r: float, color: rl.Color) -> None:
    rl.draw_circle_v(p(lx, ly), r * s, color)

  def circulo_trazo(lx: float, ly: float, r: float, color: rl.Color, g: float = grosor) -> None:
    rl.draw_ring(p(lx, ly), r * s - g / 2, r * s + g / 2, 0, 360, 32, color)

  def arco(lcx: float, lcy: float, r: float, a0: float, a1: float,
          color: rl.Color, g: float = grosor) -> None:
    centro = p(lcx, lcy)
    rl.draw_ring(centro, r * s - g / 2, r * s + g / 2, a0, a1, 48, color)
    for angulo in (a0, a1):
      rad = math.radians(angulo)
      punta = rl.Vector2(centro.x + r * s * math.cos(rad), centro.y + r * s * math.sin(rad))
      rl.draw_circle_v(punta, g / 2, color)

  def flecha(lcx: float, lcy: float, r: float, angulo_deg: float,
            color: rl.Color, largo: float = 3.6) -> None:
    """Punta de flecha tangente a la circunferencia (lcx,lcy,r) en
    `angulo_deg`, apuntando en sentido de ángulo decreciente."""
    rad = math.radians(angulo_deg)
    dirf = (math.sin(rad), -math.cos(rad))
    perp = (math.cos(rad), math.sin(rad))
    base = (lcx + r * math.cos(rad), lcy + r * math.sin(rad))
    punta = (base[0] + dirf[0] * largo * 0.6, base[1] + dirf[1] * largo * 0.6)
    izq = (base[0] - dirf[0] * largo * 0.4 + perp[0] * largo * 0.4,
          base[1] - dirf[1] * largo * 0.4 + perp[1] * largo * 0.4)
    der = (base[0] - dirf[0] * largo * 0.4 - perp[0] * largo * 0.4,
          base[1] - dirf[1] * largo * 0.4 - perp[1] * largo * 0.4)
    rl.draw_triangle(p(*izq), p(*punta), p(*der), color)

  if orbita:
    _elipse_orbita(cx, cy, s, acento)

  if glifo == 'vehiculo':
    trazo([(4.5, 17.5), (4.5, 12.5), (6.5, 7.3),
          *_bezier((6.5, 7.3), (6.8, 6.5), (7.5, 6.0), (8.4, 6.0)),
          (15.6, 6.0),
          *_bezier((15.6, 6.0), (16.5, 6.0), (17.2, 6.5), (17.5, 7.3)),
          (19.5, 12.5), (19.5, 17.5)], tinta)
    linea(4.5, 12.5, 19.5, 12.5, tinta)
    linea(6.5, 17.5, 6.5, 19.3, tinta)
    linea(17.5, 17.5, 17.5, 19.3, tinta)
    circulo_lleno(8, 15.2, 1.2, acento)
    circulo_lleno(16, 15.2, 1.2, acento)
  elif glifo == 'mapa':
    trazo([(12, 21), *_bezier((12, 21), (12, 21), (6, 15.4), (6, 10.5))], tinta)
    arco(12, 10.5, 6, 180, 360, tinta)
    trazo([(18, 10.5), *_bezier((18, 10.5), (18, 15.4), (12, 21), (12, 21))], tinta)
    circulo_trazo(12, 10.5, 2.2, acento)
  elif glifo == 'cuenta':
    circulo_trazo(12, 8.5, 3.5, tinta)
    trazo([(5, 20), *_bezier((5, 20), (5.8, 16.4), (8.6, 14.5), (12, 14.5)),
          *_bezier((12, 14.5), (15.4, 14.5), (18.2, 16.4), (19, 20))], tinta)
  elif glifo == 'cabina':
    arco(12, 16, 7.5, 180, 360, tinta)
    linea(6.2, 11.2, 7.2, 11.8, tinta)
    linea(12, 6.8, 12, 8.0, tinta)
    linea(17.8, 11.2, 16.8, 11.8, tinta)
    linea(12, 16, 15.4, 11.6, acento)
    circulo_lleno(12, 16, 1.6, acento)
  elif glifo == 'mando':
    circulo_trazo(12, 12, 8, tinta)
    arco(12, 12, 8, 270, 360, acento)
    circulo_lleno(12, 12, 2.6, acento)
  elif glifo == 'registro':
    linea(7, 5, 7, 19, tinta)
    linea(11, 7, 18, 7, tinta)
    linea(11, 12, 16, 12, tinta)
    linea(11, 17, 17, 17, tinta)
    circulo_lleno(7, 7, 1.7, acento)
    circulo_lleno(7, 12, 1.7, acento)
    circulo_lleno(7, 17, 1.7, acento)
  elif glifo == 'viajes':
    trazo([(6, 19), *_bezier((6, 19), (6, 15.5), (18, 16), (18, 11.5)),
          *_bezier((18, 11.5), (18, 7), (12, 8), (12, 6.8))], tinta)
    circulo_trazo(12, 4.9, 1.9, acento)
    circulo_lleno(6, 19, 1.7, acento)
  elif glifo == 'ajustes':
    linea(4, 8, 6.8, 8, tinta)
    linea(11.2, 8, 20, 8, tinta)
    linea(4, 16, 12.8, 16, tinta)
    linea(17.2, 16, 20, 16, tinta)
    circulo_trazo(9, 8, 2.2, tinta)
    circulo_trazo(15, 16, 2.2, acento)
  elif glifo == 'ayuda':
    circulo_trazo(12, 12, 8, tinta)
    # arcToPoint(9.8,9.6 -> 13.0,11.7, r2.3, largeArc) resuelto a centro+ángulos
    # (parametrización SVG estándar, radios/ángulos calculados aparte).
    arco(12.0999, 9.5834, 2.3, 179.5871, 426.9627, tinta)
    trazo([(13.0, 11.7), *_bezier((13.0, 11.7), (12.4, 12.0), (12.0, 12.5), (12.0, 13.2)),
          (12, 13.6)], tinta)
    circulo_lleno(12, 16.4, 1.1, acento)
  elif glifo == 'desarrollo':
    trazo([(8.5, 8), (4.5, 12), (8.5, 16)], tinta)
    trazo([(15.5, 8), (19.5, 12), (15.5, 16)], tinta)
    linea(13.2, 6.2, 10.8, 17.8, acento)
  elif glifo == 'enlace':
    # Nuevo (no está en el Dart): Dúplex en miniatura — bajada a la
    # izquierda en tinta (de arriba abajo), subida a la derecha en acento
    # (de abajo arriba), cada una con su punta de flecha, más el punto
    # central acento. Mismos tramos angulares que orbit_duplex a dibujo=1.0.
    arco(12, 12, 8, 120, 240, tinta)
    flecha(12, 12, 8, 120, tinta)
    arco(12, 12, 8, -60, 60, acento)
    flecha(12, 12, 8, -60, acento)
    circulo_lleno(12, 12, 1.8, acento)

  if orbita:
    angulo = t * 2 * math.pi / 6
    sx, sy = posicion_satelite(angulo)
    rl.draw_circle_v(p(sx, sy), 2.6 * s, acento)
