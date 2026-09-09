# Super-executor architecture review disposition

Source review: `docs/ISSUE-7-ARCHITECTURE-REVIEW.md` at commit `74301b780389acdc742def9f41bbd3fb14bc8653`.

This document is the supervisor implementation matrix. It deliberately distinguishes what belongs in the P009 release from separately identifiable follow-up work.

## P009 immutable profile

P009 is limited to these firmware deltas versus the matched stock rollback:

- RX buffer 128 -> 512
- broadcast table 30 -> 64
- key table 1 -> 12
- multicast table remains 26

The linked `.bss` delta must be exactly **+704 bytes** and the memory-manager reservation must remain unchanged. Routing, RF, retry policy, concentrator delivery-failure threshold, UART baud/flow control, network identity and NVM layout remain unchanged.

## Ranked-item disposition

| Review item | P009 disposition |
|---|---|
| S1 trustworthy acceptance/freshness | **Required and implemented:** one exact owner/start epoch, complete 16-result canary, reconnect guard, fail-fast Permit Join, correlated fresh close, exact bounded log window, partial evidence persisted before STOP. |
| S2 binary/runtime contract | **Required:** linked ELF assertions and +704 B gate; source inputs honestly labelled; generated evidence archived when emitted; artifact/source SHA binding; structured current-owner 9.1.1/EZSP19 proof. Runtime values that stock does not expose are explicitly labelled unknown/expected, not invented. |
| A1 BTT64/threshold | **BTT64 retained.** Threshold48 is not bundled. BTT>64 is rejected for P009. |
| A2 minimal XNCP identity | **Separate follow-up.** Identity-only first; no route/watchdog/reset/token/NVM/receive-all-groups behavior. Not a prerequisite for first P009 evaluation. |
| A3 counters/timing/reset semantics | **P010 diagnostic overlay implemented separately:** immediate original BUSY propagation; one queued read-only coalesced snapshot; no clear/retry/config/routing change. Not used in first P009 run. |
| B1 RX512/transport | **RX512 retained.** EUSART1/115200/no-flow preserved. No ZBT-2 baud/RTS-CTS copy. |
| B2 multicast membership | **Separate P013 experiment:** P009 stays at 26; P013 alone tests 26 -> 32 (+24 B) if later justified. |
| B3 watchdog | **Deferred isolated variant.** Requires feed/reset-cause/NVM/restart-loop proof and deliberate-hang validation off production. |
| B4 HA pacing/coalescing | **Host/HA follow-up.** Never change direct bindings; preserve order; only coalesce idempotent state assignments; no silent toggle/increment dedupe. |
| B5 reproducible build | **Required:** pinned source/builder, exact toolchain evidence, generated metadata + linked ELF evidence, twin clean P009 build, machine-readable reproducibility record and artifact hashes. |

## Explicit P009 reject guardrail

Do not add BTT254, blanket BUSY retries, larger retry queue, child-policy inflation because network size exceeds 100, copied ZBT-2 transport settings, the previously harmful concentrator delivery-failure threshold increase, unsolicited raw packet streaming, security-storage migration, manual source-route restore, receive-all-groups, private-stack high-water hooks, persistent per-event NVM counters, or watchdog enablement.

## Release completion

P009 is eligible for executor ARM only when one immutable SHA has all offline tests green; matched stock/P009 built with one pinned toolchain; exact three-delta/+704 B linked contract; complete artifact size/SHA manifest; current-owner structured stack proof; hardened acceptance semantics; reproducibility record; and all CI jobs green on that same SHA. The executor issue must then be updated to the exact SHA/run/artifact/hashes and may not substitute a moving branch.
