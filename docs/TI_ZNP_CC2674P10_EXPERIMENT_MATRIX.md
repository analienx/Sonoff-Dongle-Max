# mr4u-p10 — Firmware A/B Experiment Matrix

> **Planning only.** No firmware build or flash is authorized by this file.
>
> Purpose: make every future P10 run comparable enough that "worked better" becomes evidence rather than impression.

## 1. Candidate sequence

The planned order is intentionally serial. Do not run multiple firmware changes at once.

| ID | Firmware | SDK lineage | Purpose | Production network? | Instrumented? |
|---|---|---|---|---:|---:|
| V24 | SMLIGHT **20240716** | SDK 7.41 | first vendor regression baseline | yes, only after capacity gate | vendor only |
| V26 | SMLIGHT **20260311** | SDK 8.32.00.07 + SMLIGHT low-level UART/DMA/NPI changes | known failed baseline | yes | vendor only |
| V25 | SMLIGHT 20250325 | SDK 8.30, vendor test/dev | optional forensic midpoint only; vendor warns about PAN/commissioning | preferably no / controlled only | vendor only |
| T830-LAB-R0 | pristine TI reference ZNP + MR4U board adaptation | 8.30.01.01 | board/toolchain/protocol smoke | no | no |
| T830-KCTRL-R0 | TI + reviewed Koenkk coordinator patch set + MR4U + measured capacity | 8.30.01.01 | **first production control** | yes | no |
| T832-KCTRL-R0 | same logical control manifest, rebuilt on TI 8.32 | 8.32.00.07 | isolate TI SDK from SMLIGHT downstream | yes | no |
| T830-KDIAG-D0 | same functional config as T830-KCTRL-R0 | 8.30.01.01 | instrument only if 8.30 is the failing boundary | yes | yes |
| T832-KDIAG-D0 | same functional config as T832-KCTRL-R0 | 8.32.00.07 | instrument only if 8.32/SMLIGHT boundary is failing | yes | yes |
| CUSTOM-* | targeted fix | chosen only after evidence | fix proven failure mechanism | eventually | as needed |

The sequence can stop early if an experiment provides a decisive discriminator.


## 1.1 Hard pre-restore capacity gate for SMLIGHT 20240716

The fresh production backup currently requires:

- 102 coordinator device records;
- 101 link-key records.

The 20240716 image is a useful stability baseline but its exact SMLIGHT/P10 compiled capacity is not publicly proven.

Therefore **do not restore the production backup immediately after flashing 20240716**.

Required sequence while the newly flashed P10 is still idle/uncommissioned:

1. verify exact firmware revision and 115200 transport;
2. verify `SYS_PING` / `SYS_VERSION`;
3. run length-only TCLK NV allocation scan using the fail-closed `p10_nv_lengths.py` logic (or an equivalently reviewed TCP-safe variant);
4. require **at least 101 provisioned TCLK records**, with a preferred operational gate of >=120 to retain headroom;
5. if the upper boundary cannot be established or capacity is below the backup requirement, **do not attempt restore**;
6. rollback to the known 20260311 image and restore the fresh backup if necessary.

This separates firmware-capacity incompatibility from the runtime-hang experiment.

Neighbor/routing capacity cannot be inferred from TCLK capacity. Even if the restore gate passes, 20240716 remains a **crash-stability baseline**, not automatically the best long-term topology firmware.

Koenkk 20240710 source configuration is relevant context, not proof of the SMLIGHT P10 compiled image:

- `MAX_NEIGHBOR_ENTRIES 25`;
- `NWK_MAX_DEVICE_LIST 50`;
- `MAX_RTG_ENTRIES 100`;
- `MAX_RTG_SRC_ENTRIES 250`;
- `ZDSECMGR_TC_DEVICE_MAX 200`;
- `NVOCMP_RECOVER_FROM_COMPACT_FAILURE`;
- NPI UART2 completion on `UART2_EVENT_TX_FINISHED`.

