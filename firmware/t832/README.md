# T832-KCTRL-R0

Controlled CC2674P10/ZNP firmware candidate for `home-assistant-stack#73`.

This is **not** a generic "newer is better" firmware. It is a controlled
experiment intended to remove SMLIGHT 20260311 downstream low-level changes
while preserving the coordinator fixes and capacities required by the
production network.

## Base

- TI SimpleLink Low Power F2 SDK 8.32.00.07, exact commit pinned in `manifest.json`.
- Official TI `LP_EM_CC2674P10` ZNP project seed.
- TI-RTOS7 / TI ARM Clang 3.2.2.LTS / SysConfig 1.21.1.
- Koenkk coordinator work is used as a semantic reference only. The upstream
  patch is **not** fuzz-applied.

## Included control changes

- UART2 TX completion on `UART2_EVENT_TX_FINISHED`.
- UART ISR buffer 128.
- NVOCMP compact-failure recovery.
- Extended NV/key MT APIs needed by backup/restore.
- Large-network coordinator tables, route/source-route capacity and queues.
- 4 KiB C/ISR stack.
- Explicit non-vendor build identity.

## Deliberately excluded

- SMLIGHT 20260311 low-level UART/DMA/FIFO/task changes.
- watchdog recovery.
- diagnostic instrumentation.
- experimental fixes.
- hard-coded TX power.
- unrelated Koenkk AF/group forwarding behavior.

A successful CI build is **not** authorization to flash production hardware.
The board/CCFG/recovery/backup gates in the issue #73 plan still apply.
