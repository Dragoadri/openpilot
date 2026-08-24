#!/usr/bin/env python3
"""Puente de CONSUMO del plano de estado del mando remoto ORBIT v2.

QUE ERA ESTE FICHERO. La "cruceta" (verbos forward / break / tright / tleft). La
seccion 6 del diseno la RETIRA ("Se retiran: forward, break, tright, tleft (la
cruceta)") y la 10.2 dice por que: la flecha de la cruceta frenaba sin etiqueta ni
confirmacion mientras la barra roja exigia leer un modal de cuatro advertencias, es
decir el gradiente de riesgo estaba invertido. Ademas escribia en
car_control.actuators.gas / .brake / .steer, tres campos que en este arbol YA NO
EXISTEN (hoy son actuators.accel y actuators.torque), asi que llevaba meses siendo
codigo muerto que solo parecia funcionar: nadie lo importaba y sus params
(orbit_forward/break/tright/tleft) no los escribe ya nadie.

QUE ES AHORA. El unico sitio donde los tres consumidores de control -- controlsd,
card y desire_helper -- leen el plano de estado v2 (mensaje cereal
`orbitCommandState`, seccion 5). Se comparte a proposito: tres copias del mismo
permiso son tres permisos distintos en cuanto alguien toque una, y este permiso es el
que decide si un actuador se mueve por orden remota.

RELOJ. `deadlineMono` y `benchExpiryMono` son time.monotonic() (CLOCK_MONOTONIC, que
es de sistema y por tanto comparable entre procesos). NO son nanos_since_boot ni
logMonoTime (CLOCK_BOOTTIME, que si cuenta el tiempo suspendido): mezclarlos desplaza
el deadman por el rato que el dispositivo haya estado dormido, y un deadman con el
reloj equivocado es un actuador pegado.

QUE SE PUEDE USAR DEL PLANO Y QUE NO -- IMPORTANTE.
`activeVerb` y `cmdId` solo estan puestos MIENTRAS corre el handler: CommandRouter
llama a store.begin_command() justo antes y a store.end_command() justo despues, y
end_command() los borra sin tocar deadlineMono (a proposito: "el actuador puede seguir
vivo hasta su deadman aunque el handler ya haya vuelto"). Un handler dura microsegundos
y el publicador va a 10 Hz, asi que un consumidor a 100 Hz practicamente NUNCA los ve.
Por eso la autoridad de actuador que se usa aqui es:

    deadlineMono (ventana viva hasta el deadman) + mode + gates + benchArmed

y `activeVerb` solo se usa como condicion ADICIONAL de BLOQUEO (si el plano dice que
hay OTRO verbo corriendo, no actuamos), nunca como condicion necesaria. Quien diga
"que verbo es" es el canal de argumentos de cada verbo (los params que escribe su
handler y solo su handler); quien diga "puedes actuar" es esta ventana.
"""
import time

from openpilot.orbit.command_spec import MODE_CEREAL_NAMES, Gate, Mode

# Nombre del servicio en cereal/services.py: (True, 10., 1).
SERVICIO = "orbitCommandState"

# Verbos retirados en la seccion 6. Se dejan nombrados para que quien busque este
# modulo por lo que hacia antes encuentre el motivo y no lo reimplemente.
CRUCETA_RETIRADA = ("forward", "break", "tright", "tleft")

# Enum Mode de cereal -> Mode de command_spec. El .capnp devuelve el nombre como cadena.
_MODE_DESDE_CEREAL = {nombre: modo for modo, nombre in MODE_CEREAL_NAMES.items()}

# Params de ACTUADOR que puede dejar armados una orden remota. disarm_all los devuelve
# todos a neutro (seccion 2: "bajar autoridad siempre se acepta"). La lista vive aqui,
# junto a los consumidores que los leen, y no en el handler: el handler no sabe que
# actuadores existen, los consumidores si.
ACTUADORES_BOOL = (
  "brutebreak_active",       # deceleracion asistida (antes brutebreak)
  "ForceLaneChangeLeft",     # cambio de carril remoto
  "ForceLaneChangeRight",
  "orbit_speed_increase",    # cruise_delta
  "orbit_speed_decrease",
  "overtakingActive",        # maquina de adelantamiento (sin implementar, seccion 6)
  "sic_adelantar",
)
ACTUADORES_INT = (
  # 0 = Comma. Apaga de una vez el override de torque de la Jetson (1), el TEST MAX (2)
  # y los offsets de esquive (3): controlsd solo los aplica con su modo seleccionado.
  ("SteerTorqueMode", 0),
)
ACTUADORES_REMOVER = (
  "orbit_steering_pulse",    # pulso de direccion (banco)
)


