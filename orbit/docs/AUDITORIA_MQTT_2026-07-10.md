# Auditoría post-migración del camino MQTT ORBIT — 2026-07-10

Contexto: tras la migración `sicuem/orbit/` → `orbit/` (raíz), el usuario reportó que
**los eventos sí llegaban a la app pero la telemetría no salía y los comandos
app→comma no se aplicaban**. Auditoría multi-agente (6 auditores en paralelo +
verificación adversarial) sobre firmware y contrato con orbit-iov.

## Por qué esa tríada de síntomas es posible

- **Eventos** (`orbit/events_mqtt.py`): viven en el proceso `selfdrived`, cliente MQTT propio.
- **Telemetría** (`orbit/mqtt_envio_general.py`): hilo dentro del proceso **manager**.
- **Comandos** (`orbit/mqtt_comandos.py`): se construye **dentro del `__init__` de
  `MQTTEnvioGeneral`** (manager.py:176-184 lo arranca con try/except).

Un único fallo en ese `__init__` (o en el import del módulo) mata telemetría **y**
comandos a la vez sin tocar los eventos. Si vuelve a pasar "eventos sí, lo demás no",
mirar primero `cloudlog` del manager: `[Bemposta] fallo iniciando MQTTEnvioGeneral`
o `no se pudieron importar los hilos MQTT SIC-UEM`.

## LA regla de oro descubierta (fuente de la mayoría de bugs)

**Los Params de este árbol están TIPADOS** (`common/params_keys.h`) y validan el tipo
**Python** en `put()`:

- `put("SteerTorqueMode", "1")` → `TypeError` (es INT: hay que pasar `int`).
- `put("overtake_distancia_activacion", "50.0")` → `TypeError` (es FLOAT).
- `get()` de un param tipado devuelve el **tipo nativo o `None`** — nunca str/bytes.
  El default de params_keys.h solo se obtiene con `get(key, return_default=True)`.
- `put()` es **no bloqueante**: `put()+get()` inmediato puede leer el valor viejo
  (`block=True` en get solo espera a que la key *exista*, no al último valor).

Como casi todos los handlers envuelven en `except: pass`, estos TypeError eran
**invisibles**: el comando llegaba por MQTT, el handler corría y el efecto jamás se
materializaba.

## Corregido en esta pasada (commit de esta auditoría)

| Fichero | Bug | Efecto que tenía |
|---|---|---|
| `orbit/mqtt_comandos.py` handle_steer_torque_mode | `put(str)` en `SteerTorqueMode` (INT) + comparación int==str siempre False | **Comando de modo de volante desde la app 100% muerto** (y estado inconsistente con mode=3: ApplyTarget sí se escribía) |
| `orbit/mqtt_comandos.py` handle_speed_increment_config | `put(str)` en `orbit_speed_increment` (FLOAT) | Incremento configurado desde la app nunca se guardaba (fijo en 5) |
| `orbit/mqtt_comandos.py` handle_overtake | 3× `put(str)` en `overtake_*` (FLOAT); el 1º abortaba además los restantes | Config de adelantamiento nunca persistida (enable/disable sí funcionaba: put_bool) |
| `orbit/mqtt_comandos.py` handle_brutebreak | `put(str)` en `brutebreak_intensidad` (FLOAT) | La frenada siempre usaba la intensidad por defecto -3.5, no la de la app |
| `orbit/mqtt_comandos.py` load_config/setup_mqtt | puerto 1883 a fuego (ignoraba `broker_port` del JSON) | Con broker en puerto no estándar: comandos muertos, telemetría viva |
| `orbit/mqtt_comandos.py` handle_control_commands | bloques "compat" que rebindaban un nombre local (`orbit_tright = True`) | Código muerto engañoso, eliminado |
| `orbit/mqtt_envio_general.py` init_submaster | `SubMaster([])` lanza ValueError si los 8 toggles de canal están a False | Tumbaba TODO el subsistema (telemetría+comandos+cámara). Ahora fallback `['carState']` |
| `orbit/mqtt_envio_general.py` loop | sin guard de nivel superior: cualquier excepción de una iteración mataba la telemetría en silencio (comandos seguían vivos) | Ahora `loop()` → try/except + `_loop_once()`; loguea y reintenta |
| `orbit/mqtt_envio_general.py` stop | `comandos_mqtt=None` tras fallo de init → AttributeError que abortaba el apagado | Guard con `getattr(...) is not None` |
| `orbit/mqtt_envio_general.py` obstacle status | el payload de controlsd no lleva dongle_id → el topic GLOBAL era inatribuible (backend registraba "GLOBAL") | Se inyecta `dongle_id` antes de publicar |
| `orbit/events_mqtt.py` _ensure_mqtt_client | `_mqtt_connected = False` en el except sin `global` → variable local muerta | Añadido a la declaración global |
| `orbit/events_mqtt.py` send_event_full | el cooldown se consumía ANTES del check de conexión → evento offline perdido Y suprimidos sus reenvíos 12/30 s (siempre el 1º tras arrancar: connect_async) | Check de conexión antes de consumir cooldown |
| `orbit/events_mqtt.py` | `datetime.utcnow()` deprecado (3.12) | `datetime.now(UTC)` con el MISMO formato de cable (`...Z`) |
| `orbit/orbit_speed_ultra_simple.py` get_speed_increment | devolvía `None` implícito con el param sin escribir → `current_speed + None` TypeError; en card.py los params no se limpiaban y el fallo se reintentaba cada ciclo | Lee con `return_default=True` y siempre devuelve float |
| `selfdrive/ui/.../jetson_settings.py` _commit_mode | `put(str)` en `SteerTorqueMode` (INT), TypeError SIN capturar en el callback del diálogo | El modo tampoco se podía cambiar desde el panel del comma (y el payload MQTT retained nunca se escribía) |
| `selfdrive/controls/controlsd.py` _refresh_obstacle_config | sembraba defaults con `str(default)` en keys FLOAT → TypeError tragado y reintentado cada ~1 s | Siembra con float |
| `orbit/adelantamiento.py` get_param_float | kwarg `encoding` ya no existe en `Params.get` | API moderna (módulo dormido, pero listo si C2 lo revive) |
| `orbit/log_mqtt.py` | comentario de cabecera afirmaba (falso hoy) que se importa desde interfaces.py | Marcado MÓDULO DORMIDO |

