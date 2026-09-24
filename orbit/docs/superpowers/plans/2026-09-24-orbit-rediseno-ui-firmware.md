# Rediseño «Órbita · Grafito» de la UI del firmware — Plan de implementación


**Goal:** Llevar la identidad «Órbita · Grafito» de la app ORBIT a la UI del firmware ORBITPILOT (paleta, secciones, anillo Dúplex, campo orbital, iconos, splash), sin tocar lógica y sin ningún movimiento nuevo en marcha.

**Architecture:** Un módulo hoja de tokens (`selfdrive/ui/orbit_theme.py`, solo importa `pyray`) sustituye a las 5 copias de la paleta navy. Dos módulos de dibujo nuevos, también hoja: `selfdrive/ui/widgets/orbit_duplex.py` (anillo Dúplex y logo animado) e `selfdrive/ui/widgets/orbit_icons.py` (glifos propios). El campo orbital sustituye al `Starfield` dentro de `orbit_fx.py`. Tests puros y AST con pytest, sin ventana.

**Tech Stack:** Python 3.12, raylib vía `pyray` (`.venv` del repo), pytest.

**Spec:** `orbit/docs/superpowers/specs/2026-09-24-orbit-rediseno-ui-firmware-design.md` (identidad común: spec de la app en ORBIT-IoV).

## Global Constraints

- Repo `/home/drago/Desktop/openpilot`, rama `rediseno-orbita` (NO usar worktree; NO cambiar de rama). Comandos desde la raíz del repo con `.venv/bin/python3`.
- Tests: `.venv/bin/python3 -m pytest selfdrive/ui/tests/test_orbit_*.py -q`. Base: 10 pasan. No romper ninguno.
- Solo presentación: no cambiar lógica de mando, Params, MQTT, controles ni widgets upstream no-ORBIT (salvo los recoloreos listados).
- Sin dependencias nuevas; sin assets nuevos obligatorios (todo se dibuja con primitivas raylib).
- Paleta exacta (spec §3): fondo `#0A0E14`, sup1 `#131A24`, sup2 `#19222F`, sup3 `#212C3C`, borde `#263243`, borde fuerte `#6E7F97`, texto1 `#E8EEF6`, texto2 `#A2B1C6`, texto3 `#93A2B8`, pulso `#22D3EE`, acción `#86B9F7` (tinta encima `#05141E`), OK `#4ADE80`, aviso `#F5C842`, peligro tinta `#FF8A8A`, freno `#B91C1C` + blanco, azul profundo `#2563EB` solo en el degradado del logo, verde profundo `#16A34A` solo en el degradado del logo.
- Secciones: vehiculo `#86B9F7`, mapa `#86DCCB`, viajes `#F2BE9E`, cabina = pulso, mando `#B3A7F2`, registro `#E9A3CF`, ajustes `#B5C0CE`, cuenta `#D9B6F2`, ayuda `#F4CDDF`, desarrollo `#CDD5DF`. Nunca relleno de botón ni texto de estado.
- Onroad: **ningún movimiento nuevo**; los overlays onroad no pueden importar `orbit_fx`, `orbit_duplex` ni `orbit_icons`.
- Estilo del repo: indentación de 2 espacios, comentarios en español como el código ORBIT existente.

## Review Focus

1. **Botones que eran azul `#2563EB` con texto blanco**: al pasar a acción `#86B9F7` el texto debe pasar a `#05141E` (si no, 2,1:1). Cubierto por el test de contraste (Tarea 1) y revisado en la Tarea 4.
2. **Banner de frenada remota onroad**: debe seguir siendo relleno rojo `#B91C1C` con texto blanco y sin animación. Test AST en la Tarea 5.
3. **Splash que no cierra**: si el dueño no toca, debe cerrarse solo (≈2,2 s); tocar lo cierra antes. Tarea 6.
4. **Home sin conexión ORBIT**: satélite como anillo hueco quieto y subida del Dúplex apagada; no debe animar nada que sugiera enlace vivo. Tarea 7.
5. **Pantallas con texto sobre el campo orbital**: el texto sigue ≥ 4,5:1 (las órbitas y estrellas son ≤ 20 % de alfa). Tarea 7.

