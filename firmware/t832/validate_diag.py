#!/usr/bin/env python3
"""Fail-closed policy validation for T832-DIAG-R0."""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", type=Path, default=Path(__file__).resolve().parent)
    args = ap.parse_args()
    root = args.root.resolve()

    manifest = json.loads((root / "diag_manifest.json").read_text(encoding="utf-8"))
    require(manifest["variant"] == "T832-DIAG-R0", "wrong diagnostic variant")
    require(manifest["base_variant"] == "T832-KCTRL-R0", "wrong control base")
    ram = manifest["static_ram"]
    require(ram["maximum_diagnostic_bytes"] == 4096, "diagnostic RAM cap must be 4 KiB")
    require(ram["minimum_linker_free_sram_bytes"] == 8192, "free SRAM gate must remain 8 KiB")
    require(ram["critical_records"] == 64, "critical recorder must be 64 records")
    require(ram["routine_records"] == 64, "routine recorder must be 64 records")

    transport = manifest["transport"]
    require(transport["envelope"] == "AREQ DEBUG.msg", "transport must remain DEBUG.msg AREQ")
    require(transport["maximum_payload_bytes"] <= 240, "diagnostic payload exceeds 240 bytes")
    require(transport["minimum_export_interval_ms"] >= 5000, "telemetry faster than one frame/5 s")
    require(transport["health_snapshot_interval_ms"] == 10000, "health snapshot must be 10 s")
    require(transport["resource_snapshot_interval_ms"] == 60000, "resource snapshot must be 60 s")
    require(transport["maximum_pending_diagnostic_messages"] == 1, "more than one diagnostic message pending")
    require(transport["normal_znp_has_priority"] is True, "normal ZNP must have priority")
    require(transport["bypass_sync_suppression"] is False, "must not bypass SREQ/SRSP suppression")

    capabilities = manifest["capabilities"]
    for name in manifest["release_gate_required_capabilities"]:
        require(capabilities.get(name) is True, f"required capability unavailable: {name}")

    runtime = (root / "t832_diag_impl.inc").read_text(encoding="utf-8")
    header = (root / "t832_diag.h").read_text(encoding="utf-8")
    patcher = (root / "apply_diag.py").read_text(encoding="utf-8")
    host = (root / "t832_incident.py").read_text(encoding="utf-8")

    require("T832_DIAG_CRITICAL_RECORDS 64u" in runtime, "critical ring source drift")
    require("T832_DIAG_ROUTINE_RECORDS 64u" in runtime, "routine ring source drift")
    require("sizeof(T832DiagState) <= 4096u" in runtime, "static RAM assertion missing")
    require("T832_DIAG_EXPORT_MIN_MS 5000u" in runtime, "export limiter missing")
    require("T832_DIAG_HEALTH_MS 10000u" in runtime, "health interval drift")
    require("T832_DIAG_RESOURCE_MS 60000u" in runtime, "resource interval drift")
    require("t832Diag.sync_outstanding || t832Diag.transport_active" in runtime, "backpressure/sync gate missing")
    require("t832Diag.diag_pending || t832Diag.normal_pending" in runtime, "pending-message gate missing")
    require("T832_DIAG_EV_NPI_RX_OVERFLOW" in runtime, "RX overflow instrumentation missing")
    require("T832_DIAG_EV_NPI_WRITE_REJECT" in runtime, "write rejection instrumentation missing")
    require("T832_DIAG_EV_NPI_TX_FINISHED" in runtime, "physical TX-completion instrumentation missing")
    require("T832_DIAG_EV_STARTUP_BDB_REQUEST" in runtime, "startup BDB request instrumentation missing")
    require("T832_DIAG_CAP_RESET_CAUSE" in header, "early reset-cause capability missing")
    require("t832DiagResetCauseEarly" in patcher and "Boot_getBootReason" in patcher, "early reset-cause patch missing")
    require("T832Diag_networkState" in patcher, "existing-network resume-state hook missing")
    require("T832Diag_uartRxOverflow" in patcher, "UART overflow hook missing")
    require("T832Diag_uartTxFinished" in patcher, "UART completion hook missing")

    # Hot hook bodies must remain observational only. Export is intentionally excluded.
    hook_names = [
        "T832Diag_taskScheduled", "T832Diag_taskWork", "T832Diag_commandRx",
        "T832Diag_commandDispatch", "T832Diag_commandComplete",
        "T832Diag_responseQueued", "T832Diag_responseAllocFailed",
        "T832Diag_uartConfigured", "T832Diag_uartRx", "T832Diag_uartRxOverflow",
        "T832Diag_uartTxStart", "T832Diag_uartWriteRejected",
        "T832Diag_uartTxFinished", "T832Diag_startup",
        "T832Diag_networkState", "T832Diag_bdb", "T832Diag_rxBufferFull",
    ]
    banned = re.compile(r"\b(malloc|calloc|realloc|free|printf|fprintf|UART2_write|flash|sleep|Task_sleep)\b")
    for name in hook_names:
        match = re.search(rf"void\s+{name}\([^)]*\)\s*\{{(?P<body>.*?)\n\}}", runtime, re.S)
        require(match is not None, f"hook missing: {name}")
        require(banned.search(match.group("body")) is None, f"hot hook has forbidden operation: {name}")

    require("import serial" not in host and "from serial" not in host, "host collector must not use pyserial")
    require("/dev/serial" not in host, "host collector must not open coordinator serial path")
    require("default=7" in host, "seven-day retention default missing")
    require("default=1 << 30" in host, "1 GiB recording cap default missing")
    require("default=15 * 60" in host, "15-minute incident window missing")
    require("default=30" in host, "30-second capture deadline missing")
    require("automatic-reset-already-consumed" in host, "one-reset latch guard missing")
    require("stability-window-not-complete" in host, "10-minute stability close guard missing")

    print("T832-DIAG-R0 policy contract: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
