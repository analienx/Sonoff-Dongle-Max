# P009 controlled deployment

This is the **mechanical operator runbook**. The supervisor owns firmware/code/design. The executor must not tune parameters, patch code, add retries, change network identity, reset NVM or broaden testing.

The deployment issue must pin the exact approved commit, Actions run, artifact ID, P009 GBL SHA256/size and matched rollback GBL SHA256/size. If those values are absent or disagree with `P009-BUILD-MANIFEST.json`, **STOP**.

## 0. Approved build gate

All three Actions jobs for the exact approved source commit must be green:

1. P009 + stock rollback NCP;
2. optional P009 runtime overlay;
3. P010 diagnostic overlay.

The first production test uses **only the firmware artifact**; the other two jobs being green proves their buildability, not authorization to deploy them.

Download `sonoff-dongle-max-p009-9.1.1`, extract it, and verify:

```bash
sha256sum -c SHA256SUMS
```

The hardened artifact must include at least:

```text
P009-BUILD-MANIFEST.json          schema 2
P009-TOOLCHAIN-EVIDENCE.txt
P009-DEPLOY.txt
source-profile/
generated/p009/
generated/rollback-stock/
linked/
p009/
rollback-stock/
SHA256SUMS
```

`P009-BUILD-MANIFEST.json` binds the exact repository source commit, builder pin, RX512/BTT64/KEY12/multicast32 source profile, linked-ELF evidence and artifact hashes. The approved linked profile requires `.bss` delta **728 B** and unchanged memory-manager reservation. Any mismatch: **STOP before touching HA**.

Work from the exact source commit recorded in the manifest. Hardened `arm` rejects a different local Git HEAD.

## Remote transport

Existing proxy route:

```text
--remote-template "rtk proxy ssh {host} {command}"
```

The template must contain `{host}` and `{command}`. Once ARMED, the session locks host, add-on, Z2M path and remote transport; do not switch them mid-session.

## 1. Snapshot + ARM

```powershell
python deploy/p009_tool.py `
  --remote-template "rtk proxy ssh {host} {command}" `
  arm `
  --bundle-root .local/p009/firmware `
  --build-manifest .local/p009/firmware/P009-BUILD-MANIFEST.json `
  --session .local/p009/session.json `
  --confirm P009-ARM
```

ARM now proves more than the old runbook:

- exact source commit matches build manifest;
- whole bundle hashes valid;
- exact P009/stock GBL SHA256 **and byte size** valid;
- P009 source profile is RX512/BTT64/KEY12/multicast32 and stock rollback is RX128/BTT30/key1/multicast26;
- linked-ELF evidence in manifest was validated by CI, including the 728-B `.bss` delta;
- exactly one running Zigbee2MQTT container exists;
- it is the exact expected HA add-on container, not merely a similarly named process;
- Docker container ID and `StartedAt` are captured;
- current Docker-start-epoch logs show EmberZNet 9.1.1 / EZSP19;
- the running Z2M process answers a correlated MQTT `health_check` request with `status=ok` and `data.healthy=true`;
- coordinator IEEE/PAN/extPAN/channel come from current `bridge/info`;
- network-key plaintext stays on HA; only its SHA256 fingerprint comes from `coordinator_backup.json` inside the current owner container;
- stopped-state hashes are captured for `configuration.yaml`, `database.db`, `coordinator_backup.json`;
- stopped-state tar backup is created and hashed;
- after the add-on is stopped, there is no residual Zigbee2MQTT container;
- session reaches exactly `ARMED`.

The backup file is **not** represented as a live NCP identity read. Its key fingerprint/device count are backup evidence; current network fields come from the active owner session.

If ARM fails or is interrupted after session creation, the session is `STOPPED`. Do not repair around it.

Check state:

```powershell
python deploy/p009_tool.py `
  --remote-template "rtk proxy ssh {host} {command}" `
  status `
  --session .local/p009/session.json
