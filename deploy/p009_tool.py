#!/usr/bin/env python3
"""Controlled P009 deployment CLI. No command flashes coordinator firmware."""
from __future__ import annotations

import argparse
import subprocess
from pathlib import Path

from p009_common import DEFAULT_ADDON, DEFAULT_HOST, DEFAULT_REMOTE_TEMPLATE, DEFAULT_Z2M_DIR, configure_remote, die
from p009_deploy import cmd_arm, cmd_finalize, cmd_postflash, cmd_report, cmd_restore_data, cmd_snapshot, cmd_status
from p009_accept import cmd_acceptance


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--host", default=DEFAULT_HOST)
    p.add_argument("--addon", default=DEFAULT_ADDON)
    p.add_argument("--z2m-dir", default=DEFAULT_Z2M_DIR)
    p.add_argument("--remote-template", default=DEFAULT_REMOTE_TEMPLATE, help='Token template containing {host} and {command}, e.g. "ssh {host} {command}" or "rtk proxy ssh {host} {command}"')
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("snapshot")
    s.add_argument("--output", type=Path)
    s.set_defaults(func=cmd_snapshot)

    a = sub.add_parser("arm")
    a.add_argument("--bundle-root", type=Path, required=True)
    a.add_argument("--build-manifest", type=Path, required=True)
    a.add_argument("--session", type=Path, required=True)
    a.add_argument("--replace-session", action="store_true")
    a.add_argument("--confirm", required=True)
    a.set_defaults(func=cmd_arm)

    pf = sub.add_parser("postflash")
    pf.add_argument("--session", type=Path, required=True)
    pf.add_argument("--settle-seconds", type=int, default=20)
    pf.add_argument("--require-runtime", action="store_true")
    pf.add_argument("--confirm", required=True)
    pf.set_defaults(func=cmd_postflash)

    ac = sub.add_parser("acceptance")
    ac.add_argument("--session", type=Path, required=True)
    ac.add_argument("--active-script", type=Path, default=Path("deploy/acceptance-active.cjs"))
    ac.add_argument("--permit-script", type=Path, default=Path("deploy/acceptance-permitjoin.cjs"))
    ac.add_argument("--confirm", required=True)
    ac.set_defaults(func=cmd_acceptance)

    fn = sub.add_parser("finalize")
    fn.add_argument("--session", type=Path, required=True)
    fn.add_argument("--group-evidence", action="append", default=[], help="repeat exactly twice; brief description of verified representative group command")
    fn.add_argument("--confirm", required=True)
    fn.set_defaults(func=cmd_finalize)

    rd = sub.add_parser("restore-data")
    rd.add_argument("--session", type=Path, required=True)
    rd.add_argument("--confirm", required=True)
    rd.set_defaults(func=cmd_restore_data)

    st = sub.add_parser("status")
    st.add_argument("--session", type=Path, required=True)
    st.set_defaults(func=cmd_status)

    rp = sub.add_parser("report")
    rp.add_argument("--session", type=Path, required=True)
    rp.set_defaults(func=cmd_report)
    return p


def main() -> None:
    args = parser().parse_args()
    configure_remote(args.remote_template)
    try:
        args.func(args)
    except subprocess.CalledProcessError as exc:
        stderr = (exc.stderr or "").strip()
        die(f"command failed ({exc.returncode}): {' '.join(exc.cmd)}\n{stderr}")


if __name__ == "__main__":
    main()
