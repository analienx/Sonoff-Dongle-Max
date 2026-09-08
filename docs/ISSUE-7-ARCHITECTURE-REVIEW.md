# Issue #7: architecture review and supervisor handoff
Review date: 2026-09-07. Status: prepared for review; not posted to GitHub. No production operations were performed.
Reviewed candidate: repository commit `dca87aa4fb8405ef2ca4f0ef647c60bd46ef3600`, builder `858c34b0eb6f53a2e0c89455ea489ceaa62d58db`, herdsman `0968f979d558874b17396c96b66382d4236bbdcd`, Actions run [33907171158](https://github.com/analienx/Sonoff-Dongle-Max/actions/runs/33907171158). The local GBL, HEX, and ELF hashes were independently checked against the downloaded build manifest: all six match.
Evidence labels used below: **confirmed** means inspected source or actual ELF contents; **expected** means a conclusion from startup code without live readback; **reported** means retained investigation evidence; **unknown** means the review could not establish the value. These distinctions matter: successful compilation, a manifest value, an ELF initializer, and a running NCP configuration are different evidence.
## 1. Executive verdict
**SHIP P009 BUT FIX BLOCKERS FIRST.**
The three firmware changes are defensible. Actual binary inspection confirms RX512, BTT64, and KEY12. They have a small static cost and preserve the same linker heap reservation. No evidence requires replacing the basic MG24 architecture, increasing every table, or moving to MG26.
The deployment and acceptance machinery is not yet strong enough to justify its claims. Several checks can accept stale evidence, continue after a stop condition, or report success from incomplete execution. Those are release blockers for the current executor contract. They are not evidence that the firmware binary itself is bad.
The principal technical conclusions are:
1. Broadcast admission remains the strongest failure hypothesis, but BTT exhaustion has not been proved for each retained BUSY event. Threshold rejection, competing stack work, and shared buffer pressure remain credible.
2. Stock herdsman does not lower BTT64 or KEY12. It does attempt to set the effective maximum direct children to 32 by default. This corrects the documentation but does not justify increasing the live child limit.
3. The multicast membership table is more relevant than the current prose admits: herdsman registers application groups dynamically and consumes three fixed entries.
4. The actual P009 static `.bss` delta is **704 bytes**, not 320. Both images reserve **229,896 bytes** for the memory manager. That reservation is not a measurement of free Zigbee packet memory.
5. The next firmware architecture should add a small, read-only identity extension and, if useful, bounded health snapshots. It should continue to operate with stock Z2M without requiring those diagnostics.
6. The first improvement to implement is trustworthy acceptance and evidence collection. XNCP, watchdog changes, group-capacity changes, and transport experiments should be separately identifiable candidates.
The prepared review follows the deliverable structure in [issue #7](https://github.com/analienx/Sonoff-Dongle-Max/issues/7). Implementation and deployment remain separate subsequent work.
## 2. Assumptions challenged
| Assumption | Verdict | Evidence | Consequence |
|---|---|---|---|
| BUSY proves the broadcast table is full | Too strong | Group/broadcast paths propagate an NCP send status; no event-aligned occupancy or counter proof was retained | Keep BTT pressure as the leading hypothesis; identify the actual admission condition |
| Clean hourly ASH counters prove transport cannot contribute | Too strong | Hourly sampling loses timing; queueing latency can occur without framing/CRC errors | Keep transport as a secondary branch, especially callback backlog |
| BTT64 means 64 locally originated broadcasts are available | Unproved | A separate new-entry threshold governs local admission | Read threshold and table size together |
| Stock herdsman overwrites BTT64 or KEY12 downward | Not found in pinned startup code | No such startup writes; KEY table is queried in key operations | Do not introduce a policy overlay merely to defend against an absent override |
| The running child limit is 64 | Usually false under defaults | ELF initializes 64; herdsman attempts 32 unless stack_config.json changes it | Document compile capacity and runtime policy separately |
| Child count means total network size | False | Direct end-device children are one resource among many | A network of 104 devices does not need 104 coordinator child slots |
| 21 groups cannot pressure a 26-entry multicast table | Misleading | Three fixed memberships plus dynamic application-group registration | Inspect actual distinct memberships and registration failures |
| RX512 is still only a P010 proposal | Stale | Approved ELF contains a 512-byte rx_buffer_vcom | Correct TUNING-RESEARCH.md and cross-issue narrative |
| Broadcast entries cost 6 bytes here | False for these linked arrays | Stock table 240 bytes / 30; P009 512 bytes / 64 | Budget 8 bytes per linked entry for this build |
| Firmware consumes about 289 KB of SRAM | Invalid reading of aggregate size output | Aggregate NOBITS accounting includes heap and a 32 KB .nvm section outside SRAM | Use allocated section addresses and physical regions |
| “Effective SLCP” proves the compiled profile | False | Workflow copies project inputs, then verifier parses those copies | Retain resolved generated configuration and validate ELF evidence |
| Confirming a GBL hash proves what is running | False | confirm-flash records human acknowledgment | Distinguish artifact integrity, operational fingerprint, and firmware identity |
| Postflash identity is a current NCP read | False | safe_identity_from_running_z2m reads coordinator_backup.json inside a container | Freshness and current-session hardware identity must be established |
| P010 diagnostics do not change timing | False | Each BUSY awaits an additional EZSP read before raising the original error | Bound diagnostic delay and rate; measure its timing effect |
| Nabu Casa extensions can be copied as a single harmless package | False | Common extension includes behavior-changing capabilities and extra state | Select only needed functionality |
| A five-trial pass proves durable reliability | False | It is a bounded operational screen | Do not relabel smoke acceptance as root-cause proof or reliability certification |
Source anchors: [pinned herdsman adapter][host], [fixed endpoints][endpoints], [EZSP wrapper][ezsp], [current verifier][verify], [workflow][workflow], [deployment helpers][common], [P010 patch][p010], and [existing research document][research]. ELF measurements are detailed in section 7.
### Failure paths and what BUSY actually establishes
**ZCL group:** Z2M invokes `sendZclFrameToGroup()`; the adapter enters its queue, builds an APS group frame, and calls `ezsp.send(MULTICAST, ...)`. The wrapper calls `ezspSendMulticast()`. A successful serial/EZSP transaction returns the NCP's stack send status. Non-OK status is thrown immediately; this path has no host retry loop. On success it waits 500 ms, but the queue can run multiple unrelated operations concurrently, so that wait is not a global broadcast rate limiter. [Adapter][host], [wrapper][ezsp].
**ZCL broadcast:** `sendZclFrameToAll()` uses the same queue and `ezsp.send(BROADCAST, ...)`, then `ezspSendBroadcast()`. Again, initial admission status is distinct from the later message-sent callback and from actual delivery to every target.
**Permit Join All:** the adapter first configures joining locally, calls `ezspPermitJoining(seconds)`, and then sends the ZDO permit request through `sendZdo()` to `BroadcastAddress.DEFAULT`. In this exact version DEFAULT is **0xFFFC**, routers and coordinator. It is not 0xFFFF. Coordinator-only permit omits that broadcast. The overall host commissioning workflow can also include Green Power traffic; correlate each actual frame rather than treating the MQTT request as one radio transmission. [Adapter][host], [broadcast enum][addresses].
**Important distinction:** the unicast path explicitly maps host `EzspStatus.NO_TX_SPACE` to `SLStatus.BUSY` before its retry handling. The examined group and broadcast wrappers do not perform that translation. An exact `[ZCL GROUP ...] status=BUSY` therefore gives stronger evidence of a returned NCP status than an arbitrary log line containing BUSY. Preserve the originating symbol, send type, destination, EZSP transaction status, and stack status.
At the NCP boundary, admission touches NWK broadcast state, shared packet buffers, queue limits, retry scheduling, and radio work. The exact private stack branch returning BUSY was not established by source-level inspection here. Symbol names and documentation do not justify inventing that branch.
### Competing hypotheses and the smallest discriminator
| Hypothesis | Support / limitation | One useful observation |
|---|---|---|
| BTT capacity or local threshold | Same broadcast-dependent failures across group and permit paths; clean local-only control | Read BTT and threshold, then compare native counter 33 immediately before/after one naturally failing send |
| Shared packet-buffer exhaustion | Multiple message classes and callbacks share memory; large general heap does not prove large free packet heap | Allocation-failure counter 27 delta plus packet-pool free/minimum bytes in the same epoch |
| PHY-to-MAC queue limit | Incoming processing bursts can consume capacity | Counter 29 delta, receive rate, and queue/callback delay |
| NWK retry congestion | Retrying frames occupy resources; routing churn can contribute | Counter 31 delta and contemporaneous retry/send counts |
| RF contention indirectly prolongs resource occupancy | Clean ASH does not test RF; CCA failure may keep work pending | Counter 32 delta aligned with admission failure and normal traffic |
| Host/EZSP callback backlog | Command queue and serial command path are different schedulers | Command issue/response/callback timestamps and host transport TX-space events |
| UART/ESP buffering | RX128 provides short burst coverage; no hardware flow control configured | NCP ASH counters 18–20, host ASH errors/retransmissions, and actual UART byte rates |
| Concentrator/background routing | Discovery creates internal broadcast work | Route-request/callback timeline around BUSY, without new bulk mesh queries |
| Green Power commissioning work | Permit All may generate more than the local join operation | Per-frame trace separating ZDO permit, GP, and unrelated application traffic |
| SDK defect or unusual stack state | Still possible if capacity signals stay clean | Exact reproduction on an isolated equivalent setup after all observable limits are checked |
A rise in BROADCAST_TABLE_FULL during the window supports pressure, but does not prove that the failed local command caused the increment; a relayed broadcast may have done so. Conversely, a zero delta does not eliminate local threshold rejection unless the exact SDK path is known to increment that counter.
## 3. Effective configuration matrix
The matrix describes the approved P009 image with pinned **stock** herdsman. “Expected” assumes the relevant startup write succeeds and no additional integration changes it. The actual production stack_config.json was not read during this review.
| Resource | Build/ELF evidence | Herdsman startup behavior | Expected effective value | Verification today / issue |
|---|---|---|---|---|
| BROADCAST_TABLE_SIZE | ELF initializer 64; backing array 512 B | No stock write | 64 | ELF confirmed; stock startup has no universal readback |
| NEW_BROADCAST_ENTRY_THRESHOLD | Runtime variable exists in BSS; initialization outcome unresolved | No stock write | Unknown | Highest-priority missing admission readback; do not equate BSS zero with post-init zero |
| KEY_TABLE_SIZE | Read-only ELF constant 12 | No startup write; read in key operations | 12 | Binary confirmed; not universally checked by deployment |
| MAX_END_DEVICE_CHILDREN | ELF initializer 64 | Writes stackConfig value; default 32 | 32 if accepted, else firmware fallback | Setter logs rejection and continues; no mandatory readback |
| Physical child table capacity | ELF child-table initializer 64; 1,560 B array | Host child policy is separate | Compiled capacity 64; permitted direct children may be 32 | Do not claim host setting frees the static array |
| ROUTE_TABLE_SIZE | ELF initializer 254; linked array 2,040 B | No stock size write | 254 | No general startup readback |
| SOURCE_ROUTE_TABLE_SIZE | ELF initializer 254; backing array 1,016 B | No size write; concentrator mode is configured | 254 plus host routing policy | Capacity and discovery behavior are separate |
| ADDRESS_TABLE_SIZE | ELF initializer 128 | No size write | 128 | Trust-center cache is additional; not a simple total-device limit |
| TRUST_CENTER_ADDRESS_CACHE_SIZE | Build default not independently resolved | Writes 2 | 2 if accepted | Relevant to overlapping authentication, not BTT size |
| APS_UNICAST_MESSAGE_COUNT | Source profile 128 | No stock write | 128 expected | Not independently decoded from linked initializer here |
| DISCOVERY_TABLE_SIZE | Source define 16 | No stock write | 16 expected | Generated/compiler definition still needs archival verification |
| MULTICAST_TABLE_SIZE | ELF initializer 26; array 104 B | Does not resize; adds memberships | 26 slots | Actual usage can approach 24 with 21 distinct application groups |
| BINDING_TABLE_SIZE | Source profile 32 | No size write | 32 expected | Binding contents/security policy are separate |
| APS duplicate rejection entries | Profile 64; linked array 256 B | No stock tuning write found | 64 expected | Existing array is 4 B per entry; keep unchanged |
| RETRY_QUEUE_SIZE | ELF initializer 16; array 320 B | No stock write | 16 | Optional P009 overlay sets and reads 16 |
| Packet-buffer heap | Profile HUGE; memory manager region 229,896 B | No supported stock heap resize | Actual acquired packet pool unknown | General allocator reservation is not packet heap free space |
| SUPPORTED_NETWORKS | Resolved build default not established | Writes 1 | 1 if accepted | Optional overlay verifies; disabling logical network use does not prove static buffers were removed |
| MTORR_FLOW_CONTROL | Exact SDK initialization unresolved | No direct stock config write | Unknown | Concentrator configuration does not itself prove this flag's value |
| SEND_MULTICASTS_TO_SLEEPY_ADDRESS | Runtime object in BSS | No stock config write | SDK default expected 0; verify | Optional overlay sets/reads 0; preserve current multicast semantics |
| Store-and-forward | Research/profile prose says 5 | No verified corresponding startup write | Unknown at binary/runtime level | Treat 5 as unverified, not an audited linked value |
| Concentrator mode | Runtime state | High RAM; min 5 s, max 60 s; route error 3, delivery failure 1, max hops 0 by default | Those defaults or validated stack_config.json | Preserve prior established policy; do not repeat failed 1-to-3 experiment |
| MAX_HOPS | SDK default/source not central here | Writes 30 | 30 if accepted | Separate from concentrator max-hops parameter 0 |
| Indirect transmission timeout | Default not needed to infer host policy | Writes 7,680 ms | 7,680 ms if accepted | Does not define every retry timeout in SDK 9.1.1 |
| UART RX | Actual rx_buffer_vcom is 512 B | No host resize | 512 B | Verified in ELF |
| UART transport | SONOFF manifest EUSART1, 115200, no HW flow | Host serial/TCP settings must match | Depends on selected physical path | Manifest does not prove ESP bridge wiring or buffering |
Sources: [pinned adapter][host], [pinned builder project][builder], [EZSP configuration semantics][config]. Values explicitly labelled ELF were independently read from the downloaded binaries, not inferred from the input manifest.
The optional P009 overlay sets/readbacks BTT64, threshold 48, retry 16, MTORR1, networks 1, and sleepy-multicast 0. It does not verify KEY12 or the child limit. It also changes more than observability: threshold 48 reserves 16 entries against locally originated work. That may protect relays, but it can reduce local admission compared with a less restrictive baseline. Its effect depends on the original threshold. [Policy patch][policy].
Do not deploy this six-value policy merely because the firmware has BTT64. First establish the effective baseline. If only one value is wrong, prefer one explicit correction over a bundled policy change.
## 4. Ranked improvement candidates
Layers: A = immutable firmware; B = runtime EZSP configuration; C = XNCP identity/diagnostics; D = host/deployment software; E = HA traffic policy; F = board/ESP transport. S denotes a blocker or substantial improvement, A a strong improvement, B useful hardening, C deferred low value.
### S1 — Make acceptance enforce its own stop and freshness rules
- **Layer / targets:** D; `safe_identity_from_running_z2m`, `cmd_postflash`, `cmd_acceptance`, and both acceptance scripts.
- **Current:** backup-file identity, potentially old version lines, multiple trials after BUSY, and an uncorrelated final close.
- **Proposal:** require evidence from the current adapter session, bind owner checks to the intended add-on/transport, stop new stimuli on the first hard failure, obtain fresh closure evidence, and persist partial results before cleanup.
- **Benefit / confidence:** prevents invalid acceptance and avoids further traffic after a stop condition; high confidence from source.
- **Cost:** zero NCP SRAM/flash; modest host code and retained evidence.
- **Compatibility / risk:** no radio behavior change during normal operation; changes executor failure handling. Closure cleanup must finish or be explicitly marked unknown before the host is stopped.
- **Minimum validation:** offline mocked MQTT/remote responses covering first-trial BUSY, stale bridge state, reconnect, malformed JSON, incomplete canary, failed close, old backup, and changed owner. No live test required to expose these failures.
- **Source:** [common helpers][common], [acceptance coordinator][accept], [permit script][permit], [active script][active], [deployment state machine][deploy].
### S2 — Verify the actual binary and current configuration contract
- **Layer / targets:** A/B/D; build verifier, generated headers, ELF symbols, startup readbacks.
- **Current:** the verifier checks source inputs and filenames; runtime reads are incomplete and optional.
- **Proposal:** retain source inputs under an honest name, archive resolved headers/compiler definitions/component catalog, validate key initializers and backing allocations, and capture actual BTT/threshold/KEY/child values through the transport owner.
- **Benefit / confidence:** detects ineffective generation and runtime overrides; high.
- **Cost:** zero firmware bytes if using existing EZSP read commands and ELF inspection; host integration effort.
- **Compatibility:** readback requires a supported owner-side path. A second standalone serial client is not an acceptable way to preserve “stock operation.”
- **Minimum validation:** a deliberately mismatched input-versus-ELF fixture must fail; rejected startup writes must appear in the result rather than becoming assumed values.
- **Source:** [workflow][workflow], [verifier][verify], [host initialization][host].
### A1 — Retain BTT64; determine threshold before further capacity changes
- **Layer / symbols:** A/B; `SL_ZIGBEE_BROADCAST_TABLE_SIZE`, `sli_zigbee_broadcast_table_data`, `NEW_BROADCAST_ENTRY_THRESHOLD`.
- **Current / proposed:** keep 64. Do not automatically apply threshold 48 or enlarge above 64.
- **Benefit / confidence:** more broadcast state is plausible help for this failure signature; medium causal confidence, high confidence in the actual capacity increase.
- **Cost:** backing array grows 240 to 512 B, **+272 B SRAM**. Total matched binary change is larger because RX and key metadata also change. Isolated flash cost for BTT alone was not measured.
- **Compatibility:** neighbors retain their own limits. A larger coordinator table does not increase network airtime or every router's broadcast capacity.
- **Minimum validation:** one bounded failure window with table/threshold readback and event-aligned counters. Successful screening supports use but does not isolate the causal contribution of this one change.
- **Source:** ELF measurements; [configuration semantics][config]; [Nabu manifest][nabu].
### A2 — Firmware identity through minimal XNCP
- **Layer / APIs:** C; `zigbee_xncp`, `sl_zigbee_af_xncp_incoming_custom_frame_cb`, host `ezspGetXncpInfo()` and `ezspCustomFrame()`.
- **Current:** generic stack version plus manual artifact acknowledgment; linked image contains XNCP stubs.
- **Proposal:** immutable project/board/schema/build/profile identity, returned only on request. Keep the normal EZSP interface unchanged.
- **Benefit / confidence:** distinguishes firmware revisions that all report EmberZNet 9.1.1; high.
- **Cost:** engineering allowance **2–8 KiB flash**, **0–256 B persistent RAM**, with bounded scratch/stack usage to be measured. These are planning bounds, not measured link deltas.
- **Compatibility:** new image/release identity required. Existing hosts may ignore XNCP; a host-side reader is still needed to display its answer.
- **Minimum validation:** correct identity, unknown-command response, short/oversized input rejection, bounded response length, and stock-host startup on a spare coordinator.
- **Source:** [custom NCP guide][custom], [pinned EZSP wrapper][ezsp], [Nabu XNCP core][xncp].
### A3 — Use existing counters with timing and reset semantics
- **Layer / APIs:** C/D; `ezspReadCounters()`, `sl_zigbee_read_counters()`, existing counter storage.
- **Current:** hourly read-and-clear plus optional synchronous BUSY snapshots.
- **Proposal:** record a baseline and one failure snapshot with exact send context, read latency, adapter session, and last known clearing event. Coalesce repeated diagnostic requests. A failed or slow diagnostic must preserve the original send error and have a bounded completion path.
- **Benefit / confidence:** separates several pressure mechanisms without changing table values; high diagnostic value.
- **Cost:** zero extra NCP memory using standard EZSP. Optional custom aggregation has separately measured code/scratch cost. A native 42-counter vector is 84 payload bytes.
- **Compatibility:** instrumentation changes host timing even when read-only. Do not use a naive timeout race that leaves a serial transaction active behind the next request.
- **Minimum validation:** counter read fails, times out, or crosses hourly clear; original failure remains intact and observations are labelled valid/invalid.
- **Source:** [P010 patch][p010], [EZSP counters][ezsp], [stack API][stackinfo].
### B1 — Preserve RX512 and measure the bidirectional transport
- **Layer / symbol:** A/F; `SL_IOSTREAM_EUSART_VCOM_RX_BUFFER_SIZE`.
- **Current / proposed:** keep 512 and the existing 115200/no-HW-flow board contract.
- **Benefit / confidence:** additional short-burst tolerance; high confidence in capacity, low evidence that it cures the reported BUSY.
- **Cost:** **+384 B static RAM** relative to 128. No separate RX-only flash measurement.
- **Compatibility:** low for this array change; it does not fix ESP-side buffering, sustained overload, or NCP-to-host callback pressure.
- **Minimum validation:** inspect generated UART driver configuration; on a spare system compare byte rate, callback delay, ASH errors, and induced bounded host bursts.
- **Source:** actual `rx_buffer_vcom` symbol and [SONOFF manifest][sonoffmanifest].
### B2 — Make multicast membership observable; increase only if needed
- **Layer / symbols:** A/D; `SL_ZIGBEE_MULTICAST_TABLE_SIZE`, `onMessageSent()`, `ezspSetMulticastTableEntry()`.
- **Current:**26 slots;3 fixed memberships; application groups added after successful multicast.
- **Proposal:** first expose occupancy, distinct registered IDs, and failed registrations. If the verified requirement is above the available margin, a separate **26-to-32** capacity variant is a reasonable small step.
- **Benefit / confidence:** helps receiving group-based state updates; high confidence in host behavior, conditional need for more capacity.
- **Cost:** current backing array 104 B;6 additional entries imply **24 B raw table storage**, plus alignment and any auxiliary effects measured after linking. Flash delta unknown.
- **Compatibility:** this is a reception/membership change. It does not directly increase multicast send admission.
- **Minimum validation:** use normal existing memberships; test the capacity boundary on a spare network and verify group-state passthrough. Do not create extra production groups just to fill the table.
- **Source:** [fixed endpoints][endpoints], [host membership registration][host], actual linked array.
### B3 — Audit watchdog behavior, then deliberately enable recovery if absent
- **Layer / component:** A/F; `legacy_hal_wdog`, `SL_LEGACY_HAL_DISABLE_WATCHDOG`, platform reset-cause facility.
- **Current:** pinned project does not explicitly select Nabu's watchdog setup; ELF has reset strings and default IRQ names, which do not prove an enabled watchdog.
- **Proposal:** establish generated component selection, timeout, and feed path. If absent, evaluate the pinned SDK watchdog with the explicit enable setting 0 in an isolated variant.
- **Benefit / confidence:** recovery from genuine firmware hangs; medium, because no retained hang is the primary symptom.
- **Cost:** unknown until compiled; impose a small measured budget instead of claiming zero bytes.
- **Compatibility:** false resets can be worse than the original problem. Feed from demonstrated main-loop progress, not an interrupt that continues during a deadlock.
- **Minimum validation:** isolated deliberate hang recovers once, retains network state, reports reset reason, and does not enter a restart loop during normal NVM work.
- **Source:** [Nabu base project][nabubase], [pinned base project][builder].
### B4 — Scoped HA pacing and duplicate coalescing
- **Layer:** E, with D only if a reusable upstream host policy is justified.
- **Current:**500 ms post-send waits do not serialize all concurrent operations.
- **Proposal:** for confirmed coordinator-originated bulk scenes, use a bounded per-network group/broadcast lane. The repository's 1 s spacing, or 2 s for large independent shutdown groups, is an initial operating policy rather than a Zigbee guarantee. Deduplicate identical pending work where command semantics permit.
- **Benefit / confidence:** reduces avoidable bursts; medium until actual command traces show burst overlap.
- **Cost:** zero NCP bytes; a small bounded host queue.
- **Compatibility:** do not pace direct device bindings, reorder safety-relevant OFF commands, or silently deduplicate toggles/increments as though they were idempotent state assignments.
- **Minimum validation:** replay recorded application command timings offline and check order, maximum delay, and queue bound.
- **Source:** [existing pacing proposal][research], [adapter queue behavior][host].
### B5 — Reproducible build inputs and a generated capability manifest
- **Layer:** A/build tooling.
- **Current:** exact builder/source commits, but Docker pulls moving base images and uv:latest, and tool evidence does not include the actual compiler version. Source revision alone is not a reproducible environment.
- **Proposal:** preserve the exact successful image or publish it by digest; record compiler/SLC/SDK package versions and hashes, flags, generated sources, ELF, and release artifact hashes. Derive runtime identity from canonical inputs, not wall-clock time.
- **Benefit / confidence:** supports reproducible comparison and meaningful future deltas; high.
- **Cost:** zero NCP bytes without embedded identity; CI storage and a small report.
- **Compatibility:** do not refactor the builder architecture as a prerequisite to evaluating this already-built image.
- **Minimum validation:** two clean builds in the same frozen environment produce identical normalized firmware content or a documented, isolated source of nondeterminism.
- **Source:** [Dockerfile][docker], [workflow][workflow].
### C / REJECT — Broad tuning without a matching failure signature
Reject BTT254, blanket BUSY retries, enlarged retry queues, raising every resource, copying ZBT-2 transport pins/baud, unsolicited raw packet streaming, and a security-storage migration bundled into P009. Defer manual source-route restore, blanket receive-all-groups behavior, high-water instrumentation of private stack structures, and persistent per-event NVM counters until a specific requirement and cost are established.
## 5. Top five changes I would make
1. **Repair the executor contract before another deployment.** Fix fresh identity, current-startup evidence, fail-fast trial control, complete canary accounting, fresh closure confirmation, and durable failure evidence. This has a stronger immediate justification than adding another firmware resource.
2. **Replace the source-only proof with binary and runtime evidence.** Archive resolved configuration and component selection; assert RX512/BTT64/KEY12 in the image. Capture BTT, threshold, key-table size, and child limit from the actual adapter session.
3. **Keep the current three-value firmware profile for the first bounded evaluation.** Use BTT64, KEY12, RX512. Preserve current routing/RF/transport behavior. Correct the documentation's stale memory and child-limit claims.
4. **Make a diagnostic failure interpretable.** Add an owner-side, bounded read-only counter snapshot path with native error context and clearing/reset awareness. Keep the P009 policy overlay distinct from the P010 diagnostic overlay.
5. **Prepare an identity-only XNCP follow-up.** Give it a new immutable build/profile identity and a measured memory report. Add health fields only where the SDK has a supported source and the owner can consume them.
I would not make XNCP a prerequisite for testing the existing binary if the supervisor explicitly accepts manual flashing evidence plus current operational readbacks. I would make a trustworthy identity/acceptance mechanism a prerequisite for automated claims of success.
## 6. XNCP design recommendation
### Minimum useful identity design
Select Silicon Labs' `zigbee_xncp` component and implement a bounded handler using `sl_zigbee_af_xncp_incoming_custom_frame_cb`. The host already implements `ezspGetXncpInfo()` and `ezspCustomFrame()`. The precise information callback/configuration declarations should be taken from the resolved 2026.6.1 component; do not transplant a 6.x callback signature. [Custom NCP guide][custom], [host API][ezsp].
Expose:
| Field | Purpose |
|---|---|
| Protocol schema version | Parser compatibility |
| Project identifier | Distinguishes this community firmware from official SONOFF/Nabu builds |
| Board target identifier | SONOFF Dongle-M / EFR32MG24A420F1536IM48 |
| Firmware profile identifier | P009-compatible base or a new named follow-up |
| Full source commit or deterministic build identifier | Exact source provenance |
| Canonical build-profile hash | Covers resolved resources, transport, component selection, and relevant build inputs |
| Stack/EZSP versions | Cross-check against standard version response |
| Capability bitmap | Lists only implemented commands and supported health fields |
Do not claim an assigned manufacturer ID owned by another organization. Use a documented development/private convention permitted by the SDK, or obtain the project's proper allocation. Keep that field separate from the coordinator manufacturer code used for device-specific behavior.
Use fixed-width fields or bounded lengths, little-endian encoding, explicit schema/version checks, and a conservative maximum response size below the host's 119-byte custom payload limit. A full commit and profile hash can fit in a compact binary identity page; use a second bounded page for long descriptive strings. Do not build arbitrary memory reads, writes, resets, route edits, or token access into this identity command.
Place immutable metadata in const flash storage and verify it survives LTO. Derive the build identifier from canonical build inputs. A manifest can map that identifier to the final GBL SHA256. Do not attempt to embed the hash of the entire final binary inside itself without a precisely defined exclusion/normalization scheme.
**Identification is not cryptographic attestation.** An ordinary custom frame reports what the running program says about itself. Authenticated firmware provenance additionally requires an appropriate signed-image/secure-boot chain and verification policy. That is separate work, not a reason to add crypto protocol complexity to P009.
### Optional health snapshot
First reuse standard `ezspReadCounters()`. If a compact NCP-side snapshot also needs reset reason, uptime, or supported pool metrics, add one read-only health command. The native SDK API `sl_zigbee_read_counters(uint16_t*, uint8_t)` avoids clearing counters. [Stack counter API][stackinfo].
A possible bounded v1 layout is a 16-byte header plus 42 uint16 counters =100 bytes. The header can contain schema, command, reset classification, snapshot sequence, uptime, and validity flags. This is a proposed wire contract, not existing implementation. If using 32-bit uptime in milliseconds, document wrap and combine it with the host's session/reset history.
For additional metrics, use a second versioned page. Each field must distinguish:
- available/current value;
- supported but not yet initialized;
- unsupported;
- stale or invalid following reset/clear.
Do not invent occupancy from configured capacity. A private symbol such as `sli_zigbee_broadcast_table_data` is useful for a pinned binary audit but is not automatically a supported public telemetry API. Prefer supported getters. If none exists, leave the field unavailable until a small pinned hook is reviewed and measured.
Read counters without resetting them. Stock herdsman still clears its native counters hourly, so a custom frame cannot honestly advertise lifetime totals by returning the same underlying array. Either report those native semantics or introduce a separately justified accumulator.42 uint32 lifetime counters alone need 168 bytes and more than one custom response page; this is unnecessary for identity v1.
Counter threshold callbacks are optional diagnostics, not evidence of arithmetic rollover. The pinned host describes the callback as a threshold event. Determine the actual SDK saturation/reset behavior before doing modulo arithmetic, and avoid computing deltas across a known clear or reset.
Capture reset/fault cause early enough that initialization does not erase it, using the exact SDK/platform facilities. Separate chip reset cause from host disconnect, ASH ACK timeout, and Zigbee network-down events: these are not interchangeable reset categories. Retain a small RAM crash record if supported. Avoid new NVM writes on each BUSY, counter update, or reboot.
### Compatibility and implementation boundary
A normal stock host can ignore the extension and run Zigbee normally. That does not mean it will expose the custom identity automatically in Z2M's UI or MQTT API. Reading it requires integration through the existing owner, or a scheduled exclusive diagnostic session whose reset/ownership effects are acknowledged. Never open a second serial/TCP client against the running adapter.
Do not import all of Nabu's common extension merely to obtain a build string. Its feature set includes manual source-route operations and altered multicast reception. Reuse the SDK component and only the bounded identity pattern needed here. Preserve licenses for any reused source. [Nabu XNCP core][xncp], [Nabu manifest][nabu].
Budget identity v1 initially at 2–8 KiB incremental flash and 0–256 B persistent SRAM, with measured stack use. This range is an engineering planning allowance. The actual result must be accepted from matched ELF/linker evidence. A future identity build must receive a new artifact/hash; the already-approved P009 binary must not be silently relabelled.
## 7. Memory/resource budget
### Direct inspection of the approved binaries
Both ELF files were parsed directly as little-endian ELF32. Their SHA256 values match the build manifest. The table lists actual allocated sections, not the aggregate columns printed by a size utility.
| Section / quantity | Stock | P009 | Delta |
|---|---:|---:|---:|
| .vectors | 368 B | 368 B | 0 |
| .text, excluding separate RAM code | 263,400 B | 263,496 B | +96 B |
| .ARM.exidx | 8 B | 8 B | 0 |
| text_application_ram | 268 B | 268 B | 0 |
| .data in SRAM | 4,600 B | 4,600 B | 0 |
| .copy.table in flash | 12 B | 12 B | 0 |
| .bss proper | 22,284 B | 22,988 B | **+704 B** |
| .stack | 4,096 B | 4,096 B | 0 |
| .noinit | 160 B | 160 B | 0 |
| .bootloader_reset_section | 4 B | 4 B | 0 |
| .memory_manager_heap reservation | **229,896 B** | **229,896 B** | **0** |
| .nvm linker section | 32,768 B | 32,768 B | 0 |
| GBL file | 268,896 B | 268,992 B | +96 B |
The actual part has 256 KiB SRAM and 1,536 KiB flash. [Silicon Labs device specification][part].
Exact SRAM ranges, with ends exclusive:
| Region | Stock | P009 |
|---|---|---|
| Main stack | 0x20000008–0x20001008 | Same |
| .bss | 0x20001008–0x20006714 | 0x20001008–0x200069D4 |
| .noinit | 0x20006714–0x200067B4 | 0x200069D4–0x20006A74 |
| RAM code | 0x200067B4–0x200068C0 | 0x20006A74–0x20006B80 |
| .data | 0x20006C00–0x20007DF8 | Same |
| Memory-manager heap | 0x20007DF8–0x20040000 | Same |
This explains the apparently surprising zero heap loss: P009 consumes 704 bytes of the previous layout gap before .data. The gap after RAM code is 832 bytes in stock and 128 bytes in P009. The layout before the heap ends at 32,248 bytes from SRAM base in both images.
Consequently:
- The linked static objects grew; the heap reservation did not.
- The current 128-byte gap is not a general-purpose runtime allocator.
- A future allocation may cross an alignment boundary and reduce heap by more than its raw object size.
- Do not extrapolate “zero heap cost” to the next firmware feature.
The published 289,208-byte stock aggregate “bss” is explainable by summing multiple NOBITS sections, including the 32,768-byte .nvm section and the heap reservation. The .nvm section is placed at 0xFFE88000 in the ELF, outside SRAM; it is not 32 KiB of RAM consumption. Its placeholder/special linker address also must not be used as a literal flash operation target. The approved RX512 P009 aggregate from the same sections is 289,912 bytes. The repository's 289,528 figure is stale and corresponds to a smaller static delta.
### Resource objects that explain the change
| Linked object | Stock | P009 | Meaning |
|---|---:|---:|---|
| rx_buffer_vcom | 128 B | 512 B | +384 B UART receive storage |
| sli_zigbee_broadcast_table_data | 240 B | 512 B | +272 B;8 B per entry |
| sli_zigbee_incoming_aps_frame_counters | 8 B | 52 B | +44 B associated with expanded key-table metadata |
| Residual alignment/layout in .bss | — | — | +4 B |
| Total .bss change | — | — | **384 + 272 + 44 + 4 = 704 B** |
Other measured P009 arrays, retained from stock:
| Object | Bytes |
|---|---:|
| sli_zigbee_retry_queue | 320 |
| sli_zigbee_multicast_table | 104 |
| sli_zigbee_source_route_table_data | 1,016 |
| sli_zigbee_route_table | 2,040 |
| sli_zigbee_route_record_table_data | 2,033 |
| sli_zigbee_child_table_data | 1,560 |
| sli_zigbee_child_timers_data | 260 |
| sli_zigbee_child_status_data | 130 |
| sli_zigbee_child_lqi_data | 130 |
| sli_zigbee_address_table | 1,584 |
| sli_zigbee_aps_duplicate_rejection_entries | 256 |
| sli_zigbee_counters | 84 |
| sli_zigbee_counters_thresholds | 84 |
| sl_mac_tx_fifo_staging_buffer | 256 |
Do not divide every array by the advertised table size and assume it has no sentinel/reserved rows. The route and child arrays illustrate why exact linked allocation is more useful than a generic per-entry estimate.
The ELF also has _acUpBuffer and _acDownBuffer, each 1,024 bytes. They must not be called the physical EUSART TX/RX capacity merely because of their names; their context is debug/RTT-related. The MAC TX FIFO staging buffer is a radio resource, not the UART output buffer. Small rxBuffer/sendBuffer objects are handles, not proof of tiny packet payload buffers.
### What the ELF cannot establish by itself
The229,896-byte region is the **general memory-manager reservation**. It does not establish:
- packet heap acquired at initialization;
- remaining free packet bytes after network startup;
- minimum free space during callback bursts;
- allocation fragmentation;
- largest allocatable block;
- maximum main-stack usage;
- live queue occupancy or high-water marks;
- runtime allocations performed by libraries or host initialization.
The linked heapMemory/heapMemorySize and emHeapBase/emHeapLimit variables show runtime pool state exists. Their BSS initial values are not a post-startup measurement. Do not subtract arbitrary static table estimates from 229,896 and label the answer “free packet heap.”
For the next build, retain the linker map, resolved allocator configuration, initialization code/flags, and exact acquisition policy behind HUGE. Prefer the present strategy until actual packet pressure or starvation of another allocator is demonstrated. If dynamic allocation really is the problem, either reserve more of the existing heap for the packet subsystem or remove measured waste elsewhere; raising unrelated fixed queues is not automatically helpful.
Worst credible transient pressure combines several kinds of work: pending APS sends retaining payloads, incoming callbacks waiting for serial transmission, network retry state, route discovery, indirect messages for sleepy children, commissioning security operations, and NVM activity delaying the main loop.128 configured APS messages does not mean 128 maximum-size transmissions are guaranteed to fit concurrently with all other pools.
For budgeting a new variant:
1. Measure its new fixed sections, stack reservation, and general heap.
2. Determine packet-pool acquisition after initialization.
3. Measure maximum stack use and packet low-water mark in one bounded relevant load.
4. Set headroom criteria against measured worst use plus a stated margin.
5. Reject unsupported “enough RAM” claims based on the size utility alone.
### Transport budget and hardware limits
At115200 baud with 8N1, the nominal unescaped serial ceiling is 11,520 bytes/s in each direction.128 bytes covers about 11.1 ms of incoming line-rate data;512 bytes about 44.4 ms. RX512 therefore adds about 33.3 ms of burst storage, not a higher sustained throughput.
ASH framing/escaping, acknowledgments, retransmission, EZSP overhead, and host/bridge scheduling lower useful throughput. A100-byte snapshot takes at least 8.7 ms of line time before these overheads. Continuous diagnostics can compete with useful callbacks.
The approved board manifest uses EUSART1, TX PC1, RX PC2,115200 baud, no hardware flow control,38.4 MHz HFXO, precision 10, CTUNE100, and RSSI offset 0. The corresponding Nabu board uses a different package, EUSART0, different pins,39 MHz, CTUNE108,460800 baud, and local hardware flow control between its bridge and radio. [SONOFF manifest][sonoffmanifest], [Nabu manifest][nabu].
Those are concrete reasons to preserve the SONOFF board settings. The manifest does not prove whether RTS/CTS is physically routed or whether every ESP firmware version supports a higher baud. The SONOFF product documentation establishes an ESP32/EFR32MG24 bridge architecture, but the reviewed sources do not establish complete ESP RX/TX/socket buffer sizes, firmware version, backpressure, or watchdog behavior. [Official SONOFF introduction][sonoff].
For USB, distinguish the host's serial-driver flow setting from NCP hardware flow control and ASH protocol signaling. For TCP, host serial-driver settings may not apply at all. Verify which mode production actually uses before interpreting a baud or rtscts setting. Prefer Ethernet for predictable bridge delivery when already available, but do not claim it changes radio capacity or guarantees that bursts disappear.
## 8. Test strategy
The objective is a short, interpretable acceptance sequence. No live tests were executed for this review.
### First repair and validate the harness offline
The actual current defects are specific:
| Location | Observed behavior | Required correction / regression case |
|---|---|---|
| safe_identity_from_running_z2m | Reads coordinator_backup.json from the running container | An unchanged stale backup must not prove fresh NCP identity; require current session evidence and timestamp/source |
| version_lines / cmd_postflash | Searches a bounded log tail without a startup session boundary | Old9.1.1/EZSP19 lines must not validate a failed or different current start |
| require_single_z2m_owner | Counts containers whose names contain zigbee2mqtt | Verify intended add-on owner and relevant device/socket ownership; the name filter alone does not exclude another client |
| load_build_manifest | Validates BTT and key values but not RX512 in this gate | Reject a bundle missing the approved RX profile; bind deployment to the selected approved artifact contract |
| active finish() | Hardcodes total 16 and allows successes>=15 even if only 15 results completed | Require16 completed, unique scheduled trials; a global timeout always fails |
| active connect handler | Can schedule next() again on reconnect | Start once; reconnect must not create duplicate/out-of-order stimulus |
| active response parser | Silently ignores malformed JSON | Preserve and classify malformed relevant responses; obey the stated failure contract |
| permit main() | Runs every trial even when an earlier result failed | Stop scheduling further trials at the first hard failure |
| permit one() | Records permit_after but does not require it to be freshly false before another trial | Verify a new observation within the current trial epoch before continuing |
| permit final close | Sends QoS0 close without correlating a reply; accepts lastInfo even if stale | Correlate cleanup response and fresh close state; missing proof means unknown/fail |
| permit exception/timeout path | Exits without guaranteed close cleanup | Use bounded cleanup/finally and retain whether closure succeeded |
| permit logging | Resets captured lines between trials and only keeps selected patterns | Retain continuous event evidence, including gaps and final close |
| cmd_acceptance fatal scan | Searches resets/disconnect/network-down only after both scripts; does not comprehensively cover all pressure signatures | Monitor the complete window for the required BUSY/message-pressure/fatal set |
| cmd_acceptance failure evidence | Results are assigned to session only after the full success path | Save active and partial permit evidence before marking STOPPED |
| cmd_postflash startup | Start/wait/settle occurs outside the guarded failure block | Interrupted or failed startup must leave an explicit failed/incomplete phase |
| cmd_finalize | Requires two nonempty strings but does not mechanically validate their command outcome | Use structured command/time/result/physical-check evidence; retain the supervisor's explicit physical confirmation |
Sources: [common helpers][common], [active script][active], [permit script][permit], [acceptance runner][accept], [deployment code][deploy].
Do not fix these by adding more live tests. They can be exercised with mocked MQTT and remote-command responses.
The current canary uses **Read Reporting Configuration**, not Read Attributes(onOff). Z2M's deviceReportingRead calls endpoint.readReportingConfig and returns its result. This is a real read-only Zigbee request/response mechanism, which can serve as a transport canary, but its latency and success semantics differ from historical attribute reads or physical actuation. Preserve the response details and distinguish reporting-support errors from a transport timeout. [Z2M2.14 implementation][z2mbridge].
The existing repository tests passed 18/18 during context preparation. That is useful but does not validate these untested asynchronous/operational cases. This review did not rerun live acceptance or execute the deployment tooling.
### Bounded sequence after supervisor accepts corrections
1. **Artifact gate:** verify selected repo/release identity and all relevant hashes; resolve exact paths; preserve the matched rollback and stopped-state backup.
2. **Current identity baseline:** capture coordinator identity and network parameters from a current owner session; obtain fresh backup evidence where required for key digest comparison. Record the session/time, not just an unchanged file.
3. **Flash and resume:** follow the mechanical runbook. Verify actual resumed network and current version. Separate the operator's flash acknowledgment from on-device identity proof.
4. **Runtime evidence:** obtain BTT, threshold, KEY size, direct-child policy, and critical transport/owner metadata through an explicitly supported owner path. If stock Z2M cannot expose a required field, record the limitation and revise the supervisor's evidence contract rather than secretly adding a second client.
5. **Active canary:** exactly 16 completed read-only transactions, at least 15 successes, no hard stop signature. A global timeout or incomplete result set fails.
6. **Permit gate:** at most 5 successful 10-second All windows, serialized and individually closed. In the all-success path that is exactly 5; on the first hard failure, stop immediately. No pairing or automatic retries.
7. **Two representative real group commands:** record dispatch, original status, physical result, and any group registration/state-update anomaly. Check the actual loads; a successful send admission alone does not prove every lamp changed.
8. **Finalize or stop:** require complete evidence, fresh identity, one correct owner, and closed joining. On failure, retain evidence and use the existing supervisor-controlled recovery decision.
Where the diagnostic path is approved, take one counter baseline immediately before the relevant bounded stimulus and one after the failure/success. Do not add a rapid continuous polling service. Track the hourly clear boundary and any restart.
For attribution, a single event may still be ambiguous. If all counters remain unchanged, the correct result is “mechanism unresolved”; inspect the exact status path or use an isolated lab trace. Do not automatically retry or grow the next queue.
The approval target is practical acceptance, not proof of a small failure rate. With0 failures in 5 independent Bernoulli trials, the one-sided 95% upper bound on failure probability is approximately 45.1%. Real mesh trials are also correlated. Thus five clean windows are a bounded operational screen, not statistical proof of long-term reliability.
### Why a shared memory-pressure fix is not yet justified
RX512/BTT64/KEY12 change three values simultaneously. If the combined image succeeds, that is useful operational evidence but cannot by itself assign the improvement to BTT. A full production matrix is unnecessary. If exact causal attribution becomes important, create a small number of controlled variants on an isolated equivalent setup and change one relevant mechanism at a time.
## 9. Must-do-before-flash list
Only release blockers belong here:
1. **Make fresh identity and correct ownership demonstrable.** Backup preservation is necessary but insufficient to claim current NCP identity. A current-session evidence mechanism must be concrete before deployment.
2. **Repair acceptance stop/closure/completeness behavior.** A script that keeps opening windows after a required stop condition must not execute the current contract.
3. **Preserve partial failure evidence and handle interrupted startup.** The executor must produce a truthful STOPPED/incomplete result with original error and cleanup outcome.
4. **Bind the selected deployment to the approved binary/profile.** Enforce RX512 as well as BTT64/KEY12, and distinguish exact artifact hashes from self-consistent but unapproved metadata.
5. **Correct the release description and its acceptance claims.** The actual static delta is 704 B; stock host child policy defaults 32; device-side P009 identity is not proved by generic 9.1.1. State how unexposed runtime fields will be handled.
The local ELF audit resolves the static SRAM concern for the already-approved artifacts. Rebuilding P009 solely to recover a map is not a prerequisite when the existing ELF evidence establishes the necessary fixed allocations. Future builds should archive maps and generated configuration automatically.
The unknown threshold is an attribution/effective-policy gap. It blocks a claim that local admission has been fully characterized; it does not, by itself, prove the existing image is unsafe to evaluate. Resolve it before applying threshold 48 or recommending BTT>64.
XNCP, more multicast capacity, watchdog changes, baud increases, a new security backend, and a builder refactor are not mandatory prerequisites for the current bounded P009 evaluation.
## 10. Deferred/rejected list and remaining architecture questions
### Security and key-table semantics
KEY12 is not a 12-device network limit. Individual stored link keys, transient joining keys, network keys, and derived trust-center keys are different resources. The SDK documents trust-center master-key derivation and separate storage needs for install-code keys. Preserve the existing key policy/backend; increasing capacity does not itself establish a stronger authentication policy. [Custom NCP security guidance][custom].
There is a relevant conditional SDK issue:9.1.1 release notes retain known issue 1571691 for large networks using Secure Key Storage, with `SL_PSA_KEY_USER_SLOT_COUNT` as the documented sizing workaround; Classic Key Storage is excluded. The inspected ELF contains `zigbee_security_manager_no_vault.c`, which points toward the classic/no-vault implementation. PSA crypto symbols alone do not prove the affected key-storage backend is selected. Confirm the resolved component catalog before applying this workaround. Do not blindly set PSA slots to 12 or assume KEY12 fixes that issue. [SDK known issues][releasenotes].
If a later build uses Secure Key Storage, select slots against the documented backend requirements and supported network size, then measure its memory/storage impact. Keep any backend migration out of this P009 change.
Increasing key-table capacity should preserve existing entries, but shrinking it during rollback may make newly populated higher-index entries inaccessible. The P009 test contract forbids pairing, which limits that risk; it does not prove that no security-related state can ever evolve during operation. Record non-secret key metadata/capacity where supported and define rollback behavior before a later long-running deployment. A matching network-key hash does not prove that every individual link key and frame counter was preserved.
Do not restore stale security frame counters merely to make a backup comparison equal. Preserve the stack's supported monotonic/security migration behavior. The protected network identity and the mutable security counters need different comparison rules.
### Zigbee 4.0 and 9.1.1 capabilities
The pinned NCP already selects R22/R23 support and dynamic commissioning. A Zigbee 4.0 gateway feature also requires compatible host behavior; adding a SoC application-framework component to the NCP does not automatically make Z2M implement new joining semantics. Leave the existing network security policy intact. [Pinned project][builder].
Relevant9.1.1 notes include a dedicated sleepy-target timeout setting, packet-handoff link-quality support, and a host gateway sample. The sleepy-target default preserves prior timing. These are reasons to record resolved configuration, not reasons to tune retries or enable all components. No reviewed note proves a general BTT/BUSY fix for this SONOFF path. [Release notes][releasenotes].
The current EZSP overview contains stale protocol-version prose despite the 9.1.1 release summary specifying version 19. Prefer the pinned host's negotiated version and exact generated SDK definitions over undated general text. [Release summary][releasesummary], [EZSP overview][config].
One-request/combined-send extensions are host optimizations only when the host uses them. Pinned herdsman already sends multicast/broadcast through one corresponding EZSP send command. Adding Nabu's combined unicast command does not increase BTT capacity or automatically alter stock host behavior. Defer it until an actual per-unicast setup overhead is measured.
Use getLibraryStatus and the generated component catalog for supported capability verification, but do not treat a library bit as proof of every host-visible gateway feature. A boot capability report should name the backend, relevant libraries, supported diagnostics, and transport profile.
### Packet handoff
Packet handoff with RSSI/LQI can support a bounded diagnostic investigation. It does not need to stream all intercepted packets to the host. A receive-all setting and callback interception can change traffic processing and timing; evaluate both with a specific purpose.
For a diagnostic variant, aggregate only the fields needed for the question, retain normal processing, bound work per packet, and expose summaries on request. A callback that accidentally consumes or suppresses ordinary frames is a compatibility regression. Defer packet streaming and broad interception in the production candidate.
### Routing/concentrator policy
Keep route/source-route 254 and neighbor 26. Additional neighbor capacity is not supported by the documented configuration, and changing route-table size does not solve stale paths by itself.
Keep the established delivery failure threshold 1. The prior 1-to-3 experiment was reported worse; do not reintroduce it without new evidence. Source-route failure callbacks must be correlated with actual delivery failure and contemporaneous NWK-to-device mapping. A destination in a route-error log does not identify the router that originated the bad route.
Do not restore volatile route tables across reset as a general crash-recovery measure. Stale routes can be worse than bounded rediscovery. Nabu's route-management features are useful in their intended host architecture but are not automatically a gain for this one.
### Group and Green Power behavior
The three fixed memberships are 0,901, and 0x0B84. With21 distinct application group IDs outside that set, all successfully registered, occupancy would be 24/26. This is a conditional calculation, not a live occupancy reading. Duplicate IDs and unused groups reduce it; stale registrations accumulated during the session may increase it relative to the current configured group count.
The originating coordinator need not be a member merely to transmit to a group. Herdsman's dynamic registration exists to receive multicast state reports. Thus membership failure can explain missing state updates even when a lamp acted physically; it should not be conflated with initial group-send BUSY. [Endpoints][endpoints], [onMessageSent][host].
The failed-registration path splices a software array and retries on later occurrences. If registrations fail under concurrent group activity, verify that software indexes remain consistent with actual NCP slots. This is an audit lead, not a reproduced index-corruption finding.
Keep Green Power support and its fixed endpoint/group unless product requirements explicitly remove it. Removing GP to eliminate a permit-join symptom changes commissioning compatibility and conceals a possible pressure source. Record GP traffic separately in any failure trace.
### RF and board manifest
Do not copy Nabu's 40-pin target, oscillator, PA assumptions, reset wiring, LEDs, or product ID onto the 48-pin SONOFF board. The manifest provides concrete UART/HFXO choices; it does not establish the entire RF schematic, antenna path, FEM, PA calibration, regional power policy, or ESP firmware implementation.
Record the deployed ESP firmware/version and mode, physical connection, bootloader version, and hardware revision as part of the eventual deployment evidence. Keep the current radio calibration callback and existing power/channel settings. No retained evidence makes an RF-power increase, CCA alteration, channel move, or manufacturing-test mode a justified response to the observed initial BUSY.
Firmware build validation should verify critical pins/clock/part definitions, not only baud and filename. The existing verifier checks part, SDK, baud, flow, and EUSART selection but does not prove every resolved RF/board define.
### Crash resilience and observability
First distinguish: NCP watchdog reset, external reset, power loss, application assert/fault, serial ACK failure, ESP reboot, host process restart, and network-down callback. Correlate timestamps; do not count every host reconnect as an NCP firmware crash.
Use a watchdog only after proving the generated timeout/feed behavior and spare-device recovery. Keep assertions and faults observable through a framed mechanism or an appropriate debug channel. Do not emit raw debug text onto the shared EZSP UART.
Persistent boot/error counters are optional. A retained-RAM crash record may disappear on power loss; document that limitation. Persistent counters introduce NVM layout and wear considerations. They are not required to diagnose this admission problem.
### Build structure and provenance
The current exact textual patch is small and fail-closed against the pinned builder. Keep it for the current release rather than redesigning the build system. For multiple future variants, move the SONOFF-specific configuration into a manifest overlay/custom component if the pinned builder supports the required resolution order. Keep one authoritative profile and generate verification expectations from it, while preserving an independent assertion of what the binary contains.
The frozen builder checkout is not the complete environment. Its Dockerfile uses moving base images, uv:latest, and package installation. A local Docker image ID is useful evidence but is not automatically a retrievable immutable OCI reference. Save/publish the successful environment and its dependency inventory if repeatability is required. [Dockerfile][docker].
Do not call source patch restrictions “exactly three binary differences.” The intended configuration changes are three; bytes, addresses, padding, and generated metadata can differ more widely. Verify the intended semantic profile, image integrity, and any reproducibility normalization separately.
Reject a large permanent diagnostic framework, full upstream fork, generalized profile plugin system, or a full production parameter matrix until the current small contracts prove insufficient.
### Nabu Casa comparison limits
The preparation snapshot identified Nabu's main commit `11d8f3a105199f0ae622406e774e20470ce6e0e7` and latest listed release `v2026.08.18-beta1`; the SDK-bump comparison used `c65e86eb5b62c098615060e5562a6654a227bf0e` from July 30. The source comparison is pinned and useful, but the word “production” in older research is stronger than this evidence establishes. A current source manifest or beta release does not prove which image every shipped ZBT-2 runs. Compare the exact relevant released artifact and host configuration before asserting production equivalence. [Nabu release history](https://github.com/NabuCasa/silabs-firmware-builder/releases).
## 11. Implementation handoff to supervisor
This is a proposed change list. No production or implementation changes from this list were applied by the reviewer.
| Priority | Repository location / component | Concrete change | Done when |
|---|---|---|---|
| S | deploy/p009_common.py: safe_identity_from_running_z2m, snapshot, version_lines | Rename backup-derived evidence honestly; add current-session identity/version evidence and freshness | A stale unchanged backup plus old log lines cannot pass as current NCP evidence |
| S | deploy/p009_common.py: require_single_z2m_owner | Bind the selected container to the intended add-on and transport; document remaining ownership visibility limits | Wrong single container / another adapter client cannot be accepted as the intended owner |
| S | deploy/p009_common.py: load_build_manifest; deploy/p009_deploy.py: cmd_arm | Validate RX512 and exact selected artifact/profile contract; preserve source of approval | Older BTT64/KEY12/RX128 metadata is rejected for this release |
| S | deploy/acceptance-active.cjs | Exactly16 scheduled/completed results; timeout is failure; single-start reconnect guard; classify malformed response | Mock reconnect, timeout after 15 successes, and corrupt response all produce truthful bounded failure |
| S | deploy/acceptance-permitjoin.cjs | Abort future windows on first hard failure; continuous evidence; bounded close in cleanup; correlated close response and fresh state | First-trial BUSY cannot trigger another open; stale false cannot prove closure |
| S | deploy/p009_accept.py | Persist each stage/partial outcome before a later failure; scan complete event interval; distinguish incomplete logs | Failure report contains original per-trial evidence and cleanup result |
| S | deploy/p009_deploy.py: cmd_postflash | Include start/wait/settle in failure handling; validate current session | Failed/interrupted startup cannot leave a misleading resumable success phase |
| S | deploy/p009_deploy.py: cmd_finalize | Structured two-group evidence with outcome and physical result; final fresh identity | Two arbitrary nonempty strings are not mechanically reported as successful physical tests |
| S/A | firmware/verify_build.py | Validate generated config and selected ELF symbols/initializers; distinguish reported versus inferred values | Input/profile mismatch with actual ELF is detected |
| A | .github/workflows/build-p009.yml | Preserve generated headers, component catalog, compile/link commands, map, actual compiler versions, ELF resource report | Every new artifact has reproducible binary-level evidence and declared memory pools |
| A | runtime/patch_herdsman_observability.py | Rate-bound/coalesce snapshots; retain original status/context; account for clearing/reset and timing | Diagnostic failure cannot replace the original failure or leave an unowned pending transaction |
| A | runtime/patch_herdsman.py | Keep policy opt-in; document six actual policy writes; add final readback after relevant initialization if adopted | Threshold/mode changes are not presented as firmware-only behavior |
| A/B | Future SONOFF XNCP source/component, selected by firmware/patch_builder.py or manifest | Minimal identity command with immutable canonical profile/build ID; preserve stock EZSP behavior | New named build passes parser checks, matched memory diff, and stock-host spare-device startup |
| B | Future health component | Use native counter API; explicitly supported reset/pool fields; bounded response | Unsupported metrics are flagged, no counter clear/NVM write/unbounded callback stream |
| B | Future multicast variant | Only if measured membership demand warrants 26-to-32 | Independent variant, table occupancy proof, actual linked cost, group-state reception check |
| B | Future watchdog variant | Resolve existing behavior before explicit enable | Timeout/feed/recovery proven on isolated hardware without losing network state |
| S | docs/TUNING-RESEARCH.md | Update RX512 inclusion,704-byte .bss delta,8-byte BTT entry, host child policy, group membership caveat | Document agrees with approved binary and pinned host |
| S | firmware/RESOURCE-PROFILE.md and README.md | Separate build capacity, runtime policy, and verified values | “64 children” is not misrepresented as a universal post-startup value |
| S | docs/EXECUTOR-DEPLOY.md | Describe actual identity evidence, cleanup semantics, failure report, and bounded acceptance limits | Runbook promises only what the corrected tooling enforces |
| S | tests/test_p009.py plus minimal JS checks | Add regression cases for identified contract failures; reuse existing patterns | Each blocker has one meaningful offline failing-then-passing check |
Suggested implementation order:
1. Correct evidence/acceptance tooling and associated documentation.
2. Validate those changes offline.
3. Add generated/ELF reporting to CI for future artifacts.
4. Agree on the available owner-side readback path and explicit limits of current stock-host evidence.
5. Evaluate the unchanged approved P009 binary under the corrected bounded contract.
6. If residual failure remains, use the diagnostic branch to choose one mechanism.
7. Build identity-only XNCP as a separately named follow-up; add other firmware behavior only when supported by the result.
### Evidence still required before claiming the full architecture is characterized
- Actual production stack_config.json and the success/failure/readback of current startup writes.
- Effective new-broadcast-entry threshold and MTORR setting after initialization.
- Acquired Zigbee packet heap, runtime free/minimum bytes, and stack high-water mark.
- Resolved2026.6.1 component catalog, particularly key storage and watchdog.
- Exact UART TX buffering/driver scheduling and ESP firmware/backpressure implementation.
- Current group membership occupancy and any registration failures.
- Exact native admission branch for a BUSY event if a definitive causal claim is required.
- Concrete owner-side identity/readback integration without a competing transport client.
These gaps are explicit. The measured binary profile and the confirmed harness defects do not depend on guessing their answers.
### Audit artifacts
- Full review: this file.
- Read-only standard-library ELF inspection helper: `.local/p009/review_elf.py`.
- Reviewed local inputs: `.local/p009/firmware/`.
- All six GBL/HEX/ELF digests matched the downloaded manifest.
- No flash, live EZSP command, Home Assistant operation, restart, firmware build, or GitHub comment was performed in this review.
[host]: https://github.com/Koenkk/zigbee-herdsman/blob/0968f979d558874b17396c96b66382d4236bbdcd/src/adapter/ember/adapter/emberAdapter.ts
[endpoints]: https://github.com/Koenkk/zigbee-herdsman/blob/0968f979d558874b17396c96b66382d4236bbdcd/src/adapter/ember/adapter/endpoints.ts
[ezsp]: https://github.com/Koenkk/zigbee-herdsman/blob/0968f979d558874b17396c96b66382d4236bbdcd/src/adapter/ember/ezsp/ezsp.ts
[addresses]: https://github.com/Koenkk/zigbee-herdsman/blob/0968f979d558874b17396c96b66382d4236bbdcd/src/zspec/enums.ts
[builder]: https://github.com/Nerivec/silabs-firmware-builder/blob/858c34b0eb6f53a2e0c89455ea489ceaa62d58db/src/zigbee_ncp/zigbee_ncp.slcp
[sonoffmanifest]: https://github.com/Nerivec/silabs-firmware-builder/blob/858c34b0eb6f53a2e0c89455ea489ceaa62d58db/manifests/sonoff/sonoff_dongle-m_zigbee_ncp.yaml
[docker]: https://github.com/Nerivec/silabs-firmware-builder/blob/858c34b0eb6f53a2e0c89455ea489ceaa62d58db/Dockerfile
[nabu]: https://github.com/NabuCasa/silabs-firmware-builder/blob/c65e86eb5b62c098615060e5562a6654a227bf0e/manifests/nabucasa/zbt2/zbt2_zigbee_ncp.yaml
[nabubase]: https://github.com/NabuCasa/silabs-firmware-builder/blob/c65e86eb5b62c098615060e5562a6654a227bf0e/src/zigbee_ncp/zigbee_ncp.slcp
[xncp]: https://github.com/NabuCasa/silabs-firmware-builder/blob/c65e86eb5b62c098615060e5562a6654a227bf0e/src/zigbee_ncp/extension/xncp_extension/src/xncp_core.c
[verify]: https://github.com/analienx/Sonoff-Dongle-Max/blob/dca87aa4fb8405ef2ca4f0ef647c60bd46ef3600/firmware/verify_build.py
[workflow]: https://github.com/analienx/Sonoff-Dongle-Max/blob/dca87aa4fb8405ef2ca4f0ef647c60bd46ef3600/.github/workflows/build-p009.yml
[common]: https://github.com/analienx/Sonoff-Dongle-Max/blob/dca87aa4fb8405ef2ca4f0ef647c60bd46ef3600/deploy/p009_common.py
[deploy]: https://github.com/analienx/Sonoff-Dongle-Max/blob/dca87aa4fb8405ef2ca4f0ef647c60bd46ef3600/deploy/p009_deploy.py
[accept]: https://github.com/analienx/Sonoff-Dongle-Max/blob/dca87aa4fb8405ef2ca4f0ef647c60bd46ef3600/deploy/p009_accept.py
[active]: https://github.com/analienx/Sonoff-Dongle-Max/blob/dca87aa4fb8405ef2ca4f0ef647c60bd46ef3600/deploy/acceptance-active.cjs
[permit]: https://github.com/analienx/Sonoff-Dongle-Max/blob/dca87aa4fb8405ef2ca4f0ef647c60bd46ef3600/deploy/acceptance-permitjoin.cjs
[policy]: https://github.com/analienx/Sonoff-Dongle-Max/blob/dca87aa4fb8405ef2ca4f0ef647c60bd46ef3600/runtime/patch_herdsman.py
[p010]: https://github.com/analienx/Sonoff-Dongle-Max/blob/dca87aa4fb8405ef2ca4f0ef647c60bd46ef3600/runtime/patch_herdsman_observability.py
[research]: https://github.com/analienx/Sonoff-Dongle-Max/blob/dca87aa4fb8405ef2ca4f0ef647c60bd46ef3600/docs/TUNING-RESEARCH.md
[config]: https://docs.silabs.com/zigbee/latest/sisdk-ezsp-reference-guide/02-emberznet-serial-protocol
[custom]: https://docs.silabs.com/zigbee/latest/customized-ncp-zigbee7/03-component-customizations
[stackinfo]: https://docs.silabs.com/zigbee/latest/zigbee-stack-api/stack-info-h
[releasenotes]: https://docs.silabs.com/zigbee/latest/sisdk-zigbee-release-notes/sisdk-zigbee-sdk-release-notes
[releasesummary]: https://docs.silabs.com/zigbee/latest/sisdk-zigbee-release-notes/
[part]: https://www.silabs.com/wireless/zigbee/efr32mg24-series-2-socs/device.efr32mg24a420f1536im48
[sonoff]: https://dongle.sonoff.tech/guide/dongle-m/introduction-dongle-m/
[z2mbridge]: https://github.com/Koenkk/zigbee2mqtt/blob/2.14.0/lib/extension/bridge.ts
