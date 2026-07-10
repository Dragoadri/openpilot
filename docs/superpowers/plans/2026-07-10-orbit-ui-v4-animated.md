# ORBIT UI v4 (animada) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rediseño "profundidad y brillo, todo animado" de splash, home y menú de settings de la UI offroad ORBIT (spec: `docs/superpowers/specs/2026-07-10-orbit-ui-v4-animated-design.md`).

**Architecture:** Un módulo FX compartido nuevo (`orbit_fx.py`: easing, glow por capas, tarjeta v2 con gradiente, starfield orbital, cascada) consumido por tres pantallas: reescritura del splash como secuencia por fases, home con fondo vivo + cascada de entrada + tarjetas v2, y menú SP con marcador deslizante + transición de panel. Todo con primitivas raylib (sin shaders/texturas nuevas), tiempos vía `time.monotonic()`.

**Tech Stack:** Python 3.12, pyray/raylib 6 (bindings cffi), Params de openpilot, pytest. Verificación visual con harness offscreen + `rl.take_screenshot`.

## Global Constraints

- **Commits SOLO como `dragoadri <dragoadri@gmail.com>`. PROHIBIDA cualquier atribución a IA** (nada de `Co-Authored-By: Claude`, nada de "Generated with Claude Code") — regla dura de `CLAUDE.md`.
- Push (si se pide) siempre con `git push --no-verify` (hook LFS sin acceso de escritura).
- Texto renderizado: **solo ASCII** (fuentes bitmap `.fnt`; `—`/`…`/flechas unicode se pintan como `?`). Los `"..."` de `_ellipsize` ya son ASCII.
- Cero allocations por frame en render loops; `measure_text_cached` solo con strings estables (el tracking animado del wordmark usa spacing entero → máx. ~39 claves de caché, acotado).
- NO tocar: HUD onroad, overlay de comandos, diálogo QR, paneles interiores de settings, atributos de `system/ui/sunnypilot/lib/styles.py` (solo valores, nunca nombres — en este plan ni valores).
- Python del repo: `/home/drago/Escritorio/ORBITPILOT/.venv/bin/python`; ejecutar siempre con `PYTHONPATH=/home/drago/Escritorio/ORBITPILOT`.
- Firma de gradiente confirmada en esta build: `rl.draw_rectangle_gradient_v(x:int, y:int, w:int, h:int, top:Color, bottom:Color)` (uso idéntico en `selfdrive/ui/onroad/hud_renderer.py:106`); `rl.fade(color, a01)` REEMPLAZA el alpha (no multiplica).
- Scratchpad de la sesión (harness, capturas temporales): `/tmp/claude-1000/-home-drago-Escritorio-ORBITPILOT/25f0eabe-6c71-4ca1-87c6-0da4c11ff14b/scratchpad` — abreviado `<SCRATCH>` en los comandos.

---

### Task 1: Módulo FX compartido `orbit_fx.py` (TDD)

**Files:**
- Create: `selfdrive/ui/widgets/orbit_fx.py`
- Test: `selfdrive/ui/tests/test_orbit_fx.py`

**Interfaces:**
- Consumes: nada del repo (módulo hoja: solo `math`, `random`, `pyray`).
- Produces (usado por Tasks 3–5):
  - Constantes de color `rl.Color`: `VOID, NAVY, PANEL, HAIRLINE, CYAN, BLUE_HI, GREEN, INK, MUTED, MUTED_DIM, STAR`
  - `clamp01(t: float) -> float`, `ease_out_cubic(t: float) -> float`, `ease_out_back(t: float, s: float = 1.70158) -> float`, `pulse01(t: float, period: float) -> float`
  - `col(c: rl.Color, a01: float) -> rl.Color` (copia con alpha = a01·255)
  - `draw_glow_rounded_rect(rect, roundness, color, strength, segments=12) -> None`
  - `draw_glow_circle(cx, cy, r, color, strength) -> None`
  - `draw_card(rect, *, accent, border=None, glow=0.0, glow_color=None, alpha=1.0, roundness=0.10, segments=12) -> None`
  - `class Starfield(n=70, seed=1234, rings=3)` con atributos `stars`, `rings` y método `render(rect, t, intensity=1.0)`
  - `class Cascade(stagger=0.07, duration=0.35, rise=24.0)` con `values(t_since_show, index) -> (alpha01, dy, scale)`

- [ ] **Step 1: Escribir los tests que fallan**

Crear `selfdrive/ui/tests/test_orbit_fx.py`:

```python
from openpilot.selfdrive.ui.widgets import orbit_fx as fx


def test_easing_endpoints_and_clamping():
  assert fx.ease_out_cubic(0.0) == 0.0
  assert fx.ease_out_cubic(1.0) == 1.0
  assert fx.ease_out_cubic(-1.0) == 0.0   # clamps below
  assert fx.ease_out_cubic(2.0) == 1.0    # clamps above
  assert abs(fx.ease_out_back(0.0)) < 1e-9
  assert abs(fx.ease_out_back(1.0) - 1.0) < 1e-9
  # ease_out_back must overshoot past 1.0 somewhere in (0, 1)
  assert max(fx.ease_out_back(i / 100.0) for i in range(101)) > 1.0


def test_pulse01_range_and_periodicity():
  vals = [fx.pulse01(t / 100.0, period=1.0) for t in range(200)]
  assert all(0.0 <= v <= 1.0 for v in vals)
  assert abs(fx.pulse01(0.0, 1.0) - fx.pulse01(1.0, 1.0)) < 1e-9


def test_col_sets_and_clamps_alpha():
  c = fx.col(fx.CYAN, 2.0)
  assert (c.r, c.g, c.b, c.a) == (fx.CYAN.r, fx.CYAN.g, fx.CYAN.b, 255)
  assert fx.col(fx.CYAN, -1.0).a == 0
  assert fx.col(fx.CYAN, 0.5).a == 127


def test_starfield_deterministic_per_seed():
  a, b = fx.Starfield(n=30, seed=7), fx.Starfield(n=30, seed=7)
  assert a.stars == b.stars
  assert a.rings == b.rings
  c = fx.Starfield(n=30, seed=8)
  assert a.stars != c.stars


def test_cascade_start_and_settle():
  c = fx.Cascade(stagger=0.07, duration=0.35, rise=24.0)
  a0, dy0, s0 = c.values(0.0, index=3)   # index 3 has not started at t=0
  assert a0 == 0.0 and dy0 == 24.0 and s0 == 0.98
  a1, dy1, s1 = c.values(10.0, index=3)  # long settled
  assert a1 == 1.0 and dy1 == 0.0 and s1 == 1.0
```

