# R60 end-to-end placement experiment (v2)

**Canonical task and acceptance:** [Sonoff issue #27](https://github.com/analienx/Sonoff-Dongle-Max/issues/27); parent [#19](https://github.com/analienx/Sonoff-Dongle-Max/issues/19), epic [#18](https://github.com/analienx/Sonoff-Dongle-Max/issues/18). Reproducible source lives in standard `deploy/`, `runtime/` and `tests/`; sanitized dated A evidence lives in `evidence/issue-27/`. The corresponding sole-owner host safety gate belongs to [config PR #61](https://github.com/analienx/config/pull/61), not a duplicate experiment.

**Issue-specific private results:** `C:\Workspace\.analienx\sonoff-private\issues\27-placement\r60_placement_v2_{before,after,after_retry1,confirm}.json`. The A baseline and its two NCP and one ZCL raw captures were copied there with SHA-256 verification, originals preserved in the shared owner-gate capture spool. The frozen legacy MQTT-only cohort remains at the historical private root solely for identity matching. Raw addresses and NCP snapshots are never committed.


**Status:** Implemented and offline-tested, not a firmware fix. Original `r60_placement_before.json` remains immutable. Its 11/11 outcomes are MQTT state *proxies*, never counted as verified ZCL successes. The issue #27 true-ZCL A baseline has already been captured and preserved; do not rerun `before` on this issue. The #27 A/B/B-repeat experiment is complete. The first B attempt was preserved as `valid=false` after a synchronous NCP counter reset; a distinct `after_retry1` capture and `confirm` both completed validly. See `evidence/issue-27/R60_PLACEMENT_AFTER_20260922.md`. Do not rerun any immutable issue #27 stage.

On the authorized Zephyrus laptop, from the existing `C:\Workspace\worktrees\Sonoff-Dongle-Max-r60` tree:

```powershell
# HISTORICAL COMMANDS ONLY; #27 stages are complete and immutable. Do NOT rerun them.
# A complete and immutable: 33/33 verified ZCL reads; do NOT rerun before.
# Now physically move the WHOLE SONOFF at least 1 m away from Pi, SSD and USB3 cable;
# keep antenna orientation, channel, TX power and network unchanged.
py -3 deploy\r60_placement_experiment.py after --relocated --seconds 300
# After a rejected counter-reset window, preserve it and run one uniquely named retry:
py -3 deploy\r60_placement_experiment.py after_retry1 --relocated --seconds 300
py -3 deploy\r60_placement_experiment.py report
# Optional: leave SONOFF at the moved location, repeat under ordinary traffic.
py -3 deploy\r60_placement_experiment.py confirm --relocated --seconds 300
py -3 deploy\r60_placement_experiment.py report
```

Each stage: pin one running Ember Z2M 2.14.0/herdsman 10.9.1 owner and configuration, take a non-clearing NCP counters + neighbor/source-route snapshot through the existing owner, run 3 staggered `genOnOff.onOff` ZCL **read-only** operations on each of exactly 11 previously chosen powered routers, take a second NCP snapshot and audit the hourly counter-clear marker. One callback-resolved `endpoint.read()` result with actual `onOff` is counted as ZCL success; MQTT state updates are not. Per-device unsupported read, timeout and absence are separately classified; devices intentionally powered off are excluded by construction. No change to power, relay state, pairing, firmware, channel, PAN/IEEE, Zigbee2MQTT config or database.

Every temporary `.cjs` diagnostic is SHA256-pinned, installed only via Z2M's current owner and removed in a `finally` block. The typed gate rejects multiple owners, changed owner epoch, old plan replay, unknown image/runtime, enabled permit-join and preexisting extension; an incomplete probe or unverified removal invalidates the stage and MUST be inspected before retrying. Only the canonical HA SSH helper is used; no second serial/EZSP owner. Results and identifiers stay in `C:\Workspace\.analienx\sonoff-private`, never in Git.

The report pairs MAC-failure fraction/rate, retry and CCA rates, neighbor add/remove rate and *distinct* neighbor replacements against exact-device 3-attempt ZCL success/latency. It rejects counter reset, absent targeted log coverage, owner restart, unbalanced (>2x) traffic, or device-command regressions even if NCP counters improved. Cached source-route first-hop grouping is **diagnostic association**, not verified radio path. A short result cannot demonstrate permanent mesh reliability or isolate USB3 noise from changed antenna geometry. Do not run a full network map or turn routers on/off during a window.

Review checks: `py -3 -m unittest discover -s tests -p 'test_r60_*.py'` and `node --test tests/test_r60_verified_read_extension.cjs`. The new v2 results are independent of the preserved legacy placement baseline. `after`, `after_retry1`, and `confirm` require the explicit `--relocated` flag and never move hardware automatically.
