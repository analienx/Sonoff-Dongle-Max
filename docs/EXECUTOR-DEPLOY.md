# P009 controlled deployment — mechanical operator runbook

This is the **operator procedure**, not an engineering notebook. The supervisor owns firmware, scripts, CI, interpretation and fixes. The local executor runs only the exact approved commands, captures secret-safe evidence and stops at every stated gate.

No code/config/workflow patching, parameter tuning, added retries, NVM reset, network reform, re-pairing or broadened testing is allowed.

## 0. Current authorization source

Issue **#6** must contain a newest supervisor comment that explicitly pins all of the following from one green authoritative release run:

- exact repository source SHA;
- Actions run ID;
- aggregate artifact name/ID;
- production profile ID `P009-RX512-BTT64-KEY12-MCAST26`;
- P009 GBL filename, byte size and SHA-256;
- matched stock rollback GBL filename, byte size and SHA-256;
- exact checkout/runbook reference;
- the currently authorized stopping point.

If any value is absent, ambiguous, older than a later PAUSE comment, or disagrees with the downloaded manifests: **STOP**.

Historical comments/artifacts are evidence only. They are not deployment authorization.

## 1. Approved release gate

The authoritative workflow is `.github/workflows/release-final.yml`. The exact approved source SHA must have a green aggregate release run in which:

- offline regression tests passed;
- stock rollback + frozen P009 built in the same resolved toolchain image;
- clean-twin P009 linked ELF and HEX reproducibility passed;
- strict linked P009 assertions passed;
- P011 and P013 variant checks passed;
- host P009/P010/config-audit overlays built from the same source SHA;
- host bulk-lane and P012 status were packaged;
- aggregate SHA256 inventory verified.

Only **P009** is the first production flash candidate. P010/P011/P012/P013 and the host bulk lane are **not enabled or flashed** during the first P009 test.

After extracting the aggregate artifact, verify the aggregate inventory from its root:

```bash
sha256sum -c SHA256SUMS
```

Then verify the firmware sub-bundle independently:

```bash
cd firmware
sha256sum -c SHA256SUMS
cd ..
```

Required release structure includes at least:

```text
RELEASE-MANIFEST.json
SHA256SUMS
firmware/
  P009-BUILD-MANIFEST.json
  VARIANT-BUILD-MANIFEST.json
  FIRMWARE-COMPONENT-MANIFEST.json
  SHA256SUMS
  p009/
  stock-rollback/
  p011/
  p013/
  source-profiles/
  generated/
  linked/
  provenance/
host/
contract/
```

`RELEASE-MANIFEST.json` must state:

```text
production_flash_candidate = P009
production_profile_id      = P009-RX512-BTT64-KEY12-MCAST26
flash_authorized           = false
```

`flash_authorized=false` is intentional: release CI prepares the artifact; the separate supervisor/human gate authorizes a physical flash.

`firmware/P009-BUILD-MANIFEST.json` must describe exactly:

```text
P009:
  RX buffer       512
  BTT              64
  key table        12
  multicast        26

stock rollback:
  RX buffer       128
  BTT              30
  key table         1
  multicast        26

linked .bss delta        +704 B
memory-manager delta        0 B
```

Any MCAST32 image is **P013**, never P009. Any mismatch: STOP before touching HA.

## Remote transport

The established proxy route is:

```text
--remote-template "rtk proxy ssh {host} {command}"
```

The session locks host, add-on, Z2M directory and remote transport at ARM. Do not change them mid-session.

## 2. ARM — the first local execution gate

Work from the exact repository SHA in the approved release manifest. The hardened ARM command rejects a different local Git HEAD.

Assuming the extracted aggregate artifact is at `.local/dongle-max-release`:

```powershell
python deploy/p009_tool.py `
  --remote-template "rtk proxy ssh {host} {command}" `
  arm `
  --bundle-root .local/dongle-max-release/firmware `
  --build-manifest .local/dongle-max-release/firmware/P009-BUILD-MANIFEST.json `
  --session .local/p009/session.json `
  --confirm P009-ARM
```

ARM must prove/capture:

- exact checked-out source SHA equals the build manifest;
- firmware sub-bundle SHA256 inventory is valid;
- exact P009 and stock rollback GBL SHA256 + byte sizes are valid;
- manifest is frozen three-delta P009 with multicast26 and linked +704-B `.bss` proof;
- exactly one running Zigbee2MQTT owner exists and is proven to belong to the authoritative HA add-on slug/metadata (current `app_...` or legacy `addon_...` naming is handled by the tool);
- exact Docker container ID and `StartedAt` are captured;
- approved EmberZNet 9.1.1 and EZSP19 are proven from current structured `bridge/info` metadata when exposed, otherwise from exact current-start-epoch adapter logs; backup EZSP metadata alone is not current-runtime proof;
- a fresh Zigbee2MQTT 2.14 health probe succeeds: the request payload is **empty**, the healthy response is non-retained and is observed after publication;
- current coordinator IEEE/PAN/extPAN/channel come from secret-safe `bridge/info` fields;
- the network-key plaintext remains on HA; only its SHA-256 fingerprint leaves the owner container;
- stopped-state hashes for `configuration.yaml`, `database.db` and `coordinator_backup.json` are captured where present;
- stopped-state backup is created and hashed on HA;
- an independent local copy is created outside HA and its SHA-256 must exactly match the HA archive;
- Zigbee2MQTT is stopped and no residual owner remains;
- session phase reaches exactly `ARMED`.

The backup is not misrepresented as a live NCP read. Live network fields and backup-derived key/device metadata are separate evidence sources.

If ARM fails or is interrupted after session creation, the session becomes `STOPPED`. Do not work around it locally.

Status check:

```powershell
python deploy/p009_tool.py `
  --remote-template "rtk proxy ssh {host} {command}" `
  status `
  --session .local/p009/session.json
```

### Required ARMED report

Post to issue #6 only secret-safe evidence:

- source SHA + approved run/artifact;
- P009 GBL path/bytes/SHA256;
- rollback GBL path/bytes/SHA256;
- phase `ARMED`;
- owner container ID/start epoch;
- coordinator IEEE/PAN/extPAN/channel;
- network-key fingerprint, never key plaintext;
- stopped backup path/SHA256 plus independent local-copy path/SHA256;
- confirmation Zigbee2MQTT is stopped and no residual owner exists.

Then **STOP. Do not flash.** The supervisor must inspect ARMED evidence and issue a separate authorization for that exact P009 hash.

## 3. Manual SONOFF WebUI flash

Only after explicit supervisor authorization, upload the exact P009 GBL printed by ARM.

Forbidden:

- P011 or P013 instead of P009;
- NVM erase;
- factory reset;
- new-network creation;
- PAN/extPAN/channel/key changes.

After WebUI reports successful upload, acknowledge the exact ARM-bound SHA:

```powershell
python deploy/p009_tool.py `
  --remote-template "rtk proxy ssh {host} {command}" `
  confirm-flash `
  --session .local/p009/session.json `
  --observed-sha256 <EXACT_P009_SHA256_FROM_ARM> `
  --confirm P009-FLASHED
```

This is **human artifact acknowledgment**, not device-side attestation. P011 is the separate future self-identifying variant.

## 4. Post-flash owner/network identity gate

```powershell
python deploy/p009_tool.py `
  --remote-template "rtk proxy ssh {host} {command}" `
  postflash `
  --session .local/p009/session.json `
  --confirm P009-POSTFLASH
```

The tool starts Z2M itself and requires a genuinely new owner session. Required invariants:

- new Docker start epoch compared with pre-arm;
- exact expected HA add-on owner;
- EmberZNet 9.1.1 / EZSP19;
- same coordinator IEEE;
- same PAN/extPAN/channel;
- same network-key SHA-256 and key sequence;
- same coordinator-backup device count;
- unchanged `configuration.yaml` in this firmware-only test.

Expected phase: `IDENTITY_VERIFIED`.

Stock-host interpretation:

```text
BTT: binary 64; stock herdsman normally does not lower it
KEY: binary 12; stock herdsman normally does not lower it
MULTICAST: binary 26 in P009
children: compiled capacity 64; stock host normally asks for 32
NEW_BROADCAST_ENTRY_THRESHOLD: separate policy; unchanged in first test
```

Do not install the P009 runtime policy, P010 diagnostics, P011, P012 or P013 during this baseline test.

Any post-flash failure persists evidence, stops the session and must be reviewed before any further action.

## 5. Bounded automated acceptance

```powershell
python deploy/p009_tool.py `
  --remote-template "rtk proxy ssh {host} {command}" `
  acceptance `
  --session .local/p009/session.json `
  --confirm P009-ACCEPT
```

### Active canary

Exactly:

```text
2 rounds × 8 known mains-powered targets = 16 unique transactions
```

Pass requires all of:

- 16 scheduled;
- 16 completed;
- 16 unique result IDs;
- >=15 successes;
- no global timeout;
- no malformed correlated evidence.

