# ORBIT — sicuem/ desaparece, orbit/ en la raíz + rediseño del menú ORBIT

**Fecha:** 2026-07-10 · **Rama:** `orbit-master` · **Estado:** aprobado por drago

## Objetivo

Tres frentes aprobados:

- **A.** Eliminar el directorio `sicuem/`: la integración viva (`sicuem/orbit/`) pasa a
  **`orbit/` en la raíz del repo**, absorbiendo lo que aún vale del resto de `sicuem/`;
  el código muerto se borra (queda en la historia de git). `tools/sicuem/` → `tools/orbit/`.
- **B.** El panel de ajustes "UEM" pasa a ser **"ORBIT"** con el logo ORBIT en el rail,
  y su interior (panel principal + 3 subpaneles) se reconstruye: secciones reales,
  ajustes muertos fuera, etiquetas honestas, estética ORBIT.
- **C.** Catálogo priorizado de nuevas funcionalidades de conducción/coche (anexo),
  fundamentadas en señales reales del código. La selección de cuáles implementar se
  hace después, junto con drago — **no forman parte de esta implementación**.

Decisiones de drago (2026-07-10):

1. `tools/sicuem/` se renombra a `tools/orbit/`.
2. El toggle/demo **INTERVALOS se elimina del todo**: fila de UI, hilo en
   `longcontrol.py`, comando MQTT `intervalos` y param `intervalos_toggle`.
3. **Cero mención UEM** en el panel: sin créditos, y se borran los assets `uem_*.png`.
4. `sicuem/adelantamiento.py` **se conserva movido a `orbit/`** como módulo dormido,
   claramente marcado como material para el futuro adelantamiento C2.

---

## Parte A — Reorganización de directorios

### A.1 Qué se mueve (git mv, conservando historia)

| Origen | Destino |
|---|---|
| `sicuem/orbit/mqtt_envio_general.py` | `orbit/mqtt_envio_general.py` |
| `sicuem/orbit/mqtt_comandos.py` | `orbit/mqtt_comandos.py` |
| `sicuem/orbit/camera_sender.py` | `orbit/camera_sender.py` |
| `sicuem/orbit/zmq_client.py` | `orbit/zmq_client.py` |
| `sicuem/orbit/events_mqtt.py` | `orbit/events_mqtt.py` |
| `sicuem/orbit/log_mqtt.py` | `orbit/log_mqtt.py` (huérfano pero mantenido — utilidad) |
| `sicuem/orbit/orbit_speed_ultra_simple.py` | `orbit/orbit_speed_ultra_simple.py` |
| `sicuem/orbit/orbit_control_ultra_simple.py` | `orbit/orbit_control_ultra_simple.py` |
| `sicuem/orbit/orbit_steering_pulse.py` | `orbit/orbit_steering_pulse.py` |
| `sicuem/orbit/orbit_obstacle_pulse.py` | `orbit/orbit_obstacle_pulse.py` |
| `sicuem/orbit/config_mqtt.json` | `orbit/config_mqtt.json` |
| `sicuem/orbit/canales.json` | `orbit/canales.json` |
| `sicuem/orbit/config_jetson.json` | `orbit/config_jetson.json` |
| `sicuem/orbit/test/test_obstacle_pulse.py` | `orbit/test/test_obstacle_pulse.py` |
| `sicuem/orbit/test/test_obstacle_pulse_zmq.py` | `orbit/test/test_obstacle_pulse_zmq.py` |
| `sicuem/adelantamiento.py` | `orbit/adelantamiento.py` (dormido; docstring lo marca como material C2 y avisa de que sus params `adelantamiento_*` se retiran — C2 usará los `overtake_*`) |
| `sicuem/orbit/GUIA_JETSON_COMMA.md` | `orbit/docs/GUIA_JETSON_COMMA.md` (rutas internas `/data/openpilot/sicuem/orbit/...` → `/data/openpilot/orbit/...`) |
| `sicuem/docs/STEERING_INTERNALS.md` | `orbit/docs/STEERING_INTERNALS.md` |
| `sicuem/docs/2026-05-07-comma-jetson-mode-design.md` | `docs/superpowers/specs/` |
| `sicuem/docs/2026-05-07-comma-jetson-mode-plan.md` | `docs/superpowers/specs/` |
| `tools/sicuem/` (8 ficheros) | `tools/orbit/` (`grab_sicuem_logs.sh` → `grab_orbit_logs.sh`; autoreferencias de ruta/uso actualizadas; salida `sicuem_log_*`/`sicuem_logs/` → `orbit_log_*`/`orbit_logs/`; menciones históricas de la rama `sicuem-mig` se dejan) |

