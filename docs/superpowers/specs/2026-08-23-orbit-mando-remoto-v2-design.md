# ORBIT — Mando remoto v2: contrato, modos y app como centro de control

**Fecha:** 2026-08-23
**Repos:** `ORBITPILOT` (firmware, rama `orbit-master`) y `orbit-iov` (app + backend, rama `orbit-master`)
**Estado:** diseño para revisión
**Base:** auditoría multi-agente en `orbit/docs/AUDITORIA_ORBIT_2026-08-23.md`

---

## 0. Qué se decidió antes de escribir esto

| # | Decisión | Elegido | Consecuencia de diseño |
|---|---|---|---|
| D1 | Transporte MQTT | **Se queda como está por ahora** (IP pública, 1883, anónimo, sin TLS) | El firmware pasa a ser la **única barrera**. Todo el diseño asume un canal hostil: el dispositivo no confía en nada de lo que le llega. |
| D2 | Camino de las órdenes | **Todo por el backend REST autenticado** | La app pierde el `publish` de mando. Autorización, rate limit y auditoría entran en el camino real de datos. |
| D3 | Panda | **Firmado, safety intacta** | Intermitentes **solo Ford**. En el resto, NACK `UNSUPPORTED_PLATFORM`. Nada de UDS ni de control fino fuera de banco. |
| D4 | Arranque | **Quick wins ya + diseño en paralelo** | La Fase 0 ya está aplicándose; este documento cubre F1–F5. |

Decisión que tomo yo por defecto salvo que digas lo contrario: **el «frenado de emergencia» se convierte en «deceleración asistida»** con rango acotado a `[-2.5, -1.0]` en vía pública, rampa de jerk, `hold` máximo de 1500 ms y cancelación por el conductor. El rango completo `[-10, -1]` queda **solo en modo banco**. Motivo: una frenada que llega con segundos de latencia, ordenada por alguien que no ve lo que ve el coche, no evita un peligro — lo crea. El botón grande de pánico de la app pasa a ser **`cancel` de crucero**, que reduce autoridad en vez de aumentarla y está implementado en las 12 marcas.

---

## 1. Riesgo aceptado, y qué lo compensa

El broker seguirá abierto. Eso significa que **cualquiera que conozca un `dongle_id` puede publicar en los topics de mando**. La Fase 0 ya cierra la cadena de ataque más grave (topics `/global`, payload vacío, `retain`, `bool('false')`), pero el canal sigue siendo público. Controles compensatorios que este diseño da por obligatorios mientras D1 no cambie:

1. **El dispositivo valida todo lo que ejecuta**, no el emisor. Tipos, rangos, modo, precondiciones, frescura y unicidad — en el coche, siempre, aunque el backend ya lo haya validado.
2. **Ningún verbo peligroso es alcanzable sin armado local.** El modo banco solo se arma desde la pantalla física del comma.
3. **Todo caduca.** Sin `ttl_ms` vigente y sin heartbeat, el actuador vuelve a neutro solo.
4. **Todo deja rastro.** `command_log` en el backend se trata como registro de evidencia (append-only, UTC, actor, no borrable desde la app).
5. La plomería de TLS y credencial por dongle **se escribe igual** (Fase 1), se deja desactivada por configuración, y se puede encender el día que quieras sin tocar código.

Esto no convierte el canal en seguro. Reduce el daño de que no lo sea.

---

## 2. Principios

- **La autoridad solo baja.** Ningún comando remoto puede aumentar la autoridad de openpilot sobre el coche por encima de lo que ya tiene con el conductor delante. `disarm_all` es el único verbo que no requiere modo, gate ni deadman: bajar autoridad siempre se acepta.
- **El coche es la última palabra.** La app propone, el backend autoriza, el dispositivo decide. Cada consumidor reevalúa su propio gate en el ciclo en que actúa.
- **Nada silencioso.** Cada orden termina en un ACK con fase y motivo. Un bloqueo siempre dice por qué. Un verbo no soportado dice que no lo soporta, no falla mudo.
- **Un solo contrato.** Un namespace, un sobre, un formato de instante. Hoy el campo temporal viaja como `int`, como `string` y como ISO-8601 *en el mismo topic*: eso es la enfermedad, no un detalle.
- **El hot path es sagrado.** Nada de I/O de disco en `controlsd` (100 Hz) ni de trabajo pesado dentro del callback de paho (hilo de red: un handler lento tira el `PINGRESP` y con él la conexión).

---

## 3. Contrato v2

### 3.1 Namespace

Se congela `orbit/v2/`. Los tres namespaces vivos hoy (`telemetry_mqtt/`, `telemetry_config/`, `*/global`) se declaran **legacy** y mueren al final de la migración.

