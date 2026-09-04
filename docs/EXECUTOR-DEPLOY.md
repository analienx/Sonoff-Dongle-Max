# P009 controlled deployment

This is a mechanical runbook for issue #1. Do not tune parameters, add retries, reset NVM, change channel/network identity, or re-pair devices.

## 0. Build

Both workflow jobs must be green. Download artifact `sonoff-dongle-max-p009-9.1.1`, extract it, then verify:

```bash
sha256sum -c SHA256SUMS
```

Required bundle content: one GBL/HEX/OUT under both `p009/` and `rollback-stock/`, plus `P009-BUILD-MANIFEST.json`. Any mismatch: **STOP**.

## Remote transport

Default:

```text
--remote-template "ssh {host} {command}"
```

For the existing proxy route:

```text
--remote-template "rtk proxy ssh {host} {command}"
```

The template must contain `{host}` and `{command}`. The deployment tool uses this one transport for all remote work; it does not require `scp`.

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

ARM verifies the full bundle hashes, exact P009/stock GBL hashes, one Z2M owner, baseline 9.1.1/EZSP19, and safe coordinator identity. The network-key plaintext is hashed inside the Z2M container and is never copied to the workstation. ARM creates a stopped-state Z2M tar backup and leaves Zigbee2MQTT **STOPPED**.

Check the next action at any time:

```powershell
python deploy/p009_tool.py --remote-template "rtk proxy ssh {host} {command}" status --session .local/p009/session.json
```

## 2. One manual WebUI flash

Upload **only the exact P009 GBL printed by ARM** through the already-proven SONOFF Dongle-M WebUI. Do not erase/reset NVM. If the WebUI reports any error, do not continue.

## 3. Identity gate

```powershell
python deploy/p009_tool.py `
  --remote-template "rtk proxy ssh {host} {command}" `
  postflash `
  --session .local/p009/session.json `
  --confirm P009-POSTFLASH
```

Required: same IEEE, PAN, extPAN, channel, network-key SHA256 fingerprint, key sequence and backup device count; EmberZNet 9.1.1 / EZSP19. On identity failure, the tool automatically stops Z2M and marks the session `STOPPED`.

## 4. Bounded automated acceptance

```powershell
python deploy/p009_tool.py `
  --remote-template "rtk proxy ssh {host} {command}" `
  acceptance `
  --session .local/p009/session.json `
  --confirm P009-ACCEPT
```

This performs only:

- active read-only 2x8 real ZCL canary;
- exactly 5 x 10-second Permit Join All windows, serial, no pairing and no retry;
- test-window scan for BUSY/message-pressure failures and NCP/ASH reset/disconnect/network-down.

Any failure marks the session `STOPPED`. No soak and no parameter matrix.

## 5. Exactly two group checks + finalize

Issue exactly two representative real group commands at normal pacing and verify the physical loads. Then record both observations:

```powershell
python deploy/p009_tool.py finalize `
  --session .local/p009/session.json `
  --group-evidence "<group 1 command + physical result>" `
  --group-evidence "<group 2 command + physical result>" `
  --confirm P009-FINALIZE
```

`ACCEPTED` means stop testing.

## Report

```powershell
python deploy/p009_tool.py report --session .local/p009/session.json
```

The report is generated from the session rather than handwritten evidence.

## Optional runtime overlay

Do **not** deploy it unless separately instructed after firmware-only testing. Artifact: `sonoff-dongle-max-herdsman-p009-10.9.1`. It is pinned and fail-loud and must be delivered as a separate custom add-on/image, never by editing the official add-on container in place.

## Rollback

1. stop Z2M;
2. manually flash the exact `rollback-stock` GBL from the same verified build artifact;
3. only if Z2M data was damaged/mutated, restore the stopped-state data:

```powershell
python deploy/p009_tool.py `
  --remote-template "rtk proxy ssh {host} {command}" `
  restore-data `
  --session .local/p009/session.json `
  --confirm P009-RESTORE-DATA
```

The restore verifies the tar SHA256 and stopped-state file hashes and quarantines the failed directory.