---

### Task 1: Tokens Grafito y test de contraste

**Files:**
- Create: `selfdrive/ui/orbit_theme.py`
- Test: `selfdrive/ui/tests/test_orbit_theme.py`

**Interfaces:**
- Produces: constantes `rl.Color` `FONDO, SUP1, SUP2, SUP3, BORDE, BORDE_FUERTE, TEXTO1, TEXTO2, TEXTO3, PULSO, ACCION, SOBRE_ACCION, OK, OK_PROFUNDO, AVISO, PELIGRO, FRENO, SOBRE_FRENO, AZUL_PROFUNDO`; `SECCION: dict[str, rl.Color]` con claves `vehiculo, mapa, viajes, cabina, mando, registro, ajustes, cuenta, ayuda, desarrollo`; funciones `contraste(a, b) -> float`, `mezcla(fg, alfa, fondo) -> rl.Color`, `con_alfa(c, a01) -> rl.Color`.

- [ ] **Step 1: Test (falla)** — crear `selfdrive/ui/tests/test_orbit_theme.py`:

```python
# Contraste de la paleta Grafito del firmware (misma identidad que la app ORBIT).
from openpilot.selfdrive.ui import orbit_theme as t


def _hex(c):
  return (c.r << 16) | (c.g << 8) | c.b


def test_valores_exactos():
  esperado = {
    'FONDO': 0x0A0E14, 'SUP1': 0x131A24, 'SUP2': 0x19222F, 'SUP3': 0x212C3C,
    'BORDE': 0x263243, 'BORDE_FUERTE': 0x6E7F97,
    'TEXTO1': 0xE8EEF6, 'TEXTO2': 0xA2B1C6, 'TEXTO3': 0x93A2B8,
    'PULSO': 0x22D3EE, 'ACCION': 0x86B9F7, 'SOBRE_ACCION': 0x05141E,
    'OK': 0x4ADE80, 'OK_PROFUNDO': 0x16A34A, 'AVISO': 0xF5C842,
    'PELIGRO': 0xFF8A8A, 'FRENO': 0xB91C1C, 'SOBRE_FRENO': 0xFFFFFF, 'AZUL_PROFUNDO': 0x2563EB,
  }
  for nombre, valor in esperado.items():
    assert _hex(getattr(t, nombre)) == valor, nombre
  assert set(t.SECCION) == {'vehiculo', 'mapa', 'viajes', 'cabina', 'mando', 'registro',
                            'ajustes', 'cuenta', 'ayuda', 'desarrollo'}
  assert _hex(t.SECCION['cabina']) == 0x22D3EE
  assert _hex(t.SECCION['mando']) == 0xB3A7F2


def _fondos():
  superficies = [t.FONDO, t.SUP1, t.SUP2, t.SUP3]
  mas_clara = max(t.SECCION.values(), key=lambda c: t._luminancia(c))
  return superficies + [t.mezcla(t.PULSO, 0.22, t.FONDO), t.mezcla(mas_clara, 0.12, t.FONDO)]


def test_texto_y_tintas_llegan_a_aa():
  for nombre in ('TEXTO1', 'TEXTO2', 'TEXTO3', 'PULSO', 'ACCION', 'OK', 'AVISO', 'PELIGRO'):
    for f in _fondos():
      assert t.contraste(getattr(t, nombre), f) >= 4.5, nombre


def test_secciones_se_leen():
  for nombre, c in t.SECCION.items():
    for f in _fondos():
      assert t.contraste(c, f) >= 4.5, nombre


def test_borde_fuerte_y_rellenos():
  for f in (t.FONDO, t.SUP1, t.SUP2, t.SUP3):
    assert t.contraste(t.BORDE_FUERTE, f) >= 3.0
  assert t.contraste(t.SOBRE_ACCION, t.ACCION) >= 4.5
  assert t.contraste(t.SOBRE_FRENO, t.FRENO) >= 4.5


def test_con_alfa():
  assert t.con_alfa(t.PULSO, 0.5).a == 127
  assert t.con_alfa(t.PULSO, 2.0).a == 255
```

