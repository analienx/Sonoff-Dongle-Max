# SONOFF Ember → MR4U CC2674P10: Python operator workflow

**Status:** Read-only hot backup and source-only staging have been run on the real home network. Cold capture, target Ethernet probe, live two-layer deploy, physical radio isolation, IEEE/network restore, live start, and rollback have **not** been performed. No full Home Assistant backup is required. Secret-bearing ZIPs, add-on options and private device IDs stay in `C:/Workspace/.analienx/sonoff-private/`, never Git. Run all examples from the Sonoff repo's root on the authorized Zephyrus; use distinct private paths per attempt.

## Phase A — rehearse with live SONOFF unchanged

```text
py -3 deploy/p10_data_bundle.py capture --mode hot --out C:/Workspace/.analienx/sonoff-private/issues/p10/bundles/PREVIEW_UNIQUE.zip
py -3 deploy/p10_data_bundle.py verify --bundle C:/Workspace/.analienx/sonoff-private/issues/p10/bundles/PREVIEW_UNIQUE.zip
py -3 deploy/p10_migration_workflow.py stage --bundle C:/Workspace/.analienx/sonoff-private/issues/p10/bundles/PREVIEW_UNIQUE.zip --out C:/Workspace/.analienx/sonoff-private/issues/p10/staged/PREVIEW_UNIQUE
```

The complete Zigbee2MQTT data directory (excluding regenerable `log`/`logs`) and separate HA add-on options are included. The two external absolute `node_modules` symlink dependencies are captured as **private link metadata**, not dereferenced or automatically restored; their runtime targets must still exist. The live hot backup is provisional, **never** the final cold recovery archive. The staged source-only plan contains exact rollback YAML, rollback add-on options, private device baseline and per-file hash records.

The existing live add-on has nonempty `serial.port`, `serial.adapter`, and `serial.baudrate` overrides **matching** the YAML. Therefore both YAML and add-on options must change together during the real cutover. An application-only two-line YAML patch is inadequate for this installation.

## Phase B — MR4U independently attached via wired LAN

Record the MR4U's actual stable LAN IPv4 and **Radio 2** socket from its own UI. Close Zephyrus's COM4 owner before using the unit in TCP mode. Probe from HA: `py -3 deploy/p10_target_endpoint.py --host MR4U_LAN_IP --port RADIO2_TCP_PORT --expected-revision 20260310`. This is an *idle* ZNP ping/version test, **not** proof of a configured home Zigbee network. With the actual verified endpoint, add `--target-host MR4U_LAN_IP --target-port RADIO2_TCP_PORT` to the `p10_migration_workflow.py stage` invocation, using a new output directory. The script creates both target configuration layers only if the HA-side radio probe passes. Never assume that COM4, the first radio or a default TCP port is the Zigbee P10.

## Phase C — scheduled outage, source recovery and isolation

Use the expected original YAML SHA-256 from the PRIVATE `cutover_state.private.json` staging report (never from a random old backup). Default `p10_outage_freeze.py` is read-only and reports current add-on state. At the deliberately authorized outage only, run it with `--execute --approval STOP_Z2M_FOR_MR4U_MIGRATION`. It stops *only* the Zigbee2MQTT add-on, verifies it is stopped and creates a **new, complete cold Zigbee2MQTT ZIP** using the same strict source hash. If capture fails, do **not** continue to radio isolation; diagnose, preserve the failed archive and restore normal SONOFF operation through the normal HA controls as appropriate. Take a fresh final stage from the verified cold ZIP, with the real target endpoint.

**Physical operator handoff:** disconnect/isolate the SONOFF Zigbee radio from all its power paths, including USB/PoE if applicable; preserve original SONOFF firmware, IEEE and network NVRAM. Do not let the copied network run on both coordinators. Verify the target Radio 2 has one exclusive client. Through the supported radio-specific migration process transfer the effective old IEEE, network identity and security/counter state to the CC2674P10; Zigbee2MQTT's cross-stack Ember→Z-Stack migration is explicitly not guaranteed to avoid re-pairing. The Python tooling does **not** write radio IEEE/NVRAM or silently initialize a new network.

