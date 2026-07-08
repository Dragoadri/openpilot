import sys
import termios
import time

from multiprocessing import Queue
from termios import (BRKINT, CS8, CSIZE, ECHO, ICANON, ICRNL, IEXTEN, INPCK,
                     ISTRIP, IXON, PARENB, VMIN, VTIME)
from typing import NoReturn, TYPE_CHECKING

from openpilot.tools.sim.bridge.metadrive import metadrive_command as mod

if TYPE_CHECKING:
  from openpilot.tools.sim.bridge.common import QueueMessage

# Indexes for termios list.
IFLAG = 0
OFLAG = 1
CFLAG = 2
LFLAG = 3
ISPEED = 4
OSPEED = 5
CC = 6


KEYBOARD_HELP = """
  | key  |   functionality       |
  |------|-----------------------|
  |  1   | Cruise Resume / Accel |
  |  2   | Cruise Set    / Decel |
  |  3   | Cruise Cancel         |
  |  r   | Reset Simulation      |
  |  i   | Toggle Ignition       |
  |  q   | Exit all              |
  | wasd | Control manually      |
  |------| --- MOD-MENU -------- |
  |  l   | Spawn stopped lead car|
  |  k   | Spawn cut-in NPC (IDM)|
  |  o/p | Obstacle ahead / side |
  |  t   | Toggle traffic        |
  | +/-  | Traffic density up/dn |
  | m/n  | Next / prev map       |
  |  c   | Clear spawned objects |
  |  h   | Toggle HUD            |
"""


_KEYMAP = {
  "1": "cruise_up",
  "2": "cruise_down",
  "3": "cruise_cancel",
  "w": f"throttle_{1.0}",
  "a": f"steer_{-0.15}",
  "s": f"brake_{1.0}",
  "d": f"steer_{0.15}",
  "z": "blinker_left",
  "x": "blinker_right",
  "i": "ignition",
  "r": "reset",
  "q": "quit",
  # --- mod-menu ---
  "l": mod.LEAD,
  "k": mod.CUTIN,
  "o": mod.OBSTACLE,
  "p": mod.OBSTACLE_SIDE,
  "t": mod.TRAFFIC_TOGGLE,
  "+": mod.TRAFFIC_UP,
  "=": mod.TRAFFIC_UP,
  "-": mod.TRAFFIC_DOWN,
  "m": mod.MAP_NEXT,
  "n": mod.MAP_PREV,
  "c": mod.CLEAR,
  "h": mod.HUD,
}


def key_to_command(c):
  return _KEYMAP.get(c)


def getch() -> str:
  STDIN_FD = sys.stdin.fileno()
  old_settings = termios.tcgetattr(STDIN_FD)
  try:
    # set
    mode = old_settings.copy()
    mode[IFLAG] &= ~(BRKINT | ICRNL | INPCK | ISTRIP | IXON)
    #mode[OFLAG] &= ~(OPOST)
    mode[CFLAG] &= ~(CSIZE | PARENB)
    mode[CFLAG] |= CS8
    mode[LFLAG] &= ~(ECHO | ICANON | IEXTEN)
    mode[CC][VMIN] = 1
    mode[CC][VTIME] = 0
    termios.tcsetattr(STDIN_FD, termios.TCSAFLUSH, mode)

    ch = sys.stdin.read(1)
  finally:
    termios.tcsetattr(STDIN_FD, termios.TCSADRAIN, old_settings)
  return ch

def print_keyboard_help():
  print(f"Keyboard Commands:\n{KEYBOARD_HELP}")

def keyboard_poll_thread(q: 'Queue[QueueMessage]'):
  from openpilot.tools.sim.bridge.common import control_cmd_gen

  print_keyboard_help()

  while True:
    c = getch()
    cmd = key_to_command(c)
    if cmd is None:
      print_keyboard_help()
      continue
    q.put(control_cmd_gen(cmd))
    if cmd == "quit":
      break

def test(q: 'Queue[str]') -> NoReturn:
  while True:
    print([q.get_nowait() for _ in range(q.qsize())] or None)
    time.sleep(0.25)

if __name__ == '__main__':
  from multiprocessing import Process, Queue
  q: 'Queue[QueueMessage]' = Queue()
  p = Process(target=test, args=(q,))
  p.daemon = True
  p.start()

  keyboard_poll_thread(q)