SMLIGHT may have modified P10-specific capacity. Runtime evidence on the exact flashed image is authoritative.


## 1.2 Custom-control boundary

The custom path is deliberately two-stage:

```
T830-KCTRL-R0
    |
    | same coordinator manifest, board mapping, capacities, baud and host
    v
T832-KCTRL-R0
    |
    | compare to SMLIGHT 20260311 on the same SDK family
    v
SMLIGHT 20260311
```

Interpretation:

- T830 stable + T832 stable + SMLIGHT hangs -> strongest evidence for SMLIGHT downstream integration.
- T830 stable + T832 hangs + SMLIGHT hangs -> TI 8.32/Core-SDK interaction becomes primary.
- T830 hangs + T832 hangs -> common TI/Koenkk coordinator path or production workload.
- T830 hangs + T832 stable -> inspect 8.30-specific integration before any downstream conclusion.

Do not add diagnostics to either control until this boundary is established.


---

# 2. A/B invariants

For V24 vs T830-KCTRL-R0, freeze:

- same physical MR4U;
- same P10 radio silicon;
- same USB path/bridge mode;
- same PoE/USB topology;
- same Home Assistant host;
- same Zigbee2MQTT version;
- same zigbee-herdsman version;
- same channel;
- same coordinator identity;
- same PAN/extPAN;
- same network key/security state;
- same device database;
- same group definitions;
- same TX-power target where board/RF implementation allows a safe exact match;
- same household/device population;
- same health-probe interval;
- same synthetic workload schedule when synthetic workload is eventually enabled.

If an invariant changes, record it and treat the run as a new experiment class.
## 2.1 Forensic invariants specific to the current regression

In addition to the generic A/B invariants, preserve these exact distinctions:

### SMLIGHT 20240716

- SDK 7.41;
- 115200 baud;
- vendor production channel;
- no 20260311-advertised UART abstraction/ring-buffer/DMA-priority/FIFO/task-stack optimization layer.

### SMLIGHT 20260311

- SDK 8.32.00.07;
- 115200 baud;
- beta channel;
- SMLIGHT explicitly advertises:
  - UART abstraction removal;
  - P7/P10 RX/TX ring-buffer optimization;
  - NPI task-stack optimization;
  - DMA/UART priority optimization;
  - FIFO-threshold optimization;
  - custom reset handler/reboot-reason tracking.

The experiment should not change baud rate, Z2M/herdsman version, channel or network identity while comparing these builds.


---

# 3. Run manifest

Every run receives a unique ID:

~~~
YYYYMMDDTHHMMSSZ-<firmware-id>-<phase>
~~~

Example:

~~~
20261005T180000Z-T830-KCTRL-R0-S1
~~~

Public sanitized manifest fields:

~~~json
{
  "schema": 1,
  "run_id": "...",
  "firmware_id": "T830-KCTRL-R0",
  "firmware_sha256": "...",
  "build_manifest_sha256": "...",
  "z2m_version": "...",
  "herdsman_version": "...",
  "channel": 11,
  "device_count": 0,
  "router_count": 0,
  "phase": "S1",
  "start_utc": "...",
  "end_utc": null,
  "termination": null,
  "first_af_srsp_timeout_utc": null,
  "first_zdo_srsp_timeout_utc": null,
  "first_sys_anomaly_utc": null,
  "terminal_sys_failure_utc": null,
  "cold_power_cycle_required": null
}
~~~

No IEEE addresses or keys in public run manifests.

---

# 4. Phase definitions

## P0 — offline artifact qualification

Must pass before hardware contact:

- source provenance;
- toolchain provenance;
- board-diff classification;
- linker/CCFG/NVS audit;
- capacity audit;
- exact image SHA;
- rollback image presence.

No runtime result can compensate for failure here.

## P1 — isolated transport smoke

Target: T830-LAB-R0.

Operations:

- 20 SYS_PING;
- 20 SYS_VERSION;
- 20 application resets;
- 10 cold boots;
- bounded serial open/close cycles;
- BSL recovery validation.

