# SONOFF Ember → SMLIGHT MR4U CC2674P10: USB replacement workflow

**Primary topology: a physical USB swap on the Home Assistant host.** The MR4U does NOT have to be visible to HA while the SONOFF remains connected. Preserve the original Zigbee network, coordinator identity, database, application data and SONOFF NVRAM. No full Home Assistant backup is required. The optional Ethernet/TCP tools remain available for a *different* topology; do not mix their port settings into this USB sequence. Raw archives, IEEE addresses, keys, add-on options and device identities stay in the private Windows workspace—not Git.

**Radio identity:** Current SMLIGHT MR4U product specifications name CC2674P10 as Radio 1 and EFR32MG26 as Radio 2. Earlier notes mistakenly called the P10 Radio 2. Determine the actual ZNP/P10 interface by chip, vendor UI, firmware and the probe—not a numeric label, `COM4`, `ttyACM0`, an assumed TCP port, or the first by-id entry. Before reconnecting a physical source/target radio, ensure its application cannot auto-start; never power two coordinators carrying copied network identity at once.

## 1. Prepare with the SONOFF still operating (no outage)

- Keep the previous verified private hot bundle and source-only stage: complete Zigbee2MQTT data directory (except generated logs), addon options, 107 records/21 groups and exact rollback configuration. Check the actual source SHA from the *fresh* private staging report, not from a historical example. The old SONOFF must retain its original NV/network state for rollback.
- Check Home Assistant/Zephyrus remote access and that `deploy/p10_outage_freeze.py` DRY RUN reports the expected Ember YAML, addon boot mode and Zigbee2MQTT running. It does **not** stop the app by default. Set aside an independent access path to HA for the outage. The MR4U can remain offline from HA; any separate COM4 test on Zephyrus is not a Home Assistant USB-path discovery.
- For your installation, `serial.port`, `serial.adapter` and `serial.baudrate` exist in BOTH the Zigbee2MQTT YAML and separate HA add-on options. Both layers must be staged and applied together. The old two-line YAML-only migration is insufficient. Keep channel 11, network key/PAN/extended PAN and group/device records unchanged.

## 2. Start the deliberate outage, THEN disconnect SONOFF

From the authorized Zephyrus repository root, use the **fresh** source YAML hash from the private stage:

```text
py -3 deploy/p10_outage_freeze.py --expected-source-config-sha256 SOURCE_SHA256 --out C:/Workspace/.analienx/sonoff-private/issues/p10/bundles/cold-UNIQUE.zip
```

Review its read-only output. At the authorized cutover only, run the SAME command with `--execute --approval STOP_Z2M_FOR_MR4U_MIGRATION`. It stops only the Zigbee2MQTT add-on, verifies it remains stopped, then captures/verifies the complete private COLD bundle and its add-on options. **Do not disconnect the SONOFF unless the result confirms `SOURCE_ADDON_STOPPED_COLD_BUNDLE_VERIFIED`.** If the stop or cold capture fails, leave the SONOFF in place; do not try to activate the MR4U. Keep the source add-on stopped after successful capture.

Now physically unplug/isolate the SONOFF's Zigbee radio from every power source, preserving its firmware and retained coordinator state. This physical check is not replaceable by a Python flag. Connect the MR4U to the Home Assistant USB host, with its actual P10 radio in USB/ZNP coordinator mode; close any Windows COM4 client that owns that radio. If the MR4U exposes only its management USB and no ZNP radio on HA, switch the appropriate interface in the SMLIGHT UI using its supported procedure—do not reset or commission a new household Zigbee network.

## 3. Identify the replacement FROM HA, after the USB swap

```text
py -3 deploy/p10_usb_cutover.py discover --cold-bundle C:/Workspace/.analienx/sonoff-private/issues/p10/bundles/cold-UNIQUE.zip
```

The script requires the cold archive, stopped add-on, and absence of the original SONOFF by-id port, then displays the *currently present* stable `/dev/serial/by-id/…` USB paths on HA. Select the MR4U's actual P10 interface. Avoid unstable `/dev/ttyACM0`, Zephyrus `COM4`, Radio-2 guesses, and a USB management/debug port. Probe that exact path using:

```text
py -3 deploy/p10_usb_cutover.py stage --cold-bundle C:/Workspace/.analienx/sonoff-private/issues/p10/bundles/cold-UNIQUE.zip --out C:/Workspace/.analienx/sonoff-private/issues/p10/staged/usb-UNIQUE --target-by-id /dev/serial/by-id/EXACT_VERIFIED_P10_PATH
```