- [ ] **Step 2: Verificar que fallan**

Run: `cd /home/drago/Escritorio/ORBITPILOT && ./.venv/bin/python -m pytest selfdrive/ui/tests/test_orbit_fx.py -v`
Expected: FAIL / ERROR con `ModuleNotFoundError: No module named 'openpilot.selfdrive.ui.widgets.orbit_fx'`

- [ ] **Step 3: Implementar el módulo**

Crear `selfdrive/ui/widgets/orbit_fx.py`:

```python
"""
ORBIT shared visual-FX helpers: easing, layered glow, card chrome, starfield.

Pure raylib primitives (no shaders, no new textures) so everything runs on the
comma 3X GLES stack. Animation is driven by a caller-provided time `t` in
seconds (typically time.monotonic()-relative); nothing here allocates per
frame — Starfield precomputes its elements at construction time with a fixed
seed so offscreen screenshots stay deterministic.
"""
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
```

- [ ] **Step 4: Verificar que pasan**

Run: `cd /home/drago/Escritorio/ORBITPILOT && ./.venv/bin/python -m pytest selfdrive/ui/tests/test_orbit_fx.py -v`
Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
cd /home/drago/Escritorio/ORBITPILOT
git add selfdrive/ui/widgets/orbit_fx.py selfdrive/ui/tests/test_orbit_fx.py
git commit --no-verify -m "feat(ui): modulo orbit_fx compartido — easing, glow por capas, tarjeta v2, starfield orbital y cascada"
```

---

### Task 2: Harness de capturas offscreen (scratchpad, no se commitea)

**Files:**
- Create: `<SCRATCH>/shot_harness.py` (fuera del repo)

**Interfaces:**
- Consumes: `OrbitSplash`, `HomeLayout`, `SettingsLayoutSP`, `gui_app.init_window(title, fps)`.
- Produces: PNGs `<scene>_<t>s.png` en `<SCRATCH>` — lo usan Tasks 3–6 para verificar. CLI: `shot_harness.py <splash|home|settings> [t1 t2 ...]`, env `VARIANT=linked|unlinked` (home) y `SWITCH=1` (settings: cambia a Toggles en t=1.0 para capturar la transición).

- [ ] **Step 1: Escribir el harness**

Crear `<SCRATCH>/shot_harness.py`:

```python
"""Offscreen screenshot harness for ORBIT UI scenes.

Usage:
  BIG=1 SCALE=1 DISPLAY=:1 PYTHONPATH=/home/drago/Escritorio/ORBITPILOT \
    /home/drago/Escritorio/ORBITPILOT/.venv/bin/python shot_harness.py splash 0.8 2.5 5.2
  VARIANT=linked   ... shot_harness.py home 0.25 1.6
  SWITCH=1         ... shot_harness.py settings 0.5 1.08 1.5

Screenshots land in the cwd (raylib prepends it) as <scene>_<t>s.png.
Params staged for the 'home' variants are restored on exit.
"""
import os
import sys
import time

import pyray as rl
from openpilot.common.params import Params
from openpilot.system.ui.lib.application import gui_app

SCENE = sys.argv[1]
SHOTS = sorted(float(s) for s in sys.argv[2:]) or [1.5]

STAGE = {
  "linked": {
    "OrbitClaimed": "1", "OrbitOwner": "drago", "OrbitConnected": "1",
    "OrbitLastPublish": str(int(time.time()) - 4), "DongleId": "a1b2c3d45e6f7890",
    "GitBranch": "orbit-master", "GitCommit": "775eac3a0aaaaaaaaaaaa", "Version": "0.9.9",
  },
  "unlinked": {
    "OrbitClaimed": "0", "OrbitOwner": "", "OrbitConnected": "0",
    "DongleId": "a1b2c3d45e6f7890",
    "GitBranch": "orbit-master", "GitCommit": "775eac3a0aaaaaaaaaaaa", "Version": "0.9.9",
  },
}

params = Params()
staged: dict[str, bytes | None] = {}
variant = os.environ.get("VARIANT", "")
if SCENE == "home" and variant in STAGE:
  for k, v in STAGE[variant].items():
    staged[k] = params.get(k)
    params.put(k, v)

try:
  gui_app.init_window("shot")
  if SCENE == "splash":
    from openpilot.selfdrive.ui.sunnypilot.layouts.orbit_splash import OrbitSplash
    w = OrbitSplash()
  elif SCENE == "home":
    from openpilot.selfdrive.ui.layouts.home import HomeLayout
    w = HomeLayout()
    w.show_event()
  elif SCENE == "settings":
    from openpilot.selfdrive.ui.sunnypilot.layouts.settings.settings import SettingsLayoutSP
    w = SettingsLayoutSP()
    w.show_event()
  else:
    raise SystemExit(f"unknown scene {SCENE}")

  switch_at = 1.0 if (SCENE == "settings" and os.environ.get("SWITCH")) else None
  start = time.monotonic()
  pending = list(SHOTS)
  while pending:
    el = time.monotonic() - start
    if switch_at is not None and el >= switch_at:
      w.set_current_panel(list(w._panels.keys())[4])  # 5th tile (Toggles on SP)
      switch_at = None
    rl.begin_drawing()
    rl.clear_background(rl.BLACK)
    w.render(rl.Rectangle(0, 0, gui_app.width, gui_app.height))
    rl.end_drawing()
    if el >= pending[0]:
      rl.take_screenshot(f"{SCENE}_{pending[0]:.2f}s.png")
      pending.pop(0)
finally:
  for k, old in staged.items():
    if old is None:
      params.remove(k)
    else:
      params.put(k, old)
```

- [ ] **Step 2: Probar el harness con la UI ACTUAL (baseline)**

Run:
```bash
cd <SCRATCH> && BIG=1 SCALE=1 DISPLAY=:1 PYTHONPATH=/home/drago/Escritorio/ORBITPILOT \
  /home/drago/Escritorio/ORBITPILOT/.venv/bin/python shot_harness.py splash 2.0
