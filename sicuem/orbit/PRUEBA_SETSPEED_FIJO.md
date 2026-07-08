# Prueba de SetSpeed Fijo a 34 km/h

## Descripción

Esta es una modificación de prueba para forzar el `setSpeed` del vehículo a **34 km/h** de forma permanente, independientemente de los controles del usuario. El objetivo es verificar que podemos controlar el setSpeed a nuestro antojo.

## Modificación Realizada

### Archivo Modificado
**`/home/drago/Escritorio/OPENPILOTSIC/openpilot/selfdrive/controls/controlsd.py`**

### Líneas Modificadas
**Líneas 856-859**: Se agregó código para forzar el setSpeed a 34 km/h

```python
# 🧪 PRUEBA: Forzar setSpeed a 34 km/h SIEMPRE
velocidad_fija_kmh = 34.0
self.v_cruise_helper.v_cruise_kph = velocidad_fija_kmh
print(f"🔧 PRUEBA: Forzando setSpeed a {velocidad_fija_kmh} km/h")
```

## Cómo Funciona

1. **Se ejecuta en cada ciclo de control** (aproximadamente cada 20ms)
2. **Sobrescribe cualquier valor** que el usuario haya establecido
3. **Se aplica tanto al control como al HUD** del vehículo
4. **Se imprime en los logs** para verificar que está funcionando

## Flujo de Ejecución

```
Usuario presiona botones de velocidad
         ↓
Sistema calcula nueva velocidad
         ↓
🧪 NUESTRO CÓDIGO: Fuerza a 34 km/h
         ↓
Se aplica al v_cruise_helper.v_cruise_kph
         ↓
Se establece en hudControl.setSpeed
         ↓
Se envía al vehículo
```

## Verificación

### 1. Ejecutar OpenPilot
```bash
# En el directorio de openpilot
cd /home/drago/Escritorio/OPENPILOTSIC/openpilot
./launch_openpilot.sh
```

### 2. Verificar en Logs
Buscar en los logs el mensaje:
```
🔧 PRUEBA: Forzando setSpeed a 34.0 km/h
```

### 3. Probar con MQTT
```bash
cd /home/drago/Escritorio/OPENPILOTSIC/openpilot/sicuem/orbit
python test_setspeed_fijo.py
```

### 4. Verificar en el HUD
- El HUD del vehículo debería mostrar **34 km/h** como velocidad de crucero
- No debería cambiar aunque el usuario presione los botones de velocidad

## Topics MQTT para Verificar

### 1. CarControl
- **Topic**: `telemetry_mqtt/{DongleID}/carControl`
- **Campo**: `hudControl.setSpeed`
- **Valor esperado**: `9.44` m/s (34 km/h)

### 2. ControlsState
- **Topic**: `telemetry_mqtt/{DongleID}/controlsState`
- **Campo**: `vCruise`
- **Valor esperado**: `34.0` km/h

### 3. Resumen Principal
- **Topic**: `telemetry_mqtt/{DongleID}/resumen_principal`
- **Campo**: `control.setSpeed_kmh`
- **Valor esperado**: `34.0` km/h

## Conversiones

- **34 km/h = 9.44 m/s**
- **Fórmula**: `km/h * 1000 / 3600 = m/s`
- **Fórmula**: `m/s * 3.6 = km/h`

## Comportamiento Esperado

### ✅ Lo que DEBERÍA pasar:
1. El HUD siempre muestra 34 km/h
2. Los botones de velocidad no funcionan
3. El vehículo intenta mantener 34 km/h
4. Los logs muestran el mensaje de prueba
5. MQTT envía 34 km/h constantemente

### ❌ Lo que NO debería pasar:
1. El HUD cambia cuando presionas botones
2. El setSpeed es diferente a 34 km/h
3. No aparecen mensajes en los logs
4. MQTT envía valores diferentes

## Revertir la Modificación

Para volver al comportamiento normal, simplemente elimina o comenta las líneas 856-859:

```python
# Comentar estas líneas:
# # 🧪 PRUEBA: Forzar setSpeed a 34 km/h SIEMPRE
# velocidad_fija_kmh = 34.0
# self.v_cruise_helper.v_cruise_kph = velocidad_fija_kmh
# print(f"🔧 PRUEBA: Forzando setSpeed a {velocidad_fija_kmh} km/h")
```

## Próximos Pasos

Una vez que confirmemos que funciona:

1. **Cambiar la velocidad** modificando `velocidad_fija_kmh = 34.0`
2. **Hacerlo dinámico** leyendo desde un parámetro
3. **Controlarlo por MQTT** para cambiar la velocidad remotamente
4. **Integrarlo con Orbit** para control total

## Troubleshooting

### El setSpeed no cambia a 34 km/h
1. Verificar que el archivo se guardó correctamente
2. Reiniciar OpenPilot completamente
3. Verificar que no hay errores en los logs
4. Confirmar que el sistema está habilitado

### No aparecen mensajes en los logs
1. Verificar que el archivo se modificó correctamente
2. Buscar en todos los logs, no solo en la consola
3. Verificar que el sistema está en modo de control

### MQTT no muestra 34 km/h
1. Verificar que Orbit está ejecutándose
2. Confirmar la conexión MQTT
3. Verificar que los topics están configurados correctamente

## Notas Importantes

- ⚠️ **Esta es una modificación de PRUEBA**
- ⚠️ **No usar en carretera sin supervisión**
- ⚠️ **El vehículo intentará mantener 34 km/h constantemente**
- ⚠️ **Los controles del usuario no funcionarán**

## Archivos Relacionados

- **Modificado**: `selfdrive/controls/controlsd.py`
- **Prueba**: `sicuem/orbit/test_setspeed_fijo.py`
- **Documentación**: `sicuem/orbit/PRUEBA_SETSPEED_FIJO.md`