| Topic | Dirección | QoS | Retain |
|---|---|---|---|
| `orbit/v2/cmd/<dongle>` | backend → coche | 1 | **prohibido** (se rechaza en el coche) |
| `orbit/v2/ack/<dongle>` | coche → backend, app | 1 | no |
| `orbit/v2/tel/<dongle>/<canal>` | coche → backend, app | 0 | no |
| `orbit/v2/presence/<dongle>` | coche (LWT) | 0 | **sí** |
| `orbit/v2/caps/<dongle>` | coche | 1 | **sí** |
| `orbit/v2/cfg/desired/<dongle>` | backend | 1 | **sí** |
| `orbit/v2/cfg/reported/<dongle>` | coche | 1 | **sí** |

No existe ningún topic sin `<dongle>` en la ruta. Nunca más.

### 3.2 El sobre

```json
{
  "v": 2,
  "id": "0f8c…",           // uuid4, idempotencia
  "seq": 412,               // monótono por dongle, detecta desorden
  "verb": "lane_change",
  "args": {"direction": "left"},
  "ts_ms": 1755960000000,   // epoch ms ENTERO, siempre, en todo el sistema
  "mono_ms": 918273,        // reloj monótono del emisor
  "ttl_ms": 3000,
  "mode": "maniobra",       // modo exigido; si el coche no está en él, NACK
  "actor": {"user_id": 7, "via": "app"},
  "sig": null               // reservado para D1 = TLS + credencial por dongle
}
```

**El reloj es un problema real**, no teórico: un comma sin fix GPS ni NTP arranca con la hora equivocada. Reglas:

- `ts_ms` es **siempre** epoch en milisegundos, entero. No hay ISO-8601 en el cable.
- Los plazos internos (TTL, deadman, hold) se miden con **reloj monótono**, nunca con epoch.
- Si el reloj del dispositivo no está sincronizado, **se rechaza todo mando** con `reason: CLOCK`. Es preferible un coche que no obedece a un coche que obedece una orden de hace diez minutos.
- Deriva > 5 s entre móvil, backend y coche → se avisa en la app.

### 3.2.1 Argumentos por verbo — tabla NORMATIVA

Esta tabla, y no el ejemplo de arriba, es la referencia. **Los nombres son los que exige el coche, letra por letra**, y son los mismos en firmware, backend y app.

Hasta aquí el ejemplo suelto del sobre decía `dir` y de ahí salió una divergencia que **rompía el 100 % de los envíos** de tres verbos: el coche rechaza con `TYPE` («argumentos desconocidos») todo lo que no esté en su esquema, en vez de ignorarlo. Y como los shims legacy publican v1 y v2 a la vez (§13), el v2 se rechazaba y el v1 se ejecutaba igual por el puente: **la app pintaba «Rechazada» mientras el coche cambiaba de carril**.

Por eso el nombre lleva la unidad (`delta_kph`) o la magnitud física (`torque`). Un `value` no dice qué es; un `delta` no dice en qué unidad; `dir` no dice si es un rumbo, un directorio o un sentido.

| Verbo | Argumento | Tipo | Rango / opciones | Oblig. | Defecto |
|---|---|---|---|---|---|
| `disarm_all` | — | | | | |
| `set_mode` | `target_mode` | enum | `observador` \| `copiloto` \| `maniobra` | sí | |
| `healthcheck` | — | | | | |
| `location_now` | — | | | | |
| `cruise_delta` | `delta_kph` | float | −5.0 … 5.0 (km/h) | sí | |
| `cruise_button` | `button` | enum | `cancel` \| `resume` \| `set` | sí | |
| `follow_distance` | `personality` | int | 0 … 2 | sí | |
| `mads`, `experimental`, `dec`, `nnlc`, `openpilot_enable` | `enabled` | bool | `true` \| `false` | sí | |
| `device_admin` | `action` | enum | `reboot` \| `poweroff` \| `restart_services` | sí | |
| `lane_change` | `direction` | enum | `left` \| `right` | sí | |
| `assisted_decel` | `accel` | float | −2.5 … −1.0 (m/s²) | sí | |
| `blinker` *(no implementado)* | `direction` | enum | `left` \| `right` \| `off` | sí | |
| `overtake` *(no implementado)* | `enabled` | bool | `true` \| `false` | sí | |
| `torque_mode` | `mode` | int | 1 … 3 | sí | |
| | `apply_target` | enum | `curvature` \| `torque` (obligatorio con `mode=3`) | no | |
| `steering_pulse` | `torque` | float | −1.0 … 1.0 | sí | |
| | `duration_ms` | int | 0 … 500 | no | 200 |
| `physical_control` | `axis` | enum | `steer` \| `accel` | sí | |
| | `value` | float | −1.0 … 1.0 | sí | |

Reglas de la tabla:

