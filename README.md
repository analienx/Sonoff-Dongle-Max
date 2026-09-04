# SONOFF Dongle Max / Dongle-M — P009 MG24 firmware

Experimental large-network firmware and controlled deployment tooling for the **SONOFF Dongle-M / Dongle Max** based on Silicon Labs **EFR32MG24**.

The current firmware profile, **P009**, is built from the same pinned EmberZNet 9.1.1 / EZSP 19 baseline used for the stock rollback image. It deliberately keeps the proven radio, serial and routing configuration while increasing two constrained NCP resource tables that matter on larger or broadcast-heavy Zigbee networks.

> **Goal:** keep stock behavior where it is already good, add more NCP headroom where production testing showed repeated `SLStatus.BUSY`, and make deployment/rollback reproducible and safe.

P009 is not a generic Zigbee performance hack and it does not change RF power, channel, network identity, routing strategy or retry behavior.

Active work: https://github.com/analienx/Sonoff-Dongle-Max/issues/1

Historical root-cause investigation: https://github.com/analienx/home-assistant-stack/issues/47

## What is different from the stock 9.1.1 baseline?

P009 changes only two compile-time resource values in the pinned MG24 NCP profile:

| Resource | Stock baseline | P009 | Why |
|---|---:|---:|---|
| Zigbee broadcast table | 30 | **64** | More simultaneous broadcast-transaction headroom before the NCP must reject new broadcast work. |
| Zigbee key table | 1 | **12** | More capacity for APS/link-key entries instead of leaving the coordinator at the unusually small upstream default. |

The build verifier fails unless these are the **only intended profile differences** between the P009 and rollback builds.

### Important resources deliberately left unchanged

| Resource | P009 |
|---|---:|
| Route table | 254 |
| Source-route table | 254 |
| Address table | 128 |
| APS unicast messages | 128 |
| Discovery table | 16 |
| Multicast table | 26 |
| Neighbor table | **26 (Silicon Labs maximum)** |
| Binding table | 32 |
| Max end-device children | 64 |
| APS duplicate-rejection entries | 64 |
| Packet-buffer heap | HUGE |
| Retry queue | 16 |
| Store-and-forward | 5 |

**Neighbor-table note:** this is already fully tuned. Silicon Labs supports neighbor-table sizes of 1, 16 or **26**, with 26 the maximum number of router neighbors the Ember stack can track. P009 therefore retains 26 rather than inventing an unsupported 27/32 setting. This is also the value used by Nabu Casa's current MG24 ZBT-2 profile. End-device children are tracked separately; route/source-route capacity is also separate and is already set to 254.

Transport is also unchanged:

```text
EFR32MG24A420F1536IM48
EmberZNet 9.1.1
EZSP 19
EUSART1
115200 baud
no hardware flow control
```

## Why might P009 be better on a large Zigbee network?

### 1. More broadcast headroom

The primary reason for P009 is repeated Ember/NCP `BUSY` responses observed on a production network with more than 100 devices, especially on broadcast paths such as **Permit Join All** and other operations that fan out across the mesh.

The pinned stock MG24 builder allocates **30 broadcast-table entries**. P009 raises that to **64**. The expected effect is that the NCP can keep more broadcast transactions in flight before refusing additional broadcast work.

This may improve reliability of:

- Zigbee group/broadcast operations;
- Permit Join All;
- network-management broadcasts;
- busy periods where application broadcasts overlap routing/mesh traffic.

This is the main P009 hypothesis and is being verified with bounded production acceptance tests. It should not be interpreted as a guarantee that every `BUSY` condition comes from the broadcast table.

### 2. Less dependence on retry workarounds

An earlier workaround retried failed broadcast sends. P009 intentionally does **not** add more retries or enlarge the retry queue.

The preferred strategy is:

```text
more real NCP capacity
        instead of
more software retries under pressure
```

That should reduce the risk of turning temporary congestion into additional queued traffic.

### 3. More sensible key-table capacity

The upstream baseline used by this build has a key table of only **1** entry. P009 raises it to **12** while leaving security behavior itself unchanged.

This does not make Zigbee encryption “stronger”. It simply gives the coordinator more room for devices or features that require APS/link-key table entries.

### 4. Neighbor/routing capacity is already near the useful ceiling

The coordinator's **neighbor table is already at Ember's hard maximum of 26 router neighbors**, so P009 does not try to enlarge it further. Likewise, the route and source-route tables are already 254 entries each. That means P009's resource tuning is aimed at the remaining demonstrated pressure point—broadcast admission—rather than changing already-maximized mesh-topology tables.

A larger neighbor table would not increase radio range or make every router a direct neighbor; direct-neighbor quality still depends on RF placement and topology.

### 5. Everything else stays familiar

P009 does not attempt to solve unrelated Zigbee problems by changing many parameters at once. Keeping routing tables, source routing, UART transport, RF/network identity and retry behavior unchanged makes the result easier to attribute and easier to roll back.

## What P009 does **not** change

P009 does not:

