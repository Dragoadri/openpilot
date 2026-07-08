from metadrive.component.map.pg_map import MapGenerateMethod


def straight_block(length):
  return {"id": "S", "pre_block_socket_index": 0, "length": length}


def curve_block(length, angle=45, direction=0):
  return {"id": "C", "pre_block_socket_index": 0, "length": length,
          "radius": length, "angle": angle, "dir": direction}


def create_map(track_size=60):
  # The historical default: a closed 4-straight / 4-curve loop for endless driving.
  curve_len = track_size * 2
  return dict(
    type=MapGenerateMethod.PG_MAP_FILE,
    lane_num=2,
    lane_width=4.5,
    config=[
      None,
      straight_block(track_size),
      curve_block(curve_len, 90),
      straight_block(track_size),
      curve_block(curve_len, 90),
      straight_block(track_size),
      curve_block(curve_len, 90),
      straight_block(track_size),
      curve_block(curve_len, 90),
    ],
  )


def _sequence_map(block_sequence, lane_num=3, lane_width=3.5):
  # A procedurally-built map from a block-letter string (S,C,O,X,T,r,R,...).
  # Entry/exit straights flank special blocks so the ego routes in and out.
  return dict(
    type=MapGenerateMethod.BIG_BLOCK_SEQUENCE,
    lane_num=lane_num,
    lane_width=lane_width,
    config=block_sequence,
  )


# name -> builder(track_size) -> map_config dict
_BUILDERS = {
  "loop":           lambda ts: create_map(ts),
  "roundabout":     lambda ts: _sequence_map("SOS"),
  "intersection_x": lambda ts: _sequence_map("SXS"),
  "intersection_t": lambda ts: _sequence_map("STS"),
  "highway":        lambda ts: _sequence_map("SSSS", lane_num=3),
  "ramps":          lambda ts: _sequence_map("SrRS", lane_num=3),
}

# Cycle order for the mod-menu (loop stays first = current default).
MAP_NAMES = ["loop", "roundabout", "intersection_x", "intersection_t", "highway", "ramps"]


def get_map_config(name, track_size=60):
  builder = _BUILDERS.get(name, _BUILDERS["loop"])
  return builder(track_size)