```
Expected: crea `splash_2.00s.png` en `<SCRATCH>`. Si falla por display, arrancar antes `Xvfb :1 -screen 0 2160x1080x24 &` (o usar el DISPLAY real). Abrir el PNG con Read y confirmar que se ve el splash actual (logo + ORBIT + barras cian).

- [ ] **Step 3: Baseline de home y settings**

Run:
```bash
cd <SCRATCH> && VARIANT=linked BIG=1 SCALE=1 DISPLAY=:1 PYTHONPATH=/home/drago/Escritorio/ORBITPILOT \
  /home/drago/Escritorio/ORBITPILOT/.venv/bin/python shot_harness.py home 1.5
cd <SCRATCH> && BIG=1 SCALE=1 DISPLAY=:1 PYTHONPATH=/home/drago/Escritorio/ORBITPILOT \
  /home/drago/Escritorio/ORBITPILOT/.venv/bin/python shot_harness.py settings 0.5
```
Expected: `home_1.50s.png` y `settings_0.50s.png` con el aspecto actual. (Sin commit: el harness vive en el scratchpad.)

---

### Task 3: Splash cinematográfico

**Files:**
- Modify: `selfdrive/ui/sunnypilot/layouts/orbit_splash.py` (reescritura completa)

**Interfaces:**
- Consumes: `orbit_fx` (Task 1): `Starfield`, `clamp01`, `ease_out_cubic`, `ease_out_back`, `pulse01`, `col`, `draw_glow_circle`, y paleta `fx.VOID/CYAN/BLUE_HI/GREEN/INK/MUTED/HAIRLINE`.
- Produces: misma clase pública `OrbitSplash(Widget)` con `_dismiss()` por identidad INTACTO (quien lo pushea en `main.py` no cambia).

- [ ] **Step 1: Reescribir el archivo**

Contenido completo de `selfdrive/ui/sunnypilot/layouts/orbit_splash.py`:

```python
"""
ORBIT boot splash — cinematic phased intro.

A full-screen branding screen shown once each time the UI starts. It is pushed
on top of the widget nav stack (so on big_ui only it renders), plays a phased
boot sequence (starfield -> tri-color ring draw-in + logo bloom -> wordmark
tracking-in -> tagline), shows a thin orbital progress arc, then auto-dismisses
(or dismisses on tap) by popping itself.

ORBIT — Open Remote Bidirectional IoV Telemetry.
"""
import math
import time

import pyray as rl

from openpilot.selfdrive.ui.widgets import orbit_fx as fx
from openpilot.system.ui.lib.application import gui_app, FontWeight
from openpilot.system.ui.lib.text_measure import measure_text_cached
from openpilot.system.ui.widgets import Widget

LOGO_PATH = "img_orbit_logo.png"   # resolved under selfdrive/assets/

DURATION = 5.5     # seconds on screen before auto-dismiss
EXIT_FADE = 0.5    # global fade/zoom-out at the very end

LOGO_FRAC = 0.26   # logo width as a fraction of the screen width
WORDMARK_SIZE = 150
WORDMARK_SPACING = 26         # final tracking
WORDMARK_SPACING_WIDE = 64    # tracking animates in from this
TAGLINE = "Open Remote Bidirectional IoV Telemetry"
TAGLINE_SIZE = 40
RING_SPIN_DPS = 40.0          # continuous ring rotation, deg/s


def _win(t: float, a: float, b: float) -> float:
  """0..1 progress of t through the window [a, b]."""
  if b <= a:
    return 1.0
  return fx.clamp01((t - a) / (b - a))


