# Modo 3 COMMA+JETSON — Plan de Implementación

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Añadir un nuevo modo de torque `SteerTorqueMode=3` ("COMMA + JETSON") que use el torque del modelo Comma como base pero permita a la Jetson inyectar maniobras de esquive temporales (offset de ángulo + curvatura) cuando detecte un obstáculo.

**Architecture:** La Jetson envía un JSON por el socket ZMQ existente (puerto 5556). Un módulo nuevo `ObstaclePulseState` mantiene el estado del esquive activo y devuelve offsets por frame. `controlsd.py` los suma a `steeringAngleDeg` y `desired_curvature` mientras dura el esquive; el `LatControlTorque` del Comma persigue la trayectoria desplazada y, al expirar, recentra solo. Status sincronizado a la app vía MQTT.

**Tech Stack:** Python (controlsd, zmq_client, módulo pulse, mqtt_*), C++/Qt (UI Comma), Dart/Flutter (app), capnp params (config y estado).

---

## File Structure

**Archivos nuevos:**
- `sicuem/orbit/orbit_obstacle_pulse.py` — clase `ObstaclePulseState` con ingest, get_offsets, cancelaciones.
- `sicuem/orbit/test/test_obstacle_pulse.py` — tests unitarios.
- `sicuem/orbit/test/test_obstacle_pulse_zmq.py` — test integrado de protocolo.

**Archivos modificados:**
- `common/params.cc:175` — 4 params CLEAR + 4 params PERSISTENT.
- `sicuem/orbit/zmq_client.py:147` — distinguir formato por longitud, parsear JSON.
- `selfdrive/controls/controlsd.py:60-130 (init), 988 (selector), 1110 (post-selector)` — rama `steer_mode==3` y aplicación de offsets.
- `selfdrive/ui/sunnypilot/qt/offroad/settings/sunnypilot/jetson_settings.h` — declarar 4º botón.
- `selfdrive/ui/sunnypilot/qt/offroad/settings/sunnypilot/jetson_settings.cc` — añadir botón, conectar a `tryChangeSteerMode(3)`, indicador de estado.
- `sicuem/orbit/mqtt_envio_general.py` — publicador del status.
- `sicuem/orbit/mqtt_comandos.py:746` — validar `mode in (0,1,2,3)`.
- `/home/drago/Escritorio/PROYECTS/ORBIT/orbit_app/lib/screens/jetson_config_screen.dart` — 4ª tarjeta, listener status.
- `/home/drago/Escritorio/PROYECTS/ORBIT/orbit_app/lib/services/mqtt_service.dart` — listener nuevo topic.

---

## Task 1 — Params en `common/params.cc`

**Files:**
- Modify: `common/params.cc:175-184`

- [ ] **Step 1: Leer la zona afectada para identificar el contexto exacto**

```bash
sed -n '170,200p' /home/drago/Escritorio/OPENPILOTSIC/openpilot-img/common/params.cc
```

Expected: ver los params `JetsonTorque`, `JetsonTorqueTimestamp`, `SteerTorqueMode`, etc. ya existentes para colocar los nuevos justo después.

- [ ] **Step 2: Añadir los 8 params nuevos**

Localizar la línea con `{"SteerTorqueModeMqttPayload", CLEAR_ON_MANAGER_START},` y añadir DESPUÉS:

```c++
    // Modo COMMA+JETSON (esquive de obstáculos)
    {"JetsonObstaclePulse", CLEAR_ON_MANAGER_START},  // JSON crudo del último mensaje recibido de la Jetson (modo 3)
    {"JetsonObstacleTimestamp", CLEAR_ON_MANAGER_START},  // Wall-clock del último mensaje. Lo usa el watchdog y la detección de mensaje nuevo.
    {"JetsonObstacleStatus", CLEAR_ON_MANAGER_START},  // Estado del esquive: ""|"DODGING_LEFT"|"DODGING_RIGHT"|"CANCELED_DRIVER"|"CANCELED_STALE"
    {"JetsonObstacleStatusMqttPayload", CLEAR_ON_MANAGER_START},  // Payload JSON del status para mqtt_envio_general
    {"JetsonObstacleMaxDurationMs", PERSISTENT},  // Tope superior de duration_ms (default 2500)
    {"JetsonObstacleWatchdogMs", PERSISTENT},  // ms sin mensaje durante esquive activo → cancelar (default 400)
    {"JetsonObstacleMaxAngle", PERSISTENT},  // Grados de offset para |intensity|=1.0 (default 25.0)
    {"JetsonObstacleMaxCurv", PERSISTENT},  // Curvatura 1/m de offset para |intensity|=1.0 (default 0.030)
```

- [ ] **Step 3: Recompilar params.cc**

Run desde la raíz del repo:
```bash
cd /home/drago/Escritorio/OPENPILOTSIC/openpilot-img && scons -j4 common/
```

Expected: compilación sin errores. Si falla con "redeclaration", verificar que los nombres no estén duplicados.

- [ ] **Step 4: Verificar que los params se registran**

```bash
cd /home/drago/Escritorio/OPENPILOTSIC/openpilot-img && python3 -c "from openpilot.common.params import Params; p = Params(); p.put('JetsonObstacleMaxAngle', '25.0'); print(p.get('JetsonObstacleMaxAngle'))"
```

Expected: imprime `b'25.0'` sin lanzar `UnknownKeyName`.

- [ ] **Step 5: Commit**

```bash
cd /home/drago/Escritorio/OPENPILOTSIC/openpilot-img && git add common/params.cc && git commit -m "params: registrar params del modo 3 COMMA+JETSON

8 nuevos params:
- JetsonObstaclePulse / JetsonObstacleTimestamp (entrada Jetson)
- JetsonObstacleStatus / JetsonObstacleStatusMqttPayload (salida UI)
- JetsonObstacleMax{DurationMs,Angle,Curv} y JetsonObstacleWatchdogMs (config)

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 2 — Módulo `ObstaclePulseState` (TDD)

**Files:**
- Create: `sicuem/orbit/orbit_obstacle_pulse.py`
- Create: `sicuem/orbit/test/test_obstacle_pulse.py`

- [ ] **Step 1: Crear esqueleto del archivo de tests primero**

Crear `sicuem/orbit/test/test_obstacle_pulse.py`:

```python
"""Tests unitarios del esquive de obstáculos (modo 3 COMMA+JETSON)."""
import unittest
from unittest.mock import MagicMock

from openpilot.sicuem.orbit.orbit_obstacle_pulse import (
    ObstaclePulseState,
    DEFAULT_MAX_DURATION_MS,
    DEFAULT_WATCHDOG_MS,
    DEFAULT_MAX_ANGLE,
    DEFAULT_MAX_CURV,
)


def _carstate(steering_pressed=False, brake_pressed=False):
    cs = MagicMock()
    cs.steeringPressed = steering_pressed
    cs.brakePressed = brake_pressed
    return cs


class TestObstaclePulseState(unittest.TestCase):

    def test_idle_returns_zero_offsets(self):
        s = ObstaclePulseState()
        a, c, st = s.get_offsets(now=0.0, carstate=_carstate(), lat_active=True)
        self.assertEqual(a, 0.0)
        self.assertEqual(c, 0.0)
        self.assertEqual(st, "")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Ejecutar test, debe fallar por ImportError**

Run:
```bash
cd /home/drago/Escritorio/OPENPILOTSIC/openpilot-img && python3 -m pytest sicuem/orbit/test/test_obstacle_pulse.py -v
```

