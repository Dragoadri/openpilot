#!/usr/bin/env python3
"""
Esquive de obstáculos para el modo 3 (COMMA+JETSON).

Modelo "estado continuo" + OVERRIDE absoluto (v4, 2026-05-19):
  - La Jetson envía un JSON {"obstacle": bool, "intensity": float} cuando
    quiere cambiar de estado.
  - El Comma se queda con el ÚLTIMO mensaje recibido y actúa según él:
      · obstacle=true  → Jetson manda; aplica `intensity` como valor
        ABSOLUTO (no como offset sobre Comma). intensity=0 cuenta: fuerza
        torque=0 / curvatura=0 (volante neutro / línea recta).
      · obstacle=false → Jetson cede; manda el modelo de Comma.
  - YA NO existe `duration_ms`.

DEADMAN (v5, mando remoto v2 §5). Antes el watchdog vivía SOLO en el caller
(controlsd comparaba JetsonObstacleTimestamp contra el reloj de PARED). Dos
problemas: (1) el reloj de pared de un comma sin NTP salta minutos en cuanto
sincroniza, y un watchdog que se mide con un reloj que salta o no caduca nunca
o caduca siempre; (2) un watchdog que vive solo en el caller es un watchdog que
se puede olvidar de llamar. Ahora este objeto puede vigilarse a sí mismo con
reloj MONÓTONO: se construye con `ObstaclePulseState(deadman_s=1.0)` y
get_offsets() vuelve a neutro solo si la Jetson lleva más de ese tiempo callada.

El deadman es OPT-IN (deadman_s=0.0 por defecto) porque orbit/test/
test_obstacle_pulse.py fija por contrato el comportamiento antiguo
("test_last_value_persists_indefinitely"). El consumidor real (controlsd) SÍ lo
activa; ver la nota en el informe.

Sub-target (controlsd lee JetsonObstacleApplyTarget):
  - "torque":    actuators.torque = clamp(intensity, -1, 1)  (override)
  - "curvature": desired_curvature = intensity * max_curv     (override)
                 steeringAngleDeg  = intensity * max_angle    (override)

A diferencia de orbit_steering_pulse.py (pulso de dirección, modo banco), este
módulo:
  - lee el último mensaje de la Jetson desde Params (productor: zmq_client en
    otro proceso, no globals)
  - escala intensity [-1,+1] al valor target de ángulo y curvatura
  - cancela por volante presionado, freno, lat inactivo, por silencio de la
    Jetson (deadman) o por recibir un mensaje con obstacle=false (no por
    intensity=0; eso ahora es válido)

Convención de signo: negativo = derecha, positivo = izquierda.
"""
from __future__ import annotations

import time

# Defaults (sembrados al param la primera vez que se lee y devuelve None)
DEFAULT_MAX_ANGLE       = 25.0     # grados — para |intensity|=1.0
DEFAULT_MAX_CURV        = 0.030    # 1/m  — para |intensity|=1.0


