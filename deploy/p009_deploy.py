"""P009 snapshot, arm, post-flash, finalization and rollback commands."""
from __future__ import annotations

import argparse
import json
import re
import shlex
import time
from datetime import datetime, timezone
from pathlib import Path

from p009_common import *  # noqa: F403

PHASE_ARMING = "ARMING"
PHASE_ARMED = "ARMED"
PHASE_FLASH = "FLASH_CONFIRMED"
PHASE_IDENTITY = "IDENTITY_VERIFIED"
PHASE_AUTO = "AUTOMATED_ACCEPTANCE_PASSED"
PHASE_ACCEPTED = "ACCEPTED"
PHASE_STOPPED = "STOPPED"
PHASE_ROLLED_BACK_DATA = "ROLLED_BACK_DATA"


def require_phase(session: dict[str, object], *expected: str) -> None:
    phase = session.get("phase")
    if phase not in expected:
        die(f"session phase must be one of {expected}, got {phase!r}")


def validate_session_target(session: dict[str, object], args: argparse.Namespace) -> None:
    expected = {"host": args.host, "addon": args.addon, "z2m_dir": args.z2m_dir, "remote_template": args.remote_template}
    mismatches = [f"{k}: session={session.get(k)!r} cli={v!r}" for k, v in expected.items() if session.get(k) != v]
    if mismatches:
        die("CLI target/transport does not match armed session: " + "; ".join(mismatches))


def save_session(path: Path, session: dict[str, object]) -> None:
    session["updated_utc"] = datetime.now(timezone.utc).isoformat()
    write_json(path, session)


def stop_session(path: Path, session: dict[str, object], reason: str, host: str, addon: str, *, stop_addon: bool = False) -> None:
    if stop_addon:
        try:
            remote_exec(host, f"ha addons stop {shlex.quote(addon)}")
            wait_state(host, addon, {"stopped"})
        except BaseException as exc:
            reason += f"; additionally failed to confirm add-on stopped: {exc}"
    session["phase"] = PHASE_STOPPED
    session["stop_reason"] = reason
    save_session(path, session)


def cmd_snapshot(args: argparse.Namespace) -> None:
    snap = snapshot(args.host, args.addon, args.z2m_dir)
    validate_identity(snap["identity"])
    out = args.output or Path(f"p009-snapshot-{utcstamp()}.json")
    write_json(out, snap)
    print(f"P009: snapshot PASS -> {out}")
    print(json.dumps(snap["identity"], indent=2, sort_keys=True))