Expected: FAIL con `ModuleNotFoundError: No module named 'openpilot.sicuem.orbit.orbit_obstacle_pulse'`.

- [ ] **Step 3: Crear el módulo `orbit_obstacle_pulse.py` mínimo**

Crear `sicuem/orbit/orbit_obstacle_pulse.py`:

```python
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Esquive de obstáculos para el modo 3 (COMMA+JETSON).

A diferencia de orbit_steering_pulse.py (cruceta MQTT, valores fijos,
dos fases), este módulo:
  - lee el último mensaje de la Jetson desde Params (productor: zmq_client en
    otro proceso, no globals)
  - escala intensity [-1,+1] a offsets de ángulo y curvatura
  - cancela por volante presionado, freno, watchdog, lat inactivo o sustitución
  - una sola fase (sin retorno: el LatControlTorque del Comma recentra)

Convención de signo: negativo = derecha, positivo = izquierda
(coherente con controlsd.py:894-897).
"""
from __future__ import annotations
import time
from typing import Tuple


# Defaults (sembrados al param la primera vez que se lee y devuelve None)
DEFAULT_MAX_DURATION_MS = 2500.0   # ms — tope superior de duration_ms
DEFAULT_WATCHDOG_MS     = 400.0    # ms — sin heartbeat durante esquive → cancelar
DEFAULT_MAX_ANGLE       = 25.0     # grados — para |intensity|=1.0
DEFAULT_MAX_CURV        = 0.030    # 1/m  — para |intensity|=1.0


class ObstaclePulseState:
    """Estado del esquive activo. Una instancia por proceso controlsd."""

    def __init__(self) -> None:
        self.active: bool = False
        self.start_ts: float = 0.0
        self.duration_s: float = 0.0
        self.intensity: float = 0.0          # ya clampeado a [-1, +1]
        self.last_payload_ts: float = 0.0    # ts (wall-clock) del último mensaje recibido

    def ingest_new_message(self, payload: dict, now: float,
                           max_duration_ms: float = DEFAULT_MAX_DURATION_MS) -> None:
        """Carga un mensaje recibido de la Jetson (sustituye el actual)."""
        obstacle = bool(payload.get("obstacle", False))
        intensity = float(payload.get("intensity", 0.0))
        duration_ms = float(payload.get("duration_ms", 0.0))

        # Clamp intensity
        if intensity < -1.0:
            intensity = -1.0
        elif intensity > 1.0:
            intensity = 1.0

        # Cap duration
        if duration_ms < 0.0:
            duration_ms = 0.0
        if duration_ms > max_duration_ms:
            duration_ms = max_duration_ms

        # obstacle=False es cancelación explícita
        if not obstacle or duration_ms == 0.0:
            self.active = False
            self.intensity = 0.0
            self.duration_s = 0.0
            self.last_payload_ts = now
            return

        self.active = True
        self.intensity = intensity
        self.duration_s = duration_ms / 1000.0
        self.start_ts = now
        self.last_payload_ts = now

    def get_offsets(self, now: float, carstate, lat_active: bool,
                    watchdog_ms: float = DEFAULT_WATCHDOG_MS,
                    max_angle: float = DEFAULT_MAX_ANGLE,
                    max_curv: float = DEFAULT_MAX_CURV) -> Tuple[float, float, str]:
        """Devuelve (angle_off_deg, curv_off, status) para este frame.

        status ∈ {"", "DODGING_LEFT", "DODGING_RIGHT",
                  "CANCELED_DRIVER", "CANCELED_STALE"}
        """
        if not self.active:
            return 0.0, 0.0, ""

        # Cancelación: lat inactivo (no es del conductor, status vacío)
        if not lat_active:
            self._reset()
            return 0.0, 0.0, ""

        # Cancelación: conductor (volante o freno)
        if carstate.steeringPressed or carstate.brakePressed:
            self._reset()
            return 0.0, 0.0, "CANCELED_DRIVER"

        # Cancelación: watchdog (Jetson stale)
        if (now - self.last_payload_ts) * 1000.0 > watchdog_ms:
            self._reset()
            return 0.0, 0.0, "CANCELED_STALE"

        # Fin natural por duración
        elapsed = now - self.start_ts
        if elapsed >= self.duration_s:
            self._reset()
            return 0.0, 0.0, ""

        # Aplicar offset proporcional a intensity
        angle_off = self.intensity * max_angle
        curv_off  = self.intensity * max_curv
        # Convención: negativo = derecha, positivo = izquierda
        status = "DODGING_RIGHT" if self.intensity < 0.0 else "DODGING_LEFT"
        return angle_off, curv_off, status

    def _reset(self) -> None:
        self.active = False
        self.intensity = 0.0
        self.duration_s = 0.0
```

- [ ] **Step 4: Ejecutar test idle, debe pasar**

Run:
```bash
cd /home/drago/Escritorio/OPENPILOTSIC/openpilot-img && python3 -m pytest sicuem/orbit/test/test_obstacle_pulse.py::TestObstaclePulseState::test_idle_returns_zero_offsets -v
```

Expected: PASS.

- [ ] **Step 5: Añadir test de ingest + offsets**

Añadir al final de `test_obstacle_pulse.py` (dentro de la clase):

```python
    def test_ingest_basic_left(self):
        s = ObstaclePulseState()
        s.ingest_new_message({"obstacle": True, "intensity": 0.4, "duration_ms": 1000}, now=10.0)
        self.assertTrue(s.active)
        self.assertAlmostEqual(s.intensity, 0.4)
        self.assertAlmostEqual(s.duration_s, 1.0)

    def test_offsets_proportional_to_intensity(self):
        s = ObstaclePulseState()
        s.ingest_new_message({"obstacle": True, "intensity": -0.5, "duration_ms": 1000}, now=10.0)
        a, c, st = s.get_offsets(now=10.5, carstate=_carstate(), lat_active=True)
        self.assertAlmostEqual(a, -0.5 * DEFAULT_MAX_ANGLE)
        self.assertAlmostEqual(c, -0.5 * DEFAULT_MAX_CURV)
        self.assertEqual(st, "DODGING_RIGHT")

    def test_offsets_left_status(self):
        s = ObstaclePulseState()
        s.ingest_new_message({"obstacle": True, "intensity": 0.7, "duration_ms": 1000}, now=10.0)
        a, c, st = s.get_offsets(now=10.5, carstate=_carstate(), lat_active=True)
        self.assertGreater(a, 0)
        self.assertGreater(c, 0)
        self.assertEqual(st, "DODGING_LEFT")
```

- [ ] **Step 6: Ejecutar todos los tests**

Run:
```bash
cd /home/drago/Escritorio/OPENPILOTSIC/openpilot-img && python3 -m pytest sicuem/orbit/test/test_obstacle_pulse.py -v
```

Expected: 4 PASS.

- [ ] **Step 7: Añadir tests de cancelación, expiración, clamp**

Añadir:

