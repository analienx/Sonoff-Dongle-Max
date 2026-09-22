#!/usr/bin/env python3
"""Offline-only narrow log comparison; does not issue HA commands or change TX."""
import collections
import glob
import json
import re
import tarfile

paths=glob.glob(r'C:\Workspace\.analienx\sonoff-private\r60_ha_one_pass_*.tar.gz')
if len(paths)!=1:raise RuntimeError('Expected exactly one local archive')
# Prague log timestamps. 5dBm period is independently documented in #18 RF experiment.
# 8dBm in second window is inferred from later one-pass configuration snapshot;
# do not claim an authenticated effective NCP TX readback at the window's start.
windows={'5dbm_0720_0800':('2026-09-22 07:20:00','2026-09-22 08:00:00'),
         'later_0820_0900':('2026-09-22 08:20:00','2026-09-22 09:00:00')}
rx_timestamp=re.compile(r'^\[(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d)\]')
rx_route=re.compile(r'ROUTE_ERROR_([A-Z_]+) for')
rx_ping=re.compile(r"Failed to ping '([^']+)'")
rx_set=re.compile(r"(?i)(?:failed to publish.{0,110}'set'|publish 'set'.{0,140}fail)")
rx_error=re.compile(r'^\[.{19}\] error:')
summary={key:collections.Counter() for key in windows}
pings={key:collections.Counter() for key in windows}
set_samples={key:[] for key in windows}
with tarfile.open(paths[0],'r:gz') as archive:
 for member in archive:
  if not member.name.startswith('private/log/') or not member.name.endswith('.log'):continue
  for raw in archive.extractfile(member):
   line=raw.decode('utf-8','replace').strip()
   stamp=rx_timestamp.match(line)
   if not stamp:continue
   ts=stamp.group(1)
   for name,(start,end) in windows.items():
    if not start<=ts<end:continue
    c=summary[name]
    c['log_lines']+=1
    m=rx_route.search(line)
    if m:c['route_'+m.group(1)]+=1
    if rx_error.search(line):c['error_level_lines']+=1
    ping=rx_ping.search(line)
    if ping:
     device=ping.group(1)
     if device.startswith('BedroomBulb'):c['intentionally_unpowered_bulb_pings']+=1
     else:c['other_failed_pings']+=1;pings[name][device]+=1
    if rx_set.search(line):
     c['failed_publish_set_text_lines']+=1
     if len(set_samples[name])<5:
      # Only the timestamp and a fixed semantic marker; never disclose raw payload/IEEE.
      set_samples[name].append(ts)
result={'windows':{name:{'counts':dict(summary[name]),'failed_ping_devices':pings[name].most_common(8),
                         'set_failure_times':set_samples[name]} for name in windows},
        'limitations':['Adjacent 40-min windows are not randomized/matched traffic tests and start in different owner epochs.',
                       'Route errors and publish failures are log lines, not independent end-to-end command attempts.',
                       'Later-period 8 dBm applies to captured configuration; its effective NCP TX at start was not independently read back.']}
print(json.dumps(result,indent=2))
