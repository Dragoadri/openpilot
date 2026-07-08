# Modo 3 "COMMA + JETSON" — Esquive de obstáculos

**Fecha**: 2026-05-07
**Rama**: `sic-jetson-comma`
**Autor**: Adrián Cañadas (con Claude)
**Estado**: Diseño aprobado por el usuario, pendiente de plan de implementación

---

## 1. Problema y motivación

El proyecto SIC-UEM tiene una Jetson conectada al Comma vía ZMQ que ejecuta un
modelo PilotNet para conducción autónoma. Hoy existen 3 modos de torque
(`SteerTorqueMode` 0/1/2):

- `0` = COMMA (modelo openpilot, default)
- `1` = JETSON (PilotNet manda el torque continuo)
- `2` = TEST MAX (banco)

El modo 1 deja el control completo al modelo de la Jetson, lo que no siempre es
deseable: el modelo de Comma es muy fiable en autopista pero **no reacciona a
ciertos obstáculos** (objetos en calzada, vehículos parados en arcén, etc.).
La Jetson sí los detecta.

Queremos un modo intermedio: **el Comma sigue conduciendo (torque normal del
modelo openpilot) pero la Jetson puede inyectar maniobras de esquive
temporales cuando detecte obstáculos**.

## 2. Solución: nuevo modo `3` = COMMA + JETSON

### 2.1 Resumen funcional

- Por defecto, idéntico al modo 0 (Comma manda).
- La Jetson envía un mensaje JSON por ZMQ cuando detecta un obstáculo,
  con `intensity` (-1..+1) y `duration_ms`.
- El Comma traduce esa intensidad en un offset de `steeringAngleDeg` y
  `desired_curvature` durante el tiempo indicado.
- Sin fase de retorno: al expirar la duración, el `LatControlTorque` del
  Comma reconduce el coche al centro por sí mismo.
- Cancelaciones por seguridad: volante presionado, freno, control lateral
  inactivo, watchdog Jetson stale, mensaje nuevo (sustitución).

### 2.2 Decisiones cerradas con el usuario

| # | Pregunta | Decisión |
|---|----------|----------|
| 1 | ¿Qué representa el valor de la Jetson? | Intensidad [-1, +1] traducida a offset de curvatura/ángulo (no torque puro) |
| 2 | ¿Quién decide la duración? | La Jetson, capada a un máximo por el Comma |
| 3 | ¿Fase de retorno? | No, el LatControlTorque del Comma reconduce |
| 4 | ¿Canal? | ZMQ puerto 5556 (mismo de siempre, formato distinguido por longitud) |
| 5 | ¿Qué cancela el esquive? | Volante presionado, freno, mensaje nuevo (sustituye), watchdog, lat inactivo |
| 6 | ¿ID interno del modo nuevo? | `3` (sumar al final, sin renumerar 0/1/2) |
| 7 | ¿Magnitud máxima del esquive? | ±25° y ±0.030 1/m para `intensity = ±1.0` |
| 8 | ¿Formato del mensaje? | JSON UTF-8 |
| 8 | ¿Detección de formato en zmq_client? | Por longitud (`len > 4` = JSON, `len == 4` = float legacy) |
| 8 | ¿Tope duración / watchdog? | 2500 ms / 400 ms |
| 9 | ¿UI? | Param `JetsonObstacleStatus` + indicador discreto en pantalla Comma + sincronización MQTT a la app |
| 10 | ¿Constantes editables como params? | Sí: `JetsonObstacleMaxDurationMs`, `JetsonObstacleWatchdogMs`, `JetsonObstacleMaxAngle`, `JetsonObstacleMaxCurv` |

### 2.3 Convención de signo

`intensity` sigue la convención del Comma usada en `controlsd.py:894-897`:
**negativo = derecha, positivo = izquierda**.

## 3. Arquitectura

```
┌─────────────────────────┐
│   JETSON (PilotNet +    │
│   detector de obstáculo)│
└────────────┬────────────┘
             │ ZMQ puerto 5556 (PUSH→PULL)
             │ • float 4B   → modo 1 (legacy)
             │ • JSON >4B   → modo 3 (NUEVO)
             ▼
┌─────────────────────────┐
│ zmq_client.py           │
│ _torque_listener()      │
│ ─ parse_torque (4B)     │  → JetsonTorque, JetsonTorqueTimestamp
│ ─ parse_obstacle (JSON) │  → JetsonObstaclePulse, JetsonObstacleTimestamp
└────────────┬────────────┘
             │ Params
             ▼
┌─────────────────────────┐
│ controlsd.py            │
│ steer_mode == 3 →       │
│   actuators.steer = Comma (no se toca)
│   steeringAngleDeg += offset(intensity)
│   desired_curvature += offset(intensity)
│ ObstaclePulseState:     │
│   ingest, get_offsets,  │
│   cancelaciones         │
└────────────┬────────────┘
             │ JetsonObstacleStatus param
             ▼
┌─────────────────────────┐
│ UI Comma (jetson_       │  ← indicador discreto
│ settings.cc) + app      │     vía param + MQTT bridge
└─────────────────────────┘
```

