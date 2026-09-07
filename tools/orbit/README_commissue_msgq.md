# commIssue permanente / "Communication Issue Between Processes" — causa raíz y fix

**Primera vez:** 2026-07-02 · rama `sicuem-mig` · comma 3X · rlog `b25afc8f8295c6b3_00000013--4cf886df6f--0`
**Recurrencia:** 2026-09-03 · rama `orbit-master` (72fd5c4) · comma 3X · Hyundai Tucson 4ª gen · rutas
`b25afc8f8295c6b3_00000000--13d76952a4` … `00000008--8a7a4e26f1` (logs en `orbit_logs_full_20260907_1241`)
**Fix definitivo:** 2026-09-07 · fork de msgq con `NUM_READERS 31` (ver abajo)

## Síntoma

Al intentar activar OP: "Communication Issue Between Processes: liveCalibration, driverMonitoringState,
longitudinalPlan, livePose". En julio la alerta parpadeaba cada ~1 s; en septiembre OP no se pudo activar
nunca. En ambos casos NO era CPU, ni el modelo (QCOM, 20 Hz), ni procesos caídos, ni térmico.

## Qué muestran los rlogs

- Todos los servicios publican a su frecuencia exacta (carState 100 Hz, modelV2/cameraOdometry 20 Hz).
- `liveCalibration, livePose (inputsOK=false), longitudinalPlan, driverMonitoringState, liveParameters,
  liveDelay, liveTorqueParameters, radarState, driverAssistance` se publican con **`valid=False`**: en julio
  durante 1 mensaje cada segundo; en septiembre el **100 % del tiempo**, desde el primer segundo de cada ruta.
- Todos esos daemons publican `valid = sm.all_checks()` y su único input común es **`carState`**: lo que falla
  es el chequeo alive/freq de carState *en el lado receptor*. Replicando el SubMaster de calibrationd offline
  con el rlog real, `all_checks()` da True el 99,5 %: el fallo es de runtime, no de datos.
- loggerd pierde ~3 % de `carState` (5823/6000 por segmento) mientras `carOutput`/`sendcan`/`can` llegan a 6000.
- `commIssue` es NO_ENTRY: solo se ve en pantalla al intentar activar, pero el evento está activo siempre.

## Causa raíz

`msgq` limita cada cola a **`NUM_READERS` lectores** (15 en commaai/msgq, `msgq/msgq.h`). Cuando se registra el
16º, `msgq_init_subscriber()` (`msgq/msgq.cc`, bloque *"No more slots available. Reset all subscribers"*)
**expulsa a TODOS** (`read_valids=false`, `read_uids=0`, `num_readers=0`). Cada víctima se re-registra en su
siguiente lectura saltando al puntero de escritura (pierde lo pendiente). Con **≥16 lectores vivos** el ciclo es
perpetuo: cada re-registro vuelve a desbordar y expulsa al resto.

Los slots **nunca se liberan** (`msgq_close_queue` solo hace munmap; `num_readers` solo crece): la expulsión es el
único "GC" de slots de procesos muertos o de SubMasters recreados. Con ≤ límite de lectores vivos es una
expulsión puntual e inofensiva; con más, la tormenta.

Lectores vivos de `carState` en `orbit-master` (censo 2026-09-07):

| origen | lectores |
|---|---|
| openpilot python: controlsd, plannerd, radard, calibrationd, lagd, locationd, paramsd, torqued, modeld, dmonitoringd, selfdrived, ui | 12 |
| loggerd (C++, suscribe todo lo logueable) | 1 |
| sunnypilot `locationd_llk` (`sunnypilot/selfdrive/locationd/locationd.cc`) | 1 |
| **ORBIT** dentro de `manager`: telemetría (`orbit/mqtt_envio_general.py`, 17 servicios) | 1 |
| **ORBIT** dentro de `manager`: `GateMonitor` del mando remoto (`orbit/command_gates.py`, 7 servicios) | 1 |
| **total** | **16 > 15** |

Sunnypilot stock vive en 14. En julio (telemetría + feedbackd) eran 16; quitar la suscripción de feedbackd dejó
15 justos. El GateMonitor (commit 606f44760, 2026-08-24) fue el nuevo 16º. Además `deviceState` tiene 12
lectores sin conectividad y ~20 con athenad (4 hilos `upload_handler`, uno por SubMaster) y sunnylink
conectados: con Internet en el coche también habría desbordado 15.

Experimento local (`msgq_readers_exp.py`, publicador carState@100 Hz + N SubMasters como calibrationd):
13/14/15 lectores → `all_checks` OK 99,4 %; 16/17/20 → OK 2-4 %, carState recibido el 42-56 % de los ciclos.

## Fix definitivo (aplicado 2026-09-07)

- Submódulo `msgq_repo` apuntado al fork **`https://github.com/Dragoadri/msgq.git`**, rama `orbit`
  (base: commit `9beb84a` de commaai/msgq + `NUM_READERS 31`). 31 deja la cabecera shm en 768 B (múltiplo
  de 64, como los 384 originales). Test en el fork: `msgq/tests/test_poller.py::test_more_subscribers_than_old_limit_all_receive`.
- Test de regresión en el repo: `cereal/messaging/tests/test_msgq_reader_limit.py` (20 SubMasters como
  calibrationd; falla con 15, pasa con 31).
- **Cambia el layout de `/dev/shm`**: tras compilar hay que **reiniciar** (la OTA de `updated` ya lo hace). Si
  `QuickBootToggle` dejó `/data/openpilot/prebuilt`, borrarlo o no se recompila.
- Retirado el parche `silenciar_alertas_comm` (ocultaba el síntoma; selfdrived vuelve a ser el de sunnypilot).
- Fixes anteriores que se mantienen: feedbackd sin suscripción a carState (julio).

## Verificación en el device

```bash
# coche encendido, openpilot corriendo
cd /data/openpilot
python3 tools/orbit/diag_msgq_readers.py --census                 # todas las colas: lectores / límite
python3 tools/orbit/diag_msgq_readers.py --service carState --dur 30   # expulsiones en vivo
```

- `--census` deriva el límite del tamaño del fichero shm (funciona con builds de 15 y de 31) y marca las colas
  a ≤ 2 slots del máximo. Esperado tras el fix: `carState` ≥ 16 lectores de 31, ningún `!!`.
- Modo `--service`: 0 `EVICT-ALL` en 30 s. Si aparece uno aislado es el GC de slots muertos (inofensivo);
  repetidos = lectores vivos por encima del límite.
- `tools/orbit/grab_orbit_logs.sh pull` incluye el censo en `orbit_snapshot.txt`.
- Las colas viven en `/dev/shm/msgq_<servicio>` (o `/dev/shm/msgq_<OPENPILOT_PREFIX>/<servicio>`); no crear
  nunca sockets desde un diagnóstico: gastan un slot y re-truncan la cola.

## Reglas para no volver a romperlo

- Cada `SubMaster([...])` / `sub_sock()` gasta un slot en CADA servicio que lista, y **cada re-creación** también
  (toggles de canal en `mqtt_envio_general.init_submaster`, relevo de hilo del GateMonitor, `athenad.getMessage`,
  procesos que se reinician). Antes de añadir suscripciones a servicios calientes (carState, deviceState,
  liveCalibration, carControl, selfdriveState, modelV2) pasar `--census`.
- NUNCA crear SubMaster/sub_sock dentro de un bucle.
- El mando remoto y la telemetría deben seguir en SubMasters separados (el plano de mando no puede depender del
  hilo MQTT), así que ORBIT cuesta 2 lectores en carState por diseño: el margen lo da el límite de 31.