```python
    def test_natural_expiration(self):
        s = ObstaclePulseState()
        s.ingest_new_message({"obstacle": True, "intensity": -0.5, "duration_ms": 1000}, now=10.0)
        # En t=10.5 sigue activo
        a, _, _ = s.get_offsets(now=10.5, carstate=_carstate(), lat_active=True)
        self.assertNotEqual(a, 0)
        # En t=11.1 expira
        a, c, st = s.get_offsets(now=11.1, carstate=_carstate(), lat_active=True)
        self.assertEqual((a, c, st), (0.0, 0.0, ""))
        self.assertFalse(s.active)

    def test_cancel_steering_pressed(self):
        s = ObstaclePulseState()
        s.ingest_new_message({"obstacle": True, "intensity": -0.5, "duration_ms": 1000}, now=10.0)
        a, c, st = s.get_offsets(now=10.5, carstate=_carstate(steering_pressed=True), lat_active=True)
        self.assertEqual((a, c), (0.0, 0.0))
        self.assertEqual(st, "CANCELED_DRIVER")
        self.assertFalse(s.active)

    def test_cancel_brake_pressed(self):
        s = ObstaclePulseState()
        s.ingest_new_message({"obstacle": True, "intensity": 0.5, "duration_ms": 1000}, now=10.0)
        _, _, st = s.get_offsets(now=10.5, carstate=_carstate(brake_pressed=True), lat_active=True)
        self.assertEqual(st, "CANCELED_DRIVER")

    def test_cancel_watchdog_stale(self):
        s = ObstaclePulseState()
        s.ingest_new_message({"obstacle": True, "intensity": -0.5, "duration_ms": 2000}, now=10.0)
        # Pasan 600 ms sin nuevos mensajes → > watchdog 400
        _, _, st = s.get_offsets(now=10.6, carstate=_carstate(), lat_active=True)
        self.assertEqual(st, "CANCELED_STALE")

    def test_cancel_lat_inactive(self):
        s = ObstaclePulseState()
        s.ingest_new_message({"obstacle": True, "intensity": -0.5, "duration_ms": 1000}, now=10.0)
        a, c, st = s.get_offsets(now=10.5, carstate=_carstate(), lat_active=False)
        self.assertEqual((a, c, st), (0.0, 0.0, ""))
        self.assertFalse(s.active)

    def test_clamp_intensity(self):
        s = ObstaclePulseState()
        s.ingest_new_message({"obstacle": True, "intensity": 99.0, "duration_ms": 500}, now=0.0)
        self.assertEqual(s.intensity, 1.0)
        s.ingest_new_message({"obstacle": True, "intensity": -99.0, "duration_ms": 500}, now=0.0)
        self.assertEqual(s.intensity, -1.0)

    def test_cap_duration(self):
        s = ObstaclePulseState()
        s.ingest_new_message(
            {"obstacle": True, "intensity": 0.5, "duration_ms": 999999},
            now=0.0,
            max_duration_ms=2500.0,
        )
        self.assertAlmostEqual(s.duration_s, 2.5)

    def test_obstacle_false_cancels(self):
        s = ObstaclePulseState()
        s.ingest_new_message({"obstacle": True, "intensity": -0.5, "duration_ms": 1000}, now=10.0)
        self.assertTrue(s.active)
        s.ingest_new_message({"obstacle": False, "intensity": 0.0, "duration_ms": 0}, now=10.2)
        self.assertFalse(s.active)

    def test_substitution_replaces(self):
        s = ObstaclePulseState()
        s.ingest_new_message({"obstacle": True, "intensity": -0.5, "duration_ms": 1000}, now=10.0)
        s.ingest_new_message({"obstacle": True, "intensity": 0.8, "duration_ms": 1500}, now=10.3)
        self.assertAlmostEqual(s.intensity, 0.8)
        self.assertAlmostEqual(s.duration_s, 1.5)
        self.assertAlmostEqual(s.start_ts, 10.3)
```

- [ ] **Step 8: Ejecutar todos los tests, deben pasar**

Run:
```bash
cd /home/drago/Escritorio/OPENPILOTSIC/openpilot-img && python3 -m pytest sicuem/orbit/test/test_obstacle_pulse.py -v
```

Expected: 13 PASS.

- [ ] **Step 9: Commit**

```bash
cd /home/drago/Escritorio/OPENPILOTSIC/openpilot-img && git add -f sicuem/orbit/orbit_obstacle_pulse.py sicuem/orbit/test/test_obstacle_pulse.py && git commit -m "obstacle-pulse: módulo ObstaclePulseState con tests

- Ingest del JSON Jetson, clamp intensity, cap duration
- Cancelaciones: steering, brake, watchdog, lat inactivo, obstacle=false
- Sustitución: nuevo mensaje reemplaza al activo
- Convención de signo: negativo=derecha, positivo=izquierda
- 13 tests unitarios

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 3 — Extender `zmq_client.py` para JSON

**Files:**
- Modify: `sicuem/orbit/zmq_client.py:147-194`

- [ ] **Step 1: Añadir import de `json` arriba**

En `sicuem/orbit/zmq_client.py`, asegurar que `import json` está al principio (junto con `import math`, `import struct`, etc.):

```python
import json
import math
import struct
import threading
import time

import zmq

from openpilot.common.params import Params, UnknownKeyName
from openpilot.common.swaglog import cloudlog
```

- [ ] **Step 2: Modificar `_torque_listener` para distinguir formato por longitud**

Reemplazar el cuerpo del bucle `while self._running:` en `_torque_listener` (líneas ~155-194) por:

```python
    while self._running:
      try:
        data = self._torque_socket.recv()

        # Distinguir formato por longitud:
        #   - len == 4  → torque clásico modo 1 (float empaquetado)
        #   - len  > 4  → mensaje JSON modo 3 (esquive de obstáculo)
        if len(data) > 4:
          self._handle_obstacle_json(data)
          continue

        torque = _parse_torque(data)
        if torque is None:
          # Payload irreconocible -> ignorar este mensaje (no escribimos
          # nada en params, asi el watchdog de controlsd lo marcara stale
          # y el volante quedara en 0 hasta que llegue un valor valido).
          cloudlog.error(f"ZMQClient: payload de torque irreconocible bytes={data.hex()} len={len(data)}")
          continue
        # Log de cada torque recibido para verificacion empirica del formato
        # y del valor que se publica al param. La Jetson va a ~5 Hz, asi que
        # esto son ~5 lineas/seg en swaglog.
        cloudlog.info(f"ZMQClient: torque recibido bytes={data.hex()} len={len(data)} -> {torque}")
        now = time.time()
        try:
          self._params.put("JetsonTorqueTimestamp", f"{now:.6f}")
        except UnknownKeyName:
          if not getattr(self, "_warned_ts_param", False):
            cloudlog.error("JetsonTorqueTimestamp no registrado. Recompila common/params.cc para habilitar el watchdog del modo Jetson.")
            self._warned_ts_param = True
        self._params.put("JetsonTorque", str(torque))
      except zmq.Again:
        # RCVTIMEO cumplido sin datos. Volvemos a comprobar _running y
        # seguimos esperando. Es el mecanismo que permite a stop() romper
        # el bucle en tiempo finito.
        continue
      except zmq.ZMQError as e:
        if e.errno == zmq.ETERM:
          break
        cloudlog.warning(f"ZMQClient: error recibiendo torque: {e}")
      except Exception as e:
        cloudlog.error(f"ZMQClient: error inesperado: {e}")
