# Expansión de Datos de Telemetría en Orbit

## Resumen de Cambios

Se ha expandido significativamente la cantidad de datos de telemetría que se envían desde orbit al servidor, incorporando muchos de los datos que se envían en `sicmqtthilo2.py`.

## Canales Agregados

### 1. controlsState
- **Topic**: `telemetry_mqtt/{dongle_id}/controlsState`
- **Descripción**: Estado de controles del vehículo
- **Datos incluidos**:
  - `active`: Estado activo del control
  - `alertText1`, `alertText2`: Textos de alerta
  - `alertStatus`, `alertSize`, `alertType`: Estado y tipo de alertas
  - `alertSound`, `alertCritical`, `alertUserPrompt`: Configuración de alertas
  - `vCruise`, `vCruiseCluster`: Velocidad de crucero
  - `vEgo`, `vEgoCluster`: Velocidad del vehículo
  - `aEgo`: Aceleración del vehículo
  - `steeringAngleDeg`: Ángulo de dirección
  - `steeringPressed`, `gasPressed`, `brakePressed`: Estado de pedales
  - `canValid`: Validez del CAN
  - `gearShifter`: Posición de la palanca de cambios
  - `engineRpm`: RPM del motor
  - `steeringTorque`, `steeringTorqueEps`: Par de dirección

### 2. liveCalibration
- **Topic**: `telemetry_mqtt/{dongle_id}/liveCalibration`
- **Descripción**: Calibración en vivo del sistema
- **Datos incluidos**:
  - `calStatus`: Estado de la calibración
  - `calPerc`: Porcentaje de calibración
  - `calValid`: Validez de la calibración

### 3. gpsLocation
- **Topic**: `telemetry_mqtt/{dongle_id}/gpsLocation`
- **Descripción**: Ubicación GPS del vehículo
- **Datos incluidos**:
  - `latitude`, `longitude`, `altitude`: Coordenadas GPS
  - `speed`: Velocidad GPS
  - `bearing`: Dirección de movimiento
  - `accuracy`: Precisión del GPS
  - `timestamp`: Marca de tiempo
  - `source`: Fuente de los datos GPS

## Canales Expandidos

### 1. carState (Expandido)
Se agregaron muchos más datos de telemetría:
- `vCruise`, `vCruiseCluster`: Velocidades de crucero
- `standstill`: Estado de parada
- `steeringAngleDeg`: Ángulo de dirección
- `steeringPressed`, `gasPressed`, `brakePressed`: Estado de controles
- `canValid`: Validez del CAN
- `gearShifter`: Posición de cambios
- `engineRpm`: RPM del motor
- `steeringTorque`, `steeringTorqueEps`: Par de dirección

### 2. carControl (Expandido)
Se agregaron datos de control adicionales:
- `cruiseControl`: Control de crucero
- `lateralControlState`: Estado del control lateral
- `longitudinalControlState`: Estado del control longitudinal
- Múltiples campos de alertas y notificaciones

### 3. radarState (Expandido)
Se agregaron datos de todos los vehículos detectados:
- `leadOne` a `leadHundred`: Datos de hasta 100 vehículos detectados
- Información de distancia, velocidad relativa y aceleración para cada vehículo

### 4. drivingModelData (Expandido)
Se agregaron datos del modelo de conducción:
- `laneLines`: Líneas de carril detectadas
- `laneLineProbs`: Probabilidades de líneas de carril
- `roadEdges`: Bordes de la carretera
- `roadEdgeStds`: Desviaciones estándar de bordes
- `laneLinesStds`: Desviaciones estándar de líneas
- `laneLineProbsStds`: Desviaciones estándar de probabilidades

## Cambios en el Código

### mqtt_envio_general.py
1. **SubMaster expandido**: Ahora incluye los canales adicionales `controlsState`, `liveCalibration`, y `gpsLocation`
2. **Loop mejorado**: Envía datos de canales adicionales incluso si no están en la configuración de canales habilitados
3. **Manejo de claves por defecto**: Si un canal no tiene claves definidas, usa claves por defecto apropiadas

## Beneficios

1. **Mayor visibilidad**: Se envían muchos más datos de telemetría al servidor
2. **Compatibilidad**: Mantiene compatibilidad con el sistema existente
3. **Flexibilidad**: Los canales adicionales se envían automáticamente
4. **Robustez**: Manejo de errores mejorado para canales no configurados

## Uso

El sistema ahora enviará automáticamente todos estos datos adicionales al servidor MQTT configurado en `config_mqtt.json`. Los datos se envían con el formato:

```json
{
  "dongle_id": "ID_DEL_DISPOSITIVO",
  "campo1": "valor1",
  "campo2": "valor2",
  ...
}
```

## Notas Técnicas

- Los datos se envían solo cuando están disponibles y actualizados
- El sistema maneja automáticamente la reconexión MQTT
- Los datos se filtran para incluir solo las claves importantes definidas
- El sistema es compatible con la configuración existente

