No production backup loaded.

## P2 — isolated Zigbee smoke

Only on isolated radio/network.

Operations:

- form a disposable network only on intentionally isolated lab state;
- one router join;
- one end-device join if lab hardware exists;
- unicast command;
- groupcast;
- Mgmt_Lqi;
- permit join open/close;
- restart.

After P2 the lab state is disposable; do not confuse it with production restore evidence.

## P3 — production restore smoke

Targets: V24 after its capacity gate, then later T830-KCTRL-R0.

No stress.

Required:

- restore only after capacity/identity gates pass;
- identity;
- security counts;
- representative traffic;
- groupcast;
- inbound remote;
- normal Z2M restart once while coordinator healthy;
- reset-domain behavior recorded without intentionally causing a failure.

For V24, explicitly record whether restore consumes all required TCLK/device entries and whether any capacity warning appears.

## S0 — settle

Duration: 30–60 minutes.

Allowed:

- ordinary household traffic;
- low-rate coordinator health probe.

Forbidden:

- network-map sweep;
- repeated permit join;
- synthetic burst;
- repeated group toggling.

## S1 — normal production baseline

Minimum: 24 hours.

Goal: detect spontaneous progressive failure.

## S2 — confidence soak

Minimum:

~~~
max(72 hours, 3 x observed 20260311 failure interval)
~~~

No synthetic workload if the candidate already fails naturally.

## S3 — controlled trigger isolation

One workload class per epoch.

See section 8.

## S4 — final production confidence

Goal: 7 days ordinary operation after the final candidate/fix.

---

# 5. Health probe

Health probing itself can affect the coordinator, so keep it intentionally low-rate.

Initial policy:

~~~
every 10 minutes:
    one coordinator-check / SYS_VERSION-equivalent request
~~~

Capture:

- request UTC;
- response UTC;
- latency;
- status;
- error subsystem;
- error category.

Do not issue retry storms.

If a probe times out:

1. do not immediately send ten more;
2. mark F3 candidate;
3. collect existing logs;
4. issue at most one confirmation SYS probe if safe;
5. stop synthetic traffic.

A future diagnostic image may emit its own telemetry, but the release-control host probe remains unchanged.

---

# 6. Failure taxonomy

## F0 — healthy

- no SRSP timeout;
- ordinary destination-specific ZCL failures do not count by themselves;
- SYS probe latency within observed healthy range.

## F1 — first coordinator transport warning

Any repeated coordinator-origin:

~~~
SRSP - AF - dataRequest after 6000ms
SRSP - AF - dataRequestExt after 6000ms
~~~

across unrelated destinations, or repeatedly against a known-good destination.

Action:

- timestamp;
- freeze workload escalation;
- preserve 15 minutes pre-event / post-event logs.

## F2 — coordinator management degradation

Examples:

~~~
SRSP - ZDO - mgmtLqiReq after 6000ms
SRSP - ZDO - mgmtPermitJoinReq after 6000ms
~~~

Action:

- stop synthetic Zigbee traffic;
- no route-map retries;
- collect diagnostic state.

## F3 — local ZNP control degradation

Examples:

~~~
SRSP - SYS - version after 6000ms
abnormal SYS probe latency
~~~

Action:

- stop device-level troubleshooting;
- preserve host/bridge evidence.

## F4 — terminal radio hang

After Z2M restart / serial reopen:

~~~
SRSP - SYS - ping after 6000ms
~~~

Action:

- record exact restart result;
- capture MR4U management state;
- only then cold power-cycle.

F4 is the signature used to compare against issue #73.

---

# 7. Event windows

On first F1 event, save a private bundle covering:

~~~
T-15 min .. T+15 min
~~~

Include:

- Z2M logs;
- add-on state;
- host CPU/load;
- MQTT connectivity;
- health-probe history;
- traffic counters;
- recent HA automation activity affecting Zigbee, sanitized;
- MR4U management status/logs if available;
- diagnostic firmware telemetry if applicable.

On F3/F4, expand to the full run tail.