def cmd_arm(args: argparse.Namespace) -> None:
    if args.confirm != "P009-ARM":
        die("arm requires --confirm P009-ARM")
    if args.session.exists() and not args.replace_session:
        die(f"session already exists: {args.session}; use --replace-session only for a deliberately new deployment")
    verify_bundle_checksums(args.bundle_root)
    manifest = load_build_manifest(args.build_manifest)
    p009_gbl = find_gbl(args.bundle_root, manifest, "p009")
    stock_gbl = find_gbl(args.bundle_root, manifest, "stock")

    pre = snapshot(args.host, args.addon, args.z2m_dir)
    validate_identity(pre["identity"])
    version_blob = "\n".join(pre.get("version_lines") or [])
    if not re.search(r"9\.1\.1", version_blob):
        die("preflight logs do not show the approved EmberZNet 9.1.1 baseline")
    if not re.search(r"\bEZSP\b.*\b19\b|\bezsp\b.*\b19\b", version_blob, re.IGNORECASE):
        die("preflight logs do not show the approved EZSP 19 baseline")
    state = addon_state(pre["addon"])
    if state not in {"started", "running"}:
        die(f"expected active stock Z2M before arm, got state={state}")
    owner = require_single_z2m_owner(args.host)

    session = {
        "schema": 2,
        "phase": PHASE_ARMING,
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "repo_commit": repo_commit(),
        "host": args.host,
        "addon": args.addon,
        "z2m_dir": args.z2m_dir,
        "remote_template": args.remote_template,
        "pre": pre,
        "single_z2m_owner_pre_arm": owner,
        "p009_gbl": {"path": str(p009_gbl.resolve()), "name": p009_gbl.name, "bytes": p009_gbl.stat().st_size, "sha256": sha256_file(p009_gbl)},
        "rollback_stock_gbl": {"path": str(stock_gbl.resolve()), "name": stock_gbl.name, "bytes": stock_gbl.stat().st_size, "sha256": sha256_file(stock_gbl)},
        "build_manifest": str(args.build_manifest.resolve()),
    }
    save_session(args.session, session)

    print(f"P009: single Z2M owner confirmed: {owner}")
    print("P009: stopping Zigbee2MQTT for stopped-state backup...")
    try:
        remote_exec(args.host, f"ha addons stop {shlex.quote(args.addon)}")
        wait_state(args.host, args.addon, {"stopped"})
        stopped_hashes = remote_hashes(args.host, args.z2m_dir)
        required_stopped = {"configuration.yaml", "database.db", "coordinator_backup.json"}
        if not required_stopped.issubset(stopped_hashes):
            raise RuntimeError(f"stopped-state file hashes incomplete: {stopped_hashes}")
        stamp = utcstamp()
        backup_dir = f"/config/p009-backups/{stamp}"
        tar_path = f"{backup_dir}/zigbee2mqtt.tgz"
        q = shlex.quote
        remote = remote_exec(args.host, "set -eu; " f"mkdir -p {q(backup_dir)}; " f"tar -C /config -czf {q(tar_path)} zigbee2mqtt; " f"sha256sum {q(tar_path)}").strip()
        m = re.match(r"([0-9a-f]{64})\s+(.+)", remote)
        if not m:
            raise RuntimeError(f"could not verify stopped-state backup: {remote!r}")
        session["stopped_state_backup"] = {"remote_path": tar_path, "sha256": m.group(1), "file_sha256": stopped_hashes}
        session["phase"] = PHASE_ARMED
        save_session(args.session, session)
    except BaseException as exc:
        session["phase"] = PHASE_STOPPED
        session["stop_reason"] = f"ARM interrupted/failed after session creation: {exc}"
        save_session(args.session, session)
        print(f"P009: ARM STOPPED -> {args.session}; Zigbee2MQTT state must be reviewed before continuing.", file=__import__("sys").stderr)
        raise

    print(f"P009: ARM PASS -> {args.session}")
    print(f"P009 GBL:        {p009_gbl}")
    print(f"P009 SHA256:     {session['p009_gbl']['sha256']}")
    print(f"Stock rollback:  {stock_gbl}")
    print(f"Backup on HA:    {tar_path}")
    print(f"Backup SHA256:   {m.group(1)}")
    print("Zigbee2MQTT remains STOPPED. Flash only the exact P009 GBL above through the proven WebUI.")


def cmd_confirm_flash(args: argparse.Namespace) -> None:
    if args.confirm != "P009-FLASHED":
        die("confirm-flash requires --confirm P009-FLASHED")
    session = load_json(args.session)
    require_phase(session, PHASE_ARMED)
    validate_session_target(session, args)
    expected = str((session.get("p009_gbl") or {}).get("sha256") or "").lower()
    observed = args.observed_sha256.strip().lower()
    if not re.fullmatch(r"[0-9a-f]{64}", observed):
        die("--observed-sha256 must be a 64-character SHA256")
    if observed != expected:
        die(f"flashed GBL hash acknowledgment mismatch: expected {expected}, got {observed}")
    session["manual_flash"] = {"confirmed_utc": datetime.now(timezone.utc).isoformat(), "sha256": observed, "webui_note": args.webui_note.strip()[:500]}
    session["phase"] = PHASE_FLASH
    save_session(args.session, session)
    print(f"P009: manual flash acknowledged for exact ARM-verified GBL -> phase={PHASE_FLASH}")


def runtime_readbacks(lines: list[str]) -> dict[str, dict[str, object]]:
    expected = {
        "BROADCAST_TABLE_SIZE": 64,
        "NEW_BROADCAST_ENTRY_THRESHOLD": 48,
        "RETRY_QUEUE_SIZE": 16,
        "MTORR_FLOW_CONTROL": 1,
        "SUPPORTED_NETWORKS": 1,
        "SEND_MULTICASTS_TO_SLEEPY_ADDRESS": 0,
    }
    out: dict[str, dict[str, object]] = {}
    rx = re.compile(r"\[P009 EZSP\]\s+(\w+)\s+expected=(\d+)\s+actual=(\d+)\s+readStatus=(\w+)", re.IGNORECASE)
    for line in lines:
        m = rx.search(line)
        if not m:
            continue
        name = m.group(1).upper()
        out[name] = {"expected": int(m.group(2)), "actual": int(m.group(3)), "read_status": m.group(4).upper()}
    for name, value in expected.items():
        rec = out.get(name)
        if rec and (rec["expected"] != value or rec["actual"] != value or rec["read_status"] != "OK"):
            raise RuntimeError(f"bad P009 EZSP readback for {name}: {rec}")
    return out


