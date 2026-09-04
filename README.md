# SONOFF Dongle Max / Dongle-M firmware tooling

Dedicated firmware, build, deployment, rollback and acceptance tooling for the SONOFF Dongle-M / Dongle Max based on Silicon Labs EFR32MG24.

Current work: **P009**, an EmberZNet 9.1.1 / EZSP 19 NCP build that preserves the accepted large-network profile while increasing broadcast-table headroom from 30 to 64 entries and the key table from 1 to 12.

Active issue: https://github.com/analienx/Sonoff-Dongle-Max/issues/1

Historical investigation only: https://github.com/analienx/home-assistant-stack/issues/47

## Repository layout

- `firmware/` — pinned MG24 source patch, resource contract and strict P009/stock artifact verifier.
- `deploy/` — resumable deployment state machine, safe remote transport and bounded acceptance probes.
- `runtime/` — optional pinned zigbee-herdsman 10.9.1 policy overlay; prepared but not deployed by default.
- `tests/` — pure regression tests for transport, identity, policy readbacks and session gates.
- `docs/EXECUTOR-DEPLOY.md` — mechanical deployment procedure.
- `.github/workflows/build-p009.yml` — controlled P009 + same-toolchain stock rollback build.

Development is staged on `p009-staging`. The build workflow is deliberately triggered only from `p009-mg24-broadcast-headroom`, which is advanced after staging review so intermediate file writes do not create noisy firmware builds.

## Safety invariants

- Never clear NVM or factory-reset the coordinator.
- Preserve coordinator IEEE, PAN ID, extended PAN ID, channel and network key.
- No device re-pairing.
- Exactly one Zigbee2MQTT owner of the coordinator.
- Build P009 and the rollback stock image from the same pinned builder/toolchain invocation.
- Verify the complete artifact checksum manifest before ARM.
- Hash the network key on the HA host; never copy the plaintext key into deployment evidence.
- ARM creates and hashes a stopped-state Z2M backup and leaves Z2M stopped for the manual WebUI flash.
- A separate `FLASH_CONFIRMED` phase requires the exact ARM-verified P009 GBL SHA256 before post-flash testing can start.
- All live post-ARM commands are locked to the exact host, add-on, Z2M path and remote transport stored in the session.
- Identity, acceptance or finalization failure marks the session `STOPPED`; safety failures stop Z2M.
- Run only the bounded acceptance gate; no soak or parameter matrix.

## Deployment phases

```text
ARMING -> ARMED -> FLASH_CONFIRMED -> IDENTITY_VERIFIED -> AUTOMATED_ACCEPTANCE_PASSED -> ACCEPTED
                \-------------------------------> STOPPED on a failed/interrupted safety gate
```

The CLI does **not** flash firmware. The only firmware mutation remains one manually gated upload of the exact ARM-verified P009 GBL through the already-proven SONOFF WebUI. Because P009 intentionally retains the 9.1.1 version string, `FLASH_CONFIRMED` is an explicit human acknowledgment of the exact uploaded GBL hash; it is not presented as a device-side binary attestation.

See `docs/EXECUTOR-DEPLOY.md` before deployment.