---

# 8. Controlled trigger-isolation epochs

These are executed only after normal-load soak is understood.

Each epoch has:

~~~
15 min pre-baseline
test operation
30 min observe
~~~

Do not stack triggers in one epoch until single triggers have been classified.

## E1 — bounded unicast

- fixed 5–10 routers;
- one command per 5 seconds;
- total 50 commands;
- no full mesh enumeration.

Question: does ordinary AF load alone cause resource decline?

## E2 — groupcast

- one existing safe group;
- fixed low rate;
- no device reconfiguration;
- capture command count.

Question: does group/broadcast path accelerate the hang?

## E3 — targeted Mgmt_Lqi

- one known-good router;
- one Mgmt_Lqi request per minute;
- maximum 20 requests.

Question: does ZDO management traffic trigger degradation?

## E4 — router-scoped permit join

- known-good router;
- short 10-second windows;
- no device intentionally pairing;
- maximum five windows;
- explicitly close.

Question: does management permit-joining / broadcast work correlate?

## E5 — normal rejoin

Only if a safe test device is available.

- power-cycle one already-known device;
- no factory reset;
- scoped permit join if needed.

Question: does association/rejoin state pressure matter?

## E6 — reporting load

Do not create extra reporting configuration at first.

Observe an existing naturally high-reporting period and compare counters.

If synthetic reporting is later needed, use isolated test devices, not arbitrary production changes.

## E7 — combined reproduction

Only after individual trigger data exists.

Reproduce the historical sequence preceding the 2 Oct incident as closely as possible.

---

# 9. Stop rules during trigger testing

Stop the epoch immediately on:

- first F2;
- two F1 events within five minutes;
- health-probe latency exceeding a predetermined healthy threshold;
- unexpected Z2M restart;
- device-wide availability cascade.

Do not continue "to see how dead it gets" unless a specific diagnostic reproduction has been authorized.

---

# 10. 2024 SMLIGHT baseline capture

The user is currently reflashing/testing the 2024 firmware.

For that run, capture as soon as practical:

- exact UI-reported version;
- ZNP SYS_VERSION revision;
- exact firmware image SHA if the image is available;
- start/cold-boot timestamp;
- channel;
- TX power;
- Z2M/herdsman versions;
- network device/router counts;
- first AF timeout if any;
- F2/F3/F4 events;
- whether Z2M restart recovers;
- whether cold USB+PoE power cycle is required.

Do not change traffic just to make the 2024 run match a future script; first establish natural stability.

Primary outcomes:

~~~
time_to_first_F1
time_to_F3
time_to_F4
~~~

If no failure, report the observation as censored at the run duration.

Do not claim "fixed" after a few hours.

---

# 11. TI 8.30 production-control acceptance

A T830-KCTRL-R0 run can enter S1 only if:

- static image audit passes;
- capacity evidence passes;
- restore identity passes;
- representative traffic passes;
- no F1 during first 30-minute settle;
- SYS probes healthy;
- rollback remains available.

If an issue appears before S1, classify it as port/restore incompatibility rather than the progressive-hang experiment.

---

# 12. Diagnostic-build run

If T830-KCTRL-R0 reaches F1/F2/F3:

1. preserve release-control crash bundle;
2. cold recover;
3. rollback or load T830-KDIAG-D0;
4. restore the same network state;
5. repeat normal-load phase first;
6. only then reproduce the trigger epoch if needed.

The D0 goal is classification, not stability.

Required diagnostic outputs:

- last known heap free/min;
- allocation-failure counter;
- AF pending / failures;
- ZDO pending;
- last MT SREQ;
- last completed MT SRSP;
- stack watermarks;
- exception/error-hook state;
- reset/fault breadcrumb.

Possible evidence classes:

~~~
HEAP_EXHAUSTION
AF_RESOURCE_EXHAUSTION
ZDO_PENDING_LEAK
STACK_OVERFLOW
HARD_EXCEPTION
ERROR_SPIN
ABORT_SPIN
MT_TASK_STARVATION
DEADLOCK_UNKNOWN
UART_BRIDGE_PATH
UNKNOWN
~~~

