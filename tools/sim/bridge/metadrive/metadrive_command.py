# Mod-menu command vocabulary. Plain strings so both the bridge process and the
# metadrive process can share them without importing metadrive.

LEAD = "mod_lead"                  # stopped car ahead (lead / hard-brake test)
CUTIN = "mod_cutin"               # moving IDM car in adjacent lane
OBSTACLE = "mod_obstacle"         # obstacle centred in lane (dodge / stop test)
OBSTACLE_SIDE = "mod_obstacle_side"  # obstacle offset into the lane
TRAFFIC_TOGGLE = "mod_traffic_toggle"
TRAFFIC_UP = "mod_traffic_up"
TRAFFIC_DOWN = "mod_traffic_down"
MAP_NEXT = "mod_map_next"
MAP_PREV = "mod_map_prev"
CLEAR = "mod_clear"               # remove everything spawned
HUD = "mod_hud"                   # toggle the on-screen HUD

ALL = {
  LEAD, CUTIN, OBSTACLE, OBSTACLE_SIDE, TRAFFIC_TOGGLE, TRAFFIC_UP,
  TRAFFIC_DOWN, MAP_NEXT, MAP_PREV, CLEAR, HUD,
}


def is_mod_command(info):
  return isinstance(info, str) and info in ALL