- **`bool` es `bool` de JSON.** Ni `"false"`, ni `0`, ni `1`. La coerción de cadena a booleano es el bug que dispara un cambio de carril con el payload `'false'`.
- **Un `int` vale donde se espera `float`** (JSON manda `2`, no `2.0`); un `bool` no vale como número.
- **Un argumento que no esté en la tabla se rechaza**, no se ignora: si el emisor cree que manda `dir` y el coche espera `direction`, ignorarlo ejecutaría la maniobra con el valor por defecto en vez de decir que el sobre está mal.
- **`banco` no es un valor de `set_mode`.** Subir a banco es subir a la autoridad física y solo se hace con armado en la pantalla del comma (§4.1).
- El backend acepta **temporalmente** los nombres viejos (`dir`, `delta`, `value`) y los traduce al canónico antes de construir el sobre (`LEGACY_ARG_ALIASES`). La traducción vive en el borde; el coche sigue siendo estricto. Se retiran cuando los shims de `main.py` publiquen los nombres canónicos y la versión de la app que manda los viejos deje de estar desplegada.

Lo comprueban dos pruebas cruzadas, una a cada lado, que comparan verbo a verbo nombres, tipos, rangos, modo y TTL: `orbit/test/test_contrato_cruzado.py` (lee el catálogo del backend con `ast`) y `backend/tests/test_commands_v2.py` §10 (importa `orbit/command_spec.py`, que es un módulo puro). Si divergen, fallan ruidosamente. **Sin esa pareja de pruebas esto se vuelve a romper en la siguiente tanda**, porque cada repo puede estar en verde por su cuenta mientras el sistema entero está roto.

### 3.3 ACK: cinco fases

```
received ──> accepted ──> executing ──> applied
     │            │                        │
     └─> rejected └─> expired              └─> failed | superseded
```

`orbit/v2/ack/<dongle>`:

```json
{"v":2,"id":"0f8c…","phase":"rejected","reason":"GATE_NOT_ENGAGED",
 "detail":"openpilot no está enganchado","ts_ms":…, "mono_ms":…}
```

Códigos: `OK`, `TYPE`, `RANGE`, `MODE`, `GATE_<nombre>`, `DUPLICATE`, `EXPIRED`, `CLOCK`, `UNSUPPORTED_PLATFORM`, `UNSUPPORTED_VERB`, `BUSY`, `SUPERSEDED`, `LINK`, `INTERNAL`.

**Ningún control de la app muestra éxito antes de `applied`.** El estado intermedio se dice con palabras: «enviado, sin confirmación».

### 3.4 Semántica de entrega

QoS 1 es *at-least-once*: **el broker reentrega**. Un `lane_change` duplicado son dos cambios de carril. Por tanto:

- **Idempotencia obligatoria por `id`** en cada handler, con LRU de 512 ids.
- **Ventana de secuencia:** un `seq` menor que el último aplicado para el mismo verbo se descarta con `SUPERSEDED`.
- **Fuera de orden:** un `disarm` con `seq` menor que el `arm` que lo precedió **se ejecuta igual** (bajar autoridad nunca se descarta) — es la única excepción a la regla anterior y va escrita como tal en el código.
- **`retain` se rechaza incondicionalmente** en el namespace de mando.

### 3.5 Capacidades

`orbit/v2/caps/<dongle>` (retenido) publica qué sabe hacer **este** coche:

```json
{"v":2,"schema_version":2,"ts_ms":1755960000000,
 "brand":"ford","platform":"FORD_FOCUS_MK4","fw":"…",
 "verbs":{"cruise_delta":{"mode":"copilot","ttl_ms":2000,
                          "gates":["ENGAGED","LONG_ACTIVE"],
                          "args":{"delta_kph":{"type":"float","required":true,
                                               "min":-5,"max":5,"unit":"kph"}},
                          "limits":{"rate":{"campo":"delta_kph","presupuesto":20.0,"ventana_s":60.0}}},
          "lane_change":{"mode":"maneuver","ttl_ms":3000,
                         "args":{"direction":{"type":"str","required":true,
                                              "choices":["left","right"]}},
                         "limits":{"v_min_kph":40,"v_max_kph":130,"encadenable":false}}},
 "unsupported":{"blinker":"policy","blinker_standalone":"policy",
                "overtake":"not_implemented","dtc_read":"panda_signed"}}
```

**Los límites viven DENTRO de `args`, por argumento.** No hay un `{min,max}` suelto colgando del verbo: cuando el verbo tiene más de un argumento numérico no se puede atribuir sin adivinar, y adivinar tuvo consecuencias reales — el backend estrechaba con él todos los numéricos del verbo y dejaba a alguno con un rango vacío, es decir, un control que no puede aceptar ningún valor. Esta es además la forma que el firmware **emite** (`CommandSpec.a_dict`): mientras el consumidor buscó otra, el estrechado por capacidades fue un **no-op** — un mecanismo de seguridad que nunca se aplicaba y con el que el resto del sistema contaba.

El coche solo puede **estrechar**, nunca ampliar: si `caps` declara ±50 km/h, sigue mandando el ±5 de la tabla normativa.

La app **solo pinta lo que el coche declara**. Es lo que evita el botón que no hace nada, que es el defecto más repetido del sistema actual.

---

## 4. Modos y precondiciones

### 4.1 Los cuatro modos

