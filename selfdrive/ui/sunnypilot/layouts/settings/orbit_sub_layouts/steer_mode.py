"""
Selector de FUENTE DE TORQUE DEL VOLANTE (param SteerTorqueMode), con confirmacion.

Vive en el panel ORBIT principal y no en un subpanel a proposito: la seccion 9 del
diseno lo deja en el comma porque necesita ojos en el coche, y enterrarlo tras dos
navegaciones es lo contrario de eso.

DOS AUTORIZACIONES DISTINTAS, Y NO SE PUEDEN MEZCLAR
---------------------------------------------------
El catalogo clasifica `torque_mode` 1 y 2 como modo BANCO, y controlsd exige autorizacion
antes de dejar que el override de torque toque el volante. Pero "armar el banco" y "elegir
el modo delante del coche" NO son lo mismo:

  OrbitBenchArmed     habilita los verbos FISICOS POR MQTT (torque_mode, steering_pulse,
                      physical_control) a cualquiera que publique en el broker.
  OrbitSteerModeLocal dice que alguien ha elegido el modo EN ESTA PANTALLA, estando
                      delante. No habilita nada remoto.

Una version anterior de este fichero armaba el BANCO para devolverle la funcion al
selector, y renovaba ese armado indefinidamente mientras el modo siguiera elegido. La
consecuencia, que no se declaro: con el conductor en modo JETSON, cualquiera que conociera
el dongle_id podia mandar `torque_mode {mode: 2}` y poner el volante al tope. El "motivo en
RAM" no protegia de nada, porque solo gobernaba el acto de armar y no el gate del router,
que solo mira el param.

Ahora la seleccion presencial escribe su propio flag. El camino MQTT sigue encontrandose el
banco desarmado y sigue mandando el modelo Comma.

El vigilante (`BenchGuard`, selfdrive/ui/widgets/orbit_mando.py) retira el flag al volver a
COMMA, al pasar a offroad, y -- en TEST MAX -- al superar los 5 km/h, devolviendo ademas el
selector a COMMA.
"""
import json
import time

from openpilot.selfdrive.ui.ui_state import ui_state
from openpilot.selfdrive.ui.widgets import orbit_mando as mando
from openpilot.system.ui.lib.application import gui_app
from openpilot.system.ui.lib.multilang import tr
from openpilot.system.ui.sunnypilot.widgets.list_view import multiple_button_item_sp
from openpilot.system.ui.widgets import DialogResult
from openpilot.system.ui.widgets.confirm_dialog import ConfirmDialog

# Indice del boton -> valor de SteerTorqueMode. El orden replica el Qt original:
#   ['COMMA', 'COMMA+JETSON', 'JETSON', 'TEST MAX'] -> 0, 3, 1, 2
# (etiquetas cortas: 'MODELO COMMA' desbordaba los 320 px del boton)
MODE_BUTTONS = ["COMMA", "COMMA+JETSON", "JETSON", "TEST MAX"]
INDEX_TO_MODE = {0: 0, 1: 3, 2: 1, 3: 2}
MODE_TO_INDEX = {v: k for k, v in INDEX_TO_MODE.items()}
MODE_NAMES = {0: "MODELO COMMA", 1: "JETSON", 2: "TEST MAX", 3: "COMMA+JETSON"}

# Modos cuyo override de torque controlsd solo aplica con armado de banco vigente.
MODES_REQUIRING_BENCH = (1, 2)

TORQUE_STALE_SECONDS = 3.0

POLL_INTERVAL_S = 0.5


def read_mode() -> int:
  return mando.read_steer_mode()