- [ ] **Step 2: Ejecutar y ver que falla** — `.venv/bin/python3 -m pytest selfdrive/ui/tests/test_orbit_theme.py -q` → error de import.

- [ ] **Step 3: Implementación** — crear `selfdrive/ui/orbit_theme.py`:

```python
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
```

- [ ] **Step 4: Ejecutar** — mismo comando → PASS (5 tests). Y `.venv/bin/python3 -m pytest selfdrive/ui/tests/test_orbit_*.py -q` → 15 pasan.

- [ ] **Step 5: Commit** — `git add selfdrive/ui/orbit_theme.py selfdrive/ui/tests/test_orbit_theme.py && git commit -m "ui(orbit): tokens Grafito y test de contraste"`

---

### Task 2: Anillo Dúplex y logo animado en raylib

**Files:**
- Create: `selfdrive/ui/widgets/orbit_duplex.py`
- Test: `selfdrive/ui/tests/test_orbit_duplex.py`

**Interfaces:**
- Consumes: `orbit_theme` (Task 1).
- Produces:
  - `tramo_bajada(p: float) -> tuple[float, float]` y `tramo_subida(p: float) -> tuple[float, float]`: (inicio, fin) en grados raylib (0° = derecha, positivo = sentido horario en pantalla) del arco dibujado a progreso `p` ∈ [0,1]. Bajada: de 240° (arriba-izquierda) hacia 120° pasando por 180°; a `p` devuelve `(240 - 120*p, 240)`. Subida: de 60° (abajo-derecha) hacia −60° pasando por 0°; a `p` devuelve `(60 - 120*p, 60)`.
  - `punto(cx, cy, r, grados) -> tuple[float, float]`.
  - `draw_duplex_ring(cx, cy, radio, subida_activa: bool, dibujo: float = 1.0)`: anillo tenue (texto2 al 25 %, grosor radio·3/76) → arcos de grosor radio·13/76 con extremos redondeados (círculo en cada extremo) — bajada en texto2 al 70 % (NUNCA verde aquí), subida en ACCION si `subida_activa` o texto2 al 30 % si no — → núcleo (círculo relleno FONDO radio·30/76, aro TEXTO1 grosor radio·4/76, halo PULSO al 12 % radio·44/76, punto PULSO radio·10/76). Tramos de `dibujo`: anillo 0–0,3, arcos 0,3–0,7, núcleo 0,6–0,9.
  - `draw_orbit_logo(cx, cy, tam, t: float)`: el logo animado de la spec (§4). `t` ∈ [0,1] = 1,4 s. Tramos: anillo 0–0,214; arcos (bajada OK→OK_PROFUNDO, subida AZUL_PROFUNDO→ACCION; a falta de degradado por arco, usar el color medio o dibujar el arco en 12 segmentos interpolando color) 0,214–0,5 con ease-out cúbico; cabezas de flecha (triángulos del SVG) 0,464–0,571; núcleo (escala 0,6→1) 0,5–0,679; pulso ECG (dos polilíneas del SVG, trazadas desde el centro hacia fuera) 0,571–0,786. Geometría del SVG del logo en caja 240×240 escalada a `tam`: anillo r76, arcos r76 grosor 13, núcleo r17 aro 5 + punto r6,5, ECG izq `(103,120)(90,120)(85,129)(80,111)(75,120)(62,120)`, der `(137,120)(150,120)(155,111)(160,129)(165,120)(178,120)`, cabeza bajada `(91.5,191.3)(83.9,176.5)(74.9,192.1)`, cabeza subida `(148.5,48.7)(156.1,63.5)(165.1,47.9)`.
  - Usar `rl.draw_ring(center, inner, outer, start_deg, end_deg, segments, color)`, `rl.draw_circle_v`, `rl.draw_line_ex`, `rl.draw_triangle`. Nada de texturas ni shaders.