```

- [ ] **Step 3: Añadir el método `_handle_obstacle_json`**

Justo encima de `_torque_listener` (o donde encaje en el orden del archivo), añadir:

```python
  def _handle_obstacle_json(self, data: bytes) -> None:
    """Parsea un mensaje JSON del modo 3 (COMMA+JETSON) y lo publica en Params.

    El formato esperado es:
      {"obstacle": bool, "intensity": float [-1,+1], "duration_ms": int}

    Si el JSON está mal formado o le faltan campos clave, se loguea y se
    descarta. NO se escribe en JetsonObstaclePulse para que el lado de
    controlsd no detecte un mensaje nuevo erróneo.
    """
    try:
      payload = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as e:
      cloudlog.error(f"ZMQClient: JSON obstáculo no decodificable: {e} bytes={data[:50]!r}")
      return

    if not isinstance(payload, dict):
      cloudlog.error(f"ZMQClient: JSON obstáculo no es objeto: {payload!r}")
      return

    intensity = payload.get("intensity")
    if not isinstance(intensity, (int, float)):
      cloudlog.error(f"ZMQClient: JSON obstáculo sin intensity numérico: {payload!r}")
      return

    now = time.time()
    cloudlog.info(f"ZMQClient: pulso obstáculo {payload}")
    # Orden: payload primero (json.dumps re-serializa para limpiar espacios y
    # tipos raros), timestamp después → si controlsd lee entremedias, ve un
    # ts viejo y procesa en el siguiente frame (no falsea sustitución).
    try:
      self._params.put("JetsonObstaclePulse", json.dumps(payload))
      self._params.put("JetsonObstacleTimestamp", f"{now:.6f}")
    except UnknownKeyName:
      cloudlog.error("JetsonObstaclePulse / JetsonObstacleTimestamp no registrados. Recompila common/params.cc.")
```

- [ ] **Step 4: Crear test integrado de protocolo**

Crear `sicuem/orbit/test/test_obstacle_pulse_zmq.py`:

```python
"""Test integrado: enviar JSON por ZMQ → leer params → modo 1 sigue funcionando."""
import json
import struct
import time
import threading
import unittest

import zmq

from openpilot.common.params import Params
from openpilot.sicuem.orbit.zmq_client import ZMQClient


class TestObstacleZmqProtocol(unittest.TestCase):
    """Verifica que zmq_client distingue float legacy (modo 1) y JSON (modo 3)."""

    PORT = 5566  # puerto distinto al productivo para no chocar

    def setUp(self):
        # Cliente apuntando a localhost para test local
        self.client = ZMQClient(jetson_ip="127.0.0.1", img_port=5565,
                                torque_port=self.PORT, jpeg_quality=10)
        self.client.start()

        # Productor (rol "Jetson"): PUSH a localhost
        self.ctx = zmq.Context.instance()
        self.push = self.ctx.socket(zmq.PUSH)
        self.push.bind(f"tcp://*:{self.PORT}")
        # Pequeño sleep para que el PULL del cliente conecte
        time.sleep(0.2)

        self.params = Params()

    def tearDown(self):
        self.push.close(linger=0)
        self.client.stop()

    def test_legacy_float_message(self):
        # 4 bytes float little-endian = modo 1
        self.push.send(struct.pack("<f", 0.42))
        time.sleep(0.3)
        self.assertEqual(float(self.params.get("JetsonTorque")), 0.42)

    def test_json_obstacle_message(self):
        msg = {"obstacle": True, "intensity": -0.7, "duration_ms": 1500}
        self.push.send_string(json.dumps(msg))
        time.sleep(0.3)
        raw = self.params.get("JetsonObstaclePulse")
        self.assertIsNotNone(raw)
        parsed = json.loads(raw)
        self.assertEqual(parsed["obstacle"], True)
        self.assertAlmostEqual(parsed["intensity"], -0.7)
        self.assertEqual(parsed["duration_ms"], 1500)

    def test_invalid_json_rejected(self):
        self.params.put("JetsonObstaclePulse", "{}")  # placeholder
        self.push.send_string("not a json {]")
        time.sleep(0.3)
        # Pulse no debe haberse sobrescrito con basura
        raw = self.params.get("JetsonObstaclePulse")
        self.assertEqual(raw, b"{}")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 5: Ejecutar el test integrado**

Run:
```bash
cd /home/drago/Escritorio/OPENPILOTSIC/openpilot-img && python3 -m pytest sicuem/orbit/test/test_obstacle_pulse_zmq.py -v
```

Expected: 3 PASS. Si falla por puerto en uso, cambiar `PORT = 5566` en el test.

- [ ] **Step 6: Commit**

```bash
cd /home/drago/Escritorio/OPENPILOTSIC/openpilot-img && git add sicuem/orbit/zmq_client.py && git add -f sicuem/orbit/test/test_obstacle_pulse_zmq.py && git commit -m "zmq_client: parsear JSON de obstáculo (modo 3) en mismo socket

Coexistencia con modo 1: distinguimos por longitud
- len == 4 → float legacy → JetsonTorque (sin cambios)
- len  > 4 → JSON → JetsonObstaclePulse + JetsonObstacleTimestamp

JSON malformado o sin intensity numérico se descarta con log de error.
Test integrado: enviar float y JSON, verificar params correctos.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 4 — Inyección en `controlsd.py`

**Files:**
- Modify: `selfdrive/controls/controlsd.py:60-130 (init), 988-1092 (selector), 1110-1148 (post-selector)`

- [ ] **Step 1: Añadir imports y estado en `__init__`**

Localizar la zona de imports al principio de `controlsd.py` (alrededor de línea 28) y verificar que `import json` y `import time` están. Añadir el import del módulo nuevo:

```python
from openpilot.sicuem.orbit.orbit_obstacle_pulse import (
    ObstaclePulseState,
    DEFAULT_MAX_DURATION_MS,
    DEFAULT_WATCHDOG_MS,
    DEFAULT_MAX_ANGLE,
    DEFAULT_MAX_CURV,
)
```

En `Controls.__init__` (alrededor de línea 200-210, junto con otros estados como `self.live_torque`), añadir:

```python
    # Modo 3 (COMMA+JETSON): estado del esquive y caché de config
    self._obstacle_pulse_state = ObstaclePulseState()
    self._last_obstacle_status = ""
    self._obstacle_config_last_read = 0.0  # wall-clock; recachear cada 1s
    self._obstacle_max_duration_ms = DEFAULT_MAX_DURATION_MS
    self._obstacle_watchdog_ms = DEFAULT_WATCHDOG_MS
    self._obstacle_max_angle = DEFAULT_MAX_ANGLE
    self._obstacle_max_curv = DEFAULT_MAX_CURV
```

- [ ] **Step 2: Añadir helper `_refresh_obstacle_config` en la clase Controls**

Añadir como método de la clase (junto a otros helpers):

```python
  def _refresh_obstacle_config(self, now: float) -> None:
    """Lee los 4 params de configuración del esquive con cache de 1s.

    Si el param es None (primera vez), siembra el default. Esto hace que la
    UI/app vea valores razonables al abrir los controles.
    """
    if now - self._obstacle_config_last_read < 1.0:
      return
    self._obstacle_config_last_read = now
    for key, default, attr in (
      ("JetsonObstacleMaxDurationMs", DEFAULT_MAX_DURATION_MS, "_obstacle_max_duration_ms"),
      ("JetsonObstacleWatchdogMs",    DEFAULT_WATCHDOG_MS,     "_obstacle_watchdog_ms"),
      ("JetsonObstacleMaxAngle",      DEFAULT_MAX_ANGLE,       "_obstacle_max_angle"),
      ("JetsonObstacleMaxCurv",       DEFAULT_MAX_CURV,        "_obstacle_max_curv"),
    ):
      try:
        raw = self.params.get(key)
        if raw is None or raw == b"":
          self.params.put_nonblocking(key, str(default))
          setattr(self, attr, default)
        else:
          setattr(self, attr, float(raw))
      except (UnknownKeyName, ValueError, TypeError):
        setattr(self, attr, default)
