# Coordinator Registry

This file is the canonical repository-level map of coordinator hardware, radio silicon, host stack and experiment naming.

## Coordinator IDs

### `mr4u-p10`

- Hardware: SMLIGHT SLZB-MR4U.
- Zigbee radio: TI CC2674P10.
- Host stack: Z-Stack / ZNP.
- Current role: primary production coordinator and active reliability investigation target.
- Current work:
  - 2024 SMLIGHT P10 baseline / rollback test;
  - restored-network startup recovery;
  - SRSP/ZNP hang investigation;
  - planned TI reference ZNP control and diagnostic builds.
- Stable existing namespace:
  - `deploy/p10_*.py`
  - `tests/test_p10_*.py`
  - `docs/P10_*.md`
  - `skills/p10-zstack-restore-recovery/`
- Active planning branch:
  - `plan/mr4u-p10-ti-znp-control`

Important: `P10` identifies the CC2674P10 radio family, not the MR4U product by itself. Where another CC2674P10 board is possible, use the full coordinator ID.

### `sonoff-mg24`

- Hardware: SONOFF Dongle Max / Dongle-M.
- Zigbee radio: Silicon Labs EFR32MG24.
- Host stack: Ember / EZSP.
- Current role: previous production coordinator, rollback/reference platform, historical firmware research.
- Historical experiment generations:
  - P009
  - P013
  - P015
  - R60-related feasibility/baseline work
- Representative branches:
  - `p009-debug-capture-20260909`
  - `p009-hardening`
  - `p009-mg24-broadcast-headroom`
  - `p009-staging`
  - `assistant/p009b-build-recovery-20260930`
  - `assistant/p013-concentrator-ab-20260916`
  - `assistant/p013-route-health-20260912`
  - `assistant/p015-bidirectional-rf-shaping-20260917`
  - `assistant/mg24-emergency-fallback-20260930`

P009/P013/P015 are firmware experiment labels. They are not coordinator hardware names and must not be used to refer to MR4U/P10 work.

### `slzb-06p7`

- Hardware: SMLIGHT SLZB-06P7.
- Stack family: TI Z-Stack.
- Current role: historical predecessor / recovery reference.
- Repository status: no normalized current implementation namespace yet.

Do not silently reuse old 06P7 assumptions for MR4U/P10. Treat it as a separate coordinator even when both use TI Z-Stack.

### `mr4u-mg26`

- Hardware: the MR4U secondary EFR32MG26 radio.
- Current role in this installation: separate from the P10 Zigbee coordinator work; primarily reserved for Thread/secondary-radio use and experiments.
- It must not be selected accidentally by P10/ZNP tooling.

Do not identify MR4U radios by only "Radio 1" or "Radio 2". Use chip + protocol.

## Experiment ID rules

The repository contains three kinds of identifiers that must not be mixed:

| Identifier type | Examples | Meaning |
|---|---|---|
| Coordinator ID | `mr4u-p10`, `sonoff-mg24` | Physical coordinator + radio family |
| Firmware experiment ID | P009, P013, P015 | A specific experimental firmware/config generation |
| Vendor/build revision | 20240705, 20260310 | A firmware build/revision identifier |

When writing a new issue, branch, report or artifact, include the coordinator ID first.

Preferred examples:

```
mr4u-p10 / SMLIGHT-2024
mr4u-p10 / TI830-PROD-R0
sonoff-mg24 / P009
sonoff-mg24 / P015
```

Avoid:

```
P10 issue
P009 coordinator
Radio 1 problem
new dongle
```

when the specific hardware matters.

## Branch naming going forward

Preferred:

```
<type>/<coordinator-id>-<topic>
```

Examples:

```
plan/mr4u-p10-ti-znp-control
exp/mr4u-p10-ti830-prod-r0
fix/mr4u-p10-znp-resource-leak
exp/sonoff-mg24-p015-rf-shaping
docs/slzb-06p7-recovery-notes
```

Existing historical branches keep their original names for traceability.

## Shared invariants

Regardless of coordinator:

1. A production network has one active coordinator identity at a time.
2. Destructive firmware work requires a fresh recovery point.
3. Network identity/security preservation and firmware flashing are separate gates.
4. Coordinator firmware version is not proof of compiled table capacity.
5. Device database state is not proof of live RF reachability.
6. A route failure on one device is not equivalent to coordinator-wide ZNP failure.
7. Do not re-pair devices as a substitute for establishing coordinator correctness.