- [ ] **Step 1: Test (falla)** — crear `selfdrive/ui/tests/test_orbit_duplex.py`:

```python
import math

from openpilot.selfdrive.ui.widgets import orbit_duplex as dx


def test_bajada_va_por_la_izquierda_de_arriba_abajo():
  assert dx.tramo_bajada(0.0) == (240.0, 240.0)
  assert dx.tramo_bajada(1.0) == (120.0, 240.0)
  ini, fin = dx.tramo_bajada(1.0)
  x, _ = dx.punto(0, 0, 1, (ini + fin) / 2)   # 180°: lado izquierdo
  assert x < -0.99


def test_subida_va_por_la_derecha_de_abajo_arriba():
  assert dx.tramo_subida(0.0) == (60.0, 60.0)
  assert dx.tramo_subida(1.0) == (-60.0, 60.0)
  ini, fin = dx.tramo_subida(1.0)
  x, _ = dx.punto(0, 0, 1, (ini + fin) / 2)   # 0°: lado derecho
  assert x > 0.99


def test_progreso_se_acota():
  assert dx.tramo_bajada(-1) == dx.tramo_bajada(0)
  assert dx.tramo_subida(5) == dx.tramo_subida(1)


def test_punto_en_pantalla_y_hacia_abajo():
  x, y = dx.punto(10, 20, 2, 90)   # 90° = abajo (y crece hacia abajo)
  assert math.isclose(x, 10, abs_tol=1e-9) and math.isclose(y, 22)
```

- [ ] **Step 2:** ejecutar → falla por import.
- [ ] **Step 3:** implementar el módulo con las funciones de **Interfaces** (cabecera en español explicando bajada = órdenes, subida = telemetría, núcleo = coche). `tramo_*` acotan `p` a [0,1] y devuelven floats.
- [ ] **Step 4:** ejecutar el test → PASS; `pytest selfdrive/ui/tests/test_orbit_*.py -q` en verde. Comprobación manual de humo: `timeout 20 env BIG=1 OFFSCREEN=1 .venv/bin/python3 -c "import pyray as rl; from openpilot.selfdrive.ui.widgets import orbit_duplex as dx; rl.set_config_flags(rl.ConfigFlags.FLAG_WINDOW_HIDDEN); rl.init_window(400,400,'t'); rl.begin_drawing(); dx.draw_duplex_ring(200,200,96,True,1.0); [dx.draw_orbit_logo(200,200,170,v) for v in (0,.3,.6,1)]; rl.end_drawing(); rl.close_window(); print('ok')"` → imprime `ok`.
- [ ] **Step 5:** commit `ui(orbit): anillo Dúplex y logo «La órbita se cierra» en raylib`.

---

### Task 3: Iconos propios en raylib

**Files:**
- Create: `selfdrive/ui/widgets/orbit_icons.py`
- Test: `selfdrive/ui/tests/test_orbit_icons.py`