| Modo | Qué permite | Cómo se entra |
|---|---|---|
| **observador** | solo lectura | por defecto, siempre |
| **copiloto** | ajustes y verbos que no mueven el coche: crucero ±, distancia de seguimiento, MADS, experimental, ubicación, admin del dispositivo | desde la app, con el coche enlazado |
| **maniobra** | cambio de carril, adelantamiento, deceleración asistida, intermitente acoplado | desde la app **y** con todos los gates en verde |
| **banco** | control físico directo (torque, accel), modos de torque 1/2, pulso de dirección | **solo desde la pantalla física del comma**, TTL 300 s, desarme automático por velocidad |

El cambio de modo tiene su propio verbo, **`set_mode`** (§6), y tres reglas:

- **Alcanzable desde observador.** Si exigiera el modo de destino no se podría subir nunca; la autoridad la da el modo **concedido**, no el exigido.
- **`banco` no está entre sus valores.** Subir a banco es subir a la autoridad física de `torque_mode`, `steering_pulse` y `physical_control`: solo con armado en la pantalla del comma. Pedirlo por MQTT es `RANGE`, y ese rechazo está en el esquema, no en el handler.
- **Caduca solo.** TTL del sobre corto (5 s: una orden de «ponte en maniobra» que llega 30 s tarde describe una situación que ya no existe) y **caducidad del modo concedido** — copiloto 900 s, maniobra 120 s. Sin caducidad, «maniobra» se queda encendido para siempre y el gate de modo deja de significar nada. El argumento se llama `target_mode` y no `mode` porque el sobre ya lleva un campo `mode` con otro significado.

Subir de modo exige además **gesto explícito del usuario** en la app (§10.2: nada crítico a un solo toque). Eso se hace cumplir donde hay sesión y donde hay dedo — backend y app —; el catálogo del coche lo **declara** para que el centro de ayuda diga lo mismo que hace la interfaz.

`OrbitCommandMode` se registra como `CLEAR_ON_MANAGER_START | CLEAR_ON_OFFROAD_TRANSITION`. **Jamás `PERSISTENT`**: el precedente de `SteerTorqueMode` persistente es exactamente por qué `manager.py:92-99` tuvo que añadir un fail-safe de arranque.

### 4.2 El evaluador de gates

`orbit/command_gates.py` — `GateMonitor` con `SubMaster(['carState','selfdriveState','carControl','carParams','deviceState'])` a 10 Hz **en el proceso manager**, inyectado por referencia (el patrón ya existe en `_link_camera_to_comandos`). **Cero lecturas de Params en el camino de decisión.**

Gates disponibles:

| Gate | Fuente | Por qué |
|---|---|---|
| `ENGAGED` | `selfdriveState.enabled` | sin openpilot enganchado no hay a quién dar la orden |
| `LAT_ACTIVE` / `LONG_ACTIVE` | `carControl` | el eje concreto tiene que estar bajo control |
| `SPEED_RANGE` | `carState.vEgo` | por verbo |
| `DRIVER_IDLE` | `gasPressed`, `brakePressed`, `steeringPressed` | el conductor manda; cualquier intervención cancela |
| `DRIVER_PRESENT` | `seatbeltUnlatched`, `doorOpen`, `driverMonitoringState.faceDetected` | **hoy no se usa en ninguna precondición.** Ordenar un cambio de carril con el asiento vacío y hacerlo con el conductor atento son dos productos distintos |
| `CALIBRATED` | `liveCalibration` | |
| `NOT_DEGRADED` | `dashcamOnly`, `passive` | en esos estados la mitad de los verbos no puede aplicarse, y hoy la app no lo distinguiría de «el coche no responde» |
| `LINK_FRESH` | edad del último ACK/heartbeat | |
| `CLOCK_SYNCED` | tiempo del sistema | |

Cada consumidor (`controlsd`, `desire_helper`, `card`) **reevalúa su gate en el ciclo en que actúa**. El GateMonitor filtra pronto; el consumidor decide tarde. Defensa en profundidad, nunca un solo punto.

---

## 5. Deadman: dos relojes distintos

Son dos cosas y se confunden siempre:

- **Watchdog de actuador** (obligatorio, centenas de ms): dentro de `controlsd`, alimentado por el instante monótono del último comando válido. Si expira, neutro. Es lo que impide que un override lateral se quede pegado — el bug que hoy existe en el modo 3.

  **La ventana es UNA SOLA y hoy es global.** `CommandStateStore` tiene un único `deadline_mono` y `begin_command` lo sobreescribe con el TTL del verbo entrante, así que la ventana que abre un verbo la hereda cualquier consumidor que solo mire `deadlineMono`: tras un `torque_mode` había minutos de ventana para todo lo demás, y al revés, un verbo corto recortaba la de uno largo. Mitigación aplicada en el router mientras el campo siga siendo uno: **la ventana de un verbo nunca puede ser más larga que la que ya estuviera abierta para otro verbo**; renovar el **mismo** verbo sí la refresca. Recortar la ventana ajena baja autoridad, y bajar autoridad siempre se acepta (§2); lo que no puede pasar es lo contrario. **El arreglo definitivo es un `deadline` por verbo** en `OrbitCommandState` (`cereal/custom.capnp` + `orbit/command_state.py`), y hasta entonces el techo lo pone el TTL más largo del catálogo.
