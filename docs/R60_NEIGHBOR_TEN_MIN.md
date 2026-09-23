# Issue #28: 10-minute bounded neighbor time series

**Purpose:** Observe coordinator neighbor admission, departures and short-term outgoing-cost/age transitions at one-minute intervals. This is not a live per-frame trace, router sweep, replacement firmware, or a reproduction of the immutable #27 placement experiment.

**Owner:** [Sonoff issue #28](https://github.com/analienx/Sonoff-Dongle-Max/issues/28), under [#19](https://github.com/analienx/Sonoff-Dongle-Max/issues/19) and [#18](https://github.com/analienx/Sonoff-Dongle-Max/issues/18). Existing single-owner execution gate: `analienx/config` PR #61. Existing pinned extension and its SHA-256 remain unchanged.

From the authorized Zephyrus, with the current Sonoff worktree and the already-authorized Home Assistant SSH helper:

```powershell
py -3 deploy\r60_neighbor_ten_min.py capture
```

The fixed profile takes 11 timestamps at offsets 0, 60, …, 600 seconds, with one read-only NCP neighbor/source-route/counter snapshot per timestamp through the existing pinned Zigbee2MQTT owner gate. No new serial owner, device ZCL traffic, management broadcast, full mesh map, firmware, TX, pairing or network-config change. Each one-shot extension must be absent after its snapshot before proceeding. Capture aborts on a missing/partial snapshot, changed owner epoch, non-full neighbor table, or exceeded deadline. It preserves completed samples and refuses concurrent issue-28 series via an exclusive lock.

**Raw evidence remains private:** `C:\Workspace\.analienx\sonoff-private\issues\28-neighbor-mechanisms\r60_neighbor_ten_min_<UTC>-<nonce>.json` plus existing gate's immutable raw `r60_neighbor_result_<nonce>.json` in its private root. Do not commit device IDs, IEEE/NWK addresses, timestamps linked to personal activity, Zigbee credentials or raw captures.

The report counts observed per-interval departures, arrivals, cost and age changes, and prior unknown-outgoing-cost/age states. A router can leave and re-enter between sample points. Ten-minute aggregate NCP counter deltas can cross Zigbee2MQTT's hourly counter clear: reject such deltas, retain the independently valid neighbor snapshots, and verify the owner/log marker separately. Do not equate occupancy or these 11 snapshots with proven causality or successful household commands. After capture, publish only a sanitized issue-28 summary.

Offline tests: `py -3 -m unittest discover -s tests -p 'test_r60_*.py'`. Do not restart Zigbee2MQTT or retry an incomplete owner-gate operation without confirming extension cleanup and owner state.