No hay `__init__.py` en el árbol actual (paquetes-namespace vía symlink) — se
mantiene esa propiedad.

### A.2 Qué se borra (git rm; la historia lo conserva)

- `sicuem/canales.json`, `sicuem/config.json`, `sicuem/lead_info.json` (sin lectores;
  `IpServer` solo lo tocaba el editor muerto de la UI).
- `sicuem/orbit/`: `orbit_speed_{buttons,direct,global,no_params}.py`,
  `diagnostico_mqtt.py`, `diagnostico_mqtt_completo.py`, `simular_sistema_orbit.py`,
  `verificar_variables_globales.py`, `event_codes_map.json` (nunca leído),
  `test_imports.py` y los ~18 `test_*.py` ad-hoc de raíz (lane_change, all_commands,
  comandos_*, setspeed, speed_commands, todos_comandos, velocidad_* ×9),
  `test/telem_general/` completo (demos rotos, uno con IP pública hardcodeada).
- Notas de desarrollo obsoletas: `CAMBIO_CARRIL_MQTT.md`, `FLUJO_CAMBIO_CARRIL.md`,
  `DATOS_TIEMPO_REAL.md`, `EXPANSION_TELEMETRIA.md`, `PRUEBA_SETSPEED_FIJO.md`,
  `SOLUCION_PROBLEMAS.md`.
- `sicuem_log_20260701_133312.txt` (log de debug trackeado en la raíz).
- `__pycache__` sin trackear se limpia en local; en dispositivo ver A.6.

### A.3 Recableado (lista verificada línea a línea)

**Symlink de import (mecanismo de `openpilot.*`):**
`git rm openpilot/sicuem` + nuevo symlink trackeado `openpilot/orbit -> ../orbit`.

**Imports `openpilot.sicuem.orbit.*` → `openpilot.orbit.*`:**

- Externos: `system/manager/manager.py:30` (¡dentro de try/except — verificar que
  importa de verdad tras el cambio!), `selfdrive/controls/controlsd.py:31,102,349`,
  `selfdrive/car/card.py:226`, `selfdrive/selfdrived/selfdrived.py:570`,
  `tools/sim/lib/camerad.py:81`, `tools/orbit/diag_mqtt_orbit.py:50`.
- Internos del paquete: `mqtt_comandos.py:13,391,397,406,412,424,432`,
  `camera_sender.py:95`, `test/test_obstacle_pulse.py:12`,
  `test/test_obstacle_pulse_zmq.py:11`.

**Rutas literales `sicuem/orbit/...` → `orbit/...`:**

- `tools/sim/lib/camerad.py:16` (`JETSON_CONFIG_FILE`).
- `selfdrive/ui/widgets/orbit_server.py:17` (`CONFIG_REL`).
- `jetson_settings.py:77-78` (incluido el fallback `/data/openpilot/sicuem/orbit/...`).
- `server_ip_settings.py:85` (la :86 del config SICUEM muere con el ajuste muerto).
- `tools/orbit/diag_mqtt_orbit.py:60,62` (incluido literal `/data/openpilot`).

**`.gitignore`:** eliminar `!sicuem/config.json` (el fichero muere) y
`sicuem/mqttDebug.txt` (ya nadie lo escribe); `sicuem/**/__pycache__/` →
`orbit/**/__pycache__/`; comentario de sección `# SICUEM / AdriPilot` → `# ORBIT`.

