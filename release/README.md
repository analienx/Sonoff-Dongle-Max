# SONOFF Dongle-Max release bundle

This directory defines the release contract. The bundle is intentionally **not a single firmware image**: it contains one production candidate plus rollback, diagnostics and explicitly identified experimental/reference components.

## Authoritative production candidate

**P009** is the only default production flash candidate:

```text
P009-RX512-BTT64-KEY12-MCAST26
RX buffer        128 -> 512
broadcast table   30 -> 64
key table           1 -> 12
multicast table    26 -> 26 (unchanged)
```

P009 must retain the matched stock rollback image from the same source/toolchain run. A release bundle is invalid if its P009 manifest describes multicast32 or a linked `.bss` delta other than +704 B.

## Other required bundle components

- **Stock rollback** — matched firmware rollback; never an implicit network reset.
- **P010** — diagnostic-only host overlay for non-blocking BUSY-pressure counter snapshots. Disabled by default.
- **P011** — identity-only XNCP firmware derived from P009. It provides deterministic operational self-identification; it is not cryptographic remote attestation. Disabled by default.
- **P012** — watchdog/reset-cause research and validation contract. No watchdog is silently enabled in P009; hardware validation is still required.
- **P013** — P009 plus multicast table 26→32, explicitly separated so multicast headroom can be evaluated without changing P009 semantics. Disabled by default.
- **Host bulk lane** — bounded host-side pacing/coalescing reference implementation. It is not a global Zigbee delay and is not automatically installed.
- **Optional P009 runtime policy/config-audit overlays** — separately packaged; not part of the first stock-host P009 deployment.

The machine-readable status is in `release/COMPONENTS.json`.

## One-SHA rule

Every final aggregate bundle must be created from **one exact repository commit**. Firmware variants, host overlays, tests, evidence and release metadata all bind to that same source SHA. Historical green artifacts from older commits may inform engineering decisions, but they are not mixed into a new final release.

## Evidence layers

The release distinguishes:

1. source/profile intent;
2. generated build configuration;
3. linked ELF evidence;
4. artifact hashes/sizes;
5. resolved toolchain/base-image provenance for the CI run;
6. later owner-bound live Zigbee2MQTT/network identity evidence.

No single layer is described as proving another. In particular, an uploaded GBL hash is not device-side attestation, and a source SLCP is not proof of linked object sizes.

## Release gate

A bundle may be handed to the local deployment operator only when:

- the release branch is not behind `main`;
- authoritative release CI passes from one exact SHA;
- P009 and rollback linked assertions pass;
- P009 clean-twin reproducibility checks pass;
- P011 and P013 linked variant checks pass;
- P010/runtime/config-audit/host-policy artifacts build and test successfully;
- P012 status explicitly remains hardware-blocked unless its local test has actually happened;
- aggregate SHA256 inventory verifies;
- supervisor inspects the resulting manifests/artifacts;
- issue #6 is replaced with exact current run/artifact/hash instructions.

Passing CI does **not** authorize a flash. The first local action remains preflight + ARM + STOP before the SONOFF WebUI flash gate.
