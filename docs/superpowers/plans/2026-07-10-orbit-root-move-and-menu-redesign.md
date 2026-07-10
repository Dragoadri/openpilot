# ORBIT root move + menu redesign — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `sicuem/` desaparece: la integración viva pasa a `orbit/` en la raíz; el panel de ajustes UEM se convierte en el panel ORBIT rediseñado (logo, secciones, sin ajustes muertos).

**Architecture:** Refactor mecánico primero (mover paquete + symlink + recablear imports/rutas, repo verde en cada commit), después limpieza de features muertas (INTERVALOS), después la capa UI (rename + rewrite de paneles), y al final params + verificación visual offscreen.

**Tech Stack:** Python 3, raylib/pyray (UI), paho-mqtt, openpilot Params, scons (rebuild de `common` al tocar params_keys.h).

**Spec:** `docs/superpowers/specs/2026-07-10-orbit-root-move-and-menu-redesign-design.md`

## Global Constraints

- Commits SIN atribución de IA (regla dura de CLAUDE.md); autor solo dragoadri.
- NO renombrar el topic MQTT `sicuem_torque/<dongle>` (contrato con orbit-iov) ni tocar specs históricos ni menciones de la rama `sicuem-mig`.
- Textos de UI: español ASCII (sin acentos ni `—`/`…` — fuentes bitmap).
- Solo tokens de color `ORBIT_*` existentes; no tocar `system/ui/sunnypilot/widgets/list_view.py` compartido.
- Assets nuevos/ORBIT: non-LFS vía `.gitattributes` (patrón existente).
- Verificar cada fase: `py_compile` + grep residual + (fase UI) screenshots offscreen.
- El catálogo de funcionalidades (Parte C del spec) NO se implementa en este plan.

---

### Task 1: Mover el paquete a `orbit/` + symlink + recablear imports y rutas

**Files:**
- Move: `sicuem/orbit/` → `orbit/` (git mv), `sicuem/adelantamiento.py` → `orbit/adelantamiento.py`, `sicuem/docs/STEERING_INTERNALS.md` + `orbit/GUIA_JETSON_COMMA.md` → `orbit/docs/`, `sicuem/docs/2026-05-07-comma-jetson-mode-{design,plan}.md` → `docs/superpowers/specs/`
- Delete: ~25 scripts muertos + 6 .md de notas + `sicuem/{canales,config,lead_info}.json` + `event_codes_map.json` + `test/telem_general/` + `sicuem_log_20260701_133312.txt`
- Symlink: `openpilot/sicuem` → reemplazar por `openpilot/orbit -> ../orbit`
- Modify: `system/manager/manager.py:30`, `selfdrive/controls/controlsd.py:31,102,349`, `selfdrive/car/card.py:226`, `selfdrive/selfdrived/selfdrived.py:570`, `tools/sim/lib/camerad.py:16,67,81,103,127`, `tools/sim/mock_jetson_torque.py:9`, `orbit/mqtt_comandos.py:13,391,397,406,412,424,432`, `orbit/camera_sender.py:95`, `orbit/test/test_obstacle_pulse.py:12`, `orbit/test/test_obstacle_pulse_zmq.py:11`, `selfdrive/ui/widgets/orbit_server.py:4,17`, `selfdrive/ui/sunnypilot/layouts/settings/uem_sub_layouts/jetson_settings.py:77-78`, `.../server_ip_settings.py:85`, `selfdrive/ui/sunnypilot/onroad/orbit_command_overlay.py:11`, `.gitignore:49-52`, `orbit/docs/GUIA_JETSON_COMMA.md` (rutas device), `orbit/adelantamiento.py` (docstring)

- [ ] **Step 1: git mv del paquete y docs, git rm de lo muerto**