- **Watchdog de enlace** (opcional, segundos): alimentado por el heartbeat de la app. Si expira, se sale de modo maniobra y se avisa.

**El plano de estado NO va en Params.** `Params.put` en este árbol es `mkstemp`+`fsync`, ya provocó `commIssue` y por eso existe `_defer_param_put` en `controlsd`. Va en un mensaje cereal nuevo:

- `struct OrbitCommandState` en `cereal/custom.capnp` (donde sunnypilot ya mete sus structs SP) + servicio en `cereal/services.py`. Existen además los huecos `customReservedRawData0..N` como salida de emergencia si no se quiere tocar el esquema.
- Campos: `mode`, `activeVerb`, `cmdId`, `deadlineMono`, `gatesMask`, `lastAckPhase`.
- Requiere recompilar `cereal` en el dispositivo, igual que ya pasa al añadir claves de Params.

---

## 6. Catálogo de verbos

Leyenda de modo mínimo: **O**bservador · **C**opiloto · **M**aniobra · **B**anco

| Verbo | Modo | Gates | TTL | Límites | Estado |
|---|---|---|---|---|---|
| `disarm_all` | O | ninguno | — | — | **nuevo**, siempre aceptado |
| `set_mode` | O | ninguno | 5 s | `observador` \| `copiloto` \| `maniobra`; caduca solo (copiloto 900 s, maniobra 120 s) | **nuevo**, ver §4.1 |
| `location_now` | C | — | 10 s | — | nuevo (GPS continuo apagado por defecto) |
| `healthcheck` | C | — | 30 s | — | existe en firmware, **sin publicador** |
| `cruise_delta` | C | ENGAGED, LONG_ACTIVE | 2 s | ±5 km/h por orden, ±20 km/h por minuto | unifica los **cuatro** caminos actuales |
| `cruise_button` | C | ENGAGED | 2 s | `cancel` \| `resume` \| `set` | nuevo; `cancel` es el botón de pánico |
| `follow_distance` | C | ENGAGED | 5 s | personality 0-2 | nuevo |
| `mads` / `experimental` / `dec` / `nnlc` | C | — | 10 s | bool | nuevo (hoy solo en la pantalla del comma) |
| `openpilot_enable` | C | standstill | 10 s | bool | nuevo, kill switch del dueño |
| `device_admin` | C | offroad para `reboot` | 30 s | reboot \| poweroff \| restart_services | nuevo |
| `lane_change` | **M** | ENGAGED, LAT_ACTIVE, DRIVER_IDLE, DRIVER_PRESENT, SPEED 40-130, LINK_FRESH | 3 s | una maniobra, sin encadenar | **arreglo**: hoy `bool('false')` lo dispara |
| `assisted_decel` | **M** | ENGAGED, LONG_ACTIVE, DRIVER_IDLE | 1.5 s | `[-2.5,-1.0]`, rampa de jerk, hold fijo de 1500 ms en `controlsd` | **arreglo** de `brutebreak` |
| `blinker` | **M** | acoplado a `lane_change`; Ford | 3 s | continuo mientras dure | **nuevo**, ver §11 |
| `overtake` | **M** | los de `lane_change` + BSM | — | — | **o se implementa la máquina de estados o se retira el HUD que miente** |
| `torque_mode` 1/2/3 | **B** | armado local | **15 s** | clamp `[-1,1]`, dead-zone; `mode=3` exige `apply_target` | **arreglo** |
| `steering_pulse` | **B** | armado local, `vEgo` bajo | 500 ms | antes del limitador, no realimentado | **arreglo** |
| `physical_control` | **B** | armado local, `vEgo`<5 km/h, park/neutral, red local | 200 ms | reutiliza `joystickd` | nuevo, **nunca sobre LTE ni en la app de usuario** |

**El `hold` de `assisted_decel` no es un argumento.** Lo declaraban el firmware y el backend, y el ejecutor no lo leía: el hold real es la constante fija `ORBIT_DECEL_HOLD_MAX_S = 1.5 s` de `controlsd`. Un argumento del contrato que nadie lee es una promesa falsa — la app enseñaría un control de duración que no cambia nada. Se retira del contrato. Quien quiera una frenada **más corta** acorta el `ttl_ms` del sobre, que sí se respeta de punta a punta: el router lo convierte en `deadline_mono`, el plano lo publica como `deadlineMono` y `controlsd` exige esa ventana abierta en cada ciclo de 100 Hz. Alargarla no se puede, y es lo correcto: el techo lo pone el coche.

