# mr4u-p10 — CC2674P10 TI ZNP Control Firmware Planning Specification

> **Status: PLANNING ONLY.**
>
> This branch must not build, flash, erase, restore, or otherwise mutate any coordinator.
> It exists to design the experiment that follows the SMLIGHT 2024 soak.
>
> Tracking incident: [home-assistant-stack#73](https://github.com/analienx/home-assistant-stack/issues/73)

## 0. Executive decision

The next firmware investigation after the SMLIGHT 20240716 baseline is a **layered CC2674P10 control experiment**, not a single “vanilla TI” production image.

Forensic review found that coordinator stability depends on known, explicit coordinator patches that are not equivalent to TI application defaults. In particular, the Koenkk stable lineage enables `NVOCMP_RECOVER_FROM_COMPACT_FAILURE` and changes NPI UART2 completion handling to wait for `UART2_EVENT_TX_FINISHED`. TI itself has documented multiple UART2 race/completion bugs across SDK generations.

The experiment is therefore deliberately split into three artifacts:

1. **TI-VANILLA-LAB** — pristine TI reference ZNP plus only MR4U board adaptation/build identity. Used only for isolated toolchain, transport, reset, RF and protocol validation. It is **not** the first production control.
2. **TI-KOENKK-CONTROL** — TI SDK 8.30.01.01 plus a mechanically reviewed, minimal coordinator patch set derived from Koenkk 20250321, then MR4U board adaptation and measured production capacities. This is the primary production discriminator against SMLIGHT 20260311.
3. **TI-KOENKK-DIAG** — functionally identical to TI-KOENKK-CONTROL except for evidence-only diagnostic instrumentation needed to classify a reproduced hang.

The production control must remain intentionally boring: only upstream TI, the explicitly enumerated coordinator-stability/compatibility patch set, MR4U board support, measured capacity and build identity. No speculative “fixes” are allowed.

Why not deploy pure TI defaults to production first?

- TI NVOCMP recovery from compaction failure is customer-enabled, not a safe assumption.
- Historical TI/Koenkk investigation found the crash family required more than one interacting change.
- Koenkk 20240710 and 20250321 both carry explicit NPI UART2 TX-finished handling beyond the raw SDK project.
- A pure-TI production failure would therefore be ambiguous: it could simply reintroduce a previously known coordinator integration defect rather than isolate the SMLIGHT 20260311 regression.

---

# 1. Question the experiment must answer

The current SMLIGHT P10 failure signature is:

```
healthy operation
-> SRSP AF dataRequest/dataRequestExt timeouts
-> ZDO management timeout
-> SYS version timeout
-> Z2M restart / serial reopen
-> SYS ping timeout
-> only cold USB + PoE power removal recovers
```

The TI experiment must distinguish:

### Outcome A — TI control also hangs

Strongly increases probability of a defect in:

- TI Z-Stack / SimpleLink SDK,
- CC2674P10-specific stack/driver integration,
- scheduler/resource interaction common to both vendor and TI reference builds,
- workload-triggered silicon/SDK interaction.

Next action: reproduce on TI-KOENKK-DIAG and identify the internal failure mechanism.

### Outcome B — TI control remains stable while the matching SMLIGHT build hangs

Strongly increases probability of a downstream difference:

- SMLIGHT board/runtime adaptation,
- Koenkk-derived coordinator configuration,
- buffer/table sizing,
- feature flags,
- downstream ZNP changes,
- RF/PA board implementation,
- CCFG/NVS choices.

Next action: produce a mechanically generated diff between the TI control manifest and vendor build/config evidence.

### Outcome C — neither firmware hangs during equivalent soak

No root-cause conclusion. Increase observation duration and compare workload equivalence before attributing success to firmware.

---

# 2. Non-goals

The control experiment is **not**:

- a new optimized coordinator firmware;
- an excuse to maximize every Z-Stack table;
- a new Zigbee network;
- a migration to a different coordinator IEEE/PAN/extPAN/channel;
- a route-topology redesign;
- a watchdog-first workaround;
- a stress test before normal-load behavior is measured;
- a place to combine fixes for unrelated device/group/binding problems;
- a reason to expose Zigbee keys or device IEEE lists in git.

No custom resource-management changes are allowed in TI-KOENKK-CONTROL.

---

# 3. Upstream source baseline

## 3.1 First control SDK: SimpleLink Low Power F2 SDK 8.30.01.01

Pin the first production control to:

```
SimpleLink Low Power F2 SDK 8.30.01.01
Z-Stack 8.30.x lineage
TI Clang 3.2.2 LTS
SysConfig 1.21.1
TI-RTOS7
```

Why 8.30.01.01:

- it officially supports CC2674P10;
- Z-Stack 8.30 added `LP_CC2674P10` support (ZIGBEE-2101);
- it provides a clean comparison point around the SDK lineage used by later coordinator firmware;
- TI states 8.30.01.01 has no embedded-software changes from 8.30.00.121, so the exact package must still be pinned and hashed.

Official references:

- https://software-dl.ti.com/simplelink/esd/simplelink_cc13xx_cc26xx_sdk/8.30.01.01/exports/release_notes_simplelink_cc13xx_cc26xx_sdk_8_30_01_01.html
- https://software-dl.ti.com/simplelink/esd/simplelink_cc13xx_cc26xx_sdk/8.31.00.11/exports/docs/zigbee/release_notes_zigbee_8_30_00.html
- https://github.com/TexasInstruments/simplelink-lowpower-f2-sdk

## 3.2 Official P10 ZNP project

The TI SDK metadata exposes official CC2674P10 ZNP projects, including:

```
examples/rtos/LP_EM_CC2674P10/zstack/znp/tirtos7/iar/
examples/rtos/LP_EM_CC2674P10/zstack/znp/tirtos7/ticlang/
```

The planned implementation uses **TI Clang**, not IAR, for reproducibility and to avoid an IAR-license dependency.

Do not substitute a P7 project unless the exact pinned SDK unexpectedly lacks the P10 project at implementation time.

## 3.3 Current-SDK comparator is optional and later

TI's current public F2 SDK is 8.33.00.16. TI states its non-Wi-SUN components remain the same as 8.31.00.11.

A later `TI-CURRENT-CONTROL` can be useful, but it is not the first control. Adding a second SDK before the 8.30 control is understood would confound the experiment.

## 3.4 Forensic provenance ladder established before implementation

The vendor and upstream lineage currently known is:

| Build | SDK | Status | Key evidence |
|---|---|---|---|
| SMLIGHT 20240716 | 7.41 | production | last SMLIGHT production release before newer dev/beta line; based on the Koenkk 20240710 generation plus P10/SMLIGHT adaptation |
| Koenkk 20240710 | 7.41.00.17 | released | `NVOCMP_RECOVER_FROM_COMPACT_FAILURE`, UART2 TX-finished event handling, large-network table/buffer tuning |
| SMLIGHT 20250325 | 8.30 | test/dev | vendor warns about PAN-ID / commissioning problems; not suitable as the first production A/B |
| Koenkk 20250321 | 8.30.01.01 | released for established chips; P10 upstream WIP | updated UART ISR buffer, TX-finished semantics retained, larger routing/device capacities, P10-specific trust-center target |
| SMLIGHT 20260311 | 8.32.00.07 | beta | failing observed build; custom low-level UART/DMA/NPI/FIFO/task/reset changes |

This ladder is why SMLIGHT 20250325 is **not** the preferred midpoint despite its forensic value. Its vendor-documented migration/commissioning risk adds a confounder. The cleaner midpoint is our reproducible TI 8.30 + reviewed Koenkk coordinator-control build.

---

# 4. Source and toolchain reproducibility contract

Before the first build, create an immutable build manifest containing:

- SDK package version;
- SDK archive SHA-256;
- SDK git commit if the package is sourced from the TI GitHub redistribution;
- TI ZNP project path;
- TI Clang exact version and executable SHA-256;
- SysConfig exact version and executable/package hash;
- Python/tool helper versions;
- host OS identity;
- branch commit SHA;
- complete source-tree diff from pristine TI project;
- complete generated SysConfig diff;
- linker command file hash;
- linker map SHA-256;
- ELF/.out SHA-256;
- HEX SHA-256;
- BIN SHA-256 if generated;
- SysConfig generated file hashes;
- build timestamp in UTC;
- build variant ID.

Recommended build IDs:

```
ti830-p10-znp-lab-r0
ti830-p10-znp-prod-r0
ti830-p10-znp-prod-d0
```

Do not identify a firmware by a friendly date string alone.

---

# 5. Control purity: classify every deviation from TI upstream

Every changed line must be assigned exactly one class:

| Class | Allowed in LAB | Allowed in PROD-CONTROL | Allowed in PROD-DIAG |
|---|---:|---:|---:|
| BOARD | yes | yes | yes |
| CAPACITY | no unless needed to compile | yes, measured only | identical to control |
| BUILD-ID | yes | yes | yes |
| DIAGNOSTIC | no | no | yes |
| BEHAVIORAL FIX | no | no | no, until a later fix branch |

If a proposed change cannot be classified, it is blocked.

A machine-readable manifest should eventually list every non-upstream file and classification.

---

# 6. MR4U hardware port: hard pre-flash gate

The TI P10 support removes the need to port Zigbee to P10 from another MCU. The remaining dangerous part is adapting the **TI board definition to the actual SMLIGHT MR4U P10 wiring**.

No image may be flashed until the following are independently established.

## 6.1 Exact silicon/package

Record:

- exact CC2674P10 package on MR4U;
- silicon revision;
- flash/RAM assumptions;
- whether MR4U uses RGZ or another supported package;
- any board-level RF frontend between P10 and antenna.

Do not infer package from the chip family name.

## 6.2 UART / ZNP transport

Establish the P10-side pins and settings for:

- UART RX;
- UART TX;
- optional RTS;
- optional CTS;
- baud rate;
- inversion or level shifting if any;
- ESP32-S3 bridge behavior.

Production currently uses:

```
115200 baud
rtscts=false
```

The control must preserve host-visible ZNP compatibility unless a board fact proves otherwise.

## 6.3 Reset and bootloader/BSL wiring

Document:

- P10 RESET pin path;
- BSL/backdoor entry path;
- MR4U ESP control over RESET/BSL;
- physical recovery path if the application image never starts;
- whether PoE and USB separately keep any bridge component alive;
- exact sequence that guarantees P10 power removal.

A failed TI image must not be capable of stranding the radio without a tested recovery path.

## 6.4 Oscillators / clocks

Verify:

- HF crystal source;
- LF clock source;
- load-capacitance assumptions where relevant;
- whether TI LaunchPad defaults match MR4U.

Clock mismatches are a hard block.

## 6.5 RF / PA / antenna switch

TI provides CC2674P10 RF design metadata including normal and high-PA variants, but that does **not** prove MR4U wiring matches a TI LaunchPad.

Prove:

- MR4U RF switch topology;
- high-PA path selection;
- DIO pins controlling RF/PA switch;
- legal/calibrated power table;
- antenna path;
- board matching network assumptions.

Start production control at a conservative TX power already proven operational on the existing network; do not make RF-power changes part of the ZNP A/B.

Important caution: later TI SDK history includes board-metadata fixes involving CC2674P10 RF antenna switching. This reinforces that RF pin mapping is a hard review item, not boilerplate.

## 6.6 CCFG / boot configuration

Review, field by field:

- bootloader enable;
- BSL backdoor pin/polarity;
- image-valid configuration;
- reset vector / initial stack pointer;
- debug/JTAG policy;
- oscillator configuration;
- flash protection;
- IEEE address source;
- any vendor secondary-IEEE mechanism.

The control must not permanently disable our recovery path.

---

# 7. NVS layout: do not assume vendor compatibility

TI's P10-class reference ZNP SysConfig contains P10-specific internal-NVS placement:

```
regionBase = 0xFD800
regionSize = 0x2800
```

This is a **reference-project fact**, not proof of the current SMLIGHT image's NVS layout.

Therefore:

- do not assume raw SMLIGHT NVRAM survives a TI image;
- do not rely on an in-place firmware swap preserving network state;
- treat coordinator backup restore as the normal transfer mechanism;
- only use raw-NV preservation if layout/schema compatibility is independently proven;
- keep the known-good vendor image and cold backup available for rollback.

Before flashing TI firmware, compare:

1. TI NVS regions;
2. current SMLIGHT NVS usage if independently knowable;
3. CCFG overlap;
4. linker map;
5. flash end addresses.

Any overlap is a hard block.

---

# 8. Capacity design for the production control

## 8.1 Never ship TI defaults blindly to production

TI SysConfig defaults include, among others:

```
Group Table Size   = 16
Routing Table Size = 40
Binding Table Size = 4
```

Generated Z-Stack config also controls:

- `NWK_MAX_DEVICE_LIST`;
- `ZDSECMGR_TC_DEVICE_MAX`;
- `MAX_RTG_ENTRIES`;
- `APS_MAX_GROUPS`;
- `NWK_MAX_BINDING_ENTRIES`;
- other security/address/child/resource limits.

These are not automatically suitable for the production network.

## 8.2 Capacity values must be demand-derived

Use retained private network evidence to calculate:

- number of device records;
- number of TCLK/link-key records;
- direct-child demand;
- group demand;
- binding demand;
- routing demand;
- source-route demand;
- address-manager demand;
- neighbor-table policy target.

Do not infer all resource demands from router count.

The current recovered network is approximately:

```
~101 devices in coordinator backup
~100 link-key records
~60 routers
```

Exact implementation-time counts must be read from the fresh private backup, not copied from this document.

## 8.3 Reuse the existing fail-closed tooling

Use and extend rather than duplicate:

- `deploy/p10_capacity_gate.py`
- `deploy/p10_nv_lengths.py`
- `deploy/p10_firmware_audit.py`
- `deploy/p10_neighbor_capacity.py`

For our own TI build we gain a major advantage over vendor binaries: compiled capacities can be tied to:

```
source config
-> generated header
-> ELF/map
-> exact image SHA-256
```

The build pipeline must emit a sanitized capacity evidence JSON automatically.

## 8.4 Headroom policy

Do not pick giant values just because P10 has RAM.

For each table:

```
configured = measured_current_demand + justified_reserve
```

The reserve policy must be documented before seeing test results.

Candidate policy to evaluate during implementation:

- security/device records: current demand + 25%;
- group/binding tables: current demand + explicit future reserve;
- routing/source-route: evidence-based plus stress reserve;
- neighbor policy: retain the existing repo's conservative >=60+reserve gate unless memory accounting shows a reason to revise it.

Every increment must have a RAM cost in the build manifest.

---

# 9. Three build variants

## 9.1 TI-VANILLA-LAB

Purpose:

- prove toolchain;
- prove P10 boots;
- prove SYS_PING/SYS_VERSION;
- prove UART mapping;
- prove RF can start;
- verify CCFG/BSL/recovery;
- verify generated artifacts and maps.

Rules:

- no production coordinator backup;
- no production network identity;
- no production cutover;
- TI defaults retained except unavoidable board adaptations and build ID.

This image may be tested only on an isolated/spare P10 or during an explicitly isolated bench window.

## 9.2 TI-KOENKK-CONTROL

Purpose: production A/B control that removes SMLIGHT-specific 20260311 low-level changes while retaining known coordinator-stability behavior.

Baseline:

- TI SimpleLink Low Power F2 SDK 8.30.01.01;
- official CC2674P10 ZNP project;
- TI Clang / TI-RTOS7;
- a minimal patch set mechanically derived from Koenkk `Z-Stack_3.x.0_coordinator_20250321`.

The patch set must be reviewed line-by-line and classified. Initial expected coordinator-critical items include:

1. `NVOCMP_RECOVER_FROM_COMPACT_FAILURE`;
2. extended MT/NV/security APIs required by modern backup/restore;
3. NPI UART2 completion semantics using `UART2_EVENT_TX_FINISHED`;
4. UART ISR-buffer change only if present in the exact reviewed 20250321 patch and required by that transport implementation;
5. coordinator MAC/AF buffering and routing parameters only where they are part of the exact known coordinator baseline;
6. measured P10 production-capacity settings;
7. verified MR4U board/RF/UART/CCFG adaptation;
8. unambiguous build fingerprint.

Every imported Koenkk line must be represented in a machine-readable patch manifest:

```
upstream_path
upstream_commit/tag
patch_hunk_hash
classification
why_required
behavioral_effect
keep/drop decision
```

The objective is **not** to copy Koenkk wholesale. It is to make every difference from TI upstream explicit and reproducible.

Forbidden:

- SMLIGHT 20260311 proprietary UART/DMA/FIFO/task optimizations;
- speculative buffer increases not tied to either the reviewed coordinator baseline or measured production demand;
- watchdog auto-restart logic;
- custom queue backpressure;
- custom heap allocator;
- experimental retry/timing changes;
- diagnostics that alter scheduling/timing materially;
- route tuning introduced merely because routing is suspected;
- undocumented source patches.

### Why this is a better control than pure TI

SMLIGHT 20260311 explicitly advertises custom changes in the exact failure path:

- UART abstraction removal;
- P7/P10 RX/TX ring-buffer optimization;
- NPI task-stack optimization;
- DMA/UART priority changes;
- FIFO-threshold changes;
- custom reset handling.

TI-KOENKK-CONTROL removes that downstream layer while keeping a known coordinator-oriented integration baseline. If this control remains stable while 20260311 hangs, suspicion shifts strongly toward SMLIGHT-specific integration or SDK-8.32 interaction. If it also hangs, the common TI/Koenkk coordinator path remains suspect.

## 9.3 TI-KOENKK-DIAG

Must inherit the **same board, Zigbee, capacity, RF, NPI behavior and network configuration** as TI-KOENKK-CONTROL.

Only evidence-producing diagnostic deltas are allowed.

The diag build is deployed only after:

- the release control reproduces the hang; or
- the release control remains stable long enough that a controlled trigger-reproduction campaign is justified.

The first diagnostic targets are now ordered:

1. NPI UART2 TX/RX state, event callbacks, TX-active flag, DMA/FIFO status;
2. NVOCMP compaction begin/end/failure/recovery state;
3. OSAL/RTOS heap and stack watermarks;
4. AF/MAC/ZDO pending resources;
5. route/MTO traffic counters;
6. fault/error-spin/reset breadcrumbs.

---

# 10. A key finding: TI release defaults can hide the crash reason

The TI P10-class ZNP SysConfig inspected during planning has a number of diagnostics disabled:

- `Error.policy = Error_SPIN`;
- `Error.raiseHook = NULL`;
- P10 `Hwi.checkStackFlag = false`;
- `Hwi.enableException = false`;
- BIOS asserts disabled;
- BIOS logs disabled;
- `Task.checkStackFlag = false`;
- `System.abortFxn = System_abortSpin`;
- `System.exitFxn = System_exitSpin`.

The BIOS heap is backed by the OSAL heap through `HeapCallback`.

This matters because a fault/assert/stack failure can plausibly become an externally visible **permanent non-responsive spin** rather than a rich crash report.

Therefore the diagnostic build must explicitly distinguish:

- true deadlock/resource starvation;
- Error_SPIN;
- abort spin;
- hardware exception;
- task/system stack overflow;
- allocation failure;
- watchdog/reset.

---

# 11. Diagnostic-build architecture

Instrumentation must have low observer effect and must not require the host to send commands after the ZNP has already hung.

## 11.1 Tier D0 — low-rate live health record

Collect approximately every 30–60 seconds:

- uptime;
- free OSAL heap;
- minimum observed free heap;
- allocation failure count;
- largest free block if available;
- active/pending AF sends;
- AF confirm failure counters;
- ZDO pending request count;
- MAC resource/buffer failures if exposed;
- task stack high-water marks;
- system/HWI stack watermark;
- MT/ZNP command queue depth if accessible;
- last ZNP command received;
- last ZNP command completed;
- reset reason;
- error/assert counters.

Prefer counters and watermarks over verbose logs.

## 11.2 Host transport for live diagnostics

Candidates, in preferred order:

1. vendor-specific asynchronous MT/AREQ diagnostic frame over the existing ZNP UART;
2. a dedicated debug UART only if MR4U wiring exposes it safely;
3. SWO/JTAG during bench reproduction;
4. no periodic transport, with only persistent breadcrumbs.

The normal ZNP command IDs must remain untouched.

If using AREQ:

- fixed compact binary schema;
- sequence number;
- monotonic uptime;
- CRC inherent in MT framing;
- <=1 frame/minute initially;
- host collector ignores it unless diagnostic mode is enabled.

## 11.3 Tier D1 — crash breadcrumb

Because the observed terminal state cannot answer SYS commands, preserve the last failure state independently.

Candidate persistent record:

```
magic
schema version
boot counter
reset cause
uptime
fault class
PC/LR/SP where available
exception registers
heap free/min
alloc_fail_count
AF pending/fail counters
ZDO pending
last MT cmd
last 16 event codes
CRC
```

Storage preference:

1. retained/noinit RAM if it survives the relevant reset path;
2. fault-only NVS write, never periodic NVS logging;
3. external debug readout on the bench.

Do not create flash wear by writing health samples continuously.

## 11.4 Tier D2 — fault hooks

Diagnostic build candidates:

- custom `Error.raiseHook`;
- custom exception handler;
- enable Hwi exception decode on the bench;
- enable Task/Hwi stack checks;
- record fault context before spin/reset;
- optional watchdog only after first evidence-preserving reproduction.

The first diagnostic reproduction should **not** immediately reboot on a detected stall if doing so would erase the evidence.

---

# 12. Zigbee2MQTT / herdsman compatibility gate

Before any production restore, validate the control image against the exact host stack.

Required ZNP capabilities include at least:

- SYS_PING;
- SYS_VERSION;
- reset behavior expected by herdsman;
- ZDO startup/commissioning calls;
- AF data request / extended request;
- NV read/write APIs used by restore;
- UTIL_GET_DEVICE_INFO;
- permit-join management;
- network identity reads;
- Trust Center/security table operations used by current restore tooling.

Use the exact production Zigbee2MQTT/herdsman versions for the first A/B. Do not update host software simultaneously with firmware.

A protocol transcript from a known-good vendor startup and TI-control startup should be diffed at the command-class level, excluding secret payloads.

---

# 13. Network restore / identity contract

The TI control test must reuse the existing production network, not reform it.

Pre-flash private evidence must include fresh:

- `coordinator_backup.json`;
- `database.db`;
- Zigbee2MQTT config;
- add-on config/options;
- current coordinator IEEE;
- PAN ID;
- extended PAN ID;
- channel;
- group/device counts;
- security-record counts;
- relevant frame-counter metadata;
- exact currently installed vendor image/version evidence;
- rollback image;
- hashes for all artifacts.

Never commit key material.

After TI flash:

1. prove SYS_PING/SYS_VERSION;
2. prove board identity and build fingerprint;
3. restore the retained coordinator backup;
4. verify coordinator IEEE;
5. verify PAN/extPAN/channel;
6. verify security/address-table population;
7. verify counters are sane;
8. start the restored network using the already-proven restored-network procedure.

Known rule from the P10 recovery:

> A correctly restored Z-Stack network must be resumed with the restored-network BDB commissioning path, not treated as a new network formation.

If the standard herdsman restore leaves the radio hanging at the final startup transition, use the existing `p10-zstack-restore-recovery` skill and the proven `APP_CNF_BDB_START_COMMISSIONING(mode=0x00)` recovery logic. Never use formation mode `0x04` to paper over a restore problem.

---

# 14. Flash/cutover safety gate

No TI image enters the production MR4U until all are true:

- [ ] 2024 vendor baseline image/version is captured.
- [ ] Fresh coordinator backup exists.
- [ ] Fresh database/config bundle exists.
- [ ] Backup is parsed successfully offline.
- [ ] Rollback vendor image is locally available and hashed.
- [ ] P10 BSL/recovery path has been tested on this hardware.
- [ ] MR4U board mapping review is complete.
- [ ] CCFG review is complete.
- [ ] linker/NVS overlap check passes.
- [ ] control image exact SHA-256 is recorded.
- [ ] compiled capacity manifest passes.
- [ ] SYS_VERSION/build ID is unambiguous.
- [ ] Zigbee2MQTT is stopped and cannot auto-restart during flashing.
- [ ] only one process owns the serial interface.
- [ ] old/alternate coordinator with copied network identity is physically isolated.
- [ ] rollback procedure has been dry-reviewed.

Any failure is a no-go.

---

# 15. Offline image review before first flash

Automate static checks for every produced image:

- parse Intel HEX;
- confirm allowed flash address range;
- confirm reset vector;
- confirm initial stack pointer in valid RAM;
- decode/inspect CCFG;
- confirm BSL recovery remains possible;
- identify NVS regions;
- verify no segment overlaps NVS/CCFG unexpectedly;
- verify image size;
- verify linker symbols;
- verify capacity symbols/macros against manifest;
- hash all outputs.

Extend `deploy/p10_firmware_audit.py` rather than creating an unrelated parallel validator.

The validator must fail closed on unknown addresses or missing provenance.

---

# 16. Bench acceptance before production network restore

For TI-VANILLA-LAB / isolated control:

1. boot repeatedly 20 times;
2. SYS_PING 20/20;
3. SYS_VERSION 20/20;
4. controlled reset 20/20;
5. physical cold boot 10/10;
6. baud/transport confirmed;
7. BSL recovery confirmed;
8. build fingerprint confirmed;
9. RF starts on an isolated test network;
10. one router + one end device can join in lab, if isolated hardware is available;
11. permit join open/close works;
12. unicast AF command works;
13. ZDO Mgmt_Lqi works;
14. no UART framing errors;
15. no unexpected resets.

Do not use production devices merely to make the lab checklist convenient.

---

# 17. Production smoke acceptance

Immediately after restore to TI-KOENKK-CONTROL:

### Network identity

Must exactly match expected:

- coordinator IEEE;
- PAN;
- extPAN;
- channel;
- device/group database identity.

### Coordinator protocol

- SYS_PING;
- SYS_VERSION;
- coordinator check;
- permit-join closed;
- no repeated SRSP timeouts.

### Representative Zigbee traffic

Use a small deterministic set:

- direct child/router unicast;
- multi-hop router unicast;
- group command;
- one known end-device rejoin/poll path;
- metering report reception;
- button/remote inbound event.

Do not full-network-map immediately.

### Application acceptance

- critical lighting;
- noncritical shutdown group;
- representative dimmer;
- representative PM socket;
- Home Assistant automations dependent on Zigbee.

If identity/security is wrong, rollback immediately rather than re-pairing around the problem.

---

# 18. Soak design

The user is currently testing SMLIGHT 2024. Preserve that run as Baseline A.

For each candidate firmware, record:

```
firmware exact SHA
build manifest SHA
start UTC
cold/warm start
Z2M/herdsman version
network/device count
traffic phase
first AF SRSP failure UTC
first ZDO SRSP failure UTC
first SYS latency anomaly UTC
terminal SYS failure UTC
recovery action required
```

## Stage S0 — settle

30–60 minutes, no artificial testing beyond ordinary household use.

## Stage S1 — normal production

Minimum 24 hours with no synthetic stress.

Low-rate health probe only:

- coordinator check / SYS version equivalent every 5–10 minutes;
- record latency;
- do not use rapid probing.

## Stage S2 — confidence soak

Continue to at least 72 hours or at least 3x the previously observed failure interval, whichever is longer.

## Stage S3 — controlled workload

Only if normal-load classification is inconclusive.

Add one stress class at a time:

1. ordinary unicast sample;
2. bounded group commands;
3. targeted Mgmt_Lqi at low rate;
4. bounded router-scoped permit join;
5. controlled traffic burst.

Never start with a full 100-device network-map sweep.

## Stage S4 — final confidence

A candidate considered production-stable should ultimately survive a 7-day ordinary-use soak with no coordinator-wide SRSP degradation.

---

# 19. Failure detector

Define the failure stages before testing:

### F0 — healthy

No SRSP timeout; normal coordinator-check latency.

### F1 — early warning

Any coordinator-origin `SRSP - AF - dataRequest*` timeout not explained by a transient serial restart.

Capture immediately.

### F2 — management degradation

Any ZDO management SRSP timeout, e.g. Mgmt_Lqi / permit join.

Stop synthetic load.

### F3 — local ZNP degradation

SYS_VERSION/SYS_PING latency abnormal or timeout.

No more device-level troubleshooting.

### F4 — terminal hang

Serial can reopen but SYS_PING does not return SRSP.

Capture all evidence before cold recovery.

This staged classification prevents route failures from being confused with coordinator death.

---

# 20. Equivalent workload requirement

A/B comparison is invalid if the workloads differ materially.

The future workload harness must:

- operate through supported Zigbee2MQTT APIs;
- use fixed named canaries;
- avoid private IDs in committed output;
- produce timestamped JSONL;
- use the same schedule for each firmware;
- rate-limit operations;
- stop at F2/F3;
- never factory-reset a device;
- never form a new production network.

Host CPU, Z2M version, herdsman version and channel remain fixed across the first comparison.

---

# 21. Metrics to capture

## ZNP/transport

- SYS probe latency;
- SRSP timeout count by subsystem: SYS/AF/ZDO/UTIL/APP_CNF;
- serial reopen count;
- ZNP reset count;
- malformed MT frame count if observable.

## Zigbee

- AF send attempts/success/failure;
- ZCL terminal failures;
- route-discovery failures;
- source-route failures;
- permit-join success;
- targeted Mgmt_Lqi success.

## Traffic

- inbound messages/minute;
- outbound commands/minute;
- top talker classes, sanitized;
- group commands/minute;
- metering-report rate.

## Host

- Z2M CPU;
- host CPU/load;
- event-loop stalls if measurable;
- MQTT reconnects;
- add-on restarts.

## Diagnostic-build-only

- heap metrics;
- allocation failures;
- queue/resource high-water;
- stack high-water;
- fault/exception context;
- reset reason.

---

# 22. Rollback

Rollback is considered part of the experiment, not an emergency improvisation.

Sequence:

1. stop Z2M;
2. confirm stopped;
3. capture post-failure evidence;
4. isolate TI image/radio as required;
5. flash exact hashed vendor rollback image;
6. verify SYS_PING/SYS_VERSION;
7. restore coordinator state only if required;
8. verify identity;
9. start Z2M;
10. verify representative traffic;
11. log rollback outcome in #73.

Do not re-pair devices as a normal rollback technique.

---

# 23. Decision table

| 2024 vendor | TI-KOENKK-CONTROL | TI-KOENKK-DIAG | Interpretation |
|---|---|---|---|
| stable | stable | not needed | regression likely in newer vendor lineage; continue longer soak |
| stable | hangs | reproduces/classifies | TI 8.30 reference/common stack path suspect |
| hangs | stable | not needed initially | downstream 2024/vendor config still suspect; compare manifests |
| hangs | hangs | needed | strong common TI stack/workload hypothesis |
| stable | stable under normal, TI hangs under synthetic | diag needed | workload-triggered limit; verify equivalence |
| inconclusive | inconclusive | no | extend observation; do not claim root cause |

---

# 24. Implementation work packages — for the NEXT interaction, not this one

## WP1 — source pinning

- acquire official 8.30.01.01 SDK;
- verify hash;
- verify official P10 ZNP TI-Clang project;
- capture pristine project manifest.

## WP2 — MR4U board-reality extraction

- document actual MR4U P10 pinout;
- compare vendor hardware/firmware evidence;
- produce explicit TI->MR4U mapping table;
- independent review.

## WP3 — build system

- deterministic Python wrapper;
- no PowerShell dependency;
- invoke SysConfig + TI Clang;
- produce build manifest and all hashes;
- fail on dirty/unclassified diff.

## WP4 — capacity compiler

- parse fresh private backup;
- calculate resource demand;
- write SysConfig overrides;
- parse generated headers/map;
- emit hash-bound evidence for `p10_capacity_gate.py`.

## WP5 — static firmware validator

- HEX/CCFG/vector/NVS checks;
- BSL-preservation check;
- version/build-ID check.

## WP6 — LAB release control

- build only after WP1–5;
- isolated smoke;
- no production restore.

## WP7 — production release control

- fresh backup;
- controlled outage;
- flash;
- restore;
- acceptance;
- normal-load soak.

## WP8 — diagnostic variant

- instrumentation design review;
- build only after release-control behavior is known;
- reproduction/capture.

No WP above is authorized by this planning document alone.

---

# 25. Evidence repository layout proposed for implementation

Public/sanitized:

```
docs/ti-znp/
  CONTROL_PLAN.md
  MR4U_PORTING_CHECKLIST.md
  EXPERIMENT_MATRIX.md
  source-manifest.schema.json
  capacity-evidence.schema.json
  run-summary.schema.json

deploy/ti_znp/
  build.py
  audit_image.py
  derive_capacity.py
  compare_manifests.py
  soak_harness.py

tests/ti_znp/
  ...
```

Private/uncommitted:

```
.analienx/sonoff-private/issues/p10/ti-znp/
  sdk/
  toolchain/
  builds/
  maps/
  images/
  coordinator-backups/
  run-logs/
  crash-evidence/
```

Do not put firmware keys, Zigbee keys, IEEE inventories, USB serials, or raw coordinator backups in git.

---

# 26. Open questions that must be answered before implementation

1. Exact MR4U P10 package/revision?
2. Exact MR4U UART RX/TX pins?
3. Does MR4U connect hardware flow-control pins?
4. Exact RESET and BSL pin path?
5. Exact RF/PA switch DIO mapping?
6. Which TI RF design best matches MR4U RF frontend?
7. Exact HF/LF clock implementation?
8. Is there a safe independent debug UART/SWO/JTAG path?
9. Does the ESP32-S3 bridge manipulate reset/boot pins during normal serial open?
10. What NVS layout does the 2024 vendor image use?
11. Which ZNP NV APIs does herdsman 10.9.1 exercise during restore on this build?
12. Exact current production TCLK/device demand at cutover time?
13. Exact address-manager and routing/source-route target capacities?
14. Can a lab/spare MR4U be used for WP6, or must the production unit be reused?
15. What is the observed failure interval of the 2024 SMLIGHT baseline?

No guesses in these fields are acceptable in the production build manifest.

---

# 27. Planning conclusion

The correct next step after the 2024 SMLIGHT soak is **not** to patch Z-Stack.

It is to create a rigorously controlled TI reference experiment where:

```
same P10 silicon
same MR4U hardware
same Zigbee2MQTT/herdsman
same network
same traffic
different firmware provenance
```

The release control tells us *where* the bug lives.

The diagnostic control then tells us *what* the bug is.

Only after those two questions are separated should we create a custom firmware fix.