## Phase D — apply the two settings layers and start once

`p10_ha_apply.py --stage PRIVATE_COLD_STAGE --phase target` is a read-only plan. To execute it, the operator explicitly provides `--execute --approval APPLY_MR4U_ONLY_AFTER_SONOFF_ISOLATION` with four `--ack` values: `source-isolated`, `existing-network-restored`, `effective-ieee-verified`, `exclusive-radio-client`. It requires the addon stopped, exact original YAML SHA and matching original options; the remote narrow helper sends options through the Supervisor REST endpoint and replaces only the configuration YAML atomically. It **does not start** Zigbee2MQTT; if the prestate differs it refuses to touch production. The plan and API path are not an end-to-end, hardware-tested coordinator migration.

`p10_ha_start.py --stage PRIVATE_COLD_STAGE --phase target` checks both deployed config layers and stopped state. Its opt-in `--execute` invocation requires phase-specific approval `START_MR4U_AFTER_SONOFF_ISOLATION` and the same four `--ack` values before starting the add-on once. Inspect the first startup logs; an add-on reporting `started` does **not** prove the old network was restored. Never delete `database.db`/`coordinator_backup.json` or auto-fallback to forming a new network on error.

## Phase E — acceptance, targeted repair and rollback

Record the exact cutover instant with UTC offset. Capture a new private hot post-start bundle and run:

```text
py -3 deploy/p10_migration_workflow.py assess --baseline PRIVATE_COLD_STAGE/device_baseline.private.json --post-bundle PRIVATE_POST_BUNDLE.zip --cutover-utc 2026-09-24T12:00:00+02:00 --out PRIVATE_UNIQUE_ACCEPTANCE.json
```

The compare retains private per-device failures but shows aggregate counts of *fresh inbound* reports, missing routers, changed roles and lost groups. Separately test representative bidirectional socket/dimmer/group commands, metering, essential HA automations, joining/rejoining, and routing/source-route errors over comparable intervals. Optional `--evidence PRIVATE_JSON` permits operator-recorded function checks but is never presented as independently authenticated success. Group records are not Zigbee nodes; sleepy or intentionally powered-off devices need appropriate observation windows.

**Rollback:** stop Zigbee2MQTT, physically isolate MR4U **Zigbee Radio 2** while leaving unrelated Thread alone, keep original SONOFF NVRAM intact. `p10_ha_apply.py --stage PRIVATE_COLD_STAGE --phase rollback` checks live target configuration before changing anything. Only after `--execute --approval ROLLBACK_ONLY_AFTER_MR4U_ZIGBEE_ISOLATION --ack target-isolated` does it restore both exact source settings layers while the add-on stays stopped. Reconnect the SONOFF and run `p10_ha_start.py --phase rollback` with its specific start approval and `--ack target-isolated --ack original-sonoff-state-preserved`. Verify critical devices and fresh reports; old radio security counters and devices repaired on the MR4U may require targeted rejoins. This script restores app settings; it does **not** erase/reflash or automatically rewind radio state.

## Limitations and guardrails

Cold snapshot consistency is evidenced by the add-on being stopped before and after capture, not an OS-level atomic filesystem snapshot. Preserve records of external symlinks, any environment overrides beyond captured add-on options, and addon boot/watchdog settings. The local Python test suite uses synthetic credentials and fake devices; the helper's live-mutation paths have **not** been exercised against the production Zigbee network. Only the hot read-only archive, source-only staging, source inventory and existing COM4 diagnostics have real hardware coverage so far. No tool can prove physical radio isolation from a software acknowledgement alone. A full HA backup is optional and is not needed for the narrow backup/rollback procedure.