def cmd_postflash(args: argparse.Namespace) -> None:
    if args.confirm != "P009-POSTFLASH":
        die("postflash requires --confirm P009-POSTFLASH")
    session = load_json(args.session)
    require_phase(session, PHASE_FLASH)
    validate_session_target(session, args)
    info = addon_info(args.host, args.addon)
    if addon_state(info) not in {"started", "running"}:
        remote_exec(args.host, f"ha addons start {shlex.quote(args.addon)}")
        wait_state(args.host, args.addon, {"started", "running"}, timeout=120)
    time.sleep(args.settle_seconds)
    try:
        post = snapshot(args.host, args.addon, args.z2m_dir)
        validate_identity(post["identity"])
        diffs = compare_identity(session["pre"], post)
        version_blob = "\n".join(post.get("version_lines") or [])
        if diffs:
            raise RuntimeError("network identity changed: " + "; ".join(diffs))
        if not re.search(r"9\.1\.1", version_blob):
            raise RuntimeError("post-flash logs do not show EmberZNet 9.1.1")
        if not re.search(r"\bEZSP\b.*\b19\b|\bezsp\b.*\b19\b", version_blob, re.IGNORECASE):
            raise RuntimeError("post-flash logs do not show EZSP 19")
        readbacks = runtime_readbacks(post.get("version_lines") or [])
        required = {"BROADCAST_TABLE_SIZE", "NEW_BROADCAST_ENTRY_THRESHOLD", "RETRY_QUEUE_SIZE", "MTORR_FLOW_CONTROL", "SUPPORTED_NETWORKS", "SEND_MULTICASTS_TO_SLEEPY_ADDRESS"}
        if args.require_runtime and set(readbacks) != required:
            raise RuntimeError(f"runtime overlay required but complete six-value readback was not found: {sorted(readbacks)}")
    except BaseException as exc:
        stop_session(args.session, session, str(exc), args.host, args.addon, stop_addon=True)
        die(f"post-flash gate failed; Z2M stopped and session marked STOPPED: {exc}")
    session["postflash"] = {"snapshot": post, "runtime_readbacks": readbacks, "runtime_required": args.require_runtime}
    session["phase"] = PHASE_IDENTITY
    save_session(args.session, session)
    print(f"P009: POSTFLASH IDENTITY PASS -> phase={PHASE_IDENTITY}")
    print("No P009 runtime-overlay marker is expected for the firmware-only/stock-Z2M first test." if not readbacks else f"P009 runtime overlay readbacks detected: {len(readbacks)}/6")


def cmd_finalize(args: argparse.Namespace) -> None:
    if args.confirm != "P009-FINALIZE":
        die("finalize requires --confirm P009-FINALIZE")
    session = load_json(args.session)
    require_phase(session, PHASE_AUTO)
    validate_session_target(session, args)
    if len(args.group_evidence) != 2 or any(not x.strip() for x in args.group_evidence):
        die("finalize requires exactly two non-empty --group-evidence values")
    try:
        final_snapshot = snapshot(args.host, args.addon, args.z2m_dir)
        validate_identity(final_snapshot["identity"])
        diffs = compare_identity(session["pre"], final_snapshot)
        if diffs:
            raise RuntimeError("final identity changed: " + "; ".join(diffs))
    except BaseException as exc:
        stop_session(args.session, session, f"finalization safety gate failed: {exc}", args.host, args.addon, stop_addon=True)
        die(f"finalize STOP; Z2M stopped and session marked STOPPED: {exc}")
    session["group_command_evidence"] = [x.strip() for x in args.group_evidence]
    session["final_snapshot"] = final_snapshot
    session["phase"] = PHASE_ACCEPTED
    session["accepted_utc"] = datetime.now(timezone.utc).isoformat()
    save_session(args.session, session)
    print("P009: ACCEPTED. Stop testing; no soak or parameter matrix.")


