"""
ORBIT shared visual-FX helpers: easing, layered glow, card chrome, starfield.

Pure raylib primitives (no shaders, no new textures) so everything runs on the
comma 3X GLES stack. Animation is driven by a caller-provided time `t` in
seconds (typically time.monotonic()-relative); nothing here allocates per
frame — Starfield precomputes its elements at construction time with a fixed
seed so offscreen screenshots stay deterministic.
"""
from __future__ import annotations

import math
import random

import pyray as rl

from openpilot.selfdrive.ui import orbit_theme as t

# ORBIT palette: alias hacia los tokens unicos (paleta Grafito, ver orbit_theme.py).
# Los nombres se conservan para no romper a los consumidores de este modulo.
VOID = t.FONDO
NAVY = t.SUP1
PANEL = t.SUP2
HAIRLINE = t.BORDE
CYAN = t.PULSO
BLUE_HI = t.ACCION
GREEN = t.OK
INK = t.TEXTO1
MUTED = t.TEXTO2
MUTED_DIM = t.TEXTO3
STAR = t.TEXTO1


def clamp01(t: float) -> float:
  return 0.0 if t < 0.0 else (1.0 if t > 1.0 else t)


def ease_out_cubic(t: float) -> float:
  t = clamp01(t)
  return 1.0 - (1.0 - t) ** 3


def ease_out_back(t: float, s: float = 1.70158) -> float:
  # Slight overshoot ("spring"): f(0)=0, f(1)=1, peaks ~1.1 around t=0.7.
  t = clamp01(t)
  c3 = s + 1.0
  return 1.0 + c3 * (t - 1.0) ** 3 + s * (t - 1.0) ** 2


def pulse01(t: float, period: float) -> float:
  """0..1 sine pulse with the given period in seconds."""
  return 0.5 + 0.5 * math.sin(math.tau * t / period)


def col(c: rl.Color, a01: float) -> rl.Color:
  """Copy of c with alpha set to a01 (0..1) of full — rl.fade replaces alpha
  too but returns a struct we cannot build from tuples consistently."""
  return rl.Color(c.r, c.g, c.b, int(255 * clamp01(a01)))


def draw_glow_circle(cx: float, cy: float, r: float, color: rl.Color, strength: float) -> None:
  if strength <= 0.0:
    return
  for mul, a in ((1.0, 0.30), (1.25, 0.16), (1.55, 0.07)):
    rl.draw_circle(int(cx), int(cy), r * mul, col(color, a * strength))


# Wordmark gradient (from the orbit-ui-mockup artifact, the design source of
# truth): white at the cap line -> pale blue at 70% -> uplink blue at the
# baseline. (fraction of text height, color) stops.
WORDMARK_STOPS = ((0.0, rl.Color(255, 255, 255, 255)),
                  (0.7, t.mezcla(t.TEXTO1, 0.6, t.ACCION)),
                  (1.0, t.ACCION))


def lerp_stops(stops: tuple, f: float) -> rl.Color:
  """Piecewise-linear color for fraction f (0..1) along gradient stops."""
  for (f0, c0), (f1, c1) in zip(stops, stops[1:], strict=False):
    if f <= f1:
      t = (f - f0) / (f1 - f0) if f1 > f0 else 0.0
      return rl.Color(int(c0.r + (c1.r - c0.r) * t), int(c0.g + (c1.g - c0.g) * t),
                      int(c0.b + (c1.b - c0.b) * t), 255)
  return stops[-1][1]