```

- [ ] **Step 3: Añadir rama `steer_mode == 3` en el selector**

En `controlsd.py:1086-1092`, dentro del bloque `if CC.latActive:` después del `elif steer_mode == 2:`, añadir:

```python
        elif steer_mode == 3:
          # FUENTE 4 (COMMA+JETSON): no tocamos actuators.steer aquí.
          # El torque base lo deja Comma. Más abajo (post-selector) sumamos
          # los offsets de ángulo y curvatura cuando hay esquive activo.
          pass
        # modo 0 (COMMA): no tocamos actuators.steer, queda lo del LaC.
```

- [ ] **Step 4: Añadir aplicación de offsets después del bloque del pulso de cruceta**

Justo después del bloque `try: from openpilot.sicuem.orbit.orbit_steering_pulse import ...` y su except (alrededor de línea 1148), antes del `if self.model_use_lateral_planner:` de la línea 1150, añadir:

```python
      # ────────────────────────────────────────────────────────────────
      # MODO 3 (COMMA+JETSON): offsets de esquive por obstáculo
      # ────────────────────────────────────────────────────────────────
      # Coexiste con la cruceta de la app: ambos suman al mismo
      # steeringAngleDeg / desired_curvature. En la práctica nunca están
      # activos a la vez (la cruceta es manual del usuario, el esquive es
      # automático del modelo Jetson) pero si lo estuvieran, los offsets
      # se sumarían y sería el peor caso de superposición.
      if CC.latActive:
        try:
          steer_mode_int = int(self.params.get("SteerTorqueMode") or 0)
        except (UnknownKeyName, ValueError, TypeError):
          steer_mode_int = 0

        if steer_mode_int == 3:
          now_pulse = time.time()
          self._refresh_obstacle_config(now_pulse)

          # Detectar mensaje nuevo (timestamp más reciente que el cached)
          try:
            payload_ts_raw = self.params.get("JetsonObstacleTimestamp")
            payload_ts = float(payload_ts_raw) if payload_ts_raw else 0.0
          except (UnknownKeyName, ValueError, TypeError):
            payload_ts = 0.0

          if payload_ts > self._obstacle_pulse_state.last_payload_ts:
            try:
              payload_raw = self.params.get("JetsonObstaclePulse")
              if payload_raw:
                payload = json.loads(payload_raw)
                self._obstacle_pulse_state.ingest_new_message(
                  payload, now_pulse, max_duration_ms=self._obstacle_max_duration_ms
                )
            except (UnknownKeyName, ValueError, TypeError) as e:
              cloudlog.error(f"controlsd: ObstaclePulse JSON inválido: {e}")

          angle_off, curv_off, status = self._obstacle_pulse_state.get_offsets(
            now_pulse, CS, CC.latActive,
            watchdog_ms=self._obstacle_watchdog_ms,
            max_angle=self._obstacle_max_angle,
            max_curv=self._obstacle_max_curv,
          )
          if angle_off or curv_off:
            actuators.steeringAngleDeg += angle_off
            self.desired_curvature += curv_off

          if status != self._last_obstacle_status:
            try:
              self.params.put_nonblocking("JetsonObstacleStatus", status)
              self.params.put_nonblocking(
                "JetsonObstacleStatusMqttPayload",
                json.dumps({"status": status, "ts": now_pulse, "source": "comma"}),
              )
            except UnknownKeyName:
              pass
            self._last_obstacle_status = status
```

- [ ] **Step 5: Verificar import de cloudlog y UnknownKeyName**

En `controlsd.py`, comprobar que estos imports ya existen en el archivo (deberían, los usa el resto del código del modo Jetson):

```bash
cd /home/drago/Escritorio/OPENPILOTSIC/openpilot-img && grep -n "from openpilot.common.swaglog\|from openpilot.common.params" selfdrive/controls/controlsd.py
```

Expected: ver `from openpilot.common.params import Params, UnknownKeyName` y `from openpilot.common.swaglog import cloudlog`. Si faltan, añadirlos.

- [ ] **Step 6: Verificar sintaxis del archivo**

Run:
```bash
cd /home/drago/Escritorio/OPENPILOTSIC/openpilot-img && python3 -m py_compile selfdrive/controls/controlsd.py
```

Expected: sin output (compila bien). Si hay `SyntaxError`, leer el contexto del `if CC.latActive:` y arreglar indentación.

- [ ] **Step 7: Test manual rápido del flujo (sin coche)**

Run:
```bash
cd /home/drago/Escritorio/OPENPILOTSIC/openpilot-img && python3 -c "
from openpilot.common.params import Params
import json, time
p = Params()
p.put('SteerTorqueMode', '3')
p.put('JetsonObstaclePulse', json.dumps({'obstacle': True, 'intensity': -0.5, 'duration_ms': 1500}))
p.put('JetsonObstacleTimestamp', f'{time.time():.6f}')
print('Modo:', p.get('SteerTorqueMode'))
print('Pulso:', p.get('JetsonObstaclePulse'))
print('TS:', p.get('JetsonObstacleTimestamp'))
"
```

Expected: imprime los 3 valores correctamente sin errores.

- [ ] **Step 8: Commit**

```bash
cd /home/drago/Escritorio/OPENPILOTSIC/openpilot-img && git add selfdrive/controls/controlsd.py && git commit -m "controlsd: rama steer_mode==3 (COMMA+JETSON) con esquive

- Init de ObstaclePulseState y caché de config (4 params, 1s TTL)
- Helper _refresh_obstacle_config: siembra defaults la 1ª vez
- Selector: modo 3 = pasa, no toca actuators.steer (Comma manda)
- Post-selector: detecta mensaje nuevo por timestamp, ingest, get_offsets
- Suma offset a steeringAngleDeg y desired_curvature
- Publica JetsonObstacleStatus (param) y MqttPayload sólo cuando cambia

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 5 — UI Comma: 4º botón en `jetson_settings`

**Files:**
- Modify: `selfdrive/ui/sunnypilot/qt/offroad/settings/sunnypilot/jetson_settings.h`
- Modify: `selfdrive/ui/sunnypilot/qt/offroad/settings/sunnypilot/jetson_settings.cc`

- [ ] **Step 1: Añadir miembro al header**

En `jetson_settings.h`, junto a las declaraciones de `btn_mode_model`, `btn_mode_jetson`, `btn_mode_test`, añadir:

```cpp
  QPushButton *btn_mode_comma_jetson;
  QLabel *obstacle_status_label;  // mini indicador de esquive activo
```

- [ ] **Step 2: Crear el botón en `setupTorqueControlSection`**

En `jetson_settings.cc`, localizar las líneas 160-162 con los 3 `makeModeButton`. Reemplazar el bloque para añadir el 4º:

```cpp
  btn_mode_model        = makeModeButton(tr("★ MODELO\nCOMMA\n(RECOMENDADO)"),  "#76B900");  // verde
  btn_mode_comma_jetson = makeModeButton(tr("COMMA + JETSON\n(esquive obstaculos)"), "#3B82F6");  // azul
  btn_mode_jetson       = makeModeButton(tr("JETSON\n(PilotNet)"), "#F59E0B");  // naranja
  btn_mode_test         = makeModeButton(tr("⚠ TEST MAX\n(PELIGROSO)"), "#EF4444");  // rojo
```

- [ ] **Step 3: Añadirlo al layout en el orden visual correcto**

