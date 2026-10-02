# sonoff-mg24 — SONOFF Dongle Max / Dongle-M / EFR32MG24

## Identity

- Product family: SONOFF Dongle Max / Dongle-M
- Zigbee radio: Silicon Labs EFR32MG24
- Stack/protocol: Ember / EZSP
- Repository coordinator ID: `sonoff-mg24`

This was the previous production coordinator and remains an important rollback/reference platform.

## Historical firmware work

The following labels belong to this coordinator family:

- P009
- P013
- P015
- R60 feasibility/baseline work

They are **firmware experiment IDs**, not hardware models.

Representative historical branches include:

- `p009-debug-capture-20260909`
- `p009-hardening`
- `p009-mg24-broadcast-headroom`
- `p009-staging`
- `assistant/p009b-build-recovery-20260930`
- `assistant/p013-concentrator-ab-20260916`
- `assistant/p013-route-health-20260912`
- `assistant/p015-bidirectional-rf-shaping-20260917`
- `assistant/mg24-emergency-fallback-20260930`

## Historical architecture review

The retained P009 architecture review is:

[`docs/ISSUE-7-ARCHITECTURE-REVIEW.md`](../../docs/ISSUE-7-ARCHITECTURE-REVIEW.md)

Do not apply P009/P013/P015 assumptions to the MR4U/P10 simply because both have been used as the same household coordinator at different times.

## Role today

- rollback/reference hardware;
- source of historical large-network Ember observations;
- comparison point for Ember-vs-Z-Stack behavior;
- not the default target of current `p10_*` tooling.
