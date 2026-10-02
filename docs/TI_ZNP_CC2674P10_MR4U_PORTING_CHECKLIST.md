# mr4u-p10 — TI ZNP Porting and Pre-Flash Checklist

> **Planning artifact only. No flash authorization.**
>
> Companion to `TI_ZNP_CC2674P10_CONTROL_PLAN.md`.
> Tracking: home-assistant-stack#73.

The purpose of this checklist is to prevent a logically correct TI ZNP build from becoming a bad MR4U firmware because of one wrong board assumption.

---

# A. Source provenance

- [ ] Exact SimpleLink F2 SDK release selected.
- [ ] SDK archive SHA-256 recorded.
- [ ] TI GitHub/source commit recorded if applicable.
- [ ] Official TI P10 ZNP project path proven to exist in that exact SDK.
- [ ] TI Clang exact version pinned.
- [ ] SysConfig exact version pinned.
- [ ] Tool binaries hashed.
- [ ] Pristine source tree hash/manifest captured.
- [ ] License/redistribution requirements reviewed for any committed derived files.
- [ ] No source copied from a different SDK generation without explicit provenance.

Expected first source baseline:

```
SimpleLink Low Power F2 SDK 8.30.01.01
LP_EM_CC2674P10 ZNP
TI-RTOS7
TI Clang
```

---

# B. Physical MR4U P10 identity

## B1. Device/package

- [ ] Read actual P10 top marking / board BOM / authoritative hardware source.
- [ ] Confirm MCU is CC2674P10.
- [ ] Confirm exact package (e.g. RGZ if applicable).
- [ ] Confirm silicon revision.
- [ ] Confirm flash/RAM geometry.
- [ ] Confirm relevant TI errata for that silicon revision.
- [ ] Record board revision of MR4U.

**STOP if package/revision is inferred only from product marketing.**

## B2. Board power domains

Map:

- [ ] P10 supply rail.
- [ ] ESP32-S3 bridge supply rail.
- [ ] PoE-supplied path.
- [ ] USB-supplied path.
- [ ] whether either input back-powers the other domain.
- [ ] exact method for true P10 cold power removal.
- [ ] minimum safe power-off interval.
- [ ] whether USB D+/D- remains enumerated while P10 is unpowered.
- [ ] whether MR4U MCU/bridge can independently reset P10.

Document the previously proven operational lesson:

> PoE can keep MR4U alive while HA/USB is restarted; host restart is not a cold P10 reset.

---

# C. ZNP UART mapping

Create an authoritative table before editing SysConfig:

| Signal | MR4U P10 pin | ESP32-S3 side | TI project default | Action |
|---|---|---|---|---|
| UART RX | UNKNOWN | UNKNOWN | resolve from pinned project | BLOCKED |
| UART TX | UNKNOWN | UNKNOWN | resolve from pinned project | BLOCKED |
| RTS | UNKNOWN/unused | UNKNOWN | resolve | BLOCKED |
| CTS | UNKNOWN/unused | UNKNOWN | resolve | BLOCKED |
| RESET | UNKNOWN | UNKNOWN | resolve | BLOCKED |
| BSL | UNKNOWN | UNKNOWN | resolve | BLOCKED |

Acceptance:

- [ ] RX/TX physically verified from schematic, vendor source or measured board trace.
- [ ] 115200 baud verified.
- [ ] no parity / expected stop bits verified.
- [ ] `rtscts=false` compatibility verified unless hardware proves flow control.
- [ ] boot emits no bytes that confuse MR4U bridge.
- [ ] serial framing matches ZNP MT protocol.
- [ ] MR4U bridge does not require vendor-specific startup handshake.

Do not “try pins until SYS_PING answers” on production hardware.

---

# D. Reset / BSL / recovery

Before flashing any TI-derived image:

- [ ] Current SMLIGHT 2024 rollback image available.
- [ ] Rollback image exact SHA-256 recorded.
- [ ] Current SMLIGHT image can be reflashed through a tested path.
- [ ] P10 BSL entry method documented.
- [ ] BSL backdoor configuration identified.
- [ ] RESET control identified.
- [ ] MR4U UI recovery path identified.
- [ ] USB recovery path identified.
- [ ] recovery does not require working Zigbee application firmware.
- [ ] full flash erase recovery is understood.
- [ ] CCFG corruption recovery is understood.
- [ ] a bad vector table can be recovered.
- [ ] a bad UART mapping can be recovered.