```bash
git mv sicuem/orbit orbit
git mv sicuem/adelantamiento.py orbit/adelantamiento.py
mkdir -p orbit/docs
git mv orbit/GUIA_JETSON_COMMA.md orbit/docs/
git mv sicuem/docs/STEERING_INTERNALS.md orbit/docs/
git mv sicuem/docs/2026-05-07-comma-jetson-mode-design.md docs/superpowers/specs/
git mv sicuem/docs/2026-05-07-comma-jetson-mode-plan.md docs/superpowers/specs/
git rm -q orbit/orbit_speed_buttons.py orbit/orbit_speed_direct.py orbit/orbit_speed_global.py \
  orbit/orbit_speed_no_params.py orbit/diagnostico_mqtt.py orbit/diagnostico_mqtt_completo.py \
  orbit/simular_sistema_orbit.py orbit/verificar_variables_globales.py orbit/event_codes_map.json \
  orbit/test_imports.py orbit/test_lane_change.py orbit/test_all_commands.py \
  orbit/test_comandos_corregido.py orbit/test_comandos_servidor.py orbit/test_comandos_servidor_actualizado.py \
  orbit/test_setspeed_fijo.py orbit/test_speed_commands.py orbit/test_todos_comandos_ultra_simple.py \
  orbit/test_velocidad_corregida_final.py orbit/test_velocidad_corregido.py orbit/test_velocidad_directo.py \
  orbit/test_velocidad_directo_final.py orbit/test_velocidad_final.py orbit/test_velocidad_global.py \
  orbit/test_velocidad_simplificado.py orbit/test_velocidad_simulacion.py orbit/test_velocidad_ultra_simple.py \
  orbit/CAMBIO_CARRIL_MQTT.md orbit/FLUJO_CAMBIO_CARRIL.md orbit/DATOS_TIEMPO_REAL.md \
  orbit/EXPANSION_TELEMETRIA.md orbit/PRUEBA_SETSPEED_FIJO.md orbit/SOLUCION_PROBLEMAS.md
git rm -rq orbit/test/telem_general
git rm -q sicuem/canales.json sicuem/config.json sicuem/lead_info.json sicuem_log_20260701_133312.txt
rm -rf orbit/__pycache__ orbit/test/__pycache__
git rm openpilot/sicuem && ln -s ../orbit openpilot/orbit && git add openpilot/orbit
```
Comprobar después `ls sicuem/` = vacío (o solo restos untracked) y quitarlo.

- [ ] **Step 2: reescribir imports** — en TODOS los ficheros listados: `openpilot.sicuem.orbit` → `openpilot.orbit` (sed repo-wide excluyendo .git y docs/superpowers/specs).

- [ ] **Step 3: rutas literales** — `sicuem/orbit/` → `orbit/` en `camerad.py:16`, `orbit_server.py:17`, `jetson_settings.py:77` y `:78` (`/data/openpilot/sicuem/orbit/...` → `/data/openpilot/orbit/...`), `server_ip_settings.py:85`; docstrings/comentarios de los ficheros listados; rutas `/data/openpilot/sicuem/...` en `orbit/docs/GUIA_JETSON_COMMA.md:29,85,191`.

- [ ] **Step 4: .gitignore** — sección `# SICUEM / AdriPilot` pasa a `# ORBIT`: borrar `!sicuem/config.json` y `sicuem/mqttDebug.txt`; `sicuem/**/__pycache__/` → `orbit/**/__pycache__/`.

- [ ] **Step 5: docstring de adelantamiento.py** — añadir al principio: módulo DORMIDO conservado como material del adelantamiento C2; sus params `adelantamiento_vel_diff/distancia` se retiran de params_keys.h (C2 usará los `overtake_*`).

- [ ] **Step 6: verificar**

```bash
python3 -m py_compile orbit/*.py orbit/test/*.py system/manager/manager.py \
  selfdrive/controls/controlsd.py selfdrive/car/card.py selfdrive/selfdrived/selfdrived.py \
  tools/sim/lib/camerad.py selfdrive/ui/widgets/orbit_server.py
.venv/bin/python -c "import openpilot.orbit.orbit_obstacle_pulse, openpilot.orbit.orbit_steering_pulse" 2>/dev/null || \
  python3 -c "import openpilot.orbit.orbit_obstacle_pulse"
python3 -m pytest orbit/test/test_obstacle_pulse.py -q   # unittest puro, corre en host
grep -rn "openpilot.sicuem" --include="*.py" . | grep -v ".git" | wc -l   # esperado: 0
```