**Los 300 s de `torque_mode` eran del armado, no del actuador.** Los 300 s de §4.1 son la caducidad del **armado físico** de banco (`OrbitBenchExpiry`), que dice cuánto se admite operar el banco después de tocar la pantalla del comma. El TTL del verbo es otra cosa: es la **ventana del actuador**, el deadman de §5, que esa misma sección describe como «centenas de ms». Con **un solo** `deadlineMono` en el plano de estado, una ventana de cinco minutos la hereda cualquier consumidor que solo mire ese campo. Baja a **15 s**, renovables reenviando la orden.

**Se retiran:** `forward`, `break`, `tright`, `tleft` (la cruceta), `/speed`, `/intervalos`, y los params zombis asociados. Cada uno es superficie de mando sin cliente o con semántica peligrosa.

---

## 7. Telemetría v1

Hoy se publica el `to_dict()` **completo** de 8 mensajes cereal a 1 Hz porque `keys_importantes` está vacío en los 8 canales: el mecanismo de filtrado existe y **nunca se usa**. Eso es del orden de decenas de KB/s sobre LTE.

**Antes de rediseñar hay que medir.** Primer entregable de F3: consumo real por dispositivo y hora, medido, no estimado.

| Canal | Cadencia | Contenido |
|---|---|---|
| `vehicle` | 2 Hz | velocidad, marcha, volante, pedales, **intermitentes**, puertas, cinturón, standstill |
| `openpilot` | on-change + keepalive | engaged, MADS, alerta activa, calibración, modelo |
| `health` | 0.1 Hz | temperaturas, CPU, memoria, disco, red, panda, procesos caídos |
| `event` | on-change | eventos **tipados** desde `onroadEvents` (~120 códigos) — con el enum mapeado **en el descriptor**, no por el orden del enum de cereal, que cambia entre rebases |
| `perception` | 2 Hz | lead, TTC, carriles, BSM, plan longitudinal |
| `road` | on-change | límite de velocidad, próximo límite, nombre de la vía |
| `trip` | start/end | `trip_id` en el sobre, resumen al cerrar |
| `pos` | adaptativa | traza GPS con decimación por curvatura y calidad de fix |

Reglas transversales: lista blanca **por campo**, redondeo explícito, saneado `isfinite`→`null`, `dongle_id` fuera del payload (va en el topic). Perfiles **AHORRO / NORMAL / DIAGNÓSTICO** con degradación automática por `networkMetered` y apagado del perfil diagnóstico en el propio dispositivo a los 15 minutos.

**Cola persistente** en `/data/orbit_spool` (SQLite WAL, tope 32 MB): `event` y `trip` nunca se descartan; `vehicle`/`perception` se deciman al reenviar; `pos` no se spoolea por defecto. El backfill **nunca** refresca `last_seen` ni marca el coche online.

Backend, fase 1 del rework (resuelve el 80 %): cola en memoria acotada + writer dedicado con commit por lotes **fuera** del hilo de paho; WSGI real en vez del servidor de desarrollo de Werkzeug; sweeper global de retención; `trip_id` en muestras, eventos, imágenes y `command_log`. Postgres/Timescale queda aplazado y disparado por umbral de dispositivos.

---

## 8. Configuración: deseada vs reportada

Hoy hay **tres fuentes de verdad divergentes** (Params en el coche, tablas en el backend, `SharedPreferences` en el móvil) sin ninguna reconciliación.

- `orbit/v2/cfg/desired/<dongle>` — retenido, lo publica **solo el backend** tras validar propiedad.
- `orbit/v2/cfg/reported/<dongle>` — retenido, lo publica **el firmware tras aplicar**.
- Formato: `{version, ts_ms, source, values}`. **Gana la versión más alta; empate a favor de `comma_ui`** — el coche siempre puede corregir en local.

Sustituye a los cuatro params-buzón actuales y al `PUT /api/jetson/config` global. En la app, cada fila muestra **valor deseado frente a valor reportado**, con «aplicando…» mientras difieran. Cola offline **solo para configuración**: un ajuste diferido es útil, una maniobra diferida es un peligro.

---

## 9. Reparto de interfaz: qué se queda en el comma

El panel ORBIT son hoy ~2.950 px de scroll más dos subpaneles.

**Se queda** (necesita ojos en el coche o red caída): QR de enrolamiento · IP del broker · selector de modo de volante con confirmación · **armado del modo banco** · «Restablecer valores seguros» · **interruptor maestro local de privacidad** · los overlays onroad que avisan de mando remoto, esquive y ángulo muerto.

**Se va a la app:** los 8 toggles de telemetría, la sección de red de Jetson, la sección de pruebas, y la configuración de cámara.

**Se borra:** `debug_panel.py` (tapa media pantalla de carretera con un param `PERSISTENT|BACKUP` que sobrevive a reinicios *y a copias de seguridad*), `torque_hud.py`, y los overlays que leen params sin escritor.

**Innegociable:** el interruptor de «dejar de emitir» (posición y cámara como mínimo) tiene que funcionar **sin red y con el móvil apagado**. Trasladar la privacidad entera a la app la elimina.

---

## 10. La app

### 10.1 Arquitectura de información

