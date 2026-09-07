#!/usr/bin/env python3
"""Add bounded, read-only Ember pressure telemetry on BUSY to herdsman 10.9.1.

Diagnostic-only P010 candidate. It changes no EZSP configuration, retry policy,
queue sizing, routing, or send result. Crucially, a BUSY path never awaits the
counter read: the original send error is thrown immediately. One best-effort
snapshot is scheduled behind the adapter queue and bursts are coalesced.
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
PRESSURE_HELPER = '''    private p010PressureSnapshotPending = false;
    private p010PressureLastScheduledAt = 0;

    /**
     * P010 diagnostic-only pressure snapshot scheduler.
     *
     * The send failure path calls this synchronously but NEVER awaits an EZSP
     * request. The original BUSY is therefore thrown immediately. A single
     * read-only snapshot is scheduled on the adapter queue after the current
     * JavaScript turn; repeated BUSY events within five seconds are coalesced.
     */
    private p010SchedulePressureCounters(context: string): void {
        const now = Date.now();
        if (this.p010PressureSnapshotPending || now - this.p010PressureLastScheduledAt < 5000) {
            logger.warning(`[P010 PRESSURE] context=${context} snapshot=coalesced`, NS);
            return;
        }

        this.p010PressureSnapshotPending = true;
        this.p010PressureLastScheduledAt = now;
        setTimeout(() => {
            void this.queue
                .execute<void>(async () => {
                    const started = Date.now();
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
                        logger.warning(
                            `[P010 PRESSURE] context=${context} snapshot=ok latencyMs=${Date.now() - started} counters=${JSON.stringify(selected)}`,
                            NS,
                        );
                    } catch (error) {
                        logger.warning(
                            `[P010 PRESSURE] context=${context} snapshot=failed latencyMs=${Date.now() - started} error=${String(error)}`,
                            NS,
                        );
                    } finally {
                        this.p010PressureSnapshotPending = false;
                    }
                })
                .catch((error) => {
                    this.p010PressureSnapshotPending = false;
                    logger.warning(`[P010 PRESSURE] context=${context} snapshot=queue-failed error=${String(error)}`, NS);
                });
        }, 0);
    }

'''

GROUP_OLD = '''            if (status !== SLStatus.OK) {
                throw new Error(`~x~> [ZCL GROUP groupId=${groupID}] Failed to send with status=${SLStatus[status]}.`);
            }
'''
GROUP_NEW = '''            if (status !== SLStatus.OK) {
                if (status === SLStatus.BUSY) {
                    this.p010SchedulePressureCounters(`ZCL_GROUP:${groupID}`);
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
                    this.p010SchedulePressureCounters(`ZCL_BROADCAST:${destination}`);
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
                        this.p010SchedulePressureCounters(`ZDO_BROADCAST:${clusterName}:${networkAddress}`);
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
    if "await this.p010SchedulePressureCounters" in text:
        die("BUSY path must not await P010 diagnostics")
    if text.count("this.p010SchedulePressureCounters(`") != 3:
        die("expected exactly three non-awaiting BUSY hooks")
    if "now - this.p010PressureLastScheduledAt < 5000" not in text:
        die("five-second diagnostic coalescing guard missing")
    if text.count("[P010 PRESSURE]") != 4:
        die("unexpected pressure marker count")

    path.write_text(text, encoding="utf-8")
    print("P010 diagnostic observability patch applied")
    print("  BUSY hooks: ZCL group, ZCL broadcast, ZDO broadcast")
    print("  original BUSY propagation: immediate / not awaited")
    print("  counter operation: read-only ezspReadCounters(), queued asynchronously")
    print("  burst behavior: single-flight + 5s coalescing")
    print("  counter clear: NO")
    print("  retry/send/routing/config behavior changed: NO")


if __name__ == "__main__":
    main()
