#!/usr/bin/env python3
"""Plano de estado del mando remoto ORBIT v2 (seccion 5 del diseno).

Publica el mensaje cereal `orbitCommandState` a 10 Hz. Es lo que leen controlsd, card y
desire_helper para reevaluar su propio gate en el ciclo en que actuan.

POR QUE CEREAL Y NO PARAMS. Params.put en este arbol es mkstemp+fsync sobre eMMC. A
2-10 Hz ya provoco commIssue y por eso existe _defer_param_put en controlsd. Un plano de
estado que se escribe diez veces por segundo en disco no es un plano de estado: es una
fuente de jitter en el hot path de 100 Hz.

RELOJES. deadlineMono y benchExpiryMono son time.monotonic() (CLOCK_MONOTONIC), que es de
SISTEMA: el consumidor los compara con su propio time.monotonic(). NO son nanos_since_boot
ni logMonoTime (CLOCK_BOOTTIME): mezclarlos da un deadline desplazado por el tiempo que el
dispositivo haya estado suspendido, y un deadman con el reloj equivocado es un actuador
pegado.

Los unicos Params que se leen aqui son el modo, el armado de banco y el disparo de
disarm_all, y se leen en el tick con divisor a 1 Hz -- nunca en el camino de decision de
un comando (eso lo hace el router contra este objeto, que ya lo tiene en RAM).
"""
import threading
import time

from openpilot.common.swaglog import cloudlog
from openpilot.orbit.command_spec import (MODE_CEREAL_NAMES, PHASES, Mode, Phase, ahora_epoch_ms,
                                          ahora_mono, parse_mode)

# Nombre del servicio en cereal/services.py (True, 10., 1).
SERVICIO = "orbitCommandState"
FRECUENCIA_HZ = 10.0

# Params del mando (registrados en common/params_keys.h como
# CLEAR_ON_MANAGER_START | CLEAR_ON_OFFROAD_TRANSITION: jamas PERSISTENT, seccion 4.1).
PARAM_MODE = "OrbitCommandMode"          # INT   0..3
PARAM_BENCH_ARMED = "OrbitBenchArmed"    # BOOL
PARAM_BENCH_EXPIRY = "OrbitBenchExpiry"  # STRING, epoch ms como TEXTO
PARAM_DISARM_ALL = "OrbitDisarmAll"      # BOOL, disparo one-shot

PARAMS_REFRESH_S = 1.0

# Tope de UInt32 del campo `seq` de cereal.
SEQ_MAX = 0xFFFFFFFF