class ObstaclePulseState:
    """Estado del esquive activo. Una instancia por proceso controlsd.

    `deadman_s` > 0 activa el watchdog monótono interno (§5 del diseño): si la
    Jetson deja de publicar durante más de ese tiempo, el override vuelve a
    neutro sin depender de que el caller se acuerde de comprobarlo.
    """

    def __init__(self, deadman_s: float = 0.0) -> None:
        self.active: bool = False
        self.intensity: float = 0.0          # ya clampeado a [-1, +1]
        self.last_payload_ts: float = 0.0    # ts (wall-clock) del último mensaje; informativo
        self.last_ingest_mono: float = 0.0   # instante MONÓTONO del último mensaje; es el que manda
        self.deadman_s: float = float(deadman_s)

    def ingest_new_message(self, payload: dict, now: float) -> None:
        """Carga un mensaje recibido de la Jetson (sustituye el actual).

        Modelo "estado continuo" + override absoluto:
          - obstacle=true  → activo SIEMPRE, sin importar intensity (incluye 0).
                             intensity=0 es válido y significa "neutralizar
                             el volante / ir recto". La Jetson manda.
          - obstacle=false → idle. El modelo de Comma manda.

        `now` es el sello de PARED que trae el payload y solo se guarda como
        información; el plazo del deadman se sella aquí con time.monotonic().
        """
        obstacle = bool(payload.get("obstacle", False))
        intensity = float(payload.get("intensity", 0.0))

        # Clamp intensity
        if intensity < -1.0:
            intensity = -1.0
        elif intensity > 1.0:
            intensity = 1.0

        self.last_payload_ts = now
        self.last_ingest_mono = time.monotonic()

        # obstacle=False → idle. (intensity=0 con obstacle=true ya NO es idle).
        if not obstacle:
            self.active = False
            self.intensity = 0.0
            return

        self.active = True
        self.intensity = intensity

    def stale(self, now_mono: float | None = None) -> bool:
        """True si el deadman monótono ha vencido. Con deadman_s=0 nunca vence."""
        if self.deadman_s <= 0.0 or not self.active:
            return False
        if self.last_ingest_mono <= 0.0:
            return True
        ahora = time.monotonic() if now_mono is None else now_mono
        return (ahora - self.last_ingest_mono) > self.deadman_s

    def get_offsets(self, now: float, carstate, lat_active: bool,
                    max_angle: float = DEFAULT_MAX_ANGLE,
                    max_curv: float = DEFAULT_MAX_CURV) -> tuple[float, float, str]:
        """Devuelve (angle_target_deg, curv_target, status) para este frame.

        Semántica OVERRIDE: el caller usa estos valores como TARGET ABSOLUTO
        (asignación), no como offset (suma). Si self.intensity es 0, los
        targets son 0 → torque 0 / curvatura 0.

        status ∈ {"", "DODGING_LEFT", "DODGING_RIGHT", "DODGING_HOLD",
                  "CANCELED_DRIVER", "BSM_BLOCKED_LEFT", "BSM_BLOCKED_RIGHT"}
          - DODGING_HOLD: obstacle=true + intensity=0 (volante neutralizado).
          - BSM_BLOCKED_*: la Jetson quería esquivar a ese lado pero el BSM
            detectó un coche; el caller NO debe aplicar el override (deja
            que mande el modelo de Comma). El estado activo se mantiene:
            si el BSM se libera en el siguiente frame, vuelve a aplicar.
        """
        if not self.active:
            return 0.0, 0.0, ""

        # Orden de cancelación (de mayor a menor prioridad):
        #   0. deadman — la Jetson lleva demasiado callada
        #   1. lat_inactive — sistema sin control lateral, sin status visible
        #   2. driver override (steering/brake) → CANCELED_DRIVER
        #   3. BSM bloquea el lado al que se quiere esquivar → BSM_BLOCKED_*

        # Cancelación: deadman (silencio de la Jetson). Sin él, un
        # {"obstacle":true,"intensity":-1.0} con la Jetson colgada seguía
        # aplicando el offset máximo cada ciclo a 100 Hz indefinidamente.
        if self.stale():
            self._reset()
            return 0.0, 0.0, ""

        # Cancelación: lat inactivo (no es del conductor, status vacío)
        if not lat_active:
            self._reset()
            return 0.0, 0.0, ""

        # Cancelación: conductor (volante o freno)
        if carstate.steeringPressed or carstate.brakePressed:
            self._reset()
            return 0.0, 0.0, "CANCELED_DRIVER"

        # BSM: si la Jetson quiere esquivar a un lado y el BSM detecta un
        # coche en ese lado, NO esquivamos. Mismo criterio que el cambio de
        # carril manual en desire_helper.py: si el coche no tiene BSM
        # disponible, getattr devuelve False → no bloquea.
        # Convención: intensity > 0 → izquierda, < 0 → derecha, 0 → recto.
        left_bs = bool(getattr(carstate, 'leftBlindspot', False))
        right_bs = bool(getattr(carstate, 'rightBlindspot', False))
        if self.intensity > 0.0 and left_bs:
            return 0.0, 0.0, "BSM_BLOCKED_LEFT"
        if self.intensity < 0.0 and right_bs:
            return 0.0, 0.0, "BSM_BLOCKED_RIGHT"

        # Valor target absoluto proporcional a intensity (0 incluido).
        angle_tgt = self.intensity * max_angle
        curv_tgt  = self.intensity * max_curv
        if self.intensity == 0.0:
            status = "DODGING_HOLD"
        elif self.intensity < 0.0:
            status = "DODGING_RIGHT"
        else:
            status = "DODGING_LEFT"
        return angle_tgt, curv_tgt, status

    def _reset(self) -> None:
        self.active = False
        self.intensity = 0.0
