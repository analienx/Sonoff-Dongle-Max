"""Fail-closed single-shot MR4U CC2674P10 hardware-radio recovery.

The Zigbee coordinator data path remains USB.  SLZB-OS management is used only
for one vendor-supported radio reset (CMD_ZB_RST); recovery is then verified by
raw ZNP SYS_PING/SYS_VERSION over the Home Assistant USB endpoint.

No flash, erase, NV write, network formation, restore, pairing, or reset loop is
implemented here.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import importlib.util
import ipaddress
import json
import os
from pathlib import Path
import re
import shlex
import sys
import time
from typing import Any, Callable
from urllib.parse import urlencode
from urllib.request import Request, urlopen

HA_HELPER = Path("C:/Workspace/repos/config/skills/home-assistant-readonly/ha_readonly.py")
MODEL = "SLZB-MR4U"
CHIP = "CC2674P10"
COORDINATOR_FW_TYPE = 0
USB_COORD_MODE = 2
API_ACTION_CMD = 4
API_CMD_ZB_RST = 1
USB_RE = re.compile(
    r"^/dev/serial/by-id/usb-SMLIGHT_SMLIGHT_SLZB-MR4U_[A-Za-z0-9._-]+-if02$"
)
RUN_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{2,79}$")

REMOTE_PROBE = r"""
import json,os,select,sys,termios,time
p=sys.argv[1]
fd=os.open(p,os.O_RDWR|os.O_NOCTTY|os.O_NONBLOCK)
def raw():
    a=termios.tcgetattr(fd)
    a[0]=0;a[1]=0;a[2]=termios.CS8|termios.CREAD|termios.CLOCAL;a[3]=0
    a[4]=termios.B115200;a[5]=termios.B115200
    a[6][termios.VMIN]=0;a[6][termios.VTIME]=0
    termios.tcsetattr(fd,termios.TCSANOW,a)
    termios.tcflush(fd,termios.TCIFLUSH)
def frame(cmd):
    body=bytes([0,0x21,cmd]);f=0
    for x in body:f^=x
    return b'\xfe'+body+bytes([f])
def req(cmd,timeout=2.5):
    os.write(fd,frame(cmd));buf=b'';end=time.monotonic()+timeout
    while time.monotonic()<end:
        r,_,_=select.select([fd],[],[],0.15)
        if r:
            try:buf+=os.read(fd,4096)
            except BlockingIOError:pass
        while True:
            at=buf.find(b'\xfe')
            if at<0:buf=b'';break
            if at:buf=buf[at:]
            if len(buf)<5:break
            n=buf[1];total=n+5
            if len(buf)<total:break
            fr,buf=buf[:total],buf[total:]
            f=0
            for x in fr[1:-1]:f^=x
            if f or fr[2]!=0x61 or fr[3]!=cmd:continue
            return fr[4:-1]
    return None
try:
    raw();ping=req(1);version=req(2)
    revision=None
    if version is not None and len(version)>=9:
        revision=int.from_bytes(version[5:9],'little')
    print(json.dumps({
        'ok':bool(ping and version),
        'ping_hex':ping.hex() if ping else None,
        'version_hex':version.hex() if version else None,
        'revision':revision,
    }))
finally:
    os.close(fd)
