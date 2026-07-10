"""
Copyright (c) 2021-, Haibin Wen, sunnypilot, and a number of other contributors.

This file is part of sunnypilot and is licensed under the MIT License.
See the LICENSE.md file in the root directory for more details.

JetsonSettings sub-panel (SIC-UEM / Orbit).

Port of the old Qt JetsonSettings (selfdrive/ui/sunnypilot/qt/offroad/settings/
sunnypilot/jetson_settings.cc) to the raylib/Python sunnypilot UI.

Lets the user:
  - Select the steer-torque source mode (MODELO COMMA / COMMA+JETSON / JETSON /
    TEST MAX) with a confirmation dialog before each change. COMMA+JETSON also
    asks how the Jetson should dodge (curvature vs torque).
  - Edit the Jetson connection config (IPs / ports / JPEG quality) stored in
    orbit/config_jetson.json (atomic write, bumps _version, sets
    JetsonConfigChanged).
  - See a live JetsonObstacleStatus label (throttled param read).

On confirm, a *MqttPayload JSON param is written so the existing MQTT bridge
(mqtt_envio_general.py) propagates the change to the app/server.
"""
import json
import os
import tempfile
import time
from collections.abc import Callable

import pyray as rl

from openpilot.common.basedir import BASEDIR
from openpilot.common.params import UnknownKeyName
from openpilot.selfdrive.ui.ui_state import ui_state
from openpilot.system.ui.lib.application import gui_app
from openpilot.system.ui.lib.multilang import tr
from openpilot.system.ui.sunnypilot.widgets.input_dialog import InputDialogSP
from openpilot.system.ui.sunnypilot.widgets.list_view import (
  multiple_button_item_sp,
  button_item_sp,
  toggle_item_sp,
  ListItemSP,
  LineSeparatorSP,
)
from openpilot.system.ui.widgets import Widget, DialogResult
from openpilot.system.ui.widgets.confirm_dialog import ConfirmDialog
from openpilot.system.ui.widgets.list_view import text_item
from openpilot.system.ui.widgets.network import NavButton
from openpilot.system.ui.widgets.scroller_tici import Scroller

# Mode index in the button row -> SteerTorqueMode int value.
# Button row order matches the old Qt layout:
#   ['MODELO COMMA', 'COMMA+JETSON', 'JETSON', 'TEST MAX'] -> 0, 3, 1, 2
MODE_BUTTONS = ["MODELO COMMA", "COMMA+JETSON", "JETSON", "TEST MAX"]
INDEX_TO_MODE = {0: 0, 1: 3, 2: 1, 3: 2}
MODE_TO_INDEX = {v: k for k, v in INDEX_TO_MODE.items()}
MODE_NAMES = {0: "MODELO COMMA", 1: "JETSON", 2: "TEST MAX", 3: "COMMA+JETSON"}

TORQUE_STALE_SECONDS = 3.0

PARAM_READ_INTERVAL_FRAMES = 30  # ~0.5s at 60fps

# Default config values, mirror the old Qt defaults.
CONFIG_DEFAULTS = {
  "jetson_enabled": False,
  "jetson_ip": "192.168.1.50",
  "comma_ip": "127.0.0.1",
  "jetson_img_port": 5555,
  "jetson_torque_port": 5556,
  "jpeg_quality": 80,
}


def _resolve_config_path() -> str:
  """Resolve config_jetson.json, preferring BASEDIR with a /data/openpilot fallback."""
  candidates = [
    os.path.join(BASEDIR, "orbit", "config_jetson.json"),
    "/data/openpilot/orbit/config_jetson.json",
  ]
  for path in candidates:
    if os.path.exists(path):
      return path
  # Default to the BASEDIR location even if it does not exist yet (will be created).
  return candidates[0]