**Docs/comentarios:** README (`:62,102,153,181`), docstrings en
`orbit_command_overlay.py:11`, `orbit_server.py:4`, `camerad.py:67,103,127`,
`mock_jetson_torque.py:9`, `home.py:91`, `feedbackd.py:15`, y los que migren con la
UI nueva (Parte B).

**Intocables (contrato de cable / historia):**

- El topic MQTT **`sicuem_torque/<dongle>`** (`mqtt_envio_general.py:460,545` y la
  fila de README:129) NO se renombra: el backend/app de orbit-iov lo consume.
- Los specs históricos de `docs/superpowers/specs/` y las menciones a la rama
  `sicuem-mig` se dejan como están.

### A.4 Eliminación de INTERVALOS (decisión 2)

- `selfdrive/controls/lib/longcontrol.py:63-92`: quitar el hilo que alterna
  `DisableLongControl` cada 10 s y el clip de -1 m/s² asociado — volver al
  comportamiento upstream limpio.
- `orbit/mqtt_comandos.py`: quitar la suscripción al topic
  `telemetry_config/<dongle>/intervalos`, su rama de dispatch y el handler
  (`:553-568` pre-move).
- Param `intervalos_toggle` fuera de `common/params_keys.h`.
- Nota de contrato: la app orbit-iov puede seguir publicando `intervalos`; sin
  suscripción el broker no lo entrega — inofensivo. Limpiar el botón en orbit-iov
  queda anotado como tarea del otro repo.

### A.5 Params retirados / añadidos (`common/params_keys.h`)

- **Fuera:** `telemetria_uem` (no gobierna nada), `test_overtake_simulador` (0
  lectores), `lider_toggle`, `mapbox_toggle` (consumidor SicMqttHilo2 retirado),
  `intervalos_toggle` (A.4), `adelantamiento_vel_diff`, `adelantamiento_distancia`
  (solo los leía el módulo dormido), `navInstruction_toggle` si existe (canal
  retirado de canales.json).
- **Dentro:** `gpsLocation_toggle` (el canal existe y hoy no puede apagarse porque la
  key no está registrada; `_canal_habilitado` cae al default "on").
- `c_carril` se queda (lector vivo: `selfdrived.py:332`). `show_blindspot`,
  `modo_debug`, `silenciar_alertas_comm` se quedan.
- Tocar params exige **rebuild de scons de `common`** en host y en dispositivo
  (mismo procedimiento que en el enrollment).

### A.6 Despliegue en dispositivo (nota operativa)

En `/data/openpilot` un pull/rsync deja `__pycache__` viejos y el árbol `sicuem/`
puede sobrevivir como ficheros sin trackear (configs des-ignoradas). Tras desplegar:
`find /data/openpilot -name __pycache__ -exec rm -rf {} +` y comprobar que `sicuem/`
ha desaparecido del todo; recompilar `common` (A.5). Los fallbacks
`/data/openpilot/orbit/...` de la UI apuntan ya a la ruta nueva.

---

## Parte B — Menú: UEM → ORBIT + rediseño del panel

### B.1 Rail (`selfdrive/ui/sunnypilot/layouts/settings/settings.py`)

- Enum extendido `:56`: miembro `"UEM"` → `"ORBIT"`.
- Registro `:139`: `PanelInfo(tr_noop("ORBIT"), OrbitLayout(), icon="img_orbit_logo.png")`
  — el logo ORBIT (`selfdrive/assets/img_orbit_logo.png`, 512×512, ya non-LFS) se
  carga escalado a 64 px por `gui_app.texture`. Sin tinte plano que aplaste el logo:
  si el tinte cyan/muted del NavButton degrada el logo multicolor, dibujarlo con
  tinte `rl.WHITE` (caso especial para este panel) y expresar la selección con el
  chip/marcador, no con el tinte del icono.
- **Panel por defecto al abrir ajustes: ORBIT** (hoy la primera tile es UEM pero se
  abre DEVICE). En `SettingsLayoutSP.__init__`, tras construir `_panels`:
  `self._current_panel = OP.PanelType.ORBIT`.
- Buscar cualquier otra referencia `PanelType.UEM` en el repo y actualizarla.