"""

def private_ipv4(value: str) -> str:
    addr = ipaddress.ip_address(value)
    if addr.version != 4 or not addr.is_private or addr.is_loopback or addr.is_link_local:
        raise ValueError("management host must be an explicit private IPv4 address")
    return str(addr)


def validate_usb_path(path: str) -> str:
    if not USB_RE.fullmatch(path):
        raise ValueError("USB device must be the explicit MR4U if02 by-id endpoint")
    return path


def auth_header(username_env: str | None, password_env: str | None) -> dict[str, str]:
    if bool(username_env) != bool(password_env):
        raise ValueError("username/password environment variable names must be supplied together")
    if not username_env:
        return {}
    username = os.environ.get(username_env, "")
    password = os.environ.get(password_env or "", "")
    if not username or not password:
        raise ValueError("configured SLZB credential environment variables are empty")
    token = base64.b64encode(f"{username}:{password}".encode()).decode()
    return {"Authorization": "Basic " + token}


def http_get_text(host: str, path: str, params: dict[str, int] | None,
                  headers: dict[str, str], timeout: float = 4.0) -> str:
    private_ipv4(host)
    if not path.startswith("/") or "://" in path or ".." in path:
        raise ValueError("invalid fixed management API path")
    query = ("?" + urlencode(params)) if params else ""
    request = Request(f"http://{host}{path}{query}", headers=headers, method="GET")
    with urlopen(request, timeout=timeout) as response:
        if response.status != 200:
            raise RuntimeError(f"SLZB management returned HTTP {response.status}")
        data = response.read(1024 * 1024 + 1)
    if len(data) > 1024 * 1024:
        raise RuntimeError("SLZB response exceeds size limit")
    return data.decode("utf-8", errors="strict").strip()


def load_info(host: str, headers: dict[str, str]) -> dict[str, Any]:
    raw = http_get_text(host, "/ha_info", None, headers)
    data = json.loads(raw)
    info = data.get("Info")
    if not isinstance(info, dict):
        raise RuntimeError("SLZB /ha_info payload is missing Info")
    return info


def validate_target(info: dict[str, Any], expected_index: int,
                    expected_revision: int) -> dict[str, Any]:
    if info.get("model") != MODEL:
        raise RuntimeError("management endpoint is not the expected SLZB-MR4U")
    if int(info.get("coord_mode", -1)) != USB_COORD_MODE:
        raise RuntimeError("MR4U is not in USB coordinator mode; refusing reset")
    radios = info.get("radios")
    if not isinstance(radios, list):
        raise RuntimeError("MR4U radio inventory is unavailable")
    p10s = [r for r in radios if isinstance(r, dict) and r.get("zb_hw") == CHIP]
    if len(p10s) != 1:
        raise RuntimeError("expected exactly one CC2674P10 radio")
    radio = p10s[0]
    if int(radio.get("chip_index", -1)) != expected_index:
        raise RuntimeError("CC2674P10 radio index does not match the explicit expected index")
    if int(radio.get("zb_type", -1)) != COORDINATOR_FW_TYPE:
        raise RuntimeError("CC2674P10 is not recorded as coordinator firmware")
    if int(radio.get("zb_version", -1)) != expected_revision:
        raise RuntimeError("CC2674P10 firmware revision does not match the expected revision")
    return {
        "model": MODEL,
        "coord_mode": USB_COORD_MODE,
        "chip": CHIP,
        "radio_index": expected_index,
        "firmware_revision": expected_revision,
        "slzb_os": info.get("sw_version"),
    }


def reset_radio_once(host: str, headers: dict[str, str], index: int) -> None:
    text = http_get_text(
        host, "/api2",
        {"action": API_ACTION_CMD, "cmd": API_CMD_ZB_RST, "idx": index},
        headers,
    )
    if text != "ok":
        raise RuntimeError("SLZB-OS did not acknowledge CMD_ZB_RST")


def load_ha_client():
    spec = importlib.util.spec_from_file_location("ha_readonly", HA_HELPER)
    if spec is None or spec.loader is None:
        raise RuntimeError("canonical Home Assistant SSH helper unavailable")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.connect("ha")


def usb_identity(client, path: str) -> dict[str, str]:
    validate_usb_path(path)
    command = "udevadm info -q property -n " + shlex.quote(path)
    _, stdout, _ = client.exec_command(command, timeout=10)
    raw = stdout.read().decode("utf-8", errors="replace")
    if stdout.channel.recv_exit_status() != 0:
        raise RuntimeError("cannot read MR4U USB identity on Home Assistant")
    props: dict[str, str] = {}
    for line in raw.splitlines():
        if "=" in line:
            key, value = line.split("=", 1)
            props[key] = value
    if props.get("ID_USB_INTERFACE_NUM") != "02":
        raise RuntimeError("USB endpoint is not interface 02")
    model = props.get("ID_MODEL", "")
    if "SLZB-MR4U" not in model:
        raise RuntimeError("USB endpoint is not identified as SLZB-MR4U")
    serial = props.get("ID_SERIAL_SHORT", "")
    if not serial:
        raise RuntimeError("MR4U USB serial identity is missing")
    return {
        "interface": "02",
        "model": model,
        "serial_sha256": hashlib.sha256(serial.encode()).hexdigest(),
    }


def usb_probe(client, path: str) -> dict[str, Any]:
    validate_usb_path(path)
    command = "python3 -c " + shlex.quote(REMOTE_PROBE) + " " + shlex.quote(path)
    _, stdout, _ = client.exec_command(command, timeout=12)
    raw = stdout.read().decode("utf-8", errors="replace").strip()
    status = stdout.channel.recv_exit_status()
    if status != 0:
        raise RuntimeError("raw USB ZNP probe failed to execute")
    data = json.loads(raw)
    if not isinstance(data, dict) or "ok" not in data:
        raise RuntimeError("raw USB ZNP probe returned invalid data")
    return data


def require_z2m_quiescent(client) -> dict[str, Any]:
    from p10_ha_state import addon_quiescent
    return addon_quiescent(client)


def recover(*, info: dict[str, Any], expected_index: int, expected_revision: int,
            execute: bool, reason: str | None, run_id: str | None,
            quiescent: Callable[[], dict[str, Any]],
            identity: Callable[[], dict[str, str]],
            pre_probe: Callable[[], dict[str, Any]],
            reset_once: Callable[[], None],
            post_probe: Callable[[], dict[str, Any]],
            sleep: Callable[[float], None] = time.sleep) -> dict[str, Any]:
    target = validate_target(info, expected_index, expected_revision)
    q = quiescent()
    usb = identity()
    before = pre_probe()
    result: dict[str, Any] = {
        "operation": "mr4u_p10_r2_radio_reset",
        "target": target,
        "usb": usb,
        "z2m": q,
        "pre": before,
        "reset_attempted": False,
        "verified": False,
    }
    if not execute:
        result["mode"] = "preflight"
        return result
    if before.get("ok") is True:
        raise RuntimeError("P10 already answers raw USB ZNP; refusing recovery reset")
    if not reason or len(reason.strip()) < 6 or len(reason) > 160:
        raise ValueError("execute requires a concise reset reason")
    if not run_id or not RUN_ID_RE.fullmatch(run_id):
        raise ValueError("execute requires a safe 3-80 character run id")

    result["mode"] = "execute"
    result["reason"] = reason.strip()
    result["run_id"] = run_id
    reset_once()
    result["reset_attempted"] = True

    last: dict[str, Any] = {"ok": False}
    for attempt in range(1, 7):
        sleep(1.0 if attempt == 1 else 1.5)
        last = post_probe()
        if last.get("ok") is True:
            if last.get("revision") != expected_revision:
                raise RuntimeError("post-reset USB ZNP revision mismatch")
            result["post"] = last
            result["verify_attempt"] = attempt
            result["verified"] = True
            return result
    result["post"] = last
    result["verify_attempt"] = 6
    result["failure"] = "R2_RESET_DID_NOT_RESTORE_ZNP"
    return result


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--host", required=True, help="MR4U management private IPv4")
    p.add_argument("--radio-index", type=int, default=1)
    p.add_argument("--expected-revision", type=int, required=True)
    p.add_argument("--usb-device", required=True)
    p.add_argument("--username-env")
    p.add_argument("--password-env")
    p.add_argument("--execute", action="store_true")
    p.add_argument("--reason")
    p.add_argument("--run-id")
    args = p.parse_args(argv)

    client = None
    try:
        host = private_ipv4(args.host)
        usb_path = validate_usb_path(args.usb_device)
        if args.radio_index < 0 or args.radio_index > 2:
            raise ValueError("radio index outside MR-series range")
        headers = auth_header(args.username_env, args.password_env)
        info = load_info(host, headers)
        client = load_ha_client()

        result = recover(
            info=info,
            expected_index=args.radio_index,
            expected_revision=args.expected_revision,
            execute=args.execute,
            reason=args.reason,
            run_id=args.run_id,
            quiescent=lambda: require_z2m_quiescent(client),
            identity=lambda: usb_identity(client, usb_path),
            pre_probe=lambda: usb_probe(client, usb_path),
            reset_once=lambda: reset_radio_once(host, headers, args.radio_index),
            post_probe=lambda: usb_probe(client, usb_path),
        )
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0 if (not args.execute or result.get("verified") is True) else 3
    except (OSError, ValueError, RuntimeError, KeyError, TypeError, json.JSONDecodeError) as exc:
        print("P10_R2_RESET_FAILED: " + str(exc)[:240], file=sys.stderr)
        return 2
    finally:
        if client is not None:
            client.close()


if __name__ == "__main__":
    raise SystemExit(main())
