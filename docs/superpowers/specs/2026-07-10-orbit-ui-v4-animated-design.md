# ORBIT UI v4 — profundidad, brillo y animación (splash / home / menú)

**Fecha:** 2026-07-10 · **Rama:** `orbit-master` · **Estado:** aprobado por drago

## Objetivo

Elevar la impresión visual de la UI offroad de ORBIT: dirección estética
**profundidad y brillo** (gradientes, glow, jerarquía) con **todo animado**
(splash cinematográfico, cascadas de entrada, transiciones en el menú, fondos
vivos). Sin shaders: solo primitivas raylib (rects/rings/círculos por capas),
seguras en el GLES del comma 3X. El HUD onroad NO se toca (seguridad); el
overlay de comandos remotos tampoco.

## Alcance (archivos)

| Archivo | Acción |
|---|---|
| `selfdrive/ui/widgets/orbit_fx.py` | **NUEVO** — módulo FX compartido |
| `selfdrive/ui/sunnypilot/layouts/orbit_splash.py` | Reescritura (secuencia por fases) |
| `selfdrive/ui/layouts/home.py` | Fondo vivo + cascada + tarjetas v2 |
| `selfdrive/ui/sunnypilot/layouts/settings/settings.py` | Marcador deslizante + transición de panel + rail con gradiente |
| `selfdrive/ui/layouts/settings/settings.py` (base) | Solo si hace falta exponer un hook para la transición del panel |

## 1) Módulo compartido `orbit_fx.py`

Paleta ORBIT propia (constantes duplicadas del sistema — son estables): VOID
`#0B1220`, NAVY `#16233A`, PANEL `#1B2C48`, HAIRLINE `#2B3E5F`, CYAN `#22D3EE`,
BLUE_HI `#7DB4FF`, GREEN `#4ADE80`, INK `#E2ECFF`, MUTED `#93B4E6`,
MUTED_DIM `#5C7599`.

API:

- `clamp01(t)`, `ease_out_cubic(t)`, `ease_out_back(t)` (rebote sutil),
  `pulse01(t, period)` (seno 0..1).
- `draw_glow_rounded_rect(rect, roundness, color, strength, layers=4)` — halos
  por capas de `draw_rectangle_rounded_lines_ex` con alpha decreciente hacia
  fuera. `strength` 0..1 multiplica el alpha.
- `draw_glow_circle(cx, cy, r, color, strength)` — 3 círculos concéntricos.
- `draw_card(rect, *, accent, border, glow=0.0, alpha=1.0, roundness=0.10)` —
  tarjeta v2: base NAVY redondeada, **gradiente vertical** de luz (tinte del
  acento, alpha ~26 → 0, sobre el 45% superior, con inset horizontal ≈ radio de
  esquina para no pisar las esquinas), **línea de luz superior** de 2px en el
  acento, borde (hairline o acento) y glow opcional. `alpha` multiplica todos
  los colores (vía `rl.fade`) para las cascadas.
- `class Starfield(n=70, seed=1234, rings=3)` — estrellas precomputadas al
  construir (fracciones x/y, tamaño 1–3px, fase, velocidad): parpadeo
  `alpha = base + sin(t·v + fase)` y deriva horizontal lenta (`% 1.0`). Más
  2–3 **arcos orbitales** gigantes (`draw_ring` de segmento, alpha 8–14,
  rotando 2–4°/s) anclados fuera de centro. `render(rect, t, intensity=1.0)`.
  Semilla fija → capturas deterministas. Cero allocations por frame.
- `class Cascade(stagger=0.07, duration=0.35, rise=24.0)` —
  `values(t_since_show, index) -> (alpha01, dy, scale)` con `ease_out_cubic`.

## 2) Splash cinematográfico (`orbit_splash.py`)

`DURATION = 5.5s`; tap para saltar; la lógica de pop **por identidad** de
`_dismiss()` se conserva tal cual. Timeline (t en s desde `show`):

- **0.0–0.6** — starfield funde de negro (intensity 0→1).
- **0.3–1.2** — el anillo tricolor **se dibuja a sí mismo**: cada arco
  (CYAN/BLUE/GREEN) barre 0→80° con `ease_out_cubic`, escalonados 0.15s.
  Después rotan continuo a ~40°/s (más elegante que los 80°/s actuales).