Hard rule:

> No first TI flash if the only recovery method depends on the TI ZNP application successfully starting.

---

# E. Clock configuration

Authoritative board facts required:

- [ ] HF crystal frequency.
- [ ] LF crystal / RC oscillator choice.
- [ ] crystal load values where software-configurable.
- [ ] TI CCFG clock source matches MR4U.
- [ ] standby/wakeup clock assumptions match.
- [ ] no LaunchPad-only external clock assumption survives.

Bench measurements where practical:

- [ ] SYS uptime behaves normally.
- [ ] UART baud accuracy stable.
- [ ] RF channel center/operation sane.
- [ ] no repeated oscillator-start failure.

---

# F. RF frontend and antenna switch

This is a **hard gate**.

TI provides P10 RF designs and high-PA configurations. MR4U may not use the same antenna-switch wiring as the TI evaluation board.

Produce a board-specific RF map:

| Function | MR4U DIO / net | TI reference | Required change | Evidence |
|---|---|---|---|---|
| 2.4 GHz PA enable | UNKNOWN | TBD | TBD | TBD |
| LNA enable | UNKNOWN | TBD | TBD | TBD |
| antenna switch A | UNKNOWN | TBD | TBD | TBD |
| antenna switch B | UNKNOWN | TBD | TBD | TBD |
| bias / FEM control | UNKNOWN | TBD | TBD | TBD |

Checklist:

- [ ] determine whether MR4U uses P10 internal high-PA path or external FEM.
- [ ] determine RF switch polarity.
- [ ] verify DIO mux.
- [ ] verify TI `rfDesign` selected.
- [ ] verify PA table is appropriate for hardware.
- [ ] start with conservative power; do not combine a power experiment with the firmware experiment.
- [ ] verify regulatory ceiling.
- [ ] verify channel 11 operation before production restore.
- [ ] confirm no continuous-TX or wrong-path condition.

Important evidence point:

TI SDK history contains CC2674P10 board-metadata / antenna-switch changes in later SDK families. Therefore “official TI board” is not automatically “MR4U-correct board.”

---

# G. CCFG review

Export every generated CCFG field into a review artifact.

Review at minimum:

- [ ] image valid configuration.
- [ ] reset vector.
- [ ] initial stack pointer.
- [ ] BSL enable.
- [ ] BSL backdoor enable.
- [ ] BSL DIO.
- [ ] BSL active level.
- [ ] debug/JTAG access.
- [ ] flash protection.
- [ ] bootloader protection.
- [ ] IEEE address source.
- [ ] alternative/secondary IEEE behavior.
- [ ] HF clock source.
- [ ] LF clock source.
- [ ] DCDC settings.
- [ ] VDDR settings.
- [ ] any customer configuration copied from LaunchPad defaults.

Store a machine-readable diff:

```
TI_REFERENCE_CCFG -> MR4U_CONTROL_CCFG
```

Every changed field requires rationale.

---

# H. Flash and NVS map

Generate and review:

- [ ] linker map.
- [ ] flash segment map.
- [ ] RAM segment map.
- [ ] NVS region(s).
- [ ] CCFG region.
- [ ] vector table.
- [ ] application end address.
- [ ] stack/heap reservation.
- [ ] any noinit/retained diagnostic RAM.

Reference P10-class TI ZNP SysConfig observed in planning uses internal NVS around:

```
base 0xFD800
size 0x2800
```

Do **not** assume current SMLIGHT firmware uses the same layout.

Required checks:

- [ ] no application/NVS overlap.
- [ ] no NVS/CCFG overlap.
- [ ] no diagnostic region overlap.
- [ ] binary does not write beyond flash.
- [ ] full image range accepted by P10 flasher.
- [ ] existing SMLIGHT NVRAM is treated as incompatible until proven otherwise.

Production network state transfer should therefore be backup-driven.

---

# I. Build identity

TI control firmware must be unmistakable.

Expose:

