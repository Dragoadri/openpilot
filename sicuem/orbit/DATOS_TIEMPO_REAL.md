# Datos de Tiempo Real Expandidos en Orbit

## Resumen de Mejoras

Se ha expandido significativamente la cantidad de datos de telemetría que se envían en tiempo real desde orbit, incluyendo muchos más campos específicos y útiles para monitoreo en tiempo real.

## Datos Expandidos por Canal

### 1. carControl - Control del Vehículo

#### Datos de Actuators (actuators_*)
- `actuators_gas`: Posición del pedal de gas (0.0 - 1.0)
- `actuators_brake`: Posición del pedal de freno (0.0 - 1.0)
- `actuators_steer`: Ángulo de dirección del actuador
- `actuators_steeringAngleDeg`: Ángulo de dirección en grados
- `actuators_accel`: Aceleración del vehículo
- `actuators_longControlState`: Estado del control longitudinal ('pid', 'stopping', etc.)
- `actuators_speed`: Velocidad del vehículo
- `actuators_curvature`: Curvatura de la carretera
- `actuators_steerOutputCan`: Salida de dirección al CAN

#### Datos de HUD Control (hud_*)
- `hud_speedVisible`: Si la velocidad es visible en el HUD
- `hud_setSpeed`: Velocidad establecida por el usuario
- `hud_lanesVisible`: Si las líneas de carril son visibles
- `hud_leadVisible`: Si el vehículo líder es visible
- `hud_visualAlert`: Tipo de alerta visual ('none', 'steerRequired', etc.)
- `hud_audibleAlert`: Tipo de alerta audible ('none', 'chimeDisengage', etc.)
- `hud_rightLaneVisible`: Si el carril derecho es visible
- `hud_leftLaneVisible`: Si el carril izquierdo es visible
- `hud_rightLaneDepart`: Si está saliendo del carril derecho
- `hud_leftLaneDepart`: Si está saliendo del carril izquierdo
- `hud_leadDistanceBars`: Barras de distancia al vehículo líder

### 2. carState - Estado del Vehículo

#### Datos de Cruise State (cruise_*)
- `cruise_enabled`: Si el control de crucero está habilitado
- `cruise_speed`: Velocidad de crucero establecida
- `cruise_available`: Si el control de crucero está disponible
- `cruise_speedOffset`: Offset de velocidad
- `cruise_standstill`: Si el vehículo está parado
- `cruise_nonAdaptive`: Si el control no es adaptativo
- `cruise_speedCluster`: Velocidad mostrada en el cluster
- `cruise_speedLimit`: Límite de velocidad detectado

#### Datos Básicos del Vehículo
- `aEgo`: Aceleración del vehículo
- `vEgo`: Velocidad del vehículo
- `vEgoCluster`: Velocidad mostrada en el cluster
- `leftBlinker`, `rightBlinker`: Estado de intermitentes
- `leftBlindspot`, `rightBlindspot`: Estado de puntos ciegos
- `standstill`: Si el vehículo está parado
- `steeringAngleDeg`: Ángulo de dirección
- `steeringPressed`, `gasPressed`, `brakePressed`: Estado de pedales
- `canValid`: Validez del CAN
- `gearShifter`: Posición de la palanca de cambios
- `engineRpm`: RPM del motor
- `steeringTorque`: Par de dirección
- `steeringTorqueEps`: Par de dirección del EPS

### 3. radarState - Estado del Radar

#### Datos del Vehículo Líder 1 (lead1_*)
- `lead1_dRel`: Distancia relativa al vehículo líder
- `lead1_yRel`: Posición lateral relativa
- `lead1_vRel`: Velocidad relativa
- `lead1_aRel`: Aceleración relativa
- `lead1_vLead`: Velocidad del vehículo líder
- `lead1_dPath`: Distancia al camino
- `lead1_vLat`: Velocidad lateral
- `lead1_vLeadK`: Velocidad del líder filtrada
- `lead1_aLeadK`: Aceleración del líder filtrada
- `lead1_fcw`: Alerta de colisión frontal
- `lead1_status`: Estado del vehículo líder
- `lead1_aLeadTau`: Tiempo de aceleración del líder
- `lead1_modelProb`: Probabilidad del modelo
- `lead1_radar`: Si es detectado por radar
- `lead1_radarTrackId`: ID de seguimiento del radar