**Interfaces:**
- Consumes: `orbit_theme`.
- Produces: `GLIFOS = ('vehiculo','mapa','cuenta','cabina','mando','registro','viajes','ajustes','ayuda','desarrollo','enlace')`; `posicion_satelite(angulo: float) -> tuple[float, float]` en rejilla de 24 (centro 12,12; órbita rx 19, ry 7, inclinada −24°); `draw_orbit_icon(glifo: str, x: float, y: float, tam: float, acento: rl.Color, tinta: rl.Color = TEXTO1, orbita: bool = False, t: float = 0.0)` — `(x, y)` es la esquina superior izquierda de la caja del glifo de lado `tam`; con `orbita` la órbita sobresale (caja efectiva `tam*44/24`, centrada). El satélite está en `posicion_satelite(t * 2π / 6)` (el llamador pasa `t=0` para dejarlo quieto).
- Trazado: exactamente los glifos de la app (fichero de referencia `ORBIT-IoV/app/lib/theme/orbit_icon.dart` (rama `rediseno-orbita`), función `_dibujarGlifo`), traducidos a raylib con grosor `1.75*tam/24`: líneas `rl.draw_line_ex`; arcos de circunferencia `rl.draw_ring`; curvas Bézier cúbicas muestreadas en 12 segmentos con `draw_line_ex`; círculos de acento rellenos `rl.draw_circle_v`, de acento en trazo `rl.draw_ring`. `enlace` = dos arcos del Dúplex en miniatura (izquierda tinta de arriba abajo, derecha acento de abajo arriba, con punta de flecha) + punto central acento.

- [ ] **Step 1: Test (falla)** — `selfdrive/ui/tests/test_orbit_icons.py`:

```python
import math

from openpilot.selfdrive.ui.widgets import orbit_icons as ic


def test_glifos_de_la_app_y_enlace():
  assert set(ic.GLIFOS) >= {'vehiculo', 'mapa', 'cuenta', 'cabina', 'mando', 'registro',
                            'viajes', 'ajustes', 'ayuda', 'desarrollo', 'enlace'}


def test_satelite_en_la_orbita_inclinada():
  r = math.radians(-24)
  x, y = ic.posicion_satelite(0.0)
  assert math.isclose(x, 12 + 19 * math.cos(r), abs_tol=1e-9)
  assert math.isclose(y, 12 + 19 * math.sin(r), abs_tol=1e-9)
```

- [ ] **Step 2:** ejecutar → falla. **Step 3:** implementar. **Step 4:** tests en verde + humo offscreen como en la Tarea 2 dibujando los 11 glifos con y sin órbita → `ok`. **Step 5:** commit `ui(orbit): iconos propios con órbita y satélite`.

---

### Task 4: Paleta única en toda la UI ORBIT offroad + guardrail

**Files:**
- Modify: `selfdrive/ui/widgets/orbit_fx.py` (paleta L17-27 → importar de `orbit_theme`; conservar los nombres como alias para no romper consumidores: `VOID = t.FONDO`, `NAVY = t.SUP1`, `PANEL = t.SUP2`, `HAIRLINE = t.BORDE`, `CYAN = t.PULSO`, `BLUE_HI = t.ACCION`, `GREEN = t.OK`, `INK = t.TEXTO1`, `MUTED = t.TEXTO2`, `MUTED_DIM = t.TEXTO3`, `STAR = t.TEXTO1`)
- Modify: `selfdrive/ui/layouts/home.py` (paleta L29-41 igual; `BLUE` → `t.ACCION` y todo texto dibujado sobre `BLUE` pasa a `t.SOBRE_ACCION`)
- Modify (recolorear a tokens, mismo criterio de correspondencia de la spec §3): `selfdrive/ui/layouts/sidebar.py`, `selfdrive/ui/sunnypilot/layouts/sidebar.py`, `selfdrive/ui/widgets/offroad_alerts.py`, `selfdrive/ui/layouts/onboarding.py` (color ORBIT BLUE_DEEP L104), `selfdrive/ui/onroad/exp_button.py` (L21), `selfdrive/ui/onroad/augmented_road_view.py` (L31, L118), `selfdrive/ui/widgets/orbit_section.py`, `selfdrive/ui/widgets/orbit_enroll_dialog.py`, `selfdrive/ui/widgets/about_drago.py`, `selfdrive/ui/sunnypilot/layouts/settings/orbit_panel.py`, `selfdrive/ui/sunnypilot/layouts/settings/orbit_sub_layouts/*.py`, `selfdrive/ui/sunnypilot/layouts/orbit_splash.py` (solo colores; el rediseño del splash es la Tarea 6)
- Create: `selfdrive/ui/tests/test_orbit_paleta.py`