Do not assign a more specific class than the evidence supports.

---

# 13. Engineering interpretation

This is an engineering A/B, not a statistical population study.

Prefer:

- survival duration;
- event rate per hour;
- repeated reproduction;
- identical workload epochs;
- clear terminal signature.

Strong evidence example:

~~~
V26 fails 3/3 within 4–8 h
V24 survives 7 d
T830-KCTRL-R0 fails 3/3 within 4–8 h
~~~

Weak evidence example:

~~~
V26 failed once
V24 ran 10 h
T830 ran 12 h
~~~

Avoid certainty language when exposure time differs materially.

---

# 14. Comparison report template

For each completed candidate record:

## Artifact

- firmware ID:
- SHA:
- SDK:
- source commit:
- build manifest:
- control/diag:

## Environment

- Z2M:
- herdsman:
- device count:
- router count:
- channel:
- TX:
- start UTC:

## Exposure

- ordinary-use hours:
- S3 epochs run:
- total outbound test operations:

## Failure

- F1:
- F2:
- F3:
- F4:
- cold power cycle required:
- spontaneous reboot observed:

## Diagnostic counters

- n/a for release control unless standard counters exist.

## Interpretation

- evidence supports:
- evidence does not support:
- next discriminator:

---

# 15. Firmware selection decision tree

~~~
Start with SMLIGHT 2024 soak
|
+-- F4 repeats quickly
|    |
|    +--> build/test TI 8.30 control
|            |
|            +-- TI F4 repeats --> TI diagnostic build
|            |
|            +-- TI stable --> downstream/vendor diff
|
+-- SMLIGHT 2024 stable long enough
     |
     +--> still test TI 8.30 control if root-cause classification is desired
             |
             +-- TI stable --> regression likely newer vendor lineage
             |
             +-- TI hangs --> 2024 contains mitigation absent from TI reference;
                              compare configuration before patching
~~~

Even if 2024 proves stable, the TI control remains valuable because it separates "old vendor build happens to work" from "TI reference stack is healthy."

---

# 16. Final operational acceptance

A candidate can be considered operationally acceptable only after:

- no F2/F3/F4 in 7 days normal production;
- no rising F1 event rate;
- representative group/unicast/rejoin paths pass;
- route/source-route behavior does not materially impair the network;
- no periodic cold reset required;
- no security/restore compromise;
- no table-capacity exhaustion;
- host/Z2M stays unchanged during comparison.

Operational acceptance is not proof that the underlying TI bug has been eliminated.

---

# 17. What justifies starting a custom Z-Stack fix

Custom firmware work begins only if at least one is true:

1. TI-PROD-DIAG captures a specific resource leak/exhaustion.
2. TI-PROD-DIAG captures Error_SPIN / stack / exception evidence.
3. A reproducible upstream/downstream configuration difference maps directly to the hang.
4. TI/vendor source history identifies a candidate patch that can be isolated.
5. A deterministic workload reproduces the failure often enough to test a fix.

At that point create a **new fix branch**. Do not mutate the control branch.

---

# 18. Git/branch discipline

Current planning branch:

~~~
plan/mr4u-p10-ti-znp-control
~~~

Future branches:

~~~
exp/ti830-p10-znp-lab-r0
exp/ti830-p10-znp-prod-r0
exp/ti830-p10-znp-prod-d0
fix/p10-<proven-root-cause>
~~~

Never build a diagnostic/fix image from an uncommitted dirty tree.

Every flashed image must map to exactly one commit and manifest.


---


# 19. Forensic interpretation hardened after source review

## 19.1 Historical TI/Koenkk crash lesson

The relevant TI E2E investigation established that the SDK 6.20 long-uptime crash could take 3–7 days and was not caused by one single factor. The final stable combination reported by Koen/TI required:

- `NVOCMP_RECOVER_FROM_COMPACT_FAILURE`;
- changing the problematic UART2 integration path.

