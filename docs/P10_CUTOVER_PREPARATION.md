# MR4U P10: reusable cutover preparation (2026-09-24)

This is executable **preparation**, not a command to migrate the live Zigbee network. Public Git contains only code, synthetic fixtures and sanitized findings. Keep the live archives, coordinators' IEEE addresses, database and network keys in the private Windows workspace / HA backup storage.

## Captured recovery state

- Native full HA backup `sonoff-mr4u-precutover-20260924` (slug `edbb94f6`) created via `p10_native_ha_backup.py --create`. Supervisor confirms Home Assistant and Zigbee2MQTT add-on are present; ~2.20 GB. A previous separate full backup (2026-09-23) also exists. These are **not** tested HA restore operations.
- `p10_cutover_prepare.py capture` read the running Z2M configuration, coordinator backup, device database and state cache over verified SSH/SFTP into a *new private directory*. It rechecks file length/mtime, saves per-file SHA256, and refuses overwrite; the live data-folder capture is **not atomic**, so repeat after Zigbee2MQTT has stopped at the actual cutover boundary.
- Live database: **61 routers, 45 end devices, one coordinator, 21 groups**. Group records have `type=Group` and `groupID` instead of `ieeeAddr`; the previous device-only parser was corrected and regression-tested.
- Exact source configuration is staged byte-for-byte as `rollback_configuration.yaml`; private acceptance baseline retains all device IDs and groups. The replacement configuration is deliberately NOT created until its actual P10 endpoint has been verified from HA.

## Current radio connection: do not guess the port

- Production HA Z2M uses `/dev/serial/by-id/...SONOFF...` with `serial.adapter=ember`, baud=115200; current network channel is 11. MR4U CC2674P10 responded on **Zephyrus COM4**, not a HA path.
- MR4U's dual-radio LAN configuration uses separate sockets. Radio 2 CC26xx commonly uses port **7638**, but firmware, radio order and configured socket ports must be checked in this unit's own SMLIGHT Z2M/ZHA configuration generator. A Windows COM4 address is not a valid HA `serial.port`.
- Once MR4U is independently connected to Ethernet/PoE and a private LAN IPv4/Radio 2 socket port is known, run from Zephyrus:

```text
py -3 deploy/p10_target_endpoint.py --host <MR4U-LAN-IP> --port <RADIO2-PORT> --expected-revision 20260310
```

The command probes from **Home Assistant** using only ZNP SYS_PING/SYS_VERSION and refuses an unexpected radio/revision. If an active USB client owns the target radio, close that client before TCP probing. Never probe a production-network coordinator through this helper.

## Private command sequence (examples; use fresh unique paths)

```text
# Verify the real full HA backup; default command is read-only:
py -3 deploy/p10_native_ha_backup.py --name sonoff-mr4u-precutover-20260924
# Capture current live Z2M files to a fresh private directory, no HA writes:
py -3 deploy/p10_cutover_prepare.py capture --out C:/Workspace/.analienx/sonoff-private/issues/p10/snapshots/UNIQUE
# Check file integrity and device/group/backup records offline:
py -3 deploy/p10_cutover_prepare.py inspect --source C:/Workspace/.analienx/sonoff-private/issues/p10/snapshots/UNIQUE
# Stage the exact old configuration and rollback plan, no live changes:
py -3 deploy/p10_config_stage.py --snapshot C:/Workspace/.analienx/sonoff-private/issues/p10/snapshots/UNIQUE --out C:/Workspace/.analienx/sonoff-private/issues/p10/staged/UNIQUE --native-backup-slug edbb94f6
# When actual HA-to-Radio2 TCP ZNP connectivity works, add --target-host and --target-port to the previous command, using a NEW output directory. This stages target_configuration.yaml ONLY after successful P10 revision verification.
# Prepare a private complete device identity/group acceptance baseline:
py -3 deploy/p10_device_acceptance.py baseline --snapshot C:/Workspace/.analienx/sonoff-private/issues/p10/snapshots/UNIQUE --out C:/Workspace/.analienx/sonoff-private/issues/p10/acceptance/UNIQUE.json
```

