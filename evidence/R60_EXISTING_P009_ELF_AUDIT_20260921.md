# R60 non-production linked-ELF capacity audit — 2026-09-21

Issue #20 under #18; draft PR #26. This is an examination of an **existing, older** GitHub Actions P009 build artifact; nothing was built, flashed, read from the MG24 radio or deployed to production. It does not attest the identity of the image now running on SONOFF.

## Provenance and repeatable inspection

GitHub Actions run [`33907171158`](https://github.com/analienx/Sonoff-Dongle-Max/actions/runs/33907171158), artifact ID `9950031778`, name `sonoff-dongle-max-p009-9.1.1` (ZIP, not expired at inspection). The archive contains `P009-BUILD-MANIFEST.json`, hashes, original P009 and stock rollback `.out` (ELF), GBL/HEX and `.slcp`. The embedded manifest reports pinned builder `Nerivec/silabs-firmware-builder@858c34b0eb6f53a2e0c89455ea489ceaa62d58db`, SDK `2026.6.1`, EmberZNet `9.1.1` and EZSP `19`. Its source profile specifies **26** neighbor entries for both stock and P009. **This is an older three-delta P009 artifact with multicast 26**, not the later multicast-32 source-profile generation and not a live on-device firmware attestation.

Archive SHA-256s verified against the embedded manifest:

- P009 `.out`: `1cd29888a041e7606abf6718e48cf2eeffef41eecd25ef2ef1a7b2a32086aa28`.
- Stock rollback `.out`: `8368d3470d0622445c6b8946a68f2309fa71032ec7818e79e3481924b727328e`.

After downloading that pre-existing artifact and extracting only the `.out` files into an isolated non-production workspace, reproduce with `file P009.out`, `sha256sum P009.out stock.out`, `readelf -Ws P009.out`, `readelf -SW P009.out`, and `readelf --debug-dump=info P009.out`. Do not publish or redistribute proprietary SDK binaries outside the repository's existing authorized artifact permissions; no firmware modification was undertaken here.

## Observed linked storage and callable symbols

Both `.out` images are **ELF32 little-endian ARM EABI5 statically linked executables** with an intact symbol table and DWARF debug information. The P009 `.symtab` reports:

| ELF name | P009 size | Significance / limit |
|---|---:|---|
| `sli_zigbee_neighbor_data` | **486 B** at `0x2000321a` (`GLOBAL HIDDEN`, `.bss`) | Actual linked table object, **not** by itself proof that every operation supports >26. Stock has the same 486 B array. |
| `sli_zigbee_neighbor_count` | 1 B at `0x20003218` | Current neighbor-count field storage, not measured runtime occupancy. |
| `sli_zigbee_router_neighbor_table_size` | 1 B in `.data` | Configuration/data field; its presence does not establish a safe supported value above 26. |
| `insertNeighbor.lto_priv.0` | 416 B of function text | Neighbor admission implementation exists in the linked binary, with a link-time-optimized private symbol. No source replaceability/interposition right is inferred. |
| `sli_zigbee_neighbor_exchange_event_handler` | 210 B text | Neighbor exchange path present; no claim of multi-frame Link Status TX/RX support. |
| `sli_zigbee_route_table` | 2,040 B in `.bss` | Route storage is separate from neighbor storage. |

DWARF for `sli_zigbee_neighbor_data` identifies compilation unit `/repo/build/simplicity_sdk_2026.6.1/zigbee/stack/config/sl_zigbee_configuration.c`, source line 253. The array has `DW_AT_upper_bound: 26`, i.e. **27 allocated elements**, each a **18-byte** `sl_zigbee_neighbor_table_entry_info_t` (`27 × 18 = 486 B`). The publicly configured **26 active neighbors** are not the same as the 27-slot backing array; the role of the extra slot must be established from SDK source before changing any index rule. Extrapolating an unchanged 18-byte layout from 27 slots to *61 physical slots* for 60 active entries would add **612 B of this array only**; this is **not** a measured total SRAM budget or a verified patch route. Other tables, alignment, queues, aging, Link Status frame sizing, serialization and security need separate audits.

Archive P009 `.bss` section is `0x59cc` bytes versus stock `0x570c` (delta **704 B**) with unchanged `.memory_manager_heap` section `0x38208` bytes. These measurements belong to the *older* three-delta artifact, not the newer multicast-32 report. A reserved heap section does not tell us available live packet memory.

## Critical source/ABI gaps (NOT resolved)

`GLOBAL HIDDEN` and `lto_priv.0` are ELF symbol/linkage properties, **not** a license to override or proof that object-level replacement is supported. This artifact contains **zero `.map` files and zero SDK `.a` archives**. The source path for the table allocation is present through DWARF, but the exact object/library and license for neighbor admission, aging, neighbor exchange and Link Status, route lookups, Mgmt_Lqi pagination, and any index-width or packet-format assumptions cannot be established from symbol names alone. Even though an isolated array expansion might cost only hundreds of bytes, the stock SDK config validator still refuses a simple table-size change to 60. Preserve the complete on-device Zigbee NWK/security/trust-center implementation and the original network state.

**One next #20 action:** obtain the same pinned SDK's non-production generated build/link map and library link command (without starting another public GitHub Actions run); identify the exact implementation-owning object/archive and source/license access for `insertNeighbor`, neighbor eviction/aging, Link Status TX/RX and Mgmt_Lqi. If those implementations cannot lawfully be modified/replaced as a complete unit, document that blocker and investigate other on-device reliability changes retaining 26 direct neighbors. #20 and #18 remain open. No production settings or firmware changed.
