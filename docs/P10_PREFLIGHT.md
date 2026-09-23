# P10 candidate evaluation — separate from production SONOFF

Tracking: reliability epic #18, neighbor investigation #28. This kit audits **SLZB-06P10/P10U firmware**, without changing Zigbee2MQTT, network identity, IEEE address, keys, NVRAM, channel, or pairing. Tested only with mocked ZNP serial frames until a P10 is physically connected.

## 1. Read-only identification on Zephyrus

Leave the SONOFF as the only production coordinator on the Raspberry Pi. Attach only the new P10 over USB to the laptop; do not attach it to the production Zigbee2MQTT owner or copy coordinator data. For Ethernet/USB models switch the SMLIGHT bridge to USB mode locally (this may interrupt its own Ethernet bridge), and identify its dedicated COM port. Do **not** run these scripts against the existing coordinator or a `socket://` URL. If the new device starts or broadcasts any preconfigured network after power-on, do not join it to the household mesh.

```powershell
py -3 -m pip install pyserial
py -3 deploy/p10_readonly.py ports
py -3 deploy/p10_readonly.py inspect --port COM7 --baud 115200 --isolated-host-confirmed --out C:/Workspace/.analienx/sonoff-private/issues/p10/p10-usb-identification.json
```

Replace COM7 with the P10's enumerated port. The script opens only that port, deasserts DTR/RTS before opening it, and sends **only ZNP SYS_PING and SYS_VERSION**. Opening some USB serial bridges may still change DTR/RTS momentarily at the OS/driver level; avoid a production coordinator regardless. Baud options: 115200, 460800, 921600; select the vendor-documented rate. The script never retries other ports automatically or resets the chip. A failed response is `UNKNOWN`, not proof that the firmware is unsupported. Preserve the original factory image; do not flash during this stage. The output stores no IEEE addresses or keys. Never publish raw serial logs or network backups.

## 2. Firmware/image audit

The response is a firmware-reported ZNP version, **not** a vendor-unique build hash and not a table-capacity query. Copy the exact vendor image to a private staging directory only if there is a provenance-verified download. Fingerprint a local file without modifying it:

```powershell
py -3 deploy/p10_readonly.py artifact C:/path/to/EXACT-vendor-P10-coordinator.hex
py -3 deploy/p10_firmware_audit.py docs/p10_firmware_candidates.json --min-neighbor 60 --min-tclk 100
```

Update the candidate manifest only with values from the **exact image's** build config, map file, vendor confirmation, or independently observed proof (record provenance and SHA-256). `MAX_NEIGHBOR_ENTRIES=50` in a *different* CC2652P7 build does not prove a P10 image is configured likewise. Standard Mgmt_Lqi responses show current neighbor entries, not allocated maximum. A candidate must also have adequate routing, source-route and TCLK tables and an independently validated groupcast path; successful USB identification alone is never a migration decision. `--min-tclk 100` is a provisional conservative planning threshold, **not** a claim that every joined router consumes one TCLK record. Determine the actual backup key-record demand privately without publishing keys.

## 3. Candidate comparison / public evidence

- **Factory SMLIGHT P10 coordinator image:** inspect and preserve first. Board-level fit is strongest, but no exact-build direct-neighbor/TCLK capacities have been verified for our purchased unit. Firmware *bridge/UI* version is not the CC2674 Zigbee firmware version.
- **Latest SMLIGHT P10 image offered to the exact board:** consider only after checking its release notes, binary hash, secure fallback/bootloader and actual table allocation. A version reported on an MR4U, 07P10 or a SONOFF PP10 is **not** automatically available or compatible with a 06P10.
- **Koenkk `20250321`:** release notes mention an attempted `BUFFER_FULL` fix and SimpleLink SDK 8.30.01.01, but the published CC2674P10 binary is marked WIP/unavailable. Never flash the CC2652P7 image onto a CC2674P10.
- **Koenkk `20240710` / `20221226`:** useful Z-Stack regression histories, **not verified P10-compatible flash candidates**.
- **SONOFF Dongle-PP10 stock `20250321`:** not SMLIGHT hardware firmware. A public ~75-device restore reported `tclk table size insufficient (size=40)`; a separate groupcast `NWK_NO_ROUTE` report exists. Treat these as P10 test requirements, not as proof of the SMLIGHT firmware's capacities.