The config renderer changes **only the original two lines `serial.port` and `serial.adapter`**. It verifies the resulting YAML roundtrips and that all other parsed settings are unchanged. Its input retains the original configuration byte-for-byte in the private rollback staging area. The TCP endpoint must be probed from HA first; a hard-coded 7638 alone is not proof.

## Defined execution boundary (the preparation scripts do NOT execute these steps)

1. Check latest full backup and an immediately pre-cutover Z2M cold snapshot after stopping the add-on. Record network identity, counters, group/device inventory and a route-error baseline. Do not commit any secret-bearing artifacts.
2. Keep the SONOFF firmware/NV state intact and **physically isolate it before the new network is active**. Confirm the MR4U is in Zigbee coordinator mode and HA can reach the verified P10 socket. Do not run two coordinators with cloned identity/network security state.
3. Verify transfer of the coordinator's actual IEEE, PAN/extended PAN, channel, network key and appropriate security counters; confirm the target Z-Stack restore path for the installed Zigbee2MQTT/zigbee-herdsman version. An Ember `devices=[]` backup can be expected by design; it is not evidence that individual link keys have been reconstructed or that the cross-stack restore is valid.
4. After the target is prepared, deploy the staged target configuration through the approved HA mutation/deployment path and start Zigbee2MQTT once. Measure network startup and normal device operation instead of trusting retained database records.
5. If acceptance fails, stop Zigbee2MQTT and isolate the MR4U before reconnecting the preserved SONOFF. Restore the exact old configuration and, only when needed, its matching old application data from the preserved backup. Check security counter/rejoin behavior: an old backup is not a guarantee of instant recovery.

## Device recovery and network acceptance

At cutover, record an exact timezone-aware timestamp. Capture a second Z2M data folder after devices have had an opportunity to report (do NOT start another cloned Zigbee network). Compare with the PRIVATE baseline:

```text
py -3 deploy/p10_device_acceptance.py compare --baseline C:/Workspace/.analienx/sonoff-private/issues/p10/acceptance/UNIQUE.json --post-snapshot C:/Workspace/.analienx/sonoff-private/issues/p10/snapshots/POST_UNIQUE --cutover-utc 2026-09-24T12:00:00+02:00 --out C:/Workspace/.analienx/sonoff-private/issues/p10/acceptance/POST_UNIQUE.json
```

This reports router/end-device recovery, identity disappearance, changed roles and group loss. It compares `lastSeen` in milliseconds to the cutover timestamp: simply remaining in `database.db` is NOT counted as a recovered device. The private report retains IDs for targeted recovery; console output contains aggregate counts only. Intentionally relay-powered-off bulbs and sleepy devices need explicit observation windows; they are not automatically classified as broken.

**Separate, mandatory live acceptance:** bidirectional unicast/poll or real application reports from all feasible routers; configured groups; representative power-monitoring/socket/dimmer commands; route failures measured against baseline; stable neighbor/LQI pages; parent/rejoin behavior over a sustained window. The lastSeen script does not claim these live measurements have already passed. See `p10_capacity_gate.py` and `p10_neighbor_capacity.py` for the independent capacity/operation evidence gate.

## Validation scope

The protocol-side TCP probe has an offline fake-radio socket test that verifies its exact SYS_PING/SYS_VERSION byte sequence and decoding. Snapshot/cutover staging, config-only modification, parser Group support and acceptance report have synthetic tests. Real hardware coverage: live SFTP snapshot and SHA256 reinspection; real native full HA backup via reusable helper; original COM4 P10 diagnostic and 400 TCLK records. **No production Zigbee cutover, real TCP Radio 2 test, IEEE write, cross-stack restore or rollback has been executed here.**
