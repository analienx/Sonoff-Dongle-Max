# slzb-06p7 — SMLIGHT SLZB-06P7

## Identity

- Product: SMLIGHT SLZB-06P7
- Stack family: TI Z-Stack
- Repository coordinator ID: `slzb-06p7`

This is a historical predecessor and recovery/reference coordinator.

## Repository status

The repo does not yet have a normalized active implementation namespace for this coordinator. Historical assumptions, backups or procedures for the 06P7 must not be silently treated as MR4U/CC2674P10 facts.

Even though both `slzb-06p7` and `mr4u-p10` are TI Z-Stack coordinators, keep separate:

- radio generation;
- firmware build lineage;
- table sizing;
- NVS layout;
- CCFG/boot behavior;
- board-level RF/UART wiring;
- migration/recovery evidence.

If new 06P7-specific work is added, use the `slzb-06p7` coordinator ID explicitly in branch and artifact names.
