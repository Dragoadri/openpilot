# Force Onroad: arrancar OP en el comma sin coche (modo banco)

Port del "Force Drive State" de StarPilot (fork de FrogPilot) a orbit-master, 2026-09-08.

## Qué hace

Con el param `ForceOnroad` activo, `hardwared` da por buena la **ignición** aunque el panda
interno del 3X diga lo contrario, y el dispositivo pasa a onroad como si el coche estuviera
en marcha: arrancan camerad, modeld, selfdrived, controlsd, plannerd, radard, locationd,
calibrationd, paramsd, lagd, torqued, dmonitoring, loggerd, la UI onroad y los hilos ORBIT
(telemetría y mando).

Sin coche no hay CAN. `card` se queda en "Waiting for CAN messages..." y no publica
`carState` ni `CarParams`. Para que el resto del stack no se quede bloqueado en
`params.get("CarParams", block=True)`, `manager` restaura `CarParams` y `CarParamsSP` desde
las copias de la última conducción real (`CarParamsPersistent`, `CarParamsSPPersistent`)
justo después del borrado de la transición a onroad. Si el dispositivo nunca ha visto un
coche, arranca con el coche `MOCK` de opendbc (modo dashcam, alerta "Car Unrecognized").

## Qué funciona y qué no

| Funciona | No funciona (por diseño) |
|---|---|
| Vista onroad con cámara y trazado del modelo | Activar OP: no hay `carState` (al intentarlo salen commIssue/canBusMissing) |
| Alertas, HUD, distintivo "BENCH • NO CAR" | Velocidad, controles, MADS |
| Telemetría ORBIT (lo que haya: modelo, calibración, deviceState…) | Mando remoto: los gates exigen `carState` vivo y quedan en rojo (fail-closed) |
| loggerd graba la sesión como una ruta normal | Salida CAN: la seguridad del panda sigue en NO_OUTPUT (card nunca pone `FirmwareQueryDone`) |

## Cómo se usa

- Ajustes → Dispositivo → **Force Onroad (bench test)** → confirmar. Solo con el dispositivo
  offroad y sin OP activado. Si "Always Offroad" está activo hay que quitarlo antes: **offroad gana**.
- Para salir: el mismo botón ("Exit Force Onroad") → vuelve a HOME y se limpian los params de
  la transición a offroad como en una conducción normal.
- El param es `CLEAR_ON_MANAGER_START`: **un reinicio siempre lo apaga**. Nunca sobrevive a un reboot.
- Por SSH: `python3 -c "from openpilot.common.params import Params; Params().put_bool('ForceOnroad', True)"`.

## Dónde está

| Pieza | Fichero |
|---|---|
| Param | `common/params_keys.h` (`ForceOnroad`, junto a `OffroadMode`) |
| Ignición forzada | `system/hardware/hardwared.py` (bloque `ForceOnroad`, antes del gate de 2 Hz) |
| Restauración de CarParams | `system/manager/helpers.py::restore_car_params_for_bench`, llamada en `system/manager/manager.py` |
| Sin `canError` en banco | `selfdrive/selfdrived/selfdrived.py` (`self.force_onroad`) |
| UI: onroad y pantalla encendida | `selfdrive/ui/ui_state.py` (`force_onroad` en `update_params`, `started`, `_set_awake`) |
| UI: botón | `selfdrive/ui/sunnypilot/layouts/settings/device.py` |
| UI: distintivo | `selfdrive/ui/onroad/hud_renderer.py` |
| Tests | `system/hardware/tests/test_hardwared_force_onroad.py`, `system/manager/test/test_helpers_bench.py` |

Diferencia con StarPilot: ellos hacen `should_start |= force_onroad` (salta términos, temperatura,
espacio libre…); aquí solo se fuerza la ignición, así que el resto de condiciones de arranque
siguen mandando. Y la restauración de `CarParams` vive en `manager` (una sola vez, en el flanco a
onroad) en vez de en el botón de la UI, así funciona igual desde la UI o desde SSH.

## Fase siguiente (no hecha)

Coche simulado en el dispositivo: un publicador de `carState`/CAN falsos para que controlsd,
los gates del mando y la telemetría vean un coche y OP se pueda activar en la mesa
(equivalente a llevar `tools/sim` al comma).