**Requisitos:**
- Todo color ORBIT sale de `orbit_theme` (o de los alias de `orbit_fx`). Rellenos rojos → `t.FRENO` con texto `t.SOBRE_FRENO`; tintas de error → `t.PELIGRO`. Botones azules → `t.ACCION` con texto `t.SOBRE_ACCION`.
- Los colores de sección solo en cabeceras/filetes/iconos, con esta tabla: panel ORBIT y `_MandoCard` = `mando`; `server_settings` = `ajustes`; `advanced_settings` = `desarrollo`; `steer_mode` = `mando`; diálogo de vinculación = `vehiculo`; «acerca de» = `ayuda`.
- No cambiar textos, tamaños ni lógica.

- [ ] **Step 1: Guardrail (falla)** — `selfdrive/ui/tests/test_orbit_paleta.py`:

```python
# La paleta navy antigua no vuelve: toda la UI toma el color de orbit_theme.
import pathlib
import re

RAIZ = pathlib.Path(__file__).resolve().parents[1]   # selfdrive/ui
NAVY = [(11, 18, 32), (22, 35, 58), (27, 44, 72), (43, 62, 95), (226, 236, 255),
        (147, 180, 230), (92, 117, 153), (125, 180, 255), (37, 99, 235)]
PERMITIDOS = {'orbit_theme.py'}


def test_sin_paleta_navy():
  malos = []
  for f in RAIZ.rglob('*.py'):
    if 'tests' in f.parts or f.name in PERMITIDOS:
      continue
    texto = f.read_text()
    for r, g, b in NAVY:
      if re.search(rf'rl\.Color\(\s*{r}\s*,\s*{g}\s*,\s*{b}\s*[,)]', texto):
        malos.append(f'{f.relative_to(RAIZ)}: ({r},{g},{b})')
  assert not malos, '\n'.join(malos)
```

(El azul `(37, 99, 235)` solo puede vivir en `orbit_theme.py` como `AZUL_PROFUNDO`; si algún fichero upstream no-ORBIT lo usa por su cuenta, añadirlo a una lista `EXCEPCIONES` con comentario del motivo, no a `PERMITIDOS`.)

- [ ] **Step 2:** ejecutar → falla listando los ficheros. **Step 3:** migrar hasta que pase. **Step 4:** todos los `test_orbit_*.py` en verde + arranque de humo `timeout 20 env BIG=1 OFFSCREEN=1 .venv/bin/python3 selfdrive/ui/ui.py` sin traceback (salida esperada: termina por timeout). **Step 5:** commit `ui(orbit): paleta Grafito única en toda la UI ORBIT`.

---

### Task 5: Overlays onroad en Grafito, sin movimiento

**Files:**
- Modify: `selfdrive/ui/sunnypilot/onroad/orbit_command_overlay.py` (paleta L35-40), `selfdrive/ui/sunnypilot/onroad/orbit_follow_coach.py` (L25-32), `selfdrive/ui/sunnypilot/onroad/orbit_hardbrake_overlay.py`, `selfdrive/ui/onroad/alert_renderer.py` (solo la alerta ORBIT de la L51, si define color propio)
- Create: `selfdrive/ui/tests/test_orbit_onroad_quieto.py`

**Requisitos:** píldoras sobre `t.SUP1` con borde `t.BORDE_FUERTE` y texto `t.TEXTO1`/`t.TEXTO2`; chip «FRENADA PROBABLE» con tinta `t.AVISO`; banner de frenada remota relleno `t.FRENO` y texto `t.SOBRE_FRENO`; estados de fallo con `t.PELIGRO`. Mismos tamaños, posiciones, latches y tiempos. Nada de glow nuevo ni easing.