class CommandStateStore:
  """Estado compartido del mando. Lo escribe el router (hilo worker) y lo lee el
  publicador (hilo ORBIT); por eso todo pasa por un lock y no hay ningun objeto mutable
  que se devuelva por referencia."""

  def __init__(self, params=None):
    self._lock = threading.RLock()
    self._params = params

    self.mode = Mode.OBSERVER
    self.active_verb = ""
    self.cmd_id = ""
    self.seq = 0
    self.deadline_mono = 0.0        # 0.0 = no hay actuador remoto vivo
    self.link_deadline_mono = 0.0
    self.last_ack_phase = Phase.NONE
    self.last_reason = ""
    self.bench_armed = False
    self.bench_expiry_mono = 0.0
    # Caducidad del modo concedido, en reloj MONOTONO. 0 = sin caducidad (observador).
    self.mode_expiry_mono = 0.0
    self.clock_synced = False

    self._proximo_refresh_mono = 0.0
    self._aviso_bench_sin_caducidad = False

  # ------------------------------------------------------------------------ params

  def _get_params(self):
    if self._params is None:
      try:
        from openpilot.common.params import Params
        self._params = Params()
      except Exception:
        self._params = None
    return self._params

  def get_params(self):
    """Instancia de Params compartida (o el doble inyectado). La usa el desarme por boton
    fisico para no abrir una segunda."""
    return self._get_params()

  def refresh_params(self, forzar: bool = False) -> None:
    """Relee modo y armado de banco. Se llama desde el TICK, nunca al evaluar un comando."""
    ahora = ahora_mono()
    if not forzar and ahora < self._proximo_refresh_mono:
      return
    self._proximo_refresh_mono = ahora + PARAMS_REFRESH_S

    # La caducidad del modo se comprueba ANTES de tocar el disco y no depende de el: si
    # Params no esta disponible (build sin recompilar `common`, disco lleno), el early
    # return de abajo dejaria un modo maniobra caducado vivo en RAM para siempre. La
    # autoridad tiene que caer sola aunque falle todo lo demas.
    caduco = False
    with self._lock:
      if (self.mode is not Mode.OBSERVER and self.mode_expiry_mono > 0.0
          and ahora > self.mode_expiry_mono):
        cloudlog.warning(f"[Orbit] el modo {self.mode.name} caduco: se vuelve a observador")
        self.mode = Mode.OBSERVER
        self.mode_expiry_mono = 0.0
        caduco = True

    params = self._get_params()
    if params is None:
      return

    # --- modo
    modo = Mode.OBSERVER
    try:
      # get() devuelve int nativo en una clave INT, o None si nunca se escribio.
      crudo = params.get(PARAM_MODE)
      modo = parse_mode(crudo) or Mode.OBSERVER
    except Exception:
      # Clave desconocida (build de common sin recompilar) o disco: observador.
      # Fail-closed: el modo por defecto no permite mover el coche.
      modo = Mode.OBSERVER

    # --- armado de banco: BOOL + caducidad en epoch ms como TEXTO.
    armado = False
    expiry_mono = 0.0
    try:
      if params.get_bool(PARAM_BENCH_ARMED):
        crudo = params.get(PARAM_BENCH_EXPIRY)
        expiry_ms = int(str(crudo).strip()) if crudo not in (None, "") else 0
        if expiry_ms > 0:
          # La caducidad viaja en epoch (es lo que puede escribir la pantalla del comma y
          # lo que puede leer la app), pero el plazo se MIDE en monotono: se convierte una
          # sola vez, aqui. Con el reloj de pared torcido la conversion sale mal, asi que
          # el router exige ademas CLOCK_SYNCED para cualquier verbo de banco.
          restante_s = (expiry_ms - ahora_epoch_ms()) / 1000.0
          if restante_s > 0:
            armado = True
            expiry_mono = ahora + restante_s
        elif not self._aviso_bench_sin_caducidad:
          self._aviso_bench_sin_caducidad = True
          cloudlog.error("[Orbit] OrbitBenchArmed activo SIN OrbitBenchExpiry: se considera NO armado (fail-closed)")
    except Exception:
      armado = False
      expiry_mono = 0.0

    if caduco:
      # El modo persistido en disco todavia dice "maniobra": si se dejara, el propio valor
      # leido arriba resucitaria el modo que acaba de caducar en el siguiente tick.
      modo = Mode.OBSERVER
      try:
        params.put(PARAM_MODE, int(Mode.OBSERVER))
      except Exception:
        cloudlog.exception("[Orbit] no se pudo persistir la caducidad del modo")

    with self._lock:
      self.mode = modo
      self.bench_armed = armado
      self.bench_expiry_mono = expiry_mono

  def consume_disarm_request(self) -> bool:
    """Lee y limpia el disparo one-shot OrbitDisarmAll (boton fisico de la pantalla).

    Es redundante con el verbo disarm_all A PROPOSITO: bajar autoridad no puede depender
    de que el enlace MQTT siga vivo.
    """
    params = self._get_params()
    if params is None:
      return False
    try:
      if not params.get_bool(PARAM_DISARM_ALL):
        return False
      params.put_bool(PARAM_DISARM_ALL, False)
      return True
    except Exception:
      return False

  # ------------------------------------------------------------------------- estado

  def set_mode(self, modo, expira_s: float = 0.0) -> Mode:
    """Cambia el modo en RAM y lo persiste. put() exige el tipo NATIVO de la clave: en una
    clave INT, put(str) es un TypeError que Params se traga y deja el valor viejo.

    `expira_s` es cuanto dura el modo concedido, medido en MONOTONO (un salto del reloj de
    pared no puede alargar autoridad). 0 = sin caducidad, que solo tiene sentido para
    observador: bajar a observador no caduca porque no hay nada por debajo.
    """
    modo = parse_mode(modo) or Mode.OBSERVER
    with self._lock:
      self.mode = modo
      self.mode_expiry_mono = (ahora_mono() + expira_s) if (expira_s > 0 and modo is not Mode.OBSERVER) else 0.0
    params = self._get_params()
    if params is not None:
      try:
        params.put(PARAM_MODE, int(modo))
      except Exception:
        cloudlog.exception("[Orbit] no se pudo persistir OrbitCommandMode")
    return modo

  def begin_command(self, verb: str, cmd_id: str, seq: int, deadline_mono=None) -> None:
    """Marca el comando que se va a ejecutar.

    `deadline_mono=None` significa NO TOCAR la ventana del actuador: es lo que pasan los
    verbos que no mueven nada (spec.arma_actuador=False). El plano tiene un solo
    deadline, asi que si un healthcheck de 30 s lo escribiera un segundo despues de un
    lane_change de 3 s, le estaria regalando 27 s de autoridad que nadie pidio.
    """
    with self._lock:
      self.active_verb = verb or ""
      self.cmd_id = cmd_id or ""
      self.seq = max(0, min(int(seq or 0), SEQ_MAX))
      if deadline_mono is not None:
        self.deadline_mono = float(deadline_mono or 0.0)

  def end_command(self) -> None:
    """Cierra el comando activo SIN tocar deadline_mono: el actuador puede seguir vivo
    hasta su deadman aunque el handler ya haya vuelto."""
    with self._lock:
      self.active_verb = ""
      self.cmd_id = ""

  def clear_actuators(self) -> None:
    """disarm_all: neutro inmediato. Deadline a cero = no hay autoridad remota."""
    with self._lock:
      self.active_verb = ""
      self.cmd_id = ""
      self.deadline_mono = 0.0

  def note_ack(self, phase: str, reason: str = "") -> None:
    with self._lock:
      self.last_ack_phase = phase if phase in PHASES else Phase.NONE
      self.last_reason = reason or ""

  def expire_if_due(self) -> bool:
    """Deadman del ACTUADOR (seccion 5): si el plazo monotono del ultimo comando valido
    vencio, se vuelve a neutro. Se llama en el tick de 10 Hz.

    Es la red de seguridad de este lado; controlsd tiene la suya leyendo deadlineMono en
    su propio ciclo de 100 Hz. Dos relojes independientes para el mismo plazo, porque el
    fallo que se quiere evitar -- un override lateral pegado -- es justo el que ocurre
    cuando el unico que vigila deja de correr.
    """
    with self._lock:
      if self.deadline_mono <= 0.0 or ahora_mono() <= self.deadline_mono:
        return False
      self.active_verb = ""
      self.cmd_id = ""
      self.deadline_mono = 0.0
      return True

  def note_link(self, ventana_s: float) -> None:
    """Watchdog de ENLACE (segundos, seccion 5). Distinto del de actuador."""
    with self._lock:
      self.link_deadline_mono = ahora_mono() + float(ventana_s)

  def set_clock_synced(self, ok: bool) -> None:
    with self._lock:
      self.clock_synced = bool(ok)

  def snapshot(self) -> dict:
    with self._lock:
      return {
        "mode": self.mode,
        "active_verb": self.active_verb,
        "cmd_id": self.cmd_id,
        "seq": self.seq,
        "deadline_mono": self.deadline_mono,
        "link_deadline_mono": self.link_deadline_mono,
        "last_ack_phase": self.last_ack_phase,
        "last_reason": self.last_reason,
        "bench_armed": self.bench_armed,
        "bench_expiry_mono": self.bench_expiry_mono,
        "clock_synced": self.clock_synced,
      }

  @property
  def bench_armado_vigente(self) -> bool:
    """Armado de banco AHORA. Se recomprueba la caducidad con reloj monotono en cada
    consulta: entre el refresh de 1 Hz y la ejecucion pueden pasar los 300 s de TTL."""
    with self._lock:
      return bool(self.bench_armed) and self.bench_expiry_mono > ahora_mono()