- [ ] **Step 7: commit** — `refactor: sicuem/orbit -> orbit/ en la raiz; muere sicuem/ (codigo muerto fuera, docs reubicados)`

### Task 2: `tools/sicuem` → `tools/orbit`

**Files:** Move: `tools/sicuem/` → `tools/orbit/`; rename `grab_sicuem_logs.sh` → `grab_orbit_logs.sh`. Modify: los 8 ficheros (autoreferencias de ruta en usos/comentarios; `OUTDIR` `./sicuem_logs` → `./orbit_logs`; `log.sh` `OUT="sicuem_log_..."` → `orbit_log_...`, `/tmp/sicuem_payload.$$` → `/tmp/orbit_payload.$$`). Dejar menciones históricas `sicuem-mig`.

- [ ] Step 1: `git mv tools/sicuem tools/orbit && git mv tools/orbit/grab_sicuem_logs.sh tools/orbit/grab_orbit_logs.sh`
- [ ] Step 2: actualizar autoreferencias (`tools/sicuem` → `tools/orbit`, nombres de salida). El import de `diag_mqtt_orbit.py:50` ya quedó `openpilot.orbit.*` en Task 1; revisar sus literales `/data/openpilot/.../config_mqtt.json:60,62`.
- [ ] Step 3: `bash -n tools/orbit/*.sh` + `python3 -m py_compile tools/orbit/*.py`; `grep -rn "tools/sicuem" . | grep -v .git` = 0.
- [ ] Step 4: commit — `refactor: tools/sicuem -> tools/orbit`

### Task 3: Eliminar INTERVALOS (hilo longcontrol + comando MQTT)

**Files:** Modify: `selfdrive/controls/lib/longcontrol.py` (quitar imports `threading`/`time`/`Params` si quedan sin uso, el bloque `# [Orbit] corte periódico...` del `__init__` (self.params + thread), el método `_toggle_long_control` completo, y el clip `if self.params.get_bool("DisableLongControl"): return ...` de `update()`); `orbit/mqtt_comandos.py` (línea de suscripción `/intervalos`, rama dispatch `elif topic.endswith("/intervalos")`, método `handle_intervalos` entero).

- [ ] Step 1: ediciones anteriores; `update()` queda empezando directamente por `self.long_control_state = long_control_state_trans(...)` tras los límites del PID.
- [ ] Step 2: `python3 -m py_compile selfdrive/controls/lib/longcontrol.py orbit/mqtt_comandos.py`; `grep -rn "intervalos_toggle\|DisableLongControl" --include="*.py" .` = 0 (el param key se retira en Task 6).
- [ ] Step 3: commit — `feat(orbit)!: eliminar demo INTERVALOS (corte longitudinal periodico) de firmware y comandos MQTT`

### Task 4: Rename de la capa UI + rediseño de paneles

**Files:**
- Move (git mv): `selfdrive/ui/sunnypilot/layouts/settings/uem.py` → `orbit_panel.py`; `uem_sub_layouts/` → `orbit_sub_layouts/`; dentro: `teluem_settings.py` → `telemetry_settings.py`, `server_ip_settings.py` → `server_settings.py` (jetson_settings.py conserva nombre)
- Create: `selfdrive/ui/widgets/orbit_section.py` (SectionHeaderSP)
- Rewrite: `orbit_panel.py` (clase `OrbitLayout`), `telemetry_settings.py` (clase `TelemetrySettingsLayout`), `server_settings.py` (clase `ServerSettingsLayout`), `jetson_settings.py` (rediseño interno)
- Modify: `selfdrive/ui/sunnypilot/layouts/settings/settings.py` (enum `"UEM"`→`"ORBIT"` en `:56`, import, registro `:139`, panel por defecto), `selfdrive/ui/layouts/home.py:91-99` (modal importa `orbit_sub_layouts.server_settings.ServerSettingsLayout`)
- Delete: `sunnypilot/selfdrive/assets/offroad/uem_logo.png`, `uem_logo_completo.png`, línea `uem_*.png` de `.gitattributes`

