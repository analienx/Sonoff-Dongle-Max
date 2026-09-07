# SONOFF Dongle Max / Dongle-M — MG24 P009 firmware

Experimental large-network firmware and controlled deployment tooling for the **SONOFF Dongle-M / Dongle Max** based on Silicon Labs **EFR32MG24A420F1536IM48**.

The objective is narrow: keep the known-good network/radio/routing behavior, add measured headroom where this production network has repeatedly returned `SLStatus.BUSY`, and make every deployment claim traceable to a specific binary and a current Zigbee2MQTT owner session.

Engineering issue: https://github.com/analienx/Sonoff-Dongle-Max/issues/1

Architecture review: https://github.com/analienx/Sonoff-Dongle-Max/issues/7

Historical production investigation: https://github.com/analienx/home-assistant-stack/issues/47

## P009 firmware profile

Pinned base:

```text
Simplicity SDK 2026.6.1
EmberZNet 9.1.1
EZSP 19
EFR32MG24A420F1536IM48
EUSART1
115200 baud
no hardware flow control
```

P009 changes **exactly three** compile-time values versus the matched stock rollback image:

| Resource | Stock | P009 | Purpose |
|---|---:|---:|---|
| EUSART VCOM RX buffer | 128 | **512** | Short host-to-NCP burst tolerance. |
| Zigbee broadcast table | 30 | **64** | Primary broadcast-admission headroom hypothesis. |
| Zigbee key table | 1 | **12** | Reasonable APS/link-key storage matching current MG24 production precedent. |

Everything else in the retained large-network profile stays unchanged:

```text
route table                     254
source-route table              254
address table                   128
APS unicast messages            128
discovery table                  16
multicast table                  26
neighbor table                   26  # Silicon Labs maximum
binding table                    32
compiled max end-device children 64
APS duplicate rejection          64
packet-buffer heap              HUGE
retry queue                      16
```

### Compile-time capacity is not always runtime policy

The linked NCP contains capacity for 64 direct end-device children, but pinned stock zigbee-herdsman 10.9.1 normally attempts to set the **runtime maximum direct children to 32** unless `stack_config.json` changes it. Network size and direct-child count are not the same thing.

Stock herdsman does **not** appear to rewrite P009's broadcast-table size 64 or key-table size 12 downward. The effective `NEW_BROADCAST_ENTRY_THRESHOLD` under the stock host is still treated as **unresolved** until it is read through a supported owner-side path. The prepared threshold-48 runtime overlay therefore must not be deployed merely because the binary has BTT64.

## What the linked binary actually costs

The approved pinned-toolchain ELF audit found:

| Quantity | Stock | P009 | Delta |
|---|---:|---:|---:|
| `.bss` proper | 22,284 B | 22,988 B | **+704 B** |
| memory-manager reservation | 229,896 B | 229,896 B | 0 B |
| GBL file | 268,896 B | 268,992 B | +96 B |

The +704 B static change is explained by:

```text
RX buffer                         +384 B
broadcast backing array           +272 B
incoming APS/key counter metadata  +44 B
alignment/layout                     +4 B
```

For this linked image the broadcast backing array is 240 B for 30 entries and 512 B for 64 entries: **8 B per linked entry**, not the older generic 6-B estimate.

The 229,896-B `.memory_manager_heap` reservation is **not a measurement of free Zigbee packet memory**. Runtime packet-pool acquisition, fragmentation, low-water marks and transient allocations require live evidence.

## Failure model

Production evidence contains real group/broadcast-path `BUSY`, not only Permit Join:

```text
Kitchen Table Bulbs             group 25
Sockets Nonessential Shutdown   group 31
Lights All                      group 8
```

Coordinator-only Permit Join controls were clean while network-wide Permit Join reproduced the same class of failure. This keeps broadcast/NWK admission pressure as the leading hypothesis.

It is not yet proven that every BUSY was literally caused by a full broadcast table. Other credible admission-pressure branches include:

- local broadcast-entry threshold;
- shared packet-buffer exhaustion;
- PHY-to-MAC queue pressure;
- NWK retry congestion;
- callback/host transport backlog;
- route/concentrator background work;
- RF contention prolonging resource occupancy.

P009 therefore increases a justified capacity but keeps counter-based diagnostics available if BUSY remains.

## Multicast/group capacity

`SL_ZIGBEE_MULTICAST_TABLE_SIZE=26` is not a transmit queue. It tracks coordinator memberships used for receiving group traffic. Pinned herdsman also consumes fixed memberships and dynamically registers application groups, so a network with ~21 groups can be materially closer to 26 slots than earlier documentation implied.

We do **not** increase this table in P009. Actual occupancy/registration evidence comes first; only then would a separate 26→32 candidate make sense.

## Transport

P009 keeps the SONOFF board contract:

```text
EUSART1
115200
no RTS/CTS
```

RX512 adds short-burst storage only. At 115200 8N1, nominal line rate is about 11,520 B/s: 128 B is ~11 ms of line-rate storage, while 512 B is ~44 ms. It does not raise sustained throughput or prove the ESP bridge cannot bottleneck.

Do not copy Nabu Casa ZBT-2's 460800/CTS-RTS settings onto the SONOFF board without end-to-end hardware proof.

## Evidence layers

This repository deliberately separates four different claims:

1. **Source profile** — what SLCP/manifest inputs requested.
2. **Linked binary evidence** — what key objects/sections actually exist in the `.out` ELF.
3. **Artifact integrity** — exact GBL/HEX/OUT hashes from one CI run.
4. **Running-session evidence** — what the current Zigbee2MQTT owner reports after startup.

A copied SLCP is not called “effective configuration”. A manually acknowledged GBL SHA is not called device-side firmware attestation.

The hardened build artifact contains source inputs, generated configuration, linker maps, `readelf` evidence, toolchain evidence, linked-object assertions and a schema-versioned build manifest.

## Controlled deployment

Deployment uses a persistent state machine:

```text
ARMING
  -> ARMED
  -> FLASH_CONFIRMED
  -> IDENTITY_VERIFIED
  -> AUTOMATED_ACCEPTANCE_PASSED
  -> ACCEPTED

Any failed/incomplete safety gate -> STOPPED
```

Important safeguards include:

- exact source commit + build-manifest binding;
- whole-bundle SHA256 verification;
- exact P009 and matched stock-rollback GBL hashes/sizes;
- exactly one expected HA Zigbee2MQTT add-on owner;
- current Docker container ID/start epoch;
- current-session startup logs rather than an old log tail;
- correlated Zigbee2MQTT health response;
- live network identity from current `bridge/info`;
- network-key SHA256 computed inside the current owner container, never copied as plaintext;
- stopped-state config/database/backup hashes and tar backup;
- fail-fast acceptance with partial failure evidence persisted before STOP;
- same-owner/start-epoch checks across acceptance and finalization.

Until a dedicated XNCP identity variant is implemented, post-flash evidence proves current generic EmberZNet 9.1.1/EZSP19 operation and unchanged network identity; the exact P009 binary remains tied to the human-selected, hash-verified artifact. Those are intentionally different claims.

## Bounded acceptance

After the post-flash identity gate:

1. exactly **16 completed unique** read-only transactions (2 × 8 targets), at least 15 successful;
2. up to five serial 10-second Permit Join All trials; in a clean path exactly five, but **stop opening new windows on the first hard failure**;
3. correlated final Permit Join close and a fresh `permit_join=false` observation;
4. complete acceptance log window scanned for BUSY/message-pressure/reset/disconnect/network-down signatures;
5. exactly two structured real-group checks with command result and human-verified physical result;
6. final current-session identity check.

This is a bounded operational screen, **not statistical proof of long-term reliability**. If it passes, stop testing. If it fails, preserve the first failure and diagnose from evidence rather than adding retries or a parameter matrix.

## Optional runtime work

### P009 policy overlay

Prepared separately and **not part of the first firmware-only test**. It sets/readbacks:

```text
BROADCAST_TABLE_SIZE               64
NEW_BROADCAST_ENTRY_THRESHOLD      48
RETRY_QUEUE_SIZE                   16
MTORR_FLOW_CONTROL                  1
SUPPORTED_NETWORKS                  1
SEND_MULTICASTS_TO_SLEEPY_ADDRESS  0
```

Because threshold 48 changes local-vs-relayed broadcast admission policy, the whole six-value overlay must not be deployed simply to “make firmware values stick”. First determine the stock effective baseline.

### P010 observability overlay

Diagnostic-only. On a residual group/broadcast BUSY it schedules one **non-blocking, single-flight, 5-second-coalesced** read-only counter snapshot behind the owner queue, while propagating the original BUSY immediately.

It watches pressure counters such as:

```text
BROADCAST_TABLE_FULL
ALLOCATE_PACKET_BUFFER_FAILURE
PHY_TO_MAC_QUEUE_LIMIT_REACHED
TYPE_NWK_RETRY_OVERFLOW
PHY_CCA_FAIL_COUNT
ASH_OVERFLOW/FRAMING/OVERRUN
```

It does not clear counters, retry a send or change configuration.

## Next architecture: identity-only XNCP

The architecture review recommends a small follow-up XNCP extension that reports a deterministic project/board/schema/build/profile identity on request while remaining ignorable by stock Zigbee2MQTT. This should be a **new identifiable firmware variant**, not silently added to the already-reviewed P009 binary.

The first XNCP version should remain identity-only; health fields should be added only where supported APIs and bounded response semantics are established.

## What P009 deliberately does not do

- no NVM clear or factory reset;
- no network-key/PAN/extPAN/channel change;
- no re-pairing requirement;
- no RF-power experiment;
- no route/source-route growth beyond 254;
- no neighbor table above the hard maximum 26;
- no blanket BUSY retries;
- no retry-queue enlargement;
- no BTT254 “max everything” profile;
- no ZBT-2 transport copy;
- no deployment of P009 policy or P010 diagnostics during the first stock-host acceptance.

## Repository layout

- `firmware/` — pinned source patch, resource contract, linked-image verifier.
- `deploy/` — guarded state machine and bounded acceptance tooling.
- `runtime/` — separate P009 policy and P010 diagnostic overlays.
- `tests/` — regression tests for profiles, linked evidence and deployment gates.
- `docs/` — research, special architecture review and executor runbook.
- `.github/workflows/build-p009.yml` — P009 + matched rollback build and evidence bundle.

Current hardening work is performed on `p009-hardening`. Production flashing remains paused until the hardening build is fully green and its new artifact is reviewed.
