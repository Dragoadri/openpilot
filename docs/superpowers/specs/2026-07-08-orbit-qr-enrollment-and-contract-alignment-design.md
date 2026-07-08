# ORBIT QR device enrollment + firmware↔backend↔app contract alignment

**Date:** 2026-07-08 · **Firmware branch:** `sicuem-mig` (repo `ORBITPILOT`) · **App/backend repo:** `orbit-iov` (`master`)

This spec is the authoritative contract for implementing the device (firmware)
side of ORBIT's QR device-enrollment protocol and for closing the remaining
MQTT contract mismatches between the firmware, the Flask backend and the Flutter
app. It was distilled from a read-only audit of both repos (evidence recorded as
`file:line` throughout the investigation).

## Scope decisions (confirmed with the user)

- Edit **both** repos: firmware (`sicuem-mig`) and `orbit-iov` (app + backend).
- QR is surfaced **only via a Settings → Device button** ("Link to ORBIT"); **no** auto-popup on home.
- Include all optional workstreams: `sicuem_torque` bridge, migration cleanup, and declaring `paho-mqtt` as a dependency.

## 1. QR enrollment contract (verified against ORBIT code, not just docs)

### 1.1 Enroll announcement — firmware → backend (MQTT)
- **Topic:** `telemetry_mqtt/<dongle_id>/enroll` (backend subscribes `telemetry_mqtt/+/enroll`).
- **Payload (JSON, UTF-8):**
  ```json
  { "dongle_id": "<id>", "pairing_code": "<CODE>", "issued_at": 0,
    "ttl_s": 600, "fw": "<version>", "hw": "comma3x" }
  ```
  Backend only *requires* `pairing_code` (uppercased on ingest) and optionally reads `ttl_s` (default 600). `issued_at`/`fw`/`hw`/`dongle_id` are accepted but currently ignored server-side.
- **QoS 0, `retain=False`** (a retained single-use code would be an anti-replay hazard; periodic re-publish covers late subscribers).

### 1.2 QR deep link (rendered on screen)
- `orbit://enroll?d=<dongle_id>&c=<pairing_code>` — print the raw `pairing_code` under the QR as a manual fallback (the app has a manual-entry mode).

### 1.3 Pairing code rules
- 8 chars, alphabet `ABCDEFGHJKLMNPQRSTUVWXYZ23456789` (31 chars, no `O/0/1/I`), **UPPERCASE**, generated with a CSPRNG (`secrets.choice`).
- Single-use, TTL default **600 s**. Rotate on expiry and after a successful ack.

### 1.4 Enroll ack — backend → firmware (MQTT)
- **Topic:** `telemetry_config/<dongle_id>/enroll_ack`.
- **Payload:** `{ "claimed": true, "user_id": <int>, "ts": "<iso8601>" }`.
- **Not retained, QoS 0** → the firmware must already be subscribed at claim time. It is (subscription lives in `on_connect`).
- On receipt: set claimed, stop advertising, hide the QR.

### 1.5 Known backend limitations (do not depend on these)
- No "device online" precondition is actually enforced on claim (docs overstate).
- No MQTT "unclaim/unlink" event exists yet → firmware cannot auto-re-enter enrollment on remote unlink today. We expose a local reset path only.

## 2. Firmware design (`sicuem-mig`)

### 2.1 New Params (register in `common/params_keys.h`, SIC-UEM block)
- `OrbitClaimed` → `{PERSISTENT, BOOL}` — single source of truth; survives reboot so the QR never reappears once claimed.
- `OrbitPairingCode` → `{CLEAR_ON_MANAGER_START, STRING}` — current ephemeral code for the UI to render (fresh each boot).
- `OrbitEnrollExpiry` → `{CLEAR_ON_MANAGER_START, STRING}` — issued-at/expiry (ms epoch) for optional countdown.

Unregistered keys raise `UnknownKeyName`; registration is mandatory.

### 2.2 Publisher — `sicuem/orbit/mqtt_envio_general.py`
- Add `_maybe_announce_enroll()` called from `loop()` right after the heartbeat block, modeled on the `HEARTBEAT_SECS` pattern.
  - Return early if `params.get_bool("OrbitClaimed")`.
  - If no current code or `now - issued_at >= ttl_s(600)`: generate a new uppercase code, set `issued_at=now`, write `OrbitPairingCode` + `OrbitEnrollExpiry`.
  - If `now - last_announce >= 30 s`: publish the enroll payload to `telemetry_mqtt/{DongleID}/enroll` (`qos=0, retain=False`).
  - `fw` from build metadata/version; `hw="comma3x"`.
  - Guard against the `DongleID` fallback literal (`"DongleID"`): re-read `DongleId` and skip announcing until it resolves.
- Init the new state vars (`_last_enroll`, `_enroll_issued_at`, `_pairing_code`) in `__init__`.

