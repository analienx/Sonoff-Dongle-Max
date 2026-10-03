#!/usr/bin/env python3
"""Layer T832-DIAG-R0 instrumentation on the exact T832-KCTRL-R0 source delta.

This patcher is intentionally fail-closed: every source edit is exact-match
and the control patch is applied first from its pinned manifest. No fuzzy
patching is permitted.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import shutil
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
VARIANT = "T832-DIAG-R0"


def load_control_module():
    spec = importlib.util.spec_from_file_location("t832_apply_kctrl", HERE / "apply_kctrl.py")
    if spec is None or spec.loader is None:
        raise SystemExit("cannot load apply_kctrl.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class Exact:
    def __init__(self) -> None:
        self.edits: list[dict[str, Any]] = []

    def replace(self, path: Path, old: str, new: str, label: str, count: int = 1) -> None:
        text = path.read_text(encoding="utf-8")
        actual = text.count(old)
        if actual != count:
            raise SystemExit(f"{path}: {label}: expected {count} exact match(es), found {actual}")
        path.write_text(text.replace(old, new, count), encoding="utf-8")
        self.edits.append({"label": label, "path": str(path).replace("\\", "/")})

    def append(self, path: Path, text: str, label: str) -> None:
        existing = path.read_text(encoding="utf-8")
        if text.strip() in existing:
            raise SystemExit(f"{path}: {label}: diagnostic block already present")
        path.write_text(existing.rstrip() + "\n\n" + text.rstrip() + "\n", encoding="utf-8")
        self.edits.append({"label": label, "path": str(path).replace("\\", "/")})


def include_after(ex: Exact, path: Path, marker: str, header: str, label: str) -> None:
    ex.replace(path, marker, marker + f'#include "{header}"\n', label)


def apply_diag(sdk: Path, examples: Path, control_manifest: Path) -> dict[str, Any]:
    control = load_control_module()
    control_evidence = control.apply(sdk, examples, control_manifest)
    ex = Exact()

    mt = sdk / "source/ti/zstack/mt"
    npi = sdk / "source/ti/zstack/npi"
    api = sdk / "source/ti/zstack/stack/api"
    boot = sdk / "kernel/tirtos7/packages/ti/sysbios/family/arm/cc26xx/Boot.c"

    shutil.copy2(HERE / "t832_diag.h", mt / "t832_diag.h")
    shutil.copy2(HERE / "t832_diag_impl.inc", mt / "t832_diag_impl.inc")

    # Capture reset source in the existing SYS/BIOS boot-reason path before
    # application initialization can obscure the original reset reason.
    ex.replace(
        boot,
        "uint32_t Boot_getBootReason()\n{\n    return (SysCtrlResetSourceGet());\n}\n",
        "uint32_t t832DiagResetCauseEarly;\n\n"
        "uint32_t Boot_getBootReason()\n{\n"
        "    t832DiagResetCauseEarly = SysCtrlResetSourceGet();\n"
        "    return t832DiagResetCauseEarly;\n"
        "}\n",
        "diag.boot.reset_cause",
    )

    # Compile-time diagnostic identity without changing KCTRL routing/resource semantics.
    opts = sdk / "source/ti/zstack/apps/znp/znp_cnf.opts"
    ex.replace(
        opts,
        "-DMT_APP_CNF_FUNC\n",
        "-DMT_APP_CNF_FUNC\n-DT832_DIAG_R0=1\n",
        "diag.compile_identity",
    )

    # Reserve a dedicated MT event bit for the once-per-second exporter scheduler.
    mth = mt / "mt.h"
    ex.replace(
        mth,
        "#define MT_ZNP_BASIC_RSP_EVENT          0x2000\n#endif\n",
        "#define MT_ZNP_BASIC_RSP_EVENT          0x2000\n#endif\n"
        "#define MT_DIAG_TICK_EVENT              0x4000\n",
        "diag.mt_event",
    )

    # Runtime implementation lives in the existing MT debug translation unit.
    mt_debug = mt / "mt_debug.c"
    ex.append(mt_debug, '#include "t832_diag_impl.inc"', "diag.runtime_include")

    # MT scheduler progress and periodic exporter. Telemetry scheduling is distinct
    # from real MT/Zigbee work in the emitted fields.
    mt_task = mt / "mt_task.c"
    include_after(ex, mt_task, '#include "mt.h"\n', "t832_diag.h", "diag.mt_task.include")
    ex.replace(
        mt_task,
        "  MT_TaskID = task_id;\n",
        "  MT_TaskID = task_id;\n  T832Diag_init(task_id);\n",
        "diag.mt_task.init",
    )
    ex.replace(
        mt_task,
        "  OsalPort_setEvent(task_id, MT_SECONDARY_INIT_EVENT);\n",
        "  OsalPort_setEvent(task_id, MT_SECONDARY_INIT_EVENT);\n"
        "  OsalPortTimers_startTimer(task_id, MT_DIAG_TICK_EVENT, 1000u);\n",
        "diag.mt_task.timer_start",
    )
    ex.replace(
        mt_task,
        "  mtOSALSerialData_t *pMsg;\n\n",
        "  mtOSALSerialData_t *pMsg;\n\n"
        "  T832Diag_taskScheduled(task_id, events);\n",
        "diag.mt_task.schedule",
    )
    ex.replace(
        mt_task,
        "      MT_ProcessIncomingCommand(pMsg);\n",
        "      T832Diag_taskWork(T832_DIAG_WORK_MT, SYS_EVENT_MSG);\n"
        "      MT_ProcessIncomingCommand(pMsg);\n",
        "diag.mt_task.command_work",
    )
    ex.replace(
        mt_task,
        "  if ( events & MT_SECONDARY_INIT_EVENT )\n  {\n    MT_Init();\n",
        "  if ( events & MT_SECONDARY_INIT_EVENT )\n  {\n"
        "    T832Diag_taskWork(T832_DIAG_WORK_MT, MT_SECONDARY_INIT_EVENT);\n"
        "    MT_Init();\n",
        "diag.mt_task.init_work",
    )
    ex.replace(
        mt_task,
        "  if ( events & MT_ZTOOL_SERIAL_RCV_BUFFER_FULL )\n  {\n"
        "    /* Return unproccessed events */\n",
        "  if ( events & MT_ZTOOL_SERIAL_RCV_BUFFER_FULL )\n  {\n"
        "    T832Diag_rxBufferFull();\n"
        "    /* Return unproccessed events */\n",
        "diag.mt_task.rx_full",
    )
    ex.replace(
        mt_task,
        "  /* Discard or make more handlers */\n  return 0;\n",
        "  if (events & MT_DIAG_TICK_EVENT)\n  {\n"
        "    T832Diag_exportPoll();\n"
        "    OsalPortTimers_startTimer(task_id, MT_DIAG_TICK_EVENT, 1000u);\n"
        "    return (events ^ MT_DIAG_TICK_EVENT);\n"
        "  }\n\n"
        "  /* Discard or make more handlers */\n  return 0;\n",
        "diag.mt_task.export_tick",
    )

    # Command receive / dispatch / completion are separate observations.
    mtc = mt / "mt.c"
    include_after(ex, mtc, '#include "mt.h"\n', "t832_diag.h", "diag.mt.include")
    ex.replace(
        mtc,
        "  mtProcessMsg_t func;\n  uint8_t rsp[MT_RPC_FRAME_HDR_SZ];\n\n",
        "  mtProcessMsg_t func;\n  uint8_t rsp[MT_RPC_FRAME_HDR_SZ];\n\n"
        "  T832Diag_commandRx(pBuf[MT_RPC_POS_CMD0], pBuf[MT_RPC_POS_CMD1]);\n",
        "diag.command.rx",
    )
    ex.replace(
        mtc,
        "      /* execute processing function */\n      rsp[0] = (*func)(pBuf);\n",
        "      /* execute processing function */\n"
        "      T832Diag_commandDispatch(pBuf[MT_RPC_POS_CMD0], pBuf[MT_RPC_POS_CMD1]);\n"
        "      rsp[0] = (*func)(pBuf);\n"
        "      T832Diag_commandComplete(pBuf[MT_RPC_POS_CMD0], pBuf[MT_RPC_POS_CMD1], rsp[0]);\n",
        "diag.command.dispatch_complete",
    )

    # startupFromApp stages bracket the exact BDB call and SRSP queue attempt.
    zdo = mt / "mt_zdo.c"
    include_after(ex, zdo, '#include "mt_zdo.h"\n', "t832_diag.h", "diag.zdo.include")
    include_after(ex, zdo, '#include "bdb_interface.h"\n', "bdb.h", "diag.zdo.bdb_include")
    include_after(ex, zdo, '#include "bdb.h"\n', "nwk.h", "diag.zdo.nwk_include")
    ex.replace(
        zdo,
        "  pBuf += MT_RPC_FRAME_HDR_SZ;\n\n  if(ZG_BUILD_COORDINATOR_TYPE && ZG_DEVICE_COORDINATOR_TYPE)\n",
        "  pBuf += MT_RPC_FRAME_HDR_SZ;\n"
        "  T832Diag_startup(1u, cmd0, cmd1);\n"
        "  T832Diag_networkState(bdbAttributes.bdbNodeIsOnANetwork, _NIB.nwkState);\n\n"
        "  if(ZG_BUILD_COORDINATOR_TYPE && ZG_DEVICE_COORDINATOR_TYPE)\n",
        "diag.startup.entry",
    )
    ex.replace(
        zdo,
        "  {\n    bdb_StartCommissioning(BDB_COMMISSIONING_MODE_NWK_FORMATION);\n  }\n",
        "  {\n"
        "    T832Diag_startup(2u, cmd0, cmd1);\n"
        "    bdb_StartCommissioning(BDB_COMMISSIONING_MODE_NWK_FORMATION);\n"
        "    T832Diag_startup(3u, cmd0, cmd1);\n"
        "  }\n",
        "diag.startup.bdb_call",
        count=1,
    )
    ex.replace(
        zdo,
        "  else\n  {\n     retValue = ZFailure;\n  }\n\n"
        "  if (MT_RPC_CMD_SREQ == (cmd0 & MT_RPC_CMD_TYPE_MASK))\n  {\n"
        "    MT_BuildAndSendZToolResponse",
        "  else\n  {\n     retValue = ZFailure;\n  }\n\n"
        "  if (MT_RPC_CMD_SREQ == (cmd0 & MT_RPC_CMD_TYPE_MASK))\n  {\n"
        "    T832Diag_startup(4u, cmd0, cmd1);\n"
        "    MT_BuildAndSendZToolResponse",
        "diag.startup.srsp_queue",
        count=1,
    )

    # Observe BDB message dispatch/return in the Zigbee stack task.
    ztask = api / "zstacktask.c"
    include_after(ex, ztask, '#include "zstacktask.h"\n', "t832_diag.h", "diag.zstack.include")
    ex.replace(
        ztask,
        "    case zstackmsg_CmdIDs_BDB_START_COMMISSIONING_REQ:\n"
        "      resend = processBdbStartCommissioningReq( srcServiceTaskId, pMsg );\n"
        "      break;\n",
        "    case zstackmsg_CmdIDs_BDB_START_COMMISSIONING_REQ:\n"
        "      T832Diag_bdb(1u, srcServiceTaskId);\n"
        "      resend = processBdbStartCommissioningReq( srcServiceTaskId, pMsg );\n"
        "      T832Diag_bdb(2u, resend ? 1u : 0u);\n"
        "      break;\n",
        "diag.bdb.dispatch_return",
    )

    # Observe queueing/allocation independently from physical UART completion.
    client = npi / "npi_client_mt.c"
    include_after(ex, client, '#include "mt_rpc.h"\n', "t832_diag.h", "diag.npi_client.include")
    ex.replace(
        client,
        "    if(pRspMsg != NULL)\n    {\n",
        "    if(pRspMsg != NULL)\n    {\n"
        "        T832Diag_responseQueued(cmdType, cmdId, dataLen);\n",
        "diag.response.queue",
    )
    ex.replace(
        client,
        "        OsalPort_msgSend(npiTaskID, pRspMsg);\n    }\n\n    return;\n",
        "        OsalPort_msgSend(npiTaskID, pRspMsg);\n"
        "    }\n"
        "    else\n"
        "    {\n"
        "        T832Diag_responseAllocFailed(cmdType, cmdId, (uint16_t)(dataLen + MTRPC_FRAME_HDR_SZ));\n"
        "    }\n\n"
        "    return;\n",
        "diag.response.alloc_fail",
    )

    # UART: effective config, RX progress/overflow, write start/rejection and
    # true end-of-wire completion. KCTRL's TX_FINISHED behavior is preserved.
    uart = npi / "npi_tl_uart.c"
    include_after(ex, uart, '#include "npi_tl_uart.h"\n', "t832_diag.h", "diag.uart.include")
    ex.replace(
        uart,
        "    uartHandle = UART2_open(CONFIG_DISPLAY_UART, &params);\n",
        "    uartHandle = UART2_open(CONFIG_DISPLAY_UART, &params);\n"
        "    T832Diag_uartConfigured(params.baudRate, NPI_FLOW_CTRL);\n",
        "diag.uart.config",
    )
    ex.replace(
        uart,
        "    TransportTxLen = len;\n\n#if (NPI_FLOW_CTRL == 1)\n",
        "    TransportTxLen = len;\n"
        "    T832Diag_uartTxStart(len);\n\n"
        "#if (NPI_FLOW_CTRL == 1)\n",
        "diag.uart.tx_start",
    )
    ex.replace(
        uart,
        "    if(UART2_write(uartHandle, TransportTxBuf, TransportTxLen, NULL) != UART2_STATUS_SUCCESS )\n"
        "    {\n"
        "      TransportTxLen = 0;\n"
        "    }\n",
        "    {\n"
        "      int_fast16_t writeStatus = UART2_write(uartHandle, TransportTxBuf, TransportTxLen, NULL);\n"
        "      if(writeStatus != UART2_STATUS_SUCCESS)\n"
        "      {\n"
        "        T832Diag_uartWriteRejected(TransportTxLen, (int16_t)writeStatus);\n"
        "        TransportTxLen = 0;\n"
        "      }\n"
        "    }\n",
        "diag.uart.write_reject",
    )
    ex.replace(
        uart,
        "    if (size)\n    {\n",
        "    if (size)\n    {\n"
        "        T832Diag_uartRx((uint16_t)size, TransportRxLen);\n",
        "diag.uart.rx_progress",
    )
    ex.replace(
        uart,
        "        if (size != NPITLUART_readIsrBuf(size))\n        {\n",
        "        if (size != NPITLUART_readIsrBuf(size))\n        {\n"
        "            T832Diag_uartRxOverflow((uint16_t)size, TransportRxLen);\n",
        "diag.uart.rx_overflow",
    )
    ex.replace(
        uart,
        "    if (event == UART2_EVENT_TX_FINISHED)\n    {\n"
        "        uint32_t key = OsalPort_enterCS();\n",
        "    if (event == UART2_EVENT_TX_FINISHED)\n    {\n"
        "        T832Diag_uartTxFinished(TransportTxLen);\n"
        "        uint32_t key = OsalPort_enterCS();\n",
        "diag.uart.tx_finished",
    )

    # NV compaction begin/end/failure/duration, recovery reformat entry, and
    # init/recovery action breadcrumbs. Hooks only record; erase/reformat
    # policy (NVOCMP_RECOVER_FROM_COMPACT_FAILURE) is unchanged.
    nv = sdk / "source/ti/common/nv/nvocmp.c"
    ex.replace(
        nv,
        '#include "nvocmp.h"\n',
        '#include "nvocmp.h"\n'
        "\n"
        "extern void T832Diag_nvEvent(uint8_t stage, uint16_t b, uint16_t c);\n"
        "extern void T832Diag_nvInit(uint8_t action);\n",
        "diag.nv.decls",
    )
    ex.replace(
        nv,
        "    pNvHandle->compactInfo.xSrcEOffset = 0;\n"
        "    status = NVOCMP_compact(pNvHandle);\n",
        "    pNvHandle->compactInfo.xSrcEOffset = 0;\n"
        "    T832Diag_nvEvent(1u, nBytes, 0u);\n"
        "    status = NVOCMP_compact(pNvHandle);\n"
        "    T832Diag_nvEvent(status == NVOCMP_COMPACT_FAILURE ? 3u : 2u,"
        " (uint16_t)status, 0u);\n",
        "diag.nv.compact_site_4sp",
    )
    ex.replace(
        nv,
        "  pNvHandle->compactInfo.xSrcSOffset = pNvHandle->pageInfo[srcPg].offset;\n"
        "  status = NVOCMP_compact(pNvHandle);\n",
        "  pNvHandle->compactInfo.xSrcSOffset = pNvHandle->pageInfo[srcPg].offset;\n"
        "  T832Diag_nvEvent(1u, nBytes, 0u);\n"
        "  status = NVOCMP_compact(pNvHandle);\n"
        "  T832Diag_nvEvent(status == NVOCMP_COMPACT_FAILURE ? 3u : 2u,"
        " (uint16_t)status, 0u);\n",
        "diag.nv.compact_site_2sp",
    )
    ex.replace(
        nv,
        "#ifdef NVOCMP_RECOVER_FROM_COMPACT_FAILURE",
        "#ifdef NVOCMP_RECOVER_FROM_COMPACT_FAILURE\n"
        "        T832Diag_nvEvent(4u, NVOCMP_NVSIZE, 0u);",
        "diag.nv.reformat_entry",
        count=2,
    )
    ex.replace(
        nv,
        "  gAction = action;\n",
        "  gAction = action;\n  T832Diag_nvInit((uint8_t)action);\n",
        "diag.nv.init_action",
        count=3,
    )

    return {
        "variant": VARIANT,
        "control": control_evidence,
        "diagnostic_edits": ex.edits,
        "copied_runtime": [
            "source/ti/zstack/mt/t832_diag.h",
            "source/ti/zstack/mt/t832_diag_impl.inc",
        ],
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sdk", type=Path, required=True)
    ap.add_argument("--examples", type=Path, required=True)
    ap.add_argument("--control-manifest", type=Path, default=HERE / "manifest.json")
    ap.add_argument("--evidence", type=Path)
    args = ap.parse_args()
    evidence = apply_diag(
        args.sdk.resolve(), args.examples.resolve(), args.control_manifest.resolve()
    )
    if args.evidence:
        args.evidence.parent.mkdir(parents=True, exist_ok=True)
        args.evidence.write_text(json.dumps(evidence, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(evidence, indent=2))


if __name__ == "__main__":
    main()