def draw_text_gradient_v(font, text: str, pos, size: int, spacing: int, *,
                         width: float, height: float,
                         stops: tuple = WORDMARK_STOPS, alpha: float = 1.0,
                         bands: int = 12) -> None:
  """Vertical-gradient text fill (the CSS background-clip:text look): the same
  string is drawn once per horizontal band under a scissor, tinted with that
  band's gradient color. Cheap for short display strings like the wordmark.
  width/height are the RENDERED metrics — pass the measure_text_cached result
  (this module stays leaf-level, so it cannot apply FONT_SCALE itself)."""
  if alpha <= 0.0:
    return
  x, y, h = int(pos.x), int(pos.y), max(1.0, height)
  a255 = int(255 * clamp01(alpha))
  for i in range(bands):
    y0 = int(y + h * i / bands)
    y1 = int(y + h * (i + 1) / bands)
    if y1 <= y0:
      y1 = y0 + 1
    c = lerp_stops(stops, (i + 0.5) / bands)
    rl.begin_scissor_mode(x, y0, int(width) + 2, y1 - y0)
    rl.draw_text_ex(font, text, rl.Vector2(x, y), size, spacing,
                    rl.Color(c.r, c.g, c.b, a255))
    rl.end_scissor_mode()


def draw_card(rect: rl.Rectangle, *, border: rl.Color | None = None, alpha: float = 1.0,
              roundness: float = 0.10, segments: int = 12) -> None:
  """ORBIT card v2 (Grafito plana): relleno t.SUP1 + borde redondeado en
  `border` (t.BORDE por defecto). Sin degradado, sin línea superior, sin
  halo — nada de chrome, tal cual «tarjetas t.SUP1 con borde t.BORDE»."""
  rl.draw_rectangle_rounded(rect, roundness, segments, col(NAVY, alpha))
  rl.draw_rectangle_rounded_lines_ex(rect, roundness, segments, 2, col(border or HAIRLINE, alpha))


class Starfield:
  """Precomputed twinkling stars + slow giant orbital arcs (deterministic per seed)."""

  def __init__(self, n: int = 70, seed: int = 1234, rings: int = 3):
    rng = random.Random(seed)
    # (x frac, y frac, radius px, twinkle phase, twinkle speed rad/s, drift frac/s)
    self.stars = [(rng.random(), rng.random(), rng.uniform(1.0, 2.6),
                   rng.uniform(0.0, math.tau), rng.uniform(0.4, 1.4), rng.uniform(0.002, 0.008))
                  for _ in range(n)]
    # (cx frac, cy frac, radius frac of max dim, span deg, speed deg/s signed, start deg)
    self.rings = [(rng.uniform(0.1, 0.9), rng.uniform(-0.2, 1.2), rng.uniform(0.35, 0.75),
                   rng.uniform(60.0, 150.0), rng.uniform(2.0, 4.0) * (1.0 if i % 2 == 0 else -1.0),
                   rng.uniform(0.0, 360.0))
                  for i in range(rings)]

  def render(self, rect: rl.Rectangle, t: float, intensity: float = 1.0) -> None:
    if intensity <= 0.0:
      return
    for x0, y0, r, phase, speed, drift in self.stars:
      x = rect.x + ((x0 + t * drift) % 1.0) * rect.width
      y = rect.y + y0 * rect.height
      a = (0.30 + 0.30 * math.sin(t * speed + phase)) * intensity
      rl.draw_circle(int(x), int(y), r, col(STAR, a))
    dim = max(rect.width, rect.height)
    for cxf, cyf, rf, span, dps, a0 in self.rings:
      center = rl.Vector2(rect.x + cxf * rect.width, rect.y + cyf * rect.height)
      radius = rf * dim
      start = (a0 + t * dps) % 360.0
      rl.draw_ring(center, radius - 1.5, radius, start, start + span, 64, col(CYAN, 0.06 * intensity))