class OrbitSplash(Widget):
  def __init__(self):
    super().__init__()
    self._start: float | None = None
    self._done = False
    self._stars = fx.Starfield(n=90, seed=42)

  def _dismiss(self):
    # Pop by identity: never pop another widget if something got pushed on top.
    if self._done:
      return
    if gui_app.get_active_widget() is self:
      self._done = True
      gui_app.pop_widget()
      return
    stack = getattr(gui_app, "_nav_stack", None)
    if stack and self in stack:
      self._done = True
      gui_app.pop_widget(stack.index(self))

  def _handle_mouse_release(self, mouse_pos):
    self._dismiss()

  def _render(self, rect: rl.Rectangle):
    now = time.monotonic()
    if self._start is None:
      self._start = now
    t = now - self._start
    exit_a = fx.clamp01((DURATION - t) / EXIT_FADE)   # 1 -> 0 during the exit

    rl.draw_rectangle_rec(rect, fx.VOID)

    # Phase 0 (0.0-0.6): the starfield fades in
    self._stars.render(rect, t, intensity=_win(t, 0.0, 0.6) * exit_a)

    # Top edge light (replaces the old solid 14px bars)
    g = _win(t, 0.2, 1.0) * exit_a
    rl.draw_rectangle(int(rect.x), int(rect.y), int(rect.width), 2, fx.col(fx.CYAN, 0.45 * g))
    rl.draw_rectangle_gradient_v(int(rect.x), int(rect.y) + 2, int(rect.width), 26,
                                 fx.col(fx.CYAN, 0.10 * g), fx.col(fx.CYAN, 0.0))

    cx = rect.x + rect.width / 2.0
    bold = gui_app.font(FontWeight.BOLD)
    normal = gui_app.font(FontWeight.NORMAL)

    logo_w = int(min(rect.width * LOGO_FRAC, 460))
    wm_size = measure_text_cached(bold, "ORBIT", WORDMARK_SIZE, WORDMARK_SPACING)
    tg_size = measure_text_cached(normal, TAGLINE, TAGLINE_SIZE)
    gap_logo, gap_wordmark = 34, 24
    logo_h = logo_w  # square asset
    block_h = logo_h + gap_logo + wm_size.y + gap_wordmark + tg_size.y
    y = rect.y + max((rect.height - block_h) / 2.0, rect.height * 0.14)
    logo_cx, logo_cy = cx, y + logo_h / 2.0

    # Phase 1 (0.3-1.2 staggered): the tri-color ring draws itself in, then spins
    ring_r = logo_h * 0.64
    spin = (t * RING_SPIN_DPS) % 360.0
    for k, color in enumerate((fx.CYAN, fx.BLUE_HI, fx.GREEN)):
      sweep = 80.0 * fx.ease_out_cubic(_win(t, 0.3 + 0.15 * k, 1.2 + 0.15 * k))
      if sweep <= 0.5:
        continue
      start = spin + k * 120.0
      rl.draw_ring(rl.Vector2(logo_cx, logo_cy), ring_r - 5, ring_r, start, start + sweep,
                   48, fx.col(color, 0.85 * exit_a))

    # Satellite dot + fading trail traveling the ring (after the draw-in)
    if t > 1.2:
      sat_a = _win(t, 1.2, 1.6) * exit_a
      ang = math.radians(spin * 2.2)
      sx = logo_cx + ring_r * math.cos(ang)
      sy = logo_cy + ring_r * math.sin(ang)
      fx.draw_glow_circle(sx, sy, 7.0, fx.CYAN, 0.5 * sat_a)
      rl.draw_circle(int(sx), int(sy), 6.0, fx.col(fx.CYAN, 0.9 * sat_a))
      for lag, aa, rr in ((7.0, 0.45, 4.5), (14.0, 0.2, 3.0)):
        ang2 = math.radians(spin * 2.2 - lag)
        rl.draw_circle(int(logo_cx + ring_r * math.cos(ang2)),
                       int(logo_cy + ring_r * math.sin(ang2)), rr, fx.col(fx.CYAN, aa * sat_a))

    # Phase 1b (0.4-1.1): logo scales in with a spring + breathing cyan bloom
    lg = _win(t, 0.4, 1.1)
    la = lg * exit_a
    scale = (0.7 + 0.3 * fx.ease_out_back(lg)) * (1.0 + 0.06 * (1.0 - exit_a))
    fx.draw_glow_circle(logo_cx, logo_cy, logo_h * 0.55, fx.CYAN,
                        (0.35 + 0.35 * fx.pulse01(t, 2.4)) * la)
    try:
      tex = gui_app.texture(LOGO_PATH, logo_w, logo_h, keep_aspect_ratio=True)
      dw, dh = tex.width * scale, tex.height * scale
      rl.draw_texture_pro(tex, rl.Rectangle(0, 0, tex.width, tex.height),
                          rl.Rectangle(logo_cx - dw / 2.0, logo_cy - dh / 2.0, dw, dh),
                          rl.Vector2(0, 0), 0.0, fx.col(rl.WHITE, la))
    except Exception:
      pass
    y += logo_h + gap_logo

    # Phase 2 (1.1-1.8): wordmark tracking-in + center-out cyan underline
    wg = _win(t, 1.1, 1.8)
    if wg > 0.0:
      spacing = int(WORDMARK_SPACING_WIDE + (WORDMARK_SPACING - WORDMARK_SPACING_WIDE) * fx.ease_out_cubic(wg))
      cur = measure_text_cached(bold, "ORBIT", WORDMARK_SIZE, spacing)
      rl.draw_text_ex(bold, "ORBIT", rl.Vector2(int(cx - cur.x / 2.0), int(y)),
                      WORDMARK_SIZE, spacing, fx.col(fx.INK, wg * exit_a))
      uw = wm_size.x * fx.ease_out_cubic(_win(t, 1.4, 2.0))
      if uw > 1.0:
        rl.draw_rectangle(int(cx - uw / 2.0), int(y + wm_size.y + 10), int(uw), 4,
                          fx.col(fx.CYAN, wg * exit_a))
    y += wm_size.y + gap_wordmark

    # Phase 3 (1.7-2.3): tagline rises in
    tgp = fx.ease_out_cubic(_win(t, 1.7, 2.3))
    if tgp > 0.0:
      rl.draw_text_ex(normal, TAGLINE,
                      rl.Vector2(int(cx - tg_size.x / 2.0), int(y + 12.0 * (1.0 - tgp))),
                      TAGLINE_SIZE, 0, fx.col(fx.MUTED, tgp * exit_a))

    # Orbital progress arc (bottom-center) + pulsing tap hint
    pa = _win(t, 0.6, 1.2) * exit_a
    if pa > 0.0:
      ctr = rl.Vector2(cx, rect.y + rect.height - 158)
      rl.draw_ring(ctr, 23, 26, 0, 360, 48, fx.col(fx.HAIRLINE, 0.8 * pa))
      rl.draw_ring(ctr, 23, 26, -90, -90 + 360.0 * fx.clamp01(t / DURATION), 48,
                   fx.col(fx.CYAN, 0.85 * pa))
    if t > 2.2:
      hint = "toca la pantalla para continuar"
      ha = _win(t, 2.2, 2.8) * (0.5 + 0.5 * fx.pulse01(t, 1.8)) * exit_a
      hw = measure_text_cached(normal, hint, 30).x
      rl.draw_text_ex(normal, hint, rl.Vector2(cx - hw / 2.0, rect.y + rect.height - 96),
                      30, 0, fx.col(fx.MUTED, ha))

    # Auto-dismiss
    if t >= DURATION:
      self._dismiss()
```

- [ ] **Step 2: Verificación visual**

Run:
```bash
cd <SCRATCH> && BIG=1 SCALE=1 DISPLAY=:1 PYTHONPATH=/home/drago/Escritorio/ORBITPILOT \
  /home/drago/Escritorio/ORBITPILOT/.venv/bin/python shot_harness.py splash 0.8 2.5 5.2
```
Expected: 3 PNGs. Leerlos con Read y comprobar: en 0.8s el anillo está a medio dibujar y el logo aún creciendo; en 2.5s todo asentado (wordmark compacto, subrayado completo, satélite y arco de progreso visibles, SIN barras sólidas arriba/abajo); en 5.2s todo fundiéndose (más oscuro). Estrellas visibles en los tres.

- [ ] **Step 3: Commit**

```bash
cd /home/drago/Escritorio/ORBITPILOT
git add selfdrive/ui/sunnypilot/layouts/orbit_splash.py
git commit --no-verify -m "feat(ui): splash cinematografico por fases — starfield, anillo que se dibuja, bloom del logo, tracking del wordmark y arco de progreso"
```

---

### Task 4: Home viva

**Files:**
- Modify: `selfdrive/ui/layouts/home.py`

**Interfaces:**
- Consumes: `orbit_fx` (Task 1): `Starfield`, `Cascade`, `ease_out_cubic`, `pulse01`, `col`, `draw_card`, `draw_glow_circle`.
- Produces: sin cambios de API pública (`HomeLayout` igual hacia fuera). `_draw_card` gana kwargs `alpha=1.0, glow=0.0, glow_color=None`; `_render_telemetry_wave` gana `alpha=1.0`.

- [ ] **Step 1: Imports y constantes**

En `selfdrive/ui/layouts/home.py`, añadir tras el import de `Widget` (línea 17):

```python
from openpilot.selfdrive.ui.widgets import orbit_fx as fx
```

Añadir tras el bloque de constantes de la onda (`WAVE_SPEED = 70.0`, línea ~70):

```python
# Entrance + ambient animation
CASCADE_START = 0.15      # s after show before the first card animates in
HEADER_FADE_S = 0.30      # header fade-in
SHIMMER_PERIOD = 6.0      # s between shimmer sweeps on the wordmark underline
SHIMMER_S = 0.8           # sweep duration
SHIMMER_W = 46            # sweep width px
```

- [ ] **Step 2: Estado en `__init__` y `show_event`**

En `HomeLayout.__init__`, junto a la creación de `self._server` (línea ~168), añadir:

```python
    # Ambient background + entrance cascade
    self._stars = fx.Starfield(n=70, seed=1234)
    self._cascade = fx.Cascade(stagger=0.07, duration=0.35, rise=24.0)
    self._shown_at = time.monotonic()
