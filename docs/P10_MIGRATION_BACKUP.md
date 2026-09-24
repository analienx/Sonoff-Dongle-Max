# MR4U P10 migration: real recovery point and device records (2026-09-23)

## Verified native HA backup (private; never put backup or keys in Git)

- Native Home Assistant Supervisor full backup `sonoff-mr4u-precutover-20260923` / slug `5fd213dd` completed with no job errors; approximately 2.19 GB. Backup metadata includes Home Assistant data and the installed Zigbee2MQTT add-on (`45df7312_zigbee2mqtt`). This is a **backup capture**, not a tested restore or proof of coordinator-state migration.
- Live Zigbee2MQTT database observation: 107 records, including 61 Routers, 45 EndDevices, one Coordinator. An independent HA database snapshot is included by the full HA backup; it does not mean all 106 per-device trust-center keys can be exported.
- The existing Ember coordinator backup reports `devices=[]`; source code sets `ALLOW_APP_KEY_REQUESTS=false` and uses `ALLOW_APP_KEY_REQUESTS ? await this.exportLinkKeys() : []` when creating the backup. Thus this empty list can be normal. **Never manufacture per-device link keys from database.db.**
- The Ember backup preserves network-level material but a direct Ember → Z-Stack restore is not automatically supported. Preserve coordinator IEEE, PAN/extended PAN, channel, security frame counters and trust-center state; independently validate target restore and recovery procedure. Current full-backup `protected=false` is local-only; handle as containing credentials and Zigbee network keys.

## Reusable offline verifier (no live HA/USB operations)

```
py -3 deploy/p10_migration_backup.py inspect --source C:/private/z2m-data
py -3 deploy/p10_migration_backup.py snapshot --source C:/private/z2m-data --output C:/private/z2m-snapshots/precutover-unique.zip
```

The source is an **already retrieved private Zigbee2MQTT data directory**, not the root of Home Assistant. The script checks database identity uniqueness and role counts separately from coordinator backup device/key records, tests for essential network fields, archives without overwriting, re-opens and verifies every archived byte, and prints only role counts, status and SHA-256 hashes. Archive creation may succeed while migration preflight still requires review. Never upload generated ZIP, private input, or credentials to GitHub; use NTFS-restricted local storage or the native HA backup manager.

## Blocks before cutover

1. Independently document source and target network-state transfer and a non-destructive rollback; no assumption that Ember backup `devices=[]` is corrupt or that it guarantees all per-device keys transfer.
2. Verify running MR4U radio identity and 400-slot provisioned TCLK finding. Neighbor, source-routing and routing allocation remain unverified; 61 total routers are not necessarily 61 direct neighbors.
3. Capture fresh pre-cutover baseline and backup, preserve old SONOFF radio state, prevent two coordinators with cloned network keys/identity from operating simultaneously, and require explicit approval before stopping the live network.
4. During any bounded cutover, validate unicast, groupcast, router retention, application delivery, security rejoins, and reversible recovery. Rollback is a potential second migration, not a guaranteed plug-swap.

## Reusable native HA full-backup capture helper

The isolated Zephyrus helper `deploy/p10_native_ha_backup.py` uses the canonical host-key-verified `analienx/config` SSH connector, not embedded passwords. Without `--create` it **only checks** a named backup's Supervisor metadata; with explicit `--create` it executes exactly one native full-backup command, refuses another running backup and refuses to overwrite an existing name. It does not interact with Zigbee coordinators or read archive contents.

```
py -3 deploy/p10_native_ha_backup.py --name sonoff-mr4u-precutover-20260923
# Only for a separately authorized, unique new recovery point:
py -3 deploy/p10_native_ha_backup.py --name unique_pre_migration_name --create
```

The first command has been run against the real completed backup and verified `type=full`, `homeassistant_included=true`, `zigbee2mqtt_addon_included=true`, slug `5fd213dd` and size 2,192,373,760 bytes. This metadata does not independently prove an archive restore, radio NVRAM readback, or target coordinator compatibility. Keep the native backup on the Home Assistant host; do not expose a ZIP or network keys through GitHub, MQTT logs or this report. `--create` is not a migration command and never alters the live coordinator.
