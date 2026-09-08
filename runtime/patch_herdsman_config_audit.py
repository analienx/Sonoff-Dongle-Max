#!/usr/bin/env python3
"""Add read-only effective EZSP configuration audit to herdsman 10.9.1.

Separate diagnostic artifact. It performs no configuration writes beyond stock
herdsman behavior and must not be bundled with the P009 policy overlay.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

PIN = "0968f979d558874b17396c96b66382d4236bbdcd"
TARGET = Path("src/adapter/ember/adapter/emberAdapter.ts")
HELPER_ANCHOR = "    private async emberSetEzspConfigValue(configId: EzspConfigId, value: number): Promise<SLStatus> {"
CALL_ANCHOR = "        // WARNING: From here on EZSP commands that affect memory allocation on the NCP should no longer be called (like resizing tables)\n"

HELPER = '''    /** P009 diagnostic-only: read effective resource values after stock init. */
    private async p009AuditEzspConfiguration(): Promise<void> {
        const ids = [
            EzspConfigId.BROADCAST_TABLE_SIZE,
            EzspConfigId.NEW_BROADCAST_ENTRY_THRESHOLD,
            EzspConfigId.KEY_TABLE_SIZE,
            EzspConfigId.MAX_END_DEVICE_CHILDREN,
            EzspConfigId.RETRY_QUEUE_SIZE,
            EzspConfigId.SUPPORTED_NETWORKS,
            EzspConfigId.MTORR_FLOW_CONTROL,
            EzspConfigId.SEND_MULTICASTS_TO_SLEEPY_ADDRESS,
        ];
        for (const id of ids) {
            const [status, actual] = await this.ezsp.ezspGetConfigurationValue(id);
            logger.info(`[P009 CONFIG] ${EzspConfigId[id]} actual=${actual} readStatus=${SLStatus[status]}`, NS);
        }
    }

'''
CALL = "        await this.p009AuditEzspConfiguration();\n\n" + CALL_ANCHOR


def die(message: str) -> None:
    raise SystemExit(f"P009 config-audit patch: {message}")


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        die(f"{label}: expected exactly one anchor, got {count}")
    return text.replace(old, new, 1)


def main() -> None:
    if len(sys.argv) != 2:
        die("usage: patch_herdsman_config_audit.py <zigbee-herdsman checkout>")
    root = Path(sys.argv[1]).resolve()
    head = subprocess.check_output(["git", "-C", str(root), "rev-parse", "HEAD"], text=True).strip()
    if head != PIN:
        die(f"checkout must be exact zigbee-herdsman commit {PIN}")
    path = root / TARGET
    original = path.read_text(encoding="utf-8")
    if "[P009 CONFIG]" in original:
        die("target already appears patched")
    text = replace_once(original, HELPER_ANCHOR, HELPER + HELPER_ANCHOR, "helper")
    text = replace_once(text, CALL_ANCHOR, CALL, "post-stock-init audit call")
    expected = original.replace(HELPER_ANCHOR, HELPER + HELPER_ANCHOR, 1).replace(CALL_ANCHOR, CALL, 1)
    if text != expected:
        die("patch changed content outside the two approved anchors")
    if text.count("ezspGetConfigurationValue(id)") != 1:
        die("expected exactly one generic read-only config call")
    if "p009SetAndVerifyEzspConfigValue" in text or "[P009 EZSP]" in text or "[P010 PRESSURE]" in text:
        die("config audit must remain separate from policy/pressure overlays")
    path.write_text(text, encoding="utf-8")
    print("P009 effective-config audit patch applied")
    print("  operation: read-only ezspGetConfigurationValue")
    print("  values: BTT, threshold, key, child, retry, networks, MTORR, sleepy-multicast")
    print("  writes/retries/routing changes: NO")


if __name__ == "__main__":
    main()
