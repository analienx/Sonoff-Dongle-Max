# MG24 emergency fallback from P10/Z-Stack

This branch packages a **reversible emergency fallback** for this network's previously
accepted SONOFF Dongle-M / EFR32MG24 P009 coordinator.

It does not authorize a live flash or coordinator cutover.

## Proven local history

The accepted P009 artifact is pinned by historical deployment issue #6:

- commit `dca87aa4fb8405ef2ca4f0ef647c60bd46ef3600`
- Actions run `33907171158`, artifact `9950031778`
- P009 GBL: 268992 bytes, SHA256
  `a7747b396201d37da9073eaf81b599734684259debb78616b1fa3924fdac3fe8`
- matched stock rollback: 268896 bytes, SHA256
  `b88a7786741dea5661a1299fd0f650c692ad6a00d8fbd0e76848de8a638daaef`

The exact accepted P009 binary above is RX512, broadcast64, key12, multicast26,
route254, source-route254, and neighbor26. A later `p009-hardening` source profile
promoted multicast to 32, but that is **not** the hash-pinned production-accepted binary
used by this emergency plan.

Historical production Ember backups for this exact network from Aug 29 through Sep 24
all carry the same Ember `hashed_tclk` and have `devices: []`. The network nevertheless
ran >100 database devices without wholesale re-pairing. Therefore this emergency path
reproduces that **known network-specific backup shape** instead of trying to import all
Z-Stack TCLK-seed-derived device keys into Ember's 12-entry application link-key table.

This is deliberately narrower than generic cross-stack converters.

## Security interpretation

The current Z-Stack backup can contain many per-device keys derived from its TCLK seed.
Those records are not assumed to map one-for-one to Ember application-link-key slots.
The emergency Ember backup therefore:

- preserves coordinator IEEE, PAN, extPAN, channel and network key;
- uses the long-lived historical Ember `hashed_tclk` from this same network;
- leaves `devices: []`, matching the previous production SONOFF backup behavior;
- advances the NWK frame counter into a reserved future range.

The P10 rollback backup preserves the **full Z-Stack device/security records** and gets a
second, higher counter lease.

Risk remains for TC/application-key-specific rejoin/pairing behavior. This path is an
emergency continuity fallback, not a claim of cryptographically identical cross-stack
state.

## Reviewed generic converter

For comparison, the public `vwidor/z2m-zstack-to-ember-migration` converter was
reviewed at commit `7515fae6b04897c4b9487e05ec2cb6e9a8599634` (2026-05-06). Its
125-device report is valuable evidence that cross-stack migration can work, but its
converter deliberately copies every Z-Stack `devices[].link_key` unchanged into the
Ember backup while changing only stack metadata / `hashed_tclk`.

That is **not** used here:

- herdsman Ember backups store exported device link keys in hashed form;
- the accepted P009 NCP has `KEY_TABLE_SIZE=12`;
- this network's current Z-Stack backup contains far more key records, overwhelmingly
  TCLK-seed-derived rather than proven Ember APP-link-key slots;
- our own production SONOFF Ember backups from Aug 29 through Sep 24 consistently had
  `devices: []` and one stable `hashed_tclk`.

The emergency builder therefore follows the locally proven network-specific path instead
of forcing a generic all-key import.

## Exact historical SONOFF serial profile

The tracked post-Ember-cutover Home Assistant configuration used:

```yaml
serial:
  port: /dev/serial/by-id/usb-SONOFF_SONOFF_Dongle_Max_MG24_7e266bb02fa0f01191972c81bb936ffa-if00-port0
  adapter: ember
  baudrate: 115200
  rtscts: false
```

Do not stage this path until the actual attached SONOFF by-id is re-enumerated and matches
the expected hardware. The by-id path is evidence, not permission to assume the device is
currently attached.

## Counter leases

Use non-overlapping 10,000,000-count leases. The observed/staged counter floor must be
provided explicitly. The planner creates:

1. Ember counter = floor + 10,000,000
2. future P10 rollback counter = Ember + 10,000,000

A fresh coordinator backup must be captured before every later transition. Never reuse a
lower-counter snapshot after either coordinator has transmitted.

## Router staging

Do not optimize for an arbitrary total router count. Historical production evidence
showed the real MG24 constraint was a full **26/26 direct-neighbor table** with sustained
neighbor churn while the 254-entry source-route table retained ample headroom.

For the first MG24 boot:

- start with **at most 24 powered router candidates**, so the 26-entry direct-neighbor
  table cannot reach 26/26 even if every powered router is in direct RF range;
- keep essential hardwired breakers/switches and geographically useful anchors powered;
- temporarily power down redundant mains sockets that historically competed heavily for
  direct-neighbor slots;
- admit only devices that **secure-rejoin without a factory reset or new pairing**;
- if a candidate does not rejoin by itself, leave it offline during the reversible trial;
- target **direct-neighbor occupancy below 26 with materially lower churn**, not simply
  "30 Router records";
- after a stable checkpoint, add four candidates to reach at most 28 powered routers,
  then add at most two per checkpoint while observing occupancy/churn.

The exact candidate list is operational evidence, not membership filtering: all original
devices stay in the Zigbee2MQTT database and in the full P10 rollback backup.

## Hard cutover invariants

- exactly one coordinator/Z2M owner;
- P10 physically/logically isolated before MG24 uses the copied coordinator IEEE;
- exact P009/P009b artifact and matched rollback available and hash-verified;
- no NVM erase/factory reset and no new device pairing during the reversible trial;
- do not flash router→end-device/client role conversions while rollback-to-P10 is required;
- any device that would require a reset/re-pair on MG24 remains offline until the
  coordinator decision is final;
- coordinator IEEE must match the existing network;
- PAN/extPAN/channel/network-key fingerprint must match;
- keep the production `database.db` and friendly-name configuration;
- incompatible Z-Stack backup must never be presented directly to the Ember adapter;
- post-start verify Ember backup identity + frame counter before accepting traffic;
- rollback immediately on network identity mismatch or 0-device live activity.

## Planner

`deploy/build_mg24_emergency_backups.py` is an offline-only, fail-closed builder. It
never talks to hardware and never prints the plaintext network key.

Generated coordinator backup files remain private because they contain Zigbee secrets.
Only the sanitized manifest is suitable for evidence sharing.