Localizar las líneas con `ml->addWidget(btn_mode_*)` y reemplazarlas por:

```cpp
  ml->addWidget(btn_mode_model);
  ml->addWidget(btn_mode_comma_jetson);  // 2ª posición visual
  ml->addWidget(btn_mode_jetson);
  ml->addWidget(btn_mode_test);
```

- [ ] **Step 4: Conectar señal del nuevo botón**

Junto a los otros `connect(btn_mode_..., ...)`, añadir:

```cpp
  connect(btn_mode_comma_jetson, &QPushButton::clicked, this, [this]() { tryChangeSteerMode(3); });
```

- [ ] **Step 5: Añadir el mini indicador `obstacle_status_label`**

Después de `main_layout->addWidget(torque_status_label);`, añadir:

```cpp
  obstacle_status_label = new QLabel();
  obstacle_status_label->setStyleSheet(
    "font-size: 28px; font-weight: 600; padding: 8px; border-radius: 8px; margin-top: 6px;"
  );
  obstacle_status_label->setWordWrap(true);
  obstacle_status_label->setVisible(false);
  main_layout->addWidget(obstacle_status_label);
```

- [ ] **Step 6: Manejar el caso `mode == 3` en `tryChangeSteerMode`**

En `jetson_settings.cc`, dentro del switch/if que prepara el mensaje de confirmación según `mode`, añadir el caso `3`. Localizar el bloque que tiene los casos 0/1/2 y añadir:

```cpp
  } else if (mode == 3) {
    // COMMA + JETSON - aviso medio, no peligroso
    msg = tr("Activar COMMA + JETSON\n\n"
             "El volante usara el torque calculado por el MODELO COMMA "
             "(comportamiento normal). Si la Jetson detecta un obstaculo "
             "en la carretera, aplicara temporalmente un esquive lateral "
             "(maximo 2.5 segundos).\n\n"
             "Requisitos:\n"
             "- La Jetson conectada y enviando alertas por ZMQ\n"
             "- Modelo de deteccion de obstaculos cargado en la Jetson");
    confirmed = ConfirmationDialog::confirm(msg, tr("SI, activar COMMA+JETSON"), this);
  }
```

(Asegurarse de que el `} else if` encadena bien con los anteriores.)

- [ ] **Step 7: Actualizar `updateSteerModeVisual`**

Localizar la función. Junto a `btn_mode_jetson->setChecked(mode == 1);`, añadir:

```cpp
  btn_mode_comma_jetson->setChecked(mode == 3);
```

Y dentro del switch que pone `torque_status_label->setText(...)`, añadir:

```cpp
  case 3:
    torque_status_label->setText(tr("COMMA + JETSON - Comma manda; la Jetson puede esquivar obstaculos"));
    torque_status_label->setStyleSheet("background:#3B82F622; color:#3B82F6; font-size: 34px; font-weight: 600; padding: 12px; border-radius: 10px; margin-top: 8px;");
    break;
```

- [ ] **Step 8: Añadir polling del status en el QTimer existente**

Localizar el `QTimer` que ya hay en el constructor (ese que cada cierto tiempo lee `Params().get("SteerTorqueMode")` y refresca). Dentro del lambda del timer, añadir al final:

```cpp
    // Indicador de estado del esquive (modo 3 obstáculo)
    std::string obs = Params().get("JetsonObstacleStatus");
    if (obs.empty()) {
      obstacle_status_label->setVisible(false);
    } else {
      QString text;
      QString bg = "#3B82F622";
      QString fg = "#3B82F6";
      if (obs == "DODGING_LEFT") {
        text = tr("🚨 ESQUIVANDO ←");
        bg = "#F59E0B33"; fg = "#F59E0B";
      } else if (obs == "DODGING_RIGHT") {
        text = tr("🚨 ESQUIVANDO →");
        bg = "#F59E0B33"; fg = "#F59E0B";
      } else if (obs == "CANCELED_DRIVER") {
        text = tr("⚠ Cancelado por conductor");
        bg = "#9CA3AF33"; fg = "#9CA3AF";
      } else if (obs == "CANCELED_STALE") {
        text = tr("❌ Jetson sin respuesta");
        bg = "#EF444433"; fg = "#EF4444";
      }
      obstacle_status_label->setText(text);
      obstacle_status_label->setStyleSheet(
        QString("background:%1; color:%2; font-size: 28px; font-weight: 600; padding: 8px; border-radius: 8px; margin-top: 6px;")
        .arg(bg).arg(fg)
      );
      obstacle_status_label->setVisible(true);
    }
```

- [ ] **Step 9: Compilar la UI**

Run:
```bash
cd /home/drago/Escritorio/OPENPILOTSIC/openpilot-img && scons -j4 selfdrive/ui/
```

Expected: compila sin errores. Errores típicos:
- "no member named obstacle_status_label" → falta declaración en `.h`.
- "btn_mode_comma_jetson not declared in this scope" → ídem.
- "no matching function for call to ConfirmationDialog::confirm" → revisar firma.

- [ ] **Step 10: Commit**

```bash
cd /home/drago/Escritorio/OPENPILOTSIC/openpilot-img && git add selfdrive/ui/sunnypilot/qt/offroad/settings/sunnypilot/jetson_settings.{cc,h} && git commit -m "ui: 4º botón COMMA+JETSON e indicador de esquive en jetson_settings

- Botón azul COMMA+JETSON entre COMMA y JETSON (orden visual pedido).
- Diálogo de confirmación medio (no peligroso, no recomendado).
- Mini indicador obstacle_status_label que refleja JetsonObstacleStatus
  con colores: amarillo esquivando, gris driver, rojo stale.
- updateSteerModeVisual y polling del QTimer existentes ya cubren la
  sincronización con el param.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 6 — Bridge MQTT del status (`mqtt_envio_general.py`)

**Files:**
- Modify: `sicuem/orbit/mqtt_envio_general.py`

- [ ] **Step 1: Localizar el patrón de `SteerTorqueModeMqttPayload`**

Run:
```bash
cd /home/drago/Escritorio/OPENPILOTSIC/openpilot-img && grep -n "SteerTorqueModeMqttPayload\|_publish_to_topics\|telemetry_config" sicuem/orbit/mqtt_envio_general.py | head -30
```

Expected: ver el bloque que publica `SteerTorqueModeMqttPayload`. Lo reproduciremos para el nuevo payload.

- [ ] **Step 2: Añadir publicación del payload de obstáculo**

Localizar el método donde se publica `SteerTorqueModeMqttPayload`. Inmediatamente después de su bloque, añadir uno análogo:

```python
        # === JetsonObstacleStatus → MQTT (modo 3 COMMA+JETSON) ===
        try:
            obstacle_payload = self.params.get("JetsonObstacleStatusMqttPayload")
        except UnknownKeyName:
            obstacle_payload = None
        if obstacle_payload and obstacle_payload != getattr(self, "_last_obstacle_status_payload", None):
            try:
                payload_str = obstacle_payload.decode() if isinstance(obstacle_payload, bytes) else obstacle_payload
                self.client.publish(
                    f"telemetry_config/{self.dongle_id}/jetson_obstacle_status",
                    payload_str, qos=0, retain=False,
                )
                self.client.publish(
                    "jetson_obstacle_status/global",
                    payload_str, qos=0, retain=False,
                )
                self._last_obstacle_status_payload = obstacle_payload
            except Exception as e:
                print(f"[OBSTACLE STATUS MQTT] Error publicando: {e}")