Sources: https://github.com/Koenkk/Z-Stack-firmware/releases ; https://github.com/Koenkk/Z-Stack-firmware/discussions/545 ; https://github.com/Koenkk/zigbee2mqtt/issues/32885 ; https://www.zigbee2mqtt.io/guide/adapters/zstack.html ; https://software-dl.ti.com/simplelink/esd/simplelink_cc26x2_sdk/2.30.00.34/exports/docs/zstack/html/zigbee/znp_interface.html

## 4. Gates before any migration

1. Exactly identified product/board revision, ZNP revision and source-backed firmware SHA; evidence of **>=60 stable direct-router capacity**, including bidirectional Link Status across more than 26 entries; enough security, route and source-route capacity for the private backup.
2. A separate disposable network that tests 60+ independently verified, simultaneously reachable routers, groupcasts, unicast retries, joins and power-monitoring traffic. Mgmt_Lqi pagination must not be confused with capacity. Capture actual routing and delivery metrics with fixed devices and equal windows.
3. Written rollback, network-state migration validation, security frame-counter monotonicity, Zigbee2MQTT entity compatibility and no forced mass repair. Cross-stack Ember -> Z-Stack backup transfer is not guaranteed; do not overwrite the current SONOFF backup or presume same-stack migration guidance applies.

**No automatic firmware selection or flashing is implemented.** The audit intentionally returns `BLOCKED` until exact-build evidence and an isolated validation exist.

## 5. Additional version-specific findings (2026-09-23)

The public **SMLIGHT** P10 image lineage is broader than the Koenkk release list. A July 2026 issue shows an SLZB-06P10 running radio build `20240716` with core/ESP bridge `v3.3.1`; another July report shows an SLZB-06P10 radio `20240705` in a 115-device network with `NWK_TABLE_FULL` after router power cycling and low *ESP32 host* heap. The ESP32 host heap must **not** be confused with CC2674P10 radio heap. In an August 2026 Zigbee2MQTT issue, an SLZB-06P10 was running radio `20260310` and core `v3.3.1`. An independent July forum report describes **development/beta** radio `20260311` (115200 baud, SDK 8.32.00.07) and a positive nine-day observation, which is anecdotal and not table-capacity evidence. A SMLIGHT upstream firmware manifest diff also refers to revision `20250201`, but the exact firmware's board applicability and resources need confirmation. **Do not equate radio revision with SMLIGHT core/ESP firmware v2.x/v3.x.**

Firmware evaluation priority: (a) preserve and inspect the *actual factory image*; (b) compare the latest **stable, exact-board SMLIGHT radio firmware** after finding its release notes and SHA; (c) retain `20260310` as a contemporary reference and `20260311` as a separately tested beta possibility, not an automatic upgrade. Older `20240705`/`20240716` and `20250201` are compatibility/regression reference points. Do not downgrade to any image lacking a verified P10 recovery path. The observed SONOFF PP10 groupcast/TCLK incidents are tests to replicate, not proof about SMLIGHT builds.

Relevant dated reports: https://github.com/Koenkk/zigbee2mqtt/issues/32751 (radio 20260310); https://github.com/Koenkk/zigbee2mqtt/issues/32706 (radio 20240716); https://github.com/Koenkk/zigbee2mqtt/issues/32667 (radio 20240705, host heap distinct); https://forum.iobroker.net/topic/84679/zigbee-adapter-mit-lan-dongle-kein-automatisches-verbinden/17 (20260311 beta); https://github.com/home-assistant/core/issues/165159 (SMLIGHT reported latest-version value can be stale). Confirm exact target board and firmware artefact before any flash.
