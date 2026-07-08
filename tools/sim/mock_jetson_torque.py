#!/usr/bin/env python3
"""
Mock de la Jetson para pruebas en simulador.

Publica torques por ZMQ en formato float32, exactamente igual que haria
PilotNet en la Jetson real. Sirve para probar el selector de torque y la
UI (CT/AT/JT) en el simulador sin necesidad de tener la Jetson conectada.

ZMQ topology (debe coincidir con sicuem/orbit/zmq_client.py):
  - Jetson (este script):   PUSH socket bind('tcp://*:5556')
  - Comma (zmq_client):     PULL socket connect('tcp://<jetson_ip>:5556')

Para que el sim conecte con este mock, en config_jetson.json poner:
  "jetson_ip": "127.0.0.1"
  "jetson_enabled": true
  "jetson_torque_port": 5556

Uso:
  ./mock_jetson_torque.py constant 0.5
  ./mock_jetson_torque.py sweep
  ./mock_jetson_torque.py sine
  ./mock_jetson_torque.py manual          # interactivo: teclas a/d para girar
  ./mock_jetson_torque.py off             # publica 0 (verificar dead-zone)
  ./mock_jetson_torque.py silent          # NO publica (verificar watchdog)
"""

import argparse
import math
import struct
import sys
import time

import zmq

DEFAULT_PORT = 5556
PUBLISH_HZ = 5.0     # Frecuencia de publicacion (la Jetson real va a ~4-5 Hz)


def make_socket(port: int) -> zmq.Socket:
  ctx = zmq.Context.instance()
  sock = ctx.socket(zmq.PUSH)
  sock.setsockopt(zmq.LINGER, 0)
  sock.setsockopt(zmq.SNDHWM, 1)   # descarta si nadie escucha
  sock.bind(f"tcp://*:{port}")
  return sock


def send_torque(sock: zmq.Socket, value: float) -> None:
  """Empaqueta como float32 little-endian, igual que la Jetson real."""
  sock.send(struct.pack("f", value), flags=zmq.NOBLOCK)


def mode_constant(sock: zmq.Socket, value: float) -> None:
  print(f"[mock] modo CONSTANT {value:+.2f} a {PUBLISH_HZ} Hz. Ctrl+C para parar.")
  period = 1.0 / PUBLISH_HZ
  while True:
    send_torque(sock, value)
    print(f"  ->  {value:+.3f}", end="\r", flush=True)
    time.sleep(period)


def mode_sweep(sock: zmq.Socket) -> None:
  """Barrido lento de -1 a +1 y vuelta. Util para ver respuesta proporcional."""
  print(f"[mock] modo SWEEP -1 -> +1 -> -1, periodo 10s. Ctrl+C para parar.")
  period = 1.0 / PUBLISH_HZ
  t0 = time.time()
  while True:
    t = (time.time() - t0) % 10.0
    value = -1.0 + (t / 5.0) if t < 5.0 else 1.0 - ((t - 5.0) / 5.0)
    value = max(-1.0, min(1.0, value))
    send_torque(sock, value)
    print(f"  t={t:5.2f}s  ->  {value:+.3f}", end="\r", flush=True)
    time.sleep(period)


def mode_sine(sock: zmq.Socket) -> None:
  """Sinusoide periodo 6s entre -0.7 y +0.7 (no satura, mas realista)."""
  print(f"[mock] modo SINE amp=0.7 periodo=6s. Ctrl+C para parar.")
  period = 1.0 / PUBLISH_HZ
  t0 = time.time()
  while True:
    t = time.time() - t0
    value = 0.7 * math.sin(2 * math.pi * t / 6.0)
    send_torque(sock, value)
    print(f"  t={t:6.2f}s  ->  {value:+.3f}", end="\r", flush=True)
    time.sleep(period)


def mode_off(sock: zmq.Socket) -> None:
  """Publica 0 constante. Verifica que la dead-zone deja AT en 0."""
  print("[mock] modo OFF: publica 0.0 a 5 Hz. AT deberia ser 0.00.")
  period = 1.0 / PUBLISH_HZ
  while True:
    send_torque(sock, 0.0)
    time.sleep(period)


def mode_silent(_sock: zmq.Socket) -> None:
  """No publica nada. Verifica que el watchdog corta a 0 tras 500ms."""
  print("[mock] modo SILENT: no se publica nada. Verifica watchdog.")
  print("       En la UI del sim, AT deberia ir a 0.00 en <1s tras arrancar este modo.")
  while True:
    time.sleep(1.0)


def mode_manual(sock: zmq.Socket) -> None:
  """Lee teclas en bruto para girar."""
  import tty
  import termios

  print("[mock] modo MANUAL. Teclas: 'a' izquierda, 'd' derecha, espacio = neutro, 'q' salir.")
  fd = sys.stdin.fileno()
  old = termios.tcgetattr(fd)
  value = 0.0
  period = 1.0 / PUBLISH_HZ
  last_send = 0.0
  try:
    tty.setcbreak(fd)
    while True:
      now = time.time()
      if now - last_send >= period:
        send_torque(sock, value)
        last_send = now
        print(f"  torque={value:+.2f}", end="\r", flush=True)
      # lectura no bloqueante
      import select
      r, _, _ = select.select([sys.stdin], [], [], period / 2)
      if r:
        ch = sys.stdin.read(1)
        if ch == 'a':
          value = max(-1.0, value - 0.1)
        elif ch == 'd':
          value = min(1.0, value + 0.1)
        elif ch == ' ':
          value = 0.0
        elif ch == 'q':
          break
  finally:
    termios.tcsetattr(fd, termios.TCSADRAIN, old)
    print()


def main() -> None:
  ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
  ap.add_argument("mode", choices=["constant", "sweep", "sine", "off", "silent", "manual"])
  ap.add_argument("value", nargs="?", type=float, default=0.5,
                  help="Valor de torque (solo modo constant). Default 0.5.")
  ap.add_argument("--port", type=int, default=DEFAULT_PORT,
                  help=f"Puerto ZMQ donde bindear (default {DEFAULT_PORT})")
  args = ap.parse_args()

  if not -1.0 <= args.value <= 1.0:
    print(f"ERROR: value debe estar en [-1, 1], se dio {args.value}", file=sys.stderr)
    sys.exit(1)

  sock = make_socket(args.port)
  print(f"[mock] PUSH bind tcp://*:{args.port}  (el ZMQClient del Comma debe connect aqui)")

  try:
    if args.mode == "constant":
      mode_constant(sock, args.value)
    elif args.mode == "sweep":
      mode_sweep(sock)
    elif args.mode == "sine":
      mode_sine(sock)
    elif args.mode == "off":
      mode_off(sock)
    elif args.mode == "silent":
      mode_silent(sock)
    elif args.mode == "manual":
      mode_manual(sock)
  except KeyboardInterrupt:
    print("\n[mock] detenido por usuario")
  finally:
    sock.close(linger=0)


if __name__ == "__main__":
  main()
