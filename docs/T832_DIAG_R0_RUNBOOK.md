# T832-DIAG-R0 capture-before-recovery runbook (candidate, not deployed)

This repository authors the integration but never executes it on hardware and never edits live Home Assistant. All commands below run on the HA host/operator side against already-written logs. The collector never opens the coordinator serial device.

## 1. Preconditions

- Diagnostic firmware T832-DIAG-R0 running; host file logging captures `zh:zstack:znp` DEBUG.msg lines with `T832D1:` payloads.
- Private store root, e.g. `/config/.private/t832-diag` (0700; JSONL 0600). Firmware SHA recorded via `t832_incident.py` firmware binding.
- Watchdog trigger defined as sustained loss of expected application traffic / bridge `online` false, not telemetry absence alone. Missing telemetry is loss of observability, never proof of CPU failure.
- Current HA automation mode `single` is not a substitute for the persisted per-incident latch in `state/incident-latch.json`.

## 2. Capture barrier (must precede any Z2M stop or control-line touch)

```sh
python3 firmware/t832/t832_incident.py \
  --root /config/.private/t832-diag \
  --config-fingerprint "$T832_CONFIG_FINGERPRINT" \
  capture --trigger "$TRIGGER_REASON" \
  --window-seconds 900 --deadline-seconds 30
```

Expected: `status:captured` with `bundle` path containing `manifest.json`, `SHA256.json`, `diag-15m.jsonl`, `host-events-15m.jsonl`. `manifest.json` records trigger, 15-minute window, latest diagnostic state, last successful command stages (`MT_COMMAND_RX/DISPATCH/COMPLETE`, `RESPONSE_QUEUED`, `NPI_TX_FINISHED`, startup stages, BDB dispatch/return), missing sources, firmware SHA, and the observability note. Partial/missing sources are explicit. The bundle directory is committed atomically; the latch moves to `captured` with `reset_used:false`.

If capture exceeds 30 s, fails, or evidence cannot be saved: inhibit automatic reset, surface a local operator alert per site contract, and stop. Do not send notifications from this executor. Do not proceed to control-line actions.

## 3. Exactly one validated USB RTS R2 recovery (only after `captured`)

```sh
python3 firmware/t832/t832_incident.py --root /config/.private/t832-diag authorize-reset
# Stop Zigbee2MQTT and ensure exclusive serial ownership of the P10 CDC endpoint.
# DTR/RTS deassert; wait 100 ms; RTS assert 150 ms; deassert; wait 1.5 s.
# Keep DTR deasserted (normal boot, no BSL). No erase/flash/restore.
python3 firmware/t832/t832_incident.py --root /config/.private/t832-diag mark-recovering
```

`authorize-reset` succeeds once: latch `captured` → `reset_authorized` with `reset_used:true`. A second call fails `automatic-reset-already-consumed`. Failed-recovery latch states also refuse new resets. Log the reset action, subsequent boot/startup records, and existing post-recovery ZDO verification. Do not add periodic ZDO workload. SYS responsiveness alone is not recovery.

## 4. Verification and latch close

Report recovery with observed traffic state:

```sh
python3 firmware/t832/t832_incident.py --root /config/.private/t832-diag \
  recovery-result --success true|false --normal-traffic true|false
```

`success=false` or `normal_traffic=false` moves the latch to `failed` and prohibits automatic retry. Success moves to `stabilizing` with `stable_after_utc` = now + 10 minutes and requires `normal_traffic_observed:true`. Close only after 10 minutes of stable bridge plus observed normal traffic with bridge up:

```sh
python3 firmware/t832/t832_incident.py --root /config/.private/t832-diag \
  close-if-stable --bridge-up true --normal-traffic true
```

Early close fails `stability-window-not-complete`. Partial SYS-only recovery and failed ZDO verification remain `failed`, never `closed`. `manual-clear --reason` is operator-only and audited in `host-events.log`.

## 5. HA automation template wiring

`deploy/t832_capture_barrier.yaml` is a candidate automation skeleton: trigger on the bridge-online loss condition, action order strictly `capture` → `authorize-reset` → stop Z2M → RTS pulse (existing validated R2 primitive) → `mark-recovering` → verify → `recovery-result` → delayed `close-if-stable`. The automation must run `mode: single` per-step with the persistent latch as the idempotency guard, not as its replacement. Reviewers must confirm the capture step cannot be skipped and that control-line actions are unreachable unless `capture` returned `ok:true`.

## 6. First planned live window

72 hours HA/Z2M continuous or until reproduction, then separate shutdown/reconnect tests if clean. Existing connections mean terminal RAM/fault context may be lost on hard reset; if the first reproduction yields only unexplained silence, recommend independent bench/debug/bridge observation instead of tuning buffers/routes.