```

> Nota: el helper exacto (`self.client.publish` vs `self._publish_to_topics`) depende de cómo esté el archivo. Adaptar al método existente que ya usa `SteerTorqueModeMqttPayload`. Los topics y el campo `_last_obstacle_status_payload` son lo único nuevo.

- [ ] **Step 3: Verificar import de `UnknownKeyName`**

Run:
```bash
cd /home/drago/Escritorio/OPENPILOTSIC/openpilot-img && grep -n "UnknownKeyName" sicuem/orbit/mqtt_envio_general.py
```

Expected: si no aparece, añadirlo arriba: `from openpilot.common.params import Params, UnknownKeyName`.

- [ ] **Step 4: Verificar que el archivo compila / no rompe**

Run:
```bash
cd /home/drago/Escritorio/OPENPILOTSIC/openpilot-img && python3 -m py_compile sicuem/orbit/mqtt_envio_general.py
```

Expected: sin output.

- [ ] **Step 5: Commit**

```bash
cd /home/drago/Escritorio/OPENPILOTSIC/openpilot-img && git add sicuem/orbit/mqtt_envio_general.py && git commit -m "mqtt: publicar JetsonObstacleStatus a topics telemetry/global

Mismo patrón que SteerTorqueModeMqttPayload. Sentido único Comma→app
(la app sólo lo muestra, no envía esquives).

Topics:
- telemetry_config/{dongle_id}/jetson_obstacle_status
- jetson_obstacle_status/global

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 7 — Validación en `mqtt_comandos.py`

**Files:**
- Modify: `sicuem/orbit/mqtt_comandos.py:746-775`

- [ ] **Step 1: Localizar la validación actual del modo**

Run:
```bash
cd /home/drago/Escritorio/OPENPILOTSIC/openpilot-img && sed -n '740,780p' sicuem/orbit/mqtt_comandos.py
```

Expected: ver el `try: mode = int(...)` y el rango aceptado.

- [ ] **Step 2: Asegurar que acepta 0..3**

Si el código tiene una validación tipo `if mode not in (0, 1, 2):`, cambiarla a `if mode not in (0, 1, 2, 3):`. Si simplemente parsea int sin validar rango, añadir validación explícita:

Localizar el bloque tras `mode = int(data["steer_torque_mode"])` y añadir/modificar:

```python
      if mode not in (0, 1, 2, 3):
        print(f"[STEER MODE SYNC] Valor fuera de rango: {mode}, ignorando")
        return
```

- [ ] **Step 3: Verificar sintaxis**

Run:
```bash
cd /home/drago/Escritorio/OPENPILOTSIC/openpilot-img && python3 -m py_compile sicuem/orbit/mqtt_comandos.py
```

Expected: sin output.

- [ ] **Step 4: Commit**

```bash
cd /home/drago/Escritorio/OPENPILOTSIC/openpilot-img && git add sicuem/orbit/mqtt_comandos.py && git commit -m "mqtt_comandos: aceptar SteerTorqueMode=3 (COMMA+JETSON)

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 8 — App Flutter: 4ª tarjeta y listener

**Files:**
- Modify: `/home/drago/Escritorio/PROYECTS/ORBIT/orbit_app/lib/screens/jetson_config_screen.dart`
- Modify: `/home/drago/Escritorio/PROYECTS/ORBIT/orbit_app/lib/services/mqtt_service.dart`

- [ ] **Step 1: Añadir tarjeta del modo 3 antes de la tarjeta del modo 1**

En `jetson_config_screen.dart`, dentro de `_buildSteerTorqueModeCard()`, localizar el bloque `_buildSteerModeCard(mode: 1, ...)` y añadir ANTES:

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
          const SizedBox(height: 12),
```

- [ ] **Step 2: Verificar que `_changeSteerMode(3)` funciona**

`_changeSteerMode(int mode)` ya parsea cualquier int. Para ser explícito, localizar el método y comprobar que no tiene un `if mode > 2` o similar. Si lo tiene, ampliar a `mode > 3`.

- [ ] **Step 3: Añadir helpers `_getSteerModeColor` y `_getSteerModeShortName` para modo 3**

Localizar los `switch (_steerTorqueMode)` (alrededor de líneas 1197 y 1205) y añadir caso `case 3:`:

```dart
  Color _getSteerModeColor() {
    switch (_steerTorqueMode) {
      case 0: return _kJetsonGreen;
      case 1: return const Color(0xFFF59E0B);
      case 2: return const Color(0xFFEF4444);
      case 3: return const Color(0xFF3B82F6);
      default: return Colors.grey;
    }
  }

  String _getSteerModeShortName() {
    switch (_steerTorqueMode) {
      case 0: return 'COMMA';
      case 1: return 'JETSON';
      case 2: return 'TEST MAX';
      case 3: return 'COMMA+JETSON';
      default: return '-';
    }
  }
```

(Adaptar al texto exacto de los métodos actuales — si ya tienen otra estructura, conservarla y añadir el caso 3.)

- [ ] **Step 4: Añadir listener de obstacle_status en `mqtt_service.dart`**

En `mqtt_service.dart`, junto a `addSteerTorqueModeListener` y `_handleSteerTorqueModeMessage`, añadir:

```dart
  // === Listener de JetsonObstacleStatus ===
  final List<Function(String, String)> _obstacleStatusListeners = [];

  void addObstacleStatusListener(Function(String dongleId, String status) cb) {
    _obstacleStatusListeners.add(cb);
  }

  void removeObstacleStatusListener(Function(String dongleId, String status) cb) {
    _obstacleStatusListeners.remove(cb);
  }

  void _handleObstacleStatusMessage(String deviceId, Map<String, dynamic> data) {
    final status = (data['status'] ?? '') as String;
    for (final cb in _obstacleStatusListeners) {
      try { cb(deviceId, status); } catch (e) { print('Listener obstacle status error: $e'); }
    }
  }
```

- [ ] **Step 5: Encaminar el topic en el manejador genérico**

Localizar el método que recibe mensajes MQTT (alrededor de línea 167 con `if (topic.contains('/steer_torque_mode')`). Añadir:

```dart
        if (topic.contains('/jetson_obstacle_status') || topic == 'jetson_obstacle_status/global') {
          _handleObstacleStatusMessage(deviceId, data);
        }
```

- [ ] **Step 6: Suscribirse al topic en la inicialización**

Localizar donde se hacen los `subscribe(...)` (junto a los de `steer_torque_mode`). Añadir:

```dart
    client.subscribe('jetson_obstacle_status/global', MqttQos.atMostOnce);
    client.subscribe('telemetry_config/+/jetson_obstacle_status', MqttQos.atMostOnce);
```

- [ ] **Step 7: Mostrar el status en la pantalla**

En `jetson_config_screen.dart`, añadir un campo `String _obstacleStatus = '';` en el State.

En `initState`, suscribirse:

```dart
    mqttService.addObstacleStatusListener(_onObstacleStatusUpdate);
```

En `dispose`:

```dart
    mqttService.removeObstacleStatusListener(_onObstacleStatusUpdate);
```

Método:

```dart
  void _onObstacleStatusUpdate(String deviceId, String status) {
    if (deviceId != widget.dongleId) return;
    setState(() => _obstacleStatus = status);
  }
```

Y en el widget de la tarjeta del modo 3, añadir un `if (_obstacleStatus.isNotEmpty)` que muestre un chip pequeño con el texto correspondiente. Por ejemplo, justo después del bloque `_buildSteerModeCard(mode: 3, ...)`:

