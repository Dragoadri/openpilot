#!/usr/bin/env python3
import argparse

from typing import Any
from multiprocessing import Queue

from openpilot.tools.sim.bridge.metadrive.metadrive_bridge import MetaDriveBridge

def create_bridge(dual_camera, high_quality, map="loop", traffic=0.0, render=False, track_size=60):
  queue: Any = Queue()

  simulator_bridge = MetaDriveBridge(dual_camera, high_quality, map=map, traffic=traffic,
                                     render=render, track_size=track_size)
  simulator_process = simulator_bridge.run(queue)

  return queue, simulator_process, simulator_bridge

def main():
  _, simulator_process, _ = create_bridge(True, False)
  simulator_process.join()

def parse_args(add_args=None):
  parser = argparse.ArgumentParser(description='Bridge between the simulator and openpilot.')
  parser.add_argument('--joystick', action='store_true')
  parser.add_argument('--high_quality', action='store_true')
  parser.add_argument('--dual_camera', action='store_true')
  parser.add_argument('--map', default='loop',
                      help='map preset: loop, roundabout, intersection_x, intersection_t, highway, ramps')
  parser.add_argument('--traffic', type=float, default=0.0,
                      help='traffic density 0.0-1.0 (0 disables; expensive)')
  parser.add_argument('--render', action='store_true',
                      help='open the MetaDrive window with the mod-menu HUD')
  parser.add_argument('--track-size', type=int, default=60, dest='track_size',
                      help='loop preset size')

  return parser.parse_args(add_args)

if __name__ == "__main__":
  args = parse_args()

  queue, simulator_process, simulator_bridge = create_bridge(
    args.dual_camera, args.high_quality, map=args.map, traffic=args.traffic,
    render=args.render, track_size=args.track_size)

  if args.joystick:
    # start input poll for joystick
    from openpilot.tools.sim.lib.manual_ctrl import wheel_poll_thread

    wheel_poll_thread(queue)
  else:
    # start input poll for keyboard
    from openpilot.tools.sim.lib.keyboard_ctrl import keyboard_poll_thread

    keyboard_poll_thread(queue)

  simulator_bridge.shutdown()

  simulator_process.join()