Verificación: smoke funcional de los 12 handlers contra Params reales (20/20 PASS),
`_loop_once()` conducido con cliente MQTT fake + SubMaster stub (8/8 PASS: telemetría,
enroll, obstacle+dongle_id, sicuem_torque, heartbeat, resiliencia del loop, guard de
SubMaster vacío), eventos con cliente fake (4/4 PASS), py_compile y ruff (= o mejor que HEAD).

## Encontrado pero NO corregido (decisiones/para el futuro)

**Lado orbit-iov (tocar en ese repo, no aquí):**
- La app aún publica `telemetry_config/<d>/intervalos`; el firmware eliminó INTERVALOS
  a propósito (sin suscriptor es inocuo). Pendiente quitar el botón en la app.
- El **healthcheck** remoto (`telemetry_config/<d>/healthcheck` →
  `telemetry_mqtt/<d>/healthcheck`) no tiene contraparte aún en backend/app: el
  firmware va por delante. Implementar botón/vista de diagnóstico en orbit-iov.
- Nadie publica ya `telemetry_config/<d>/speed` (formato JSON viejo); el firmware sigue
  suscrito por compatibilidad. La app usa `speed_up`/`speed_down`.

**Lado firmware (riesgo bajo, documentado):**
- **paho-mqtt**: vendorizado en `/paho` (2.1.0, parcheado para que `mqtt.Client()` sin
  argumentos caiga a la callback API VERSION1 con solo un DeprecationWarning) y sin pin
  en pyproject. Con un paho 3.x futuro, `mqtt.Client()` sin argumentos ROMPERÁ los 3
  clientes (envio_general, comandos, events). Si se actualiza paho: pasar
  `mqtt.CallbackAPIVersion.VERSION1` explícito o migrar callbacks a VERSION2.
- **DongleID fallback**: si `DongleId` no existe al arrancar el hilo, se suscribe/publica
  con el literal `"DongleID"` para siempre (no se re-resuelve). En device real no pasa
  (registration corre antes); en PC/sim puede confundir.
- `max_queued_messages_set(0)` significa cola ILIMITADA en paho (el comentario dice lo
  contrario). Hoy es inerte: todos los publish son qos=0 y paho los descarta sin conexión.
- `orbit/log_mqtt.py` y `orbit/adelantamiento.py` son módulos dormidos (0 importadores).

## Recordatorio de deploy en el comma

Tras desplegar estos cambios en el device: **rebuild scons de `common`** si cambian
keys de params (aquí NO cambiaron), y **borrar `__pycache__`** de `orbit/` y cualquier
resto untracked de `sicuem/` (los .pyc viejos con paths `sicuem.*` han causado fallos
de import fantasma).