- [ ] **Step 1: Test (falla)** — `selfdrive/ui/tests/test_orbit_onroad_quieto.py`:

```python
# En marcha nada decorativo se mueve: los overlays onroad ORBIT no pueden
# importar módulos de animación y toman el color de orbit_theme.
import ast
import pathlib

ONROAD = pathlib.Path(__file__).resolve().parents[1] / 'sunnypilot' / 'onroad'
FICHEROS = ['orbit_command_overlay.py', 'orbit_follow_coach.py', 'orbit_hardbrake_overlay.py']
PROHIBIDOS = {'orbit_fx', 'orbit_duplex', 'orbit_icons'}


def _modulos(arbol):
  for n in ast.walk(arbol):
    if isinstance(n, ast.Import):
      yield from (a.name for a in n.names)
    elif isinstance(n, ast.ImportFrom):
      yield n.module or ''
      yield from (f'{n.module}.{a.name}' for a in n.names)


def test_onroad_sin_animacion_y_con_tokens():
  for nombre in FICHEROS:
    mods = list(_modulos(ast.parse((ONROAD / nombre).read_text())))
    assert not [m for m in mods if any(p in m for p in PROHIBIDOS)], nombre
    assert any('orbit_theme' in m for m in mods), f'{nombre} no usa orbit_theme'
```

- [ ] **Step 2:** falla. **Step 3:** recolorear. **Step 4:** verde + humo `ui.py`. **Step 5:** commit `ui(orbit): overlays onroad en Grafito, sin movimiento nuevo`.

---

### Task 6: Splash «La órbita se cierra»

**Files:**
- Modify: `selfdrive/ui/sunnypilot/layouts/orbit_splash.py`

**Requisitos:** mantener la clase `OrbitSplash`, su API y la forma en que `layouts/main.py` la empuja y la cierra (tocar para cerrar; cierre automático). Nueva secuencia: fondo `t.FONDO`; `orbit_duplex.draw_orbit_logo(cx, cy, 340, t_anim)` con `t_anim = clamp(transcurrido / 1.4)`; wordmark «ORBIT» (misma fuente/tamaño que hoy, color `t.TEXTO1`, sin degradado de colores antiguos) que aparece con opacidad en 0,75–0,93 de `t_anim` y un subrayado `t.PULSO` que se alarga en 0,82–0,98; lema «Open Remote Bidirectional IoV Telemetry» en `t.TEXTO2` en 0,9–1,0; badge «powered by drago» igual que hoy. Cierre automático a los 2,2 s (constante `DURACION = 2.2`). Eliminar el anillo con giro continuo (`RING_SPIN_DPS`) y cualquier bucle. Sin `Starfield`.

- [ ] Steps: implementar → `test_orbit_*.py` en verde → humo `ui.py` → commit `ui(orbit): splash «La órbita se cierra» en 1,4 s`.

---

### Task 7: Home offroad con campo orbital y anillo Dúplex

**Files:**
- Modify: `selfdrive/ui/widgets/orbit_fx.py` (añadir `CampoOrbital`, conservar `Starfield` si algún consumidor lo usa o eliminarlo si solo lo usaba el home — y su test en `test_orbit_fx.py` se adapta), `selfdrive/ui/layouts/home.py`, `selfdrive/ui/tests/test_orbit_fx.py`

