# SONOFF → MR4U P10 USB migration: operator handoff

**This is the current USB-only runbook.** It does not require Ethernet or simultaneous access to the two adapters. The original SONOFF is kept as the intact physical recovery coordinator. A full Home Assistant backup is optional; the script makes a new complete *cold Zigbee2MQTT-only* backup as its first outage step. Never publish private bundle contents, coordinator IEEE, network keys, by-id serial numbers, device addresses or HA add-on options.

## Phase 0 — while SONOFF is still plugged in and Zigbee2MQTT is running

Use an already verified private *hot* bundle as the source of the original YAML hash, or create a new one if configuration has changed. The driver refuses changed source YAML, mismatched add-on `serial` overrides, an existing destination, or an add-on not in its expected running state. Paths below are PRIVATE and must be unique on each attempt.

```text
py -3 deploy/p10_usb_handoff.py --source-bundle PRIVATE_VERIFIED_HOT.zip --cold-out PRIVATE_NEW_COLD.zip --stage-out PRIVATE_NEW_SOURCE_STAGE
```

When deliberately beginning the outage, use exactly the same command with `--execute --approval BEGIN_USB_CUTOVER_STOP_AND_BACKUP`. **The Python driver stops Zigbee2MQTT itself, verifies the complete cold archive, stages the original YAML/add-on options and per-device baseline, and rechecks the add-on is stopped.** Its only positive physical handoff result is `READY_TO_DISCONNECT_SONOFF`. A failure means **do not disconnect**; preserve recovery artifacts and check HA before any new attempt. No extra full HA backup is created.

## Phase 1 — human hardware action after READY_TO_DISCONNECT_SONOFF

Disconnect the old SONOFF from all its power sources without factory resetting or flashing it. Do not run the old and replacement Zigbee coordinators simultaneously on the copied household network. Connect the MR4U by USB to Home Assistant (not Zephyrus); disconnect any other client holding its P10 Zigbee serial interface. Keep Zigbee2MQTT stopped. The MR4U's independent Thread radio must not be selected for Zigbee.

## Phase 2 — discover P10 after the swap, without starting the network

```text
py -3 deploy/p10_usb_cutover.py discover --cold-bundle PRIVATE_NEW_COLD.zip
py -3 deploy/p10_usb_cutover.py stage --cold-bundle PRIVATE_NEW_COLD.zip --target-by-id EXACT_VERIFIED_HA_P10_USB_BY_ID --out PRIVATE_NEW_TARGET_STAGE
```

The first command lists available stable HA USB paths **only after it confirms the old SONOFF by-id path is absent and the add-on is stopped**. The second probes only the selected interface with ZNP SYS_PING and SYS_VERSION, checks the previously recorded P10 revision and produces matching replacement Zigbee2MQTT YAML **and** Supervisor add-on options. Only `serial.port` and `serial.adapter` are changed. Do not use COM4, `/dev/ttyACM0`, a guessed interface number or a generic SMLIGHT radio label as the target. `target_configuration.yaml` is staged but not deployed.

## Phase 3 — existing network, apply, start and acceptance

Preserve `database.db`, `coordinator_backup.json`, network channel/PAN/key and the untouched SONOFF. Copy the source **effective IEEE** to the P10 using an appropriate device-supported procedure and verify the effective secondary IEEE readback (TI primary IEEE can differ). Zigbee2MQTT's `ember` → `zstack` backup-driven network restoration happens during the first start; **do not attest that restoration already succeeded before that start**. Cross-stack migration may still require targeted device repairs; never delete the database or backup as a way to force startup.

Run the default read-only `p10_ha_apply.py --stage PRIVATE_NEW_TARGET_STAGE --phase target` plan; the explicit deployment requires `--execute --approval APPLY_MR4U_ONLY_AFTER_SONOFF_ISOLATION` and `--ack source-isolated --ack source-backup-preserved --ack effective-ieee-verified --ack exclusive-radio-client`. This applies both app settings layers but leaves Zigbee2MQTT stopped. `p10_ha_start.py --stage PRIVATE_NEW_TARGET_STAGE --phase target` is also read-only by default; its explicit start requires its phase-specific approval `START_MR4U_AFTER_SONOFF_ISOLATION` and the same four acknowledgements. **Inspect startup logs immediately for real backup restoration and matching network identity.** A started add-on, retained database rows or pre-start acknowledgements alone are not proof that the network is working.

After startup, take a new private observation bundle and run `p10_migration_workflow.py assess`; then test bidirectional unicast, groups, metering, important HA automations, a controlled join/rejoin, and route-error trends. Follow `P10_PYTHON_MIGRATION_WORKFLOW.md` for exact acceptance/rollback commands. If starting fails, leave SONOFF intact: stop Zigbee2MQTT, isolate the P10 Zigbee radio, restore the source settings from the cold stage, reconnect SONOFF, and start once. Do not rewind the old radio's network state blindly.

**Merge of code into Git main does not itself authorize these live steps.** The backup-driven Ember→Z-Stack restore and exact P10 effective-IEEE write are not performed by these Python scripts. A physical unplug confirmation, live radio readback and first-start observations are separate, real-world migration evidence.

**Supervisor error after physical disconnect:** Home Assistant may report Zigbee2MQTT `error`, not `stopped`, after the original USB adapter disappears. The USB discovery/apply/start helpers accept this state only if the exact Zigbee2MQTT Docker container is independently confirmed exited. `started`, an uninspectable container and a running container all fail closed. No Home Assistant Zigbee integration needs to be configured merely for HAOS to expose the replacement USB serial devices.
