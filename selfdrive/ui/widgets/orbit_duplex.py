"""
Anillo Dúplex y logo animado «La órbita se cierra», en primitivas raylib.

Gramática (spec «Órbita · Grafito» §4, puerto de app/lib/theme/duplex_ring.dart):
la BAJADA (arco izquierdo, de arriba abajo) son tus órdenes descendiendo al
coche; la SUBIDA (arco derecho, de abajo arriba) es la telemetría que sube
desde el coche; el NÚCLEO (círculo central) es el propio coche.

Ángulos en grados raylib: 0° = derecha, positivo = sentido horario en
pantalla — la misma orientación que los radianes de `Canvas.drawArc` en
Flutter, así que los tramos angulares se copian tal cual del original.
"""
from __future__ import annotations

import math

import pyray as rl

from openpilot.selfdrive.ui import orbit_theme as ot
from openpilot.selfdrive.ui.widgets import orbit_fx as fx

# Geometría fija del SVG del logo (caja 240×240, centro 120,120, anillo r76).
_CAJA = 240.0
_R_ANILLO = 76.0
_ECG_IZQ = ((103, 120), (90, 120), (85, 129), (80, 111), (75, 120), (62, 120))
_ECG_DER = ((137, 120), (150, 120), (155, 111), (160, 129), (165, 120), (178, 120))
_CABEZA_BAJADA = ((91.5, 191.3), (83.9, 176.5), (74.9, 192.1))
_CABEZA_SUBIDA = ((148.5, 48.7), (156.1, 63.5), (165.1, 47.9))

# Línea de tiempo del logo, en fracciones de los 1,4 s totales.
_FIN_ANILLO = 0.214
_FIN_ARCOS = 0.5
_INI_CABEZAS, _FIN_CABEZAS = 0.464, 0.571
_INI_NUCLEO, _FIN_NUCLEO = 0.5, 0.679
_INI_PULSO, _FIN_PULSO = 0.571, 0.786


def _acota01(p: float) -> float:
  return 0.0 if p < 0.0 else (1.0 if p > 1.0 else p)


def _tramo(v: float, desde: float, hasta: float) -> float:
  """Fracción 0..1 de `v` dentro de [desde, hasta], acotada."""
  return _acota01((v - desde) / (hasta - desde))


def tramo_bajada(p: float) -> tuple[float, float]:
  """(inicio, fin) en grados del arco de bajada a progreso p ∈ [0,1]."""
  p = _acota01(p)
  return (240.0 - 120.0 * p, 240.0)


def tramo_subida(p: float) -> tuple[float, float]:
  """(inicio, fin) en grados del arco de subida a progreso p ∈ [0,1]."""
  p = _acota01(p)
  return (60.0 - 120.0 * p, 60.0)


def punto(cx: float, cy: float, r: float, grados: float) -> tuple[float, float]:
  rad = math.radians(grados)
  return (cx + r * math.cos(rad), cy + r * math.sin(rad))


def _lerp_color(a: rl.Color, b: rl.Color, f: float) -> rl.Color:
  f = _acota01(f)
  m = lambda x, y: round(x + (y - x) * f)
  return rl.Color(m(a.r, b.r), m(a.g, b.g), m(a.b, b.b), m(a.a, b.a))


def _color_en_angulo(angulo: float, ang_a: float, color_a: rl.Color,
                     ang_b: float, color_b: rl.Color) -> rl.Color:
  return _lerp_color(color_a, color_b, (angulo - ang_a) / (ang_b - ang_a))


def _extremo_redondo(center: rl.Vector2, radio: float, grosor: float, angulo: float,
                     color: rl.Color) -> None:
  px, py = punto(center.x, center.y, radio - grosor / 2, angulo)
  rl.draw_circle_v(rl.Vector2(px, py), grosor / 2, color)


def _draw_arco_con_tapas(center: rl.Vector2, radio: float, grosor: float,
                         ini_fin: tuple[float, float], color: rl.Color) -> None:
  ini, fin = ini_fin
  if fin <= ini:
    return
  rl.draw_ring(center, radio - grosor, radio, ini, fin, 64, color)
  _extremo_redondo(center, radio, grosor, ini, color)
  _extremo_redondo(center, radio, grosor, fin, color)


def _draw_arco_degradado(center: rl.Vector2, radio: float, grosor: float,
                         ini_fin: tuple[float, float],
                         ang_a: float, color_a: rl.Color,
                         ang_b: float, color_b: rl.Color, segmentos: int = 12) -> None:
  ini, fin = ini_fin
  if fin <= ini:
    return
  paso = (fin - ini) / segmentos
  for i in range(segmentos):
    a0 = ini + paso * i
    a1 = a0 + paso
    color = _color_en_angulo((a0 + a1) / 2, ang_a, color_a, ang_b, color_b)
    rl.draw_ring(center, radio - grosor, radio, a0, a1, 4, color)


def _trazar_parcial(pts_pantalla: tuple[tuple[float, float], ...], frac: float,
                    grosor: float, color: rl.Color) -> None:
  """Dibuja los primeros `frac` (0..1) del largo total de la polilínea."""
  if frac <= 0.0:
    return
  segs = list(zip(pts_pantalla, pts_pantalla[1:], strict=False))
  total = sum(math.dist(a, b) for a, b in segs)
  if total <= 0.0:
    return
  objetivo = total * min(frac, 1.0)
  recorrido = 0.0
  for a, b in segs:
    largo = math.dist(a, b)
    if recorrido + largo <= objetivo:
      rl.draw_line_ex(rl.Vector2(*a), rl.Vector2(*b), grosor, color)
      recorrido += largo
    else:
      restante = objetivo - recorrido
      if restante <= 0.0:
        break
      f = restante / largo
      rl.draw_line_ex(rl.Vector2(*a), rl.Vector2(a[0] + (b[0] - a[0]) * f,
                                                  a[1] + (b[1] - a[1]) * f), grosor, color)
      break