## 4. Componentes a modificar / añadir

### 4.1 Params nuevos (`common/params.cc`)

```cpp
// Pulso de esquive (CLEAR_ON_MANAGER_START)
{"JetsonObstaclePulse", CLEAR_ON_MANAGER_START},
  // JSON crudo del último mensaje recibido. Lo escribe zmq_client.

{"JetsonObstacleTimestamp", CLEAR_ON_MANAGER_START},
  // Wall-clock time.time() del último mensaje recibido. Watchdog.

{"JetsonObstacleStatus", CLEAR_ON_MANAGER_START},
  // Estado actual del esquive: "" | "DODGING_LEFT" | "DODGING_RIGHT" |
  // "CANCELED_DRIVER" | "CANCELED_STALE". Lo escribe controlsd.

{"JetsonObstacleStatusMqttPayload", CLEAR_ON_MANAGER_START},
  // Payload JSON listo para publicar via MQTT.

// Configuración (PERSISTENT)
{"JetsonObstacleMaxDurationMs", PERSISTENT},   // default 2500
{"JetsonObstacleWatchdogMs", PERSISTENT},      // default 400
{"JetsonObstacleMaxAngle", PERSISTENT},        // default 25.0
{"JetsonObstacleMaxCurv", PERSISTENT},         // default 0.030
```

`SteerTorqueMode` no cambia: ahora acepta valores `0, 1, 2, 3`.

**Sembrado de defaults**: en `ObstaclePulseState._refresh_config()` (lectura
con cache, 1 vez/s), si `params.get(key)` devuelve `None` se usa el default
hardcoded en el módulo y se escribe en el param para que aparezca en la UI
la primera vez. La UI/app permitirá editarlos posteriormente.

### 4.2 Módulo nuevo `sicuem/orbit/orbit_obstacle_pulse.py`

Encapsula el estado del esquive activo. Análogo a `orbit_steering_pulse.py`
pero leyendo de Params (no globals — el productor `zmq_client` está en otro
proceso) y con cancelaciones más completas.

API:

```python
class ObstaclePulseState:
  def ingest_new_message(self, payload_dict, now): ...
  def get_offsets(self, now, carstate, lat_active) -> (angle_off, curv_off, status): ...
```

**Comportamiento de `obstacle: false`**: si llega un mensaje con
`obstacle == False`, `ingest_new_message` actúa como cancelación explícita
(`self.active = False`, status `""` en el siguiente frame). Es la forma
oficial que tiene la Jetson de cortar un esquive antes de que expire
naturalmente. Como la Jetson normalmente sólo manda cuando hay obstáculo,
este caso es opcional pero se respeta si llega.

Las constantes de magnitud y timeouts se leen de Params con cache (1 lectura/s
o cuando cambien) para evitar overhead a 100 Hz.

### 4.3 `selfdrive/controls/controlsd.py`

Añadir rama `steer_mode == 3` justo después del `elif steer_mode == 2` (línea
~1086):

```python
elif steer_mode == 3:
  # COMMA+JETSON: actuators.steer = Comma. Aplicaremos offsets más abajo.
  pass

# Tras el selector, junto al pulso de la cruceta:
if CC.latActive and steer_mode == 3:
  # Detectar mensaje nuevo (timestamp más reciente que el cached)
  payload_ts = float(self.params.get("JetsonObstacleTimestamp") or 0.0)
  if payload_ts > self._obstacle_pulse_state.last_payload_ts:
    payload_raw = self.params.get("JetsonObstaclePulse")
    if payload_raw:
      try:
        payload = json.loads(payload_raw)
        self._obstacle_pulse_state.ingest_new_message(payload, time.time())
      except (ValueError, TypeError):
        cloudlog.error("ObstaclePulse: payload JSON inválido")

  angle_off, curv_off, status = self._obstacle_pulse_state.get_offsets(
    time.time(), CS, CC.latActive
  )
  if angle_off or curv_off:
    actuators.steeringAngleDeg += angle_off
    self.desired_curvature += curv_off

  if status != self._last_obstacle_status:
    self.params.put_nonblocking("JetsonObstacleStatus", status)
    self.params.put_nonblocking(
      "JetsonObstacleStatusMqttPayload",
      json.dumps({"status": status, "ts": time.time(), "source": "comma"})
    )
    self._last_obstacle_status = status
```