### B.2 Ficheros del panel

- `git mv` `.../settings/uem.py` → `orbit_panel.py` (evita chocar con el módulo
  `orbit/` de la raíz en el naming mental; la clase pasa de `UemLayout` a
  `OrbitLayout`) y `uem_sub_layouts/` → `orbit_sub_layouts/` con:
  - `jetson_settings.py` (rediseñado, B.5),
  - `telemetry_settings.py` (renombrado desde `teluem_settings.py`, B.4),
  - `server_settings.py` (renombrado desde `server_ip_settings.py`, B.3).
- `home.py:96` (modal SERVIDOR de la home) importa el nuevo `server_settings`.
- Assets: se borran `sunnypilot/selfdrive/assets/offroad/uem_logo.png` y
  `uem_logo_completo.png` + su línea en `.gitattributes` (`uem_*.png -filter…`).
- La navegación interna se queda con el patrón IntEnum de la casa (steering.py);
  no se migra a push_widget en esta tanda.

### B.3 Panel principal ORBIT (`orbit_panel.py`)

Estructura, de arriba abajo (Scroller vertical; tarjetas ListItemSP estilo ORBIT ya
baked-in):

1. **Cabecera hero** (widget propio, no ListItemSP): logo ORBIT + wordmark
   "ORBIT" + subtítulo "Estacion de control del vehiculo" + chips de estado en vivo:
   `SERVIDOR` (broker+API ok → verde), `ENLACE` (`OrbitConnected`), `CUENTA`
   (`OrbitOwner` o "SIN VINCULAR"), `JETSON` (modo activo + torque fresco vía
   `JetsonTorqueTimestamp`). Params cacheados a 2 s (patrón de home.py) — nunca
   por frame. Solo ASCII (fuentes bitmap).
2. **Cabeceras de sección reales**: nuevo widget `SectionHeaderSP` (etiqueta
   mayúsculas 36 px en `ORBIT_CYAN` apagado + hairline a la derecha, sin tarjeta,
   no interactivo) — vive en el módulo del panel o en `selfdrive/ui/widgets/`;
   NO se toca `system/ui/sunnypilot/widgets/list_view.py` compartido.
3. **Sección CONEXION**: fila "Servidor ORBIT" (desc = IP:puerto actual, botón
   EDITAR → InputDialogSP), fila "Probar conexion" (PROBAR → probe broker+API con
   resultado en dialog). El subpanel de IPs desaparece: sus 2 filas vivas se
   integran aquí; el editor del "Servidor SICUEM" muerto se elimina.
   `server_settings.py` conserva una clase fina `ServerSettingsLayout` (las mismas
   filas + Back) porque el modal de la home la envuelve a pantalla completa —
   ambas superficies comparten las mismas factorías de filas.
4. **Sección TELEMETRIA**: fila de estado ("Conectado — ultimo dato hace Ns" desde
   `OrbitConnected`/`OrbitLastPublish`) + botón "Canales de telemetria" → subpanel
   B.4. Sin toggle maestro falso (`telemetria_uem` muere); el botón siempre activo.
5. **Sección CONDUCCION**: toggle "MOSTRAR ANGULO MUERTO" (igual), toggle
   `c_carril` reetiquetado honesto: "AVISOS EN CAMBIO DE CARRIL — Añade avisos en
   pantalla si hay vehiculo en el angulo muerto durante un cambio de carril."
   (Aquí aterrizarán las funcionalidades del catálogo que se elijan.)
6. **Sección JETSON**: fila de estado compacta (modo actual + IP + frescura torque)
   + botón "Configurar Jetson" → subpanel B.5.
7. **Sección PRUEBAS**: toggle "MODO DEBUG" (igual) y toggle "SILENCIAR ALERTAS DE
   COMUNICACION" con descripción corta ("Oculta commIssue/locationd temporal.
   Solo pruebas — si aparecen constantemente hay un problema real; ver
   tools/orbit."). PRUEBA ADELANTAMIENTO desaparece (muerto). INTERVALOS
   desaparece (A.4).

