"""
Copyright (c) 2021-, Haibin Wen, sunnypilot, and a number of other contributors.

This file is part of sunnypilot and is licensed under the MIT License.
See the LICENSE.md file in the root directory for more details.

OrbitLayout - panel ORBIT de los ajustes.

Reparto de interfaz de la seccion 9 del diseno: aqui SOLO queda lo que necesita ojos en
el coche o lo que tiene que funcionar con la red caida.

  * estado del MANDO REMOTO (modo, salud del enlace, ultimo comando y su resultado),
  * ARMADO DE BANCO con confirmacion, TTL de 300 s y cuenta atras,
  * DESARMAR TODO, anclado abajo y fuera del scroll: es el unico control que nunca
    se bloquea y nunca puede quedar fuera de alcance,
  * selector de modo de volante con confirmacion,
  * interruptor maestro LOCAL de privacidad,
  * QR de enrolamiento e IP del broker,
  * "Restablecer valores seguros".

Se fue a la app: los canales de telemetria (8 toggles) y la configuracion de camara.
Se borro: la seccion PRUEBAS (modo_debug y silenciar_alertas_comm) junto con el overlay
que consumia modo_debug.

EL ESTADO DEL MANDO SE LEE DE CEREAL, NO DE PARAMS. `ui_state.orbit_command` es la
vista del mensaje `orbitCommandState` (10 Hz) que refresca UIStateSP en cada frame. Los
unicos Params que se leen aqui son los de la cuenta atras del armado, y a 1 Hz.
"""
import time
from enum import IntEnum

import pyray as rl

from openpilot.common.swaglog import cloudlog
from openpilot.selfdrive.ui.layouts.settings import settings as OP
from openpilot.selfdrive.ui.ui_state import ui_state
from openpilot.selfdrive.ui.widgets import orbit_mando as mando
from openpilot.selfdrive.ui.widgets.orbit_enroll_dialog import OrbitEnrollDialog
from openpilot.selfdrive.ui.widgets.orbit_section import SectionHeaderSP
from openpilot.selfdrive.ui.widgets.orbit_server import ServerMonitor
from openpilot.system.ui.lib.application import gui_app, FontWeight
from openpilot.system.ui.lib.multilang import tr
from openpilot.system.ui.lib.text_measure import measure_text_cached
from openpilot.system.ui.sunnypilot.widgets.list_view import toggle_item_sp, button_item_sp
from openpilot.system.ui.widgets import Widget, DialogResult
from openpilot.system.ui.widgets.button import Button, ButtonStyle
from openpilot.system.ui.widgets.confirm_dialog import ConfirmDialog, alert_dialog
from openpilot.system.ui.widgets.scroller_tici import Scroller
from openpilot.selfdrive.ui.sunnypilot.layouts.settings.orbit_sub_layouts.advanced_settings import AdvancedSettingsLayout
from openpilot.selfdrive.ui.sunnypilot.layouts.settings.orbit_sub_layouts.server_settings import ServerRows
from openpilot.selfdrive.ui.sunnypilot.layouts.settings.orbit_sub_layouts.steer_mode import SteerModeRows

_REFRESH_SECONDS = 1.0
# El heartbeat MQTT escribe OrbitLastPublish cada ~3 s; sin dato fresco en 30 s
# el enlace se considera caido aunque OrbitConnected quedara en True (el
# proceso pudo morir sin escribir el False de despedida).
_LINK_STALE_SECONDS = 30.0

# Barra anclada de DESARMAR TODO.
_DISARM_BAR_HEIGHT = 132
_DISARM_BAR_GAP = 20
_DISARM_FEEDBACK_S = 2.5

_RED = rl.Color(0xF2, 0x55, 0x55, 255)
_AMBER = rl.Color(0xF5, 0xC8, 0x42, 255)


def _publish_age(params) -> float:
  """Segundos desde el ultimo publish MQTT; inf si no hay dato."""
  try:
    last = params.get("OrbitLastPublish")
    if last:
      return max(0.0, (time.time_ns() / 1e9) - float(last))
  except Exception:
    pass
  return float("inf")


class PanelType(IntEnum):
  MAIN = 0
  ADVANCED = 1