class JetsonSettingsLayout(Widget):
  def __init__(self, back_btn_callback: Callable):
    super().__init__()
    self._back_button = NavButton(tr("Back"))
    self._back_button.set_click_callback(back_btn_callback)

    self._config_path = _resolve_config_path()
    self._config: dict = {}
    self._load_config()
    self._config_mtime = self._current_mtime()

    # Throttle / live state
    self._frame = 0
    self._obstacle_status = ""
    self._live_torque = ""
    self._live_torque_ts = ""
    self._live_obstacle = ""

    items = self._initialize_items()
    self._scroller = Scroller(items, line_separator=False, spacing=0)

  # ---------------------------------------------------------------- items
  def _initialize_items(self):
    self._jetson_enabled_toggle = toggle_item_sp(
      title=lambda: tr("Activar envio a la Jetson"),
      description=lambda: tr("Habilita el envio de imagenes a la Jetson y la recepcion de su torque."),
      initial_state=bool(self._config.get("jetson_enabled", False)),
      callback=self._on_jetson_enabled,
    )
    self._enabled_status = ListItemSP(
      title=lambda: self._jetson_enabled_status_text(),
      description="",
    )

    self._mode_selector = multiple_button_item_sp(
      title=lambda: tr("Control del volante"),
      description=lambda: tr("Selecciona de donde sale el torque que se aplica al volante "
                             "cuando el control lateral esta activo."),
      buttons=MODE_BUTTONS,
      button_width=320,
      selected_index=MODE_TO_INDEX.get(self._read_mode(), 0),
      callback=self._on_mode_button,
    )

    self._mode_status = ListItemSP(
      title=lambda: self._mode_status_text(),
      description="",
    )

    self._obstacle_label = ListItemSP(
      title=lambda: self._obstacle_status_text(),
      description="",
    )

    self._ip_button = button_item_sp(
      title=lambda: tr("IP de la Jetson"),
      button_text=lambda: tr("EDITAR"),
      callback=lambda: self._edit_config_field("jetson_ip", tr("IP de la Jetson"), is_int=False),
    )
    self._comma_ip_button = button_item_sp(
      title=lambda: tr("IP del Comma (este dispositivo)"),
      button_text=lambda: tr("EDITAR"),
      callback=lambda: self._edit_config_field("comma_ip", tr("IP del Comma (este dispositivo)"), is_int=False),
    )
    self._img_port_button = button_item_sp(
      title=lambda: tr("Puerto de imagenes"),
      button_text=lambda: tr("EDITAR"),
      callback=lambda: self._edit_config_field("jetson_img_port", tr("Puerto de imagenes"), is_int=True),
    )
    self._torque_port_button = button_item_sp(
      title=lambda: tr("Puerto de torque"),
      button_text=lambda: tr("EDITAR"),
      callback=lambda: self._edit_config_field("jetson_torque_port", tr("Puerto de torque"), is_int=True),
    )
    self._quality_button = button_item_sp(
      title=lambda: tr("Calidad de imagen (10-100)"),
      button_text=lambda: tr("EDITAR"),
      callback=lambda: self._edit_config_field("jpeg_quality", tr("Calidad de imagen (10-100)"), is_int=True,
                                               clamp=(10, 100), step=10),
    )

    # ESTADO: read-only live rows (param reads throttled in _update_state)
    self._status_mode = text_item(lambda: tr("Modo actual"), lambda: MODE_NAMES.get(self._read_mode(), "-"))
    self._status_ip = text_item(lambda: tr("IP Jetson"), lambda: str(self._config.get("jetson_ip") or "-"))
    self._status_torque = text_item(lambda: tr("Torque actual"), self._torque_text)
    self._status_obstacle = text_item(lambda: tr("Obstaculo detectado"), self._obstacle_yesno_text)

    items = [
      self._jetson_enabled_toggle,
      self._enabled_status,
      LineSeparatorSP(40),
      self._mode_selector,
      self._mode_status,
      self._obstacle_label,
      LineSeparatorSP(40),
      self._status_mode,
      self._status_ip,
      self._status_torque,
      self._status_obstacle,
      LineSeparatorSP(40),
      self._ip_button,
      self._comma_ip_button,
      self._img_port_button,
      self._torque_port_button,
      self._quality_button,
    ]
    return items

  # ---------------------------------------------------------------- mode
  def _read_mode(self) -> int:
    raw = ui_state.params.get("SteerTorqueMode")
    try:
      return int(raw) if raw else 0
    except (ValueError, TypeError):
      return 0

  def _mode_status_text(self) -> str:
    mode = self._read_mode()
    if mode == 0:
      return tr("MODELO COMMA - El volante usa el torque del modelo interno (original)")
    if mode == 1:
      return tr("JETSON - El volante hara caso al torque que llega de la Jetson (PilotNet)")
    if mode == 2:
      return tr("TEST MAX - Torque FIJO al maximo hacia la derecha (para probar interceptacion)")
    if mode == 3:
      tgt = ui_state.params.get("JetsonObstacleApplyTarget")
      tgt_label = tr("TORQUE") if tgt == "torque" else tr("CURVATURA")
      return tr("COMMA + JETSON - esquive en") + f" {tgt_label}"
    return ""

  def _obstacle_status_text(self) -> str:
    if self._read_mode() != 3:
      return ""
    obs = self._obstacle_status
    mapping = {
      "DODGING_LEFT": tr("ESQUIVANDO  <-"),
      "DODGING_RIGHT": tr("ESQUIVANDO  ->"),
      "DODGING_HOLD": tr("ESQUIVANDO  - NEUTRO"),
      "BSM_BLOCKED_LEFT": tr("BSM BLOQUEA  <-"),
      "BSM_BLOCKED_RIGHT": tr("BSM BLOQUEA  ->"),
      "CANCELED_DRIVER": tr("Cancelado por conductor"),
      "CANCELED_STALE": tr("Jetson sin respuesta"),
    }
    return mapping.get(obs, "")

  def _read_live_param(self, key: str) -> str:
    # New params written by orbit/zmq_client.py; tolerate older manifests.
    try:
      raw = ui_state.params.get(key)
    except UnknownKeyName:
      return ""
    return raw if raw else ""

  def _refresh_live_status(self):
    self._live_torque = self._read_live_param("JetsonTorque")
    self._live_torque_ts = self._read_live_param("JetsonTorqueTimestamp")
    self._live_obstacle = self._read_live_param("JetsonObstaclePulse")

  def _torque_text(self) -> str:
    if not self._live_torque:
      return "-"
    try:
      if not self._live_torque_ts or time.time() - float(self._live_torque_ts) > TORQUE_STALE_SECONDS:
        return "-"
      return f"{float(self._live_torque):+.2f}"
    except (TypeError, ValueError):
      return "-"

  def _obstacle_yesno_text(self) -> str:
    # JetsonObstaclePulse holds the last {"obstacle": bool, "intensity": float} JSON
    if self._live_obstacle:
      try:
        payload = json.loads(self._live_obstacle)
        if isinstance(payload, dict) and payload.get("obstacle"):
          return tr("SI")
      except ValueError:
        pass
    return tr("NO")

  def _on_mode_button(self, index: int):
    """User pressed a mode button. Confirm before committing, then write param + MQTT payload."""
    target_mode = INDEX_TO_MODE.get(index, 0)
    current = self._read_mode()

    # COMMA+JETSON always re-asks the sub-target (matching old Qt behavior),
    # so do not early-return for it. For other modes, no-op if unchanged.
    if target_mode == current and target_mode != 3:
      return

    if target_mode == 0:
      msg = tr("Volver al MODELO COMMA (recomendado).\n\n"
               "El volante usara el torque calculado por el modelo interno de openpilot. "
               "Esta es la opcion mas segura y probada.")
      confirm_text = tr("Cambiar a MODELO COMMA")
    elif target_mode == 1:
      msg = tr("ATENCION\n\n"
               "Vas a delegar el control del volante a la JETSON (PilotNet). "
               "El volante obedecera al torque que calcule la red neuronal externa.\n\n"
               "Asegurate de que la Jetson esta conectada y enviando torque por ZMQ, "
               "de estar en un entorno controlado y de tener las manos sobre el volante.\n\n"
               "Deseas continuar?")
      confirm_text = tr("SI, usar JETSON")
    elif target_mode == 2:
      msg = tr("PELIGRO - MODO DE PRUEBA\n\n"
               "Este modo fija el torque del volante al MAXIMO hacia la DERECHA de forma continua. "
               "SOLO sirve para verificar la interceptacion del torque.\n\n"
               "USALO SOLO EN PRUEBAS CONTROLADAS, CON LAS MANOS EN EL VOLANTE. "
               "NO LO USES EN VIA PUBLICA.\n\n"
               "Deseas continuar?")
      confirm_text = tr("SI, ACTIVAR TEST MAX")
    else:  # target_mode == 3
      if current == 3:
        # Already in COMMA+JETSON: skip the mode confirm, go straight to sub-target choice.
        self._ask_obstacle_apply_target(current)
        return
      msg = tr("Activar COMMA + JETSON.\n\n"
               "El volante usara el torque del MODELO COMMA (comportamiento normal). "
               "Si la Jetson detecta un obstaculo, aplicara temporalmente un esquive lateral.\n\n"
               "Requisitos: Jetson conectada y enviando alertas por ZMQ, y modelo de "
               "deteccion de obstaculos cargado.")
      confirm_text = tr("SI, activar COMMA+JETSON")

    def on_result(result: DialogResult):
      # Always re-sync the selector to the real state (handles cancel).
      self._sync_selector()
      if result != DialogResult.CONFIRM:
        return
      if target_mode == 3:
        self._ask_obstacle_apply_target(current)
      else:
        self._commit_mode(target_mode)

    gui_app.push_widget(ConfirmDialog(msg, confirm_text, tr("Cancelar"), callback=on_result))

  def _ask_obstacle_apply_target(self, prev_mode: int):
    """Choose how the Jetson should dodge: 'curvature' (recommended) or 'torque' (beta).

    ConfirmDialog only offers two buttons, so this is a two-step flow:
      step 1: "esquive en CURVATURA?"  CONFIRM -> curvature ; CANCEL -> step 2
      step 2: "usar TORQUE (beta)?"    CONFIRM -> torque    ; CANCEL -> abort (no change)
    """
    def commit_target(target: str):
      ui_state.params.put("JetsonObstacleApplyTarget", target)
      self._write_apply_target_payload(target)
      self._commit_mode(3)

    def ask_torque():
      msg = tr("COMMA + JETSON - Usar TORQUE para esquivar? (BETA)\n\n"
               "TORQUE pisa directamente el torque del volante mientras dura el esquive. "
               "Reaccion mas fuerte e inmediata.\n\n"
               "Pulsa Cancelar para no cambiar nada.")

      def on_torque(result: DialogResult):
        self._sync_selector()
        if result == DialogResult.CONFIRM:
          commit_target("torque")
        # CANCEL / dismiss -> abort, leave mode unchanged

      gui_app.push_widget(ConfirmDialog(msg, tr("SI, usar TORQUE"), tr("Cancelar"), callback=on_torque))

    msg = tr("COMMA + JETSON - Como debe esquivar la Jetson?\n\n"
             "CURVATURA suma un offset a la curvatura deseada. Comportamiento historico, "
             "mas suave y predecible (RECOMENDADO).\n\n"
             "Pulsa CURVATURA para usarla, o Otra opcion para elegir TORQUE (beta).")

    def on_curvature(result: DialogResult):
      self._sync_selector()
      if result == DialogResult.CONFIRM:
        commit_target("curvature")
      elif result == DialogResult.CANCEL:
        ask_torque()

    gui_app.push_widget(ConfirmDialog(msg, tr("CURVATURA (recomendado)"), tr("Otra opcion (TORQUE)"), callback=on_curvature))

  def _commit_mode(self, mode: int):
    ui_state.params.put("SteerTorqueMode", str(mode))
    self._write_mode_payload(mode)
    self._sync_selector()

  def _sync_selector(self):
    self._mode_selector.action_item.set_selected_button(MODE_TO_INDEX.get(self._read_mode(), 0))

  # ------------------------------------------------------------- payloads
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
      "timestamp": str(int(time.time() * 1000)),
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
      "ts": str(int(time.time() * 1000)),
    }
    ui_state.params.put("JetsonObstacleApplyTargetMqttPayload", json.dumps(payload))

  # --------------------------------------------------------- jetson enabled
  def _on_jetson_enabled(self, enabled: bool):
    self._config["jetson_enabled"] = bool(enabled)
    self._save_config()

  def _jetson_enabled_status_text(self) -> str:
    return tr("Estado: ACTIVA") if self._config.get("jetson_enabled", False) else tr("Estado: INACTIVA")

  def _sync_jetson_enabled(self):
    toggle = getattr(self, "_jetson_enabled_toggle", None)
    if toggle is not None:
      toggle.action_item.toggle.set_state(bool(self._config.get("jetson_enabled", False)))

  # ------------------------------------------------------------- config IO
  def _current_mtime(self) -> float:
    try:
      return os.path.getmtime(self._config_path)
    except OSError:
      return 0.0

  def _load_config(self):
    self._config = dict(CONFIG_DEFAULTS)
    try:
      with open(self._config_path) as f:
        data = json.load(f)
      if isinstance(data, dict):
        self._config.update(data)
    except (OSError, ValueError):
      pass

  def _save_config(self):
    """Atomic write (tempfile + os.replace), bump _version, set JetsonConfigChanged, push MQTT payload."""
    version_ms = int(time.time() * 1000)
    self._config["_version"] = str(version_ms)

    directory = os.path.dirname(self._config_path)
    try:
      os.makedirs(directory, exist_ok=True)
      fd, tmp_path = tempfile.mkstemp(dir=directory, suffix=".tmp")
      try:
        with os.fdopen(fd, "w") as f:
          json.dump(self._config, f, indent=4, sort_keys=True)
        os.replace(tmp_path, self._config_path)
      except Exception:
        if os.path.exists(tmp_path):
          os.remove(tmp_path)
        raise
    except OSError:
      return

    # Record our own write so the live-reload check does not treat it as external.
    self._config_mtime = self._current_mtime()
    ui_state.params.put_bool("JetsonConfigChanged", True)
    self._write_config_payload(version_ms)

  def _write_config_payload(self, version_ms: int):
    dongle = self._dongle_id()
    if not dongle:
      return
    payload = {
      "dongle_id": dongle,
      "jetson_enabled": bool(self._config.get("jetson_enabled", False)),
      "jetson_ip": str(self._config.get("jetson_ip", "")),
      "comma_ip": str(self._config.get("comma_ip", "")),
      "jetson_img_port": int(self._config.get("jetson_img_port", 5555)),
      "jetson_torque_port": int(self._config.get("jetson_torque_port", 5556)),
      "jpeg_quality": int(self._config.get("jpeg_quality", 80)),
      "source": "comma_ui",
      "timestamp": str(int(time.time() * 1000)),
      "_version": str(version_ms),
    }
    ui_state.params.put("JetsonConfigMqttPayload", json.dumps(payload))

  def _edit_config_field(self, key: str, title: str, is_int: bool, clamp: tuple[int, int] | None = None,
                         step: int | None = None):
    current = str(self._config.get(key, CONFIG_DEFAULTS.get(key, "")))

    def on_input(result: DialogResult, text: str):
      if result != DialogResult.CONFIRM:
        return
      text = text.strip()
      if not text:
        return
      if is_int:
        try:
          value = int(text)
        except ValueError:
          return
        if step:
          value = int(round(value / step) * step)
        if clamp:
          value = max(clamp[0], min(clamp[1], value))
        self._config[key] = value
      else:
        self._config[key] = text
      self._save_config()

    dialog = InputDialogSP(title, current_text=current, min_text_size=1, callback=on_input)
    dialog.show()

  # ------------------------------------------------------------- lifecycle
  def _update_state(self):
    super()._update_state()
    self._frame += 1
    if self._frame % PARAM_READ_INTERVAL_FRAMES == 0:
      obs = ui_state.params.get("JetsonObstacleStatus")
      self._obstacle_status = obs if obs else ""
      self._refresh_live_status()
      self._sync_selector()
      # Live-reload config_jetson.json if an external writer (e.g. MQTT bridge)
      # changed it while the panel is open. Saving merges keys, so this is safe
      # even mid-edit; our own writes update _config_mtime to avoid self-triggering.
      mtime = self._current_mtime()
      if mtime and mtime != self._config_mtime:
        self._config_mtime = mtime
        self._load_config()
        self._sync_jetson_enabled()
    # Hide the obstacle status row unless there is something to show.
    self._obstacle_label.set_visible(bool(self._obstacle_status_text()))

  def _render(self, rect):
    self._back_button.set_position(self._rect.x, self._rect.y + 20)
    self._back_button.render()
    content_rect = rl.Rectangle(
      rect.x,
      rect.y + self._back_button.rect.height + 40,
      rect.width,
      rect.height - self._back_button.rect.height - 40,
    )
    self._scroller.render(content_rect)

  def show_event(self):
    self._load_config()
    self._config_mtime = self._current_mtime()
    self._sync_jetson_enabled()
    self._sync_selector()
    obs = ui_state.params.get("JetsonObstacleStatus")
    self._obstacle_status = obs if obs else ""
    self._refresh_live_status()
    self._scroller.show_event()