class CommandStateService:
  """Tick unico del subsistema: refresca gates, refresca params y publica el estado.

  Se arranca desde el hilo ORBIT del manager. Un solo hilo para las dos cosas porque el
  SubMaster del GateMonitor y el PubMaster de aqui tienen que vivir en el MISMO hilo:
  msgq no es thread-safe.
  """

  def __init__(self, gates, store: CommandStateStore, pm=None, on_disarm=None):
    self._gates = gates
    self._store = store
    self._pm = pm
    self._pm_inyectado = pm is not None
    self._on_disarm = on_disarm
    self._msg_fallidos = 0

  def _ensure_pm(self):
    if self._pm is None:
      try:
        from cereal import messaging
        self._pm = messaging.PubMaster([SERVICIO])
      except Exception:
        self._pm = None
    return self._pm

  def reset_pm(self) -> None:
    """Tira el PubMaster para que lo recree el hilo nuevo. msgq no es thread-safe y el
    que teniamos lo construyo el hilo que acaba de morir."""
    if not self._pm_inyectado:
      self._pm = None

  def set_on_disarm(self, cb) -> None:
    self._on_disarm = cb

  def build_message(self):
    """Construye el mensaje cereal a partir del store y del GateMonitor."""
    from cereal import messaging
    snap = self._store.snapshot()
    msg = messaging.new_message(SERVICIO)
    msg.valid = True
    st = msg.orbitCommandState
    st.mode = MODE_CEREAL_NAMES[snap["mode"]]
    st.activeVerb = snap["active_verb"]
    st.cmdId = snap["cmd_id"]
    st.seq = max(0, min(int(snap["seq"]), SEQ_MAX))
    st.deadlineMono = float(snap["deadline_mono"])
    st.linkDeadlineMono = float(snap["link_deadline_mono"])
    st.gates = int(self._gates.mask) if self._gates is not None else 0
    st.lastAckPhase = snap["last_ack_phase"] if snap["last_ack_phase"] in PHASES else Phase.NONE
    st.lastReason = snap["last_reason"]
    st.benchArmed = bool(snap["bench_armed"])
    st.benchExpiryMono = float(snap["bench_expiry_mono"])
    st.clockSynced = bool(snap["clock_synced"])
    return msg

  def step(self) -> None:
    """Un tick a 10 Hz. Nunca lanza: es el hilo que alimenta el deadman."""
    try:
      if self._gates is not None:
        self._gates.update(0)
        self._store.set_clock_synced(self._gates.clock_synced)
      self._store.refresh_params()
      self._store.expire_if_due()

      # Boton fisico de desarme: se atiende aqui porque este hilo corre aunque el enlace
      # MQTT este caido, que es justo cuando mas falta hace.
      if self._on_disarm is not None and self._store.consume_disarm_request():
        try:
          self._on_disarm()
        except Exception:
          cloudlog.exception("[Orbit] fallo el disarm_all local")

      pm = self._ensure_pm()
      if pm is None:
        return
      pm.send(SERVICIO, self.build_message())
      self._msg_fallidos = 0
    except Exception:
      self._msg_fallidos += 1
      if self._msg_fallidos in (1, 100):
        cloudlog.exception("[Orbit] CommandStateService.step fallo")

  def run(self, stop_event=None) -> None:
    """Bucle a 10 Hz. Bloquea: llamar en su propio hilo."""
    try:
      from openpilot.common.realtime import Ratekeeper
      rk = Ratekeeper(FRECUENCIA_HZ, print_delay_threshold=None)
    except Exception:
      rk = None
    while stop_event is None or not stop_event.is_set():
      self.step()
      if rk is not None:
        rk.keep_time()
      elif stop_event is not None:
        stop_event.wait(1.0 / FRECUENCIA_HZ)
      else:
        # Sin Ratekeeper y sin senal de parada: dormir a mano. Sin esto el bucle giraria
        # a la maxima velocidad del core y se comeria una CPU entera del comma.
        time.sleep(1.0 / FRECUENCIA_HZ)