def cmd_restore_data(args: argparse.Namespace) -> None:
    if args.confirm != "P009-RESTORE-DATA":
        die("restore-data requires --confirm P009-RESTORE-DATA")
    session = load_json(args.session)
    validate_session_target(session, args)
    backup = session.get("stopped_state_backup") or {}
    remote_path = backup.get("remote_path")
    expected_hash = backup.get("sha256")
    if not isinstance(remote_path, str) or not re.fullmatch(r"[0-9a-f]{64}", str(expected_hash)):
        die("invalid stopped-state backup metadata")
    q = shlex.quote
    try:
        actual = remote_exec(args.host, f"sha256sum {q(remote_path)}").split()[0]
        if actual != expected_hash:
            raise RuntimeError(f"remote rollback backup hash mismatch: {actual}")
        remote_exec(args.host, f"ha addons stop {shlex.quote(args.addon)}")
        wait_state(args.host, args.addon, {"stopped"})
        quarantine = f"/config/zigbee2mqtt.failed-p009-{utcstamp()}"
        remote_exec(args.host, "set -eu; " f"mv {q(args.z2m_dir)} {q(quarantine)}; " f"tar -C /config -xzf {q(remote_path)}; " f"test -f {q(args.z2m_dir + '/database.db')}; " f"test -f {q(args.z2m_dir + '/configuration.yaml')}; " f"test -f {q(args.z2m_dir + '/coordinator_backup.json')}")
        expected_files = backup.get("file_sha256") or {}
        restored_hashes = remote_hashes(args.host, args.z2m_dir)
        if expected_files and restored_hashes != expected_files:
            raise RuntimeError(f"restored stopped-state hashes differ: expected={expected_files} actual={restored_hashes}")
        remote_exec(args.host, f"ha addons start {shlex.quote(args.addon)}")
        wait_state(args.host, args.addon, {"started", "running"}, timeout=120)
        require_single_z2m_owner(args.host)
    except BaseException as exc:
        session["phase"] = PHASE_STOPPED
        session["stop_reason"] = f"data restore failed/interrupted: {exc}"
        save_session(args.session, session)
        print("P009: data restore STOPPED; review HA/Z2M filesystem and add-on state before further action.", file=__import__("sys").stderr)
        raise
    session["data_restore"] = {"utc": datetime.now(timezone.utc).isoformat(), "quarantine": quarantine}
    session["phase"] = PHASE_ROLLED_BACK_DATA
    save_session(args.session, session)
    print(f"P009: stopped-state data restored; failed state quarantined at {quarantine}")


def cmd_status(args: argparse.Namespace) -> None:
    session = load_json(args.session)
    phase = session.get("phase")
    next_step = {
        PHASE_ARMING: "Interrupted/in-progress ARM state. Do not continue until reviewed.",
        PHASE_ARMED: "Flash exact P009 GBL via WebUI, then confirm-flash with its exact SHA256.",
        PHASE_FLASH: "Run postflash identity gate.",
        PHASE_IDENTITY: "Run bounded acceptance.",
        PHASE_AUTO: "Run exactly two representative group commands, then finalize with two evidence strings.",
        PHASE_ACCEPTED: "Done. Stop testing.",
        PHASE_STOPPED: "Do not continue. Review stop_reason and decide rollback/runtime/MG26.",
        PHASE_ROLLED_BACK_DATA: "Verify coordinator firmware/identity before normal operation.",
    }.get(phase, "Unknown phase; review session JSON.")
    print(json.dumps({"phase": phase, "next": next_step, "stop_reason": session.get("stop_reason")}, indent=2))


def cmd_report(args: argparse.Namespace) -> None:
    s = load_json(args.session)
    p = s.get("p009_gbl") or {}
    st = s.get("rollback_stock_gbl") or {}
    a = s.get("acceptance") or {}
    can = a.get("active") or {}
    per = a.get("permit") or {}
    results = per.get("results") or []
    permit_ok = sum(1 for r in results if isinstance(r, dict) and r.get("status") == "ok")
    busy = sum(len(r.get("busy") or []) for r in results if isinstance(r, dict))
    groups = len(s.get("group_command_evidence") or [])
    print(f"PHASE: {s.get('phase')}")
    print(f"P009 GBL: {p.get('name')} | {p.get('bytes')} | {p.get('sha256')}")
    print(f"STOCK GBL: {st.get('name')} | {st.get('bytes')} | {st.get('sha256')}")
    print(f"MANUAL FLASH ACK: {'YES' if s.get('manual_flash') else 'NO'}")
    print(f"POSTFLASH IDENTITY: {'PASS' if s.get('postflash') else 'NOT RUN'}")
    print(f"ACTIVE CANARY: {can.get('successes', 0)}/{can.get('total', 16)}")
    print(f"PERMIT JOIN ALL: {permit_ok}/{len(results) or 5} OK | BUSY={busy}")
    print(f"GROUP COMMANDS: {groups}/2")
    print(f"NCP/ASH RESET DURING GATE: {len(a.get('fatal_log_lines') or [])}")
    if s.get("phase") == PHASE_STOPPED:
        print(f"FINAL: STOPPED ON {s.get('stop_reason')}")
    elif s.get("phase") == PHASE_ACCEPTED:
        print("FINAL: PASS")
    else:
        print("FINAL: INCOMPLETE")
