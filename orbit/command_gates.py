#!/usr/bin/env python3
"""Evaluador de precondiciones del mando remoto ORBIT v2 (seccion 4.2 del diseno).

GateMonitor mantiene un SubMaster a 10 Hz EN EL PROCESO MANAGER (el hilo ORBIT) y se
inyecta por referencia en el router y en el publicador de estado, igual que ya se hace
con el CameraSender en _link_camera_to_comandos.

Dos reglas que no se negocian:

  * CERO lecturas de Params en el camino de decision. Params.get es un open()+read()
    sobre eMMC; hacerlo al evaluar un comando mete I/O de disco en el camino de una
    maniobra. Lo unico que se lee de Params aqui son el modo y el armado de banco, y se
    leen en el TICK de 10 Hz con divisor a 1 Hz, nunca dentro de evaluate().
  * Fail-closed en todo. Si un servicio no esta vivo, si el campo no existe o si algo
    lanza, el gate queda ROJO. Un gate que se cae en verde ante un error es un gate que
    autoriza una maniobra justo cuando el coche esta peor informado.

El GateMonitor filtra pronto; cada consumidor (controlsd, card, desire_helper) reevalua
ademas su propio gate en el ciclo en que actua. Defensa en profundidad, nunca un solo
punto (seccion 4.2, ultimo parrafo).
"""
import threading

from openpilot.common.time_helpers import system_time_valid
from openpilot.orbit.command_spec import Gate, ahora_mono

# Servicios de la seccion 4.2.
GATE_SERVICES_BASE = ("carState", "selfdriveState", "carControl", "carParams", "deviceState")

# DESVIACION DELIBERADA de la lista literal de la seccion 4.2, y verificada en el arbol:
# esa lista de cinco servicios NO contiene las fuentes que la propia tabla de gates de la
# misma seccion declara. `CALIBRATED` dice "fuente: liveCalibration" y `DRIVER_PRESENT`
# dice "driverMonitoringState.faceDetected". Sin estos dos servicios ambos gates serian
# constantes -- y un gate constante en verde es peor que no tenerlo. Se anaden.
GATE_SERVICES_EXTRA = ("liveCalibration", "driverMonitoringState")

GATE_SERVICES = GATE_SERVICES_BASE + GATE_SERVICES_EXTRA

# Rango de maniobra por defecto (seccion 6, fila lane_change). Es tambien el que define
# el bit speedRange de la mascara publicada: la mascara es global y necesita UNA
# referencia; los verbos con rango propio lo llevan en spec.limits y evaluate() usa ese.
V_MIN_MANIOBRA_KPH = 40.0
V_MAX_MANIOBRA_KPH = 130.0

# Edad maxima del ultimo trafico valido del enlace para considerarlo fresco (seccion 4.2,
# gate LINK_FRESH). 5 s: el watchdog de enlace de la seccion 5 es de segundos, el de
# actuador (centenas de ms) vive en controlsd y no es esto.
LINK_FRESH_MAX_S = 5.0

# Cada cuanto se releen del disco el modo y el armado de banco. 1 Hz sobre un tick de
# 10 Hz: el usuario no nota 1 s de retardo al cambiar de modo desde la pantalla y a
# cambio no hay I/O de disco a 10 Hz.
PARAMS_REFRESH_S = 1.0

# Edad maxima de la mascara para darla por vigente. El tick va a 10 Hz, asi que 0.5 s
# son CINCO ticks perdidos.
#
# REGLA DURA (no es una optimizacion, es la regla de seguridad del subsistema): si el
# GateMonitor muere, se queda bloqueado o su hilo deja de correr, la ultima mascara que
# dejo en RAM sigue ahi y se leeria como si fuera de ahora. Una mascara congelada EN
# VERDE es lo peor que puede pasar aqui: autoriza una maniobra con la foto del coche de
# hace un minuto. Por eso, pasada esta edad, la mascara vale CERO y evaluate() falla
# todos los gates que se le pidan. Nunca al reves.
MASK_MAX_AGE_S = 0.5