```

En `show_event` (línea ~174), añadir al final:

```python
    self._shown_at = time.monotonic()
```

- [ ] **Step 3: Fondo vivo en `_render`**

En `_render`, justo después de `rl.draw_rectangle(int(rect.x), ... VOID)` (línea 204), añadir:

```python
    self._stars.render(rect, current_time, intensity=0.5)
```

- [ ] **Step 4: Header con fade + shimmer**

En `_render_header`, tras obtener las fuentes (línea ~260), añadir:

```python
    ha = fx.ease_out_cubic((time.monotonic() - self._shown_at) / HEADER_FADE_S)
```

Cambiar el tint del logo (línea ~266) de `rl.WHITE` a `fx.col(rl.WHITE, ha)`; el wordmark `INK` → `fx.col(INK, ha)`; el subrayado `PULSE` → `fx.col(PULSE, ha)`; la tagline `MUTED` → `fx.col(MUTED, ha)`.

Después de dibujar la tagline (línea ~275), añadir el shimmer periódico del subrayado:

```python
    # Periodic shimmer sweeping across the cyan underline
    phase = time.monotonic() % SHIMMER_PERIOD
    if phase < SHIMMER_S and ha >= 1.0:
      sx = int(tx + (wm.x - SHIMMER_W) * (phase / SHIMMER_S))
      uy = int(ty + wm.y + 5)
      half = SHIMMER_W // 2
      rl.draw_rectangle_gradient_h(sx, uy, half, 3, fx.col(INK, 0.0), fx.col(INK, 0.9))
      rl.draw_rectangle_gradient_h(sx + half, uy, half, 3, fx.col(INK, 0.9), fx.col(INK, 0.0))
```

- [ ] **Step 5: Cascada + glow en las tarjetas de estado**

Reemplazar el bucle final de `_render_status_cards` (líneas 361–369) por:

```python
    now = time.monotonic()
    ts = now - self._shown_at - CASCADE_START
    n = len(cards)
    cw = (rect.width - CARD_GAP * (n - 1)) / n
    for i, (key, title, value, color, detail, sub, tappable) in enumerate(cards):
      a, dy, _scale = self._cascade.values(ts, i)
      card = rl.Rectangle(rect.x + i * (cw + CARD_GAP), rect.y + dy, cw, rect.height)
      self._card_rects[key] = card
      glow, glow_color = 0.0, color
      if key == "server" and broker_ok and backend_ok:
        glow, glow_color = 0.20 + 0.18 * fx.pulse01(now, 3.2), COMMANDS   # breathing: all healthy
      elif key == "link" and claimed:
        glow, glow_color = 0.16 + 0.14 * fx.pulse01(now, 3.2), COMMANDS
      elif tappable:
        glow = 0.16
      self._draw_card(card, title, value, color, detail, sub, tappable, value_size=52,
                      value_y=rect.height * 0.30, chevron_color=color,
                      alpha=a, glow=glow, glow_color=glow_color)
      if key == "server":
        self._render_telemetry_wave(card, alpha=a)
        if self._connected:
          # Live pulse dot right after the SERVIDOR title
          tw = measure_text_cached(gui_app.font(FontWeight.MEDIUM), "SERVIDOR", 26, 3)
          dot_x, dot_y = card.x + CARD_PAD + tw.x + 22, card.y + 28 + tw.y / 2
          blink = 0.35 + 0.65 * fx.pulse01(now, 1.6)
          fx.draw_glow_circle(dot_x, dot_y, 9, PULSE, 0.5 * blink * a)
          rl.draw_circle(int(dot_x), int(dot_y), 6, fx.col(PULSE, blink * a))
```

- [ ] **Step 6: Cascada en las tarjetas de info**

Reemplazar el bucle final de `_render_info_cards` (líneas 401–407) por:

```python
    now = time.monotonic()
    ts = now - self._shown_at - CASCADE_START
    n = len(cards)
    cw = (rect.width - CARD_GAP * (n - 1)) / n
    for i, (key, title, value, color, detail, sub, tappable) in enumerate(cards):
      a, dy, _scale = self._cascade.values(ts, 3 + i)   # continues after the status row
      card = rl.Rectangle(rect.x + i * (cw + CARD_GAP), rect.y + dy, cw, rect.height)
      self._card_rects[key] = card
      glow, glow_color = 0.0, color
      if key == "update" and self.update_available:
        glow, glow_color = 0.16 + 0.14 * fx.pulse01(now, 3.2), COMMANDS
      elif tappable:
        glow = 0.16
      self._draw_card(card, title, value, color, detail, sub, tappable, value_size=42,
                      value_y=rect.height * 0.28, chevron_color=color,
                      alpha=a, glow=glow, glow_color=glow_color)
