"""Identify the MR4U P10 ZNP TCP endpoint FROM the Home Assistant host.

Requires explicit private LAN IPv4 and per-radio socket port from SMLIGHT UI.
Sends only SYS_PING and SYS_VERSION to an otherwise idle, uncommissioned radio.
Never write radio NV, network parameters, Zigbee2MQTT configuration or HA state.
"""
from __future__ import annotations
import argparse
import importlib.util
import ipaddress
import json
from pathlib import Path
import shlex
import sys

HELPER = Path('C:/Workspace/repos/config/skills/home-assistant-readonly/ha_readonly.py')
REMOTE = r'''
import json,socket,sys,time
host,port=sys.argv[1],int(sys.argv[2])
def frame(cmd):
    data=bytes([0,0x21,cmd]); fcs=0
    for x in data: fcs ^= x
    return b'\xfe'+data+bytes([fcs])
def exact(sock,n):
    out=bytearray()
    while len(out)<n:
        piece=sock.recv(n-len(out))
        if not piece: raise OSError('socket closed before expected ZNP response')
        out.extend(piece)
    return bytes(out)
def transact(sock,cmd):
    sock.sendall(frame(cmd))
    end=time.monotonic()+4.0
    while time.monotonic()<end:
        if exact(sock,1)!=b'\xfe': continue
        head=exact(sock,3); count,sub,code=head
        if count>80: raise ValueError('Unexpected ZNP length')
        tail=exact(sock,count+1)
        checksum=0
        for x in head+tail: checksum ^= x
        if checksum: raise ValueError('Invalid ZNP frame checksum')
        if (sub,code)==(0x61,cmd): return tail[:-1]
    raise TimeoutError('No matching ZNP response')
try:
    with socket.create_connection((host,port),timeout=5) as sock:
        sock.settimeout(5)
        ping=transact(sock,1)
        version=transact(sock,2)
    if len(ping)!=2 or len(version) not in (9,10) or version[1]!=1:
        raise ValueError('Unexpected ZNP product, firmware or payload')
    print(json.dumps({'znp_ping':True,'product':version[1],
                      'revision':int.from_bytes(version[5:9],'little'),
                      'version':[version[2],version[3],version[4]],
                      'znp_capability_mask':int.from_bytes(ping,'little')}))
except Exception as error:
    print(json.dumps({'znp_ping':False,'error_type':type(error).__name__}))
    sys.exit(2)
'''


def check_address(host: str, port: int) -> None:
    addr = ipaddress.ip_address(host)
    if addr.version != 4 or not addr.is_private or addr.is_loopback or addr.is_link_local:
        raise ValueError('Only an explicit private LAN IPv4 address is accepted')
    if type(port) is not int or not 1 <= port <= 65535:
        raise ValueError('Invalid single-radio TCP port')


def run(host: str, port: int, expected_revision: int) -> dict:
    check_address(host, port)
    spec = importlib.util.spec_from_file_location('p10_ha', HELPER)
    if spec is None or spec.loader is None:
        raise RuntimeError('Canonical HA SSH helper unavailable')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    client = module.connect('ha')
    try:
        command = 'python3 -c ' + shlex.quote(REMOTE) + ' ' + shlex.quote(host) + ' ' + str(port)
        _, stdout, _ = client.exec_command(command, timeout=15)
        data = json.loads(stdout.read().decode('utf-8'))
        if stdout.channel.recv_exit_status() != 0 or data.get('znp_ping') is not True:
            raise RuntimeError('HA could not reach a valid ZNP radio at the supplied endpoint')
        if data.get('product') != 1 or data.get('revision') != expected_revision:
            raise RuntimeError('Target is not the expected MR4U P10 firmware revision')
        return {'host_reachable_from_ha': True, 'znp_radio_verified': True,
                'radio_revision': data['revision'], 'port': port,
                'network_state_restored': False, 'coordinator_ieee_preserved': False}
    finally:
        client.close()


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--host', required=True)
    p.add_argument('--port', required=True, type=int)
    p.add_argument('--expected-revision', default=20260310, type=int)
    args = p.parse_args(argv)
    try:
        print(json.dumps(run(args.host, args.port, args.expected_revision), sort_keys=True, indent=2))
        return 0
    except (OSError, RuntimeError, ValueError, KeyError, TypeError) as exc:
        print('P10_TARGET_ENDPOINT_ERROR: ' + str(exc)[:150], file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