### 2.3 Subscriber — `sicuem/orbit/mqtt_comandos.py`
- Append `f"telemetry_config/{self.DongleID}/enroll_ack"` to the `on_connect` subscribe list (so broker hot-reload re-subscribes for free).
- Add router branch `elif topic.endswith("/enroll_ack"): self.handle_enroll_ack(payload)`.
- `handle_enroll_ack`: `json.loads`, if `data.get("claimed") is True` → `params.put_bool("OrbitClaimed", True)` and `params.remove("OrbitPairingCode")`. No anti-echo needed (firmware never publishes ack).

### 2.4 `sicuem_torque` bridge — `sicuem/orbit/mqtt_envio_general.py`
- The app + backend consume `sicuem_torque/<dongle>` but the firmware never publishes it.
- Publish `sicuem_torque/{DongleID}` JSON `{ "torque": <float>, "active": <bool>, "obstacle_detected": <bool>, "confidence": <float?>, "dongle_id": <id> }` at the same cadence as the existing obstacle-status publish. Source the numeric torque from the Jetson path (`zmq_client` / obstacle-pulse). Best-effort: if a clean numeric torque is unavailable, publish the boolean `active`/`obstacle_detected` derived from the existing status and clearly flag the limitation.

### 2.5 UI — Settings entry + dialog
- New `selfdrive/ui/widgets/orbit_enroll_dialog.py` (copy of `pairing_dialog.py`, Widget-based — comma3x is tici/`big_ui`, default layouts):
  - `_get_pairing_url` returns `orbit://enroll?d={DongleId}&c={OrbitPairingCode}` from Params.
  - Regenerate the QR texture when the code Param changes (not only on the 300 s timer).
  - `_update_state` pops when `params.get_bool("OrbitClaimed")` (NOT `prime_state.is_paired`).
  - Draw the raw code beneath the QR.
- `selfdrive/ui/layouts/settings/device.py`: add an "Link to ORBIT" `button_item` (visible only when `not OrbitClaimed`), mirroring the existing conditional "Pair Device" button, pushing `OrbitEnrollDialog()`.
- **No** auto-popup / `main.py` change (per decision).

### 2.6 Migration cleanup
- `sicuem/orbit/canales.json`: remove the `navInstruction` entry (dropped at runtime; not a cereal service in this build).
- `selfdrive/ui/sunnypilot/layouts/settings/uem_sub_layouts/teluem_settings.py`: remove the orphaned telemetry toggles whose only consumer was the retired `SicMqttHilo2` (keep `intervalos_toggle`, still read by `longcontrol.py`); drop stale `sicmqtthilo2.py` references in the module docstring.
- Delete dead legacy files `sicuem/sicmqtthilo.py` and `sicuem/sicmqtthilo2.py`; remove the stale comment in `system/manager/manager.py`.

### 2.7 paho dependency
- Declare `paho-mqtt` in `pyproject.toml` (and lock if `uv` is available) so clean/CI environments resolve the import.
- **Keep** the vendored `/paho` tree (the device image relies on it via `BASEDIR` on `PYTHONPATH`; deleting it risks silently disabling all telemetry on-device). Add a short note documenting the dual setup. Deleting the vendored tree is explicitly out of scope for safety.

## 3. orbit-iov changes (`master`)

- `backend/server/mqtt_handler.py`: subscribe to `telemetry_config/+/intervalos`, `telemetry_config/+/jetson_apply_target`, `telemetry_config/+/jetson_obstacle_status` (+ `jetson_obstacle_status/global`) if persistence is desired; extend `mode_names` with `3: "COMMA+JETSON"`.
- `app/lib/services/mqtt_service.dart`: include `_version` (epoch ms) in the `jetson_config` command payload so the firmware anti-echo layer-2 works; remove the dangling `resumen_principal` subscription and the `navInstruction` expectation (firmware no longer advertises it).
- These are additive/low-risk and must not change existing working command flows.

## 4. Parallelization & integration

Disjoint file ownership → agents run in parallel editing directly (no shared file):
- **Agent A (firmware MQTT+params+torque):** `common/params_keys.h`, `sicuem/orbit/mqtt_envio_general.py`, `sicuem/orbit/mqtt_comandos.py`.
- **Agent B (firmware UI):** `selfdrive/ui/widgets/orbit_enroll_dialog.py` (new), `selfdrive/ui/layouts/settings/device.py`.
- **Agent C (firmware cleanup+paho):** `sicuem/orbit/canales.json`, `.../teluem_settings.py`, delete `sicuem/sicmqtthilo*.py`, `system/manager/manager.py` comment, `pyproject.toml`.
- **Agent D (orbit-iov):** `backend/server/mqtt_handler.py`, `app/lib/services/mqtt_service.dart`.

## 5. Verification (no device/CI available here)
- Runtime import is not possible in this tree (no compiled `capnp`). Verification is: `python -m py_compile` on every changed `.py`, JSON validity for `canales.json`, and adversarial review of each diff against this contract. Flag anything that needs on-device confirmation.