```

- [ ] **Step 7: `_draw_card` v2 y onda con alpha**

Reemplazar `_draw_card` entero (líneas 409–435) por:

```python
  def _draw_card(self, card: rl.Rectangle, title: str, value: str, color: rl.Color,
                 detail: str, sub: str, tappable: bool, value_size: int, value_y: float,
                 chevron_color: rl.Color, alpha: float = 1.0, glow: float = 0.0,
                 glow_color: rl.Color | None = None):
    hdr_font = gui_app.font(FontWeight.MEDIUM)
    val_font = gui_app.font(FontWeight.BOLD)
    sub_font = gui_app.font(FontWeight.NORMAL)

    fx.draw_card(card, accent=chevron_color, border=chevron_color if tappable else HAIRLINE,
                 glow=glow, glow_color=glow_color, alpha=alpha)

    max_w = card.width - 2 * CARD_PAD
    rl.draw_text_ex(hdr_font, title, rl.Vector2(int(card.x + CARD_PAD), int(card.y + 28)), 26, 3,
                    fx.col(MUTED, alpha))
    if tappable:
      self._draw_chevron(card.x + card.width - CARD_PAD - 16, card.y + card.height / 2, 20,
                         fx.col(chevron_color, alpha))

    value = self._ellipsize(val_font, value, value_size, max_w - (36 if tappable else 0))
    vy = card.y + value_y
    rl.draw_text_ex(val_font, value, rl.Vector2(int(card.x + CARD_PAD), int(vy)), value_size, 0,
                    fx.col(color, alpha))

    if detail:
      detail = self._ellipsize(sub_font, detail, 26, max_w - (36 if tappable else 0))
      rl.draw_text_ex(sub_font, detail, rl.Vector2(int(card.x + CARD_PAD), int(vy + value_size + 18)),
                      26, 0, fx.col(MUTED, alpha))

    if sub:
      sub = self._ellipsize(sub_font, sub, 24, max_w)
      rl.draw_text_ex(sub_font, sub, rl.Vector2(int(card.x + CARD_PAD), int(card.y + card.height - 52)),
                      24, 0, fx.col(MUTED_DIM, alpha))
```

Y en `_render_telemetry_wave`, cambiar la firma a `def _render_telemetry_wave(self, card: rl.Rectangle, alpha: float = 1.0):` y los dos colores: `MUTED_DIM` → `fx.col(MUTED_DIM, alpha)` (línea 447) y `PULSE` → `fx.col(PULSE, alpha)` (línea 458).

- [ ] **Step 8: Pill con slide + respiración, y powered-by con fade**

Reemplazar el cuerpo de `_render_link_pill` desde `text_size = ...` (línea 511) hasta el final por:

```python
    text_size = measure_text_cached(font, text, PILL_FONT_SIZE)
    dot_r = 8
    inner_pad = 32
    dot_gap = 16
    pill_w = inner_pad * 2 + dot_r * 2 + dot_gap + text_size.x

    # Slide in from the right + fade during the home entrance
    ts = time.monotonic() - self._shown_at
    e = fx.ease_out_cubic((ts - 0.1) / 0.4)
    pill_rect = rl.Rectangle(right_x - pill_w + (1.0 - e) * 30.0, y, pill_w, PILL_HEIGHT)
    self._pill_rect = pill_rect

    rl.draw_rectangle_rounded(pill_rect, 1.0, 20, fx.col(PANEL, e))
    rl.draw_rectangle_rounded_lines_ex(pill_rect, 1.0, 20, 2,
                                       fx.col(accent if claimed else HAIRLINE, e))

    # Status dot (breathing glow ring while linked)
    dot_x = pill_rect.x + inner_pad + dot_r
    dot_y = pill_rect.y + PILL_HEIGHT / 2
    if claimed:
      fx.draw_glow_circle(dot_x, dot_y, dot_r + 3, COMMANDS,
                          (0.35 + 0.35 * fx.pulse01(ts, 2.6)) * e)
    rl.draw_circle(int(dot_x), int(dot_y), dot_r, fx.col(accent, e))

    text_x = dot_x + dot_r + dot_gap
    text_y = pill_rect.y + (PILL_HEIGHT - text_size.y) / 2
    rl.draw_text_ex(font, text, rl.Vector2(int(text_x), int(text_y)), PILL_FONT_SIZE, 0,
                    fx.col(accent, e))
    return pill_w
```

En `_render_powered_by`, tras el guard `if self._drago is None:` añadir:

```python
    a = fx.ease_out_cubic((time.monotonic() - self._shown_at - 0.6) / 0.4)
```

y cambiar el tint del dragón `rl.WHITE` → `fx.col(rl.WHITE, a)`, `MUTED` → `fx.col(MUTED, a)` y `COMMANDS` → `fx.col(COMMANDS, a)` en los dos `draw_text_ex` finales.

- [ ] **Step 9: Verificación visual**

Run:
```bash
cd <SCRATCH> && VARIANT=linked BIG=1 SCALE=1 DISPLAY=:1 PYTHONPATH=/home/drago/Escritorio/ORBITPILOT \
  /home/drago/Escritorio/ORBITPILOT/.venv/bin/python shot_harness.py home 0.25 1.6
cd <SCRATCH> && VARIANT=unlinked BIG=1 SCALE=1 DISPLAY=:1 PYTHONPATH=/home/drago/Escritorio/ORBITPILOT \
  /home/drago/Escritorio/ORBITPILOT/.venv/bin/python shot_harness.py home 1.6
```
Expected: en `home_0.25s.png` la cascada a medias (tarjetas de la fila 2 aún subiendo/translúcidas); en `home_1.60s.png` todo asentado con estrellas de fondo, gradiente/luz superior en tarjetas, glow verde en SERVIDOR, dot cian junto al título, pill con dot respirando. En la variante unlinked: ENLACE con borde/glow cian y pill "SIN VINCULAR". Comprobar que los 6 títulos/valores se leen bien sobre el nuevo fondo.

- [ ] **Step 10: Commit**

```bash
cd /home/drago/Escritorio/ORBITPILOT
git add selfdrive/ui/layouts/home.py
git commit --no-verify -m "feat(ui): home viva — starfield orbital de fondo, cascada de entrada, tarjetas con gradiente y glow, pulso en vivo y shimmer"
```

---

### Task 5: Menú animado (settings SP)

**Files:**
- Modify: `selfdrive/ui/sunnypilot/layouts/settings/settings.py`

**Interfaces:**
- Consumes: `orbit_fx` (Task 1): `clamp01`, `ease_out_cubic`; base `OP.SettingsLayout` (`set_current_panel`, `_draw_current_panel`, `OP.PANEL_COLOR`, `OP.PANEL_MARGIN`); `panel_info.button_rect` actualizado por frame por el scroller.
- Produces: sin cambios de API pública. `NavButton` deja de dibujar el marcador (lo dibuja el sidebar, deslizándolo).

- [ ] **Step 1: Imports y constantes**

Al inicio de `selfdrive/ui/sunnypilot/layouts/settings/settings.py`, añadir a los imports (tras la línea 8 `from enum import IntEnum`):

```python
import math
import time
```

y tras el import de `Scroller` (línea 34):

```python
from openpilot.selfdrive.ui.widgets import orbit_fx as fx
```

Junto a `NAV_TILE_H_INSET = 12` (línea 41), añadir:

```python
MARKER_ANIM_S = 0.22     # cyan marker slide between tiles
PANEL_ANIM_S = 0.22      # panel slide+fade on tab change
PANEL_SLIDE_PX = 36.0
```

- [ ] **Step 2: `NavButton` sin marcador, con chip respirando y press inset**

En `NavButton._render`, reemplazar el bloque `if is_selected:` (líneas 89–98) por:

```python
    if is_selected:
      rl.draw_rectangle_rounded(tile, 0.24, 12, OP.ORBIT_PANEL)
      rl.draw_rectangle_rounded_lines_ex(tile, 0.24, 12, 2, OP.ORBIT_HAIRLINE)
      # (cyan marker bar + halo now drawn by the sidebar so it can slide between tiles)
    elif hovered and mouse_down:
      pressed = rl.Rectangle(tile.x + 2, tile.y + 2, tile.width - 4, tile.height - 4)
      rl.draw_rectangle_rounded(pressed, 0.24, 12, OP.ORBIT_NAVY)