- **0.4–1.1** — logo escala 0.7→1.0 con `ease_out_back` + fade; bloom cian
  detrás (`draw_glow_circle` con pulso).
- **1.1–1.8** — wordmark ORBIT funde con **tracking animado** (spacing 64→26,
  `ease_out_cubic`); subrayado cian barre desde el centro 1.4–2.0.
- **1.7–2.3** — tagline funde y sube ~12px; después, hint "toca la pantalla
  para continuar" pulsando.
- **Continuo** — un **satélite** (punto cian con 2 puntos de estela) recorre el
  anillo; **arco de progreso** fino (radio ~26px, abajo-centro) se llena
  0→360° con `elapsed/DURATION`.
- **Salida (últimos 0.5s)** — fade global + zoom sutil del logo (1.0→1.06).
- Se eliminan las barras cian/azul de 14px arriba/abajo → hairline superior con
  glow tenue.

## 3) Home viva (`home.py`)

- **Fondo:** `Starfield` (intensity ~0.5) + arcos orbitales, dibujado entre el
  fill VOID y el contenido, en todos los estados (HOME/UPDATE/ALERTS).
- **Cascada de entrada:** `show_event` registra `_shown_at`. Header funde en
  t 0–0.3; tarjetas 0..5 con stagger 0.07 desde t=0.15 (fade + subir 24px);
  pill entra deslizando ~30px desde la derecha; powered-by al final. Para el
  alpha, `_draw_card` y la onda ECG aceptan multiplicador y aplican `rl.fade`.
- **Tarjetas v2:** vía `orbit_fx.draw_card` (gradiente + luz superior +
  borde). SERVIDOR con broker+API ok → glow verde **respirando**
  (`pulse01(t, 3.2s)`, amplitud baja); ENLACE vinculado → respiración verde;
  tarjetas tappables → glow del acento constante suave. La onda ECG se queda.
- **Punto de pulso:** dot cian (r≈7) parpadeando junto al título SERVIDOR
  cuando `OrbitConnected`, con mini-glow.
- **Pill:** el dot de estado lleva anillo de respiración cuando VINCULADO.
- **Shimmer:** cada ~6s un destello de 40px recorre el subrayado cian del
  wordmark (0.8s, gradiente horizontal).
- Cacheo de Params intacto (10s/2s); nada nuevo por frame salvo trig.

## 4) Menú (`settings.py` SP)

- **Marcador deslizante:** `set_current_panel` guarda (panel anterior, t0). El
  marcador cian + halo dejan de dibujarse dentro de `NavButton`; los dibuja el
  sidebar DESPUÉS del scroller, interpolando entre `button_rect` del tile
  anterior y el nuevo (`ease_out_cubic`, ~220ms). Como los `button_rect` se
  actualizan cada frame por el scroller, el marcador sigue el scroll.
- **Transición de panel:** al cambiar de pestaña, el panel se renderiza con
  offset `dx = 36→0` (`ease_out_cubic`, ~220ms) dentro de
  `begin_scissor_mode(panel_rect)` + overlay VOID con alpha 150→0 (fundido
  desde oscuro). Hook en la capa SP; solo se toca la base si no hay forma de
  envolver el render del panel.
- **Rail:** gradiente vertical sutil (ligeramente más claro arriba); chip del
  icono seleccionado respira (alpha 30↔55); feedback de pulsación con inset
  1–2px además del cambio de color actual.

## 5) Rendimiento y restricciones

- Presupuesto por frame: <100 elementos animados; solo trig + draws de
  primitivas; sin texturas nuevas, sin shaders, sin allocations en render.
- `measure_text_cached` solo con strings estables (regla existente).
- Fuentes bitmap: **solo ASCII** en cualquier texto nuevo.
- Los tiempos usan `time.monotonic()` relativo a `show_event`.

## 6) Verificación

Harness offscreen (receta conocida: `.venv` + `DISPLAY=:1` + render N frames +
`rl.take_screenshot`): splash en t≈0.8 (anillo dibujándose) y t≈2.5
(asentado); home en cascada (t≈0.25) y asentada (t≈1.5); menú con el marcador
a mitad de deslizamiento y asentado. Al final, refrescar las capturas del
README (`docs/images/ui-*.png`, non-LFS).

## Fuera de alcance

Onroad (HUD, path, alertas), diálogo QR (ya rediseñado), paneles interiores de
settings (toggles/device/…), textos/traducciones.