- change Zigbee channel;
- change coordinator IEEE/PAN/extPAN/network key;
- clear NVM;
- require devices to be paired again;
- increase RF transmit power;
- change EUSART baud rate or flow control;
- enlarge the retry queue;
- add broad `BUSY` retry loops;
- replace Zigbee2MQTT by default;
- promise higher LQI/RSSI or magically repair a weak RF mesh.

If a network problem is caused by RF interference, poor router placement, a bad device, route churn or host instability, a larger broadcast table is not a substitute for fixing that root cause.

## Optional runtime policy

The repository also prepares an **optional**, pinned zigbee-herdsman 10.9.1 policy overlay. It is not deployed during the firmware-first test.

If later required, it explicitly sets and reads back:

```text
BROADCAST_TABLE_SIZE               64
NEW_BROADCAST_ENTRY_THRESHOLD      48
RETRY_QUEUE_SIZE                   16
MTORR_FLOW_CONTROL                  1
SUPPORTED_NETWORKS                  1
SEND_MULTICASTS_TO_SLEEPY_ADDRESS  0
```

The threshold of **48** deliberately leaves 16 of the 64 broadcast entries available for relaying broadcasts originated elsewhere in the mesh.

Every value must read back correctly or Zigbee2MQTT startup fails loudly. The overlay does not modify the existing herdsman send/retry algorithm.

## Reproducible stock rollback

A major feature of this repository is not just the tuned firmware itself, but the way it is built.

Every CI run builds:

1. **P009 firmware**;
2. an **unmodified stock rollback firmware**;
3. both from the **same pinned Silicon Labs builder/toolchain**.

The artifact contains:

- `.gbl`, `.hex` and `.out` for P009;
- `.gbl`, `.hex` and `.out` for stock rollback;
- effective stock and P009 resource profiles;
- the exact SONOFF hardware manifest;
- build/toolchain provenance;
- `P009-BUILD-MANIFEST.json`;
- `SHA256SUMS` for the entire bundle.

This makes rollback a first-class part of the build rather than an unrelated firmware download found later.

## Controlled deployment tooling

The `deploy/` tooling treats firmware flashing as a stateful production change instead of a loose list of shell commands.

```text
ARMING
  -> ARMED
  -> FLASH_CONFIRMED
  -> IDENTITY_VERIFIED
  -> AUTOMATED_ACCEPTANCE_PASSED
  -> ACCEPTED

Any failed/interrupted safety gate -> STOPPED
```

Notable safeguards:

- verifies all build-bundle checksums before ARM;
- verifies exactly one running Zigbee2MQTT owner;
- creates and hashes a stopped-state Z2M backup;
- fingerprints the network key **on the HA host** without copying the plaintext key to deployment evidence;
- locks a deployment session to the exact host, add-on, Zigbee2MQTT path and SSH/proxy transport;
- requires explicit confirmation of the ARM-verified P009 GBL SHA-256 after the manual WebUI flash;
- checks IEEE, PAN ID, extended PAN ID, channel, network-key fingerprint, key sequence and backup device count after flashing;
- automatically stops on safety-gate failures;
- keeps the actual firmware upload manual through the already-proven SONOFF WebUI path;
- includes a same-build stock rollback image and hash-verified data restore path.

The CLI itself never flashes firmware.

## Bounded acceptance instead of endless soak testing

After flashing, P009 uses a deliberately small acceptance gate:

- read-only **2 × 8 real ZCL transaction canary**;
- exactly **5 × 10-second Permit Join All** trials;
- scan the test window for `BUSY`, message-pressure errors and NCP/ASH resets;
- exactly **2 representative group commands** with physical verification;
- final network-identity recheck.

If this passes, testing stops. If `BUSY` still reproduces, the exact failure is captured and the next decision is made from evidence rather than running a large parameter matrix.

## Expected benefit summary

For a small, healthy Zigbee network, P009 may provide little or no visible difference from stock firmware.

For a **large MG24 network with significant broadcast/group traffic**, P009 is intended to provide:

- more NCP broadcast capacity;
- fewer broadcast-path `BUSY` rejections;
- better tolerance of short traffic bursts;
- less need for host-side retry workarounds;
- more reasonable APS/link-key table capacity;
- deterministic rollback and much safer firmware deployment.

The first four are **expected engineering benefits**, not yet universal performance claims. Production acceptance results will be recorded in issue #1.

## Repository layout

- `firmware/` — pinned MG24 source patch, resource contract and strict P009/stock artifact verifier.
- `deploy/` — resumable deployment state machine, remote transport and bounded acceptance probes.
- `runtime/` — optional pinned zigbee-herdsman 10.9.1 policy overlay.
- `tests/` — regression tests for transport, identity, policy readbacks and deployment gates.
- `docs/EXECUTOR-DEPLOY.md` — mechanical deployment procedure.
- `.github/workflows/build-p009.yml` — controlled P009 + same-toolchain stock rollback build.

Development is staged on `p009-staging`. The firmware workflow is triggered from `p009-mg24-broadcast-headroom` only after staging review, avoiding unnecessary intermediate firmware builds.

## Status

**Experimental / production validation in progress.**

P009 is designed to be conservative and reversible, but it is still custom coordinator firmware. Review `docs/EXECUTOR-DEPLOY.md` and issue #1 before flashing.