Later stable coordinator generations did **not** simply abandon UART2 forever. Koenkk 20240710 uses UART2 but patches NPI completion semantics around `UART2_EVENT_TX_FINISHED`.

Therefore the correct lesson is:

> Treat NV compaction/recovery and NPI UART2 completion/state handling as interacting failure domains. Do not reduce the hypothesis to “memory leak” or “UART2 is broken”.

## 19.2 Exact 20240710 -> 20250321 coordinator changes relevant to our network

Public Koenkk patches show:

| Setting | 20240710 | 20250321 |
|---|---:|---:|
| SDK | 7.41.00.17 | 8.30.01.01 |
| NVOCMP recovery | enabled | enabled |
| MAC TX data | 50 | 50 |
| MAC TX max | 80 | 80 |
| MAC RX max | 50 | 50 |
| route table | 100 | 150 |
| source routes | 250 | 250 |
| route requests | 40 | 40 |
| direct-device list | 50 | 75 |
| neighbor table | 25 | 50 |
| Trust Center devices | 200 | 400 on P10 target, 200 otherwise |
| UART ISR buffer | SDK/default path | increased 32 -> 128 |
| NPI TX completion | `UART2_EVENT_TX_FINISHED` patch | retained |

This makes 20240716 useful for **stability regression**, but potentially less representative of the capacity/topology we ultimately want for ~60 routers.

## 19.3 Why SMLIGHT 20250325 is not the preferred next production step

It would be an attractive SDK midpoint, but SMLIGHT itself marks it test/dev and warns about PAN-ID/commissioning problems after flashing.

That means a failure on 20250325 could be:

- migration/layout behavior;
- commissioning state;
- capacity/config change;
- the runtime hang under study.

That is too confounded for the first production A/B. Prefer 20240716 first, then the reproducible T830-KCTRL-R0 control.

## 19.4 Why 20260311 is especially suspicious

TI SDK 8.32.00.07 states that only Wi-SUN changed relative to 8.31.00.11; other SDK components remain the same. The underlying Z-Stack generation remains 8.30.x.

SMLIGHT 20260311, however, explicitly advertises additional low-level UART/DMA/NPI/FIFO/task-stack modifications.

Therefore the highest-value regression boundary is no longer simply:

```
TI SDK 7.41 vs TI SDK 8.32
```

It is:

```
SMLIGHT/Koenkk-style 7.41 coordinator integration
vs
TI 8.30 coordinator baseline
vs
SMLIGHT 8.32 + custom low-level transport integration
```

This is the structure future tests must preserve.

---

# 19. Reset-domain discrimination matrix

The 2 Oct incident established that recovery method itself is diagnostic evidence.

Observed on current MR4U/P10:

- Zigbee2MQTT restart / serial reopen did not recover the radio.
- Direct ZNP `SYS_RESET_REQ` produced no response and did not recover the radio.
- SLZB-OS **Zigbee radio restart** recovered the P10 and restored valid `SYS_PING` over the Ethernet ZNP endpoint.
- A previous full MR4U cold cycle did not immediately produce a usable ZNP path in the tested sequence; USB enumeration/transport sequencing also complicated that observation.

Do not collapse these into a generic “restart”.

## Reset classes

| ID | Recovery action | Executes code on hung ZNP? | Expected volatile-state effect | Destructive to Zigbee NVM? |
|---|---|---:|---:|---:|
| R0 | Z2M restart / serial reopen | no P10 reset | none | no |
| R1 | ZNP `SYS_RESET_REQ` | yes — requires MT/ZNP parser to run | application/system reset if serviced | no |
| R2 | SLZB-OS radio restart / hardware reset line | no cooperation from ZNP expected | hardware reset; intended to clear active CPU/SRAM state | no |
| R3 | true MR4U/P10 power removal | no | full volatile-state loss | no |
| R4 | reflash same application image without mass erase | bootloader/debug path | image rewritten; persistent NVS may remain depending flash layout/tool | potentially no, but verify |
| R5 | mass erase + reflash + restore | no | all volatile + application/NVS reset | **yes**; backup/restore required |

