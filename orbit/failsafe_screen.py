#!/usr/bin/env python3
"""Pantalla de emergencia del arranque: enseña el registro cuando todo lo demás ha muerto.

launch_chffrplus.sh la lanza si manager.py termina. Depende SOLO de pyray: nada
de cereal, params, fuentes del repo ni del paquete openpilot, porque cualquiera
de esas piezas puede ser precisamente lo que ha fallado. Usa la fuente por
defecto de raylib y muestra las últimas líneas de los ficheros que se le pasan
(el registro persistente de arranque y el volcado de tmux).

Uso:  failsafe_screen.py [--once] fichero [fichero ...]

Sin botones: el usuario fotografía la pantalla y apaga y enciende. --once pinta
un solo fotograma y sale (para tests).
"""
import os
import sys

WIDTH, HEIGHT = 2160, 1080
MARGIN = 40
FONT_SIZE = 28          # la fuente por defecto de raylib es de 10 px; se escala
LINE_H = 34
MAX_COLS = 120
FPS = 5

TITLE = "ORBIT: el arranque no ha terminado. Registro del arranque (foto = diagnostico):"
FOOT = "Apaga y enciende para reintentar. Registro completo en /data/orbit_boot.log"


def tail(path: str, n: int) -> list[str]:
  try:
    with open(path, encoding="utf-8", errors="replace") as f:
      lines = [ln.rstrip("\n") for ln in f.readlines()]
  except Exception as e:
    return [f"({path}: {type(e).__name__})"]
  return lines[-n:] if lines else [f"({path}: vacio)"]


def build_lines(paths: list[str], rows: int) -> list[str]:
  """Reparte las filas disponibles entre los ficheros, el primero con prioridad."""
  out: list[str] = []
  if not paths:
    return out
  per = max(4, rows // len(paths))
  for i, p in enumerate(paths):
    budget = rows - len(out) if i == len(paths) - 1 else per
    out.append(f"== {p}")
    for ln in tail(p, max(0, budget - 1)):
      out.append(ln[:MAX_COLS])
  return out[:rows]


def main(argv: list[str]) -> int:
  once = "--once" in argv
  paths = [a for a in argv[1:] if a != "--once"]
  rows = (HEIGHT - 2 * MARGIN - 3 * LINE_H) // LINE_H
  lines = build_lines(paths, rows)

  import pyray as rl  # import tardío: si ni esto existe, salimos con codigo != 0 y el shell sigue
  rl.set_trace_log_level(rl.TraceLogLevel.LOG_WARNING)
  rl.set_config_flags(rl.ConfigFlags.FLAG_MSAA_4X_HINT)
  rl.init_window(WIDTH, HEIGHT, "ORBIT failsafe")
  rl.set_target_fps(FPS)
  try:
    while not rl.window_should_close():
      rl.begin_drawing()
      rl.clear_background(rl.Color(8, 12, 24, 255))
      font = rl.get_font_default()
      y = MARGIN
      rl.draw_text_ex(font, TITLE, rl.Vector2(MARGIN, y), FONT_SIZE, 2, rl.Color(255, 196, 64, 255))
      y += LINE_H * 2
      for ln in lines:
        color = rl.Color(255, 120, 120, 255) if ("FALLO" in ln or "error" in ln.lower() or "Traceback" in ln) else rl.RAYWHITE
        rl.draw_text_ex(font, ln, rl.Vector2(MARGIN, y), FONT_SIZE, 2, color)
        y += LINE_H
      rl.draw_text_ex(font, FOOT, rl.Vector2(MARGIN, HEIGHT - MARGIN - LINE_H), FONT_SIZE, 2, rl.Color(150, 170, 200, 255))
      rl.end_drawing()
      if once:
        break
  finally:
    rl.close_window()
  return 0


if __name__ == "__main__":
  if os.environ.get("ORBIT_FAILSAFE_HIDDEN") == "1":  # tests: ventana oculta
    import pyray as _rl
    _rl.set_config_flags(_rl.ConfigFlags.FLAG_WINDOW_HIDDEN)
  sys.exit(main(sys.argv))
