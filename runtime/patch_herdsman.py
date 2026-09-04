#!/usr/bin/env python3
"""Apply the P009 fail-loud EZSP runtime policy to zigbee-herdsman 10.9.1.

The patch is intentionally pinned and narrow. It changes no send/retry/routing logic.
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

PIN = "0968f979d558874b17396c96b66382d4236bbdcd"
TARGET = Path("src/adapter/ember/adapter/emberAdapter.ts")
HELPER_ANCHOR = "    private async emberSetEzspConfigValue(configId: EzspConfigId, value: number): Promise<SLStatus> {"
P009_HELPER = '    /**\n     * P009: set a mutable EZSP resource/admission value and immediately read it back.\n     * Unlike ordinary tuning, a mismatch here defeats the firmware/resource contract,\n     * so startup must fail loudly instead of silently running with partial policy.\n     */\n    private async p009SetAndVerifyEzspConfigValue(configId: EzspConfigId, value: number): Promise<void> {\n        const setStatus = await this.emberSetEzspConfigValue(configId, value);\n\n        if (setStatus !== SLStatus.OK) {\n            throw new Error(`[P009 EZSP] failed to set ${EzspConfigId[configId]}=${value}: ${SLStatus[setStatus]}`);\n        }\n\n        const [getStatus, actual] = await this.ezsp.ezspGetConfigurationValue(configId);\n        logger.info(\n            `[P009 EZSP] ${EzspConfigId[configId]} expected=${value} actual=${actual} readStatus=${SLStatus[getStatus]}`,\n            NS,\n        );\n\n        if (getStatus !== SLStatus.OK || actual !== value) {\n            throw new Error(\n                `[P009 EZSP] readback mismatch for ${EzspConfigId[configId]}: expected=${value} actual=${actual} status=${SLStatus[getStatus]}`,\n            );\n        }\n    }\n\n'
INIT_OLD = '        await this.emberSetEzspConfigValue(EzspConfigId.SUPPORTED_NETWORKS, 1);\n        // allow other devices to modify the binding table\n'
INIT_NEW = '        // P009 resource/admission contract paired with the tuned MG24 NCP.\n        // 64 BTT entries with threshold 48 reserve 16 entries for relaying broadcasts\n        // originated elsewhere in the mesh. Do not increase RETRY_QUEUE_SIZE.\n        await this.p009SetAndVerifyEzspConfigValue(EzspConfigId.BROADCAST_TABLE_SIZE, 64);\n        await this.p009SetAndVerifyEzspConfigValue(EzspConfigId.NEW_BROADCAST_ENTRY_THRESHOLD, 48);\n        await this.p009SetAndVerifyEzspConfigValue(EzspConfigId.RETRY_QUEUE_SIZE, 16);\n        await this.p009SetAndVerifyEzspConfigValue(EzspConfigId.MTORR_FLOW_CONTROL, 1);\n        await this.p009SetAndVerifyEzspConfigValue(EzspConfigId.SUPPORTED_NETWORKS, 1);\n        await this.p009SetAndVerifyEzspConfigValue(EzspConfigId.SEND_MULTICASTS_TO_SLEEPY_ADDRESS, 0);\n        // allow other devices to modify the binding table\n'


def die(message: str) -> None:
    raise SystemExit(f"P009 herdsman patch: {message}")


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        die(f"{label}: expected exactly one anchor, got {count}")
    return text.replace(old, new, 1)


def git_head(root: Path) -> str:
    try:
        return subprocess.check_output(["git", "-C", str(root), "rev-parse", "HEAD"], text=True).strip()
    except Exception as exc:
        die(f"cannot read git HEAD: {exc}")


def main() -> None:
    if len(sys.argv) != 2:
        die("usage: patch_herdsman.py <zigbee-herdsman checkout>")
    root = Path(sys.argv[1]).resolve()
    if git_head(root) != PIN:
        die(f"checkout must be exact zigbee-herdsman 10.9.1 commit {PIN}")
    path = root / TARGET
    if not path.is_file():
        die(f"missing {TARGET}")

    original = path.read_text(encoding="utf-8")
    if "[P009 EZSP]" in original:
        die("target already appears patched")

    # The exact source commit is pinned above. P009 performs exactly two textual
    # operations: inserts one helper immediately before the existing config setter,
    # and replaces the one SUPPORTED_NETWORKS initialization anchor with the six
    # set+readback calls. Existing stock queue/BUSY handling is deliberately retained.
    text = replace_once(original, HELPER_ANCHOR, P009_HELPER + HELPER_ANCHOR, "helper insertion")
    text = replace_once(text, INIT_OLD, INIT_NEW, "initEzsp policy")

    expected = original.replace(HELPER_ANCHOR, P009_HELPER + HELPER_ANCHOR, 1).replace(INIT_OLD, INIT_NEW, 1)
    if text != expected:
        die("patch changed content outside the two approved anchors")

    expected_calls = {
        "BROADCAST_TABLE_SIZE": 64,
        "NEW_BROADCAST_ENTRY_THRESHOLD": 48,
        "RETRY_QUEUE_SIZE": 16,
        "MTORR_FLOW_CONTROL": 1,
        "SUPPORTED_NETWORKS": 1,
        "SEND_MULTICASTS_TO_SLEEPY_ADDRESS": 0,
    }
    for name, value in expected_calls.items():
        pat = rf"p009SetAndVerifyEzspConfigValue\(EzspConfigId\.{name}, {value}\)"
        if len(re.findall(pat, text)) != 1:
            die(f"runtime invariant missing/duplicated: {name}={value}")

    # Do not reject stock 10.9.1's own QUEUE_BUSY_DEFER_MSEC behavior. The pinned
    # source already contains it; the exact-anchor equality above proves P009 does
    # not alter that send/retry logic.
    path.write_text(text, encoding="utf-8")
    print("P009 zigbee-herdsman runtime policy applied")
    print("  broadcast table readback:          64")
    print("  new broadcast entry threshold:     48")
    print("  retry queue:                       16")
    print("  MTORR flow control:                 1")
    print("  supported networks:                 1")
    print("  multicast-to-sleepy-address:        0")
    print("  existing stock send/retry logic:    UNCHANGED")


if __name__ == "__main__":
    main()
