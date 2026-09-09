# SONOFF Dongle Max / Dongle-M — MG24 large-network firmware

Custom, evidence-driven firmware and deployment tooling for the **SONOFF Dongle-M / Dongle Max** (`EFR32MG24A420F1536IM48`) used with Zigbee2MQTT on a large production Zigbee network.

The project has one narrow production objective: address repeatable coordinator-originated group/broadcast `SLStatus.BUSY` without destabilizing the known-good radio, routing, network identity or normal direct-bound control path. Experimental improvements are kept as separately identified variants rather than silently folded into the production baseline.

- Engineering/root-cause history: https://github.com/analienx/Sonoff-Dongle-Max/issues/1
- Independent architecture review: https://github.com/analienx/Sonoff-Dongle-Max/issues/7
- Deployment operator gate: https://github.com/analienx/Sonoff-Dongle-Max/issues/6
- Historical production investigation: https://github.com/analienx/home-assistant-stack/issues/47

## Production candidate: frozen P009

Pinned base:

```text
Simplicity SDK 2026.6.1
EmberZNet 9.1.1
EZSP 19
EFR32MG24A420F1536IM48
EUSART1
115200 baud
no hardware flow control
builder Nerivec/silabs-firmware-builder@858c34b0eb6f53a2e0c89455ea489ceaa62d58db
```

P009 changes **exactly three** compile-time values versus the matched stock rollback:

| Resource | Stock | P009 | Purpose |
|---|---:|---:|---|
| EUSART VCOM RX buffer | 128 | **512** | Short host→NCP burst tolerance. |
| Zigbee broadcast table | 30 | **64** | Primary broadcast-admission headroom hypothesis. |
| Zigbee key table | 1 | **12** | Additional APS/link-key storage without changing network security material. |
| Zigbee multicast table | **26** | **26** | Intentionally unchanged in P009. |

Everything else in the retained MG24 profile stays unchanged, including route/source-route 254, address/APS 128, discovery16, neighbor26, binding32, compiled child capacity64, APS duplicate rejection64, HUGE packet-buffer heap and retry queue16.

The linked contract is intentionally exact:

| Quantity | Stock | P009 | Delta |
|---|---:|---:|---:|
| `.bss` proper | 22,284 B | 22,988 B | **+704 B** |
| memory-manager reservation | 229,896 B | 229,896 B | 0 B |

The 229,896-B region is a linker reservation, **not measured free Zigbee packet memory**.

See `firmware/RESOURCE-PROFILE.md` for the complete linked-symbol contract.

## Why P009 exists

Production evidence contains real group/broadcast-path `BUSY`, including operations such as `Kitchen Table Bulbs`, `Sockets Nonessential Shutdown` and `Lights All`. Coordinator-only permit controls were clean while network-wide Permit Join reproduced the same broad failure class.

Broadcast/NWK admission pressure is therefore the leading hypothesis, but the project does not pretend that every BUSY is proven to be a full broadcast table. Other credible pressure branches include packet-buffer exhaustion, retry congestion, PHY/MAC queue pressure, RF contention, route/concentrator background work and host/callback backlog.

That is why P009 increases only justified headroom and P010 exists as a separate diagnostic surface if BUSY remains.

## Explicit variants and bundle components

The final deliverable is a coherent **one-source-SHA release bundle**, not one ambiguous firmware image.

### P011 — identity-only XNCP

P011 starts from frozen P009 and preserves its Zigbee resource/transport values. It adds a small read-only XNCP identity command carrying compact source/profile identity.

The build hashes a canonical semantic profile rather than the textual SLCP file, and stores a trusted-side record containing the full source SHA and full SHA-256. The wire response uses compact prefixes.

P011 is **operational self-identification, not cryptographic remote attestation**. Stock Zigbee2MQTT must work normally if it ignores the extension. P011 is disabled by default.

Issue: https://github.com/analienx/Sonoff-Dongle-Max/issues/8

### P012 — watchdog/reset research

The pinned NCP project does not explicitly select a watchdog component, and P009/P011/P013 do not silently add one.

P012 is a required research/diagnostic bundle component whose production promotion remains blocked on a controlled spare-hardware test proving observable reset cause, single recovery without a reset loop and preserved network/NVM state.

See `docs/P012-WATCHDOG-RESET.md` and issue #9.

### P013 — multicast32 experiment

P013 is P009 plus exactly:

```text
SL_ZIGBEE_MULTICAST_TABLE_SIZE 26 -> 32
```

That costs 24 B linked `.bss` (`22,988 -> 23,012 B`). Separating it from P009 preserves a clean causal first test of the BUSY intervention while retaining a cheap future receive-membership headroom experiment. P013 is disabled by default.

### P010 — BUSY pressure observability

P010 is a host-side diagnostic overlay. When the original send returns BUSY, it schedules a single-flight, rate-limited **read-only** NCP counter snapshot and propagates the original BUSY immediately. It does not retry the send, clear counters or change configuration.

Signals include broadcast-table-full, packet-buffer allocation failures, PHY→MAC queue saturation, NWK retry overflow, CCA and ASH errors.

### Host bulk lane

`runtime/bulk_lane.py` is an offline/reference implementation for specific bulk automation paths. It is deliberately **not** a global Zigbee send delay. Guardrails include no hidden BUSY retries, no direct-binding latency changes and no unsafe coalescing of toggles/steps/safety OFF operations.

Issue: https://github.com/analienx/Sonoff-Dongle-Max/issues/10

