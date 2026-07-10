"""Test integrado: enviar JSON por ZMQ → leer params → modo 1 sigue funcionando."""
import json
import socket
import struct
import time
import unittest

import zmq

from openpilot.common.params import Params
from openpilot.orbit.zmq_client import ZMQClient


def _free_port() -> int:
    """Devuelve un puerto TCP libre en localhost (lo libera antes de devolverlo)."""
    with socket.socket() as s:
        s.bind(("", 0))
        return s.getsockname()[1]


class TestObstacleZmqProtocol(unittest.TestCase):
    """Verifica que zmq_client distingue float legacy (modo 1) y JSON (modo 3)."""

    def setUp(self):
        # Puertos dinámicos para evitar conflictos entre workers de pytest-xdist
        self._img_port = _free_port()
        self._torque_port = _free_port()

        # Cliente apuntando a localhost para test local
        self.client = ZMQClient(jetson_ip="127.0.0.1", img_port=self._img_port,
                                torque_port=self._torque_port, jpeg_quality=10)
        self.client.start()

        # Productor (rol "Jetson"): PUSH a localhost
        self.ctx = zmq.Context.instance()
        self.push = self.ctx.socket(zmq.PUSH)
        self.push.bind(f"tcp://*:{self._torque_port}")
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
        self.assertAlmostEqual(float(self.params.get("JetsonTorque")), 0.42, places=5)

    def test_json_obstacle_message(self):
        # v2: el payload ya no lleva duration_ms (modelo estado continuo)
        msg = {"obstacle": True, "intensity": -0.7}
        self.push.send_string(json.dumps(msg))
        time.sleep(0.3)
        raw = self.params.get("JetsonObstaclePulse")
        self.assertIsNotNone(raw)
        parsed = json.loads(raw)
        self.assertEqual(parsed["obstacle"], True)
        self.assertAlmostEqual(parsed["intensity"], -0.7)
        self.assertNotIn("duration_ms", parsed)

    def test_invalid_json_rejected(self):
        self.params.put("JetsonObstaclePulse", "{}")  # placeholder reconocible
        self.push.send_string("not a json {]")
        time.sleep(0.3)
        # Pulse no debe haberse sobrescrito con basura
        raw = self.params.get("JetsonObstaclePulse")
        self.assertEqual(raw, "{}")

    def test_nan_intensity_rejected(self):
        # JSON acepta NaN como token válido — pero debe rechazarse
        self.params.put("JetsonObstaclePulse", "{}")  # marcador
        self.push.send_string('{"obstacle": true, "intensity": NaN}')
        time.sleep(0.3)
        # Pulse no debe haberse sobrescrito
        self.assertEqual(self.params.get("JetsonObstaclePulse"), "{}")

    def test_missing_intensity_rejected(self):
        self.params.put("JetsonObstaclePulse", "{}")  # marcador
        self.push.send_string('{"obstacle": true}')
        time.sleep(0.3)
        self.assertEqual(self.params.get("JetsonObstaclePulse"), "{}")


if __name__ == "__main__":
    unittest.main()