class CampoOrbital:
  """Campo orbital del home offroad: estrellas quietas + tres órbitas
  inclinadas en el color de la sección + el satélite de ESTE coche (su
  enlace ORBIT). Puerto de OrbitFieldPainter (app/lib/theme/orbit_field.dart),
  con un único satélite (no hay flota que pintar en el firmware).
  Precomputado en construcción con seed fija -> determinista para tests."""

  # Semiejes (a, b) de las tres órbitas, tal cual el lienzo de la app,
  # escalados x1.6 para el lienzo 2160x1080 del firmware.
  _ESCALA = 1.6
  _ORBITAS = ((120 * _ESCALA, 40 * _ESCALA), (205 * _ESCALA, 70 * _ESCALA), (300 * _ESCALA, 104 * _ESCALA))
  _INCLINACION = math.radians(-14)
  _SEGMENTOS = 72
  _PERIODO_SATELITE = 40.0  # s: vuelta completa del satélite en la órbita interior (F-R6: se ve casi toda la vuelta)

  def __init__(self, seed: int = 7, n: int = 60):
    rng = random.Random(seed)
    # (x frac, y frac, radio px, color) — estrellas quietas, sin parpadeo:
    # el color (STAR a un alfa fijo) no cambia frame a frame, se precalcula aqui.
    self.estrellas = [(rng.random(), rng.random(), rng.uniform(0.4, 1.6), col(STAR, rng.uniform(0.05, 0.15)))
                      for _ in range(n)]
    # Cache de los puntos de las 3 elipses, valida mientras no cambien centro/escala.
    self._orbita_cache_clave: tuple[float, float, float] | None = None
    self._orbita_cache_pts: list[list[rl.Vector2]] = []

  def _punto(self, centro: tuple[float, float], a: float, b: float, angulo: float) -> tuple[float, float]:
    x, y = a * math.cos(angulo), b * math.sin(angulo)
    ci, si = math.cos(self._INCLINACION), math.sin(self._INCLINACION)
    return (centro[0] + x * ci - y * si, centro[1] + x * si + y * ci)

  def render(self, rect: rl.Rectangle, centro: rl.Vector2, color: rl.Color, t: float,
             conectado: bool) -> None:
    for x01, y01, r, color_estrella in self.estrellas:
      x = rect.x + x01 * rect.width
      y = rect.y + y01 * rect.height
      rl.draw_circle(int(x), int(y), r, color_estrella)

    cxy = (centro.x, centro.y)
    clave = (cxy[0], cxy[1], self._ESCALA)
    if clave != self._orbita_cache_clave:
      self._orbita_cache_clave = clave
      self._orbita_cache_pts = [
        [rl.Vector2(*self._punto(cxy, a, b, i / self._SEGMENTOS * math.tau)) for i in range(self._SEGMENTOS + 1)]
        for a, b in self._ORBITAS
      ]

    orbita_color = col(color, 0.20)
    for pts in self._orbita_cache_pts:
      for p0, p1 in zip(pts, pts[1:], strict=False):
        rl.draw_line_ex(p0, p1, 1.5, orbita_color)

    # F-R6: el satélite viaja por la órbita interior (la más pequeña), no la
    # del medio, para que quede visible la mayor parte de la vuelta.
    a_int, b_int = self._ORBITAS[0]
    if conectado:
      angulo = (t / self._PERIODO_SATELITE) * math.tau
      px, py = self._punto(cxy, a_int, b_int, angulo)
      rl.draw_circle(int(px), int(py), 18, col(CYAN, 0.35))
      rl.draw_circle(int(px), int(py), 5, CYAN)
    else:
      # Sin conexión: anillo hueco quieto (nada que sugiera un enlace vivo).
      px, py = self._punto(cxy, a_int, b_int, 0.0)
      rl.draw_ring(rl.Vector2(px, py), 3.5, 5.0, 0, 360, 24, col(MUTED_DIM, 0.60))


class Cascade:
  """Staggered entrance: per-index (alpha01, rise-offset dy, scale) for t since show."""

  def __init__(self, stagger: float = 0.07, duration: float = 0.35, rise: float = 24.0):
    self.stagger = stagger
    self.duration = duration
    self.rise = rise

  def values(self, t_since_show: float, index: int) -> tuple[float, float, float]:
    e = ease_out_cubic((t_since_show - index * self.stagger) / self.duration)
    return e, (1.0 - e) * self.rise, 0.98 + 0.02 * e