- [ ] human build ID.
- [ ] exact git commit.
- [ ] SDK version.
- [ ] variant `LAB-R0`, `PROD-R0`, or `PROD-D0`.
- [ ] 32-bit ZNP revision chosen so it cannot be mistaken for SMLIGHT 2024/2026.
- [ ] full image SHA in build manifest.

Do not overload an existing SMLIGHT date revision.

Recommended semantic internal label:

```
TI830-MR4U-P10-ZNP-PROD-R0
```

The limited numeric SYS_VERSION revision can be separately mapped in the manifest.

---

# J. Z-Stack capacity review

For production control, list every capacity-affecting setting with:

```
TI default
measured demand
chosen value
reserve
RAM/flash cost
generated symbol
linker/map evidence
```

Required settings include, where applicable:

- [ ] `NWK_MAX_DEVICE_LIST`
- [ ] `ZDSECMGR_TC_DEVICE_MAX`
- [ ] Trust Center link-key/NV allocation
- [ ] address manager entries
- [ ] neighbor entries
- [ ] child entries
- [ ] routing table entries
- [ ] route-request entries
- [ ] source-route entries
- [ ] group table
- [ ] binding table
- [ ] APS duplicate/retry structures where configurable
- [ ] MAC buffers if configurable
- [ ] AF transaction structures if configurable

Known TI defaults observed:

```
groupTableSize   16
routingTableSize 40
bindingTableSize 4
```

These are not production acceptance values.

### Capacity evidence contract

- [ ] Fresh private Z2M inventory captured.
- [ ] Fresh coordinator backup parsed.
- [ ] actual TCLK/link-key demand measured.
- [ ] group demand measured.
- [ ] binding demand measured.
- [ ] direct-child demand measured where available.
- [ ] route/source-route policy documented.
- [ ] generated config parsed.
- [ ] ELF/map proves compiled allocation.
- [ ] exact image hash linked to evidence.
- [ ] `p10_capacity_gate.py` consumes evidence successfully.
- [ ] no capacity value entered manually without source/build proof.

---

# K. Heap / task / queue baseline

Even the non-diagnostic control should emit an offline build report of:

- [ ] total SRAM.
- [ ] statically allocated SRAM.
- [ ] OSAL heap region.
- [ ] task stacks and sizes.
- [ ] interrupt stack.
- [ ] noinit region.
- [ ] free linker RAM margin.

This lets us compare capacity tuning against resource margin without adding runtime instrumentation.

For diagnostic control additionally record:

- [ ] heap statistics API availability.
- [ ] stack high-water APIs.
- [ ] queue counters.
- [ ] exception hook path.
- [ ] fault breadcrumb storage.

---

# L. Preserve release-control semantics

TI-PROD-CONTROL MUST keep TI release behavior for:

- [ ] Error policy.
- [ ] Hwi exception behavior.
- [ ] stack checks.
- [ ] BIOS asserts/logs.
- [ ] normal retry values.
- [ ] route expiry.
- [ ] MAC retry count.
- [ ] NWK retry count.
- [ ] APS retry count.

Unless changing one is strictly necessary for production capacity or MR4U hardware, do not touch it.

This is intentionally uncomfortable: if TI reference spins on an Error, the control should reproduce that before the diagnostic build changes fault handling.

---

# M. Diagnostic delta review

TI-PROD-DIAG must be generated from TI-PROD-CONTROL with a machine-readable diff.

Allowed diagnostic changes:

- [ ] Error raise hook.
- [ ] Hwi exception capture.
- [ ] Task stack checking.
- [ ] Hwi stack checking.
- [ ] reset-cause capture.
- [ ] OSAL heap counters.
- [ ] AF/ZDO resource counters.
- [ ] low-rate diagnostic AREQ.
- [ ] fault-only persistent breadcrumb.

Not initially allowed:

- [ ] changed queue sizes.
- [ ] changed heap size.
- [ ] changed routing.
- [ ] changed retries.
- [ ] changed task priorities.
- [ ] automatic watchdog recovery.

Those would change the bug rather than merely observe it.

---

# N. ZNP protocol compatibility smoke

Before production backup restore:

