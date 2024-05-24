# Cython, now uses scons to build
from openpilot.selfdrive.boardd.boardd_api_impl import can_list_to_can_capnp
assert can_list_to_can_capnp

# [Start Adrian] ****************************************************************************
sttime = datetime.now().strftime('%Y/%m/%d_%H:%M:%S')
f = open("boardd.txt", "a")
f.write(f"[{sttime}] ping...\n")
f.close()
# [End Adrian] ******************************************************************************


def can_capnp_to_can_list(can, src_filter=None):
  ret = []
  for msg in can:
    if src_filter is None or msg.src in src_filter:
      ret.append((msg.address, msg.busTime, msg.dat, msg.src))
  return ret
