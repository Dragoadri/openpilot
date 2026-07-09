#!/usr/bin/env python3
# Preview a map preset in a MetaDrive window without launching openpilot.
# Usage: ./preview_map.py --map roundabout   (Ctrl-C or close the window to quit)
import argparse

from metadrive.envs.metadrive_env import MetaDriveEnv

from openpilot.tools.sim.bridge.metadrive.metadrive_maps import get_map_config, MAP_NAMES


def main():
  parser = argparse.ArgumentParser(description="Preview a MetaDrive map preset.")
  parser.add_argument("--map", default="roundabout", help="one of: " + ", ".join(MAP_NAMES))
  parser.add_argument("--track-size", type=int, default=60, dest="track_size")
  args = parser.parse_args()

  env = MetaDriveEnv(dict(
    use_render=True,
    # The minimal MetaDrive fork strips 3D meshes/assets: skip the logo texture,
    # the pedestrian/cone/barrier model preload, and the ego car mesh (drawn as a
    # box) so the render window doesn't crash on missing gltf/png files.
    show_logo=False,
    preload_models=False,
    vehicle_config=dict(render_vehicle=False),
    map_config=get_map_config(args.map, args.track_size),
    traffic_density=0.0,
  ))
  try:
    env.reset()
    print(f"Previewing '{args.map}'. Close the window or Ctrl-C to quit.")
    while True:
      _, _, terminated, truncated, _ = env.step([0.0, 0.0])
      env.render()
      if terminated or truncated:
        env.reset()
  except KeyboardInterrupt:
    pass
  finally:
    env.close()


if __name__ == "__main__":
  main()