```

Y reemplazar la asignación del chip seleccionado (líneas 103–104) por una versión que respira:

```python
    if is_selected:
      chip_a = int(41 + 14 * math.sin(time.monotonic() * 2.4))
      chip_bg = rl.Color(OP.ORBIT_CYAN.r, OP.ORBIT_CYAN.g, OP.ORBIT_CYAN.b, chip_a)
```

- [ ] **Step 3: Estado de animación y `set_current_panel`**

En `SettingsLayoutSP.__init__`, tras `self._nav_items: list[Widget] = []` (línea 129), añadir:

```python
    # Marker-slide + panel-transition animation state
    self._marker_prev = self._current_panel
    self._marker_t0 = 0.0
    self._panel_switch_t0 = 0.0
```

Añadir el override (tras `_draw_sidebar`, como método nuevo de `SettingsLayoutSP`):

```python
  def set_current_panel(self, panel_type):
    if panel_type != self._current_panel:
      self._marker_prev = self._current_panel
      now = time.monotonic()
      self._marker_t0 = now
      self._panel_switch_t0 = now
    super().set_current_panel(panel_type)
```

- [ ] **Step 4: Rail con gradiente + marcador deslizante**

En `_draw_sidebar`, justo después de `rl.draw_rectangle_rec(rect, OP.SIDEBAR_COLOR)` (línea 159), añadir:

```python
    # Subtle vertical light so the rail reads as lit from above
    rl.draw_rectangle_gradient_v(int(rect.x), int(rect.y), int(rect.width), int(rect.height * 0.45),
                                 rl.Color(27, 44, 72, 70), rl.Color(27, 44, 72, 0))
```

Al final de `_draw_sidebar`, después de `self._sidebar_scroller.render(nav_rect)` (línea 198), añadir:

```python
      self._draw_nav_marker(nav_rect)
```

Y añadir el método nuevo a `SettingsLayoutSP`:

```python
  def _draw_nav_marker(self, nav_rect: rl.Rectangle):
    """Cyan selection marker + halo, drawn over the rail so it can slide with
    easing between the previous and the current tile. button_rects are updated
    every frame by the scroller, so the marker follows scrolling too."""
    cur = self._panels[self._current_panel].button_rect
    if cur.width <= 0:
      return
    prev = self._panels[self._marker_prev].button_rect
    t = fx.clamp01((time.monotonic() - self._marker_t0) / MARKER_ANIM_S)
    if prev.width <= 0 or t >= 1.0:
      row = cur
    else:
      e = fx.ease_out_cubic(t)
      row = rl.Rectangle(prev.x + (cur.x - prev.x) * e, prev.y + (cur.y - prev.y) * e,
                         prev.width + (cur.width - prev.width) * e,
                         prev.height + (cur.height - prev.height) * e)
    tile_y = row.y + NAV_TILE_INSET
    tile_h = row.height - 2 * NAV_TILE_INSET
    bar = rl.Rectangle(row.x + NAV_TILE_H_INSET + 3, tile_y + tile_h * 0.18, 11, tile_h * 0.64)
    halo = rl.Rectangle(bar.x - 3, bar.y - 3, bar.width + 6, bar.height + 6)
    rl.begin_scissor_mode(int(nav_rect.x), int(nav_rect.y), int(nav_rect.width), int(nav_rect.height))
    rl.draw_rectangle_rounded(halo, 1.0, 8, rl.Color(OP.ORBIT_CYAN.r, OP.ORBIT_CYAN.g, OP.ORBIT_CYAN.b, 55))
    rl.draw_rectangle_rounded(bar, 1.0, 8, OP.ORBIT_CYAN)
    rl.end_scissor_mode()
```

- [ ] **Step 5: Transición del panel (slide + fundido desde oscuro)**

Añadir a `SettingsLayoutSP` el override:

```python
  def _draw_current_panel(self, rect: rl.Rectangle):
    bg = rl.Rectangle(rect.x + 10, rect.y + 10, rect.width - 20, rect.height - 20)
    rl.draw_rectangle_rounded(bg, 0.04, 30, OP.PANEL_COLOR)
    content_rect = rl.Rectangle(rect.x + OP.PANEL_MARGIN, rect.y + 25,
                                rect.width - (OP.PANEL_MARGIN * 2), rect.height - 50)
    panel = self._panels[self._current_panel]
    if not panel.instance:
      return
    t = fx.clamp01((time.monotonic() - self._panel_switch_t0) / PANEL_ANIM_S)
    if t >= 1.0:
      panel.instance.render(content_rect)
      return
    e = fx.ease_out_cubic(t)
    rl.begin_scissor_mode(int(bg.x), int(bg.y), int(bg.width), int(bg.height))
    panel.instance.render(rl.Rectangle(content_rect.x + (1.0 - e) * PANEL_SLIDE_PX, content_rect.y,
                                       content_rect.width, content_rect.height))
    # Fade-from-dark overlay while the panel slides in
    rl.draw_rectangle_rounded(bg, 0.04, 30,
                              rl.Color(OP.PANEL_COLOR.r, OP.PANEL_COLOR.g, OP.PANEL_COLOR.b,
                                       int(150 * (1.0 - e))))
    rl.end_scissor_mode()
