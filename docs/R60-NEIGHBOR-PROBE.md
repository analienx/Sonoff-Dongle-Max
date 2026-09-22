# R60 coordinator-only neighbor readback — staged, NOT deployed

Parent #18; evidence task #19; instrumentation fallback #21. Source: `runtime/r60_neighbor_extension.cjs`. Offline mock tests passed; the extension is **not installed** on production Z2M. A successful single read-only HA collection on 2026-09-22 is documented in `evidence/R60_ONE_PASS_20260922.md`. Those retained stock logs do not expose a live coordinator-neighbor table; no live 26/26 occupancy or churn is established. The user requested **one HA log collection pass only**, which has been completed. Do not re-collect logs while working from that archive.

## Verified pinned API and scope

- Zigbee2MQTT 2.14.0 exposes `zigbee.zhController` and loads external extensions through `lib/extension/externalExtensions.ts`; `bridge/request/extension/save` dynamically imports/starts one while writing a file to its data path. Saving an external extension is a runtime/configuration mutation, even when its logic is read-only, and is not covered by the canonical HA read-only skill.
- zigbee-herdsman v10.9.1's `Controller.adapter` and EmberAdapter `ezsp` are TypeScript `private`, not stable public extension APIs. They are accessible as ordinary properties in pinned compiled JS, but installed-version mismatch or missing API must fail closed. The extension does not instantiate another Controller/Ezsp/serial client.
- Existing EZSP `ezspNeighborCount()` and indexed `ezspGetNeighbor(i)` read only the coordinator's NCP-internal neighbor table; they do not issue `Mgmt_Lqi`, `Mgmt_Rtg`, ZCL traffic or a network-wide map. Returned fields are `shortId`, `longId`, `averageLqi`, `inCost`, `outCost`, `age`. Index is not persistent identity; compare by EUI64 locally. Returned age has a 16-second aging period in pinned herdsman type definitions.
- Staged extension accepts only `{ "action": "snapshot", "transaction": "r60_01" }` on `<configured-base-topic>/bridge/request/r60_neighbor` and responds on `<configured-base-topic>/bridge/response/r60_neighbor`. Requests require unique transaction/request-reply matching. Never publish requests from a public broker.

## Boundedness and limitations

At most **one** neighbor-count request plus **26** indexed GET_NEIGHBOR requests; refuses concurrent calls, ten-minute cooldown violation, queue over eight, count over 26, and non-OK entry. Eight-second elapsed check occurs between calls, **not** a hard wall-clock timeout of in-flight EZSP requests. EZSP uses the existing NCP serial owner. No periodic background job, mesh sweep, counter clear, network identity read, persistence or second serial owner. Incomplete snapshots explicitly fail; `max_supported:26` describes this pinned build, not a silicon limit. A single table sample does not prove congestion caused ordinary command failures.

## Production gate — NOT authorized by this document

1. First use the **single saved HA evidence archive** and existing per-device Hall-bulb/socket `set` failures to implement the narrowest reproducible reliability fix. Do not require an extension deployment merely to continue service-failure work. Freeze simultaneous TX experimentation, restarting, OTA, pairing and broad maps.
2. If a local-neighbor snapshot becomes necessary for a specific test, confirm no concurrent OTA, pairing, TX/firmware change or ongoing full-network map. Verify one-owner image/start epoch, exact installed herdsman 10.9.1 and external-extension loader. Follow `analienx/config` local-executor and mutation-safety skills: extension `save` requires a deterministic, reviewed deployment/rollback operation. Do not bypass via raw MQTT, injecting Node, arbitrary container editing, inspector or second UART/TCP owner.
3. Confirm staged digest, pre-existing extension state, and exact stop/remove rollback. Do not modify immutable add-on image. Require separately gated authorization before any live install.
4. Once separately gated, request a single bounded snapshot with unique transaction, correlate neighbor IEEE/NWK to same-time DB locally; keep private identifiers off public GitHub. Stop on queue pressure, command regression or reset. No broad network map.

## Status

**NOT DEPLOYED / OPTIONAL NEXT DIAGNOSTIC.** The completed one-pass HA log archive has sufficient evidence of continuing real command failures to prioritize controlled service stabilization now. Stock logs cannot reveal 26/26 live neighbor occupancy; do not claim the table caused failures or declare #19's full occupancy acceptance criteria achieved.
