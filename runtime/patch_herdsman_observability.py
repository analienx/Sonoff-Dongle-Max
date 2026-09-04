#!/usr/bin/env python3
"""Add best-effort, read-only Ember pressure telemetry on BUSY to herdsman 10.9.1.

This is a diagnostic-only P010 candidate. It changes no EZSP configuration,
retry policy, queue sizing, routing, or send status. On BUSY from the three
broadcast/group paths implicated by production evidence it calls the existing
`ezspReadCounters()` API and logs selected counters without clearing them.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

PIN = "0968f979d558874b17396c96b66382d4236bbdcd"
TARGET = Path("src/adapter/ember/adapter/emberAdapter.ts")

IMPORT_OLD = "    EmberApsOption,\n    EmberDeviceUpdate,\n"
IMPORT_NEW = "    EmberApsOption,\n    EmberCounterType,\n    EmberDeviceUpdate,\n"

HELPER_ANCHOR = "    private async watchdogCounters(): Promise<void> {\n"
PRESSURE_HELPER = '''    /**
     * P010 diagnostic-only pressure snapshot. Read-only and best-effort: this
     * must never clear counters, retry the send, or replace the original error.
     */
    private async p010LogPressureCounters(context: string): Promise<void> {
        try {
            const counters = await this.ezsp.ezspReadCounters();
            const selected = {
                ASH_OVERFLOW_ERROR: counters[EmberCounterType.ASH_OVERFLOW_ERROR],
                ASH_FRAMING_ERROR: counters[EmberCounterType.ASH_FRAMING_ERROR],
                ASH_OVERRUN_ERROR: counters[EmberCounterType.ASH_OVERRUN_ERROR],
                ALLOCATE_PACKET_BUFFER_FAILURE: counters[EmberCounterType.ALLOCATE_PACKET_BUFFER_FAILURE],
                PHY_TO_MAC_QUEUE_LIMIT_REACHED: counters[EmberCounterType.PHY_TO_MAC_QUEUE_LIMIT_REACHED],
                NWK_RETRY_OVERFLOW: counters[EmberCounterType.TYPE_NWK_RETRY_OVERFLOW],
                PHY_CCA_FAIL_COUNT: counters[EmberCounterType.PHY_CCA_FAIL_COUNT],
                BROADCAST_TABLE_FULL: counters[EmberCounterType.BROADCAST_TABLE_FULL],
                ADDRESS_CONFLICT_SENT: counters[EmberCounterType.ADDRESS_CONFLICT_SENT],
            };
            logger.warning(`[P010 PRESSURE] context=${context} counters=${JSON.stringify(selected)}`, NS);
        } catch (error) {
            logger.warning(`[P010 PRESSURE] context=${context} counter-read-failed=${String(error)}`, NS);
        }
    }

'''

GROUP_OLD = '''            if (status !== SLStatus.OK) {
                throw new Error(`~x~> [ZCL GROUP groupId=${groupID}] Failed to send with status=${SLStatus[status]}.`);
            }
'''
GROUP_NEW = '''            if (status !== SLStatus.OK) {
                if (status === SLStatus.BUSY) {
                    await this.p010LogPressureCounters(`ZCL_GROUP:${groupID}`);
                }
                throw new Error(`~x~> [ZCL GROUP groupId=${groupID}] Failed to send with status=${SLStatus[status]}.`);
            }
'''

BROADCAST_OLD = '''            if (status !== SLStatus.OK) {
                throw new Error(`~x~> [ZCL BROADCAST destination=${destination}] Failed to send with status=${SLStatus[status]}.`);
            }
'''
BROADCAST_NEW = '''            if (status !== SLStatus.OK) {
                if (status === SLStatus.BUSY) {
                    await this.p010LogPressureCounters(`ZCL_BROADCAST:${destination}`);
                }
                throw new Error(`~x~> [ZCL BROADCAST destination=${destination}] Failed to send with status=${SLStatus[status]}.`);
            }
'''

ZDO_BROADCAST_OLD = '''                if (status !== SLStatus.OK) {
                    throw new Error(
                        `~x~> [ZDO ${clusterName} BROADCAST to=${networkAddress} messageTag=${messageTag}] Failed to send request with status=${SLStatus[status]}.`,
                    );
                }
'''
ZDO_BROADCAST_NEW = '''                if (status !== SLStatus.OK) {
                    if (status === SLStatus.BUSY) {
                        await this.p010LogPressureCounters(`ZDO_BROADCAST:${clusterName}:${networkAddress}`);
                    }
                    throw new Error(
                        `~x~> [ZDO ${clusterName} BROADCAST to=${networkAddress} messageTag=${messageTag}] Failed to send request with status=${SLStatus[status]}.`,
                    );
                }
'''


def die(message: str) -> None:
    raise SystemExit(f"P010 observability patch: {message}")


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
        die("usage: patch_herdsman_observability.py <zigbee-herdsman checkout>")
    root = Path(sys.argv[1]).resolve()
    if git_head(root) != PIN:
        die(f"checkout must be exact zigbee-herdsman 10.9.1 commit {PIN}")
    path = root / TARGET
    if not path.is_file():
        die(f"missing {TARGET}")

    original = path.read_text(encoding="utf-8")
    if "[P010 PRESSURE]" in original:
        die("target already appears patched")

    text = original
    text = replace_once(text, IMPORT_OLD, IMPORT_NEW, "EmberCounterType import")
    text = replace_once(text, HELPER_ANCHOR, PRESSURE_HELPER + HELPER_ANCHOR, "pressure helper")
    text = replace_once(text, GROUP_OLD, GROUP_NEW, "ZCL group BUSY hook")
    text = replace_once(text, BROADCAST_OLD, BROADCAST_NEW, "ZCL broadcast BUSY hook")
    text = replace_once(text, ZDO_BROADCAST_OLD, ZDO_BROADCAST_NEW, "ZDO broadcast BUSY hook")

    expected = original
    for old, new in (
        (IMPORT_OLD, IMPORT_NEW),
        (HELPER_ANCHOR, PRESSURE_HELPER + HELPER_ANCHOR),
        (GROUP_OLD, GROUP_NEW),
        (BROADCAST_OLD, BROADCAST_NEW),
        (ZDO_BROADCAST_OLD, ZDO_BROADCAST_NEW),
    ):
        expected = expected.replace(old, new, 1)
    if text != expected:
        die("patch changed content outside the five approved anchors")

    if text.count("ezspReadCounters()") != original.count("ezspReadCounters()") + 1:
        die("expected exactly one new read-only counter snapshot call")
    if text.count("ezspReadAndClearCounters()") != original.count("ezspReadAndClearCounters()"):
        die("patch must not add or remove counter-clearing calls")
    if text.count("[P010 PRESSURE]") != 2:
        die("unexpected pressure marker count")

    path.write_text(text, encoding="utf-8")
    print("P010 diagnostic observability patch applied")
    print("  BUSY hooks: ZCL group, ZCL broadcast, ZDO broadcast")
    print("  counter operation: read-only ezspReadCounters()")
    print("  counter clear: NO")
    print("  retry/send/routing/config behavior changed: NO")


if __name__ == "__main__":
    main()