class CommandPlane:
  """El plano de mando entero en un objeto: GateMonitor + store + publicador + su hilo.

  Existe para que el supervisor de hilos ORBIT del manager (manager.py, el bucle que ya
  resucita MQTTEnvioGeneral con backoff) pueda vigilar tambien esto con la MISMA
  interfaz: start / stop / join / is_alive / healthy.

  POR QUE ES UN SINGLETON (get_command_plane) Y NO UNA CLASE QUE EL SUPERVISOR
  INSTANCIA. El router de mando guarda una REFERENCIA a self.gates y a self.store. Si
  cada reinicio construyera objetos nuevos, el router seguiria consultando el GateMonitor
  MUERTO: una mascara congelada que nadie refresca. Congelada en verde significa
  autorizar una maniobra con la foto del coche de hace un minuto. Manteniendo el objeto y
  relevando solo el HILO, la referencia del router nunca queda huerfana; y mientras el
  hilo no tica, la mascara se declara rancia y todos los gates valen rojo (ver
  GateMonitor.stale).

  El hilo hace UNA sola cosa a 10 Hz: refrescar gates, refrescar params, vencer el deadman
  y publicar orbitCommandState. Nada de MQTT: este hilo tiene que seguir vivo justo cuando
  el enlace se cae, porque es el que apaga los actuadores.
  """

  def __init__(self, params=None, gates=None, store=None, on_disarm=None):
    from openpilot.orbit.command_gates import GateMonitor
    self.gates = gates if gates is not None else GateMonitor()
    self.store = store if store is not None else CommandStateStore(params=params)
    self._on_disarm = on_disarm
    self.service = CommandStateService(self.gates, self.store, on_disarm=self._disparo_disarm)
    self._thread: threading.Thread | None = None
    self._stop = threading.Event()

  # ------------------------------------------------------------------------ desarme

  def set_on_disarm(self, cb) -> None:
    """Fija quien ejecuta el desarme del boton FISICO. Lo pone MQTTComandos para que el
    boton y el verbo disarm_all acaben en el mismo sitio."""
    self._on_disarm = cb

  def _disparo_disarm(self) -> None:
    """Boton fisico OrbitDisarmAll. Si nadie se ha registrado, se desarma igual con la
    funcion compartida: bajar autoridad no puede depender de que el enlace este montado."""
    cb = self._on_disarm
    if cb is not None:
      cb()
      return
    try:
      from openpilot.orbit.orbit_control_ultra_simple import disarm_all_actuators
      tocados = disarm_all_actuators(self.store.get_params())
      cloudlog.warning(f"[Orbit] disarm_all por boton fisico (sin enlace): {tocados}")
    except Exception:
      cloudlog.exception("[Orbit] disarm_all por boton fisico fallo")

  # ------------------------------------------------------------------- ciclo de vida

  def start(self) -> None:
    if self._thread is not None and self._thread.is_alive():
      return
    # Relevo de hilo: msgq no es thread-safe, asi que el SubMaster y el PubMaster del
    # hilo anterior no se pueden reutilizar. Se tiran y los recrea el hilo nuevo.
    self.gates.reset_sm()
    self.service.reset_pm()
    self._stop = threading.Event()
    self._thread = threading.Thread(target=self.service.run, args=(self._stop,),
                                    daemon=True, name="OrbitCommandPlane")
    self._thread.start()

  def is_alive(self) -> bool:
    t = self._thread
    return t is not None and t.is_alive()

  def healthy(self) -> bool:
    """Vivo Y ticando. Un hilo que existe pero no publica desde hace medio segundo deja
    a los consumidores sin plano de estado, que es lo mismo que sin mando: el supervisor
    tiene que reiniciarlo, no darlo por bueno."""
    if not self.is_alive():
      return False
    return not self.gates.stale

  def stop(self, timeout: float = 2.0) -> None:
    self._stop.set()
    t = self._thread
    if t is not None and t.is_alive():
      t.join(timeout=timeout)

  def join(self, timeout=None) -> None:
    t = self._thread
    if t is not None:
      t.join(timeout)


# Instancia unica del proceso. La crean (indistintamente) el supervisor del manager y
# MQTTEnvioGeneral: quien llegue primero. Ver el docstring de CommandPlane para por que
# el objeto tiene que sobrevivir a los reinicios de su hilo.
_PLANE: CommandPlane | None = None
_PLANE_LOCK = threading.Lock()


def get_command_plane() -> CommandPlane:
  global _PLANE
  with _PLANE_LOCK:
    if _PLANE is None:
      _PLANE = CommandPlane()
    return _PLANE
