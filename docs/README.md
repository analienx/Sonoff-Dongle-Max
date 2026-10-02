# Documentation Index

Repository-level documentation is organized by **coordinator scope**, even where older filenames are retained for compatibility.

## Shared

- [Coordinator Registry](COORDINATOR_REGISTRY.md) — canonical hardware/stack/naming map.
- Root [README](../README.md) — repository purpose, safety invariants and current focus.

## mr4u-p10 — SMLIGHT MR4U / CC2674P10 / Z-Stack

Migration / restore / cutover:

- [P10 USB cutover quickstart](P10_USB_CUTOVER_QUICKSTART.md)
- [P10 Python migration workflow](P10_PYTHON_MIGRATION_WORKFLOW.md)
- [P10 upstream cutover runbook](P10_UPSTREAM_CUTOVER_RUNBOOK.md)
- [P10 cutover preparation](P10_CUTOVER_PREPARATION.md)
- [P10 migration backup](P10_MIGRATION_BACKUP.md)

Preflight / firmware evidence:

- [P10 preflight](P10_PREFLIGHT.md)
- [P10 firmware candidate manifest](p10_firmware_candidates.json)

Recovery specialization:

- [P10 Z-Stack restore recovery skill](../skills/p10-zstack-restore-recovery/SKILL.md)

Current TI reference-ZNP planning is maintained on the canonical planning branch:

`plan/mr4u-p10-ti-znp-control`

## sonoff-mg24 — SONOFF Dongle Max / EFR32MG24 / Ember

- [Historical Issue #7 architecture review](ISSUE-7-ARCHITECTURE-REVIEW.md)

P009/P013/P015 implementation history primarily lives on historical branches rather than current main.

## slzb-06p7 — historical SMLIGHT Z-Stack predecessor

No normalized active implementation docs are currently on main.

See [`coordinators/slzb-06p7/README.md`](../coordinators/slzb-06p7/README.md) for scope and future naming guidance.

## Compatibility note

The existing `P10_*` documentation names and `p10_*` Python/test paths are intentionally retained to avoid breaking working tooling and cross-references.

New work should prefer explicit coordinator IDs in branch names and new top-level artifact names.
