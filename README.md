# SONOFF Dongle Max / Dongle-M firmware tooling

Dedicated firmware, build, deployment, rollback and acceptance tooling for the SONOFF Dongle-M / Dongle Max based on Silicon Labs EFR32MG24.

The current production experiment is **P009**: an EmberZNet 9.1.1 / EZSP 19 NCP build that preserves the existing large-network profile while increasing broadcast-table headroom from 30 to 64 entries and the key table from 1 to 12.

## Safety invariants

- Never clear NVM or factory-reset the coordinator.
- Preserve coordinator IEEE, PAN ID, extended PAN ID, channel and network key.
- No device re-pairing.
- Exactly one Zigbee2MQTT owner of the coordinator.
- Build P009 and the rollback stock image from the same pinned toolchain.
- Flash only after the build artifact, hashes and stopped-state backup are verified.
- Run only the bounded acceptance gate; no soak or parameter matrix.

See `docs/EXECUTOR-DEPLOY.md` and the active GitHub issue before deploying.

## Canonical Home Assistant diagnostics and Zigbee device identification

For any live Home Assistant access, Zigbee2MQTT NWK/address mapping or route-error investigation, load the **single canonical** [Home Assistant read-only skill](https://github.com/analienx/config/blob/main/skills/home-assistant-readonly/SKILL.md) from `analienx/config` (main). It provides the existing SSH alias, a host-key-verified Paramiko fallback for Windows OpenSSH exit-255 failures, and the reusable `ha_readonly.py` live inventory helper. Keep implementation and credentials in the canonical location; do not copy the helper or SSH settings here. This does not authorize Zigbee firmware flashing, HA mutations or bypass of this repository's own safety/deployment rules.

## Separate migration toolkit: SONOFF Ember → SMLIGHT MR4U P10 (USB)

For the optional **existing-network USB coordinator replacement**, start at [the Python USB cutover quickstart](docs/P10_USB_CUTOVER_QUICKSTART.md), then read [the full staged workflow](docs/P10_PYTHON_MIGRATION_WORKFLOW.md). This is separate from P009 production firmware deployment. Its `p10_usb_handoff.py` stops Zigbee2MQTT, creates/verifies a full *narrow cold Zigbee2MQTT backup* and stages original config/rollback before authorizing a physical SONOFF disconnect; `p10_usb_cutover.py` identifies the MR4U CC2674P10 only **after** that disconnect. Neither tool flashes coordinators or modifies active Zigbee network identity. Ember→Z-Stack device recovery is not guaranteed; targeted re-pairing can be necessary, unlike the same-radio P009 firmware-upgrade rule above.
