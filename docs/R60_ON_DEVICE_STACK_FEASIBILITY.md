# R60 on-device coordinator stack feasibility — initial source audit (INCOMPLETE)

Parent #18; independent task #20. Scope: EFR32MG24A420F1536IM48 on the SONOFF Dongle-M / Dongle Max, existing Zigbee network, Zigbee NWK/routing/security on the MG24, stock Zigbee2MQTT host. This is **not** a candidate selection, license determination, source/binary reverse-engineering result or production firmware authorization.

## Reproducible source anchors

| Question | Verified evidence | Consequence / unknown |
|---|---|---|
| Exact existing board manifest | Pinned `Nerivec/silabs-firmware-builder@858c34b0eb6f53a2e0c89455ea489ceaa62d58db`, [`manifests/sonoff/sonoff_dongle-m_zigbee_ncp.yaml`](https://github.com/Nerivec/silabs-firmware-builder/blob/858c34b0eb6f53a2e0c89455ea489ceaa62d58db/manifests/sonoff/sonoff_dongle-m_zigbee_ncp.yaml), targets `EFR32MG24A420F1536IM48`, `src/zigbee_ncp`, Simplicity SDK `2026.6.1`, GCC `14.2.1`, `EUSART1`, `115200`, no UART hardware flow control | Reproducible *source manifest*, not attestation of current production NCP binary or >26-neighbor support. |
| Our large-network profile | [`firmware/RESOURCE-PROFILE.md`](https://github.com/analienx/Sonoff-Dongle-Max/blob/p009-hardening/firmware/RESOURCE-PROFILE.md) records neighbor capacity 26, route/source route 254/254 and distinct runtime vs linked capacities | 60 mesh routers do not imply 60 direct coordinator neighbors; remaining failures require measured on-device occupancy/churn and end-to-end command outcomes. |
| Upstream EmberZNet configuration | [Silicon Labs EmberZNet 9.1.1 configuration defaults](https://docs.silabs.com/zigbee/9.1.1/zigbee-stack-api/sl-zigbee-configuration-defaults-h) defines max neighbor-table size 26 and a compile-time check admitting 1, 16 or 26 | Simply changing `SL_ZIGBEE_NEIGHBOR_TABLE_SIZE` to 60 is **not a supported EmberZNet 9.1.1 configuration**. This alone is not evidence of a silicon limit, and does not prove how much of neighbor/routing implementation is provided as modifiable source versus precompiled library. |
| Present diagnostic path | Pinned [zigbee-herdsman v10.9.1 `ezsp.ts`](https://github.com/Koenkk/zigbee-herdsman/blob/v10.9.1/src/adapter/ember/ezsp/ezsp.ts) exposes coordinator-local `ezspNeighborCount()` and indexed `ezspGetNeighbor(i)` | Safe owner-mediated readback has been staged in PR #25, **not deployed**. It can establish whether local 26/26 is currently real, but does not expose or enlarge the internal stack algorithms. |
| Alternative SONOFF builder firmware | Pinned builder lists a SONOFF Dongle-M Zigbee router and OpenThread RCP alongside its Zigbee NCP manifest | These are *different roles/protocols*; their existence does not establish an MG24 Zigbee coordinator with 60 direct neighbors, ordinary EZSP compatibility, or network-preserving migration. |
| NXP large-neighbor design reference | [NXP table-configuration guidelines](https://mcuxpresso.nxp.com/mcuxsdk/25.09.00/html/middleware/wireless/zigbee/Docs/JNUG3130/topics/table_configuration_guidelines.html) describe using multiple Link Status messages with larger neighbor tables | Architecture reference only. NXP code/binaries are not shown to target this MG24, implement the SONOFF board support, or be compatible with current EZSP/network state. |

## Candidate matrix — evidence grades, not assumptions

| Candidate | EFR32MG24 / SONOFF board | Stock Z2M EZSP | >26 DIRECT neighbors | Exact network-state continuity | Physical validation |
|---|---|---|---|---|---|
| Pinned EmberZNet 9.1.1 board NCP | Yes at manifest level / exact live binary unverified | Pinned existing host path | **No supported config above 26**; alternate internals unverified | Existing deployment path intended to preserve it; new image needs exact rollback and identity proof | No new R60 image tested |
| Nabu Casa / third-party EFR32MG24 builds | Not yet audited for exact SONOFF board | Not yet audited | Unknown | Unknown | None shown |
| Replace/extend parts of on-device Ember stack | Requires SDK symbol, source and library audit | Must preserve EZSP19 | Unknown until complete admission/aging/indexing/Link Status/Mgmt_Lqi/security audit | Unknown; proof required | None |
| Clean open embedded Zigbee PRO stack port to MG24 | No complete candidate verified | EZSP compatibility or safe adapter work unverified | Unknown | Trust center, counters, tokens and existing network security/identity must be proved | None |
| Historical TI Z-Stack on SLZB-06P7 | Different MCU/vendor and board | Different host adapter | Not a verified MG24 binary | Behavioral comparison only | Not a SONOFF candidate |

## Engineering go/no-go and pending investigations

**No verified drop-in MG24 / SONOFF 60-direct-neighbor NCP has been established in this audit.** This means *not verified*, not proof that none exists. The production problem may be solved with 26 direct neighbors if a different source-route/queue/RF/map defect is identified; do not presuppose that 60 direct neighbors are necessary.

Before attempting custom-stack work on a **non-production SDK/build copy**, record the generated `SL_ZIGBEE_NEIGHBOR_TABLE_SIZE` header and config validation, extract linked ELF / `.map` / link command and library archives, and identify the implementation owners (source vs replaceable object vs opaque archive) for neighbor admission/eviction/aging, routing indexes, Link Status packing/fragmentation TX+RX, Mgmt_Lqi pagination and NWK/security paths. Do not claim to have audited symbol visibility, linker relocations, license rights or actual RAM/flash headroom from this manifest-only review. Any added 34 entries impose additional index, packet-format and neighbor-advertisement work; **no measured byte or timing cost exists yet**. Check upstream license terms for the builder/SDK and any alternate source before modifying or redistributing it.

**Next concrete #20 action:** on a non-production pinned-builder/SDK checkout, obtain the generated project and ELF/link-map and record exact symbol/library provenance for neighbor-table validation, admission/aging and Link Status encoding. Keep #20 open until the broader candidate/license/source audit is complete. Production firmware flashing is outside this task.
