# MR4U P10: reusable cutover preparation (2026-09-24)

**Start with the ordered [upstream-aligned cutover runbook](P10_UPSTREAM_CUTOVER_RUNBOOK.md) and `analienx/config:skills/zigbee-coordinator-migration/SKILL.md`.** This document explains existing scripts and real evidence. Neither the scripts nor offline tests have migrated or restored the existing Zigbee network. Do not publish actual radio IEEE addresses, private household device IDs, raw backup files or network keys.

## Recovery artifacts already captured

- OPTIONAL broad recovery point: Home Assistant full backup `sonoff-mr4u-precutover-20260924` (slug `edbb94f6`), ~2.20 GB, includes the Zigbee2MQTT add-on; a separate full backup dated September 23 also exists. The full HA backups were created and their metadata verified, but have **not** undergone restore testing. **Creating another full HA backup is NOT a cutover prerequisite.**
- `p10_cutover_prepare.py capture` retrieved **only the named** `configuration.yaml`, `coordinator_backup.json`, `database.db`, `state.json` and any listed optional files via verified SSH/SFTP into private storage. It checks length/mtime and SHA-256 per file and refuses overwrite. It is **not an atomic or complete data-directory backup while Z2M is running**: custom converters/extensions, other local data and HA add-on options outside YAML might not be captured. A final **complete cold Zigbee2MQTT data-folder + add-on settings** snapshot must be taken after Z2M stops. The radio's original NVRAM/network state remains physically on the preserved SONOFF and is NOT exported by copying files.
- Last private database inventory: 61 routers, 45 end devices, one coordinator, 21 groups. `type=Group` rows with `groupID` are supported by the corrected parser. Source config was staged byte-for-byte as `rollback_configuration.yaml`; baseline retained private device and group IDs.
- The existing Ember backup has `devices=[]`; this can be expected by design and is not proof of lost Zigbee2MQTT device records. A device database or matching record count does not demonstrate complete Trust Center key restoration to a different stack.

## Actual connection and radio isolation

- Production Z2M currently opens SONOFF over its HA `/dev/serial/by-id/...` USB path with `serial.adapter=ember` and 115200 baud. The replacement CC2674P10 answered on **Zephyrus COM4** at revision `20260310`, but a Windows COM port is not an HA TCP path.
- Use the **actual MR4U unit's** SMLIGHT UI to identify the CC2674P10 *chip*, installed Z-Stack coordinator image, radio mode, LAN address and configured socket; labels and default port `7638` are not sufficient proof of which radio is exposed. Prefer wired Ethernet/PoE and a stable LAN address. Release any COM4/USB client before TCP access and ensure no other ZHA/Z2M/OTBR or MR4U hub process owns this Zigbee radio. Do not allow it to form the copied household network during connectivity checks.
- `p10_target_endpoint.py` sends read-only ZNP SYS_PING/SYS_VERSION **from Home Assistant** to the chosen private LAN IPv4 and socket, comparing expected P10 firmware revision. It does **not** independently prove physical board identity, exclusive serial ownership, current network/security state or effective coordinator IEEE. After SMLIGHT LAN setup:

```text
py -3 deploy/p10_target_endpoint.py --host <MR4U-LAN-IP> --port <VERIFIED-P10-PORT> --expected-revision 20260310
```

- Source radio isolation is a **separate physical step** after Z2M stops: preserve the SONOFF's NVRAM, account for every USB/PoE/other power path, positively prevent its Zigbee radio transmitting, and prevent Z2M/add-on watchdogs or another process from reopening it. Do not run two coordinators with cloned identity/network state together. On rollback isolate the **P10 Zigbee radio** before reactivating SONOFF; the MR4U's independent Thread radio need not be switched off if its Zigbee radio is demonstrably isolated.

## Private preparation scripts (not a live cutover)

```text
# OPTIONAL: inspect existing broad HA backup without creating another one:
py -3 deploy/p10_native_ha_backup.py --name sonoff-mr4u-precutover-20260924
# Provisional, named-file live snapshot; use fresh unique private paths:
py -3 deploy/p10_cutover_prepare.py capture --out C:/Workspace/.analienx/sonoff-private/issues/p10/snapshots/UNIQUE
py -3 deploy/p10_cutover_prepare.py inspect --source C:/Workspace/.analienx/sonoff-private/issues/p10/snapshots/UNIQUE
# Exact rollback YAML and proposed target YAML after endpoint verification only:
py -3 deploy/p10_config_stage.py --snapshot C:/Workspace/.analienx/sonoff-private/issues/p10/snapshots/UNIQUE --out C:/Workspace/.analienx/sonoff-private/issues/p10/staged/UNIQUE --native-backup-slug edbb94f6
# Current private baseline of all device/group identities:
py -3 deploy/p10_device_acceptance.py baseline --snapshot C:/Workspace/.analienx/sonoff-private/issues/p10/snapshots/UNIQUE --out C:/Workspace/.analienx/sonoff-private/issues/p10/acceptance/UNIQUE.json
```