class _MandoCard(Widget):
  """La tarjeta de cabecera del panel: identidad ORBIT + estado del MANDO REMOTO.

  Absorbe el hero anterior (una tarjeta de 312 px que solo llevaba logo, wordmark y
  chips) porque el panel tenia ~2.950 px de scroll y la seccion 9 pide adelgazarlo. La
  informacion no se pierde: los chips SERVIDOR / ENLACE / CUENTA siguen aqui, en la
  franja superior, y debajo van las tres lineas que exige el punto 1 del encargo:

    MODO            modo vigente del mando (y el chip de BANCO ARMADO con su cuenta atras)
    ENLACE          salud del enlace de mando
    ULTIMO COMANDO  verbo + fase del ACK + motivo

  Los tres salen del mensaje cereal `orbitCommandState` a traves de
  `ui_state.orbit_command`, que UIStateSP refresca en cada frame. Si el plano no publica
  NO se pinta verde ni se conserva el ultimo valor conocido: se pinta "SUBSISTEMA DE
  MANDO CAIDO". Un panel de mando que miente sobre el estado del mando es peor que no
  tenerlo.

  Lo que se lee de Params (chips y cuenta atras) esta limitado a _REFRESH_SECONDS; por
  frame no se lee nada.
  """

  HEIGHT = 300

  def __init__(self, monitor: ServerMonitor):
    super().__init__()
    self._rect = rl.Rectangle(0, 0, 0, self.HEIGHT)
    self._monitor = monitor
    self._font_bold = gui_app.font(FontWeight.BOLD)
    self._font = gui_app.font(FontWeight.NORMAL)
    try:
      self._logo = gui_app.texture("img_orbit_logo.png", 56, 56)
    except Exception:
      self._logo = None

    self._last_refresh = 0.0
    self._chips: list[tuple[str, bool]] = []
    self._bench_restante = 0.0

  def set_parent_rect(self, parent_rect: rl.Rectangle) -> None:
    super().set_parent_rect(parent_rect)
    self._rect.width = parent_rect.width

  def _refresh(self):
    now = time.monotonic()
    if now - self._last_refresh < _REFRESH_SECONDS:
      return
    self._last_refresh = now

    # Cuenta atras del armado: se refresca a 1 Hz, que es justo lo que necesita un
    # contador en segundos, y no en cada frame (serian 60 lecturas de Params).
    _, self._bench_restante = mando.bench_snapshot()

    params = ui_state.params
    connected = params.get_bool("OrbitConnected") and _publish_age(params) <= _LINK_STALE_SECONDS
    owner = params.get("OrbitOwner")
    owner = owner.strip() if isinstance(owner, str) else ""

    server_ok = self._monitor.broker_ok and self._monitor.backend_ok
    cuenta = owner.split()[0][:12].upper() if owner else tr("SIN VINCULAR")

    self._chips = [
      (tr("SERVIDOR"), server_ok),
      (tr("ENLACE"), connected),
      (cuenta, bool(owner)),
    ]

  # --------------------------------------------------------------------- pintado
  def _draw_identity(self, card: rl.Rectangle, pad: float) -> float:
    """Franja superior: logo + wordmark a la izquierda, chips a la derecha."""
    y = card.y + 20
    strip_h = 56
    x = card.x + pad
    if self._logo is not None:
      rl.draw_texture_pro(
        self._logo,
        rl.Rectangle(0, 0, self._logo.width, self._logo.height),
        rl.Rectangle(x, y, 56, 56),
        rl.Vector2(0, 0), 0, rl.WHITE,
      )
      x += 56 + 18

    wm = measure_text_cached(self._font_bold, "ORBIT", 36, 3)
    rl.draw_text_ex(self._font_bold, "ORBIT", rl.Vector2(x, y + (strip_h - wm.y) / 2), 36, 3, OP.ORBIT_INK)
    x += wm.x

    chip_h = 46
    chip_y = y + (strip_h - chip_h) / 2
    right = card.x + card.width - pad
    for label, ok in reversed(self._chips):
      size = measure_text_cached(self._font_bold, label, 24, 1)
      chip_w = size.x + chip_h + 30
      if right - chip_w < x + 30:
        break
      chip = rl.Rectangle(right - chip_w, chip_y, chip_w, chip_h)
      rl.draw_rectangle_rounded(chip, 1.0, 12, OP.ORBIT_VOID)
      rl.draw_rectangle_rounded_lines_ex(chip, 1.0, 12, 2, OP.ORBIT_HAIRLINE)
      dot = OP.ORBIT_GREEN if ok else rl.Color(OP.ORBIT_MUTED.r, OP.ORBIT_MUTED.g, OP.ORBIT_MUTED.b, 120)
      rl.draw_circle(int(chip.x + 24), int(chip_y + chip_h / 2), 7, dot)
      rl.draw_text_ex(self._font_bold, label, rl.Vector2(chip.x + 42, chip_y + (chip_h - size.y) / 2),
                      24, 1, OP.ORBIT_INK if ok else OP.ORBIT_MUTED)
      right -= chip_w + 14

    sep_y = y + strip_h + 16
    rl.draw_line_ex(rl.Vector2(card.x + pad, sep_y), rl.Vector2(card.x + card.width - pad, sep_y),
                    2, OP.ORBIT_HAIRLINE)
    return sep_y + 18

  # Columna de valores: "ULTIMO COMANDO" a 26 px mide ~300, asi que el valor arranca
  # despues o se solapa con su propia etiqueta.
  VALUE_X = 340

  def _line(self, y: float, x: float, etiqueta: str, valor: str, color: rl.Color, size: int = 34) -> None:
    rl.draw_text_ex(self._font, etiqueta, rl.Vector2(x, y + 6), 26, 1, OP.ORBIT_MUTED)
    rl.draw_text_ex(self._font_bold, valor, rl.Vector2(x + self.VALUE_X, y), size, 0, color)

  def _render(self, _):
    self._refresh()
    card = rl.Rectangle(self._rect.x, self._rect.y + 8, self._rect.width, self._rect.height - 16)
    rl.draw_rectangle_rounded(card, 0.12, 12, OP.ORBIT_NAVY)
    rl.draw_rectangle_rounded_lines_ex(card, 0.12, 12, 2, OP.ORBIT_HAIRLINE)

    pad = 28
    x = card.x + pad
    y = self._draw_identity(card, pad)

    st = getattr(ui_state, "orbit_command", None)
    if st is None or not st.available:
      rl.draw_text_ex(self._font_bold, tr("SUBSISTEMA DE MANDO CAIDO"), rl.Vector2(x, y), 34, 0, _RED)
      rl.draw_text_ex(self._font, tr("No se publica orbitCommandState: sin mando remoto y sin gates."),
                      rl.Vector2(x, y + 48), 26, 0, OP.ORBIT_MUTED)
      return

    # 1) modo vigente + chip de armado con cuenta atras
    modo_color = OP.ORBIT_GREEN if st.mode == "observer" else _AMBER
    self._line(y, x, tr("MODO"), st.mode_label, modo_color)
    if st.bench_armed:
      etiqueta = tr("BANCO ARMADO") + f"  {int(self._bench_restante)}s"
      size = measure_text_cached(self._font_bold, etiqueta, 24, 1)
      chip = rl.Rectangle(card.x + card.width - pad - size.x - 36, y - 2, size.x + 36, 42)
      rl.draw_rectangle_rounded(chip, 1.0, 10, _AMBER)
      rl.draw_text_ex(self._font_bold, etiqueta, rl.Vector2(chip.x + 18, chip.y + (42 - size.y) / 2),
                      24, 1, rl.Color(0x14, 0x1A, 0x0A, 255))

    # 2) salud del enlace de mando
    y += 62
    if not st.link_ok:
      enlace, color = tr("CAIDO"), _RED
    elif not st.clock_synced:
      # Sin reloj sincronizado el router rechaza todo verbo de banco: decirlo aqui evita
      # el "el coche no responde y no se por que".
      enlace, color = tr("OK - reloj sin sincronizar"), _AMBER
    else:
      enlace, color = tr("OK"), OP.ORBIT_GREEN
    self._line(y, x, tr("ENLACE"), enlace, color)

    # 3) ultimo comando y como acabo
    y += 62
    if st.last_ack_phase != "none":
      texto = f"{st.active_verb or '-'}  -  {st.phase_label}"
      if st.last_reason:
        texto += f"  ({st.last_reason})"
    else:
      texto = tr("ninguno")
    color = _RED if st.phase_is_bad else OP.ORBIT_INK
    # El motivo puede ser largo: se recorta al ancho de la tarjeta en vez de desbordarla.
    max_w = card.width - (x - card.x) - self.VALUE_X - pad
    while texto and measure_text_cached(self._font_bold, texto, 30, 0).x > max_w:
      texto = texto[:-1]
    self._line(y, x, tr("ULTIMO COMANDO"), texto, color, size=30)


