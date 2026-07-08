# Migración SICUEM / Orbit → sunnypilot actual — Diseño

**Fecha:** 2026-06-15
**Autor:** Adrián Cañadas (TFG SIC-UEM) con Claude Code
**Origen:** `/home/drago/Escritorio/OPENPILOTSIC/openpilot-img` — rama `sic-jetson`, base `master-sic` (sunnypilot antiguo, commit `be54bf90cf`)
**Destino:** `/home/drago/Escritorio/OPENPILOTSIC/openpilot` — rama `sicuem-mig`, sunnypilot actual (PR #1863)

---

## 1. Objetivo

Portar todo el trabajo del TFG (carpetas `sicuem/` + `sicuem/orbit/` y la integración fuera de esas carpetas) desde un fork de sunnypilot antiguo a un checkout reciente de sunnypilot. No se usa GitHub/cherry-pick: se reimplementa entendiendo el código, porque las dos bases divergen mucho.

**Alcance aprobado:** las 4 áreas (núcleo MQTT, lógica de control, telemetría+cámara, BSM de coche) y **reimplementar los paneles UI esenciales** en el nuevo framework Python/raylib. Enfoque **por capas, de abajo arriba (Opción A)**. `paho` se mantiene **vendorizada**.

## 2. Drift estructural (origen → destino)

El destino es un sunnypilot muy posterior con refactors mayores de upstream:

| Área | Origen (base antigua) | Destino (hoy) |
|---|---|---|
| Resolución de imports | `openpilot/sicuem -> ../sicuem` symlink | falta el symlink `sicuem` |
| Params | claves en `common/params.cc` | `common/params_keys.h`, macro `{"Name", {FLAGS, TYPE[, "default"]}}` |
| `controlsd.py` | monolítico (+823) | solo actuación; lógica en `selfdrive/selfdrived/selfdrived.py`, `selfdrive/car/card.py`, `modeld` |
| Campo de torque lateral | `actuators.steer` | **`actuators.torque`** (rename crítico) |
| v_cruise / set-speed | en `controlsd` | en `selfdrive/car/card.py` (VCruiseHelper) |
| eventos de cambio de carril | `controlsd`/`events.py` | `selfdrive/selfdrived/selfdrived.py` + `selfdrived/events.py` |
| `events.py` | `selfdrive/controls/lib/events.py` | `selfdrive/selfdrived/events.py` |
| DesireHelper (cambio de carril) | corre en `controlsd` | corre en **modeld** (`sunnypilot/modeld_v2/modeld.py` y/o `selfdrive/modeld/modeld.py`); BSM/timer en `sunnypilot/.../auto_lane_change.py` |
| enum de eventos | `car.CarEvent.EventName` | core `log.OnroadEvent.EventName`; **fork → `custom.OnroadEventSP.EventName`** (EventsSP) |
| Coches | `selfdrive/car/hyundai\|toyota` | **opendbc** (`opendbc_repo/opendbc/car/...`); no puede importar `openpilot.*` |
| `cereal/car.capnp` | en cereal | symlink → `opendbc_repo/opendbc/car/car.capnp` |
| Thumbnails de cámara | generados en `camerad` (`camera_common.cc`, `camera_qcom2.cc`) | en **loggerd/encoderd** (`system/loggerd/encoder/jpeg_encoder.cc`, `encoderd.cc`, `loggerd.h`) |
| UI | Qt/C++ (`selfdrive/ui/sunnypilot/qt/...`) | **Python/raylib** (`selfdrive/ui/**`, `selfdrive/ui/sunnypilot/**`) |
| Índices cereal Event | `@130/@131` libres | `@130/@131` **ocupados** (selfdriveState/liveTracks) → usar `@152/@153` |

**Dependencias ya presentes en destino:** `pyzmq`, `pillow`, `requests`. opendbc_repo inicializado. Solo hace falta vendorizar `paho`.

## 3. Componentes y clasificación

### 3.1 Núcleo MQTT / paquete `sicuem` (copia + arreglos)
Hilos arrancados por `manager.py`:
- **`SicMqttHilo2`** (`sicuem/sicmqtthilo2.py`) — telemetría legacy a broker principal, mapbox, cambios de carril.
- **`MQTTEnvioGeneral`** (`sicuem/orbit/mqtt_envio_general.py`) — telemetría Orbit + imágenes + comandos; arranca `MQTTComandos` y `CameraSender`.

Módulos runtime: `mqtt_comandos.py`, `camera_sender.py`, `zmq_client.py`, `events_mqtt.py`, `log_mqtt.py`, `orbit_speed_ultra_simple.py`, `orbit_steering_pulse.py`, `orbit_control_ultra_simple.py`, `orbit_obstacle_pulse.py`, `adelantamiento.py`. Configs: `sicuem/{canales,config}.json`, `orbit/{canales,config_mqtt,config_jetson,event_codes_map}.json`.

**Arreglos al copiar:**
- `sicmqtthilo2.py`: rutas relativas `../../sicuem/*.json` → `os.path.join(os.path.dirname(__file__), ...)`.
- `adelantamiento.py`: `Params('/tmp')` → `Params()`.
- `CameraSender`: depende de servicios cereal `jetsonThumbnail`/`driverThumbnail` (los crea la Fase 2/5).

**NO migrar:** `mqttDebug.txt` (13 MB), `__pycache__`, `lead_info*.json`, `configuracion_uem.json`. Tests/diagnósticos `test_*`, `diagnostico_*`, `simular_*`, `verificar_*`: opcionales (mantener solo `test/test_obstacle_pulse*.py` como pytest útil).

### 3.2 Lógica de control (reimplementación semántica)
- **Selector `SteerTorqueMode` 0/1/2** → `controlsd.state_control` tras `LaC.update`; escribe **`actuators.torque`** (no `.steer`); publica `CommaSteerTorque`/`AppliedSteerTorque`.
- **Modo 3 (COMMA+JETSON, esquive)** → `controlsd` con `ObstaclePulseState`; override de `actuators.torque` (sub-target `torque`) o `desired_curvature`+`steeringAngleDeg`+`actuators.curvature` (sub-target `curvature`); respeta `BSM_BLOCKED_*`; publica `JetsonObstacleStatus`.
- **Brutebreak** → `controlsd` tras `actuators.accel`; clamp a `pid_accel_limits[0]`; auto-clear con `vEgo<0.5`.
- **Pulso de dirección (cruceta)** (opcional) → `controlsd`.
- **Override de velocidad** (`process_speed_commands`) → **`selfdrive/car/card.py`** (donde vive VCruiseHelper), no controlsd.
- **Eventos `laneChangeBlockedLeft/Right` + forzado de carril** → `selfdrive/selfdrived/selfdrived.py` (`update_events`) vía **EventsSP** (`custom.OnroadEventSP.EventName @24/@25`), alertas en `sunnypilot/selfdrive/selfdrived/events.py` (`EVENTS_SP`).
- **Auto-overtake + force-lane-change (DesireHelper)** → **reescritura** como extensión sunnypilot (estilo `auto_lane_change.py`) invocada desde `DesireHelper.update` en **modeld**; hay que **añadir `radarState`** al SubMaster de modeld; la velocidad se aplica en `card.py`.
- **Mirror de alertas MQTT** (`events_mqtt.send_alert`) → `selfdrive/selfdrived/selfdrived.py` tras `create_alerts`.
- **`DisableLongControl`** (opcional) → `selfdrive/controls/lib/longcontrol.py` (firma nueva `__init__(self, CP, CP_SP)` / `update(self, active, CS, a_target, should_stop, accel_limits)`).
- **Debounce `locationdTemporaryError` 2 s** (opcional) → `selfdrived.py`.
- `orbit_control_ultra_simple` escribe `actuators.gas/brake/steer` (inexistentes) → **opcional/skip** o reescribir a `torque/accel`.

> Limitación heredada: los globals de `orbit_steering_pulse`/`_control` se ponen en el proceso `manager` (mqtt_comandos) y se leen en `controlsd` (otro proceso) → solo cruzan vía params. Migrar tal cual y documentar.

### 3.3 Interfaz cereal / params / manager (aditivo)
- **`common/params_keys.h`**: ~60 claves (ver §4.1). Deduplicar `overtakingActive` (elegir `CLEAR_ON_MANAGER_START`). Añadir también las leídas-pero-no-declaradas: `controlsState_toggle`, `liveCalibration_toggle`, `adelantamiento_vel_diff`, `adelantamiento_distancia` y los bools de fallback `orbit_forward/break/tright/tleft/speed_increase/speed_decrease`.
- **`cereal/log.capnp`**: `driverThumbnail @152 :Thumbnail;` y `jetsonThumbnail @153 :Thumbnail;` (struct `Thumbnail` ya existe). NUNCA `@130/@131`.
- **`cereal/services.py`**: `"driverThumbnail": (True, 0.2, 1)` y `"jetsonThumbnail": (False, 5., 1)` tras `"thumbnail"`. `laneChangeCommand` es **huérfano** (sin productor/consumidor/struct) → **skip**.
- **`custom.capnp`**: `laneChangeBlockedLeft @24`/`laneChangeBlockedRight @25` en `OnroadEventSP.EventName`.
- **`system/manager/manager.py`**: 2 imports (`SicMqttHilo2`, `MQTTEnvioGeneral`) + 2 `.start()` tras `ensure_running`, antes del `while True`. **Defaults** ya no van en manager; van como 3er elemento en `params_keys.h`. Arrancar sicuem **después** de migrar el paquete (un ImportError aquí brickea el arranque) → import guardado en try/except durante desarrollo.

### 3.4 Integración de sistema / build / sim
- **Pipeline de thumbnails** → reimplementar multi-rate en `system/loggerd/encoder/jpeg_encoder.cc` (`pushThumbnail` elige `initJetsonThumbnail()/initDriverThumbnail()/initThumbnail()` según el socket — `Event.which()` debe casar), `system/loggerd/encoderd.cc` (cadencias por `frame_id`: thumbnail lento ~0.2 Hz, jetson ~5 Hz, driver) y `system/loggerd/loggerd.h` (`EncoderInfo.thumbnail_name`/campo nuevo para canal rápido). **No tocar** `camera_common.cc`/`camera_qcom2.cc`.
- **`system/athena/registration.py`** → adaptar: no persistir `UNREGISTERED_DONGLE_ID`; reintentar si está atascado; persistir solo dongle válido. Mantener el early-return de timeout pero sin persistir el valor malo.
- **`system/qcomgpsd/nmeaport.py`** (opcional) → comentar prints; `except Exception: sleep(1)` (no `pass`, para no spinear).
- **`tools/sim/mock_jetson_torque.py`** → copia literal (ZMQ PUSH `*:5556`, float32 LE).
- **`tools/sim/lib/camerad.py` + `simulated_sensors.py`** (opcional) → adaptar feature (no el diff): publicar `thumbnail` + ZMQ a Jetson; añadir `rgb=` a `cam_send_yuv_road`.
- **`paho/` + `paho_mqtt-2.1.0.dist-info/`** → copia literal a la raíz (sin `__pycache__`).
- **`openpilot/sicuem`** → `ln -s ../sicuem openpilot/sicuem`.
- **`.gitignore`** → quitar la línea `config.json` (para versionar los configs sicuem); NO añadir `*.md` global (ocultaría docs upstream); ignorar `sicuem/mqttDebug.txt` y `sicuem/**/__pycache__`.
- **SKIP:** `system/webrtc/device/video.py` (reescrito; el path thumbnail ya cubre el caso), `tools/sim/lib/simulated_car.py` (bloque pedal eliminado upstream), `launch_chffrplus.sh` (sin mapd), `.gitattributes` (regla con path equivocado), `pyproject` metadrive `@main` (destino ya en `@minimal`). `paho-mqtt` en pyproject: opcional (se usa vendorizada) → **no** añadir, fuente única.

### 3.5 BSM de coche (verify-only)
Prácticamente **todo SKIP**: el destino (opendbc) ya decodifica BSM del Tucson CAN FD vía `ADAS_CMD_50_50ms.BCW_LtIndSta/BCW_RtIndSta`, `enableBsm = 0x1ba in fingerprint[CAN.ECAN]` por defecto, y ambos fingerprints EUR (`99211-N9240 14Q`, `99110-N9000`) ya están. Las señales del origen (`LEFT_MB`/`MORE_LEFT_PROB`) eran adivinanzas y romperían. El debounce era no-op (`BSM_PERSISTENCE_FRAMES=1`). opendbc no puede importar `openpilot` → `modo_debug` no portable. **Acción:** verificar en coche que `leftBlindspot/rightBlindspot` conmutan; solo si falla en carretera, reimplementar un debounce puro (sin Params).

### 3.6 UI (reimplementación Python/raylib)
Patrón de paneles: `selfdrive/ui/sunnypilot/layouts/settings/steering.py` + `steering_sub_layouts/torque_settings.py` (Widget + `Scroller` + `toggle_item_sp`/`option_item_sp`/`multiple_button_item_sp`/`simple_button_item_sp` + `NavButton` + `InputDialogSP`/`ConfirmDialog`). Registro en `settings.py` (`OP.PanelType` IntEnum + `self._panels`). Overlays onroad: `HudRendererSP` (`selfdrive/ui/sunnypilot/onroad/hud_renderer.py`), `pyray`, throttle de lecturas de params (~0.5 s). Iconos deben ser **PNG** (rasterizar los SVG).

- **ESENCIAL:** `UemLayout` (toggles `telemetria_uem`/`c_carril`/`show_blindspot`/`modo_debug`/`test_overtake_simulador` + botones a subpaneles), `JetsonSettings` (selector `SteerTorqueMode` con diálogos de confirmación, sub-dialog curvature/torque, IPs/puertos/JPEG quality → `config_jetson.json` atómico + `_version` anti-eco + `*MqttPayload`), `ServerIpSettings` (broker en `config_mqtt.json` y `config.IpServer` en `config.json`), overlay **esquive/`JetsonObstacleStatus`**, **`DebugPanel`** (tail de `/tmp/mqtt_debug_messages.txt`).
- **SECUNDARIO/opcional:** torque HUD (CT/AT/JT, `modo_debug`), badge de overtake, reuse de `BlindSpotIndicators`, botón `GirarALaDerecha` (mejor señalizar por param que lanzar subproceso), `TelUemSettings`, developer-UI (Velocidad_C1-4, distancias maniobra).
- **SKIP:** `InfoUem`/`SenderUem` (comentados en el origen), fix C-locale (`float()` es locale-independiente en Python), `SConscript`/`sunnypilot_main.h` (C++).

## 4. Contrato de interfaz

### 4.1 Params (`common/params_keys.h`)
Torque/Jetson: `SteerTorqueMode`(INT,PERSISTENT), `JetsonTorque`/`JetsonTorqueTimestamp`(STRING,CLEAR_ON_MANAGER_START), `JetsonTorqueGain`/`JetsonDeadZone`(STRING,PERSISTENT), `CommaSteerTorque`/`AppliedSteerTorque`(STRING,CLEAR), `SteerTorqueModeMqttPayload`(JSON,CLEAR), `JetsonConfigChanged`(BOOL,CLEAR), `JetsonConfigMqttPayload`(JSON,CLEAR).
Modo 3: `JetsonObstaclePulse`(JSON,CLEAR), `JetsonObstacleTimestamp`/`JetsonObstacleStatus`/`JetsonObstacleStatusMqttPayload`/`JetsonObstacleApplyTargetMqttPayload`(STRING/JSON,CLEAR), `JetsonObstacleMaxAngle`/`JetsonObstacleMaxCurv`(FLOAT,PERSISTENT), `JetsonObstacleApplyTarget`(STRING,PERSISTENT).
Cambio de carril/overtake: `ForceLaneChangeLeft`/`ForceLaneChangeRight`/`c_carril`(BOOL,PERSISTENT), `bsmLaneChangeStatus`/`overtakeStatus`/`overtakingActive`/`OvertakeTargetSpeedKph`/`test_overtake_simulador`(CLEAR), `sic_adelantar`(PERSISTENT|CLEAR), `overtake_distancia_activacion`/`overtake_tiempo_carril_izq`/`overtake_incremento_velocidad`(FLOAT/INT,PERSISTENT), `waitingToReturn`/`returningRight`(PERSISTENT).
Long/freno: `brutebreak_active`(BOOL,CLEAR), `brutebreak_intensidad`(FLOAT,PERSISTENT), `DisableLongControl`(BOOL,PERSISTENT), `intervalos_toggle`(BOOL,PERSISTENT).
Velocidad: `Velocidad_C1..C4`(STRING,PERSISTENT), `vel_adel`(CLEAR), `orbit_speed_increment`(FLOAT,PERSISTENT).
Toggles UI/telemetría: `telemetria_uem`/`modo_debug`(BACKUP)/`show_blindspot`/`carState_toggle`/`carControl_toggle`/`lider_toggle`/`gpsLocationExternal_toggle`/`drivingModelData_toggle`/`radarState_toggle`/`navInstruction_toggle`/`mapbox_toggle`/`controlsState_toggle`/`liveCalibration_toggle`(BOOL,PERSISTENT).
Nav/sender: `roundabout_distance`/`intersection_distance`/`merge_distance`/`turn_distance`/`off_road_distance`/`on_road_distance`/`sender_uem_up/down/left/right`(PERSISTENT).
Extra leídos: `adelantamiento_vel_diff`/`adelantamiento_distancia`(FLOAT), `orbit_forward/break/tright/tleft/speed_increase/speed_decrease`(BOOL,CLEAR), `GirarALaDerecha`(BOOL).

### 4.2 cereal
- `log.capnp` Event: `driverThumbnail @152`, `jetsonThumbnail @153` (`Thumbnail`).
- `services.py`: `driverThumbnail (True,0.2,1)`, `jetsonThumbnail (False,5.,1)`. `laneChangeCommand`: skip.
- `custom.capnp` `OnroadEventSP.EventName`: `laneChangeBlockedLeft @24`, `laneChangeBlockedRight @25`.

### 4.3 ZMQ / archivos
- ZMQ: PUSH `*:5556` (mock/Jetson) ↔ PULL en `zmq_client.py`; imágenes PUB `*:5555`. `config_jetson.json` gobierna IPs/puertos/`jpeg_quality`/`jetson_enabled`/`_version`.
- IPC UI↔comandos: `/tmp/mqtt_debug_messages.txt` (escrito por `mqtt_comandos.py`, leído por `DebugPanel`).
- Configs compartidos (escritura atómica + `_version` anti-eco): `config_jetson.json`, `config_mqtt.json`, `config.json`.

## 5. Plan por fases (Opción A)

Cada fase termina con verificación; build verde antes de seguir.

- **F0 — Empaquetado/prereqs:** copiar `sicuem/` (runtime + configs, sin ruido); copiar `paho/`+dist-info; symlink `openpilot/sicuem`; `.gitignore`; arreglos de rutas (`sicmqtthilo2`, `adelantamiento`). *Verif:* `python -c "import openpilot.sicuem.orbit.zmq_client"`.
- **F1 — Params:** todas las claves en `params_keys.h` (prerequisito bloqueante). *Verif:* compila C++ params; `Params().get(...)` no lanza `UnknownKeyName`.
- **F2 — cereal:** `log.capnp` `@152/@153`; `services.py`; `custom.capnp` `@24/@25`; rebuild cereal. *Verif:* `scons cereal`; codegen genera builders.
- **F3 — manager:** imports + arranque de hilos (guardado). *Verif:* `manager.py` importa; hilos arrancan sin romper boot.
- **F4 — control (verticales):** 4a selector torque → 4b modo-3 → 4c brutebreak → 4d pulso (opc) → 4e velocidad (card.py) → 4f eventos lane-blocked (selfdrived+EventsSP) → 4g overtake/force-lane (modeld, +radarState) → 4h mirror alertas → 4i DisableLong (opc) → 4j debounce (opc). *Verif:* import/lint de controlsd/selfdrived/card/longcontrol; tests de proceso si disponibles.
- **F5 — cámara/sistema:** encoderd/jpeg_encoder/loggerd.h multi-rate; `registration.py`; `nmeaport` (opc). *Verif:* `scons` de loggerd; smoke de `camera_sender` contra canal.
- **F6 — sim/test (opc):** `mock_jetson_torque.py`; sim camerad/sensors.
- **F7 — UI:** esenciales (UemLayout, JetsonSettings, ServerIpSettings, overlay esquive, DebugPanel) → secundarios. Rasterizar assets. *Verif:* arrancar UI en PC (`selfdrive/ui/ui.py`), navegar paneles.
- **F8 — BSM:** verify-only; confirmar Tucson decodifica; sin tocar opendbc salvo necesidad probada en coche.

## 6. Decisiones (defaults elegidos)
1. `laneChangeCommand`: **skip** (huérfano).
2. Eventos lane-blocked: **`OnroadEventSP.EventName` (EventsSP)**, no opendbc/core.
3. Hilos MQTT: **always-on** como el origen, import guardado; `MQTTEnvioGeneral` solo desde `manager` (quitar el `.start()` duplicado de controlsd).
4. `paho`: **solo vendorizada** (no en pyproject).
5. IPs hardcodeadas en configs: **se migran tal cual** (proyecto del autor); editables desde UI `JetsonSettings`/`ServerIpSettings`.
6. DesireHelper: hook en **ambos** modeld (stock + modeld_v2) o el que use el dispositivo; añadir `radarState` al SubMaster correspondiente.
7. `orbit_control_ultra_simple` (gas/brake/steer): **skip** salvo necesidad concreta (campos renombrados).
8. Tests/diagnósticos sicuem: copiar solo `test/test_obstacle_pulse*.py`; resto opcional/omitido.

## 7. Riesgos
- **Seguridad (alto):** selector/modo-3/brutebreak overridean torque/aceleración del EPS. `actuators.steer`→`actuators.torque`: una copia ciega "no hace nada" en silencio. Excepciones en hot-path: solo log, nunca propagar. `TEST MAX` (-1.0) tras confirmación.
- **Presupuesto realtime:** `controlsd` 100 Hz y `modeld` a tasa de cámara; meter Params/json/time en esos bucles puede romper el budget. Cachear config (1 s), `put_nonblocking`, mover MQTT a procesos del manager.
- **Índices cereal:** reusar `@130/@131` corrompería selfdriveState/liveTracks → usar `@152/@153`. Confirmar libres antes de fijar.
- **DesireHelper en modeld:** sin `radarState` en su SubMaster, `d_rel=0` (no-op silencioso); cruces de proceso con `card.py` para la velocidad.
- **Thumbnail driver:** solo publica si `RecordFront` y el hilo del encoder driver corre — verificar o desacoplar.
- **opendbc:** repo separado; cualquier cambio real va ahí (no en openpilot) y sin importar `openpilot.*`.
- **Boot:** ImportError en `manager.py` brickea arranque → migrar paquete antes / guardar import.

## 8. Verificación
- Smoke de imports Python (`openpilot.sicuem.*`, controlsd/selfdrived/card/longcontrol, UI).
- `scons cereal` (+ loggerd en F5) para capnp/C++ afectado.
- Lint (`ruff`/pyflakes) de los módulos tocados.
- UI en PC: arrancar y navegar los paneles nuevos.
- Funcional/coche (fuera de este equipo): BSM Tucson, ciclo MQTT, esquive, overtake — checklist para el dispositivo/sim.

## 9. Preguntas abiertas para validar en coche/dispositivo
- ¿El Tucson EUR puebla `BCW_LtIndSta/RtIndSta` correctamente (sin caída con intermitente)? (test de conducción/replay)
- ¿Qué modeld usa el dispositivo (stock vs `modeld_v2`/tinygrad)? Determina dónde aplicar overtake/force-lane.
- ¿`/tmp/mqtt_debug_messages.txt` sigue siendo el IPC acordado para `DebugPanel`?
- ¿El servidor HTTP de snapshots (`195.235.211.197:2204`) sigue en uso o queda superado por el path thumbnail→MQTT/ZMQ?

## 10. Estado de implementación (2026-06-15)

Ejecutado en rama `sicuem-mig`. **Sin commits** (a petición). Verificación: `py_compile` de todo el Python, `capnp compile` de `log.capnp`/`custom.capnp`/`car.capnp`, y revisión del C++ (no se compiló: el entorno del repo no está construido — falta `uv sync` + `scons`).

**Hecho:**
- F0 paquete `sicuem/`+`orbit/` + `paho` vendorizada + symlink `openpilot/sicuem` + `.gitignore` + arreglo rutas (`sicmqtthilo2`, `adelantamiento`).
- F1 ~75 params en `params_keys.h` (sin colisiones; `overtakingActive` deduplicado).
- F2 cereal: `driverThumbnail @152`/`jetsonThumbnail @153`, servicios, `OnroadEventSP.laneChangeBlocked L/R @24/@25`.
- F3 `manager.py` imports guardados + arranque de hilos.
- F4a/b/c/d selector torque + modo-3 esquive + brutebreak + pulso dirección en `controlsd.py` (`actuators.steer`→`actuators.torque`).
- F4e override velocidad MQTT en `card.py`. F4f eventos `laneChangeBlocked` (EventsSP) + alertas. F4h espejo de alertas MQTT en `selfdrived.py`. F4i `DisableLongControl` en `longcontrol.py`.
- F4g **parcial**: cambio de carril forzado MQTT (`ForceLaneChange L/R`) en `desire_helper.py`.
- F5 cámara→thumbnails en `encoderd`/`jpeg_encoder`/`loggerd.h` (jetson 5 Hz, driver 0.2 Hz) + `registration.py` + `mock_jetson_torque.py` + `nmeaport` + sim camerad/sensors.
- F7 UI: `UemLayout`, `JetsonSettings`, `ServerIpSettings`, overlay esquive, `DebugPanel` (registrados en `settings.py`/`hud_renderer.py`).

**Diferido / pendiente (decisión consciente):**
- F4g auto-overtake completo (lead + ±velocidad + espera/retorno): requiere cablear `radarState` en el SubMaster de `modeld` (riesgo realtime) y validación en coche.
- F4j debounce `locationdTemporaryError` (omitido: timing de evento de seguridad, bajo valor).
- UI secundaria: torque HUD CT/AT/JT, badge overtake, `TelUemSettings`, developer-UI, botón `GirarALaDerecha`, `InfoUem`/`SenderUem`, toggle `jetson_enabled`, cosméticos sidebar/wifi.
- `DebugPanel`: solo-render (sin botones colapsar/limpiar — el layout onroad no enruta ratón a overlays).
- Traducciones `.ts`: sin regenerar (textos nuevos salen en español por defecto).

**Pendiente de verificación en dispositivo / entorno construido:**
- Build (`uv sync` + `scons`): compilar C++ (encoderd/jpeg_encoder) y regenerar cereal/services.h.
- F8 BSM Tucson: verificar en coche que `leftBlindspot/rightBlindspot` conmutan (el sunnypilot nuevo ya lo decodifica; no se tocó opendbc).
- Ciclo MQTT extremo-a-extremo, esquive modo-3, cambio de carril MQTT, streaming de cámara.
