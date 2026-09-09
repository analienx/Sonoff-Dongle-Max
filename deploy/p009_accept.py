"""P009 bounded acceptance command."""
from __future__ import annotations

import argparse
import json
import re
import shlex
from datetime import datetime, timezone

from p009_common import *  # noqa: F403
from p009_deploy import PHASE_AUTO, PHASE_IDENTITY, require_phase, save_session, stop_session, validate_session_target

def parse_json_output(text: str, label: str) -> dict[str, object]:
    try:
        doc = json.loads(text)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"{label} did not return JSON: {exc}; output={text[:500]!r}") from exc
    if not isinstance(doc, dict):
        raise RuntimeError(f"{label} output is not an object")
    return doc


def scan_hard_signatures(text: str) -> list[str]:
    return scan_hard_log_signatures(text)


def validate_active_result(active: dict[str, object]) -> None:
    expected = active.get("expected")
    completed = active.get("completed")
    unique = active.get("unique_completed")
    scheduled = active.get("scheduled")
    successes = active.get("successes")
    if expected != 16 or completed != 16 or unique != 16 or scheduled != 16:
        raise RuntimeError(
            f"active canary incomplete/duplicated: expected={expected} completed={completed} unique={unique} scheduled={scheduled}"
        )
    if not isinstance(successes, int) or successes < 15:
        raise RuntimeError(f"active canary success threshold failed: {successes}/16")
    hard_events = active.get("hard_events") or []
    if active.get("global_timeout") is True or active.get("malformed_responses") not in (0, None) or hard_events:
        raise RuntimeError(
            f"active canary evidence invalid: global_timeout={active.get('global_timeout')} malformed={active.get('malformed_responses')} hard_events={hard_events[:3] if isinstance(hard_events, list) else hard_events}"
        )
    if active.get("ok") is not True:
        raise RuntimeError(f"active canary failed despite complete evidence: {successes}/16")


def validate_permit_result(permit: dict[str, object]) -> None:
    requested = permit.get("requested") or {}
    if not isinstance(requested, dict) or requested.get("all") != 5 or requested.get("coord") != 0:
        raise RuntimeError(f"permit gate requested unexpected trial counts: {requested}")
    if permit.get("attempted") != 5:
        raise RuntimeError(f"permit gate did not complete all five success-path trials: attempted={permit.get('attempted')}")
    cleanup = permit.get("cleanup") or {}
    if not isinstance(cleanup, dict) or cleanup.get("ok") is not True or cleanup.get("fresh_permit_false") is not True:
        raise RuntimeError(f"permit cleanup did not prove fresh permit_join=false: {cleanup}")
    if permit.get("final_permit") is not False:
        raise RuntimeError(f"permit final state is not false: {permit.get('final_permit')!r}")
    if permit.get("hard_stop") not in (None, "") or permit.get("global_timeout") is True:
        raise RuntimeError(f"permit gate recorded hard stop/timeout: {permit.get('hard_stop')!r}")
    malformed = permit.get("malformed") or []
    if malformed:
        raise RuntimeError(f"permit gate observed malformed MQTT evidence: {malformed[:3]}")
    if permit.get("ok") is not True:
        raise RuntimeError("permit-join gate failed")


def owner_epoch(host: str, addon: str) -> dict[str, object]:
    container = require_single_z2m_owner(host, addon)
    return container_session(host, container)


