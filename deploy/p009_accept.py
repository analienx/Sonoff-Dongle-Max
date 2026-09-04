"""P009 bounded acceptance command."""
from __future__ import annotations

import argparse
import json
import re
import shlex

from p009_common import *  # noqa: F403
from p009_deploy import PHASE_AUTO, PHASE_IDENTITY, require_phase, save_session, stop_session, validate_session_target


def parse_json_output(text: str, label: str) -> dict[str, object]:
    try:
        doc = json.loads(text)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"{label} did not return JSON: {exc}") from exc
    if not isinstance(doc, dict):
        raise RuntimeError(f"{label} output is not an object")
    return doc


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
    try:
        remote_write_text(args.host, remote_active, args.active_script.read_text(encoding="utf-8"))
        remote_write_text(args.host, remote_permit, args.permit_script.read_text(encoding="utf-8"))
        container = require_single_z2m_owner(args.host)
        logs_before = addon_logs(args.host, args.addon)

        out1 = remote_exec(args.host, f"docker exec {shlex.quote(container)} node {shlex.quote(remote_active)}")
        active = parse_json_output(out1, "active canary")
        if active.get("ok") is not True:
            raise RuntimeError(f"active canary failed: {active.get('successes')}/{active.get('total')}")

        out2 = remote_exec(args.host, f"docker exec -e NJ_ALL=5 -e NJ_COORD=0 -e NJ_SECONDS=10 {shlex.quote(container)} node {shlex.quote(remote_permit)}")
        permit = parse_json_output(out2, "permit-join gate")
        if permit.get("ok") is not True:
            raise RuntimeError("permit-join gate failed")

        logs_after = addon_logs(args.host, args.addon)
        delta, exact_delta = appended_logs(logs_before, logs_after)
        fatal = [line for line in delta.splitlines() if re.search(r"NCP.*reset|ASH.*(error|reset)|adapter.*disconnected|NETWORK_DOWN", line, re.IGNORECASE)]
        if fatal:
            raise RuntimeError("fatal NCP/ASH signatures in acceptance window: " + " | ".join(fatal[-10:]))
    except BaseException as exc:
        stop_session(args.session, session, str(exc), args.host, args.addon, stop_addon=True)
        die(f"acceptance STOP; Z2M stopped and session marked STOPPED: {exc}")

    session["acceptance"] = {"active": active, "permit": permit, "fatal_log_lines": fatal, "log_delta_exact": exact_delta}
    session["phase"] = PHASE_AUTO
    save_session(args.session, session)
    print(f"P009: automated acceptance PASS -> phase={PHASE_AUTO}")
    if not exact_delta:
        print("P009: WARNING: add-on log buffer rotated; fatal scan used bounded final 500-line tail.")
    print("Run exactly two representative real group commands and verify the physical loads, then finalize.")