class OrbitLayout(Widget):
  def __init__(self):
    super().__init__()

    self._current_panel = PanelType.MAIN
    self._advanced_layout = AdvancedSettingsLayout(lambda: self._set_current_panel(PanelType.MAIN))

    self._monitor = ServerMonitor()
    self._server_rows = ServerRows()
    self._steer_rows = SteerModeRows()

    self._last_refresh = 0.0
    self._bench_status = ""
    # Cacheados en _refresh_status (1 Hz): los lambdas de las filas se evaluan en cada
    # frame y leer Params ahi es abrir ficheros 60 veces por segundo.
    self._bench_armed = False
    self._disarm_feedback_until = 0.0

    # DESARMAR TODO vive FUERA del Scroller: anclado abajo, siempre a la vista. Un boton
    # de panico al que hay que llegar haciendo scroll no es un boton de panico.
    self._disarm_button = Button(
      lambda: tr("DESARMADO") if time.monotonic() < self._disarm_feedback_until else tr("DESARMAR TODO"),
      click_callback=self._do_disarm_all,
      font_size=52,
      font_weight=FontWeight.BOLD,
      button_style=ButtonStyle.DANGER,
      border_radius=16,
    )

    items = self._initialize_items()
    self._scroller = Scroller(items, line_separator=False, spacing=0)

  # ------------------------------------------------------------------------- items
  def _initialize_items(self):
    self._mando_card = _MandoCard(self._monitor)

    self._bench_button = button_item_sp(
      title=lambda: tr("Modo banco (armado local)"),
      button_text=lambda: tr("DESARMAR") if self._bench_armed else tr("ARMAR"),
      description=lambda: self._bench_status,
      callback=self._toggle_bench,
    )

    self._privacy_toggle = toggle_item_sp(
      title=lambda: tr("NO EMITIR POSICION NI CAMARA"),
      description=lambda: tr("Interruptor maestro local. Corta el envio de posicion y de imagen " +
                             "desde el propio coche: funciona sin red y con el movil apagado."),
      initial_state=mando.privacy_muted(),
      callback=self._on_privacy,
    )

    self._enroll_button = button_item_sp(
      title=lambda: tr("Vincular con la app (QR)"),
      button_text=lambda: tr("MOSTRAR"),
      description=lambda: tr("Muestra el codigo QR de enrolamiento en esta pantalla."),
      callback=lambda: gui_app.push_widget(OrbitEnrollDialog()),
    )

    self._advanced_button = button_item_sp(
      title=lambda: tr("Ajustes avanzados"),
      button_text=lambda: tr("ABRIR"),
      description=lambda: tr("Avisos de HUD (angulo muerto, cambio de carril) y enlace con la " +
                             "Jetson (IPs, puertos, calidad de imagen)."),
      callback=lambda: self._set_current_panel(PanelType.ADVANCED),
    )

    self._safe_reset_button = button_item_sp(
      title=lambda: tr("Restablecer valores seguros"),
      # "RESTABLECER" (11 caracteres) no cabe en los 300 px del ButtonAction y se partia
      # en dos lineas ("RESTABLECE" / "R"). El titulo de la fila ya dice que restablece.
      button_text=lambda: tr("APLICAR"),
      description=lambda: tr("Devuelve los params ORBIT que afectan a la conduccion a su estado " +
                             "seguro (volante COMMA, sin comandos remotos pendientes, alertas visibles)."),
      callback=self._confirm_safe_reset,
    )

    # Tres cabeceras, no seis: cada SectionHeaderSP son 96 px de scroll.
    return [
      self._mando_card,
      self._bench_button,
      SectionHeaderSP(tr("VOLANTE")),
      *self._steer_rows.items,
      SectionHeaderSP(tr("CONEXION")),
      self._enroll_button,
      # Solo la fila del broker: "Probar conexion" sigue en el modal SERVIDOR de la home.
      self._server_rows.items[0],
      SectionHeaderSP(tr("DISPOSITIVO")),
      self._privacy_toggle,
      self._advanced_button,
      self._safe_reset_button,
    ]

  # --------------------------------------------------------------- armado de banco
  def _toggle_bench(self):
    if mando.bench_armed():   # sin cache: es una accion, no un pintado
      self._apply_bench_disarm()
      return

    # El texto dice que habilita mandos REMOTOS porque es exactamente lo que hace, y es el
    # dato que decide si armar o no. Elegir el modo de volante EN ESTA PANTALLA no necesita
    # esto: eso va por OrbitSteerModeLocal y no abre nada por MQTT.
    msg = tr("Armar el MODO BANCO durante 5 minutos?\n\n" +
             "Mientras este armado, los verbos de control fisico (torque del volante, pulso " +
             "de direccion, control directo) pasan a ser ejecutables DE FORMA REMOTA desde " +
             "la app. Armalo solo con el coche parado y contigo delante.\n\n" +
             "No hace falta para elegir el modo de volante en esta pantalla.\n\n" +
             "Se desarma solo al agotarse los 5 minutos, al superar los 5 km/h y al pasar " +
             "a offroad.")

    def on_result(result: DialogResult):
      if result != DialogResult.CONFIRM:
        return
      fallos = mando.arm_bench()
      guard = getattr(ui_state, "orbit_bench_guard", None)
      if guard is not None:
        guard.note_local_arm(mando.ARM_REASON_BENCH)
      self._last_refresh = 0.0
      if fallos:
        gui_app.push_widget(alert_dialog(tr("No se pudo armar el banco:") + "\n" + "\n".join(fallos)))

    gui_app.push_widget(ConfirmDialog(msg, tr("SI, armar 5 minutos"), tr("Cancelar"), callback=on_result))

  def _apply_bench_disarm(self):
    fallos = mando.disarm_bench()
    guard = getattr(ui_state, "orbit_bench_guard", None)
    if guard is not None:
      guard.note_disarm()
    self._last_refresh = 0.0
    if fallos:
      gui_app.push_widget(alert_dialog(tr("No se pudo desarmar el banco:") + "\n" + "\n".join(fallos)))

  # ------------------------------------------------------------------ desarmar todo
  def _do_disarm_all(self):
    fallos = mando.disarm_all()
    self._steer_rows.sync()
    guard = getattr(ui_state, "orbit_bench_guard", None)
    if guard is not None:
      guard.note_disarm()
    self._last_refresh = 0.0
    if fallos:
      gui_app.push_widget(alert_dialog(tr("DESARME INCOMPLETO. Han fallado:") + "\n" + "\n".join(fallos)))
    else:
      self._disarm_feedback_until = time.monotonic() + _DISARM_FEEDBACK_S

  # ---------------------------------------------------------------------- privacidad
  def _on_privacy(self, enabled: bool):
    fallos = mando.set_privacy_mute(bool(enabled))
    if fallos:
      gui_app.push_widget(alert_dialog(tr("El corte de emision fallo en:") + "\n" + "\n".join(fallos)))

  # -------------------------------------------------- restablecer valores seguros
  def _confirm_safe_reset(self):
    msg = tr("Restablecer los params ORBIT de conduccion a valores seguros?\n\n" +
             "- Modo de volante: COMMA\n" +
             "- Armado de banco y modo del mando: desarmados\n" +
             "- Frenado de emergencia remoto: OFF\n" +
             "- Cambios de carril forzados pendientes: borrados\n" +
             "- Pulso de direccion remoto: borrado\n" +
             "- Alertas de comunicacion: visibles\n\n" +
             "No toca la configuracion de servidor, telemetria ni Jetson (IPs/puertos), " +
             "ni el interruptor de privacidad.")

    def on_result(result: DialogResult):
      if result != DialogResult.CONFIRM:
        return
      self._apply_safe_reset()

    gui_app.push_widget(ConfirmDialog(msg, tr("SI, restablecer"), tr("Cancelar"), callback=on_result))

  def _apply_safe_reset(self):
    """Escrituras INDEPENDIENTES, cada una con su try y su log.

    Antes esto era un unico try/except global alrededor de las cinco escrituras: si la
    primera fallaba (y la primera era `put("SteerTorqueMode", 0)`, la mas propensa,
    porque un put con el tipo equivocado lanza TypeError) las otras cuatro ni se
    intentaban y el usuario no se enteraba de nada. Un boton de panico que falla mudo
    es peor que no tener boton.
    """
    params = ui_state.params
    fallos: list[str] = []

    def _put(clave, valor):
      try:
        # block=True: la escritura por defecto es asincrona y el resultado que se pinta
        # justo despues seria el valor viejo (ver la nota de orbit_mando._BLOQUEANTE).
        params.put(clave, valor, True)
      except Exception:
        cloudlog.exception(f"[Orbit/UI] valores seguros: fallo {clave}")
        fallos.append(clave)

    def _put_bool(clave, valor):
      try:
        params.put_bool(clave, valor, True)
      except Exception:
        cloudlog.exception(f"[Orbit/UI] valores seguros: fallo {clave}")
        fallos.append(clave)

    def _remove(clave):
      try:
        params.remove(clave)
      except Exception:
        cloudlog.exception(f"[Orbit/UI] valores seguros: fallo borrar {clave}")
        fallos.append(clave)

    # 1. fuente de torque del volante (INT: put exige int nativo)
    _put("SteerTorqueMode", 0)
    # 2. frenado remoto
    _put_bool("brutebreak_active", False)
    # 3. cambios de carril forzados pendientes
    _put_bool("ForceLaneChangeLeft", False)
    _put_bool("ForceLaneChangeRight", False)
    # 4. alertas de comunicacion visibles
    _put_bool("silenciar_alertas_comm", False)
    # 5. pulso de direccion remoto
    _remove("orbit_steering_pulse")
    # 6. autoridad del mando: armado de banco y modo, por si el hilo ORBIT esta caido
    fallos.extend(mando.disarm_bench())
    _put(mando.PARAM_COMMAND_MODE, 0)
    # 7. HUD de adelantamiento: sic_adelantar es PERSISTENT y su overlay ya no existe;
    #    apagarlo aqui evita dejar un flag encendido que nadie puede volver a apagar.
    _put_bool("sic_adelantar", False)
    # 8. volcado de mensajes MQTT a /tmp (era PERSISTENT|BACKUP y sobrevivia a reinicios
    #    y a copias de seguridad; su panel ya no existe, pero el escritor sigue)
    _put_bool("modo_debug", False)

    guard = getattr(ui_state, "orbit_bench_guard", None)
    if guard is not None:
      guard.note_disarm()
    self._steer_rows.sync()
    self._last_refresh = 0.0  # repintar el estado vivo de inmediato

    if fallos:
      gui_app.push_widget(alert_dialog(tr("RESTABLECIMIENTO INCOMPLETO. Han fallado:") +
                                       "\n" + "\n".join(sorted(set(fallos)))))

  # ------------------------------------------------------------------ estado vivo
  def _refresh_status(self):
    now = time.monotonic()
    if now - self._last_refresh < _REFRESH_SECONDS:
      return
    self._last_refresh = now

    armado, restante_s = mando.bench_snapshot()
    self._bench_armed = armado
    if armado:
      restante = int(restante_s)
      guard = getattr(ui_state, "orbit_bench_guard", None)
      motivo = guard.reason if guard is not None else None
      if motivo == mando.ARM_REASON_STEER:
        self._bench_status = (tr("ARMADO por el selector de volante") + f" - {restante}s " +
                              tr("(se renueva mientras el modo siga elegido)"))
      else:
        self._bench_status = tr("ARMADO") + f" - {restante}s " + tr("restantes")
    else:
      self._bench_status = tr("Desarmado. Los verbos de banco se rechazan.")

  # -------------------------------------------------------------------- lifecycle
  def _set_current_panel(self, panel: PanelType):
    self._current_panel = panel

  def _render(self, rect):
    if self._current_panel == PanelType.ADVANCED:
      self._advanced_layout.render(rect)
      return

    self._refresh_status()
    self._server_rows.poll()
    self._steer_rows.poll()

    # El scroller cede la franja inferior a la barra de desarme para que no se solapen:
    # si compartieran rect, un toque en el boton contaria tambien como arrastre.
    bar_h = _DISARM_BAR_HEIGHT + _DISARM_BAR_GAP
    self._scroller.render(rl.Rectangle(rect.x, rect.y, rect.width, max(0.0, rect.height - bar_h)))
    self._disarm_button.render(rl.Rectangle(rect.x, rect.y + rect.height - _DISARM_BAR_HEIGHT,
                                            rect.width, _DISARM_BAR_HEIGHT))

  def show_event(self):
    self._set_current_panel(PanelType.MAIN)
    self._last_refresh = 0.0
    self._steer_rows.sync()
    self._privacy_toggle.action_item.toggle.set_state(mando.privacy_muted())
    self._scroller.show_event()