For target YAML, add `--target-host` and `--target-port` to `p10_config_stage.py` **only after the HA-to-P10 TCP probe works**, using a NEW output directory. This renderer changes only the existing `serial.port` and `serial.adapter` lines; it does not write the coordinator IEEE, form a network or edit live HA. Review any HA add-on configuration/environment overrides outside YAML, serial flow control and target baud separately. Preserve old PAN/extended PAN, key and channel 11. Do not upgrade firmware or Z2M and migrate simultaneously.

## Maintenance-window operator sequence — scripts do NOT execute it

1. Freeze unrelated changes and record cutover timestamp, current source network identity and representative unicast/groupcast/metering/automation and route-error baseline.
2. Stop Z2M and verify the add-on is stopped, cannot auto-restart and has released SONOFF. Take the **final complete cold** Z2M data directory and add-on settings copy; verify private hashes and keep the old radio's stored state intact. Current `p10_cutover_prepare.py` needs expansion or an independent complete-directory backup operation; it cannot by itself satisfy this step.
3. Physically isolate the old SONOFF radio; then restore the **existing** Zigbee network state to the verified MR4U P10. Copy and verify the *effective* coordinator IEEE using an appropriate supported P10 procedure (factory-primary vs configurable-secondary IEEE matters), PAN ID, extended PAN ID, channel, network key, key sequence/counters and Trust Center behavior. Zigbee2MQTT says Ember↔Z-Stack cross-stack migrations are **not officially supported** and may need targeted re-pairing; a successful boot alone does not establish network compatibility. Do not delete original `coordinator_backup.json` or `database.db` to suppress a mismatch error.
4. Deploy the minimal staged target YAML via `analienx/config:skills/home-assistant-local-executor/SKILL.md` and its deterministic mutation safety rules, start exactly one Z2M client on the P10, confirm logs say existing network restored rather than newly formed, and verify active IEEE and identity.
5. Observe newly reporting devices against the private baseline and separately test real bidirectional commands, groups, metering, essential HA automations, security rejoins, a controlled test pairing, missing-router diagnostics and route/source-route trends. Zigbee mesh routing may settle over minutes or hours; avoid repetitive whole-mesh scans. Sleepy/end devices and intentionally relay-off bulbs need independent observation windows.
6. KEEP the P10 only if agreed critical checks pass. Otherwise stop Z2M, isolate MR4U Zigbee radio, restore exact old config and only any corresponding old application files actually needed, reactivate intact SONOFF, restart Z2M once and check communication. Frame-counter and rejoin behavior may make rollback less immediate; do not blindly flash stale radio-state backups or run two cloned networks simultaneously. Record any targeted re-pairs because they affect reversibility.
7. Capture a new backup on the coordinator ultimately kept, plus a narrow Z2M data snapshot and measured acceptance results. Existing 61 routers in the mesh and 400 provisioned P10 TCLK slots are NOT proof of a 60-entry direct-neighbor allocation.

## Existing acceptance helper and test scope

```text
py -3 deploy/p10_device_acceptance.py compare --baseline C:/Workspace/.analienx/sonoff-private/issues/p10/acceptance/UNIQUE.json --post-snapshot C:/Workspace/.analienx/sonoff-private/issues/p10/snapshots/POST_UNIQUE --cutover-utc 2026-09-24T12:00:00+02:00 --out C:/Workspace/.analienx/sonoff-private/issues/p10/acceptance/POST_UNIQUE.json
```

The command reports private device/group retention and `lastSeen` since cutover, **not** bidirectional traffic or group delivery. `p10_neighbor_capacity.py` and `p10_capacity_gate.py` are separate limited-evidence diagnostics; use TI-specific `bridge/request/coordinator_check` (only if supported) to diagnose missing routers, not to infer the maximum table allocation. Our synthetic protocol and config tests do not prove a cross-stack restore or rollback.

**Evidence to date:** real confidential SFTP snapshot, original rollback YAML/hash, optional real HA backup, MR4U P10 USB identification/400 TCLK NV-length slots; fake TCP radio and snapshot/parser/staging tests. No actual HA-to-MR4U TCP endpoint probe, source IEEE transfer, completed cold full Z2M data copy, cross-stack restore, SONOFF isolation, live cutover or rollback has been performed.