**Interfaces (produce):**
- `orbit_section.SectionHeaderSP(text: str)` — Widget no interactivo: etiqueta MAYUSCULAS 36px `ORBIT_CYAN` con alpha ~200 + hairline horizontal a la derecha; altura fija 64. Uso: elemento de Scroller.
- `orbit_panel.OrbitLayout()` — reemplaza `UemLayout`; mismo contrato Widget (render/show_event).
- `server_settings.ServerSettingsLayout(back_btn_callback)` — misma firma que la vieja `ServerIpSettingsLayout` (la consume el modal de home).
- `telemetry_settings.TelemetrySettingsLayout(back_btn_callback)`, `jetson_settings.JetsonSettingsLayout(back_btn_callback)` — firma sin cambios.

- [ ] **Step 1: git mv de ficheros/directorios.**

- [ ] **Step 2: `orbit_section.py`** — nuevo widget:

```python
import pyray as rl
from openpilot.selfdrive.ui.layouts.settings import settings as OP
from openpilot.system.ui.lib.application import gui_app, FontWeight
from openpilot.system.ui.lib.text_measure import measure_text_cached
from openpilot.system.ui.widgets import Widget

_HEADER_H = 64

class SectionHeaderSP(Widget):
  def __init__(self, text: str):
    super().__init__()
    self._text = text
    self._font = gui_app.font(FontWeight.BOLD)
    self.rect.height = _HEADER_H

  def _render(self, rect):
    size = measure_text_cached(self._font, self._text, 36)
    y = rect.y + (rect.height - size.y) / 2
    color = rl.Color(OP.ORBIT_CYAN.r, OP.ORBIT_CYAN.g, OP.ORBIT_CYAN.b, 200)
    rl.draw_text_ex(self._font, self._text, rl.Vector2(rect.x + 8, y), 36, 2, color)
    line_x = rect.x + 8 + size.x + 24
    line_y = rect.y + rect.height / 2
    if line_x < rect.x + rect.width - 16:
      rl.draw_line_ex(rl.Vector2(line_x, line_y), rl.Vector2(rect.x + rect.width - 16, line_y), 2, OP.ORBIT_HAIRLINE)
```
(Comprobar cómo fija altura un widget de Scroller — seguir el patrón de `LineSeparatorSP`/`Spacer` reales.)

- [ ] **Step 3: `server_settings.py`** — partir de la vieja: quitar `_sicuem_path`, `_sicuem_button`, `_read_sicuem_ip`, `_edit_sicuem` y su import; `_resolve_path("orbit/config_mqtt.json")`; exponer además una factoría `make_server_rows(owner) -> list` usada por la clase y por `OrbitLayout` (sección CONEXION) para no duplicar filas: fila broker (titulo "Servidor ORBIT (broker MQTT)", desc IP actual, EDITAR) + fila probar (PROBAR, estado en desc). La clase = Back + Scroller(make_server_rows(self)).

- [ ] **Step 4: `telemetry_settings.py`** — reescritura de la lista de toggles:

```python
TELEMETRY_TOGGLES = [
  ("carState_toggle", "carState", "Publica el estado del vehiculo (velocidad, pedales, volante) por MQTT."),
  ("carControl_toggle", "carControl", "Publica las ordenes de control por MQTT."),
  ("gpsLocationExternal_toggle", "gpsLocationExternal", "Publica la localizacion GPS externa por MQTT."),
  ("gpsLocation_toggle", "gpsLocation", "Publica la localizacion GPS del dispositivo por MQTT."),
  ("radarState_toggle", "radarState", "Publica los objetivos del radar por MQTT."),
  ("drivingModelData_toggle", "drivingModelData", "Publica la salida del modelo de conduccion por MQTT."),
  ("controlsState_toggle", "controlsState", "Publica el estado interno del control por MQTT."),
  ("liveCalibration_toggle", "liveCalibration", "Publica la calibracion en vivo por MQTT."),
]
```
Clase `TelemetrySettingsLayout` (resto igual que la vieja: fila camara + Back + Scroller). Nota en el docstring: el heartbeat se publica siempre. Guard PC/sim ya existe (open failure → INACTIVO).