- [ ] SYS_PING.
- [ ] SYS_VERSION.
- [ ] SYS_RESET behavior.
- [ ] UTIL_GET_DEVICE_INFO.
- [ ] APP_CNF/BDB commands expected by recovery tooling.
- [ ] ZDO startup.
- [ ] ZDO Mgmt_Lqi.
- [ ] ZDO permit join.
- [ ] AF data request.
- [ ] AF extended data request.
- [ ] NV length/read/write operations required by restore.
- [ ] Trust Center table APIs.
- [ ] coordinator backup restore path.
- [ ] expected AREQ indications.

Host side:

- [ ] exact Zigbee2MQTT version pinned.
- [ ] exact herdsman version pinned.
- [ ] no host update during A/B.

---

# O. Production backup gate

Immediately before any production TI flash:

- [ ] new coordinator backup.
- [ ] new database snapshot.
- [ ] new Z2M configuration snapshot.
- [ ] add-on options snapshot.
- [ ] all artifacts hashed.
- [ ] backup parses.
- [ ] expected device count recorded.
- [ ] expected security-record count recorded.
- [ ] group count recorded.
- [ ] coordinator identity recorded privately.
- [ ] network identity recorded privately.
- [ ] current vendor image/version recorded.
- [ ] rollback path reviewed.

Never depend on a two-day-old backup when a fresh backup can be made.

---

# P. Exclusive-owner gate

At flash/restore time:

- [ ] Z2M stopped.
- [ ] Z2M auto-start suppressed if needed.
- [ ] no Python serial process.
- [ ] no browser/device UI process owns ZNP UART.
- [ ] no second coordinator with copied network identity active.
- [ ] source/rollback coordinator physically isolated where required.

---

# Q. First boot gate

After TI image flash, before restore:

- [ ] USB enumerates.
- [ ] correct MR4U interface identified by evidence, not tty number.
- [ ] SYS_PING passes 20 times.
- [ ] SYS_VERSION returns exact TI build ID.
- [ ] no unsolicited boot loop.
- [ ] controlled reset works.
- [ ] cold reset works.
- [ ] BSL recovery still works.
- [ ] CCFG readback/audit matches intended values if readback is supported safely.

If this fails, rollback **before** touching production network state.

---

# R. Restore gate

After backup restore:

- [ ] no new network formation.
- [ ] coordinator IEEE correct.
- [ ] PAN correct.
- [ ] extPAN correct.
- [ ] channel 11.
- [ ] expected security table count.
- [ ] expected address/device state.
- [ ] frame/security counters plausible.
- [ ] BDB resume path is restored-network mode.
- [ ] no `ZDO_STARTUP_FROM_APP` loop.
- [ ] no deletion of backup/database as a workaround.

---

# S. Application acceptance

Representative only; no network-wide stress yet.

- [ ] known direct router.
- [ ] known multi-hop router.
- [ ] known PM socket.
- [ ] known dimmer.
- [ ] known groupcast.
- [ ] known remote/button inbound.
- [ ] one end-device poll/rejoin path.
- [ ] critical Home Assistant automation.
- [ ] noncritical socket shutdown group.

---

# T. Soak preconditions

- [ ] baseline phase ID assigned.
- [ ] health-probe interval fixed.
- [ ] workload script frozen.
- [ ] stop conditions frozen.
- [ ] timestamps UTC.
- [ ] sanitized run-log schema validated.
- [ ] issue #73 run comment template ready.

No tuning after the run starts.

---

# U. Immediate stop conditions

Stop experiment and preserve evidence if:

- [ ] identity mismatch.
- [ ] backup restore mismatch.
- [ ] repeated boot loop.
- [ ] unexpected flash/NVS corruption.
- [ ] first SYS timeout after serial reopen.
- [ ] coordinator-wide SRSP cascade.
- [ ] security table unexpectedly empty.
- [ ] widespread device loss clearly tied to restore.
- [ ] recovery/rollback path uncertain.

---

# V. Review sign-off record

Before implementation, create a review table:

| Area | Evidence location | Reviewer conclusion | Blocking issue |
|---|---|---|---|
| P10 package | | | |
| UART | | | |
| reset/BSL | | | |
| clocks | | | |
| RF/PA | | | |
| CCFG | | | |
| NVS/linker | | | |
| capacity | | | |
| ZNP protocol | | | |
| backup/rollback | | | |

All rows must be resolved before first production flash.