#### Datos del Vehículo Líder 2 (lead2_*)
- Mismos campos que lead1 pero para el segundo vehículo detectado

### 4. drivingModelData - Datos del Modelo de Conducción

#### Datos de Líneas de Carril (lane_*)
- `lane_leftY`: Posición Y de la línea izquierda
- `lane_rightY`: Posición Y de la línea derecha
- `lane_leftProb`: Probabilidad de la línea izquierda
- `lane_rightProb`: Probabilidad de la línea derecha

### 5. controlsState - Estado de Controles

#### Datos de Alertas
- `alertText1`, `alertText2`: Textos de alerta
- `alertStatus`: Estado de la alerta ('normal', 'userPrompt', etc.)
- `alertSize`: Tamaño de la alerta ('none', 'mid', 'full')
- `alertType`: Tipo de alerta
- `alertSound`: Sonido de la alerta
- `alertCritical`: Si la alerta es crítica
- `alertUserPrompt`: Si requiere intervención del usuario

#### Datos de Control
- `active`: Si el control está activo
- `vCruise`, `vCruiseCluster`: Velocidades de crucero
- `vEgo`, `vEgoCluster`: Velocidades del vehículo
- `aEgo`: Aceleración del vehículo
- `steeringAngleDeg`: Ángulo de dirección
- `steeringPressed`, `gasPressed`, `brakePressed`: Estado de controles
- `canValid`: Validez del CAN
- `gearShifter`: Posición de cambios
- `engineRpm`: RPM del motor
- `steeringTorque`, `steeringTorqueEps`: Par de dirección

### 6. liveCalibration - Calibración en Vivo

- `calStatus`: Estado de la calibración ('calibrated', 'uncalibrated', etc.)
- `calPerc`: Porcentaje de calibración (0-100)
- `calValid`: Si la calibración es válida

### 7. gpsLocationExternal - Ubicación GPS Externa

- `latitude`: Latitud GPS
- `longitude`: Longitud GPS
- `altitude`: Altitud GPS

### 8. gpsLocation - Ubicación GPS

- `latitude`: Latitud GPS
- `longitude`: Longitud GPS
- `altitude`: Altitud GPS
- `speed`: Velocidad GPS
- `bearing`: Dirección de movimiento
- `accuracy`: Precisión del GPS
- `timestamp`: Marca de tiempo
- `source`: Fuente de los datos GPS

## Beneficios de los Datos Expandidos

1. **Monitoreo Detallado**: Ahora puedes ver datos específicos como `actuators_curvature`, `hud_lanesVisible`, `cruise_enabled`, etc.

2. **Datos de Vehículos Líderes**: Información detallada de hasta 2 vehículos detectados por el radar.

3. **Estado de Líneas de Carril**: Probabilidades y posiciones de las líneas de carril detectadas.

4. **Alertas y Controles**: Estado detallado de alertas y controles del vehículo.

5. **Calibración**: Estado de la calibración del sistema en tiempo real.

## Formato de Datos

Los datos se envían con el formato:
```json
{
  "dongle_id": "ID_DEL_DISPOSITIVO",
  "actuators_gas": 0.0,
  "actuators_brake": 0.0,
  "actuators_steer": 0.12866191565990448,
  "hud_setSpeed": 11.11111068725586,
  "hud_lanesVisible": true,
  "cruise_enabled": true,
  "lead1_dRel": 0.0,
  "lead1_vRel": 0.0,
  "lane_leftProb": 0.9726606607437134,
  "lane_rightProb": 0.983817994594574,
  ...
}
```

## Uso Recomendado

Estos datos son ideales para:
- Monitoreo en tiempo real del estado del vehículo
- Análisis de comportamiento de conducción
- Detección de anomalías
- Desarrollo de algoritmos de control
- Visualización de datos de telemetría

















