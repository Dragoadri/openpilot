# commIssue / locationdTemporaryError cada ~1 s al activar OP — causa raíz y fixes

**Fecha:** 2026-07-02 · **Rama:** `sicuem-mig` · **Device:** comma 3X
**Evidencia:** rlog `b25afc8f8295c6b3_00000013--4cf886df6f--0` (decodificado con
`rlog_a_json.py` / analizadores ad-hoc).

## Síntoma

Al conducir (sobre todo con OP activado): "TAKE CONTROL IMMEDIATELY —
Communication issue between processes" cada ~1 s, alternando a ratos con
"locationd temporary error". NO lo arreglaron ni el throttle de telemetría en
controlsd ni `sched_rt_runtime_us=-1` (ambos cambios siguen siendo buenos, pero
atacaban otra cosa).

## Qué mostró el rlog (lo importante)

- **Ningún proceso se atasca**: todos los servicios publican a su frecuencia
  exacta, sin huecos (carState 100 Hz, modelV2/livePose/cameraOdometry 20 Hz…).
- Sin embargo `radarState, longitudinalPlan, driverAssistance, liveParameters,
  driverMonitoringState, liveDelay, liveTorqueParameters, liveCalibration` se
  publican con **`valid=False` durante EXACTAMENTE 1 mensaje**, en una "ola"
  que recorre todos los daemons, con **período 1.0008 s** y fase que deriva
  ~+0.8 ms/s (→ es un bucle userspace con `sleep(1)`, no un timer del kernel).
- Todos esos daemons publican `valid = sm.all_checks()` y **su único input
  común es `carState`**: lo que parpadea es el chequeo alive/freq de carState
  *en el lado receptor* de cada daemon.
- `modelDataV2SP` va `valid=False` el 100 % del tiempo (su publisher no marca
  valid): está en la lista `ignore` de selfdrived, es solo ruido en los logs.
- `gpsLocation` publica a 0.13 Hz (declarado 1 Hz): también ignorado por
  selfdrived (`gps_packets`), inerte para esta alerta.

## Causa raíz

`msgq` limita cada canal a **`NUM_READERS = 15` suscriptores**. Cuando un 16º
intenta registrarse, `msgq_init_subscriber()` (msgq/msgq.cc) ejecuta el bloque
*"No more slots available. Reset all subscribers to kick out inactive ones"*:
**expulsa a TODOS los lectores del canal** (`read_valids=false`,
`read_uids=0`). Cada víctima se re-registra en su siguiente lectura pero
**pierde su cola pendiente** → ese ciclo su SubMaster ve carState "no alive" →
publica su salida con `valid=False` → selfdrived ve `all_checks()=False` →
`commIssue` (y si le toca a locationd: `livePose.inputsOK=False` →
`locationdTemporaryError`).

Con **≥16 suscriptores vivos el ciclo es perpetuo**: tras cada expulsión los
daemons rápidos se re-registran en ms, y el más lento — el hilo de telemetría
MQTT (`MQTTEnvioGeneral.loop()`, `sm.update()` + `time.sleep(1)` ⇒ período
1.0008 s) — se re-registra ~1 s después, vuelve a desbordar el límite y
dispara la siguiente expulsión. De ahí el período y la deriva observados.

Suscriptores vivos de `carState` en esta rama (contados en código): selfdrived,
controlsd, plannerd (poll), radard, paramsd, torqued, lagd, calibrationd,
locationd, dmonitoringd, modeld, loggerd, ui, feedbackd, telemetría MQTT SICUEM
= **15**, más **mapd** si está instalado (el rlog muestra `locationd_llk`
arrancando, señal de que el ecosistema mapd está activo) = **16 → tormenta**.
El sunnypilot stock vive justo en 15; nuestra telemetría (+1) lo desborda.

## Fixes aplicados en esta rama

1. **`selfdrive/ui/feedback/feedbackd.py`**: quitadas las suscripciones a
   `carState` y `selfdriveStateSP` (solo las usaba un bloque `if False` —
   código muerto upstream). carState pasa de 16 a ≤15 suscriptores → se corta
   el ciclo perpetuo. Cero pérdida de funcionalidad.
2. **Toggle UEM "SILENCIAR ALERTAS DE COMUNICACION"** (param
   `silenciar_alertas_comm`, menú UEM): con él activado, selfdrived deja de
   añadir `commIssue`, `commIssueAvgFreq`, `locationdTemporaryError` y
   `paramsdTemporaryError`. Los `cloudlog.event("commIssue", ...)` se siguen
   emitiendo para poder diagnosticar. El resto de alertas de seguridad
   (cámaras, CAN, sensores, procesos caídos…) NO se tocan. Se refresca cada
   ~3 s, no hace falta reiniciar la ruta.

## Verificación en el device (5 min, sin rebuild)

```bash
# con el coche encendido y openpilot corriendo:
cd /data/openpilot
python3 tools/orbit/diag_msgq_readers.py --service carState --dur 30
```

- Si imprime `EVICT-ALL` cada ~1.000-1.001 s → mecanismo confirmado; el
  "primer registro tras evict" nombra al proceso que desborda.
- Tras desplegar el fix de feedbackd: repetir → 0 expulsiones (o slots llenos
  pero estables). En el coche: sin commIssue al activar OP.

## Fix definitivo (opcional, recomendado a medio plazo)

Subir el límite: `tools/orbit/msgq_num_readers.patch` (NUM_READERS 15→31 en
`msgq_repo/msgq/msgq.h`). Requiere rebuild completo + **reboot** (cambia el
layout de las colas en /dev/shm). Al ser un submódulo, para hacerlo permanente
hay que hacer fork de `commaai/msgq` y apuntar `.gitmodules` al fork. Detalles
en la cabecera del patch.

## Reglas para no volver a romperlo

- Cada `SubMaster([...])` / `sub_sock()` NUEVO sobre un canal caliente
  (carState, carControl, controlsState, liveCalibration, modelV2…) gasta un
  slot de los 15. Antes de añadir telemetría/overlays que suscriban esos
  canales, contar suscriptores (o correr `diag_msgq_readers.py`).
- NUNCA crear SubMaster/sub_sock dentro de un bucle (cada creación registra un
  suscriptor nuevo; los slots no se liberan al morir el proceso hasta la
  siguiente expulsión).
- Si no se usan mapas (SLC), quitar el binario mapd (`/data/media/0/osm/...`,
  ver `mapd_ready()` en process_config.py) libera otro slot de carState.
