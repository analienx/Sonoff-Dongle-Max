# P10 fresh-network rebuild/reconciliation

## Purpose

`deploy/p10_rebuild_reconciler.py` reconstructs Zigbee2MQTT application state
after devices are physically reset and commissioned onto a **fresh**
MR4U CC2674P10 / Z-Stack network.

Tool version: **0.1.0**

It intentionally does **not** copy network keys, PAN/extPAN, Trust Center keys,
frame counters or coordinator NVRAM into the rebuild manifest.

Captured/restorable application state:

- device identity keyed by IEEE address;
- Zigbee2MQTT friendly names and device options;
- BSEED/custom `reporting:` options from configuration;
- exact numeric group IDs, options and endpoint memberships;
- non-coordinator device/group bindings;
- cached ZCL reporting as an opt-in reference;
- joined/interviewed progress during staged commissioning.

## Safety model

- `snapshot`, `pilot`, `plan` and `status` are local/read-only operations.
- `apply` is dry-run unless `--execute` plus the exact approval phrase
  `APPLY_P10_REBUILD_RECONCILIATION` are supplied.
- Converter-managed coordinator bindings/reporting are not copied blindly.
  A normal Zigbee2MQTT `device/configure` request is used after rejoin.
- User/direct bindings are replayed only when the target exists.
- Unsupported custom binding clusters are deferred for review rather than sent
  as raw numeric cluster IDs.
- Raw reporting replay is opt-in; converter configuration is preferred first.
- Keep Home Assistant discovery disabled while names are being reconstructed,
  then re-enable it once device identities are stable.

The current MQTT operations were checked against the Zigbee2MQTT documentation
updated 2026-08-22: group creation/options/membership, device rename/options,
configure, bind and reporting/configure.

## Current private recovery artifacts

Verified current P10 cold rollback point:

`C:\Workspace\.analienx\sonoff-private\issues\p10\bundles\cold-p10-pre-fresh-pilot-20260926T065336Z.zip`

SHA-256:

`387e68587df8e2872f73007513c2b8451a4be3735183d98a85510abc96e26a68`

Full application reconstruction manifest:

`C:\Workspace\.analienx\sonoff-private\issues\p10\rebuild-manifest-v0.1.0-20260926.json`

It contains **105 non-coordinator devices and 21 groups** and no Zigbee network
secrets.

Corrected pilot manifest:

`C:\Workspace\.analienx\sonoff-private\issues\p10\pilot-manifest-v0.1.0-workroom-window-left-20260926.json`

## Commands

Create a full manifest:

```powershell
python deploy\p10_rebuild_reconciler.py snapshot `
  --bundle <verified-cold-bundle.zip> `
  --out <private-rebuild-manifest.json>
```

Create a pilot subset:

```powershell
python deploy\p10_rebuild_reconciler.py pilot `
  --manifest <private-rebuild-manifest.json> `
  --device WRSocketWindowLeft `
  --device KitchenSocketRight `
  --device 0x348d13fffefffa53 `
  --device 0x08fd52fffed5864e `
  --device HallBreakerFA5 `
  --alias 0x348d13fffefffa53=RODRET_Pilot_A `
  --alias 0x08fd52fffed5864e=RODRET_Pilot_B `
  --out <private-pilot-manifest.json>
```

After some devices have joined the fresh network, capture a bundle of the fresh
state and build a replay plan:

```powershell
python deploy\p10_rebuild_reconciler.py plan `
  --manifest <private-pilot-manifest.json> `
  --current-bundle <fresh-network-bundle.zip> `
  --out <private-plan.json>
```

Inspect progress:

```powershell
python deploy\p10_rebuild_reconciler.py status `
  --manifest <private-pilot-manifest.json> `
  --current-bundle <fresh-network-bundle.zip>
```

Review the JSON plan before applying. Default apply is dry-run:

```powershell
python deploy\p10_rebuild_reconciler.py apply --plan <private-plan.json>
```

Live replay can be limited to one IEEE at a time:

```powershell
python deploy\p10_rebuild_reconciler.py apply `
  --plan <private-plan.json> `
  --scope 0xa4c138075cd16ed4 `
  --execute `
  --approval APPLY_P10_REBUILD_RECONCILIATION
```

## Corrected fresh-P10 pilot set

| Device | IEEE | Role | Notes |
|---|---|---|---|
| `WRSocketWindowLeft` | `0xa4c138ef578c9f75` | Router | BSEED TS011F socket; Workroom naming set; member of group 31 |
| `KitchenSocketRight` | `0xa4c138075cd16ed4` | Router | BSEED TS011F-BS-PM |
| `HallBreakerFA5` | `0x94b216fffe9260f5` | Router | Tongou-style TS011F; description says dryer, phase A; reset only with dryer confirmed off |
| `RODRET_Pilot_A` | `0x348d13fffefffa53` | EndDevice | Previous production interview failed |
| `RODRET_Pilot_B` | `0x08fd52fffed5864e` | EndDevice | Previous production interview succeeded and emitted an action |

The earlier candidate `LivingRoomSocketTableLeft` was removed from the pilot:
it is the wrong room. The HA inventory has no explicit area assigned to
`WRSocketWindowLeft`, so its exact physical "table-left" position still needs
visual confirmation before factory reset.

The corrected pilot requires only one existing group:

- group **31** — `Sockets Nonessential Shutdown`

No pilot device has a custom non-coordinator binding in the current cold
snapshot. The binding-replay path is nevertheless covered by synthetic tests
because it is required for the later whole-network rebuild.

## Pilot acceptance gate

Do not expand the rebuild simply because devices appear in Zigbee2MQTT.

Require:

1. all three pilot routers join and interview successfully;
2. coordinator check shows all three correctly registered;
3. both RODRETs join/configure and publish repeated real button actions;
4. `WRSocketWindowLeft` is restored to exact group ID 31;
5. its BSEED custom reporting option and device options are restored;
6. repeated unicast control/read tests succeed;
7. at least one RODRET is commissioned through a pilot router;
8. arrange the routers so at least one useful test path exercises routing rather
   than every device sitting directly beside the coordinator;
9. no pilot router appears in `missing_routers`;
10. reconciler status shows all five expected IEEE addresses recovered.

If this gate passes, keep the **same fresh network** and continue the house-wide
rebuild; do not form another network.

If it fails, stop and restore the verified current P10 cold state. Any pilot
device that was factory-reset must then be paired back to the restored network.

## Full rebuild after a passing pilot

1. Pair mains-powered routers outward from the coordinator.
2. Re-run coordinator check and representative command tests in small batches.
3. Restore each joined IEEE's friendly name/options/group memberships.
4. Replay now-satisfiable custom bindings; leave missing-target dependencies
   deferred until their targets join.
5. Add battery/end devices only after nearby router coverage is established.
6. Re-enable HA discovery after names are stable and validate HA entities and
   automations.
7. Finish with groupcast, multi-hop and normal-use validation for at least
   24 hours.

## What cannot be automated safely

- physically factory-resetting/waking devices;
- deciding whether an attached socket/breaker load is safe to interrupt;
- proving physical room/location purely from Zigbee metadata;
- resolving unsupported manufacturer-specific binding clusters without review;
- guaranteeing Home Assistant entity continuity without post-rejoin validation.