class OrbitAuthority:
  """Instantanea del plano de estado. Se construye una vez por ciclo y no se muta.

  Todos los valores por defecto son los de "sin autoridad": si el mensaje no llega, si
  llega invalido o si algo revienta al leerlo, el consumidor ve exactamente lo mismo que
  si el mando estuviera apagado. Fail-closed, seccion 4.2.
  """
  __slots__ = ("fresh", "mode", "gates", "active_verb", "cmd_id", "seq", "deadline_mono",
               "link_deadline_mono", "bench_armed", "bench_expiry_mono", "clock_synced",
               "last_ack_phase")

  def __init__(self, fresh=False, mode=Mode.OBSERVER, gates=0, active_verb="", cmd_id="",
               seq=0, deadline_mono=0.0, link_deadline_mono=0.0, bench_armed=False,
               bench_expiry_mono=0.0, clock_synced=False, last_ack_phase="none"):
    self.fresh = bool(fresh)
    self.mode = mode
    self.gates = int(gates)
    self.active_verb = active_verb
    self.cmd_id = cmd_id
    self.seq = int(seq)
    self.deadline_mono = float(deadline_mono)
    self.link_deadline_mono = float(link_deadline_mono)
    self.bench_armed = bool(bench_armed)
    self.bench_expiry_mono = float(bench_expiry_mono)
    self.clock_synced = bool(clock_synced)
    self.last_ack_phase = last_ack_phase

  # ------------------------------------------------------------------ predicados

  def window_open(self, now_mono: float) -> bool:
    """Ventana de autoridad de actuador viva. ES el deadman (seccion 5).

    Comparacion con `>` y no `>=`: con deadline_mono == 0.0 (sin comando) o NaN el
    resultado es False, que es la respuesta segura.
    """
    return self.fresh and self.deadline_mono > now_mono

  def remaining_s(self, now_mono: float) -> float:
    return max(0.0, self.deadline_mono - now_mono) if self.fresh else 0.0

  def mode_at_least(self, mode_min) -> bool:
    return self.fresh and int(self.mode) >= int(mode_min)

  def has_gates(self, requeridos: int) -> bool:
    return self.fresh and (self.gates & int(requeridos)) == int(requeridos)

  def missing_gates(self, requeridos: int) -> list:
    """Nombres de los gates que faltan, para el motivo del ACK / del log."""
    if not self.fresh:
      return ["LINK"]
    return [g.name for g in Gate if (int(requeridos) & g) and not (self.gates & g)]

  def bench_ok(self, now_mono: float) -> bool:
    """Armado de banco vigente AHORA.

    La caducidad se recomprueba contra el reloj monotono en cada consulta y no solo
    contra el bit `benchArmed`: entre que el publicador refresca el param (1 Hz) y el
    consumidor actua pueden pasar los 300 s de TTL del armado (seccion 4.1).
    """
    return self.fresh and self.bench_armed and self.bench_expiry_mono > now_mono

  def busy_with_other(self, verb: str) -> bool:
    """True si el plano dice que esta corriendo OTRO verbo.

    Solo bloquea; no habilita (ver la nota del encabezado: activeVerb casi nunca es
    observable). Bloquear de mas resta autoridad, que es la direccion segura.
    """
    return bool(self.active_verb) and bool(verb) and self.active_verb != verb

  def allows(self, verb: str, mode_min, gates_req: int, now_mono: float,
             requiere_banco: bool = False) -> tuple:
    """Permiso completo para mover un actuador. Devuelve (ok, motivo).

    El motivo usa el vocabulario de codigos de la seccion 3.3 (LINK / MODE / EXPIRED /
    CLOCK / GATE_<nombre>) para que el consumidor lo pueda registrar y el router lo
    pueda convertir en ACK sin traducir nada.
    """
    if not self.fresh:
      return False, "LINK"
    if not self.clock_synced:
      # Seccion 3.2: mejor un coche que no obedece que uno que obedece una orden de
      # hace diez minutos.
      return False, "CLOCK"
    if not self.mode_at_least(mode_min):
      return False, "MODE"
    if requiere_banco and not self.bench_ok(now_mono):
      return False, "MODE"
    if not self.window_open(now_mono):
      return False, "EXPIRED"
    if self.busy_with_other(verb):
      return False, "BUSY"
    faltan = self.missing_gates(gates_req)
    if faltan:
      return False, f"GATE_{faltan[0]}"
    return True, "OK"


# Instancia compartida de "sin autoridad". Es inmutable en la practica (nadie escribe
# sus campos) y ahorra construir un objeto por ciclo a 100 Hz cuando el mando no esta
# haciendo nada, que es el 99.9 % del tiempo.
SIN_AUTORIDAD = OrbitAuthority()


