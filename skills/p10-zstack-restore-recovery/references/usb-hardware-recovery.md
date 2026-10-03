# Bounded P10 USB hardware recovery

Use this branch for a previously running, validated network that loses command service, including progressive AF → ZDO → SYS timeouts. Keep the existing identity, security state and application database. It is separate from a failed initial restore.

## Establish the target and ownership

- Identify the actual radio through USB identity, persistent by-id interface, sysfs interface number and previously verified chipset/firmware. On the measured MR4U, **if00 was MG26 and if02 was P10**. Neither is an ESP32 management/Berry console. Do not generalize this mapping to every unit or trust ttyACM numbering alone.
- Capture bounded, timestamped private logs and current configuration before intervention. Preserve the backup and database; never publish their contents or hardware/network identifiers.
- Stop Zigbee2MQTT and verify Supervisor/container state and exclusive serial ownership. Disable an independent Supervisor watchdog that could race the recovery controller. Use a single-flight lock and exclusive serial access; refuse to open a busy port.
- Verify both application YAML and Supervisor serial options, baud rate, flow control and the intended TX setting. Preserve the user's deployment setting rather than imposing a universal TX value.
- Gate network identity/channel/key against the intended preserved backup. A backup is a comparison reference, not permission to replay older frame counters.

## One hardware attempt, then explicit acceptance

1. With the application stopped, issue bounded read-only probes: three SYS ping attempts and SYS version. If the radio is responsive, validate its state and return **without a reset**. Partial or inconsistent responses need diagnosis, not a reset loop.
2. Only when all ping attempts and version fail may the reviewed hardware-reset mechanism run once. Verify the exact target/Core DTR/RTS mapping before deployment. A normal-boot radio reset is distinct from bootloader entry, flashing or a host USB re-enumeration. Do not use a speculative pulse or send management commands to MG26.
3. Before the pulse, write and fsync a private **pending-attempt latch**. Preserve it across HA/recovery-process restarts. Deassert reset/boot signals in a finally path.
4. After the pulse, require repeated valid SYS ping, an accepted SYS version and read-only state validation: effective IEEE, NIB PAN/extended PAN/channel, configured/startup/BDB flags, active-key fingerprint and non-regressed security counters. A valid ping alone does not authorize application startup.
5. Start stock Zigbee2MQTT only after those gates pass. Keep the attempt latched while raw validation has passed but application acceptance is incomplete.
6. Subscribe before publishing a uniquely correlated `bridge/request/permit_join` request with `time: 0`. Require a fresh, non-retained successful response with the matching transaction and closed-join result. This checks outbound ZDO without opening pairing. Bridge-online state or unsolicited reports alone are insufficient.
7. Record success and apply a cooldown. On a failed gate, stop/leave the application stopped, retain a durable failed-attempt latch and notify with the captured evidence. A failed, pending or incomplete attempt must block further automatic pulses, including after HA reboot. Clear it only after explicit review of the failure and current state.

Never erase/replay NVRAM, form a new network, re-pair devices, flash firmware, or change PAN/channel/key/IEEE as part of this controller. A host reboot may leave a PoE-powered MR4U running; it is not an equivalent radio cold reset.

## Evidence limits

On 2026-10-03, production was already running on USB with firmware 20240716 when the guarded controller was deployed. Fresh inbound reports and a correlated outbound closed-join ZDO response passed; the running Zigbee2MQTT container was preserved. Regression tests cover refusal gates and durable attempt state. **The complete new controller's reset branch has not yet been accepted during a real runtime hang.** Do not induce a production outage merely to claim that validation, and do not describe the controller as a firmware root-cause fix.

The HA implementation and deployment evidence live in the private Home Assistant stack's `docs/P10_USB_RECOVERY_AUTOMATION.md`. Keep household paths and identifiers in that private implementation; this reference defines the portable gate contract.