## Interpretation

### R1 fails, R2 succeeds

Strongly supports one of:

- MT/ZNP task deadlock/starvation;
- heap/queue/resource exhaustion preventing command processing;
- CPU/peripheral state that requires hardware reset;
- fault/error spin;
- stack corruption;
- scheduler/interrupt deadlock.

This pattern makes a reflash-only brick unlikely.

### R2 fails, R3 succeeds

Raises probability of:

- reset-domain/AON/peripheral state not fully cleared by board-level RST;
- reset-line implementation/timing problem;
- hardware interface state surviving RST;
- bridge/P10 reset sequencing issue.

### R2 and R3 fail, R4 succeeds

Raises probability of:

- application flash corruption;
- boot-time image/configuration corruption;
- firmware state rewritten by flashing;
- a bootloader/application transition problem.

Do not infer NVS corruption unless R4 is proven to erase/change the relevant NVS region.

### R4 fails, R5 + restore succeeds

Raises probability of persistent NVS/configuration corruption or an incompatible stored state.

This is the first outcome that strongly points to persistent network/application state rather than runtime volatile state.

## Required future evidence

For every reproduced F3/F4 event, record:

1. exact failure timestamp;
2. R0 outcome;
3. one bounded R1 attempt;
4. R2 outcome;
5. R3 only if R2 fails;
6. reflash only after evidence capture and backup gate;
7. reset reason / fault breadcrumb in diagnostic builds.

Never jump directly from F4 to reflash. The recovery boundary is part of the root-cause evidence.

## TI hardware fact to preserve

The CC2674P10 datasheet indicates that while the RESET pin is held, CPU/register state and SRAM are not retained. Therefore an R2 recovery is consistent with clearing a volatile runtime failure. It does **not** prove which volatile resource failed.

Official reference:
https://www.ti.com/lit/ds/symlink/cc2674p10.pdf

## SMLIGHT known-issue comparison

SMLIGHT documents a long-standing CC26XX SDK hang class affecting CC2674P10 with the same terminal symptom `SRSP - SYS - ping after 6000ms`. Their documentation notes that the radio may sometimes fail to respond even to the RST pin and can require physical power removal.

Our present incident is therefore within the documented failure family, but the successful R2 radio restart is an important per-incident discriminator and must be preserved rather than generalized away.

Official reference:
https://smlight.tech/support/manuals/books/slzb-os/page/all-os-versions


---

# 20. Vendor regression ladder discovered 2026-10-02

SMLIGHT's current public update API provides a much more precise firmware lineage than was known when this plan was first written.

| ID | SMLIGHT revision | SDK | Channel | Baud | Public image SHA-256 | Diagnostic meaning |
|---|---:|---|---|---:|---|---|
| V24 | 20240716 | **7.41** | production | 115200 | `633f79058c39e2fc9335bb11f816ad6a045438515da11c36b30a46b7c8d1b7d9` | old stable/control candidate |
| V25 | 20250325 | **8.30** | test/dev | 115200 | `16ad308f550947098f703d09148aafec5277550dd762fe72ec22e9768a3c5808` | SDK-transition intermediate; backup-safe lab use only |
| V26-115 | 20260311 | **8.32.00.07** | beta | 115200 | `63af04ded64441bb355aa1ee874549f381c16dfb0e3f3954a00f475af9a5c94a` | observed failing production image |
| V26-460 | 20260310 | **8.32.00.07** | beta | 460800 | `ff5a6fbf1a2c8327bcf28ea95b95189849b368f4952a92a64d25517db7fee7ec` | same vendor code family, high-baud variant |

Vendor API:
`https://updates.smlight.tech/services/api/slzb-06x-ota.php?type=ZB&format=slzb&device=4`

## Critical 20260311 vendor deltas

SMLIGHT explicitly describes 20260311/20260310 as containing low-level coordinator transport/runtime work:

