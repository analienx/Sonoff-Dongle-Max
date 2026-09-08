# P012 — watchdog/reset-cause resilience research

P012 is a required **research and validation component** of the release bundle. It is **not enabled in P009** and must not be treated as production firmware until the local hardware experiment below passes.

## Verified baseline

The pinned upstream project is `Nerivec/silabs-firmware-builder@858c34b0eb6f53a2e0c89455ea489ceaa62d58db`, SDK 2026.6.1 / EmberZNet 9.1.1.

The selected `zigbee_ncp.slcp` components include the Zigbee stack, NCP UART hardware, Green Power, security/link-key support, token interface, R22/R23 support and related platform components. **No watchdog component is explicitly selected in the pinned NCP project.**

Therefore:

- P009 does not introduce watchdog behavior;
- P011 does not introduce watchdog behavior;
- P013 does not introduce watchdog behavior;
- no release claim assumes a watchdog is running merely because the MCU may contain watchdog hardware;
- reset cause/watchdog recovery is not considered proven by CI alone.

## Why watchdog is not silently enabled

A watchdog can improve recovery from a true firmware hang, but a poorly understood watchdog can also convert a diagnosable assert/hang into a silent reboot loop. That would make this network harder to debug and could repeatedly interrupt coordinator service while hiding the causal failure.

The production criterion is therefore **fail-visible recovery**, not simply “the NCP restarted.”

## Required local experiment before promotion

Use non-production/spare Dongle-M hardware. The executor remains a bounded test operator; no local code edits are allowed.

A future P012 experimental image must:

1. preserve the exact P009 Zigbee resource and transport profile unless a change is explicitly identified as P012-only;
2. have a distinct build/profile identity and hash;
3. preserve NVM/network identity across the test;
4. expose a reset cause that distinguishes at least the controlled watchdog reset from ordinary power-on/software restart where the SDK supports it;
5. use a documented timeout/feed owner;
6. survive one deliberate controlled hang and recover once;
7. not enter a repeated reset loop;
8. leave enough evidence to determine why the reset occurred;
9. show no automatic NVM clear, network reform, re-pairing or route manipulation.

### Test sequence

The exact mechanical command sequence will be issued only after a P012 experimental image exists and CI proves it preserves P009 invariants. The local operator will then:

- flash only the explicitly identified P012 experimental image to spare/non-production hardware;
- capture pre-test identity and reset diagnostics;
- trigger one supervisor-defined controlled hang/fault;
- capture reboot/reset-cause evidence;
- verify the device does not repeat-reset;
- verify network/NVM identity is preserved where applicable;
- stop and report raw evidence.

No soak test or repeated fault campaign is required for the first decision.

## Promotion gate

P012 may be considered for a future production profile only if all of the following become true:

- watchdog component/API and feed ownership are source-proven for the pinned SDK;
- one controlled hang demonstrates recovery;
- reset cause is externally observable and unambiguous enough for operations;
- no reset loop is observed;
- network state is preserved;
- linked RAM/flash impact is measured;
- ordinary stock Zigbee2MQTT startup/operation remains compatible;
- the benefit addresses a real observed failure class.

Until then the release status is:

```text
P012 = required research/diagnostic deliverable
P009 watchdog = disabled / unchanged from pinned base project
production promotion = BLOCKED ON LOCAL HARDWARE VALIDATION
```

Issue: https://github.com/analienx/Sonoff-Dongle-Max/issues/9
