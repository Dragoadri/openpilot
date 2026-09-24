"""Capturas offscreen del rediseño «Órbita · Grafito».

Script, no test de pytest (por eso el nombre no lleva el prefijo `test_`).
Inicializa `gui_app` en big_ui, renderiza cada pantalla del rediseño y
guarda un PNG por pantalla con `rl.load_image_from_screen` + `export_image`,
igual que los scripts de captura ad-hoc de las tareas anteriores. Termina
solo, sin bucle infinito.

Uso:
  BIG=1 OFFSCREEN=1 .venv/bin/python3 selfdrive/ui/tests/orbit_capturas.py <dir>

Genera en <dir>:
  splash_0.5s.png, splash_1.4s.png, home_conectado.png, home_sin_conexion.png,
  panel_orbit.png, vinculacion_qr.png

Usa el Params de PC del repo (nunca el del dispositivo real). Cada valor que
toca se guarda antes de escribirlo y se restaura en un `finally`, así que el
script no deja estado.
"""
import os

# SCALE=1.0 antes de cualquier import de openpilot: en PC, application.py
# autoescala la ventana al monitor si SCALE no esta puesta (aqui da 0.844),
# y el script dibuja en coordenadas pensadas para 2160x1080 sin re-escalar,
# asi que sin esto las capturas salen a 1824x912 y recortadas por la derecha.
os.environ.setdefault("SCALE", "1.0")

import sys
import time
from pathlib import Path
from unittest import mock

import pyray as rl

from openpilot.common.params import Params
from openpilot.system.ui.lib.application import gui_app
from openpilot.selfdrive.ui.sunnypilot.layouts import orbit_splash
from openpilot.selfdrive.ui.layouts.home import HomeLayout
from openpilot.selfdrive.ui.sunnypilot.layouts.settings.orbit_panel import OrbitLayout
from openpilot.selfdrive.ui.widgets.orbit_enroll_dialog import OrbitEnrollDialog
from openpilot.selfdrive.ui.widgets.orbit_server import ServerMonitor

# Params que toca este script (Params de PC); se restauran al terminar.
PARAM_KEYS = ["OrbitConnected", "OrbitPairingCode", "OrbitClaimed", "OrbitOwner"]


def _capturar(widget, out_path: Path) -> None:
  """Renderiza un fotograma del widget a pantalla completa y lo exporta a PNG."""
  rl.begin_drawing()
  rl.clear_background(rl.BLACK)
  widget.render(rl.Rectangle(0, 0, gui_app.width, gui_app.height))
  rl.end_drawing()

  img = rl.load_image_from_screen()
  rl.export_image(img, str(out_path))
  rl.unload_image(img)
  print("ok", out_path)


def _capturar_splash(out_dir: Path) -> None:
  # El splash es time-based (LOGO_DUR=1.4, DURACION=2.2): se fija su reloj
  # (time.monotonic, leído por orbit_splash._render) a los instantes pedidos
  # en vez de dormir en tiempo real. No se toca el módulo del splash.
  splash = orbit_splash.OrbitSplash()
  splash._start = 0.0
  for t, nombre in ((0.5, "splash_0.5s.png"), (1.4, "splash_1.4s.png")):
    with mock.patch.object(orbit_splash.time, "monotonic", return_value=t):
      _capturar(splash, out_dir / nombre)


def _capturar_home(params: Params, out_dir: Path) -> None:
  # El satélite del anillo Dúplex depende de OrbitConnected.
  # ServerMonitor sondea la red de verdad en un hilo de fondo (_loop); para
  # que la escena "conectado" sea coherente (tarjeta SERVIDOR/ENLACE en
  # verde, no "Sin conexion" en ambar) sin tocar el modulo de producto, se
  # anula _loop en el scope del script -ninguna instancia sondea la red- y
  # se fijan los atributos a mano segun el escenario, igual que se fijo el
  # reloj del splash.
  with mock.patch.object(ServerMonitor, "_loop", lambda self: None):
    for conectado, nombre in ((True, "home_conectado.png"), (False, "home_sin_conexion.png")):
      # block=True: si no, la escritura es async (putBoolNonBlocking) y la
      # lectura inmediata de mas abajo (_fast_refresh, en show_event) puede
      # correr antes de que el valor este en disco.
      params.put_bool("OrbitConnected", conectado, block=True)
      params.put_bool("OrbitClaimed", conectado, block=True)
      params.put("OrbitOwner", "demo@orbit" if conectado else "", block=True)
      home = HomeLayout()
      home.show_event()
      home._server._broker_ok = conectado
      home._server._backend_ok = conectado
      # Salta la animacion de entrada (anillo, cascada de tarjetas, fade del
      # header) para capturar el estado asentado, igual que el script ad-hoc.
      home._shown_at = time.monotonic() - 5.0
      _capturar(home, out_dir / nombre)


def _capturar_panel(out_dir: Path) -> None:
  panel = OrbitLayout()
  panel.show_event()
  _capturar(panel, out_dir / "panel_orbit.png")


def _capturar_qr(params: Params, out_dir: Path) -> None:
  # Codigo de emparejamiento minimo para que el dialogo tenga QR que dibujar;
  # sin reclamar, para ver la vista de vinculacion (no la de "Vinculado").
  params.put("OrbitPairingCode", "TEST1234", block=True)
  params.put_bool("OrbitClaimed", False, block=True)
  dialog = OrbitEnrollDialog()
  _capturar(dialog, out_dir / "vinculacion_qr.png")
  del dialog


def main() -> None:
  out_dir = Path(sys.argv[1])
  out_dir.mkdir(parents=True, exist_ok=True)

  params = Params()
  originales = {k: params.get(k) for k in PARAM_KEYS}

  gui_app.init_window("orbit capturas")
  try:
    _capturar_splash(out_dir)
    _capturar_home(params, out_dir)
    _capturar_panel(out_dir)
    _capturar_qr(params, out_dir)
  finally:
    rl.close_window()
    for k, v in originales.items():
      if v is None:
        params.remove(k)
      elif isinstance(v, bool):
        params.put_bool(k, v, block=True)
      else:
        params.put(k, str(v), block=True)


if __name__ == "__main__":
  main()