`15/15` is not a pass. Reconnect cannot replay a second stimulus sequence.

Before Permit Join starts, an owner-ID/start-epoch-bound Docker log window is checked for hard BUSY/message-pressure/reset/disconnect signatures. A hard signature stops the run immediately; rolling add-on log-prefix continuity is not used as the safety primitive.

### Permit Join All

Clean path:

```text
5 serial trials
10 seconds each
no pairing
no executor-added retry
```

On the first failed trial no further open window is scheduled.

Any hard BUSY/reset/ASH/disconnect/network-down event immediately requests `time:0` closure and prevents further opening stimulus. Cleanup still performs a final close and requires a **non-retained**, fresh `permit_join=false` observation. The same Docker owner/start epoch must own the whole bounded acceptance.

Clean phase: `AUTOMATED_ACCEPTANCE_PASSED`.

## 6. Exactly two real group checks

After automated acceptance, perform exactly two representative normal group commands, preferably historically BUSY-sensitive groups where physically safe.

Each evidence record must contain non-empty:

```text
group
command
timestamp              # timezone-qualified ISO-8601, after automated acceptance
command_result          # exactly PASS
physical_result         # exactly PASS
physical_observation    # human description of what was actually observed
```

The two records must name two distinct groups. Finalize also scans the same owner/container log interval covering these physical checks and refuses acceptance on BUSY/reset/ASH/disconnect/network-down evidence.

Example:

```json
{"group":"Lights All","command":"OFF","timestamp":"2026-09-09T11:40:00+02:00","command_result":"PASS","physical_result":"PASS","physical_observation":"selected room lights visibly switched off"}
```

Finalize:

```powershell
python deploy/p009_tool.py `
  --remote-template "rtk proxy ssh {host} {command}" `
  finalize `
  --session .local/p009/session.json `
  --group-evidence '<GROUP1_JSON>' `
  --group-evidence '<GROUP2_JSON>' `
  --confirm P009-FINALIZE
```

Finalize rechecks current identity and the same owner/start epoch. Clean phase: `ACCEPTED`.

`ACCEPTED` is a bounded operational screen, not long-term reliability certification. Stop testing after it passes.

## Hard STOP conditions

Stop immediately on any of:

- source/run/artifact/hash/byte-size mismatch;
- P009 profile not exactly RX512/BTT64/KEY12/MCAST26;
- linked +704-B evidence absent or mismatched;
- wrong EmberZNet/EZSP baseline;
- wrong/multiple Z2M owner;
- unexpected owner restart inside a bounded gate;
- backup/hash failure;
- WebUI uncertainty/flash failure;
- coordinator/network identity drift;
- new-network/reset/mass-rejoin behavior;
- incomplete or <15/16 active canary;
- BUSY / MAX_MESSAGE_LIMIT / NO_BUFFERS / MESSAGE_TOO_LONG during acceptance;
- NCP/ASH reset/disconnect/NETWORK_DOWN;
- malformed/incomplete MQTT evidence;
- Permit Join closure not freshly proven;
- inability to obtain the owner-bound Docker log evidence window.

Do not retry by adding delays, retries, tuning or extra diagnostic traffic after a hard stop.

## Rollback

If failure occurs **after P009 was actually flashed**:

1. preserve failure evidence;
2. stop Z2M;
3. manually flash **only the matched `stock-rollback` GBL from the same approved release artifact**;
4. do not reset NVM;
5. start stock Z2M and verify 9.1.1/EZSP19 plus original network identity.

If the NCP is completely unavailable to EZSP after the flash, rollback is still a manual SONOFF WebUI firmware operation; do not make network recovery conditional on a working EZSP session.

Do not restore the Z2M data tar merely because firmware was rolled back. Restore data only if configuration/database state was actually mutated or damaged:

```powershell
python deploy/p009_tool.py `
  --remote-template "rtk proxy ssh {host} {command}" `
  restore-data `
  --session .local/p009/session.json `
  --confirm P009-RESTORE-DATA
```

The restore validates the backup hash, quarantines failed data and revalidates core-file hashes. This archive is Zigbee2MQTT data recovery only; it is **not** a bit-for-bit Dongle-M ESP/NVM/bootloader recovery image. Preserve the SONOFF ESP settings/NVM during the in-place radio firmware update.

## Reporting

```powershell
python deploy/p009_tool.py report --session .local/p009/session.json
```

Never post plaintext network keys, MQTT passwords/tokens or other secrets.