def cmd_acceptance(args: argparse.Namespace) -> None:
    if args.confirm != "P009-ACCEPT":
        die("acceptance requires --confirm P009-ACCEPT")
    session = load_json(args.session)
    require_phase(session, PHASE_IDENTITY)
    validate_session_target(session, args)
    for path in (args.active_script, args.permit_script):
        if not path.is_file():
            die(f"acceptance script missing: {path}")

    remote_active = f"{args.z2m_dir}/p009-acceptance-active.cjs"
    remote_permit = f"{args.z2m_dir}/p009-acceptance-permitjoin.cjs"
    evidence: dict[str, object] = {
        "started_utc": datetime.now(timezone.utc).isoformat(),
        "status": "RUNNING",
        "active": None,
        "permit": None,
        "hard_log_lines": [],
        "log_delta_exact": None,
    }
    session["acceptance"] = evidence
    save_session(args.session, session)

    try:
        remote_write_text(args.host, remote_active, args.active_script.read_text(encoding="utf-8"))
        remote_write_text(args.host, remote_permit, args.permit_script.read_text(encoding="utf-8"))
        start_owner = owner_epoch(args.host, args.addon)
        container = str(start_owner["container"])
        log_container = str(start_owner["container_id"])
        log_since = str(evidence["started_utc"])
        evidence["owner_start"] = start_owner
        evidence["log_capture"] = {"container_id": log_container, "since": log_since, "mode": "docker-owner-bound"}
        save_session(args.session, session)

        out1 = remote_exec(args.host, f"docker exec {shlex.quote(container)} node {shlex.quote(remote_active)}")
        active = parse_json_output(out1, "active canary")
        evidence["active"] = active
        evidence["active_completed_utc"] = datetime.now(timezone.utc).isoformat()
        save_session(args.session, session)
        validate_active_result(active)

        active_window = container_logs_since(args.host, log_container, log_since)
        active_hard = scan_hard_signatures(active_window)
        evidence["active_log_sha256"] = sha256_bytes(active_window.encode("utf-8"))
        evidence["hard_log_lines"] = active_hard
        save_session(args.session, session)
        if active_hard:
            raise RuntimeError("hard signature appeared during active canary; Permit Join was not started: " + " | ".join(active_hard[-10:]))

        mid_owner = owner_epoch(args.host, args.addon)
        if (mid_owner.get("container_id"), mid_owner.get("started_at")) != (start_owner.get("container_id"), start_owner.get("started_at")):
            raise RuntimeError(f"Z2M owner/start epoch changed during active canary: start={start_owner} now={mid_owner}")

        out2 = remote_exec(
            args.host,
            f"docker exec -e NJ_ALL=5 -e NJ_COORD=0 -e NJ_SECONDS=10 {shlex.quote(container)} node {shlex.quote(remote_permit)}",
        )
        permit = parse_json_output(out2, "permit-join gate")
        evidence["permit"] = permit
        evidence["permit_completed_utc"] = datetime.now(timezone.utc).isoformat()
        save_session(args.session, session)
        validate_permit_result(permit)

        full_window = container_logs_since(args.host, log_container, log_since)
        full_hard = scan_hard_signatures(full_window)
        evidence["full_log_sha256"] = sha256_bytes(full_window.encode("utf-8"))
        evidence["log_delta_exact"] = True
        evidence["hard_log_lines"] = full_hard
        save_session(args.session, session)
        if full_hard:
            raise RuntimeError("hard NCP/message-pressure signature in acceptance window: " + " | ".join(full_hard[-10:]))

        end_owner = owner_epoch(args.host, args.addon)
        evidence["owner_end"] = end_owner
        if (end_owner.get("container_id"), end_owner.get("started_at")) != (start_owner.get("container_id"), start_owner.get("started_at")):
            raise RuntimeError(f"Z2M owner/start epoch changed during acceptance: start={start_owner} end={end_owner}")
        evidence["status"] = "PASSED"
        evidence["completed_utc"] = datetime.now(timezone.utc).isoformat()
        save_session(args.session, session)
    except BaseException as exc:
        evidence["status"] = "FAILED"
        evidence["error"] = str(exc)
        evidence["failed_utc"] = datetime.now(timezone.utc).isoformat()
        session["acceptance"] = evidence
        save_session(args.session, session)
        stop_session(args.session, session, f"acceptance failed: {exc}", args.host, args.addon, stop_addon=True)
        die(f"acceptance STOP; partial evidence persisted, Z2M stopped and session marked STOPPED: {exc}")

    session["acceptance"] = evidence
    session["phase"] = PHASE_AUTO
    save_session(args.session, session)
    print(f"P009: automated acceptance PASS -> phase={PHASE_AUTO}")
    print("Run exactly two representative real group commands and verify the physical loads, then finalize.")