- [ ] **Step 5: `jetson_settings.py` rediseño** — mismo comportamiento, nueva composición de items:

```python
items = [
  SectionHeaderSP(tr("ENLACE")),
  self._jetson_enabled_toggle,
  self._mode_selector,
  self._mode_status,        # texto largo del modo (se conserva: es la explicacion)
  self._obstacle_label,     # visible solo en modo 3 con estado
  SectionHeaderSP(tr("ESTADO")),
  self._status_torque,
  self._status_obstacle,
  SectionHeaderSP(tr("RED")),
  self._ip_button, self._comma_ip_button, self._img_port_button,
  self._torque_port_button, self._quality_button,
]
```
Fuera: `self._enabled_status` ("Estado: ACTIVA"), `self._status_mode` ("Modo actual"), `self._status_ip` ("IP Jetson" de solo lectura) y los `LineSeparatorSP` — y su código asociado (`_jetson_enabled_status_text`). El resto (diálogos, payloads, live-reload, `_update_state`) intacto. Config path ya es `orbit/config_jetson.json` (Task 1).

- [ ] **Step 6: `orbit_panel.py` (OrbitLayout)** — estructura del Scroller:

```python
# hero: widget propio _OrbitHero (logo 96px izq via gui_app.texture("img_orbit_logo.png",96,96),
#   wordmark "ORBIT" bold 56 + subtitulo "Estacion de control del vehiculo" muted 32,
#   y 4 chips de estado (SERVIDOR/ENLACE/CUENTA/JETSON) pill redondeada:
#   verde=ok, muted-dim=off; refresco de params/probe cacheado a 2s (patron home.py
#   _fast_refresh; ServerMonitor de orbit_server.py para broker+api))
items = [
  self._hero,                                   # ~220px
  SectionHeaderSP(tr("CONEXION")),
  *make_server_rows(self),                      # broker EDITAR + PROBAR
  SectionHeaderSP(tr("TELEMETRIA")),
  self._telemetry_status,                       # text_item "Estado" -> "Conectado - ultimo dato hace Ns" / "Sin conexion"
  self._telemetry_button,                       # "Canales de telemetria" -> TELEMETRY subpanel (siempre habilitado)
  SectionHeaderSP(tr("CONDUCCION")),
  self._show_blindspot_toggle,                  # igual que antes
  self._lane_warn_toggle,                       # c_carril: "AVISOS EN CAMBIO DE CARRIL" desc honesta (avisos de angulo muerto durante el cambio)
  SectionHeaderSP(tr("JETSON")),
  self._jetson_status,                          # text_item: "MODELO COMMA - 192.168.1.50" (+ " - torque OK" si fresco)
  self._jetson_button,                          # "Configurar Jetson" -> JETSON subpanel
  SectionHeaderSP(tr("PRUEBAS")),
  self._modo_debug_toggle,                      # igual
  self._silenciar_alertas_toggle,               # desc corta: "Oculta commIssue/locationd temporal. Solo pruebas (ver tools/orbit)."
]
```
Dispatch interno IntEnum `PanelType {MAIN, JETSON, TELEMETRY}` (patrón actual, sin SERVER). `show_event` resetea a MAIN. Estados del hero y `_telemetry_status`/`_jetson_status` leen `OrbitConnected`, `OrbitLastPublish`, `OrbitOwner`, `SteerTorqueMode`, `JetsonTorqueTimestamp`, config jetson_ip — cache 2 s, nunca por frame. SIN cabecera universitaria, SIN credito, SIN toggles muertos (`telemetria_uem`, `test_overtake_simulador`).

