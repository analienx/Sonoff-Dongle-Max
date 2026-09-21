# R60 coordinator-only neighbor readback — staged, NOT deployed

Parent #18; evidence task #19; instrumentation fallback #21. Source: `runtime/r60_neighbor_extension.cjs`. The extension has passed offline mock tests only. **It is not installed on production Z2M; no live 26/26 occupancy or churn is established by the implementation itself.**

## Verified pinned API and scope

- Zigbee2MQTT 2.14.0 exposes `zigbee.zhController` and loads external extensions through `lib/extension/externalExtensions.ts`; `bridge/request/extension/save` dynamically imports/starts one while writing a file to its data path. Saving an external extension is a **runtime/configuration mutation**, even when its logic is read-only, and is not covered by the canonical HA read-only skill.
- zigbee-herdsman v10.9.1's `Controller.adapter` and EmberAdapter `ezsp` are TypeScript `private`, not stable public extension APIs. They are accessible as ordinary properties in the pinned compiled JS, but every installed-version mismatch or missing API must fail closed. The extension does not instantiate another Controller/Ezsp/serial client.
- The existing EZSP `ezspNeighborCount()` and indexed `ezspGetNeighbor(i)` read the coordinator's NCP-internal neighbor table; they do **not** issue `Mgmt_Lqi`, `Mgmt_Rtg`, ZCL traffic or a network-wide map. The returned fields are `shortId`, `longId`, `averageLqi`, `inCost`, `outCost`, `age`. Index is not a persistent identity; compare by EUI64 locally. The returned age is based on a 16-second aging period per herdsman's pinned type definition.
- The staged extension accepts only `{ "action": "snapshot", "transaction": "r60_01" }` on `<configured-base-topic>/bridge/request/r60_neighbor` and publishes one response on `<configured-base-topic>/bridge/response/r60_neighbor`. The caller must use a unique transaction and request/reply matching, and never publish requests from a public broker.

## Boundedness and limitations

A snapshot performs at most **one** neighbor-count request plus **26** indexed GET_NEIGHBOR requests. It refuses a concurrent request, a request within ten minutes of the previous accepted request, a queue of more than eight owner tasks, an unexpected count above 26, and an entry with non-OK status. It checks an 8-second elapsed budget before each index (an already-dispatched EZSP request cannot safely be canceled; the budget is **not** a strict wall-clock cutoff). EZSP internally serializes frames in its existing owner queue. No periodic background jobs, Zigbee management sweep, counter clears, serial takeover, network identity read, or persistence are performed by the extension itself.

An incomplete snapshot returns an explicit error, never a partial table advertised as complete. `max_supported:26` is a *pinned build contract*, not a measured live hardware limit. A single sample does not establish churn or prove 26/26 is causal; normal traffic samples are required, separated by at least ten minutes and compared by EUI64 after excluding unpowered devices.

## Production gate — NOT authorized by this document

1. Confirm no concurrent OTA, pairing, TX/firmware change or ongoing full-network map. Re-verify current one-owner image/start epoch and exact pinned `zigbee-herdsman` 10.9.1, plus that the installed external-extension loader exists. Confirm per-device ordinary commands are not already suffering a severe incident.
2. Follow `analienx/config` Home Assistant local-executor and mutation-safety skills; external-extension `save` is a runtime/configuration mutation requiring the appropriate deterministic, reviewed deployment/rollback operation. **Do not bypass that gate by calling MQTT directly, injecting Node into the running container, editing add-on files, attaching an inspector, or opening a second UART/TCP NCP owner.** A remote HA mutation operation is not present in the current generic filesystem broker; design and test the narrow operation before live deployment.
3. Validate the exact on-disk extension digest and runtime version, pre-record the previous `external_extensions` state, ensure a known way to stop/remove only this extension, and verify no unintended Zigbee2MQTT owner restart. Do not install via modifying the immutable add-on image/container.
4. Once separately gated, take one bounded snapshot with a transaction identifier; correlate neighbor IEEE/NWK against same-time Z2M database **locally**. Keep raw device identifiers, logs and request replies off public GitHub. Check current command failures and stop on queue saturation, device control regression or reset. Only then consider one further snapshot after the cooldown.

## Status / exact next task

**Blocked for live occupancy evidence until the narrow HA extension-deployment mutation gate and concurrency checks are implemented and approved.** While blocked, #20 can independently investigate actual MG24 stack/source/neighbor-table limits and alternative firmware; do not claim #19 complete, promote the custom firmware branch, or flash production on the strength of this offline test.