The authoritative machine-readable component status is `release/COMPONENTS.json`.

## Compile-time capacity vs runtime policy

The NCP links capacity for 64 direct end-device children, but pinned stock zigbee-herdsman 10.9.1 normally asks for 32 unless `stack_config.json` overrides it. Network size and direct-child count are different quantities.

Stock herdsman does not normally lower P009 BTT64 or KEY12. `NEW_BROADCAST_ENTRY_THRESHOLD` remains a separate runtime admission policy. The prepared threshold48 runtime overlay is therefore **not part of the first firmware-only deployment**.

## Transport contract

P009/P011/P013 keep the SONOFF board path:

```text
EUSART1
115200 baud
no RTS/CTS
RX buffer 512 B
```

RX512 is short-burst storage only. At 115200 8N1 it is roughly 44 ms of line-rate capacity versus ~11 ms for RX128; it does not increase sustained throughput.

Do not copy a ZBT-2 460800/CTS-RTS profile onto Dongle-M without end-to-end proof through the SONOFF ESP bridge, physical pins and firmware.

## Evidence model

The project deliberately separates:

1. source/profile intent;
2. generated component/configuration evidence;
3. linked ELF section/symbol assertions;
4. GBL/HEX/OUT hashes and sizes;
5. resolved CI toolchain/base-image provenance;
6. owner-bound live Zigbee2MQTT/network evidence after startup.

A source SLCP is not “effective linked configuration.” An uploaded GBL hash is not device-side attestation. A bounded acceptance pass is not proof of long-term statistical reliability.

The upstream builder is Git-pinned, but its Dockerfile references mutable parent tags and live package repositories. Authoritative release CI therefore records the **resolved parent image digests and final builder image ID for the actual release run** instead of overstating eternal rebuild reproducibility.

## Authoritative release CI

`.github/workflows/release-final.yml` is the release gate. From one exact repository SHA it:

- runs the entire offline regression suite;
- builds matched stock rollback;
- builds frozen P009 and a clean reproducibility twin;
- builds P011 and verifies its linked XNCP identity surface;
- builds P013 and verifies the only resource change is multicast26→32 / +24 B `.bss`;
- archives generated build metadata and linked `readelf` evidence;
- records resolved Docker/toolchain provenance;
- builds P009 runtime, P010 observability and read-only config-audit host overlays against pinned zigbee-herdsman;
- packages the host bulk-lane and P012 validation contract;
- aggregates everything into one SHA-bound release candidate with recursive SHA256 inventory.

The release manifest always states `flash_authorized: false`. CI success is a software/release gate, not permission to modify the live coordinator.

## Controlled deployment

`deploy/p009_tool.py` owns the deployment state machine. It does **not** flash firmware itself.

```text
ARMING
  -> ARMED
  -> FLASH_CONFIRMED
  -> IDENTITY_VERIFIED
  -> AUTOMATED_ACCEPTANCE_PASSED
  -> ACCEPTED

any failed/incomplete safety gate -> STOPPED
```

The hardened live proof binds:

- exact release source SHA and P009 manifest;
- exact P009 + matched rollback GBL hash/size;
- one exact Zigbee2MQTT HA add-on container;
- current Docker container ID/start epoch;
- a Zigbee2MQTT 2.14 **empty** `health_check` request with a non-retained healthy response observed after publication;
- secret-safe `bridge/info` network identity;
- network-key SHA-256 computed inside the owner container rather than exported in plaintext;
- current backup metadata and stopped-state hashes;
- current-session log windows;
- same owner/session requirements through acceptance.

Post-flash P009 still has generic EmberZNet/EZSP identity; exact P009 binary selection remains tied to the hash-verified WebUI artifact. P011 exists precisely to improve future on-device custom-build self-identification.

## Bounded acceptance

After the post-flash identity gate:

1. exactly **16 completed unique** read-only canary transactions, at least 15 successful;
2. up to five serial 10-second Permit Join All trials, with no new opening after the first hard failure;
3. correlated/fresh final close evidence and `permit_join=false`;
4. complete current log window scan for BUSY/pressure/reset/disconnect/network-down signatures;
5. exactly two structured real-group checks with command and physical result;
6. final current-session identity check.

Reconnects cannot replay the stimulus sequence, malformed correlated responses fail the run, incomplete 15/15 cannot masquerade as 15/16, and failure evidence is persisted before STOP.

If this bounded screen passes, stop testing. Do not turn it into a stress/parameter matrix.

## Safety invariants

The production path does not perform:

- NVM clear or factory reset;
- PAN/extPAN/channel/network-key change;
- re-pairing;
- RF-power experimentation;
- neighbor table above hard max26;
- route/source-route enlargement beyond254;
- blanket BUSY retries;
- retry-queue enlargement;
- threshold48 during first stock-host P009 test;
- automatic P010/P011/P012/P013 activation;
- automatic host bulk-lane installation.

## Repository layout

- `firmware/` — P009/P011/P013 patches and linked-image verifiers.
- `deploy/` — owner-bound deployment state machine and bounded acceptance.
- `runtime/` — optional host runtime/observability/config-audit/bulk-lane components.
- `tests/` — regression and release-contract tests.
- `docs/` — architecture, tuning, watchdog/reset and executor runbooks.
- `release/` — machine-readable bundle semantics/status.
- `.github/workflows/release-final.yml` — authoritative one-SHA release CI.

**Deployment issue #6 remains paused until the current release workflow is green and the resulting exact aggregate artifact has been inspected and pinned.**
