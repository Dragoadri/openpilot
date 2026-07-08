"""
Copyright (c) 2021-, Haibin Wen, sunnypilot, and a number of other contributors.

This file is part of sunnypilot and is licensed under the MIT License.
See the LICENSE.md file in the root directory for more details.

UemLayout - top-level SIC-UEM / Orbit settings panel.

Port of the old Qt UemPanel (selfdrive/ui/sunnypilot/qt/offroad/settings/
uem_settings.cc). Exposes the SIC-UEM feature toggles and buttons that open the
Jetson and Server-IP sub-panels, using the _current_panel IntEnum dispatch
pattern from steering.py.
"""
from enum import IntEnum

from openpilot.selfdrive.ui.ui_state import ui_state
from openpilot.system.ui.lib.multilang import tr
from openpilot.system.ui.sunnypilot.widgets.list_view import toggle_item_sp, simple_button_item_sp, ListItemSP, LineSeparatorSP
from openpilot.system.ui.widgets import Widget
from openpilot.system.ui.widgets.scroller_tici import Scroller
from openpilot.selfdrive.ui.sunnypilot.layouts.settings.uem_sub_layouts.jetson_settings import JetsonSettingsLayout
from openpilot.selfdrive.ui.sunnypilot.layouts.settings.uem_sub_layouts.server_ip_settings import ServerIpSettingsLayout
from openpilot.selfdrive.ui.sunnypilot.layouts.settings.uem_sub_layouts.teluem_settings import TelUemSettingsLayout


class PanelType(IntEnum):
  UEM = 0
  JETSON = 1
  SERVER_IP = 2
  TELUEM = 3


class UemLayout(Widget):
  def __init__(self):
    super().__init__()

    self._current_panel = PanelType.UEM
    self._jetson_layout = JetsonSettingsLayout(lambda: self._set_current_panel(PanelType.UEM))
    self._server_ip_layout = ServerIpSettingsLayout(lambda: self._set_current_panel(PanelType.UEM))
    self._teluem_layout = TelUemSettingsLayout(lambda: self._set_current_panel(PanelType.UEM))

    items = self._initialize_items()
    self._scroller = Scroller(items, line_separator=False, spacing=0)

  def _initialize_items(self):
    self._header_label = ListItemSP(
      title=lambda: tr("Configuracion UEM"),
      description=lambda: tr("SIC-UEM - Universidad Europea de Madrid"),
      icon="../../../sunnypilot/selfdrive/assets/offroad/uem_logo.png",
    )
    self._funciones_label = ListItemSP(title=lambda: tr("Funciones"), description="")
    self._config_label = ListItemSP(title=lambda: tr("Configuracion"), description="")
    self._credit_label = ListItemSP(
      title=lambda: tr("Acerca de SIC-UEM"),
      description=lambda: tr("Rama modificada por Adrian Canadas - Grupo de Investigacion SIC-UEM, "
                            "Universidad Europea de Madrid (TFG)."),
      icon="../../../sunnypilot/selfdrive/assets/offroad/uem_logo.png",
    )

    self._telemetria_toggle = toggle_item_sp(
      param="telemetria_uem",
      title=lambda: tr("TELEMETRIA UEM"),
      description=lambda: tr("Envia telemetria del vehiculo al servidor SICUEM."),
    )
    self._c_carril_toggle = toggle_item_sp(
      param="c_carril",
      title=lambda: tr("FUNCION CAMBIO DE CARRIL"),
      description=lambda: tr("Permite ordenar cambios de carril desde la app Orbit."),
    )
    self._show_blindspot_toggle = toggle_item_sp(
      param="show_blindspot",
      title=lambda: tr("MOSTRAR ANGULO MUERTO"),
      description=lambda: tr("Muestra el estado del angulo muerto en la pantalla de conduccion."),
    )
    self._modo_debug_toggle = toggle_item_sp(
      param="modo_debug",
      title=lambda: tr("MODO DEBUG"),
      description=lambda: tr("Muestra los mensajes MQTT recibidos en la pantalla de conduccion."),
    )
    self._test_overtake_toggle = toggle_item_sp(
      param="test_overtake_simulador",
      title=lambda: tr("PRUEBA ADELANTAMIENTO (SIMULADOR)"),
      description=lambda: tr("Ejecuta la rutina de prueba de adelantamiento en el simulador (sin coches)."),
    )
    self._silenciar_alertas_toggle = toggle_item_sp(
      param="silenciar_alertas_comm",
      title=lambda: tr("SILENCIAR ALERTAS DE COMUNICACION"),
      description=lambda: tr("Oculta las alertas 'TAKE CONTROL: Communication issue' y 'locationd/paramsd temporary error'. "
                             "El resto de alertas de seguridad siguen activas. Solo para pruebas: si aparecen "
                             "constantemente hay un problema real que diagnosticar (ver tools/sicuem)."),
    )

    self._teluem_button = simple_button_item_sp(
      button_text=lambda: tr("Conf. TELEMETRIA UEM"),
      button_width=800,
      callback=lambda: self._set_current_panel(PanelType.TELUEM),
      enabled=lambda: ui_state.params.get_bool("telemetria_uem"),
    )
    self._jetson_button = simple_button_item_sp(
      button_text=lambda: tr("Conf. NVIDIA Jetson"),
      button_width=800,
      callback=lambda: self._set_current_panel(PanelType.JETSON),
    )
    self._server_ip_button = simple_button_item_sp(
      button_text=lambda: tr("Conf. IP Servidores"),
      button_width=800,
      callback=lambda: self._set_current_panel(PanelType.SERVER_IP),
    )

    return [
      self._header_label,
      self._funciones_label,
      self._telemetria_toggle,
      self._teluem_button,
      self._c_carril_toggle,
      self._show_blindspot_toggle,
      self._modo_debug_toggle,
      self._test_overtake_toggle,
      self._silenciar_alertas_toggle,
      LineSeparatorSP(40),
      self._config_label,
      self._jetson_button,
      self._server_ip_button,
      LineSeparatorSP(40),
      self._credit_label,
    ]

  def _set_current_panel(self, panel: PanelType):
    self._current_panel = panel

  def _render(self, rect):
    if self._current_panel == PanelType.JETSON:
      self._jetson_layout.render(rect)
    elif self._current_panel == PanelType.SERVER_IP:
      self._server_ip_layout.render(rect)
    elif self._current_panel == PanelType.TELUEM:
      self._teluem_layout.render(rect)
    else:
      self._scroller.render(rect)

  def show_event(self):
    self._set_current_panel(PanelType.UEM)
    self._scroller.show_event()
