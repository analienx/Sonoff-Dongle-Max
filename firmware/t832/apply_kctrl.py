#!/usr/bin/env python3
"""Apply the T832-KCTRL-R0 control delta to exact pinned TI sources.

Fail-closed by design: every replacement requires the exact expected upstream
text and exactly one occurrence. This is intentionally not a fuzzy patcher.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path


VARIANT = "T832-KCTRL-R0"
SDK_COMMIT = "6499c3f53fc5fb5806213be695450a7b43fbaf3d"
EXAMPLES_COMMIT = "87ff5b638b632050228a7504f35cf3b95581c278"


def replace_exact(path: Path, old: str, new: str, *, count: int = 1) -> None:
    text = path.read_text(encoding="utf-8")
    actual = text.count(old)
    if actual != count:
        raise SystemExit(
            f"{path}: expected {count} occurrence(s) of upstream block, found {actual}"
        )
    path.write_text(text.replace(old, new, count), encoding="utf-8")


def append_opts(path: Path) -> None:
    marker = "-DMT_APP_CNF_FUNC\n"
    block = """-DMT_APP_CNF_FUNC

# T832-KCTRL-R0 — classified control delta
# BUILD_ID
-DIS_COORDINATOR
-DCODE_REVISION_NUMBER=8320001

# REQUIRED_CORRECTNESS
-DNVOCMP_RECOVER_FROM_COMPACT_FAILURE

# RESTORE_COMPAT
-DFEATURE_NVEXID=1
-DMT_SYS_KEY_MANAGEMENT=1

# CAPACITY
-DZDSECMGR_TC_DEVICE_MAX=400
-DMAX_BCAST=30
-DMAX_NEIGHBOR_ENTRIES=50
-DMAX_RTG_ENTRIES=150
-DMAX_RTG_SRC_ENTRIES=250
-DMAX_RREQ_ENTRIES=40
-DNWK_MAX_DEVICE_LIST=75

# LARGE_NETWORK_BASELINE
-DLINK_DOWN_TRIGGER=12
-DNWK_ROUTE_AGE_LIMIT=5
-DDEF_NWK_RADIUS=15
-DDEFAULT_ROUTE_REQUEST_RADIUS=8
-DZDNWKMGR_MIN_TRANSMISSIONS=0
-DROUTE_DISCOVERY_TIME=13
-DMTO_RREQ_LIMIT_TIME=5000
-DROUTE_EXPIRY_TIME=2
-DNWK_INDIRECT_MSG_TIMEOUT=8
-DZMAC_MAX_FRAME_RETRIES=7
-DNWK_MAX_DATA_RETRIES=4
-DMULTICAST_ENABLED=FALSE
-DAPSC_ACK_WAIT_DURATION_POLLED=500
-DCONCENTRATOR_ENABLE=TRUE
-DCONCENTRATOR_ROUTE_CACHE=TRUE
-DCONCENTRATOR_DISCOVERY_TIME=60
-DSRC_RTG_EXPIRY_TIME=10
-DCONFLICTED_ADDR_TABLE_SIZE=15
"""
    replace_exact(path, marker, block)


def apply(sdk: Path, examples: Path) -> dict[str, object]:
    # Keep these assertions close to the edit logic: wrong trees must stop.
    sdk_git = sdk / ".git"
    examples_git = examples / ".git"
    if not sdk_git.exists() or not examples_git.exists():
        raise SystemExit("SDK and examples inputs must be Git checkouts")

    # LARGE_NETWORK_BASELINE — MAC queue headroom.
    opts = sdk / "source/ti/zstack/apps/znp/znp_cnf.opts"
    replace_exact(opts, "-DMAC_CFG_TX_DATA_MAX=5\n-DMAC_CFG_TX_MAX=8\n-DMAC_CFG_RX_MAX=5",
                  "-DMAC_CFG_TX_DATA_MAX=50\n-DMAC_CFG_TX_MAX=80\n-DMAC_CFG_RX_MAX=50")
    append_opts(opts)

    # REQUIRED_CORRECTNESS — UART ISR headroom.
    uart_h = sdk / "source/ti/zstack/npi/npi_tl_uart.h"
    replace_exact(uart_h, "#define UART_ISR_BUF_SIZE 32", "#define UART_ISR_BUF_SIZE 128")

    # REQUIRED_CORRECTNESS — do not signal NPI completion until the UART has
    # physically emitted the final byte.
    uart_c = sdk / "source/ti/zstack/npi/npi_tl_uart.c"
    replace_exact(
        uart_c,
        "static void NPITLUART_writeCallBack(UART2_Handle handle, void *ptr, size_t size, void *userArg, int_fast16_t status);\n",
        "static void NPITLUART_writeCallBack(UART2_Handle handle, void *ptr, size_t size, void *userArg, int_fast16_t status);\n"
        "static void NPITLUART_eventCallBack(UART2_Handle handle, uint32_t event, uint32_t data, void *userArg);\n",
    )
    replace_exact(
        uart_c,
        "    params.readCallback = NPITLUART_readCallBack;\n"
        "    params.writeCallback = NPITLUART_writeCallBack;\n",
        "    params.readCallback = NPITLUART_readCallBack;\n"
        "    params.writeCallback = NPITLUART_writeCallBack;\n"
        "    params.eventCallback = NPITLUART_eventCallBack;\n"
        "    params.eventMask |= UART2_EVENT_TX_FINISHED;\n",
    )
    old_cb = """static void NPITLUART_writeCallBack(UART2_Handle handle, void *ptr, size_t size, void *userArg, int_fast16_t status)
{
    uint32_t key;
    key = OsalPort_enterCS();

#if (NPI_FLOW_CTRL == 1)
    if ( !RxActive )
    {
        UART2_readCancel(uartHandle);
        if ( npiTransmitCB )
        {
            npiTransmitCB(TransportRxLen,TransportTxLen);
        }
    }

    TxActive = FALSE;
#else
    if ( npiTransmitCB )
    {
        npiTransmitCB(0,TransportTxLen);
    }
#endif // NPI_FLOW_CTRL = 1

    OsalPort_leaveCS(key);
}
"""
    new_cb = """static void NPITLUART_writeCallBack(UART2_Handle handle, void *ptr, size_t size, void *userArg, int_fast16_t status)
{
    /* T832-KCTRL: UART2 write callback means queued-to-driver, not wire-idle. */
}

