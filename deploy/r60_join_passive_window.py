#!/usr/bin/env python3
"""Issue #28: bounded read-only join-window Docker log capture; no NCP or MQTT operations."""
import datetime as dt
import importlib.util
import json
from pathlib import Path
import re
import shlex
import socket
import time

HELPER = Path(r'C:\Workspace\repos\config\skills\home-assistant-readonly\ha_readonly.py')
PRIVATE = Path(r'C:\Workspace\.analienx\sonoff-private\issues\28-neighbor-mechanisms')
DURATION = 600
LIMIT = 128 * 1024 * 1024

def run():
    PRIVATE.mkdir(parents=True, exist_ok=True)
    tag = dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    logfile = PRIVATE / ('r60_join_passive_' + tag + '.log')
    manifest = PRIVATE / ('r60_join_passive_' + tag + '.json')
    spec = importlib.util.spec_from_file_location('ha_readonly', HELPER)
    helper = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(helper)
    start = dt.datetime.now(dt.timezone.utc)
    client = helper.connect('ha')
    saved = 0
    blocks = 0
    reason = None
    try:
        command = "docker ps --filter name=zigbee2mqtt --format '{{.ID}}'"
        _, out, err = client.exec_command(command, timeout=15)
        owners = out.read().decode('utf8', 'replace').splitlines()
        if out.channel.recv_exit_status() or len(owners) != 1:
            raise RuntimeError('single_running_z2m_owner_unavailable')
        owner = owners[0].strip()
        if not re.fullmatch(r'[0-9a-f]{12,64}', owner):
            raise RuntimeError('bad_owner_container_id')
        since = (start - dt.timedelta(minutes=5)).strftime('%Y-%m-%dT%H:%M:%SZ')
        command = 'docker logs --follow --timestamps --since ' + shlex.quote(since) + ' ' + owner + ' 2>&1'
        _, stdout, _ = client.exec_command(command, timeout=30)
        channel = stdout.channel
        deadline = time.monotonic() + DURATION
        print(json.dumps({'status':'capturing','issue':28,'started_utc':start.isoformat(), 'private_log':str(logfile),'owner_short_id':owner}), flush=True)
        with logfile.open('xb') as target:
            while time.monotonic() < deadline:
                if channel.recv_ready():
                    block = channel.recv(65536)
                    if not block: reason = 'remote_log_stream_ended'; break
                    if saved + len(block) > LIMIT: reason = 'capture_size_limit'; break
                    target.write(block)
                    saved += len(block); blocks += 1
                elif channel.exit_status_ready(): reason = 'remote_log_stream_ended'; break
                else: time.sleep(.2)
        if reason is None: reason = 'duration_complete'
    except Exception as exc:
        reason = type(exc).__name__ + ':' + str(exc)
        raise
    finally:
        client.close()
        report = {'issue':28,'start_utc':start.isoformat(), 'end_utc':dt.datetime.now(dt.timezone.utc).isoformat(), 'reason':reason, 'bytes':saved,'blocks':blocks,'private_log':str(logfile),'log_exists':logfile.exists()}
        with manifest.open('x', encoding='utf8') as dest: json.dump(report,dest,indent=2)
        print(json.dumps(report),flush=True)

if __name__ == '__main__': run()