def draw_duplex_ring(cx: float, cy: float, radio: float, subida_activa: bool,
                     dibujo: float = 1.0) -> None:
  """El anillo del coche (home / ficha). `radio` = r76 del SVG ya escalado."""
  center = rl.Vector2(cx, cy)

  anillo_f = _tramo(dibujo, 0.0, 0.3)
  arcos_f = _tramo(dibujo, 0.3, 0.7)
  nucleo_f = _tramo(dibujo, 0.6, 0.9)

  if anillo_f > 0.0:
    grosor = radio * 3 / 76
    rl.draw_ring(center, radio - grosor, radio, -90, -90 + 360 * anillo_f, 64,
                ot.con_alfa(ot.TEXTO2, 0.25))

  if arcos_f > 0.0:
    grosor = radio * 13 / 76
    color_subida = ot.ACCION if subida_activa else ot.con_alfa(ot.TEXTO2, 0.30)
    # Nunca verde aquí: el verde solo significa «el coche lo confirmó».
    _draw_arco_con_tapas(center, radio, grosor, tramo_bajada(arcos_f), ot.con_alfa(ot.TEXTO2, 0.70))
    _draw_arco_con_tapas(center, radio, grosor, tramo_subida(arcos_f), color_subida)

  if nucleo_f > 0.0:
    rl.draw_circle_v(center, radio * 44 / 76, ot.con_alfa(ot.PULSO, 0.12 * nucleo_f))
    rl.draw_circle_v(center, radio * 30 / 76, ot.con_alfa(ot.FONDO, nucleo_f))
    grosor_aro = radio * 4 / 76
    r_aro = radio * 30 / 76
    rl.draw_ring(center, r_aro - grosor_aro, r_aro, 0, 360, 48, ot.con_alfa(ot.TEXTO1, nucleo_f))
    rl.draw_circle_v(center, radio * 10 / 76, ot.con_alfa(ot.PULSO, nucleo_f))


def draw_orbit_logo(cx: float, cy: float, tam: float, t: float) -> None:
  """Momento «La órbita se cierra»: t ∈ [0,1] son los 1,4 s de la animación."""
  s = tam / _CAJA
  center = rl.Vector2(cx, cy)

  def p(sx: float, sy: float) -> tuple[float, float]:
    return (cx + (sx - 120.0) * s, cy + (sy - 120.0) * s)

  anillo = _tramo(t, 0.0, _FIN_ANILLO)
  arcos = fx.ease_out_cubic(_tramo(t, _FIN_ANILLO, _FIN_ARCOS))
  cabezas = _tramo(t, _INI_CABEZAS, _FIN_CABEZAS)
  nucleo = fx.ease_out_cubic(_tramo(t, _INI_NUCLEO, _FIN_NUCLEO))
  pulso = _tramo(t, _INI_PULSO, _FIN_PULSO)

  if anillo > 0.0:
    radio = s * _R_ANILLO
    rl.draw_ring(center, radio - 2 * s, radio, -90, -90 + 360 * anillo, 64,
                ot.con_alfa(ot.TEXTO2, 0.18))

  if nucleo > 0.0:
    # Resplandor plano tras el núcleo (paridad con OrbitLogoPainter de la app:
    # radial pulse->transparente, r40 en la caja 240×240), antes del ECG/arcos.
    rl.draw_circle_gradient(center, 40 * s, ot.con_alfa(ot.PULSO, 0.42 * nucleo),
                            ot.con_alfa(ot.PULSO, 0.0))

  if arcos > 0.0:
    grosor = 13 * s
    radio = s * _R_ANILLO
    _draw_arco_degradado(center, radio, grosor, tramo_bajada(arcos), 240, ot.OK, 120, ot.OK_PROFUNDO)
    _draw_arco_degradado(center, radio, grosor, tramo_subida(arcos), 60, ot.AZUL_PROFUNDO, -60, ot.ACCION)

  if cabezas > 0.0:
    v0, v1, v2 = (p(*pt) for pt in _CABEZA_BAJADA)
    rl.draw_triangle(rl.Vector2(*v0), rl.Vector2(*v1), rl.Vector2(*v2), ot.con_alfa(ot.OK, cabezas))
    v0, v1, v2 = (p(*pt) for pt in _CABEZA_SUBIDA)
    rl.draw_triangle(rl.Vector2(*v0), rl.Vector2(*v1), rl.Vector2(*v2), ot.con_alfa(ot.ACCION, cabezas))

  if pulso > 0.0:
    grosor = 3 * s
    _trazar_parcial(tuple(p(*pt) for pt in _ECG_IZQ), pulso, grosor, ot.PULSO)
    _trazar_parcial(tuple(p(*pt) for pt in _ECG_DER), pulso, grosor, ot.PULSO)

  if nucleo > 0.0:
    escala = 0.6 + 0.4 * nucleo
    rl.draw_circle_v(center, 17 * s * escala, ot.con_alfa(ot.FONDO, nucleo))
    grosor_aro = 5 * s * escala
    r_aro = 17 * s * escala
    rl.draw_ring(center, r_aro - grosor_aro, r_aro, 0, 360, 32, ot.con_alfa(ot.TEXTO1, nucleo))
    rl.draw_circle_v(center, 6.5 * s * escala, ot.con_alfa(ot.PULSO, nucleo))