Inicialización en `Controls.__init__`:

```python
from openpilot.sicuem.orbit.orbit_obstacle_pulse import ObstaclePulseState
self._obstacle_pulse_state = ObstaclePulseState()
self._last_obstacle_status = ""
```

### 4.4 `sicuem/orbit/zmq_client.py`

En `_torque_listener()`, distinguir formato por longitud:

```python
if len(data) > 4:
  # Modo 3: JSON
  try:
    payload = json.loads(data.decode())
    if not isinstance(payload.get("intensity"), (int, float)):
      cloudlog.error(...); continue
    now = time.time()
    self._params.put("JetsonObstaclePulse", json.dumps(payload))
    self._params.put("JetsonObstacleTimestamp", f"{now:.6f}")
  except (ValueError, KeyError) as e:
    cloudlog.error(f"ZMQClient: JSON obstáculo inválido: {e}")
  continue

# len <= 4: float legacy del modo 1, sin cambios respecto al actual
torque = _parse_torque(data)
...
```

### 4.5 UI Comma (`jetson_settings.cc`/`.h`)

Añadir 4º botón en el orden visual: **COMMA → COMMA+JETSON → JETSON → TEST MAX**.

```cpp
// .h
QPushButton *btn_mode_comma_jetson;

// .cc en setupTorqueControlSection():
btn_mode_comma_jetson = makeModeButton(tr("COMMA + JETSON\n(esquive obstaculos)"), "#3B82F6");
ml->addWidget(btn_mode_model);
ml->addWidget(btn_mode_comma_jetson);   // 2ª posición visual
ml->addWidget(btn_mode_jetson);
ml->addWidget(btn_mode_test);
connect(btn_mode_comma_jetson, &QPushButton::clicked, this, [this]() { tryChangeSteerMode(3); });
```

Diálogo de confirmación medio (azul, no rojo) explicando el modo. Mismo patrón
que `tryChangeSteerMode(0/1/2)` actual.

`updateSteerModeVisual(int mode)`: `btn_mode_comma_jetson->setChecked(mode == 3)`.

Mini indicador debajo de los botones que lee `JetsonObstacleStatus` cada 500 ms:
- vacío → invisible
- `DODGING_LEFT/RIGHT` → "🚨 ESQUIVANDO ←/→" amarillo
- `CANCELED_DRIVER` → "⚠ Cancelado por conductor" gris (3 s)
- `CANCELED_STALE` → "❌ Jetson sin respuesta" rojo (3 s)

### 4.6 UI app Flutter (`orbit_app/lib/screens/jetson_config_screen.dart`)

Añadir 4ª tarjeta en `_buildSteerTorqueModeCard()` después de la del modo 0
y antes de la del modo 1:

```dart
_buildSteerModeCard(
  mode: 3,
  title: 'COMMA + JETSON',
  subtitle: 'Comma manda + Jetson esquiva obstáculos',
  description: 'Torque normal del modelo Comma. La Jetson puede inyectar esquives temporales cuando detecte un obstáculo.',
  accent: const Color(0xFF3B82F6),
  icon: Icons.shield_rounded,
  badge: _ModeBadge(text: 'BETA', icon: Icons.science_rounded),
),
```

Widget de estado en vivo escuchando `JetsonObstacleStatus` por MQTT. Mismo
patrón del listener `steer_torque_mode` ya existente.

`_changeSteerMode(int mode)` ya acepta cualquier int; basta validar 0..3 si se
quiere ser estricto.

### 4.7 MQTT bridge (`sicuem/orbit/mqtt_envio_general.py`)

Publicador del payload `JetsonObstacleStatusMqttPayload` en topics:
- `telemetry_config/{dongle_id}/jetson_obstacle_status`
- `jetson_obstacle_status/global`

Sentido único Comma → app (la app no envía esquives, sólo los muestra).

### 4.8 `sicuem/orbit/mqtt_comandos.py`

`handle_steer_torque_mode` ya parsea int. Sólo asegurar que acepta `3` como
valor válido (validación explícita opcional `if mode not in (0,1,2,3): reject`).

## 5. Protocolo Jetson → Comma (resumen)

Documento separado: `/home/drago/Escritorio/PROTOCOLO_JETSON_MODO3.md`

