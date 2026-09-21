# R60 owner restart and transient address conflicts — 2026-09-21

Parent #18; #19 passive baseline; PR #25. All observations are from **read-only SSH log/metadata inspection**, without opening an NCP serial client, installing an extension, changing network/HA or issuing network-wide management requests. Counts are log lines, not deduplicated device events or command-failure rates. All times below are 2026-09-21 UTC unless noted.

## Reproducible sanitized evidence

```powershell
py -3 deploy/r60_probe.py
py -3 deploy/r60_extension_preflight.py
py -3 deploy/r60_restart_timeline.py
py -3 deploy/r60_ota_activity.py
py -3 -m unittest discover -s tests -p 'test_r60_*.py' -q
node --test tests/test_r60_neighbor_extension.cjs
```

Retain any unsanitized log, EUI64/NWK, Zigbee database, credentials and MQTT payload **only in authorized local storage**, never in this public repository. Timeline tools return only predeclared event categories and minute bins; their categories can overlap and do not establish causation.

## Timestamped evidence and corrected interpretation

- Passive inventory at **20:25:01 UTC** still showed **61 Router / 44 EndDevice / 1 Coordinator database records**, one Zigbee2MQTT owner started **18:36:47 UTC**, configured Ember/herdsman 10.9.1; records do *not* prove active router count.
- Docker event log at **20:25:00 UTC** records `kill`, followed at **20:25:07 UTC** by `stop`, `die`, `destroy`, `create`, `start` for the Zigbee2MQTT container. The new owner has start epoch **20:25:07 UTC** (restart count zero for *this new container*). This proves a container lifecycle/replacement, **not** why or by whom it was requested. Do not describe it as a proven spontaneous crash, NCP reset or OTA-triggered restart.
- Previous log session `2026-09-21.20-36-50` ended **22:25:06 local (20:25:06 UTC)**. It contained **184 route-error lines** over ~108 minutes: many-to-one 118, source-route 34, non-tree 12, indirect expiry 8, address conflict 12. The earlier 155 count was a shorter prefix of this *same* session; do not treat those as independent runs.
- New session `2026-09-21.22-25-09` began **22:25:09 local**; by 22:27:52 it had **18 address-conflict route-error lines**, plus one each of many-to-one, non-tree and source-route. The burst is real as log output; its initiating device, NWK/IEEE history and causal relation to container replacement are **unverified**.
- **Correction of the first OTA classifier:** the initial regex `zigbee.*update` erroneously included generic Zigbee updates. It was removed in commit `e905242`. A narrower classifier subsequently found **19 explicit OTA-related references** at local 22:25 and 19 at 22:27, but none matching its *firmware-transfer start, progress or completion* templates in the inspected windows. Such references can describe OTA metadata, extension startup or availability; **an active OTA transfer is neither proved nor excluded**. No user-visible change or rollback was attempted.
- A read-only compatibility preflight at **20:27:33 UTC** found one Ember owner, installed Zigbee2MQTT **2.14.0**, herdsman **10.9.1**, the external-extension loader on disk and no existing `r60_neighbor_extension.cjs`. Staged source SHA-256 was `a0ce05511e11adc9a79296182bcfe9b10225b855cbfb8c1c3f9c51625d84b199`. Its result was `static_preflight_ok=true`, **`deployment_authorized=false`**: no in-memory API attestation, trusted concurrent-OTA/pairing/map exclusion, approved typed deployment broker/rollback or stable-epoch proof during a future operation.

## Operational consequence / remaining blockers

Start a new ordinary-traffic comparison window at the **20:25:07 UTC owner epoch**; do not combine its post-restart burst with previous rates as one stationary regime. A fresh log directory does not establish a radio reset. Do not deploy the neighbor extension just because a static compatibility probe passed: first implement and independently validate the canonical narrow HA mutation/rollback gate and an authenticated current-workload check. Only a separately gated coordinator-local snapshot can establish current 26/26 occupancy and subsequent churn; #19 and #18 remain open. The non-production #20 stack/ELF feasibility audit can proceed without touching live HA.
