# Live SONOFF MG24 coordinator neighbor readback — 2026-09-22

Epic #18; baseline #19; source [PR #25](https://github.com/analienx/Sonoff-Dongle-Max/pull/25). **This is a completed live coordinator-local observation, not firmware deployment or proof of automatic route recovery.** The user explicitly requested using the running SONOFF coordinator and proceeding with a single bounded diagnostic. Do not run another general HA log-collection pass.

## Exact execution and protected state

- `2026-09-22T10:52:30.469Z` (12:52:30 Europe/Prague): one `ezspNeighborCount()` plus exactly 26 indexed `ezspGetNeighbor()` readbacks via the already-running Z2M/Ember owner. NCP readback elapsed **371 ms**; transaction-matched result status `ok`, 26 rows. Existing owner image was `ghcr.io/zigbee2mqtt/zigbee2mqtt-aarch64:2.14.0-1`, herdsman `10.9.1`; its `StartedAt` remained `2026-09-22T06:12:05.582374526Z` before/after. **No second EZSP/serial owner**, map, induced link loss, TX/channel/security change, pairing, NVM/flash, or add-on restart.
- Source `runtime/r60_neighbor_extension.cjs` SHA256 `a0ce05511e11adc9a79296182bcfe9b10225b855cbfb8c1c3f9c51625d84b199` was run through the separately typed `z2m_r60_neighbor_snapshot` privileged helper, committed on `analienx/config:assistant/r60-owner-probe-gate-20260922`. Plan digest and full unredacted neighbor data stay only in `C:\Workspace\.analienx\sonoff-private\` on the authorized laptop. Helper’s four offline Python gate tests passed, both JS scripts passed syntax checks, and earlier staged-extension mock tests passed. The temporary extension returned a matching snapshot response, was removed through the built-in Z2M extension/remove path, and its `.cjs` file was verified **absent** afterward.
- Z2M’s external-extension manager retains a `external_extensions/node_modules` symlink after save/remove. It exists on the HA host but resolves only *inside the Z2M container*; do **not** unlink this runtime-manager resource ad hoc while the owner remains running. The helper verified removal of the temporary extension file, **not removal of that manager-managed symlink**. No claim of a byte-for-byte unchanged extension directory.

## Sanitized observed table

| Metric | Readback |
|---|---:|
| Current occupied direct coordinator-neighbor entries | **26** |
| Probe configured maximum entries read | **26** |
| Unique short addresses / unique IEEE addresses | **26 / 26** |
| Matching Router records in the saved one-pass database | **26 of 26** |
| Average LQI minimum / median / maximum | **77 / 126 / 233** |
| Incoming cost | **1 for all 26** |
| Outgoing cost | **0: 1 entry; 1: 15; 2: 6; 3: 4** |
| Age | **0: 1; 2: 1; 3: 6; 4: 14; 5: 3; 6: 1** |

Readback roles/models cross-referenced PRIVATELY to the database in the previously captured `2026-09-22T07:02:48Z` HA archive (no new HA database/log collection): 13 `TS011F`, 5 `ZBMINIR2`, 3 `RB 287 C`, 2 `TS0505B`, and one each `TS011F-BS-PM`, `TS0001-AVB`, `TS0601`. Note that a Zigbee NWK short address is temporary and current snapshot rows are not automatically a valid historic mapping.

Two `TS0505B` routers have snapshot LQI **108** with outbound cost **0** (unknown/no established outbound cost) and LQI **77** with outbound cost **1**, respectively. Their *current* NWK short-address values match 15 and 42 historical `MANY_TO_ONE_ROUTE_FAILURE` lines in the retained archive, but historical IEEE↔NWK continuity was **not** verified; treat this as a provisional correlation only, not a confirmed lifetime error tally for those same physical devices. Do not publish private IEEE/NWK addresses in the issue or automatically unpair/reflash a device from this match.

## Decision and limits

The previously reported historical **26/26** saturation is NOW independently confirmed on the live production coordinator. It is credible to investigate whether the fixed-size table is retaining weak or unidirectional links and delaying admission/replacement of better neighbors in this >60-router network. It is **not** proved by this single snapshot that occupancy directly caused a particular many-to-one route failure, that automatic eviction failed, that `0` outbound cost persisted, or that every failed route was direct to the coordinator. The ordinary Zigbee2MQTT concentrator settings already initialize automatic MTORR discovery, but the snapshot cannot prove on-air propagation of every refresh.

**Next engineering action:** make a small, falsifiable on-device *neighbor admission/aging/replacement* candidate with a deterministic offline test using the 26-entry full-table/weak-link case. Confirm the actual MG24 stack implementation and memory/index/Link Status invariants before changing firmware; do NOT simply edit `26→60` or broadcast extra MTORRs. Prefer short, non-disruptive live-owner acceptance where possible. Keep current production firmware/network unchanged until the candidate and exact rollback are validated. Full end-to-end network reliability is **not yet fixed**.
