openpilot in simulator
=====================

openpilot implements a [bridge](run_bridge.py) that allows it to run in the [MetaDrive simulator](https://github.com/metadriverse/metadrive).

## Launching openpilot
First, start openpilot.
``` bash
# Run locally
./tools/sim/launch_openpilot.sh
```

## Bridge usage
```
$ ./run_bridge.py -h
usage: run_bridge.py [-h] [--joystick] [--high_quality] [--dual_camera]
Bridge between the simulator and openpilot.

options:
  -h, --help            show this help message and exit
  --joystick
  --high_quality
  --dual_camera
```

#### Bridge Controls:
- To engage openpilot press 2, then press 1 to increase the speed and 2 to decrease.
- To disengage, press "S" (simulates a user brake)

#### All inputs:

```
| key  |   functionality       |
|------|-----------------------|
|  1   | Cruise Resume / Accel |
|  2   | Cruise Set    / Decel |
|  3   | Cruise Cancel         |
|  r   | Reset Simulation      |
|  i   | Toggle Ignition       |
|  q   | Exit all              |
| wasd | Control manually      |
```

## MetaDrive

### Launching Metadrive
Start bridge processes located in tools/sim:
``` bash
./run_bridge.py
```

## Maps & Mod-Menu

Pick a map and (optionally) enable traffic and the on-screen mod-menu at launch:

```bash
./run_bridge.py --map roundabout --render          # drive a roundabout with the HUD
./run_bridge.py --map intersection_x --traffic 0.1 # a 4-way with light traffic
```

Map presets: `loop` (default, endless track), `roundabout`, `intersection_x`,
`intersection_t`, `highway`, `ramps`. Preview any map without openpilot:

```bash
./preview_map.py --map roundabout
```

### Mod-menu hotkeys (press in the run_bridge terminal)

| key | action | key | action |
|-----|--------|-----|--------|
| `l` | spawn stopped lead car | `t` | toggle traffic |
| `k` | spawn cut-in NPC (IDM)  | `+`/`-` | traffic density up/down |
| `o` | obstacle ahead (in lane)| `m`/`n` | next / previous map |
| `p` | obstacle offset to side | `c` | clear spawned objects |
| `h` | toggle HUD              | `r` | reset · `wasd` drive |

### Caveats (minimal MetaDrive fork)

- NPC vehicles and cones/barriers render as **boxes** (car/cone/barrier 3D
  meshes are stripped from the minimal assets). The default obstacle is a
  traffic **warning** sign, which is the only static object with a real mesh.
  Physics/collision and IDM behaviour are unaffected — good for testing
  avoidance and lead-car response, not for visual fidelity.
- Traffic is CPU-expensive; it is off by default.
- Real maps (Waymo/nuScenes/OSM via `ScenarioEnv`) are **not supported** here:
  they need the separate `scenarionet` package, converted datasets, and the 3D
  models the minimal fork strips. Do not wire `ScenarioEnv` into the bridge.