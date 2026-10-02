# mr4u-p10 — SMLIGHT SLZB-MR4U / CC2674P10

## Identity

- Product: SMLIGHT SLZB-MR4U
- Zigbee radio: TI CC2674P10
- Stack/protocol: Z-Stack / ZNP
- Repository coordinator ID: `mr4u-p10`

This is the current primary Zigbee coordinator and the active reliability/recovery target.

## Current work

- SMLIGHT 2024 P10 baseline / rollback testing.
- Existing-network restore and startup recovery.
- Coordinator-wide SRSP/ZNP hang investigation.
- TI reference CC2674P10 ZNP control experiment planning.

Planning branch:

`plan/cc2674p10-ti-znp-control`

## Existing stable namespaces

The following older paths are intentionally retained because scripts/tests/docs already depend on them:

- `deploy/p10_*.py`
- `tests/test_p10_*.py`
- `docs/P10_*.md`
- `skills/p10-zstack-restore-recovery/`

Here, `p10` means the CC2674P10/Z-Stack target family. It does **not** mean all repository content belongs to this coordinator.

## Important MR4U distinction

The MR4U is dual-radio hardware. Do not use "Radio 1" or "Radio 2" as durable identity. Select the Zigbee radio by:

- chip: CC2674P10;
- protocol: ZNP/Z-Stack;
- verified firmware;
- verified USB endpoint.

The EFR32MG26 radio is a separate role and must not be selected by P10 tooling.

## Recovery-specific rule

For the validated failure where a coordinator backup restore succeeds but the P10 hangs at the final `ZDO_STARTUP_FROM_APP` transition, use:

[`skills/p10-zstack-restore-recovery/SKILL.md`](../../skills/p10-zstack-restore-recovery/SKILL.md)

The reviewed recovery resumes the already restored network; it must not silently reform it.
