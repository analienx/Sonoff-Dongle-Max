# Issue #28: ten-minute coordinator neighbor time series (2026-09-22)

**Status: complete observational capture, not a network repair.** Read-only 11-point series at one-minute cadence in the relocated position, using the existing single-owner pinned diagnostic and verified extension cleanup. Implementation: `deploy/r60_neighbor_ten_min.py`, offline analysis: `deploy/r60_neighbor_series_analyze.py`, tests: `tests/test_r60_neighbor_{ten_min,series_analyze}.py`. See `docs/R60_NEIGHBOR_TEN_MIN.md`; parent issues #19 and #18; earlier placement experiment #27 remains immutable.

**Private capture:** retained on authorized Zephyrus in `C:\Workspace\.analienx\sonoff-private\issues\28-neighbor-mechanisms\` as an immutable timestamped JSON plus individually preserved private one-shot NCP snapshots. No raw identities or map are committed. The capture's 11 full tables were all 26/26, had one unchanged Zigbee2MQTT owner epoch, and passed gate/extension-removal validation. Sample spacing 59.9–60.1 s. The source-route table held 83 entries at every point; occupancy is not route delivery proof.

| Read-only observation across 10 adjacent one-minute intervals | Value |
|---|---:|
| Valid snapshot points / intervals | 11 / 10 |
| Distinct direct neighbors appearing in any snapshot | 37 |
| Direct neighbors present at all 11 points | 16 |
| Observed departures / arrivals between successive snapshots | 28 / 28 |
| Return events after at least one sampled absence / distinct returning routers | 17 / 14 |
| Departures preceded by `outCost=0` / departures preceded by known outgoing cost | 12 / 16 |
| Departures preceded by age greater than six | 2 |
| Retained neighbors changing outgoing cost known→unknown / unknown→known | 14 / 9 |

**Denominators and caution:** Across the ten *starting* tables (260 peer-minute observations), there were 26 observations with `outCost=0` and 234 with known outgoing cost; respectively 12 and 16 were absent one minute later. These are repeated, correlated observations of a changing neighbor set, not 260 independent routers or measured eviction probabilities. `outCost=0` means the outgoing cost is **unknown**, not a directly measured low RSSI or lack of a physical radio link. Neither ordinary household command failure nor actual MAC next hop was measured during this passive capture.

**Counter integrity:** One hourly Zigbee2MQTT NCP-counter-clear marker was found in a complete 3,408-line targeted log audit; an actual counter decrease occurs in the second one-minute interval. Any aggregate counter subtraction spanning that clear is invalid and is not used here. The independently read neighbor-table sequence remains valid. No owner restart was observed. Neighbor add/remove event counters, if used separately, are *not* equal to the 28 endpoint-observed transitions because replacements between samples are missed.

**Interpretation:** A full direct-neighbor table was actively replacing entries, with only 16 peers continuously present and 14 distinct peers demonstrably returning after sampled absences. Unknown outgoing cost was common immediately before observed departure and outgoing cost also changed in both directions among retained peers. This makes loss/recovery of *confirmed bidirectional reachability*, Link Status reception and neighbor admission policy more specific hypotheses than a generic source-route-capacity shortage. The current observations cannot distinguish RF interference, marginal first-hop connectivity, missed unacknowledged Link Status, and intentional stack selection/eviction. They do not establish that these transitions caused a failed ZCL command.

**Next causally discriminating measurement:** gated, owner-local *passive* per-message APS destination/status timing linked to real command failures and time-local neighbor changes; actual MAC next-hop attribution needs supported lower-layer telemetry or an independent receive-only 802.15.4 sniffer. Keep the production firmware, coordinator identity, channel, TX, intentional power-off exclusions, pairing, and network configuration unchanged. No broad Mgmt_Lqi scans, router reboot sweep or `26→60` constant-only patch is justified by this capture.