Sin tarjeta de créditos, sin escudo, cero mención UEM (decisión 3).

### B.4 Subpanel Canales de telemetría (`telemetry_settings.py`)

- Toggles por canal alineados con `orbit/canales.json` (8): `carState`,
  `carControl`, `gpsLocationExternal`, `radarState`, `drivingModelData`,
  **`controlsState` y `liveCalibration` (nuevas filas — params ya existentes)**,
  **`gpsLocation` (nueva fila + param nuevo A.5)**. Etiquetas limpias sin "UEM"
  (p. ej. "carState — Estado del vehiculo").
- Fuera: LIDER, RESPUESTA MAPBOX (muertos), INTERVALOS (A.4).
- Se queda la fila informativa "Envio de camara a ORBIT" (estado del
  camera_sender), con guard para PC/sim donde `/data` no existe.
- Nota bajo el header: el heartbeat de presencia se publica siempre.

### B.5 Subpanel Jetson (`jetson_settings.py`, rediseño)

- Se conserva TODO el comportamiento (escritura atómica con `_version`, payloads
  MQTT espejo, live-reload por mtime cada 30 frames, diálogos de confirmación
  peligrosos del selector de modo). Solo cambia la presentación:
  - Fuera filas redundantes: "Estado: ACTIVA/INACTIVA" (duplica el toggle),
    "Modo actual" (duplica el selector), fila "IP Jetson" del bloque estado
    (duplica la fila EDITAR).
  - Secciones con `SectionHeaderSP`: **ENLACE** (toggle activar + selector de modo
    de volante), **ESTADO** (torque actual con staleness, obstaculo/esquive solo
    visibles cuando activos), **RED** (IP Jetson, IP Comma, puertos, calidad JPEG
    — filas EDITAR).
  - Rutas de config ya en `orbit/config_jetson.json` (A.3).

### B.6 Idioma y estilo

- Todo el contenido del panel en español ASCII (sin acentos — fuentes bitmap), como
  el resto de la capa ORBIT. Los botones Back/Close heredados quedan como están
  (fuera de alcance).
- Paleta: tokens `ORBIT_*` existentes; nada de colores nuevos hardcodeados.

### B.7 Verificación

1. `python3 -m py_compile` de todos los ficheros tocados + import real
   `openpilot.orbit.*` de los módulos puros; correr
   `orbit/test/test_obstacle_pulse.py` (unittest puro, corre en host).
2. Harness offscreen conocido (`.venv` + `DISPLAY=:1` + render N frames +
   `rl.take_screenshot`): panel ORBIT principal, subpanel canales, subpanel Jetson,
   y el rail con la tile ORBIT seleccionada. Refrescar las capturas del README
   afectadas (`docs/images/ui-*.png`, non-LFS).
3. `grep -rn sicuem --exclude-dir=.git` residual = solo topic `sicuem_torque`,
   specs históricos y menciones de rama.
4. `ruff check` sobre los ficheros tocados.
5. Commits sin atribución de IA (regla dura del repo); push con `--no-verify`.

---

## Parte C — Anexo: catálogo de funcionalidades de conducción (para elegir)

Fundamentadas en señales que ya emite el dispositivo y en la infraestructura ORBIT
existente (bridge de Params, patrón de topics `telemetry_config/<dongle>/<cmd>`,
overlays pyray, canal Jetson ZMQ). Orden = recomendación (valor/esfuerzo/riesgo).

