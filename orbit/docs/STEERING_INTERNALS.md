# Como funciona el sistema de direccion internamente

Documento de referencia para entender la logica interna de giro, torque, cambio de carril
y como la velocidad afecta a todo el sistema.

---

## Indice

1. [Flujo general: de la carretera al volante](#1-flujo-general)
2. [La velocidad lo cambia todo](#2-la-velocidad-lo-cambia-todo)
3. [Curvatura, aceleracion lateral y torque](#3-curvatura-aceleracion-lateral-y-torque)
4. [El controlador PID de torque](#4-el-controlador-pid-de-torque)
5. [Limites de torque por coche](#5-limites-de-torque-por-coche)
6. [Rate limiting: rampa de torque](#6-rate-limiting-rampa-de-torque)
7. [Override del conductor](#7-override-del-conductor)
8. [Cambio de carril: maquina de estados](#8-cambio-de-carril-maquina-de-estados)
9. [El sistema Desire](#9-el-sistema-desire)
10. [ForceLaneChange de ORBIT](#10-forcelanechange-de-orbit)
11. [Steering Pulse de ORBIT](#11-steering-pulse-de-orbit)
12. [BSM (Blind Spot Monitoring)](#12-bsm-blind-spot-monitoring)
13. [Envio al CAN bus](#13-envio-al-can-bus)
14. [Tabla resumen de parametros](#14-tabla-resumen)
15. [Archivos clave](#15-archivos-clave)

---

## 1. Flujo general

La cadena completa desde que la camara ve la carretera hasta que el volante gira:

```
Camara (camerad)
    |
    v
Modelo de IA (supercombo) → detecta carriles, bordes, trayectoria
    |
    v
Lateral Planner (lateral_planner.py) → calcula path optimo con MPC
    |
    v
Curvatura deseada (1/metro) → "cuanto tiene que curvarse el coche"
    |
    v
Controlador lateral (latcontrol_torque.py) → convierte curvatura a torque
    |
    v
PID loop → P + I + D + Feedforward = torque normalizado [-1.0, 1.0]
    |
    v
Limites del coche (car/__init__.py) → rate limiting + limites de torque
    |
    v
Car Controller (hyundai/carcontroller.py) → escala a unidades del coche
    |
    v
Mensaje CAN (LKAS11 o LFA) → se envia al motor de la direccion (EPS)
    |
    v
El volante gira
```

**Archivos involucrados en orden:**
- `selfdrive/controls/lib/lateral_planner.py` → planificacion del path
- `selfdrive/controls/controlsd.py` → loop principal de control (lineas 835-863)
- `selfdrive/controls/lib/latcontrol_torque.py` → conversion curvatura → torque
- `selfdrive/controls/lib/pid.py` → controlador PID
- `selfdrive/car/__init__.py` → limites de torque genericos
- `selfdrive/car/hyundai/carcontroller.py` → controlador especifico Hyundai
- `selfdrive/car/hyundai/hyundaican.py` → creacion del mensaje CAN

---

## 2. La velocidad lo cambia todo

### La formula clave

```python
# latcontrol_torque.py:177
desired_lateral_accel = desired_curvature * CS.vEgo ** 2
```

La aceleracion lateral crece con el **cuadrado** de la velocidad. Misma curvatura, resultados
muy diferentes:

| Velocidad | vEgo (m/s) | Curvatura 0.01 | Aceleracion lateral |
|-----------|-----------|----------------|---------------------|
| 20 km/h   | 5.5       | 0.01           | **0.3 m/s2**        |
| 50 km/h   | 13.9      | 0.01           | **1.9 m/s2**        |
| 80 km/h   | 22.2      | 0.01           | **4.9 m/s2**        |
| 100 km/h  | 27.8      | 0.01           | **7.7 m/s2**        |
| 120 km/h  | 33.3      | 0.01           | **11.1 m/s2**       |

Esto significa que a 100 km/h la misma curva requiere **~25 veces mas** aceleracion lateral
que a 20 km/h. El sistema compensa esto automaticamente porque trabaja con aceleracion
lateral, no con angulos fijos.

### Compensacion de friccion a baja velocidad

A baja velocidad, la direccion tiene mas friccion mecanica. El sistema lo compensa:

```python
# latcontrol_torque.py:27-28
LOW_SPEED_X = [0, 10, 20, 30]   # m/s
LOW_SPEED_Y = [15, 13, 10, 5]   # factor de friccion (se eleva al cuadrado)
```

| Velocidad (m/s) | Factor friccion | Factor^2 |
|------------------|----------------|----------|
| 0                | 15             | 225      |
| 10 (~36 km/h)   | 13             | 169      |
| 20 (~72 km/h)   | 10             | 100      |
| 30 (~108 km/h)  | 5              | 25       |

El factor de friccion se suma a la senal de control para vencer la resistencia mecanica del
volante. A mas velocidad, menos friccion se necesita.

---

## 3. Curvatura, aceleracion lateral y torque

### La cadena de conversion

```
Curvatura (1/m)
    |   × velocidad^2
    v
Aceleracion lateral deseada (m/s2)
    |   - aceleracion lateral real
    v
Error de aceleracion lateral
    |   / latAccelFactor + friccion
    v
Torque feedforward (fuerza base)
    |   + PID(error)
    v
Torque normalizado [-1.0, 1.0]
    |   × STEER_MAX
    v
Torque en unidades del coche (ej: -384 a +384 para Hyundai)
```

### Conversion de curvatura a angulo de volante

```python
# vehicle_model.py:93-105
def get_steer_from_curvature(self, curv, u, roll):
    return (curv - self.roll_compensation(roll, u)) * self.sR * 1.0 / self.curvature_factor(u)
```

Donde:
- `curv`: curvatura deseada (1/m)
- `u`: velocidad (m/s)
- `sR`: ratio de la direccion (cuanto gira el volante vs las ruedas)
- `curvature_factor(u)`: factor que depende de la velocidad y el slip de los neumaticos

### Torque desde aceleracion lateral (modelo lineal)

```python
# interfaces.py:343-350
def torque_from_lateral_accel_linear(self, latcontrol_inputs, torque_params, ...):
    friction = get_friction(...)
    return (lateral_acceleration / float(torque_params.latAccelFactor)) + friction
```

Ejemplo: si `latAccelFactor = 0.25`, entonces 1.0 m/s2 de aceleracion lateral = 4 unidades
de torque.

---

## 4. El controlador PID de torque

El error entre la aceleracion lateral deseada y la real se procesa con un PID:

```python
# latcontrol_torque.py:237-238
setpoint = desired_lateral_accel + low_speed_factor * desired_curvature
measurement = actual_lateral_accel + low_speed_factor * actual_curvature
error = setpoint - measurement
```

```python
# pid.py:55-72
self.p = error * self.k_p           # Proporcional: reaccion inmediata al error
self.i += error * self.k_i * dt     # Integral: corrige errores persistentes
self.d = error_rate * self.k_d      # Derivativo: amortigua oscilaciones
self.f = feedforward * self.k_f     # Feedforward: prediccion del torque necesario

control = self.p + self.i + self.d + self.f
output = clip(control, -1.0, 1.0)   # Normalizado entre -1 y 1
```

### Feedforward con red neuronal (opcional)

Si `use_nn=True`, se usa una red neuronal para predecir el torque directamente:

```python
# latcontrol_torque.py:207-249
nn_input = [CS.vEgo, desired_lateral_accel, friction_input, roll]
           + past_lateral_accels + future_planned_accels
           + past_rolls + future_rolls
ff = self.torque_from_nn(nn_input)
```

La NN toma velocidad, aceleracion lateral, friccion, inclinacion, y datos pasados/futuros
para predecir directamente el torque. Mejor que el modelo lineal para coches no lineales.

---

## 5. Limites de torque por coche

### Hyundai/Kia (nuestro caso)

```python
# hyundai/values.py:15-51
class CarControllerParams:
    STEER_DELTA_UP = 3         # incremento por frame (100 Hz)
    STEER_DELTA_DOWN = 7       # decremento por frame
    STEER_DRIVER_ALLOWANCE = 50
    STEER_DRIVER_MULTIPLIER = 2
    STEER_DRIVER_FACTOR = 1
    STEER_THRESHOLD = 150

    # Segun el coche:
    STEER_MAX = 384            # Hyundai/Kia estandar
    STEER_MAX = 270            # CAN-FD (coches nuevos)
    STEER_MAX = 255            # Genesis G80/G90
```

### Comparativa entre marcas

| Parametro        | Hyundai    | Toyota | GM   | Subaru    |
|------------------|-----------|--------|------|-----------|
| STEER_MAX        | 255-384   | 1500   | 300  | 1000-3071 |
| STEER_DELTA_UP   | 2-3       | 10-15  | 10   | 40-50     |
| STEER_DELTA_DOWN | 3-7       | 25     | 15   | 40-70     |
| Frecuencia ctrl  | 100 Hz    | 100 Hz | 33 Hz| 100 Hz    |

Los numeros son unidades internas de cada fabricante (no son Nm directos).
- GM: 300 unidades = 3 Nm
- El resto depende del EPS del coche

---

## 6. Rate limiting: rampa de torque

No se puede pasar de 0 a STEER_MAX de golpe. El torque sube/baja gradualmente:

```python
# car/__init__.py:113-128 (simplificado)
def apply_driver_steer_torque_limits(apply_torque, apply_torque_last, driver_torque, LIMITS):
    # Rate limit: no cambiar mas de DELTA_UP/DOWN por frame
    apply_torque = clip(apply_torque,
                       apply_torque_last - LIMITS.STEER_DELTA_DOWN,
                       apply_torque_last + LIMITS.STEER_DELTA_UP)
    return apply_torque
```

### Tiempos reales para llegar al maximo (Hyundai estandar)

```
STEER_MAX = 384, STEER_DELTA_UP = 3, a 100 Hz:

Tiempo para llegar al max = 384 / 3 = 128 frames = 1.28 segundos

Desglose:
  0.0s → torque = 0
  0.1s → torque = 30
  0.5s → torque = 150
  1.0s → torque = 300
  1.28s → torque = 384 (MAX)
```

La bajada es mas rapida (seguridad):
```
Tiempo para bajar del max = 384 / 7 = 55 frames = 0.55 segundos
```

---

## 7. Override del conductor

Cuando el conductor agarra el volante, el sistema adapta los limites:

```python
# car/__init__.py
driver_max_torque = STEER_MAX + (STEER_DRIVER_ALLOWANCE + driver_torque * STEER_DRIVER_FACTOR) * STEER_DRIVER_MULTIPLIER
```

### Ejemplo con Hyundai (STEER_MAX=384, ALLOWANCE=50, FACTOR=1, MULTIPLIER=2):

| Torque del conductor | Limite max del sistema | Efecto |
|---------------------|----------------------|--------|
| 0 (no toca)         | 384 + (50+0)*2 = 484 | Sistema funciona normal |
| 50 (empuja suave)   | 384 + (50+50)*2 = 584| Mas margen para el sistema |
| -100 (opone)        | 384 + (50-100)*2 = 284| Reduce fuerza del sistema |
| -200 (opone fuerte) | 384 + (50-200)*2 = 84 | Sistema casi desactivado |

Ademas, si el torque del conductor supera `STEER_THRESHOLD` (150), el sistema detecta
"steeringPressed" y puede soltar el control lateral.

---

## 8. Cambio de carril: maquina de estados

### Los 4 estados

```python
# desire_helper.py:19-20
LaneChangeState = {
    off,                    # Sin cambio de carril
    preLaneChange,          # Esperando condiciones (BSM, timer, torque)
    laneChangeStarting,     # Cambiando de carril (lane lines se desvanecen)
    laneChangeFinishing     # Completando (lane lines vuelven)
}
```

### Diagrama de transiciones

```
                 [intermitente ON + velocidad > 32 km/h]
                              |
        off ──────────────> preLaneChange
         ^                    |
         |                    | [BSM libre + (torque aplicado O timer agotado)]
         |                    v
         |              laneChangeStarting
         |                    |
         |                    | [probabilidad cambio < 2% + lane lines < 1%]
         |                    v
         |              laneChangeFinishing
         |                    |
         |                    | [automatico tras completar]
         └────────────────────┘
```

### Condiciones para cambiar de carril

1. **Velocidad minima**: 20 mph (~32 km/h) - configurable
2. **Intermitente activado**: izquierdo o derecho
3. **BSM libre**: no hay vehiculo en el angulo muerto
4. **Activacion**: torque del conductor en la direccion correcta O timer automatico
5. **Tiempo maximo**: 10 segundos (si no se completa, se cancela)

```python
# desire_helper.py:700-709
LANE_CHANGE_SPEED_MIN = 20 * CV.MPH_TO_MS  # ~8.9 m/s = ~32 km/h
LANE_CHANGE_TIME_MAX = 10.0  # segundos
```

### Que pasa durante el cambio

Cuando el estado es `laneChangeStarting`, la probabilidad de las lineas de carril se reduce
gradualmente para que el coche "ignore" las lineas actuales y siga la trayectoria hacia el
carril nuevo:

```python
# lateral_planner.py:122-125
if self.DH.desire == log.Desire.laneChangeRight or self.DH.desire == log.Desire.laneChangeLeft:
    self.LP.lll_prob *= self.DH.lane_change_ll_prob   # Se va a 0 gradualmente
    self.LP.rll_prob *= self.DH.lane_change_ll_prob
```

```python
# desire_helper.py:778-783
self.lane_change_ll_prob = max(self.lane_change_ll_prob - 2 * DT_MDL, 0.0)

# Cuando las lineas estan casi a 0 y el modelo dice que ya se completo:
if lane_change_prob < 0.02 and self.lane_change_ll_prob < 0.01:
    self.lane_change_state = LaneChangeState.laneChangeFinishing
```

---

## 9. El sistema Desire

"Desire" es la intencion que se le pasa al modelo de IA. Mapea el estado del cambio de
carril a lo que el modelo debe hacer:

```python
# desire_helper.py:25-44
DESIRES = {
    LaneChangeDirection.left: {
        LaneChangeState.off: Desire.none,               # No hacer nada
        LaneChangeState.preLaneChange: Desire.none,      # Esperando, no mover
        LaneChangeState.laneChangeStarting: Desire.laneChangeLeft,   # GIRAR IZQUIERDA
        LaneChangeState.laneChangeFinishing: Desire.laneChangeLeft,  # SEGUIR GIRANDO
    },
    LaneChangeDirection.right: {
        LaneChangeState.off: Desire.none,
        LaneChangeState.preLaneChange: Desire.none,
        LaneChangeState.laneChangeStarting: Desire.laneChangeRight,  # GIRAR DERECHA
        LaneChangeState.laneChangeFinishing: Desire.laneChangeRight, # SEGUIR GIRANDO
    },
}
```

El flujo completo:
1. **Input** → intermitente del coche (`carState.leftBlinker`)
2. **DesireHelper** → evalua estado, BSM, velocidad → produce `Desire.laneChangeLeft`
3. **Lateral Planner** → usa el Desire para ajustar el path y reducir confianza en lineas
4. **MPC** → calcula curvatura optima para la trayectoria nueva
5. **Controlador lateral** → convierte curvatura a torque
6. **Volante gira** → el coche cambia de carril

---

## 10. ForceLaneChange de ORBIT

Nuestro sistema permite forzar cambios de carril desde la app sin tocar el intermitente:

```python
# desire_helper.py:182-279
def check_and_force_lane_change_param(self, carstate):
    # Requisito: toggle c_carril activado
    if not self.param_s.get_bool("c_carril"):
        return

    # Leer BSM
    left_bsm = self._get_blindspot(carstate, LaneChangeDirection.left)
    right_bsm = self._get_blindspot(carstate, LaneChangeDirection.right)

    # Si ForceLaneChangeLeft activado por MQTT:
    if self.param_s.get_bool("ForceLaneChangeLeft"):
        self.param_s.put_bool("ForceLaneChangeLeft", False)  # Consumir el comando

        if left_bsm:
            # BSM ocupado → esperar
            self.waiting_bsm_left = True
            self.param_s.put("bsmLaneChangeStatus", "CARRIL_OCUPADO_IZQ")
        else:
            # BSM libre → cambiar ya
            self.param_s.put("bsmLaneChangeStatus", "CARRIL_LIBRE_IZQ")
            self.lane_change_direction = LaneChangeDirection.left
            self.lane_change_state = LaneChangeState.laneChangeStarting
```

### Flujo desde la app:

```
App ORBIT → MQTT: telemetry_config/{dongle_id}/left
    → mqtt_comandos.py: put_bool("ForceLaneChangeLeft", True)
    → desire_helper.py: check_and_force_lane_change_param()
        → Verifica BSM
        → Si libre: activa laneChangeStarting
        → Si ocupado: espera a que se libere
    → lateral_planner.py: genera trayectoria al carril izquierdo
    → El coche cambia de carril
```

### Params involucrados:

| Param | Tipo | Funcion |
|-------|------|---------|
| `c_carril` | bool | Toggle de seguridad (debe estar ON) |
| `ForceLaneChangeLeft` | bool | Comando de cambio izquierda (se autoconsume) |
| `ForceLaneChangeRight` | bool | Comando de cambio derecha (se autoconsume) |
| `bsmLaneChangeStatus` | string | Estado para la app: REVISANDO_BSM_IZQ, CARRIL_OCUPADO_IZQ, CARRIL_LIBRE_IZQ, etc. |

---

## 11. Steering Pulse de ORBIT

Para giros temporales rapidos (sin cambio de carril), tenemos el sistema de "pulso":

```python
# orbit_steering_pulse.py
orbit_steering_pulse_angle = 3.0          # grados de giro
orbit_steering_pulse_initial_duration = 0.5  # 0.5s girando
orbit_steering_pulse_return_duration = 0.5   # 0.5s volviendo
# Total: 1 segundo
```

### Fases del pulso:

```
Fase 1 (0.0s - 0.5s): "initial"
    → Gira 3 grados en la direccion pedida
    → Ajusta curvatura +/- 0.008

Fase 2 (0.5s - 1.0s): "return"
    → Gira 3 grados en la direccion OPUESTA (vuelve)
    → Ajusta curvatura en sentido contrario

Despues de 1.0s: se desactiva automaticamente
```

### Aplicacion en controlsd.py (lineas 865-903):

```python
if is_active and effective_direction in ["right", "left"] and CC.latActive:
    if effective_direction == "right":
        actuators.steeringAngleDeg += 3.0     # +3 grados
        self.desired_curvature += 0.008       # ajuste de curvatura
    elif effective_direction == "left":
        actuators.steeringAngleDeg -= 3.0     # -3 grados
        self.desired_curvature -= 0.008
```

**Importante**: Este pulso se suma DIRECTAMENTE al output del controlador lateral. No pasa
por el sistema de Desire ni por el planificador. Es un offset crudo sobre el torque/angulo
calculado.

---

## 12. BSM (Blind Spot Monitoring)

El sistema de angulo muerto se integra en todos los cambios de carril:

```python
# desire_helper.py:151-181
def _has_bsm(self, carstate):
    """Comprueba si el coche tiene sensores BSM."""
    try:
        _ = carstate.leftBlindspot
        _ = carstate.rightBlindspot
        return True
    except AttributeError:
        return False

def _get_blindspot(self, carstate, direction):
    """Obtiene estado del angulo muerto."""
    if direction == LaneChangeDirection.left:
        return getattr(carstate, 'leftBlindspot', False)
    elif direction == LaneChangeDirection.right:
        return getattr(carstate, 'rightBlindspot', False)
    return False
```

### Comportamiento en cambio de carril normal (con intermitente):

```python
# desire_helper.py:726-775
# En estado preLaneChange:
blindspot_detected = (
    (left_bsm and direction == left) or
    (right_bsm and direction == right)
)

if blindspot_detected:
    # BLOQUEAR cambio de carril
    # Resetear timer parcialmente (dejar 0.3s de margen cuando se libere)
    self.lane_change_wait_timer = min(timer, max(0, auto_timer - 0.3))
```

### Comportamiento en ForceLaneChange (ORBIT):

Si BSM ocupado → entra en modo "waiting" → cuando BSM se libera → ejecuta el cambio
automaticamente. El estado se reporta a la app via `bsmLaneChangeStatus`.

---

## 13. Envio al CAN bus

### Hyundai Legacy (CAN clasico)

```python
# hyundaican.py:6-99
def create_lkas11(packer, frame, CP, apply_steer, steer_req, ...):
    values = {
        "CR_Lkas_StrToqReq": apply_steer,   # Torque: -384 a +384
        "CF_Lkas_ActToi": steer_req,         # 1=activo, 0=inactivo
        "CF_Lkas_ToiFlt": torque_fault,      # Workaround para EPS
        "CF_Lkas_MsgCount": frame % 0x10,    # Contador
    }
    # Checksum segun modelo (CRC8, suma 6B, suma 7B)
    return packer.make_can_msg("LKAS11", 0, values)
```

### Hyundai CAN-FD (coches nuevos)

```python
# hyundaicanfd.py:38-62
def create_steering_messages(packer, CP, CAN, enabled, lat_active, apply_steer, ...):
    values = {
        "TORQUE_REQUEST": apply_steer,       # Torque: -270 a +270
        "STEER_REQ": 1 if lat_active else 0,
        "LKA_ICON": 2 if lat_active else ...,
    }
    # HDA2: mensaje LKAS en ACAN
    # Otros: mensaje LFA en ECAN
```

### Proteccion contra fallo del EPS

```python
# car/__init__.py:170-191
def common_fault_avoidance(fault_condition, request, above_limit_frames, ...):
    # Si el angulo de volante > 85 grados durante >89 frames:
    # → Cortar request bit para evitar fallo del EPS
    if above_limit_frames > max_above_limit_frames:
        request = False  # Soltar brevemente para resetear
```

---

## 14. Tabla resumen

### Parametros de torque por marca

| Parametro        | Hyundai std | Hyundai CAN-FD | Toyota | GM   |
|------------------|------------|----------------|--------|------|
| STEER_MAX        | 384        | 270            | 1500   | 300  |
| STEER_DELTA_UP   | 3          | 2              | 10-15  | 10   |
| STEER_DELTA_DOWN | 7          | 3              | 25     | 15   |
| Tiempo al max    | 1.28s      | 1.35s          | 1.0s   | 0.3s |
| Frecuencia       | 100 Hz     | 100 Hz         | 100 Hz | 33 Hz|

### Resumen del sistema de giro

| Concepto | Valor/Formula |
|----------|---------------|
| Formula clave | `lateral_accel = curvatura × velocidad^2` |
| Torque normalizado | `[-1.0, 1.0]` → se escala a `[-STEER_MAX, +STEER_MAX]` |
| Velocidad min cambio carril | 32 km/h (configurable) |
| Tiempo max cambio carril | 10 segundos |
| Steering pulse angle | 3 grados, 1 segundo total |
| Steering pulse curvature | +/- 0.008 |

---

## 15. Archivos clave

| Archivo | Que hace |
|---------|----------|
| `selfdrive/controls/controlsd.py` | Loop principal de control (100 Hz) |
| `selfdrive/controls/lib/lateral_planner.py` | Planifica trayectoria lateral con MPC |
| `selfdrive/controls/lib/latcontrol_torque.py` | Convierte curvatura deseada → torque |
| `selfdrive/controls/lib/pid.py` | Controlador PID generico |
| `selfdrive/controls/lib/vehicle_model.py` | Modelo del vehiculo (curvatura ↔ angulo) |
| `selfdrive/controls/lib/desire_helper.py` | Maquina de estados de cambio de carril |
| `selfdrive/car/__init__.py` | Limites de torque y rate limiting genericos |
| `selfdrive/car/interfaces.py` | Conversion aceleracion lateral → torque |
| `selfdrive/car/hyundai/values.py` | Constantes especificas Hyundai/Kia |
| `selfdrive/car/hyundai/carcontroller.py` | Controlador de coche Hyundai |
| `selfdrive/car/hyundai/hyundaican.py` | Mensajes CAN para Hyundai Legacy |
| `selfdrive/car/hyundai/hyundaicanfd.py` | Mensajes CAN para Hyundai CAN-FD |
| `orbit/orbit_steering_pulse.py` | Sistema de pulso de giro ORBIT |
| `orbit/mqtt_comandos.py` | Comandos MQTT (lane change, control, etc) |