Primer nivel: **Vehículo · Mapa · Cuenta**. El sujeto es el coche, no la flota.

Dentro del vehículo, tres pestañas (de cuatro a tres): **Cabina · Mando · Registro**. «Parámetros» se pliega dentro de Cabina; «Eventos» y «Actividad» se funden en Registro.

### 10.2 Pantalla de Mando

Sin acordeones. Cuatro zonas:

1. **Cinta de estado fija** arriba: velocidad, crucero, engaged, **salud del enlace**. Cuando el enlace se degrada, **atenúa todo lo demás**.
2. **Crucero** como control principal (es lo que se usa el 90 % del tiempo y hoy está enterrado).
3. **Maniobras**: cambio de carril por **mantener pulsado 400 ms** con anillo de progreso. Nada crítico a un solo toque.
4. **Deceleración asistida** por **deslizador**, con la intensidad real impresa en el raíl. Fuera el modal de cuatro advertencias que hoy nadie lee.

`Desarmar todo` siempre alcanzable. **Se retira la cruceta.**

El gradiente de riesgo actual está invertido: la barra roja exige leer un modal de cuatro advertencias, y la flecha de la cruceta frena **sin etiqueta ni confirmación**. Se corrige.

### 10.3 Onboarding, vinculación y ayuda

- **Primer arranque:** qué es ORBIT y, explícitamente, **qué NO puede hacer**. La aceptación de seguridad se registra **en el backend** con fecha, versión del texto y `user_id` — un bool en `SharedPreferences` se borra al reinstalar y no prueba nada.
- **Asistente de vinculación QR paso a paso:** qué ve en la pantalla del comma, qué ve en la app, y qué hacer si falla (código caducado, sin cobertura, dispositivo ya reclamado). Permiso de cámara pedido **antes** de abrir el escáner.
- **Centro de ayuda:** guía por función, glosario y solución de problemas con diagnóstico en vivo. Las precondiciones de cada verbo se **generan del mismo mapa que usa el motor de gates**, así no pueden desincronizarse de la realidad.

### 10.4 Sistema de diseño

Tokens v2 con **semántica cerrada**: rojo solo para freno y error; verde nunca como fondo de acción; `onAccent` obligatorio sobre relleno claro. Test de lint que **falla** ante `Colors.` o `TextStyle(` fuera de `lib/theme`. Seis pasos tipográficos. Accesibilidad real: escalado del sistema acotado a 1.4 (hoy se **anula**), `Semantics` en todos los controles de mando, y un «Modo Coche» que de verdad suba contraste y tamaño.

---

## 11. Intermitentes (D3: panda firmado)

**Ford, y solo Ford.** `Steering_Data_FD1` (0x083) ya lo transmite openpilot vía `fordcan.create_button_msg`, ya está en la allowlist TX de `opendbc/safety/modes/ford.h:307-313` para bus 0 y 2, y su `tx_hook` solo valida `cancel`/`resume` y comenta explícitamente que blinkers, limpias y largas son *passthru*.

Trabajo: parámetro `turn` en `create_button_msg` · emisión **continua** mientras dure (hoy el mensaje solo se envía en eventos) · **verificación en banco de quién gana la puja de 0x083 frente al SCCM real**.

Condición de producto: **solo acoplado a una maniobra real, nunca como botón suelto.** Un intermitente remoto sin maniobra es una señal falsa a los demás conductores.

Resto de marcas: `caps` declara `blinker.supported=false` y la app **no pinta el control**. Hyundai CAN-FD queda **descartado**: `CANFD_ENABLE_BLINKERS` existe pero **ninguna PlatformConfig lo asigna**, y 0x165/0x16A **no están en ninguna lista TX** — está doblemente muerto, y quien lea ese código puede creer que funciona.

---

## 12. Plan de pruebas de fallo

Los tests de contrato validan la forma del payload. Lo que decide si esto es seguro son estas pruebas, y hoy no existe **ninguna** (`orbit/test/` tiene dos ficheros, ambos del pulso de obstáculo):

| Prueba | Resultado esperado |
|---|---|
| Cortar el enlace a mitad de maniobra | coche neutro en < 1,5 s |
| Reinyectar un comando capturado | `DUPLICATE` |
| Entregar dos comandos fuera de orden | una sola maniobra, `SUPERSEDED` en el otro |
| Reloj desfasado 5 min | `CLOCK`, no ejecución |
| Publicar con `retain` en el topic de mando | descartado |
| Payload vacío | descartado |
| Saturar el broker | sin bloqueo del hilo de red, sin crecimiento de RAM |
| Matar el proceso de telemetría con un viaje abierto | ningún actuador pegado |
| Jetson colgada en modo 3 | neutro al expirar el watchdog |
| Comando de otro `dongle_id` | descartado |

Banco HIL o, como mínimo, MetaDrive **con inyección de latencia** (el entorno de simulación ya está montado en este árbol).

---

## 13. Migración v1 → v2

