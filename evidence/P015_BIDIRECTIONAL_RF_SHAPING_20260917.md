# P015 — bidirectional RF topology shaping

## Hypothesis

The MG24 coordinator may hear enough marginal routers to keep the Ember router-neighbor table at or near its 26-entry ceiling and induce neighbor churn. A small passive attenuation on the Zigbee RF path reduces TX and RX link budget together, unlike a software TX-power reduction, and can therefore reduce marginal direct-neighbor competition without creating coordinator-only asymmetric links.

This is an A/B experiment, not a permanent tuning decision.

## Protected invariants

- Keep Zigbee channel 11.
- Keep coordinator IEEE, PAN ID, extPAN ID and network key unchanged.
- Keep production High-RAM concentrator profile at 5/60 seconds, route-error threshold 3, delivery-failure threshold 1.
- Do not change Tuya measurement polling during this RF A/B.
- Do not change firmware tables, retry policy, CCA mode or BSEED router/client roles during this RF A/B.
- Never run a full network map, broad Mgmt_Rtg or broad Mgmt_Lqi scan inside either sample window.

## Baseline

Capture ordinary production Zigbee2MQTT logs with the existing antenna path and 0 dB added attenuation. Preserve startup/effective stack-config lines with the sample so the analyzer can prove the concentrator profile did not drift.

Discard the first 5 minutes after any Zigbee2MQTT/coordinator restart from the measured steady-state window.

## Candidate

1. Stop Zigbee2MQTT and power down the coordinator before changing the antenna path.
2. Insert one 3 dB passive 2.4 GHz inline SMA attenuator in the Zigbee antenna path.
3. Reattach the same antenna and restore coordinator power/Zigbee2MQTT.
4. Confirm the same channel/network identity and the same High-RAM 5/60, route-threshold 3, delivery-threshold 1 profile.
5. Ignore the first 5 minutes after startup, then capture ordinary traffic only.

Do not use software TX-power reduction as a substitute for this candidate; it is not bidirectional shaping.

## Analysis

Run:

```bash
python3 deploy/analyze_rf_shaping_ab.py baseline.log candidate-3db.log \
  --baseline-attenuation-db 0 \
  --candidate-attenuation-db 3 \
  --inventory bridge-devices.json \
  --fail-regression
```

The analyzer reuses the existing route-health and same-destination burst classification. It rejects samples contaminated by management scans and requires the production concentrator profile in both windows.

## Acceptance / rollback gates

Accept 3 dB as promising when:

- route-error rate falls by at least 30%;
- hard coordinator/NCP regression count does not increase;
- same-destination burst rate does not materially regress;
- soft failure rate does not materially regress;
- no practical device-reachability regression is observed.

Rollback immediately if hard failures appear or ordinary command/reachability behavior degrades. Treat >20% route-error regression as a failed candidate.

If 3 dB is `IMPROVED`, keep it for a longer confirmation window before considering additional attenuation. If it is `NO_CLEAR_CHANGE`, do not stack unrelated changes into the same sample; decide separately whether a 6 dB candidate is justified. If it is worse, restore the original antenna path.

## Follow-on experiment kept separate

After RF shaping has a clean result, test the two `_TZ3000_cehuw1lw` / `TS011F_plug_3` Kitchen devices independently by increasing `measurement_poll_interval` from the effective default to 300 seconds. Their polling A/B must not overlap P015, otherwise attribution is lost.
