# R60 live NCP radio-neighbor pressure and USB topology — 2026-09-22

Parent #18 / #19; PR #25. **Redacted read-only evidence, no reliability fix deployed.** Exact IEEE/NWK/route data and unredacted logs stay on authorized laptop. No NCP flash, counter clear, serial takeover, pairing, full map, TX/channel change or router power cycling. Temporary Z2M diagnostic extension file removed; existing owner unchanged.

## Owner-local methods

Pinned Z2M 2.14.0 / herdsman 10.9.1, Ember coordinator. One digest-pinned, one-shot external extension through the **existing Z2M owner** at 2026-09-22T11:22:31.729Z (Prague 13:22:31); every NCP call serialized via `adapter.queue.execute()` (corrects earlier raw-EZSP diagnostic). One read of 26 neighbor entries, source-route total/filled, 79 indexed source-route entries and **non-clearing** NCP counter vector. Existing owner StartedAt 2026-09-22T06:12:05.582374526Z remained stable. One-shot helper in `analienx/config` draft PR #61; extension file removed after success; Z2M-managed `external_extensions/node_modules` symlink persists and must not be unlinked ad hoc. Privileged helper's four Python gate tests passed. Newly expanded public diagnostic mocks were committed but not independently verified by a GitHub-hosted test job at the time of this note.

Read-only, strictly filtered live owner Docker output located `[NCP COUNTERS]` **hourly read-and-clear at 2026-09-22 13:12:09 Prague (11:12:09Z)**. The reported previous interval had **7331 MAC TX unicast successes / 910 failures / 4754 retries**, **349 neighbor additions / 349 removals / 185 stale indications**, **68 route discoveries**, **6544 APS unicast successes / 2 failures**, 552 CCA failures. Packet-buffer allocation failure, PHY→MAC drops, NWK retry overflow, broadcast-table full, and address-conflict-sent counts were **all zero**.

## New counter interval: 11:12:09Z–11:22:31Z (~10m22s)

| Metric | NCP non-clearing count |
|---|---:|
| MAC TX unicast success / failure / retry | **1332 / 192 / 866** |
| APS TX unicast success / failure | 1029 / 0 |
| Neighbor added / removed / stale | **61 / 61 / 35** |
| NWK route discoveries initiated | 13 |
| PHY CCA failure | 99 |
| Broadcast table full / packet buffer allocation failure | 0 / 0 |
| PHY→MAC drops / NWK retry overflow | 0 / 0 |
| ASH overflow / framing / overrun | 0 / 0 / 0 |
| Address-conflict sent | 0 |

MAC failed/(MAC success+failed) is ~11.0% in the prior hourly period and ~12.6% in the short next period. **These are individual link-layer frame outcomes, not user command failure rates; MAC retry counts have different semantics.** NCP `ROUTE_DISCOVERY_INITIATED` counts submission of *some* route discoveries to the MAC, **not specifically confirmed transmitted/propagated MTORR**. APS unicast failures only 2 and 0 in these particular counter periods; older saved Z2M logs contain real failed `set` operations. No basis here for adding another MTORR timer or increasing BTT/source-route storage.

## Table structure and turnover

Neighbor table full 26/26, but two entries replaced over a previous 13m21s matched pair, proving admission is not frozen. A previous neighbor with outgoing cost 0 recovered/was replaced; the latest snapshot has **zero** cost-0 neighbors. Source-route table **79/254**, all 79 indexed entries distinct and structurally valid: 30 direct, 34 one-relay, 15 two-relay chains; no invalid closer indices/cycles. This does **not** certify current on-air delivery or IEEE↔NWK correctness. The repeated added/removed counters expose **sustained high neighbor churn**, plausibly from a full 26-entry table and/or unstable 2.4 GHz links, **not** proof that a larger or more aggressive neighbor table is buildable or will cure it.

## Host/RF topology: actionable additional evidence

Live Z2M serial configuration uses a **local USB device path, not Ethernet/Wi-Fi transport**. HA OS USB inventory reports `Bus 001 Device 002: 10c4:ea60 SONOFF SONOFF Dongle Max MG24` (USB2 host bus) and a separate `Bus 002 Device 002: 152d:0580 JMicron AXAGON External Enclosure` (USB3 host bus); `lsblk` shows `sda usb disk`. **Both the Zigbee coordinator and a USB3 external SSD are attached to the Raspberry Pi.** Software inventory does *not* report their physical distance, cable shielding/placement, antenna attachment or active 2.4GHz SONOFF AP. Laptop WLAN scan did not show an obvious SONOFF SSID; HA entity registry shows no readily usable SONOFF AP/WLAN control entity. Do **not** claim ESP Wi-Fi interferes or is enabled based on these scans.

Zigbee2MQTT's official network-stability guidance explicitly warns against placing a USB coordinator close to a computer, SSD or other radio source and recommends at least 50 cm of USB extension cable: https://www.zigbee2mqtt.io/advanced/zigbee/02_improve_network_range_and_stability.html . With the unusually high verified MAC TX failures and neighbor replacement counts, **separating the SONOFF radio and its antennas from the Pi and the USB3 SSD/cable** is a reversible, low-risk next physical intervention if they are currently colocated. Prefer a suitably shielded USB2 extension and place the radio/antennas ≥1 m from the Pi/SSD/USB3 cabling and other 2.4GHz radios; do not unplug the boot SSD. This may briefly interrupt Z2M USB serial and is **not** remotely executable; the user must make the physical placement change. Do not move it if already separated at a sufficient distance; then focus on other RF/environmental differences or coordinator firmware selection/capacity.

**Acceptance after physical change:** keep channel, radio TX, firmware and normal household traffic unchanged; use a bounded one-owner 10-minute post-settle read (NCP counter epoch/short delta and 2–3 previously affected, powered devices' read-only ZCL outcomes), compare normalized MAC failures and neighbor add/remove per minute with 11.0–12.6% and ~5.6–5.9 replacements/min baseline. A major and repeatable reduction alongside restored actual commands supports RF-coupling cause; no improvement rejects it and motivates on-device neighbor-selection/capacity engineering. No threshold is a promise of flawless behavior. No autonomous repeated log collection or speculative flashing.
