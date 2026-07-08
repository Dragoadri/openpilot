# Sistema de Cambio de Carril por MQTT en Orbit

## Resumen

Se ha implementado un sistema completo de cambio de carril controlado remotamente desde la app a través de MQTT. El sistema permite cambiar de carril a izquierda o derecha enviando comandos desde el servidor.

## Arquitectura del Sistema

### 1. **Flujo de Comandos**
```
App → Servidor Flask → MQTT Broker → Orbit → Params → DesireHelper → Ejecución
```

### 2. **Componentes Implementados**

#### **mqtt_comandos.py**
- **Función**: Recibe comandos MQTT del servidor
- **Topics suscritos**:
  - `telemetry_config/{dongle_id}/left` - Cambio a la izquierda
  - `telemetry_config/{dongle_id}/right` - Cambio a la derecha
  - `telemetry_config/{dongle_id}/intervalos` - Control de intervalos
- **Funcionalidad**:
  - Procesa comandos de cambio de carril
  - Verifica seguridad (toggle `c_carril`)
  - Previene conflictos (no permite ambos cambios simultáneamente)
  - Guarda comandos en Params del sistema

#### **mqtt_envio_general.py** (Modificado)
- **Función**: Integra el sistema de comandos con el envío de telemetría
- **Nuevas características**:
  - Inicializa automáticamente el sistema de comandos
  - Maneja la conexión MQTT para comandos
  - Proporciona métodos de inicio y parada

#### **desire_helper.py** (Ya existente)
- **Función**: Ejecuta los cambios de carril basándose en los Params
- **Método clave**: `check_and_force_lane_change_param()`
- **Funcionalidad**:
  - Lee `ForceLaneChangeLeft` y `ForceLaneChangeRight` de Params
  - Verifica condiciones de seguridad (blindspot)
  - Ejecuta el cambio de carril cuando es seguro

## Comandos MQTT

### **Cambio a la Izquierda**
- **Topic**: `telemetry_config/{dongle_id}/left`
- **Payload**: `"true"` para activar, `"false"` para cancelar
- **Efecto**: Establece `ForceLaneChangeLeft = True` en Params

### **Cambio a la Derecha**
- **Topic**: `telemetry_config/{dongle_id}/right`
- **Payload**: `"true"` para activar, `"false"` para cancelar
- **Efecto**: Establece `ForceLaneChangeRight = True` en Params

### **Control de Intervalos**
- **Topic**: `telemetry_config/{dongle_id}/intervalos`
- **Payload**: `"true"` para activar, `"false"` para desactivar
- **Efecto**: Controla el toggle de intervalos

## Seguridad y Validaciones

### **1. Toggle de Seguridad**
- **Parámetro**: `c_carril`
- **Función**: Debe estar activado para permitir cambios de carril
- **Comportamiento**: Si está desactivado, todos los comandos se rechazan

### **2. Prevención de Conflictos**
- **Lógica**: No permite cambios simultáneos a izquierda y derecha
- **Comportamiento**: Si hay un cambio activo, cancela ambos al recibir el opuesto

### **3. Verificación de Blindspot**
- **Función**: Verifica que no haya vehículos en el punto ciego
- **Comportamiento**: Bloquea el cambio si detecta vehículos en el carril objetivo

## Estados del Sistema

### **Estados de Cambio de Carril**
1. **off**: Sin cambio de carril activo
2. **preLaneChange**: Preparándose para cambiar
3. **laneChangeStarting**: Iniciando el cambio
4. **laneChangeFinishing**: Finalizando el cambio

### **Estados de Conexión MQTT**
1. **Desconectado**: Sin conexión al broker
2. **Conectando**: Intentando conectar
3. **Conectado**: Listo para recibir comandos
4. **Reconectando**: Perdió conexión, intentando reconectar

## Uso desde la App

### **Enviar Comando de Cambio**
```python
# Desde el servidor Flask
import paho.mqtt.publish as publish

# Cambio a la izquierda
publish.single(
    f"telemetry_config/{dongle_id}/left",
    "true",
    hostname="localhost",
    port=1883
)

# Cambio a la derecha
publish.single(
    f"telemetry_config/{dongle_id}/right",
    "true",
    hostname="localhost",
    port=1883
)

# Cancelar cambios
publish.single(
    f"telemetry_config/{dongle_id}/left",
    "false",
    hostname="localhost",
    port=1883
)
```

### **Verificar Estado**
```python
# Verificar si el cambio está activo
from openpilot.common.params import Params
params = Params()

left_active = params.get_bool("ForceLaneChangeLeft")
right_active = params.get_bool("ForceLaneChangeRight")
safety_toggle = params.get_bool("c_carril")
```

## Logs y Debugging

### **Logs de Comandos**
- `📨 Comando recibido en {topic}: {payload}`
- `✅ Cambio de carril forzado a la IZQUIERDA para {dongle_id}`
- `✅ Cambio de carril forzado a la DERECHA para {dongle_id}`
- `🛑 Cambio de carril bloqueado por toggle c_carril`
- `⚠️ No se puede activar IZQ, ya hay cambio a DERECHA`

### **Logs de Conexión**
- `✅ MQTT Comandos conectado al broker`
- `🔌 MQTT Comandos conectado`
- `📡 Suscrito a comandos para {dongle_id}`
- `🔌 MQTT Comandos desconectado. Reintentando...`

## Configuración

### **Archivo de Configuración**
```json
{
  "broker": "localhost",
  "broker_port": 1883
}
```

### **Parámetros del Sistema**
- `c_carril`: Toggle de seguridad para cambios de carril
- `ForceLaneChangeLeft`: Comando de cambio a la izquierda
- `ForceLaneChangeRight`: Comando de cambio a la derecha
- `intervalos_toggle`: Control de intervalos

## Beneficios

1. **Control Remoto**: Cambio de carril desde la app sin tocar el vehículo
2. **Seguridad**: Múltiples validaciones de seguridad
3. **Robustez**: Reconexión automática y manejo de errores
4. **Integración**: Funciona con el sistema existente de openpilot
5. **Flexibilidad**: Fácil de extender con nuevos comandos

## Troubleshooting

### **El cambio de carril no funciona**
1. Verificar que `c_carril` esté activado
2. Comprobar conexión MQTT
3. Verificar que no haya vehículos en el punto ciego
4. Revisar logs para errores

### **Comandos no llegan**
1. Verificar conexión al broker MQTT
2. Comprobar que el dongle_id sea correcto
3. Verificar que los topics estén bien formados
4. Revisar configuración del broker

### **Cambios se cancelan automáticamente**
1. Verificar que no haya conflictos (izquierda y derecha simultáneos)
2. Comprobar estado del blindspot
3. Verificar que el sistema esté en modo de conducción activo