static void NPITLUART_eventCallBack(UART2_Handle handle, uint32_t event, uint32_t data, void *userArg)
{
    if (event == UART2_EVENT_TX_FINISHED)
    {
        uint32_t key = OsalPort_enterCS();

#if (NPI_FLOW_CTRL == 1)
        if ( !RxActive )
        {
            UART2_readCancel(uartHandle);
            if ( npiTransmitCB )
            {
                npiTransmitCB(TransportRxLen, TransportTxLen);
            }
        }
        TxActive = FALSE;
#else
        if ( npiTransmitCB )
        {
            npiTransmitCB(0, TransportTxLen);
        }
#endif
        OsalPort_leaveCS(key);
    }
}
"""
    replace_exact(uart_c, old_cb, new_cb)

    # LARGE_NETWORK_BASELINE — NWK internal queue headroom.
    nwk = sdk / "source/ti/zstack/stack/nwk/nwk_globals.c"
    replace_exact(
        nwk,
        "#define NWK_MAX_DATABUFS_WAITING    8     // Waiting to be sent to MAC\n"
        "#define NWK_MAX_DATABUFS_SCHEDULED  5     // Timed messages to be sent\n"
        "#define NWK_MAX_DATABUFS_CONFIRMED  5     // Held after MAC confirms\n"
        "#define NWK_MAX_DATABUFS_TOTAL      12    // Total number of buffers",
        "#define NWK_MAX_DATABUFS_WAITING    48    // Waiting to be sent to MAC\n"
        "#define NWK_MAX_DATABUFS_SCHEDULED  30    // Timed messages to be sent\n"
        "#define NWK_MAX_DATABUFS_CONFIRMED  30    // Held after MAC confirms\n"
        "#define NWK_MAX_DATABUFS_TOTAL      72    // Total number of buffers",
    )

    # REQUIRED_CORRECTNESS — larger C/ISR stack, preserving P10 flash/NVS map.
    linker = sdk / "source/ti/zstack/boards/cc13x4_cc26x4/cc13x4_cc26x4_tirtos7_ticlang.cmd"
    replace_exact(linker, "--stack_size=0x600   /* C stack is also used for ISR stack */",
                  "--stack_size=4096    /* T832-KCTRL C/ISR stack */")
    replace_exact(linker, "--stack_size=1024", "--stack_size=4096")

    # BUILD_ID — distinguish this image from vendor builds.
    version = sdk / "source/ti/zstack/mt/mt_version.c"
    replace_exact(
        version,
        """const uint8_t MTVersionString[] = {
                                   2,  /* Transport protocol revision */
                                   0,  /* Product ID */
                                   2,  /* Software major release number */
                                   7,  /* Software minor release number */
                                   1,  /* Software maintenance release number */
                                 };""",
        """const uint8_t MTVersionString[] = {
                                   2,  /* Transport protocol revision */
                                   1,  /* Product ID: custom coordinator */
                                   2,  /* Software major release number */
                                   7,  /* Software minor release number */
                                   1,  /* Software maintenance release number */
                                   ((CODE_REVISION_NUMBER >> 0)  & 0xFF),
                                   ((CODE_REVISION_NUMBER >> 8)  & 0xFF),
                                   ((CODE_REVISION_NUMBER >> 16) & 0xFF),
                                   ((CODE_REVISION_NUMBER >> 24) & 0xFF),
                                 };""",
    )

    project = examples / "examples/rtos/LP_EM_CC2674P10/zstack/znp/tirtos7/ticlang/znp_LP_EM_CC2674P10_tirtos7_ticlang.projectspec"
    syscfg = examples / "examples/rtos/LP_EM_CC2674P10/zstack/znp/tirtos7/znp.syscfg"
    if not project.exists() or not syscfg.exists():
        raise SystemExit("Pinned examples tree does not contain the official LP_EM_CC2674P10 ZNP project")

    return {
        "variant": VARIANT,
        "sdk_commit": SDK_COMMIT,
        "examples_commit": EXAMPLES_COMMIT,
        "projectspec": str(project.relative_to(examples)).replace("\\", "/"),
        "syscfg": str(syscfg.relative_to(examples)).replace("\\", "/"),
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sdk", type=Path, required=True)
    ap.add_argument("--examples", type=Path, required=True)
    ap.add_argument("--evidence", type=Path)
    args = ap.parse_args()

    evidence = apply(args.sdk.resolve(), args.examples.resolve())
    if args.evidence:
        args.evidence.parent.mkdir(parents=True, exist_ok=True)
        args.evidence.write_text(json.dumps(evidence, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(evidence, indent=2))


if __name__ == "__main__":
    main()