class OrbitCommandLink:
  """Lector del plano de estado v2 para un consumidor de control.

  Crea su PROPIO SubMaster de un solo servicio en vez de meter 'orbitCommandState' en
  el SubMaster principal del proceso. Motivos: (1) los tres consumidores quedan
  identicos, (2) no se toca la lista de servicios que replican process_replay y los
  logs de referencia, y (3) si cereal no esta disponible el consumidor se queda sin
  mando en lugar de no arrancar.

  msgq NO es thread-safe: el SubMaster se crea y se lee SIEMPRE desde el mismo hilo que
  llama a poll(). Por eso la creacion es perezosa (en el primer poll) y no en __init__.
  """

  def __init__(self, sm=None, etiqueta: str = "orbit"):
    self._sm = sm            # SubMaster ajeno ya suscrito a SERVICIO (opcional)
    self._propio = sm is None
    self._roto = False
    self._etiqueta = etiqueta
    self._aviso_dado = False

  def _ensure_sm(self):
    if self._sm is not None or self._roto:
      return self._sm
    try:
      import cereal.messaging as messaging
      self._sm = messaging.SubMaster([SERVICIO])
    except Exception:
      # Sin cereal no hay plano de estado y por tanto no hay mando remoto. Se marca
      # roto para no reintentar el import en cada ciclo del loop de control.
      self._roto = True
      self._sm = None
    return self._sm

  def poll(self) -> OrbitAuthority:
    """Un tick de lectura. NUNCA lanza: lo llama el hot path de 100 Hz."""
    try:
      sm = self._ensure_sm()
      if sm is None:
        return SIN_AUTORIDAD
      if self._propio:
        sm.update(0)  # no bloqueante: este SubMaster no es el que marca el ritmo
      if not sm.alive[SERVICIO] or not sm.valid[SERVICIO]:
        # Publicador muerto o mensaje invalido = sin autoridad. Es el caso de "matar el
        # proceso de telemetria con un viaje abierto" de la seccion 12: ningun actuador
        # puede quedarse pegado porque el que daba permiso dejo de hablar.
        return SIN_AUTORIDAD
      st = sm[SERVICIO]
      return OrbitAuthority(
        fresh=True,
        mode=_MODE_DESDE_CEREAL.get(str(st.mode), Mode.OBSERVER),
        gates=int(st.gates),
        active_verb=str(st.activeVerb),
        cmd_id=str(st.cmdId),
        seq=int(st.seq),
        deadline_mono=float(st.deadlineMono),
        link_deadline_mono=float(st.linkDeadlineMono),
        bench_armed=bool(st.benchArmed),
        bench_expiry_mono=float(st.benchExpiryMono),
        clock_synced=bool(st.clockSynced),
        last_ack_phase=str(st.lastAckPhase),
      )
    except Exception:
      if not self._aviso_dado:
        self._aviso_dado = True
        try:
          from openpilot.common.swaglog import cloudlog
          cloudlog.exception(f"[Orbit] {self._etiqueta}: fallo leyendo {SERVICIO}, mando remoto desactivado este ciclo")
        except Exception:
          pass
      return SIN_AUTORIDAD


def disarm_all_actuators(params=None) -> list:
  """Devuelve a NEUTRO todos los actuadores que puede dejar armados una orden remota.

  Lo llama el handler de `disarm_all` (unico verbo sin modo, sin gate y sin TTL) y el
  boton fisico de la pantalla. Corre en el hilo del manager, NO en el loop de control:
  aqui si se puede escribir Params con block=True.

  Devuelve la lista de claves tocadas para que el ACK diga que se desarmo de verdad.
  """
  tocados = []
  if params is None:
    try:
      from openpilot.common.params import Params
      params = Params()
    except Exception:
      return tocados

  for clave in ACTUADORES_BOOL:
    try:
      if params.get_bool(clave):
        params.put_bool(clave, False, block=True)
        tocados.append(clave)
    except Exception:
      pass

  for clave, neutro in ACTUADORES_INT:
    try:
      # put() exige el tipo NATIVO de la clave: put("0") sobre un INT es un TypeError
      # que Params se traga y deja el valor viejo -- es decir, un desarme que no desarma.
      if params.get(clave) != neutro:
        params.put(clave, int(neutro), block=True)
        tocados.append(clave)
    except Exception:
      pass

  for clave in ACTUADORES_REMOVER:
    try:
      if params.get(clave):
        params.remove(clave)
        tocados.append(clave)
    except Exception:
      pass

  # Esquive de la Jetson (modo 3): no basta con SteerTorqueMode=0 si alguien vuelve a
  # seleccionar el modo 3 con el ultimo payload todavia en "obstacle": true. Se inyecta
  # un estado neutro Y se avanza el timestamp, porque controlsd solo ingiere el payload
  # cuando el timestamp crece. block=True y en este orden: si el timestamp aterrizara
  # antes que el payload, controlsd releeria el payload VIEJO.
  try:
    params.put("JetsonObstaclePulse", '{"obstacle": false, "intensity": 0.0}', block=True)
    params.put("JetsonObstacleTimestamp", f"{time.time_ns() / 1e9:.3f}", block=True)
    tocados.append("JetsonObstaclePulse")
  except Exception:
    pass

  return tocados