**Requisitos:**
- `CampoOrbital(seed=7)`: 60 estrellas precomputadas (alfa 0,05–0,15, `t.TEXTO1`); `render(rect, centro, color, t, conectado: bool)` dibuja tres elipses (semiejes 120×40, 205×70, 300×104, escaladas ×1,6 para 2160×1080) inclinadas −14° en `color` al 20 % (elipses muestreadas con 72 segmentos `draw_line_ex`, grosor 1,5), y el satélite de este coche en la órbita del medio: si `conectado`, núcleo `t.PULSO` r5 con halo al 35 % r18 recorriendo la órbita en 40 s (`t` en segundos); si no, anillo hueco `t.TEXTO3` al 60 % quieto. Determinista por seed (test).
- Home: el bloque de marca sustituye el PNG del logo por `draw_duplex_ring(..., subida_activa=conectado, dibujo=entrada)` (entrada 0→1 en 0,7 s al mostrarse el home, con `ease_out_cubic`); el campo orbital, detrás de todo, centrado en ese anillo, color `t.SECCION['vehiculo']`; tarjetas `t.SUP1` con borde `t.BORDE`, cabeceras de tarjeta en `t.TEXTO2` mayúsculas; pill de enlace: conectado → borde/tinta `t.PULSO`, sin conexión → `t.AVISO` (como hoy, recoloreado); onda de telemetría en `t.PULSO` (y línea plana `t.TEXTO3` sin conexión).
- `conectado` = el mismo criterio que hoy usa el home para `OrbitConnected`.

- [ ] **Step 1: Test** — añadir a `selfdrive/ui/tests/test_orbit_fx.py`:

```python
def test_campo_orbital_determinista():
  a = fx.CampoOrbital(seed=7)
  b = fx.CampoOrbital(seed=7)
  assert a.estrellas == b.estrellas
  assert len(a.estrellas) == 60
```

(`estrellas` = lista de tuplas `(x01, y01, radio, alfa)` en coordenadas normalizadas.)

- [ ] Steps: test falla → implementar → verde → humo `ui.py` → commit `ui(orbit): home con campo orbital y anillo Dúplex`.

---

### Task 8: Cabeceras de sección con icono propio

**Files:**
- Modify: `selfdrive/ui/widgets/orbit_section.py` (`SectionHeaderSP`), `selfdrive/ui/sunnypilot/layouts/settings/orbit_panel.py` y `orbit_sub_layouts/*.py` (pasar la sección)

**Requisitos:** `SectionHeaderSP` acepta `seccion: str | None = None`; con sección dibuja a la izquierda `orbit_icons.draw_orbit_icon(glifo, ..., tam=40, acento=t.SECCION[seccion], orbita=True, t=time.monotonic())` y un filete corto (24×4, radio 2) del color de la sección bajo el título; sin sección, igual que hoy recoloreado. Glifo por sección: mando→`mando`, ajustes→`ajustes`, desarrollo→`desarrollo`, vehiculo→`vehiculo`, ayuda→`ayuda`, cabina→`enlace`. Tabla de secciones de la Tarea 4. El satélite solo se mueve aquí (offroad, menús).

- [ ] Steps: implementar → `test_orbit_panel_help.py` y `test_orbit_panel_refs.py` siguen en verde → humo `ui.py` → commit `ui(orbit): cabeceras de sección con icono y color propios`.

---

### Task 9: Script de capturas offscreen

**Files:**
- Create: `selfdrive/ui/tests/orbit_capturas.py` (script, no test de pytest: nombre sin prefijo `test_`)

**Requisitos:** `BIG=1 OFFSCREEN=1 .venv/bin/python3 selfdrive/ui/tests/orbit_capturas.py <dir>` inicializa `gui_app` (2160×1080), fija Params de ejemplo mínimos si hacen falta (sin tocar el dispositivo real: usar el Params de PC del repo), y guarda PNG en `<dir>`: `splash_0.5s.png`, `splash_1.4s.png`, `home_conectado.png`, `home_sin_conexion.png`, `panel_orbit.png`, `vinculacion_qr.png`. Para cada pantalla: instanciar el layout/widget, renderizar unos fotogramas y `rl.take_screenshot` o `rl.load_image_from_screen` + `export_image`. Termina solo (sin bucle infinito).

- [ ] Steps: implementar → ejecutar con `timeout 120` → comprobar que existen los 6 PNG → commit `ui(orbit): script de capturas offscreen del rediseño`.
