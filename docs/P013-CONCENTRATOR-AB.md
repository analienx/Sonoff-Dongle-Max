# P013 Ember concentrator A/B

This experiment evaluates Zigbee2MQTT/zigbee-herdsman Ember concentrator timing before changing NCP firmware resources.

## Why this is runtime-first

P009 already provides large route/source-route capacity and the Silicon Labs maximum neighbor table. Fresh production evidence therefore does not justify another speculative table increase.

Current zigbee-herdsman loads `stack_config.json` from the same directory as `coordinator_backup.json`, logs the effective stack configuration at startup, applies the concentrator values with `ezspSetConcentrator()`, then enables source-route discovery in `RESCHEDULE` mode.

The Zigbee2MQTT Ember documentation exposes these settings specifically for manual stack tuning. The current default timing is `CONCENTRATOR_MIN_TIME=5` and `CONCENTRATOR_MAX_TIME=60` seconds.

References:
- https://github.com/Koenkk/zigbee-herdsman/blob/master/src/adapter/ember/adapter/emberAdapter.ts
- https://www.zigbee2mqtt.io/guide/adapters/emberznet.html

## Profiles

Baseline:

```json
{
  "CONCENTRATOR_MIN_TIME": 5,
  "CONCENTRATOR_MAX_TIME": 60
}
```

Candidate:

```json
{
  "CONCENTRATOR_MIN_TIME": 10,
  "CONCENTRATOR_MAX_TIME": 120
}
```

All omitted values remain at zigbee-herdsman defaults. The A/B intentionally changes only MTORR timing.

## Live procedure

1. Locate the actual `coordinator_backup.json` used by production Zigbee2MQTT.
2. Put `stack_config.json` in that exact directory.
3. Capture startup logs after restart. Do not assume the file was consumed.
4. Require a startup line containing the effective `Using stack config {...}` JSON and a successful `[CONCENTRATOR] Started source route discovery` line.
5. Collect an ordinary-traffic window. Do **not** run full-network `Mgmt_Rtg`, `Mgmt_Lqi`, or network-map scans during the sample.
6. Repeat with the candidate profile for a comparable window.
7. Compare with:

```bash
python3 deploy/analyze_concentrator_ab.py baseline.log candidate.log --fail-regression
```

The analyzer checks the observed profile, rejects management-scan contamination, normalizes route/soft failures by sample duration, and keeps hard NCP/coordinator failures as an absolute regression boundary.

## Decision boundary

`IMPROVED` means route-error rate fell and soft-failure rate did not rise, with no hard regression. `NO_CLEAR_CHANGE` is not evidence for a firmware change. `WORSE_ROUTING`, `WORSE_SOFT_FAILURES`, `HARD_REGRESSION`, `PROFILE_NOT_CONFIRMED`, or `INVALID_SAMPLE` reject that candidate/sample.

Do not change PAN ID, channel, network key, coordinator IEEE, RF power, route-table sizes, retry policy, or multiple concentrator thresholds as part of the same A/B.