class GateMonitor:
  """Calcula la mascara de gates a 10 Hz. Un solo objeto por proceso, compartido."""

  def __init__(self, sm=None, params=None, servicios=None, link_fresh_max_s: float = LINK_FRESH_MAX_S,
               mask_max_age_s: float = MASK_MAX_AGE_S):
    self._servicios = tuple(servicios) if servicios is not None else GATE_SERVICES
    self._sm = sm
    self._sm_inyectado = sm is not None
    self._params = params
    self._link_fresh_max_s = float(link_fresh_max_s)
    self._mask_max_age_s = float(mask_max_age_s)

    self._lock = threading.Lock()
    self._mask = 0
    self._v_ego_kph = 0.0
    self._standstill = True
    self._onroad = False
    self._brand = ""
    self._platform = ""
    self._carstate_ok = False
    self._ultimo_enlace_mono = 0.0   # 0.0 = nunca hubo trafico valido -> LINK_FRESH rojo
    self._clock_ok = False
    self._proximo_clock_mono = 0.0
    # 0.0 = update() no ha corrido nunca -> la mascara esta RANCIA y vale cero.
    self._ultimo_update_mono = 0.0

  # ------------------------------------------------------------------ ciclo de vida

  def ensure_sm(self):
    """Crea el SubMaster perezosamente y SOLO en el hilo que hara update().

    Perezoso a proposito: msgq no es thread-safe y construir el SubMaster en __init__
    lo ataria al hilo que construye el objeto, que no tiene por que ser el que lo
    consume. Si la creacion falla se devuelve None y todos los gates quedan rojos, en
    vez de tumbar el subsistema ORBIT entero.
    """
    if self._sm is None:
      try:
        from cereal import messaging
        self._sm = messaging.SubMaster(list(self._servicios))
      except Exception:
        self._sm = None
    return self._sm

  def reset_sm(self) -> None:
    """Tira el SubMaster para que lo vuelva a crear el hilo que llame a update().

    Lo usa el relevo del hilo del plano de mando (CommandPlane.start tras un reinicio del
    supervisor): msgq NO es thread-safe, asi que un SubMaster construido por el hilo que
    acaba de morir no se puede seguir leyendo desde el hilo nuevo. Un SubMaster INYECTADO
    (tests) no se toca: no lo construimos nosotros.
    """
    if self._sm_inyectado:
      return
    self._sm = None
    with self._lock:
      # Sin datos nuevos la mascara vuelve a cero Y se marca rancia: durante el relevo no
      # hay nadie mirando el coche, y eso es exactamente un gate en rojo.
      self._mask = 0
      self._carstate_ok = False
      self._ultimo_update_mono = 0.0

  # ------------------------------------------------------------------------- lectura

  def _campo(self, servicio: str, camino: str, por_defecto=None):
    """Lee un campo anidado del SubMaster devolviendo `por_defecto` ante cualquier fallo."""
    try:
      obj = self._sm[servicio]
      for parte in camino.split("."):
        obj = getattr(obj, parte)
      return obj
    except Exception:
      return por_defecto

  def _vivo(self, servicio: str) -> bool:
    """Servicio recibido hace poco. Si no, el gate que dependa de el queda rojo."""
    try:
      return bool(self._sm.alive[servicio] and self._sm.valid[servicio])
    except Exception:
      return False

  def _visto(self, servicio: str) -> bool:
    """Servicio recibido ALGUNA vez. Para carParams, que se publica a 0.02 Hz y cuya
    ventana de `alive` (500 s) no dice gran cosa."""
    try:
      return bool(self._sm.seen[servicio])
    except Exception:
      return False

  # -------------------------------------------------------------------------- update

  def update(self, timeout_ms: int = 0) -> int:
    """Un tick. Llamar a 10 Hz desde el hilo ORBIT. Devuelve la mascara nueva.

    timeout_ms=0: no se bloquea nunca. El ritmo lo pone el Ratekeeper del llamante; si
    este update() bloqueara, bloquearia tambien la publicacion de orbitCommandState y
    con ella el deadman que leen los consumidores.
    """
    sm = self.ensure_sm()
    if sm is not None:
      try:
        sm.update(timeout_ms)
      except Exception:
        pass

    ahora = ahora_mono()

    # El reloj se comprueba a 1 Hz: system_time_valid() hace un stat() de /lib/systemd.
    if ahora >= self._proximo_clock_mono:
      self._proximo_clock_mono = ahora + PARAMS_REFRESH_S
      try:
        self._clock_ok = bool(system_time_valid())
      except Exception:
        self._clock_ok = False

    mask = 0
    v_ego_kph = 0.0
    standstill = True
    onroad = False
    brand = ""
    platform = ""
    # Sin carState fresco NO hay velocidad conocida. Se lleva aparte porque evaluate()
    # recalcula SPEED_RANGE con el rango propio del verbo: con carState muerto, v_ego
    # valdria 0.0 y los verbos de banco (rango 0-5 km/h) verian el gate en VERDE con el
    # coche en marcha. Fail-open exactamente en los verbos fisicos.
    carstate_ok = False

    if sm is not None:
      # --- ENGAGED: sin openpilot enganchado no hay a quien dar la orden.
      if self._vivo("selfdriveState") and bool(self._campo("selfdriveState", "enabled", False)):
        mask |= Gate.ENGAGED

      # --- LAT_ACTIVE / LONG_ACTIVE: el eje concreto tiene que estar bajo control.
      if self._vivo("carControl"):
        if bool(self._campo("carControl", "latActive", False)):
          mask |= Gate.LAT_ACTIVE
        if bool(self._campo("carControl", "longActive", False)):
          mask |= Gate.LONG_ACTIVE

      if self._vivo("carState"):
        carstate_ok = True
        v_ego = float(self._campo("carState", "vEgo", 0.0) or 0.0)
        v_ego_kph = v_ego * 3.6
        standstill = bool(self._campo("carState", "standstill", True))

        # --- SPEED_RANGE con el rango de maniobra por defecto (ver constantes).
        if V_MIN_MANIOBRA_KPH <= v_ego_kph <= V_MAX_MANIOBRA_KPH:
          mask |= Gate.SPEED_RANGE

        # --- DRIVER_IDLE: el conductor manda; cualquier intervencion cancela.
        if not (bool(self._campo("carState", "gasPressed", True)) or
                bool(self._campo("carState", "brakePressed", True)) or
                bool(self._campo("carState", "steeringPressed", True))):
          mask |= Gate.DRIVER_IDLE

        # --- DRIVER_PRESENT: cinturon, puertas y cara.
        # OJO: el diseno dice "driverMonitoringState.faceDetected" y ESE CAMPO NO EXISTE
        # en este arbol -- el plano esta en DriverMonitoringStateDEPRECATED. El vivo esta
        # anidado en visionPolicyState.faceDetected, y policy.py lo escribe SIEMPRE (es la
        # salida cruda del modelo, no depende de que la politica activa sea vision), asi
        # que se puede leer tal cual sin ramificar por activePolicy.
        cara = bool(self._campo("driverMonitoringState", "visionPolicyState.faceDetected", False)) \
            and self._vivo("driverMonitoringState")
        if cara and not bool(self._campo("carState", "seatbeltUnlatched", True)) \
                and not bool(self._campo("carState", "doorOpen", True)):
          mask |= Gate.DRIVER_PRESENT

      # --- CALIBRATED
      if self._vivo("liveCalibration"):
        try:
          from cereal import log
          if self._campo("liveCalibration", "calStatus") == log.LiveCalibrationData.Status.calibrated:
            mask |= Gate.CALIBRATED
        except Exception:
          pass

      # --- NOT_DEGRADED: en dashcam/passive la mitad de los verbos no puede aplicarse, y
      # hoy la app no lo distinguiria de "el coche no responde".
      if self._visto("carParams"):
        brand = str(self._campo("carParams", "brand", "") or "")
        # Plataforma para el descriptor de capacidades (seccion 3.5): la app solo pinta
        # lo que ESTE coche declara, y "ford" a secas no basta para saber si hay BSM.
        platform = str(self._campo("carParams", "carFingerprint", "") or "")
        if not bool(self._campo("carParams", "dashcamOnly", True)) and \
           not bool(self._campo("carParams", "passive", True)):
          mask |= Gate.NOT_DEGRADED

      if self._vivo("deviceState"):
        onroad = bool(self._campo("deviceState", "started", False))

    # --- LINK_FRESH: edad del ultimo trafico valido del enlace.
    if self._ultimo_enlace_mono > 0.0 and (ahora - self._ultimo_enlace_mono) < self._link_fresh_max_s:
      mask |= Gate.LINK_FRESH

    # --- CLOCK_SYNCED: sin esto no se acepta ningun mando (seccion 3.2).
    if self._clock_ok:
      mask |= Gate.CLOCK_SYNCED

    with self._lock:
      self._mask = int(mask)
      self._v_ego_kph = v_ego_kph
      self._standstill = standstill
      self._onroad = onroad
      self._brand = brand
      self._platform = platform
      self._carstate_ok = carstate_ok
      # Sello de vigencia: lo mira todo lo que lee la mascara. Se pone AQUI, al final del
      # tick, y no al principio: si el cuerpo de update() lanzara a medias, la mascara no
      # se daria por vigente.
      self._ultimo_update_mono = ahora
    return int(mask)

  # ---------------------------------------------------------------------- consultas

  def _rancio(self, ahora: float) -> bool:
    """True si la mascara no se ha refrescado dentro de la ventana. Sin lock: lo llaman
    los que ya lo tienen cogido."""
    return self._ultimo_update_mono <= 0.0 or (ahora - self._ultimo_update_mono) > self._mask_max_age_s

  @property
  def stale(self) -> bool:
    """El GateMonitor no esta publicando datos frescos (hilo muerto, bloqueado o aun sin
    arrancar). Quien lo vea a True tiene que tratar TODOS los gates como rojos."""
    with self._lock:
      return self._rancio(ahora_mono())

  @property
  def age_s(self) -> float:
    with self._lock:
      if self._ultimo_update_mono <= 0.0:
        return float("inf")
      return ahora_mono() - self._ultimo_update_mono

  @property
  def mask(self) -> int:
    """Mascara VIGENTE. Rancia = 0, es decir todos los gates en rojo.

    Devolver la ultima mascara conocida seria devolver la foto del coche de hace un
    minuto; si en esa foto el coche estaba enganchado y a 90 km/h, autorizaria un cambio
    de carril con el coche ya parado o con el conductor al volante.
    """
    with self._lock:
      if self._rancio(ahora_mono()):
        return 0
      return self._mask

  @property
  def v_ego_kph(self) -> float:
    with self._lock:
      return self._v_ego_kph

  @property
  def standstill(self) -> bool:
    with self._lock:
      return self._standstill

  @property
  def onroad(self) -> bool:
    with self._lock:
      return self._onroad

  @property
  def brand(self) -> str:
    with self._lock:
      return self._brand

  @property
  def platform(self) -> str:
    with self._lock:
      return self._platform

  @property
  def clock_synced(self) -> bool:
    """Rancio = NO sincronizado. Sin nadie mirando el reloj no se da por bueno."""
    with self._lock:
      if self._rancio(ahora_mono()):
        return False
      return bool(self._mask & Gate.CLOCK_SYNCED)

  def note_link(self, cuando_mono: float | None = None) -> None:
    """Marca trafico valido del enlace (comando aceptado o heartbeat). Alimenta LINK_FRESH."""
    with self._lock:
      self._ultimo_enlace_mono = ahora_mono() if cuando_mono is None else float(cuando_mono)

  @property
  def link_age_s(self) -> float:
    with self._lock:
      if self._ultimo_enlace_mono <= 0.0:
        return float("inf")
      return ahora_mono() - self._ultimo_enlace_mono

  # --------------------------------------------------------------------- evaluacion

  def evaluate(self, spec, args=None) -> tuple[bool, list]:
    """Evalua los gates que exige `spec`. Devuelve (ok, [Gate fallados]).

    NO toca disco ni cereal: lee la mascara que dejo el ultimo update(). SPEED_RANGE se
    recalcula aqui con el rango propio del verbo (spec.limits), porque el bit de la
    mascara publicada usa el rango de maniobra por defecto y hay verbos -- los de banco --
    cuyo rango es el contrario (velocidad BAJA).
    """
    requeridos = int(getattr(spec, "gates", 0) or 0)
    if requeridos == 0:
      return True, []

    with self._lock:
      if self._rancio(ahora_mono()):
        # Mascara rancia: el hilo del plano no esta ticando. TODOS los gates pedidos
        # fallan. Es la misma regla que el fail-closed de _vivo(), pero un nivel mas
        # arriba: alli se cae un servicio, aqui se cae el evaluador entero.
        return False, [g for g in Gate if requeridos & g]
      mask = self._mask
      v_ego_kph = self._v_ego_kph
      carstate_ok = self._carstate_ok

    fallados = []
    for gate in Gate:
      if not (requeridos & gate):
        continue
      if gate is Gate.SPEED_RANGE:
        limites = getattr(spec, "limits", {}) or {}
        v_min = float(limites.get("v_min_kph", V_MIN_MANIOBRA_KPH))
        v_max = float(limites.get("v_max_kph", V_MAX_MANIOBRA_KPH))
        if not carstate_ok or not (v_min <= v_ego_kph <= v_max):
          fallados.append(gate)
        continue
      if not (mask & gate):
        fallados.append(gate)

    return (len(fallados) == 0), fallados