- removed one abstraction layer from the UART path;
- optimized UART RX/TX ring buffers for P7/P10;
- optimized NPI task stack usage;
- optimized DMA and UART priorities;
- optimized FIFO thresholds;
- added a custom reset handler with reboot-reason tracking.

This is now a first-class suspect area because the observed failure terminates in MT/ZNP command starvation.

## Binary observations

Downloaded directly from the public vendor URLs:

- V24 image size: 182,840 bytes.
- V25 image size: 278,126 bytes.
- V26-115 image size: 278,134 bytes.
- V26-460 image size: 278,134 bytes.
- V24 -> V25 is a major image/layout transition (+95,286 bytes). The newer images expose MCUBoot-related strings absent from V24.
- V25 vs V26-115: approximately 64.6% of overlapping raw bytes differ despite almost identical image size. Treat this as a substantial rebuild/code change.
- V26-115 vs V26-460: only 106 raw bytes differ at equal size, strongly supporting the vendor statement that they are the same code family differentiated mainly by baud/build metadata and signatures.

## Important TI-stack nuance

SimpleLink SDK 8.32.00.07 still packages **TI Z-Stack 8.30.00.x**.

Therefore V25 -> V26 is not best modeled as “new Zigbee routing stack generation”. Highest-value differences are:

1. TI Core SDK / drivers;
2. SMLIGHT NPI/UART/DMA implementation;
3. runtime/task/buffer configuration;
4. NVOCMP/NVS configuration.

Routing and MTO load remain plausible triggers/accelerators rather than the leading terminal-fault location.

## Concrete static-diff targets

Before creating any custom fix, establish for V24 / V25 / V26 where technically possible:

### NPI / UART
- legacy UART vs UART2 vs vendor direct/custom UART path;
- exact RX/TX ring-buffer sizes;
- FIFO thresholds;
- DMA use and channel configuration;
- interrupt priorities;
- NPI task priority and stack size;
- TX completion mechanism;
- `UART2_EVENT_TX_FINISHED` handling;
- UART error/event handling;
- host baud and timing.

### NVOCMP / NVS
- `NVOCMP_RECOVER_FROM_COMPACT_FAILURE` enabled/disabled;
- NVOCMP version;
- page count and page size;
- NVS base/layout;
- RAM-optimization mode;
- compaction error path;
- sanity-check availability;
- migration behavior across V24 -> V25.

### OS / fault handling
- Error policy;
- Hwi exception handling;
- task/Hwi stack checks;
- reset handler;
- watchdog configuration;
- reset-reason persistence.

### Zigbee load/resource configuration
- OSAL heap size / auto-size mode;
- AF/MAC buffers;
- routing/source-route/RREQ tables;
- TCLK/device capacity;
- MTO configuration;
- route expiry.

## Historical TI precedent — use as a hypothesis generator, not proof

The long-running TI/Koenkk SDK 6.20 instability investigation showed a similar progression:

- `MEM_ERROR` / `BUFFER_FULL`;
- AF request timeouts;
- eventual ZNP silence;
- failure sometimes requiring 3–7 days to reproduce.

The final stable combination in that investigation required **both**:

1. `NVOCMP_RECOVER_FROM_COMPACT_FAILURE`;
2. legacy UART instead of UART2.

Earlier experiments with single changes were inconclusive. Therefore our P10 research must test subsystem combinations and avoid declaring a root cause from one correlated counter.

## Current experiment priority

1. Run V24 natural production soak without synthetic stress.
2. Preserve exact time-to-F1/F2/F3/F4 if it fails.
3. If V24 is stable beyond the V26 failure exposure, prioritize a **static V24 vs V26 transport/NVOCMP diff**.
4. Use V25 only if needed as a controlled intermediate boundary; vendor labels it test/dev and warns of PAN/commissioning behavior.
5. Build TI 8.30 release control to separate upstream TI behavior from SMLIGHT downstream changes.
6. Only then create diagnostic/custom firmware.
