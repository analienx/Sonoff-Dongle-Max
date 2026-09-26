# P10 fresh-network rebuild / reconciliation

## Status

Tooling version: 0.2.0.

The first v0.1 pilot attempt uncovered a critical CC2674P10/Z-Stack behavior:
standard zigbee-herdsman recommissioning (STARTUP_OPTION=0x03 plus new PAN/key)
did not clear the extended address-manager table.

The first post-commission backup showed:
- address-manager capacity 457, used 10;
- all 8 pre-pilot coordinator-backup IEEE entries still present;
- 2 additional address entries;
- fresh Zigbee2MQTT database with 0 ordinary devices.

Therefore a new PAN/key is not sufficient evidence of a clean P10 on this
firmware. v0.2 refuses live fresh commissioning without independent P10 NVRAM
sanitation evidence.

No pilot device may be reset or paired while fresh_prejoin_state_clean=false.

## Recovery artifact terminology

Verified cold bundle:
C:\Workspace\.analienx\sonoff-private\issues\p10\bundles\cold-p10-pre-fresh-pilot-20260926T065336Z.zip

SHA-256:
387e68587df8e2872f73007513c2b8451a4be3735183d98a85510abc96e26a68

This is a logical Zigbee2MQTT/coordinator-backup rollback point containing the
captured application data and HA add-on options. It is not a raw byte-for-byte
P10 NVRAM image.

Rollback verification requires the production coordinator IEEE, PAN/extPAN,
channel and network key to return; the expected coordinator-backup records and
database device count must be present; and HA add-on options must match.

## Current v0.2 private manifests

Full:
C:\Workspace\.analienx\sonoff-private\issues\p10\rebuild-manifest-v0.2.0-20260926.json

Pilot:
C:\Workspace\.analienx\sonoff-private\issues\p10\pilot-manifest-v0.2.0-20260926.json

The full manifest contains 105 non-coordinator devices and 21 groups. It stores
friendly names, device options, group IDs/options/memberships, non-coordinator
bindings and reporting references. It does not contain the Zigbee network key.

The pilot set remains:
- WRSocketWindowLeft — 0xa4c138ef578c9f75
- KitchenSocketRight — 0xa4c138075cd16ed4
- HallBreakerFA5 — 0x94b216fffe9260f5
- RODRET A — 0x348d13fffefffa53
- RODRET B — 0x08fd52fffed5864e

Group 31 (Sockets Nonessential Shutdown) is included, but pilot group membership
is filtered to selected pilot devices only.

## Fresh-network cutover state machine

Tool: deploy/p10_fresh_network_pilot.py

v0.2 changes:
- Supervisor startup is treated as an in-progress start, not a reason to send a
  second start command.
- Stop/start command exit codes are secondary to observed Supervisor and
  container state.
- Failed fresh verification never triggers an automatic rollback through a
  startup race. The add-on is frozen stopped and explicit rollback is required.
- Atomic file replacement has no destructive remove-then-rename fallback.
- The official HA add-on forces Home Assistant discovery enabled, so the pilot
  isolates discovery instead:
  - MQTT base: zigbee2mqtt_p10_pilot
  - discovery prefix: homeassistant_p10_pilot
  - HA status topic: homeassistant_p10_pilot/status
- Fresh verification requires 0 ordinary Z2M devices, 0 coordinator-backup
  device entries, 0 address-manager entries, 0 security-manager entries,
  0 APS link-key-data entries, 0 TCLK entries, no old IEEE overlap, and a
  different network fingerprint from production.
- Live cutover requires sanitation evidence format p10-nv-sanitation-evidence-v1.
- Permit join is never opened by this tool.

Read-only status:
python deploy\p10_fresh_network_pilot.py status

A fresh prejoin state is usable only when fresh_prejoin_state_clean=true.

Logical rollback:
python deploy\p10_fresh_network_pilot.py rollback --bundle <cold.zip> --sha256 <sha> --approval RESTORE_PRE_PILOT_P10_LOGICAL_STATE

Rollback performs: genuine quiescence, add-on option restoration if needed,
atomic application-data restore, single startup, then production identity and
database verification. Failure leaves the add-on stopped.

## Application-state reconciler

Tool: deploy/p10_rebuild_reconciler.py

Every executable plan is bound to a secret-free network fingerprint derived
from coordinator IEEE, PAN ID, extended PAN ID and channel. Live apply re-reads
the current coordinator backup and refuses to run against a different network.

Every live execution also requires a persistent journal. Successful operation
IDs are recorded; failed operations are not marked complete, so a sleepy device
can be retried safely.

v0.2 also:
- fails closed on unresolved pilot selectors;
- filters pilot group members to selected devices;
- restores group friendly names with group/rename;
- scopes group operations to related device restores only;
- compares existing custom bindings before binding;
- runs converter configure once per network/journal;
- disables raw reporting replay;
- treats reporting mismatches as explicit review/configure items;
- fails non-zero if any MQTT operation fails;
- verifies actual names/options/groups/bindings/reporting in status rather than
  treating a successful interview as full restoration.

The production cold bundle self-check reports 104/105 fully restored. The one
non-pass is the RODRET that was already captured with an incomplete interview.

## Pilot acceptance gate

Before promotion require:
1. genuinely clean P10 prejoin table state;
2. all three pilot routers joined/interviewed and registered;
3. both RODRETs joined/configured and repeatedly publishing actions;
4. group 31 state restored where applicable;
5. BSEED options/reporting behavior restored;
6. repeated unicast commands pass;
7. groupcast passes;
8. at least one meaningful routed/multi-hop path passes;
9. coordinator_check has no missing pilot router;
10. stop/start Zigbee2MQTT once;
11. all pilot devices return after restart;
12. coordinator_check remains clean after restart;
13. reconciler status confirms application-state restoration;
14. no unexpected coordinator/address/security records appear.

Only after every gate passes does the same pilot network expand into production.

## Remaining blocker: true P10 sanitation

The standard zigbee-herdsman clear/recommission sequence demonstrably leaves
extended address-manager records on this CC2674P10 firmware.

A destructive NVRAM sanitizer is deliberately not implemented in this branch
until the exact mechanism is validated for MR4U CC2674P10 revision 20260310.
Potential zigpy-znp nvram_reset use must be preceded by compatibility review,
low-level backup planning, and post-wipe evidence generation.

Until then v0.2 intentionally refuses fresh commissioning.

## Intentionally manual / review-only

- physically factory-resetting or waking devices;
- deciding whether a breaker/socket load is safe to interrupt;
- manufacturer-specific reporting recreation when metadata is incomplete;
- raw P10 NVRAM wipe before its toolchain is separately validated;
- claiming Home Assistant entity continuity without post-join validation.
