# Issue #28 — bounded join-window capture, 2026-09-22

**Scope:** A previously unjoined mains-powered socket rejoined the existing SONOFF Dongle Max / Zigbee2MQTT 2.14.0-1 network. This is passive, read-only observation of normal household/pairing traffic, NOT a coordinator-neighbor snapshot, OTA attempt, network repair, or proof of cause. Issue owner [#28](https://github.com/analienx/Sonoff-Dongle-Max/issues/28); earlier 10-minute [26-slot neighbor series](R60_NEIGHBOR_TEN_MIN_20260922.md) was taken **before** this join and is not contemporaneous.

## Collection and integrity

- An initial existing-log + state archive was collected at **16:43:07 UTC**. A separate 600-second `docker logs --follow` trace ran **16:45:10–16:55:11 UTC**, with five minutes of retrospective log backfill starting **16:40:10 UTC**; it therefore contains the join itself. The running collector exited **0**, reason `duration_complete`, 4,195,138 bytes, 964 received blocks; no capture limit reached.
- Full logs and archive are private under `C:\Workspace\.analienx\sonoff-private\issues\28-neighbor-mechanisms\`. Raw IEEE identifiers, temporary NWK mapping, MQTT payloads, Home Assistant DB/state, credentials and private user device names are **not** in Git. Full trace SHA-256: `ffe983baf764225c3df9b54e3ad7b1456b4b5cb3de1a911d6f6fe4cb660cbe0`.
- The initial archive captured one running Z2M owner that started at **06:12:05 UTC**. The same container's log stream remained open throughout the follow window; an independent post-capture owner-epoch attestation was not taken. Neither the logger nor analyzer opens EZSP, installs an extension, issues a ZCL read, or changes pairing, TX, channel, firmware, or router state. Code: `deploy/r60_join_passive_window.py` and `deploy/r60_join_passive_analyze.py`.

## Actual join and associated errors (UTC)

| Time | Observed event |
|---|---|
| 16:41:17.913 | Socket join announced; Z2M began interview. |
| 16:41:33.189 | Active-endpoints query failed once, then succeeded. The failed query's target network address matches the address in the three subsequent source-route-error logs. |
| 16:41:43.380–16:41:53.470 | Initial `modelId` read failed; Z2M retried and obtained it. |
| 16:42:03.350 | One `ROUTE_ERROR_SOURCE_ROUTE_FAILURE` naming the joining socket's NWK address, before interview success. |
| 16:42:03.681 | Interview completed and Zigbee2MQTT declared pairing successful. |
| 16:42:03.752 and 16:42:03.851 | Two further source-route failures naming the same socket's NWK address, just after interview completion. |

**The socket did pair successfully despite the transient query and route errors.** The captured log contains no subsequent route-error event naming its join-time NWK address through 16:55:11 UTC, and no subsequent recorded leave or repeat interview for that socket. This is not a confirmed post-join on/off-command or OTA success test, and network addresses can change.

## Fresh ten-minute live window only: 16:45:10–16:55:11 UTC

| Zigbee2MQTT log event | Observed count |
|---|---:|
| `ROUTE_ERROR_SOURCE_ROUTE_FAILURE` | 1 (another address, not the joining socket's join-time NWK) |
| `ROUTE_ERROR_MANY_TO_ONE_ROUTE_FAILURE` | 5 |
| `ROUTE_ERROR_NON_TREE_LINK_FAILURE` | 2 |
| `ROUTE_ERROR_ADDRESS_CONFLICT` | 0 |
| Newly completed interviews / denied joins | 0 / 0 |
| Explicit Z2M `Failed to read state` messages | 2 (both known intentionally unpowered workroom dimmers; exclude from connectivity regressions) |
| `SLStatus.BUSY` log events | 0 |

Counts are **log observations only**; they are not per-radio-packet, per-neighbor, or all-network failure rates. The initial five-minute backfill additionally included one unrelated many-to-one route failure before the join; two more many-to-one and the three joining-device source-route failures occurred before the fresh ten-minute live window began. A ZCL debug `Error` line alone is not equivalent to a failed user command. Normal traffic varied; no control cohort or before/after causality can be inferred.

## Interpretation and next measurement

The joining socket experienced a failed initial discovery request and three source-route errors tied to its **temporary** NWK during interview completion, then completed pairing. Its route-error cluster did not persist in the subsequent captured period. Other route errors continued elsewhere in the mesh after pairing, which prevents treating the three-device-specific events as proof of a new network-wide problem. Read failures from two deliberately unpowered workroom dimmers must not be included in the active-device failure denominator.

**Important gap:** We deliberately did **not** install the temporary owner-local NCP neighbor extension or poll routers during active pairing/possible follow-on OTA. This join-window trace therefore cannot show the 26-slot table's individual replacements, link-status/outgoing-cost transitions, CCA/MAC retry counters, or actual MAC next hops. The earlier ten-minute neighbor series is non-contemporaneous and cannot be correlated to this join by timestamp. The next controlled comparison should use the existing safe owner gate only after pairing/OTA are idle, then align neighbor samples with naturally occurring command outcomes; never infer a 26→60 firmware fix from this join trace.
