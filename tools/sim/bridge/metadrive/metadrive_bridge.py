import math
from multiprocessing import Queue

from metadrive.component.sensors.base_camera import _cuda_enable

from openpilot.tools.sim.bridge.common import SimulatorBridge
from openpilot.tools.sim.bridge.metadrive.metadrive_common import RGBCameraRoad, RGBCameraWide
from openpilot.tools.sim.bridge.metadrive.metadrive_world import MetaDriveWorld
from openpilot.tools.sim.bridge.metadrive.metadrive_maps import get_map_config
from openpilot.tools.sim.lib.camerad import W, H


class MetaDriveBridge(SimulatorBridge):
  TICKS_PER_FRAME = 5

  def __init__(self, dual_camera, high_quality, test_duration=math.inf, test_run=False,
               map="loop", traffic=0.0, render=False, track_size=60):
    super().__init__(dual_camera, high_quality)

    self.should_render = render
    self.test_run = test_run
    self.test_duration = test_duration if self.test_run else math.inf
    self.map = map
    self.traffic = traffic
    self.track_size = track_size

  def build_config(self):
    sensors = {
      "rgb_road": (RGBCameraRoad, W, H, )
    }

    if self.dual_camera:
      sensors["rgb_wide"] = (RGBCameraWide, W, H)

    config = dict(
      use_render=self.should_render,
      vehicle_config=dict(
        enable_reverse=False,
        render_vehicle=False,
        image_source="rgb_road",
      ),
      sensors=sensors,
      image_on_cuda=_cuda_enable,
      image_observation=True,
      interface_panel=[],
      out_of_route_done=False,
      on_continuous_line_done=False,
      crash_vehicle_done=False,
      crash_object_done=False,
      arrive_dest_done=False,
      traffic_density=self.traffic,
      map_config=get_map_config(self.map, self.track_size),
      decision_repeat=1,
      physics_world_step_size=self.TICKS_PER_FRAME/100,
      preload_models=False,
      show_logo=False,
      anisotropic_filtering=False
    )

    if self.should_render:
      # A visible window alongside CUDA offscreen cameras is a fragile combo;
      # single-threaded rendering avoids black frames / GL threading crashes.
      config["multi_thread_render"] = False

    return config

  def spawn_world(self, queue: Queue):
    config = self.build_config()
    modmenu_opts = dict(map_name=self.map, track_size=self.track_size,
                        render=self.should_render, traffic_density=self.traffic)
    return MetaDriveWorld(queue, config, self.test_duration, self.test_run,
                          self.dual_camera, modmenu_opts=modmenu_opts)