This sends only ZNP SYS_PING and SYS_VERSION from HA to the selected idle USB port and checks the previously observed P10 revision `20260310`. It stages exact rollback YAML/add-on options, proposed two-field USB target YAML/add-on options, hashes, identity/group baseline and an explicit record that **network restore has NOT occurred**. No target radio/NVRAM/IEEE or Home Assistant config is written by this command. If the probe fails, do not choose another device solely because its name looks plausible; inspect SMLIGHT USB mode and radio assignment first.

## 4. Set the replacement IEEE, then let Zigbee2MQTT restore from the preserved backup

With SONOFF physically isolated, copy the source coordinator **effective IEEE** into the P10 secondary IEEE through an appropriate device-supported procedure, and read back the configured replacement address. Keep the verified final cold archive and its original `coordinator_backup.json`, `database.db`, PAN/extended PAN, channel 11, network key and security-counter data intact; verify source identity consistency offline. **Zigbee2MQTT performs its backup-driven network restore at the first target start, not during the read-only USB discovery or configuration staging.** Therefore the pre-start acknowledgements attest preserved backup and configured IEEE, *not* that PAN/key/counters have already restored. After startup inspect the effective running IEEE, network identity/security and device operation; fail closed rather than deleting backups or fabricating Ember `devices` records if cross-stack restore does not work. Zigbee2MQTT explicitly does not guarantee no-repair Ember↔Z-Stack migration.

After the IEEE has been configured/read back and the source backup preserved, run the read-only plan first:

```text
py -3 deploy/p10_ha_apply.py --stage C:/Workspace/.analienx/sonoff-private/issues/p10/staged/usb-UNIQUE --phase target
```

The explicit `--execute` form additionally needs `--approval APPLY_MR4U_ONLY_AFTER_SONOFF_ISOLATION` and four `--ack` flags: `source-isolated`, `source-backup-preserved`, `effective-ieee-verified`, `exclusive-radio-client`. It updates **both** YAML and add-on options while leaving Z2M stopped. Check that the new effective port is the verified by-id path, `adapter: zstack`, and unrelated settings are unchanged. Next use the separate read-only `p10_ha_start.py --stage STAGE --phase target` plan; its explicit start approval is `START_MR4U_AFTER_SONOFF_ISOLATION` and it requires the same four acknowledgements. Read the startup logs once; a started app is not proof of restored network identity. Do not bypass a mismatch by deleting database/coordinator backup or forming a new network.

## 5. Check real operation, or reverse the USB swap

Take a private post-start Zigbee2MQTT bundle. `p10_migration_workflow.py assess --baseline STAGE/device_baseline.private.json --post-bundle POST.zip --cutover-utc UTC_OFFSET_TIMESTAMP --out PRIVATE_REPORT.json` compares the 106 non-coordinator devices, 21 groups and fresh inbound reports. Separately verify outbound unicast, groupcast, dimmer/socket/metering, critical automations, router rejoins and controlled joining; compare route/source-route failures across equivalent windows. Sleepy devices and intentionally switched-off bulbs need separate observation windows. The 400 TCLK slots previously measured are not a proof of 60 direct neighbors.

For rollback, **stop Z2M first**, confirm it cannot restart, unplug/isolate the MR4U Zigbee interface (and all applicable powers if radio cannot otherwise be disabled), and only then reconnect the preserved SONOFF. Apply `p10_ha_apply.py --stage STAGE --phase rollback` to restore BOTH original setting layers while Z2M is stopped; explicit execution requires `--approval ROLLBACK_ONLY_AFTER_MR4U_ZIGBEE_ISOLATION --ack target-isolated`. Start the original SONOFF with `p10_ha_start.py --stage STAGE --phase rollback` and its own documented phase-specific acknowledgement. Prefer the intact SONOFF NV state, not a blind rewind of stale security counters. Targeted rejoins may be needed if devices were repaired on the P10. Preserve post-attempt logs and both private backup sets.

**Testing distinction:** earlier hot capture and source-only stage were exercised against HA, and Python synthetic tests covered the existing preparation stack. The NEW USB discovery/probe, effective-IEEE restore, live target apply/start, post-cutover acceptance and rollback are **not yet hardware-tested**: USB discovery can only be tested after your planned physical swap. If remote Zephyrus access is unavailable, do not claim these steps have run or disconnect the SONOFF as an automated next action.