| # | Propuesta | Se apoya en | Dif. | Riesgo control |
|---|---|---|---|---|
| 1 | **Coach de distancia (THW/TTC)** — píldora HUD verde/ámbar/roja + tiempo bajo 1.5 s por viaje | `radarState.leadOne` (dRel/vRel), `carState.vEgo`, patrón torque_hud | Baja | Ninguno |
| 2 | **Aviso predictivo de frenada** — chip "FRENADA PROBABLE" + evento MQTT | `modelV2.meta.hardBrakePredicted` + `disengagePredictions` (hoy sin uso), events_mqtt | Baja | Ninguno |
| 3 | **Monitor desacuerdo Comma vs Jetson** — score de divergencia + badge + geotag | `CommaSteerTorque`/`JetsonTorque` (ya en Params), `gpsLocation` | Baja | Ninguno |
| 4 | **Healthcheck remoto** — comando `diag`: térmicas, voltaje panda, procesos, frescura enlaces → informe + página "Salud" | `deviceState`, `pandaStates`, `managerState`, `procLog`, router de comandos | Baja | Ninguno |
| 5 | **Asesor de curva** — aflora el SCC vision de sunnypilot: "CURVA: reduce a X" | `longitudinalPlanSP.smartCruiseControl.vision` (corre en silencio) | Baja | Ninguno |
| 6 | **Caja negra de incidentes** — ring-buffer 10 s señales+JPEG, volcado ante frenazo/AEB/brutebreak | SubMaster + `jetsonThumbnail` 5 Hz + events_mqtt; lección de escrituras coalescidas | Media | Ninguno |
| 7 | **Informe de viaje** — km, % engaged, desconexiones+motivos, comandos remotos; tarjeta "Ultimo viaje" | `onroadEvents(SP)`, `selfdriveState(SP)` (MADS), odometría carState | Media | Ninguno |
| 8 | **Gate de atención para comandos remotos** — rechaza maniobras remotas con conductor distraído (fail-closed) + medidor HUD | `driverMonitoringState` (sin uso por ORBIT), handlers mqtt_comandos, gate desire_helper | Media | **Positivo** (añade veto) |
| 9 | **Cumplimiento de límites** — vEgo vs límite resuelto; fase 2: cap de flota sobre v_cruise (solo recorte, solo longActive) | `longitudinalPlanSP.speedLimit`, `liveMapDataSP`, `carStateSP.speedLimit`, vía v_cruise de card.py | Media | Fase 2 toca set-speed |
| 10 | **Geofencing on-device** — zonas por config retenida versionada; eventos, privacidad de cámara, cap de campus | `gpsLocation`, patrón `jetson_config` (anti-echo `_version`), `camera_sender.set_enabled` | Media | Solo si arma el cap |
| 11 | **Mapa rugosidad/agarre** — energía IMU + fricción aprendida, por tramos de 100 m geotagged | `accelerometer`/`gyroscope` 104 Hz, `livePose`, `liveTorqueParameters` | Media | Ninguno |
| 12 | **Eco-score + coasting** — suavidad, anticipación, "suelta gas" ante límite/lead lento | `carState` (aEgo/gas), `radarState`, `liveMapDataSP.speedLimitAhead` | Media | Ninguno |
| 13 | **Personalidad longitudinal adaptativa** — relaxed/standard/aggressive según densidad (liveTracks), vía y atención; con histéresis y chip visible | `liveTracks`, `liveMapDataSP`, `driverMonitoringState`, `LongitudinalPersonality` estándar | Media | Dentro de personalidades stock |
| 14 | **Canal de percepción Jetson genérico** — mensajes JSON `detections` (la rama len>4 de zmq_client ya rutea JSON); overlay de cajas + resumen MQTT | `zmq_client.py:259-289`, feed de imágenes existente, patrón jetson_overlays | Alta | Solo display en v1 |
| 15 | **Adelantamiento C2 completo** — secuenciador: retorno al carril + bump de velocidad; escribe `overtakeStatus` (¡el overlay existe sin escritor!) | params `overtake_*` existentes, bridge ForceLaneChange, `modelV2.meta.laneChangeState`, radar, `orbit/adelantamiento.py` dormido | Alta | **FUERTE** — pista cerrada obligatoria; desire_helper no comprueba tráfico en contra |

Recomendación primera tanda: **1+2+3+4** (valor visible inmediato, cero riesgo,
100 % sobre infra existente).

## Fuera de alcance

Spec ORBIT UI v4 (animaciones splash/home/menú — sesión aparte), HUD onroad de
seguridad, migración a push_widget, renombrado del topic `sicuem_torque`
(contrato con orbit-iov), cambios en el repo orbit-iov (limpiar botón INTERVALOS
de la app queda anotado allí), traducciones/.ts.
