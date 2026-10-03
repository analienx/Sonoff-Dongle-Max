# T832-DIAG-R0 observer cost (estimate, not a hardware measurement)

RAM (proven): `T832DiagState <= 4096` bytes by `_Static_assert`; linked map must still show `>= 8192` bytes unallocated SRAM via the compiled contract gate. Rings are 64 critical + 64 routine 20-byte records (2560 bytes); remainder is counters, timestamps, watermarks-maxima, first-fault slot, and gate flags.

UART volume (bounded): at most one diagnostic AREQ per 5000 ms; each frame is `T832D1:` + 104 hex chars (52-byte packet) = 111 bytes of DEBUG.msg text plus ZNP framing. Health preparation every 10 s and resource preparation every 60 s only enqueue records; export still obeys the 5 s / 1-pending / normal-traffic-wins gates with skip accounting and no backlog replay. Worst case is 12 frames/minute (~1332 text bytes/minute) and typical is far less under backpressure.

CPU/hook cost (estimate): hot hooks are fixed word writes plus one 64-bit tick read; record path adds one critical-section pair and one 20-byte copy; coalesce check touches only the last ring slot. Export poll runs on the 1 s MT tick and early-outs on the 5 s gate. No allocation, formatting, UART, flash, or waits in hooks or fault paths. Host-measured Python timings must not be presented as target CPU claims. Hardware cycle/hook timing remains unvalidated until bench measurement on the pinned toolchain and board.