Esquema:

```json
{
  "obstacle": true,
  "intensity": -0.7,
  "duration_ms": 1500
}
```

- Convención de signo: **negativo = derecha**, positivo = izquierda.
- `intensity ∈ [-1, +1]` (capado).
- `duration_ms ∈ [1, 2500]` (capado al máximo en Comma).
- Sólo enviar cuando hay obstáculo. No heartbeat.
- Mensaje nuevo durante un esquive activo → sustituye al actual.

## 6. Cronología de un esquive

```
T=0        Coche en modo 3, Comma manda. Status = "".
T=0.001s   Jetson detecta obstáculo, envía JSON.
T=0.010s   zmq_client.recv → params.put(JetsonObstaclePulse, JetsonObstacleTimestamp).
T=0.020s   controlsd siguiente frame: ingest_new_message, get_offsets devuelve
           (-17.5°, -0.021, "DODGING_RIGHT"). Aplica offsets a steeringAngleDeg
           y desired_curvature. Publica status.
T=0.05s    mqtt_envio_general detecta payload nuevo → topic MQTT → app/UI Comma muestran.
T=0.02..1.5s   El LatControlTorque persigue la nueva trayectoria desplazada.
T=1.5s     Expiración natural: get_offsets → (0, 0, ""). Se quita el offset.
T=1.5..2s  El LatControlTorque del Comma recentra el coche solo (sin fase de retorno explícita).
```

Cancelaciones posibles entre T=0.02 y T=1.5:
- `steeringPressed` o `brakePressed` → reset, status `CANCELED_DRIVER`.
- `latActive=False` → reset, status `""`.
- `(now - last_payload_ts) > watchdog_ms` → reset, status `CANCELED_STALE`.
- Mensaje nuevo de la Jetson → `ingest_new_message` sustituye.

## 7. Tests / verificación

1. **Unit**: `ObstaclePulseState` ingest + tick por tick (offsets, cancelaciones,
   expiración, sustitución).
2. **Protocolo**: enviar JSON conocido por ZMQ → comprobar que
   `JetsonObstaclePulse`/`JetsonObstacleTimestamp` se actualizan.
3. **Coexistencia modo 1/3**: enviar 4-byte float después de un JSON → ambos
   funcionan sin interferirse.
4. **Seguridad**: `duration_ms: 999999` → se capa a 2500.
5. **Coche/sim**: con obstáculo simulado y modo 3, ver volante moverse y
   recentrarse.

## 8. Riesgos y mitigaciones

| Riesgo | Mitigación |
|--------|------------|
| Jetson se cuelga durante esquive | Watchdog 400 ms → cancelar |
| `duration_ms` enorme accidental | Cap a `JetsonObstacleMaxDurationMs` (2500 ms) |
| `intensity` fuera de rango | Clamp [-1, +1] en `ingest_new_message` |
| Pelea con LatControlTorque al recentrar | Sin fase de retorno; el PID ya recentra solo |
| JSON malformado | `try/except` con log de error y skip del mensaje |
| Coche se va a un lado por offset acumulado entre frames | Offsets aplicados son **absolutos por frame** (no acumulan), si dejas de aplicar vuelve a la base de Comma inmediatamente |

## 9. Trabajo no incluido (YAGNI)

- Categorización por tipo de obstáculo (peatón vs cono vs vehículo).
- Comunicación bidireccional Comma → Jetson para que la Jetson sepa el estado
  del coche (vEgo, ángulo actual). De momento es one-way.
- Aprendizaje del comportamiento (logs estructurados sí, pero no fine-tuning
  online).
- Adaptación de la magnitud según vEgo (a más velocidad, esquive más suave).
  Si en pruebas se ve necesario, se añade en una iteración posterior.

## 10. Plan de implementación (alto nivel — el plan detallado lo hará writing-plans)

1. Añadir params en `common/params.cc` y compilar.
2. Crear `orbit_obstacle_pulse.py` con tests unitarios.
3. Extender `zmq_client.py` con la rama JSON.
4. Modificar `controlsd.py` con la rama `steer_mode == 3`.
5. Modificar `jetson_settings.cc/.h` (4º botón + indicador).
6. Modificar `mqtt_envio_general.py` (publicador del status).
7. Modificar `mqtt_comandos.py` (validar valor `3`).
8. Modificar app Flutter (4ª tarjeta + listener).
9. Tests integrados con mensaje JSON de prueba.
10. Documentar en `STEER_TORQUE_MODE.md` y commit del protocolo Jetson.
