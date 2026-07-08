from openpilot.tools.sim.bridge.metadrive import metadrive_command as cmd
from openpilot.tools.sim.bridge.metadrive.metadrive_maps import MAP_NAMES, get_map_config

TRAFFIC_STEP = 0.05
TRAFFIC_ON_DEFAULT = 0.1


def ahead_pose(lane, ego_position, distance, lateral=0.0):
  # Pure geometry: project a pose `distance` metres ahead of the ego along its lane.
  lon, lat = lane.local_coordinates(ego_position)
  s = min(lon + distance, getattr(lane, "length", lon + distance))
  pos = lane.position(s, lat + lateral)
  heading = lane.heading_theta_at(s)
  return pos, heading


class ModMenu:
  def __init__(self, env, opts):
    self.env = env
    self.track_size = opts.get("track_size", 60)
    self.render = opts.get("render", False)
    self.traffic_density = opts.get("traffic_density", 0.0)
    name = opts.get("map_name", "loop")
    self.map_idx = MAP_NAMES.index(name) if name in MAP_NAMES else 0
    self.spawned_ids = []
    self.pending_reset = False       # process should apply traffic + reset()
    self.pending_map = None          # process should switch map + reset()
    self.hud = None
    self.hud_visible = True

  # ---- dispatch ----------------------------------------------------------
  def apply(self, command):
    if command == cmd.LEAD:
      self.spawn_lead()
    elif command == cmd.CUTIN:
      self.spawn_cutin()
    elif command == cmd.OBSTACLE:
      self.spawn_obstacle(0.0)
    elif command == cmd.OBSTACLE_SIDE:
      self.spawn_obstacle(2.0)
    elif command == cmd.CLEAR:
      self.clear()
    elif command == cmd.HUD:
      self.toggle_hud()
    elif command == cmd.TRAFFIC_TOGGLE:
      self.traffic_density = 0.0 if self.traffic_density >= 0.01 else TRAFFIC_ON_DEFAULT
      self.pending_reset = True
    elif command == cmd.TRAFFIC_UP:
      self.traffic_density = min(1.0, self.traffic_density + TRAFFIC_STEP)
      self.pending_reset = True
    elif command == cmd.TRAFFIC_DOWN:
      self.traffic_density = max(0.0, self.traffic_density - TRAFFIC_STEP)
      self.pending_reset = True
    elif command == cmd.MAP_NEXT:
      self.map_idx = (self.map_idx + 1) % len(MAP_NAMES)
      self.pending_map = MAP_NAMES[self.map_idx]
    elif command == cmd.MAP_PREV:
      self.map_idx = (self.map_idx - 1) % len(MAP_NAMES)
      self.pending_map = MAP_NAMES[self.map_idx]
    self.draw_hud()

  def map_config_for(self, name):
    return get_map_config(name, self.track_size)

  # ---- object lifecycle --------------------------------------------------
  def clear(self):
    eng = self.env.engine
    if not self.spawned_ids:
      return
    tm = getattr(eng, "traffic_manager", None)
    if tm is not None:
      if hasattr(tm, "_traffic_vehicles"):
        tm._traffic_vehicles = [v for v in tm._traffic_vehicles if v.id not in self.spawned_ids]
      # cut-ins are registered in the traffic manager too; drop the stale refs so the
      # manager's own before_reset() does not KeyError clearing an already-gone id.
      if hasattr(tm, "spawned_objects"):
        for _id in self.spawned_ids:
          tm.spawned_objects.pop(_id, None)
    eng.clear_objects(list(self.spawned_ids))
    self.spawned_ids = []

  def on_reset(self):
    # Objects spawned via engine.spawn_object are NOT owned by a manager, and
    # env.reset() asserts none remain — so callers must clear() BEFORE reset().
    # This only drops any leftover refs afterwards as a safety net.
    self.spawned_ids = []

  # ---- spawns (lazy metadrive imports) -----------------------------------
  def _ego_lane(self):
    ego = self.env.vehicle
    if ego is None or getattr(ego, "navigation", None) is None:
      return None, None
    return ego, ego.lane

  def spawn_lead(self):
    from metadrive.component.vehicle.vehicle_type import DefaultVehicle
    ego, lane = self._ego_lane()
    if lane is None:
      return
    pos, heading = ahead_pose(lane, ego.position, 40.0)
    v = self.env.engine.spawn_object(
      DefaultVehicle,
      vehicle_config=dict(spawn_position_heading=(pos, heading), spawn_velocity=None),
    )
    self.spawned_ids.append(v.id)

  def spawn_cutin(self):
    import numpy as np
    from metadrive.component.vehicle.vehicle_type import DefaultVehicle
    from metadrive.policy.idm_policy import IDMPolicy
    ego, lane = self._ego_lane()
    if lane is None:
      return
    lon, lat = lane.local_coordinates(ego.position)
    s = min(lon + 25.0, getattr(lane, "length", lon + 25.0))
    w = lane.width_at(s)
    pos = lane.position(s, lat + w)
    heading = lane.heading_theta_at(s)
    speed = 8.0
    vel = [speed * np.cos(heading), speed * np.sin(heading)]
    eng = self.env.engine
    tm = eng.traffic_manager
    v = tm.spawn_object(
      DefaultVehicle,
      vehicle_config=dict(spawn_position_heading=(pos, heading),
                          spawn_velocity=vel, spawn_velocity_car_frame=False),
    )
    tm.add_policy(v.id, IDMPolicy, v, eng.generate_seed())
    tm._traffic_vehicles.append(v)             # required so before_step drives it
    self.spawned_ids.append(v.id)

  def spawn_obstacle(self, lateral=0.0):
    from metadrive.component.static_object.traffic_object import TrafficWarning
    ego, lane = self._ego_lane()
    if lane is None:
      return
    pos, heading = ahead_pose(lane, ego.position, 30.0, lateral)
    obj = self.env.engine.spawn_object(
      TrafficWarning, lane=lane, position=pos, heading_theta=heading, static=True,
    )
    self.spawned_ids.append(obj.id)

  # ---- HUD ---------------------------------------------------------------
  def create_hud(self):
    if not self.render:
      return
    from direct.gui.OnscreenText import OnscreenText
    from panda3d.core import TextNode
    if self.hud is not None:
      self.hud.destroy()                       # avoid stacking/orphaning nodes on map switch
    self.hud = OnscreenText(
      text="", parent=self.env.engine.aspect2d, pos=(-1.31, 0.92), scale=0.045,
      fg=(1, 1, 1, 1), bg=(0, 0, 0, 0.55), align=TextNode.ALeft, mayChange=True,
    )
    self.draw_hud()

  def toggle_hud(self):
    if self.hud is None:
      return
    self.hud_visible = not self.hud_visible
    self.hud.show() if self.hud_visible else self.hud.hide()

  def draw_hud(self):
    if self.hud is None or not self.hud_visible:
      return
    traffic = ("ON %.2f" % self.traffic_density) if self.traffic_density >= 0.01 else "OFF"
    self.hud.setText(
      "MOD-MENU  [h]\n"
      "map: %s\n"
      "traffic: %s\n"
      "spawned: %d\n"
      "[l]lead [k]cut-in\n"
      "[o]obst [p]side\n"
      "[t]traffic  +/-\n"
      "[m/n]map  [c]clear\n"
      "[r]reset [wasd]drive"
      % (MAP_NAMES[self.map_idx], traffic, len(self.spawned_ids))
    )