```dart
          if (_steerTorqueMode == 3 && _obstacleStatus.isNotEmpty) ...[
            const SizedBox(height: 8),
            Container(
              padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
              decoration: BoxDecoration(
                color: _obstacleStatusColor().withOpacity(0.15),
                border: Border.all(color: _obstacleStatusColor(), width: 1),
                borderRadius: BorderRadius.circular(8),
              ),
              child: Row(
                children: [
                  Icon(Icons.shield_rounded, color: _obstacleStatusColor(), size: 18),
                  const SizedBox(width: 8),
                  Text(_obstacleStatusText(),
                       style: TextStyle(color: _obstacleStatusColor(), fontWeight: FontWeight.w600)),
                ],
              ),
            ),
          ],
```

Helpers:

```dart
  Color _obstacleStatusColor() {
    switch (_obstacleStatus) {
      case 'DODGING_LEFT':
      case 'DODGING_RIGHT':
        return const Color(0xFFF59E0B);
      case 'CANCELED_DRIVER':
        return Colors.grey;
      case 'CANCELED_STALE':
        return const Color(0xFFEF4444);
      default:
        return const Color(0xFF3B82F6);
    }
  }

  String _obstacleStatusText() {
    switch (_obstacleStatus) {
      case 'DODGING_LEFT': return '🚨 Esquivando ←';
      case 'DODGING_RIGHT': return '🚨 Esquivando →';
      case 'CANCELED_DRIVER': return '⚠ Cancelado por conductor';
      case 'CANCELED_STALE': return '❌ Jetson sin respuesta';
      default: return _obstacleStatus;
    }
  }
```

- [ ] **Step 8: Compilar la app**

Run:
```bash
cd /home/drago/Escritorio/PROYECTS/ORBIT/orbit_app && flutter analyze
```

Expected: 0 errores. Warnings de "info" se aceptan.

- [ ] **Step 9: Commit en el repo de la app**

```bash
cd /home/drago/Escritorio/PROYECTS/ORBIT && git add orbit_app/lib/ && git commit -m "feat: 4ª tarjeta COMMA+JETSON e indicador de esquive

- Tarjeta azul para mode=3 entre COMMA y JETSON.
- Listener mqtt jetson_obstacle_status (telemetry_config/+ y global).
- Chip pequeño bajo la tarjeta cuando hay esquive activo.
- Helpers para color/texto de los 4 estados.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 9 — Documentación final

**Files:**
- Modify: `/home/drago/Escritorio/PROYECTS/ORBIT/STEER_TORQUE_MODE.md`

- [ ] **Step 1: Actualizar la tabla de modos**

En `STEER_TORQUE_MODE.md`, actualizar la tabla "Los 3 modos" → "Los 4 modos" añadiendo:

```markdown
| `3` | **COMMA + JETSON** | Igual que MODELO COMMA por defecto. La Jetson puede inyectar esquives temporales (offset de ángulo + curvatura) cuando detecte un obstáculo. Azul. |
```

Y añadir una sección al final referenciando el spec:

```markdown
## Modo 3 (COMMA + JETSON) — Esquive de obstáculos

Ver:
- `sicuem/docs/2026-05-07-comma-jetson-mode-design.md` (spec)
- `sicuem/docs/2026-05-07-comma-jetson-mode-plan.md` (plan)
- `PROTOCOLO_JETSON_MODO3.md` (protocolo Jetson)
```

- [ ] **Step 2: Commit**

```bash
cd /home/drago/Escritorio/PROYECTS/ORBIT && git add STEER_TORQUE_MODE.md && git commit -m "docs: documentar modo 3 COMMA+JETSON

Referencias al spec/plan/protocolo. Tabla actualizada a 4 modos.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Verificación end-to-end (sin coche)

- [ ] **Step 1: Arrancar el comma en simulador**

Run en una terminal:
```bash
cd /home/drago/Escritorio/OPENPILOTSIC/openpilot-img && tools/sim/launch_openpilot.sh
```

- [ ] **Step 2: En otra terminal, simular la Jetson enviando un esquive**

Run:
```bash
cd /home/drago/Escritorio/OPENPILOTSIC/openpilot-img && python3 -c "
import zmq, json, time
ctx = zmq.Context.instance()
s = ctx.socket(zmq.PUSH)
s.connect('tcp://127.0.0.1:5556')
time.sleep(0.5)

# Activar modo 3
from openpilot.common.params import Params
Params().put('SteerTorqueMode', '3')
print('Modo 3 activado')

# Enviar esquive 1500ms a la izquierda
msg = {'obstacle': True, 'intensity': 0.5, 'duration_ms': 1500}
s.send_string(json.dumps(msg))
print(f'Enviado: {msg}')
time.sleep(2.0)

# Estado tras esquive
print('Status final:', Params().get('JetsonObstacleStatus'))
"
```

Expected: ver en logs del comma la entrada `controlsd: ObstaclePulse JSON inválido` (NO debe aparecer), y `JetsonObstacleStatus` pasando por `DODGING_LEFT` y luego vacío. En la UI del Comma el indicador amarillo aparece y desaparece.

- [ ] **Step 3: Verificar comportamiento en cancel**

Repetir Step 2 pero pulsar el freno durante el esquive (en simulador). Status final debe ser `CANCELED_DRIVER`.

- [ ] **Step 4: Verificar coexistencia con modo 1**

Cambiar `SteerTorqueMode` a `1` y enviar un float legacy:
```bash
python3 -c "
import zmq, struct, time
ctx = zmq.Context.instance()
s = ctx.socket(zmq.PUSH)
s.connect('tcp://127.0.0.1:5556')
time.sleep(0.3)
s.send(struct.pack('<f', 0.4))
from openpilot.common.params import Params
time.sleep(0.5)
print('JetsonTorque:', Params().get('JetsonTorque'))
print('JetsonObstaclePulse:', Params().get('JetsonObstaclePulse'))
"
```

Expected: `JetsonTorque` = `b'0.4'`, `JetsonObstaclePulse` no se ha tocado.

---

## Self-Review (resultado)

**1. Spec coverage:**
- §4.1 params nuevos → Task 1 ✓
- §4.2 ObstaclePulseState → Task 2 ✓
- §4.3 controlsd → Task 4 ✓
- §4.4 zmq_client → Task 3 ✓
- §4.5 UI Comma → Task 5 ✓
- §4.6 UI app → Task 8 ✓
- §4.7 MQTT bridge → Task 6 ✓
- §4.8 mqtt_comandos → Task 7 ✓
- §5 protocolo Jetson → ya documentado en `PROTOCOLO_JETSON_MODO3.md` (no requiere task de código).
- §6 cronología → cubierta por la verificación end-to-end.
- §7 tests → Task 2 (unit), Task 3 (zmq integrado), verificación end-to-end (sim).

**2. Placeholder scan:** sin TBD/TODO. Todos los pasos tienen código o comando concreto. La única zona "adapt al método existente" es Task 6 Step 2 (porque el archivo `mqtt_envio_general.py` no se conoce línea a línea sin abrirlo); el step indica explícitamente cómo localizarlo.

**3. Type consistency:** `ObstaclePulseState`, `ingest_new_message`, `get_offsets`, constantes `DEFAULT_*` consistentes en Tasks 2 y 4. Status strings (`DODGING_LEFT`, `DODGING_RIGHT`, `CANCELED_DRIVER`, `CANCELED_STALE`) idénticos en módulo, controlsd, UI Comma y app.