```

### Required ARMED report

Post only secret-safe evidence:

- approved source commit/run/artifact;
- verified P009 GBL path + bytes + SHA256;
- verified rollback GBL path + bytes + SHA256;
- session phase `ARMED`;
- current-session identity fields/fingerprints;
- Docker owner/start evidence;
- stopped-state backup path + SHA256;
- confirmation Z2M is STOPPED and no residual owner exists.

Then **STOP before WebUI flash** until the human/supervisor authorizes that exact artifact.

## 2. Manual WebUI flash + artifact acknowledgment

Upload only the exact P009 GBL printed by ARM through the proven SONOFF Dongle-M WebUI.

Forbidden:

- NVM erase;
- factory reset;
- new-network creation;
- channel/key/PAN changes.

After WebUI reports success, acknowledge the exact ARM-verified SHA:

```powershell
python deploy/p009_tool.py `
  --remote-template "rtk proxy ssh {host} {command}" `
  confirm-flash `
  --session .local/p009/session.json `
  --observed-sha256 <EXACT_P009_SHA256_FROM_ARM> `
  --confirm P009-FLASHED
```

This is **human artifact acknowledgment**, not device-side firmware attestation. Do not claim otherwise. A future identity-only XNCP variant is intended to close that gap.

## 3. Current-session post-flash identity gate

Run:

```powershell
python deploy/p009_tool.py `
  --remote-template "rtk proxy ssh {host} {command}" `
  postflash `
  --session .local/p009/session.json `
  --confirm P009-POSTFLASH
```

The tool expects the add-on still to be stopped, starts it itself, and collects a **new** current-owner session.

Required:

- new Docker start epoch versus pre-arm;
- exact expected Z2M add-on owner;
- current-session 9.1.1 / EZSP19 evidence;
- same coordinator IEEE;
- same PAN;
- same extPAN;
- same channel;
- same network-key SHA256 fingerprint;
- same key sequence;
- same backup device count;
- unchanged `configuration.yaml` for this firmware-only test.

Expected phase: `IDENTITY_VERIFIED`.

The stock-host contract at this point is intentionally recorded as:

```text
BTT: binary=64; stock herdsman does not rewrite it downward
KEY: binary=12; stock herdsman does not rewrite it downward
MULTICAST: binary=32; firmware-side membership capacity
children: binary capacity=64; stock host normally requests runtime max=32
NEW_BROADCAST_ENTRY_THRESHOLD: separate runtime admission policy; not changed in first test
```

Do **not** deploy the six-value P009 runtime overlay in order to manufacture a threshold readback during this first test.

Any post-flash failure stops Z2M, persists available evidence and marks `STOPPED`.

## 4. Bounded automated acceptance

```powershell
python deploy/p009_tool.py `
  --remote-template "rtk proxy ssh {host} {command}" `
  acceptance `
  --session .local/p009/session.json `
  --confirm P009-ACCEPT
```

### Active canary

The script must schedule and complete exactly:

```text
2 rounds x 8 known mains-powered targets = 16 unique transactions
```

Pass requires:

- exactly 16 scheduled;
- exactly 16 completed;
- exactly 16 unique result IDs;
- >=15 successes;
- no global timeout;
- no malformed correlated MQTT evidence.

`15/15` is **not** a pass.

After the active phase, the Python coordinator checks the exact log delta **before starting Permit Join**. A hard BUSY/message-pressure/reset/disconnect signature stops the test immediately; no Permit Join stimuli follow.

### Permit Join

Clean success path:

```text
exactly 5 serial Permit Join All trials
10 seconds each
no pairing
no executor-added retry
```

On the **first failed trial**, no further opening stimulus is scheduled.

Each trial requires:

- correlated bridge response;
- no BUSY / max-message / no-buffer / message-too-long evidence in its window;
- a fresh `bridge/info` observation showing `permit_join=false` after the window.

Cleanup always attempts a correlated `time:0` close and requires a fresh `permit_join=false` observation. Cleanup is safety work, not an extra success trial.

