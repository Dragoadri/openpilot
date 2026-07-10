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

# ORBIT palette (stable; duplicated by design so this module stays leaf-level)
VOID = rl.Color(11, 18, 32, 255)         # #0B1220
NAVY = rl.Color(22, 35, 58, 255)         # #16233A
PANEL = rl.Color(27, 44, 72, 255)        # #1B2C48
HAIRLINE = rl.Color(43, 62, 95, 255)     # #2B3E5F
CYAN = rl.Color(34, 211, 238, 255)       # #22D3EE live pulse accent
BLUE_HI = rl.Color(125, 180, 255, 255)   # #7DB4FF uplink
GREEN = rl.Color(74, 222, 128, 255)      # #4ADE80 commands/downlink
INK = rl.Color(226, 236, 255, 255)       # #E2ECFF
MUTED = rl.Color(147, 180, 230, 255)     # #93B4E6
MUTED_DIM = rl.Color(92, 117, 153, 255)  # #5C7599
STAR = rl.Color(190, 215, 255, 255)      # starfield dots


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


# (outset px, alpha at strength=1) per glow layer, inner to outer
_GLOW_LAYERS = ((3, 0.22), (7, 0.12), (12, 0.06), (18, 0.03))


def draw_glow_rounded_rect(rect: rl.Rectangle, roundness: float, color: rl.Color,
                           strength: float, segments: int = 12) -> None:
  if strength <= 0.0:
    return
  for outset, a in _GLOW_LAYERS:
    grown = rl.Rectangle(rect.x - outset, rect.y - outset,
                         rect.width + 2 * outset, rect.height + 2 * outset)
    rl.draw_rectangle_rounded_lines_ex(grown, roundness, segments, 3, col(color, a * strength))


def draw_glow_circle(cx: float, cy: float, r: float, color: rl.Color, strength: float) -> None:
  if strength <= 0.0:
    return
  for mul, a in ((1.0, 0.30), (1.25, 0.16), (1.55, 0.07)):
    rl.draw_circle(int(cx), int(cy), r * mul, col(color, a * strength))


# Wordmark gradient (from the orbit-ui-mockup artifact, the design source of
# truth): white at the cap line -> pale blue at 70% -> uplink blue at the
# baseline. (fraction of text height, color) stops.
WORDMARK_STOPS = ((0.0, rl.Color(255, 255, 255, 255)),
                  (0.7, rl.Color(191, 214, 255, 255)),
                  (1.0, rl.Color(125, 180, 255, 255)))


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


def draw_card(rect: rl.Rectangle, *, accent: rl.Color, border: rl.Color | None = None,
              glow: float = 0.0, glow_color: rl.Color | None = None, alpha: float = 1.0,
              roundness: float = 0.10, segments: int = 12) -> None:
  """ORBIT card v2: optional halo + navy base + top light (accent-tinted
  vertical gradient over the upper 45%) + 2px top accent line + border."""
  draw_glow_rounded_rect(rect, roundness, glow_color or accent, glow * alpha, segments)
  rl.draw_rectangle_rounded(rect, roundness, segments, col(NAVY, alpha))
  inset = 24  # keeps the gradient/light off the rounded corners
  gx, gw = int(rect.x + inset), int(rect.width - 2 * inset)
  if gw > 0:
    rl.draw_rectangle_gradient_v(gx, int(rect.y + 3), gw, int(rect.height * 0.45),
                                 col(accent, 0.10 * alpha), col(accent, 0.0))
    rl.draw_rectangle(gx, int(rect.y + 1), gw, 2, col(accent, 0.45 * alpha))
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


class Cascade:
  """Staggered entrance: per-index (alpha01, rise-offset dy, scale) for t since show."""

  def __init__(self, stagger: float = 0.07, duration: float = 0.35, rise: float = 24.0):
    self.stagger = stagger
    self.duration = duration
    self.rise = rise

  def values(self, t_since_show: float, index: int) -> tuple[float, float, float]:
    e = ease_out_cubic((t_since_show - index * self.stagger) / self.duration)
    return e, (1.0 - e) * self.rise, 0.98 + 0.02 * e