class SteerModeRows:
  """Filas del selector de volante, para incrustar en un Scroller ajeno.

  El contenedor llama a `poll()` desde su `_render` (hilo de UI) para resincronizar el
  selector con el valor real del param: el modo tambien lo puede cambiar la app.
  """

  def __init__(self):
    self._last_poll = 0.0
    # Texto de estado cacheado. El lambda del titulo lo llama el render (y la medida de
    # texto) en CADA frame: recalcularlo ahi seria abrir Params 60 veces por segundo.
    self._status_cached = ""

    # El estado vivo va en el TITULO del selector y no en una fila aparte: son 188 px de
    # scroll menos y el dato queda pegado al control que lo produce.
    self._selector = multiple_button_item_sp(
      title=lambda: tr("Control del volante") + "  -  " + self._status_cached,
      description=lambda: tr("De donde sale el torque que se aplica al volante cuando el control " +
                             "lateral esta activo. Elegir JETSON o TEST MAX aqui arma el banco en " +
                             "local durante 5 minutos: es una accion presencial."),
      buttons=MODE_BUTTONS,
      button_width=320,
      selected_index=MODE_TO_INDEX.get(read_mode(), 0),
      callback=self._on_mode_button,
    )

  @property
  def items(self) -> list:
    return [self._selector]

  def poll(self):
    now = time.monotonic()
    if now - self._last_poll < POLL_INTERVAL_S:
      return
    self._last_poll = now
    self.sync()

  def sync(self):
    """Resincroniza el boton marcado y el texto de estado con los Params reales."""
    self._selector.action_item.set_selected_button(MODE_TO_INDEX.get(read_mode(), 0))
    self._status_cached = self._status_text()

  # ------------------------------------------------------------------- estado
  def _status_text(self) -> str:
    """Estado REAL, no el boton pulsado.

    Sin esto el selector se queda marcando JETSON, el volante lo lleva el modelo Comma
    porque el banco no esta armado, y nada en pantalla lo explica: exactamente la
    regresion que rompio la demo.
    """
    mode = read_mode()
    if mode == 0:
      return tr("torque del modelo interno")
    if mode == 3:
      tgt = ui_state.params.get("JetsonObstacleApplyTarget")
      tgt_label = tr("TORQUE") if tgt == "torque" else tr("CURVATURA")
      return tr("esquive en") + f" {tgt_label}"

    armado, restante = mando.bench_snapshot()
    if armado:
      return tr("ACTIVO, banco armado") + f" ({int(restante)}s)"
    return tr("SIN EFECTO: banco no armado, manda COMMA")

  # -------------------------------------------------------------------- accion
  def _on_mode_button(self, index: int):
    target_mode = INDEX_TO_MODE.get(index, 0)
    current = read_mode()

    # COMMA+JETSON siempre vuelve a preguntar el sub-objetivo (igual que el Qt viejo),
    # asi que no se hace early-return con el.
    if target_mode == current and target_mode != 3:
      return

    if target_mode == 0:
      msg = tr("Volver al MODELO COMMA (recomendado).\n\n" +
               "El volante usara el torque calculado por el modelo interno de openpilot. " +
               "Esta es la opcion mas segura y probada.")
      confirm_text = tr("Cambiar a MODELO COMMA")
    elif target_mode == 1:
      msg = tr("ATENCION\n\n" +
               "Vas a delegar el control del volante a la JETSON (PilotNet). " +
               "El volante obedecera al torque que calcule la red neuronal externa.\n\n" +
               "Al confirmar se ARMA EL BANCO EN LOCAL durante 5 minutos, renovables " +
               "mientras el modo siga elegido. Se desarma solo al volver a COMMA, al " +
               "pasar a offroad o si se reinicia la interfaz.\n\n" +
               "Asegurate de que la Jetson esta conectada y enviando torque por ZMQ, " +
               "de estar en un entorno controlado y de tener las manos sobre el volante.\n\n" +
               "Deseas continuar?")
      confirm_text = tr("SI, usar JETSON")
    elif target_mode == 2:
      msg = tr("PELIGRO - MODO DE PRUEBA\n\n" +
               "Este modo fija el torque del volante al MAXIMO hacia la DERECHA de forma continua. " +
               "SOLO sirve para verificar la interceptacion del torque.\n\n" +
               "Al confirmar se ARMA EL BANCO EN LOCAL durante 5 minutos. Se desarma solo " +
               "en cuanto el coche supere los 5 km/h.\n\n" +
               "USALO SOLO EN PRUEBAS CONTROLADAS, CON LAS MANOS EN EL VOLANTE. " +
               "NO LO USES EN VIA PUBLICA.\n\n" +
               "Deseas continuar?")
      confirm_text = tr("SI, ACTIVAR TEST MAX")
    else:  # target_mode == 3
      if current == 3:
        self._ask_obstacle_apply_target()
        return
      msg = tr("Activar COMMA + JETSON.\n\n" +
               "El volante usara el torque del MODELO COMMA (comportamiento normal). " +
               "Si la Jetson detecta un obstaculo, aplicara temporalmente un esquive lateral.\n\n" +
               "No necesita armado de banco.\n\n" +
               "Requisitos: Jetson conectada y enviando alertas por ZMQ, y modelo de " +
               "deteccion de obstaculos cargado.")
      confirm_text = tr("SI, activar COMMA+JETSON")

    def on_result(result: DialogResult):
      # Siempre resincronizar con el estado real (cubre el cancelar).
      self.sync()
      if result != DialogResult.CONFIRM:
        return
      if target_mode == 3:
        self._ask_obstacle_apply_target()
      else:
        self._commit_mode(target_mode)

    gui_app.push_widget(ConfirmDialog(msg, confirm_text, tr("Cancelar"), callback=on_result))

  def _ask_obstacle_apply_target(self):
    """Como debe esquivar la Jetson: 'curvature' (recomendado) o 'torque' (beta).

    ConfirmDialog solo ofrece dos botones, asi que es un flujo en dos pasos:
      paso 1: "esquive en CURVATURA?"  CONFIRM -> curvature ; CANCEL -> paso 2
      paso 2: "usar TORQUE (beta)?"    CONFIRM -> torque    ; CANCEL -> abortar
    """
    def commit_target(target: str):
      ui_state.params.put("JetsonObstacleApplyTarget", target)
      self._write_apply_target_payload(target)
      self._commit_mode(3)

    def ask_torque():
      msg = tr("COMMA + JETSON - Usar TORQUE para esquivar? (BETA)\n\n" +
               "TORQUE pisa directamente el torque del volante mientras dura el esquive. " +
               "Reaccion mas fuerte e inmediata.\n\n" +
               "Pulsa Cancelar para no cambiar nada.")

      def on_torque(result: DialogResult):
        self.sync()
        if result == DialogResult.CONFIRM:
          commit_target("torque")

      gui_app.push_widget(ConfirmDialog(msg, tr("SI, usar TORQUE"), tr("Cancelar"), callback=on_torque))

    msg = tr("COMMA + JETSON - Como debe esquivar la Jetson?\n\n" +
             "CURVATURA suma un offset a la curvatura deseada. Comportamiento historico, " +
             "mas suave y predecible (RECOMENDADO).\n\n" +
             "Pulsa CURVATURA para usarla, o Otra opcion para elegir TORQUE (beta).")

    def on_curvature(result: DialogResult):
      self.sync()
      if result == DialogResult.CONFIRM:
        commit_target("curvature")
      elif result == DialogResult.CANCEL:
        ask_torque()

    gui_app.push_widget(ConfirmDialog(msg, tr("CURVATURA (recomendado)"), tr("Otra opcion (TORQUE)"),
                                      callback=on_curvature))

  def _commit_mode(self, mode: int):
    # SteerTorqueMode es INT: put(str) lanza TypeError, y ese TypeError se comia ademas
    # el payload MQTT de la linea siguiente -> ni cambiaba el modo ni se enteraba la app.
    # block=True: el armado de banco de la linea siguiente y el texto de estado leen
    # este valor de inmediato; con la escritura en vuelo leerian el modo anterior.
    ui_state.params.put("SteerTorqueMode", mode, True)

    # Armado presencial del banco. Va DESPUES del modo para que no exista una ventana en
    # la que el banco esta armado sin que nadie haya pedido un modo de banco.
    # AUTORIZACION PRESENCIAL, no armado de banco. Antes esta rama llamaba a arm_bench(),
    # y eso tenia una consecuencia que no se declaro: OrbitBenchArmed es lo que el router
    # comprueba para dejar pasar los verbos FISICOS por MQTT, asi que elegir "Jetson"
    # delante del coche dejaba torque_mode / steering_pulse / physical_control alcanzables
    # para cualquiera que publicase en el broker -- y el arrendamiento se renovaba solo,
    # sin fin. El "motivo en RAM" no protegia de nada: solo gobernaba el acto de armar, no
    # el gate del router. Ahora la seleccion presencial escribe su propio flag, que
    # controlsd acepta para los modos 1 y 2 y que NO habilita ningun verbo remoto.
    if mode in MODES_REQUIRING_BENCH:
      mando.set_steer_local(True)
    else:
      mando.set_steer_local(False)

    self._write_mode_payload(mode)
    self.sync()

  # ------------------------------------------------------------------ payloads
  def _dongle_id(self) -> str | None:
    dongle = ui_state.params.get("DongleId")
    return dongle if dongle else None

  def _write_mode_payload(self, mode: int):
    dongle = self._dongle_id()
    if not dongle:
      return
    payload = {
      "dongle_id": dongle,
      "steer_torque_mode": mode,
      "source": "comma_ui",
      "timestamp": str(time.time_ns() // 1_000_000),
    }
    ui_state.params.put("SteerTorqueModeMqttPayload", json.dumps(payload))

  def _write_apply_target_payload(self, target: str):
    dongle = self._dongle_id()
    if not dongle:
      return
    payload = {
      "dongle_id": dongle,
      "apply_target": target,
      "source": "comma_ui",
      "ts": str(time.time_ns() // 1_000_000),
    }
    ui_state.params.put("JetsonObstacleApplyTargetMqttPayload", json.dumps(payload))