- [ ] **Step 7: `settings.py` SP** — `"UEM"` → `"ORBIT"` en el IntEnum extendido (:56); `from ...settings.orbit_panel import OrbitLayout`; registro: `OP.PanelType.ORBIT: PanelInfo(tr_noop("ORBIT"), OrbitLayout(), icon="img_orbit_logo.png")`; al final de `__init__`: `self._current_panel = OP.PanelType.ORBIT`. En `NavButton._render`, si el icono es el logo ORBIT multicolor el tinte cyan/muted lo pisa: dibujar con `rl.WHITE` cuando `panel_info.icon == "img_orbit_logo.png"` (selección ya la marcan chip+barra). `grep -rn "PanelType.UEM"` para otros usos.

- [ ] **Step 8: `home.py`** — modal `_ServerSettingsModal` importa `orbit_sub_layouts.server_settings.ServerSettingsLayout`; docstring sin "SICUEM".

- [ ] **Step 9: assets** — `git rm sunnypilot/selfdrive/assets/offroad/uem_logo.png uem_logo_completo.png`; quitar bloque `uem_*.png` de `.gitattributes`.

- [ ] **Step 10: verificar** — `py_compile` de todo lo tocado; `grep -rni "uem" selfdrive/ui/ --include="*.py"` = solo hits legítimos (ninguno); screenshots offscreen (Task 7 los repite formalmente): render `SettingsLayoutSP` → panel ORBIT main, TELEMETRY, JETSON.

- [ ] **Step 11: commit** — `feat(ui): panel UEM -> ORBIT con logo; rediseno completo del panel y subpaneles (secciones, ajustes muertos fuera, etiquetas honestas)`

### Task 5: params_keys.h — retirar muertos, añadir gpsLocation_toggle

**Files:** Modify: `common/params_keys.h` (quitar: `telemetria_uem`, `test_overtake_simulador`, `lider_toggle`, `mapbox_toggle`, `navInstruction_toggle`, `intervalos_toggle`, `DisableLongControl`, `adelantamiento_vel_diff`, `adelantamiento_distancia`; añadir junto a los `*_toggle`: `{"gpsLocation_toggle", {PERSISTENT, BOOL}},`)

- [ ] Step 1: ediciones; `grep -rn` de cada key retirada sobre `--include="*.py"` = 0 antes de quitarla.
- [ ] Step 2: `scons -j$(nproc) common/` (rebuild de params en host; anotar que el device necesita lo mismo al desplegar).
- [ ] Step 3: commit — `feat(params): retirar params muertos UEM/INTERVALOS y registrar gpsLocation_toggle`

### Task 6: README + barrido final de referencias

**Files:** Modify: `README.md:62,102,153,181`, `selfdrive/ui/feedback/feedbackd.py:15` (comentario `[SICUEM]`→`[ORBIT]`), cualquier resto del grep.

- [ ] Step 1: ediciones README (mermaid, quick start, árbol de dirs, bullet de design docs; la fila del topic `sicuem_torque` en :129 SE QUEDA).
- [ ] Step 2: `grep -rn "sicuem" --exclude-dir=.git .` → residuo esperado: topic `sicuem_torque` (código+README), specs históricos en docs/superpowers/, menciones `sicuem-mig` en tools/orbit y specs. Nada más.
- [ ] Step 3: commit — `docs: README y comentarios al layout orbit/ definitivo`

### Task 7: Verificación visual + capturas README

- [ ] Step 1: harness offscreen (receta memoria: `BIG=1 SCALE=1 DISPLAY=:1 PYTHONPATH=... .venv/bin/python` + `gui_app.init_window` + render 30 frames + `rl.take_screenshot`): capturar (a) ajustes con rail y panel ORBIT main, (b) subpanel canales, (c) subpanel Jetson.
- [ ] Step 2: revisar visualmente las capturas (composición, textos ASCII, chips del hero, logo en rail).
- [ ] Step 3: refrescar la captura de settings del README (`docs/images/ui-settings*.png`, non-LFS) si cambió su naming; actualizar referencia si procede.
- [ ] Step 4: commit — `docs(img): capturas del panel ORBIT redisenado`

**Deploy (nota, fuera del repo):** en el device tras pull: borrar `__pycache__` residuales y árbol `sicuem/` untracked; recompilar `common` (params). La app orbit-iov: quitar el botón INTERVALOS (tarea del otro repo).