The full acceptance log delta must remain exact; log rotation/loss means evidence is incomplete and the gate fails rather than printing a warning.

The same Docker container ID/start epoch must own the adapter from acceptance start to end.

Partial active/Permit Join evidence is persisted into the session **before** STOP handling.

Expected clean phase: `AUTOMATED_ACCEPTANCE_PASSED`.

## 5. Exactly two structured real group checks

After automated acceptance passes, issue exactly two representative normal group operations. Prefer historically BUSY-sensitive groups when safe.

For each one record:

- group/entity/topic;
- exact command;
- timestamp;
- command result from HA/Z2M/MQTT;
- human-verified physical result.

Finalize requires each evidence item as JSON. Example shape:

```json
{"group":"Lights All","command":"OFF","timestamp":"2026-09-07T21:00:00+02:00","command_result":"Z2M accepted","physical_result":"selected loads switched off"}
```

PowerShell example:

```powershell
python deploy/p009_tool.py `
  --remote-template "rtk proxy ssh {host} {command}" `
  finalize `
  --session .local/p009/session.json `
  --group-evidence '{"group":"<group1>","command":"<cmd>","timestamp":"<ISO8601>","command_result":"<result>","physical_result":"<human verified>"}' `
  --group-evidence '{"group":"<group2>","command":"<cmd>","timestamp":"<ISO8601>","command_result":"<result>","physical_result":"<human verified>"}' `
  --confirm P009-FINALIZE
```

Finalize rechecks current identity and requires the **same Docker owner/start epoch as postflash**. Clean result: `ACCEPTED`.

`ACCEPTED` means stop testing. It is a bounded operational acceptance result, not long-term reliability certification.

## Report

```powershell
python deploy/p009_tool.py report --session .local/p009/session.json
```

Post the generated report plus both structured group observations. Never paste plaintext network keys, MQTT credentials or tokens.

## Hard STOP conditions

Stop immediately on any of:

- artifact/source/hash/byte-size mismatch;
- linked evidence absent/unvalidated or not the approved +728-B multicast32 profile;
- wrong baseline 9.1.1/EZSP19;
- wrong/multiple Z2M owner;
- unexpected owner restart during a bounded gate;
- backup/hash failure;
- WebUI uncertainty or flash error;
- post-flash network identity drift;
- new-network/reset/mass-rejoin behavior;
- active canary incomplete or <15/16;
- BUSY / MAX_MESSAGE_LIMIT / NO_BUFFERS / MESSAGE_TOO_LONG during acceptance;
- NCP/ASH reset/disconnect/NETWORK_DOWN;
- malformed/incomplete MQTT evidence;
- Permit Join closure not freshly proven;
- log-window loss/rotation during the bounded gate.

Do not “try again”, add delays/retries, change tuning or generate extra diagnostic traffic after a hard-stop event.

## Optional overlays

Do **not** deploy during first P009 acceptance:

- `sonoff-dongle-max-herdsman-p009-10.9.1` — behavior-changing runtime policy;
- `sonoff-dongle-max-herdsman-p010-observability-10.9.1` — diagnostic-only BUSY counter snapshot.

If residual BUSY survives accepted P009 operation, the supervisor decides whether/when P010 is justified.

## Rollback

If failure occurs after firmware was actually flashed:

1. preserve the failure evidence;
2. stop Z2M;
3. manually flash **only the matched `rollback-stock` GBL from the same approved artifact**;
4. do not reset NVM;
5. start stock Z2M and verify 9.1.1/EZSP19 + original network identity.

Do not restore the Z2M data tar just because firmware was rolled back. Restore data only if the configuration/database itself was actually mutated/damaged:

```powershell
python deploy/p009_tool.py `
  --remote-template "rtk proxy ssh {host} {command}" `
  restore-data `
  --session .local/p009/session.json `
  --confirm P009-RESTORE-DATA
```

The restore verifies tar SHA256, quarantines failed data and validates restored core-file hashes. Any interrupted restore stays `STOPPED`.