1. Publicación **dual** v1+v2 durante una versión, con `schema_version` en ambos. **Las dos copias son la MISMA orden del usuario y el coche tiene que tratarlas como tal.** Hoy no se cruzan solas: el puente v1 fabrica su propio `id` y usa otro cajón de secuencia, así que la idempotencia no las une. Medido: un `cruise_delta` gastaba el **doble** del presupuesto de ritmo, y si el sobre v2 se rechazaba (gate rojo, modo insuficiente) el gemelo v1 se ejecutaba igual — la app decía «Rechazada» mientras el coche cambiaba de carril. Dos mecanismos, en este orden:
   - **Correlación por `id`**: si el emisor v1 declara el `id` del sobre v2 gemelo (`origin_id` en `CommandRouter.submit_local`), la LRU de idempotencia las une por identidad y la copia v1 se descarta **en silencio** — el ACK del gemelo es el que el backend conoce. Requiere que el shim lo publique en el payload v1.
   - **Ventana de eco** (respaldo, mientras no viaje ese `id`): mismo verbo y mismos argumentos por **caminos distintos** en menos de 2 s = una sola orden. Solo cruza caminos distintos: dos pulsaciones reales del usuario viajan siempre por el mismo, y tragarse la segunda sería un botón que no responde.

   Lo definitivo es lo que dice el título de la fase: **dejar de publicar el v2 en los shims** en cuanto la app deje de usar las rutas legacy.
2. La app consume v2 en cuanto exista; el backend acepta ambos.
3. Los verbos v1 se van apagando **por verbo**, con el `caps` marcando cuáles ya no existen.
4. Al cerrar la migración se borran `telemetry_config/*` de mando y el namespace `*/global` de los dos repos.

---

## 14. Fases

| Fase | Objetivo | Éxito |
|---|---|---|
| **F0** *(en curso)* | Contención: quitar peligro y superficie muerta | Los 12 bugs críticos cerrados; `ruff`/`flutter analyze`/`pytest` en verde |
| **F1** | Mando por backend autenticado + plomería de transporte (desactivada) | La app no puede publicar en ningún topic de mando; ninguna orden llega al coche sin pasar por el guard de propiedad y dejar fila en `command_log`; no queda ningún topic `*/global` |
| **F2** | Protocolo v2: sobre, ACK, modos, gates, deadman + arreglo de los verbos | La tabla de §12 entera en verde. Cada comando termina en un ACK con fase y motivo. Ningún verbo físico alcanzable sin armado local |
| **F3** | Telemetría v1 + backend que aguante | Consumo medido por debajo de 6 MB/h en perfil NORMAL **con más señales útiles que hoy**; un viaje se reconstruye por `trip_id` sin heurísticas |
| **F4** | Configuración deseada/reportada + adelgazar la UI del comma | Cambiar un ajuste desde cualquiera de los dos lados se refleja en el otro sin pisarse; el panel ORBIT cabe en una pantalla |
| **F5** | UX, onboarding y ayuda | Ningún control dice «enviado» sin confirmación; un usuario nuevo llega del registro a ver telemetría sin ayuda externa |
| **F6** | Intermitentes Ford, cámara bajo demanda, banco | Intermitentes verificados en banco con el SCCM emitiendo en paralelo; cámara por debajo de 2 MB/h |

---

## 15. Fuera de alcance, y por qué

- **Firmware de panda propio** → decisión de empresa (responsabilidad civil, seguro, homologación), no de backlog técnico. D3 = firmado.
- **Lectura de DTC por UDS** → aunque 0x7D0/0x730/0x750 estén en las allowlists, el `tx_hook` solo deja pasar el frame exacto de *tester-present*. Exigiría tocar panda.
- **Teleconducción sobre LTE** → el control físico existe **solo** en modo banco, red local, coche parado y con alguien delante.
- **Ráfagas de largas y limpias** → técnicamente posibles por el mismo 0x083 en Ford; fuera de alcance de forma permanente.
- **Monitorización del conductor como producto** → los datos existen y se usan **solo** como gate de precondición (`DRIVER_PRESENT`). Publicarlos como canal es un tratamiento con base jurídica propia y va detrás de la postura legal.

---

## 16. Lo que sigue sin resolver

Estas tres no bloquean F1–F2, pero sí F3 en adelante:

1. **Escala y propiedad.** ¿Piloto de ~10 coches con propiedad 1:1 (SQLite basta) o decenas con vehículos compartidos (Postgres, permisos por vehículo, y **arbitraje entre mandos simultáneos**, que hoy no existe)? El parámetro `user_id` de los comandos está escrito como si ya hubiera vehículos compartidos, y el esquema lo prohíbe.
2. **Postura legal.** Responsable del tratamiento, base jurídica por canal, DPIA para posición y monitorización, retención justificada, y — en flota — informar a la persona vigilada, que no es la que da el consentimiento.
3. **Revocación y ciclo de vida del vínculo.** Móvil robado, cuenta comprometida, venta del coche, desvinculación forzada, y kill-switch de flota para una versión conocida como mala.