```

(`self._panel_switch_t0 = 0.0` inicial → `t >= 1.0` desde el primer frame: sin animación al abrir settings, solo al cambiar de pestaña.)

- [ ] **Step 6: Verificación visual**

Run:
```bash
cd <SCRATCH> && SWITCH=1 BIG=1 SCALE=1 DISPLAY=:1 PYTHONPATH=/home/drago/Escritorio/ORBITPILOT \
  /home/drago/Escritorio/ORBITPILOT/.venv/bin/python shot_harness.py settings 0.5 1.08 1.5
```
Expected: en `settings_0.50s.png` el estado inicial (marcador en la 1a pestaña, rail con luz arriba); en `settings_1.08s.png` la transición a Toggles a medias — marcador entre pestañas Y panel desplazado/oscurecido; en `settings_1.50s.png` asentado en Toggles con el marcador a ras del tile. Nada del marcador debe pintarse fuera del área de tiles (scissor).

- [ ] **Step 7: Commit**

```bash
cd /home/drago/Escritorio/ORBITPILOT
git add selfdrive/ui/sunnypilot/layouts/settings/settings.py
git commit --no-verify -m "feat(ui): menu animado — marcador cian deslizante con halo, transicion slide+fade del panel, rail con luz y chip respirando"
```

---

### Task 6: Refrescar capturas del README

**Files:**
- Modify: `docs/images/ui-splash.png`, `docs/images/ui-home.png`, `docs/images/ui-home-unlinked.png`, `docs/images/ui-toggles.png`, `docs/images/ui-device.png` (regeneradas; ya son non-LFS vía override `docs/images/*.png` en `.gitattributes`)

**Interfaces:**
- Consumes: harness de Task 2 + pantallas ya rediseñadas (Tasks 3–5). PIL (`from PIL import Image`) del `.venv` para reescalar a 1080 de ancho como las capturas actuales.

- [ ] **Step 1: Generar las capturas**

```bash
cd <SCRATCH>
ENVV="BIG=1 SCALE=1 DISPLAY=:1 PYTHONPATH=/home/drago/Escritorio/ORBITPILOT"
PY=/home/drago/Escritorio/ORBITPILOT/.venv/bin/python
env $ENVV $PY shot_harness.py splash 2.6
env $ENVV VARIANT=linked $PY shot_harness.py home 1.6
env $ENVV VARIANT=unlinked $PY shot_harness.py home 1.6   # renombrar antes de que lo pise: mv home_1.60s.png home_linked.png tras la 1a
env $ENVV $PY shot_harness.py settings 0.5                 # panel DEVICE (2a pestaña es la que muestra ui-device; ver nota)
env $ENVV SWITCH=1 $PY shot_harness.py settings 1.6        # asentado en Toggles
```
Nota: la primera pestaña del SP es UEM; para `ui-device.png` hacer una pasada con `SWITCH=1` editado temporalmente (índice 1 = Device) o capturar la pestaña que muestre el panel Device. Renombrar cada PNG antes de la siguiente pasada para no sobrescribir.

- [ ] **Step 2: Reescalar y copiar al repo**

```bash
cd <SCRATCH> && /home/drago/Escritorio/ORBITPILOT/.venv/bin/python - <<'EOF'
from PIL import Image
import os
MAP = {
  "splash_2.60s.png": "ui-splash.png",
  "home_linked.png": "ui-home.png",
  "home_unlinked.png": "ui-home-unlinked.png",
  "settings_toggles.png": "ui-toggles.png",
  "settings_device.png": "ui-device.png",
}
for src, dst in MAP.items():
  im = Image.open(src)
  w = 1080
  im.resize((w, int(im.height * w / im.width)), Image.LANCZOS) \
    .save(os.path.join("/home/drago/Escritorio/ORBITPILOT/docs/images", dst))
  print(dst, "ok")
EOF
```
Expected: 5 líneas "ok". Leer cada PNG resultante con Read para confirmar que se ven bien (sin frames a medio animar salvo intención).

- [ ] **Step 3: Commit**

```bash
cd /home/drago/Escritorio/ORBITPILOT
git add docs/images/ui-splash.png docs/images/ui-home.png docs/images/ui-home-unlinked.png docs/images/ui-toggles.png docs/images/ui-device.png
git commit --no-verify -m "docs: capturas actualizadas de la UI v4 animada (splash, home, menu)"
```

---

### Task 7: Regresión final

**Files:**
- (solo verificación; commit únicamente si hay arreglos)

- [ ] **Step 1: Lint de los archivos tocados**

Run:
```bash
cd /home/drago/Escritorio/ORBITPILOT && ./.venv/bin/python -m ruff check \
  selfdrive/ui/widgets/orbit_fx.py selfdrive/ui/tests/test_orbit_fx.py \
  selfdrive/ui/sunnypilot/layouts/orbit_splash.py selfdrive/ui/layouts/home.py \
  selfdrive/ui/sunnypilot/layouts/settings/settings.py
```
Expected: "All checks passed!" (si `ruff` no está como módulo, usar `./.venv/bin/ruff check ...`). Arreglar lo que salga.

- [ ] **Step 2: Tests unitarios + imports**

Run:
```bash
cd /home/drago/Escritorio/ORBITPILOT && ./.venv/bin/python -m pytest selfdrive/ui/tests/test_orbit_fx.py -q && \
  PYTHONPATH=. ./.venv/bin/python -c "
import openpilot.selfdrive.ui.widgets.orbit_fx
import openpilot.selfdrive.ui.sunnypilot.layouts.orbit_splash
print('imports ok')"
```
Expected: `5 passed` + `imports ok`. (home/settings importan cadenas pesadas con side effects de ventana; su humo real ya quedó cubierto por el harness en Tasks 4–5.)

- [ ] **Step 3: Pasada visual final de las 3 pantallas**

Repetir una captura asentada de cada escena (splash 2.6s, home linked 1.6s, settings 1.5s) y revisarlas juntas: paleta consistente, texto legible sobre el starfield, sin artefactos de scissor ni glow recortado. Si algo desentona, ajustar alphas/intensidades (valores en un solo sitio: `orbit_fx.py` y las constantes de cada pantalla) y re-capturar.

- [ ] **Step 4: Commit de ajustes (solo si los hubo)**

```bash
cd /home/drago/Escritorio/ORBITPILOT
git add -u && git commit --no-verify -m "fix(ui): ajustes finos de la pasada visual v4"
```
