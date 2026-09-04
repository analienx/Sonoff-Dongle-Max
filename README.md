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
