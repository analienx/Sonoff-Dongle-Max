#!/usr/bin/env python3
"""Local-only secondary classification of the ONE saved HA archive; no HA requests."""
import collections
import glob
import json
import re
import tarfile

path=glob.glob(r'C:\Workspace\.analienx\sonoff-private\r60_ha_one_pass_*.tar.gz')
if len(path)!=1:raise RuntimeError('Require exactly one prior capture')
# These are text categories, not unique transactions or independently verified device-command outcomes.
checks={'failed_to_send':re.compile(r'(?i)failed to send'),
        'failed_to_read':re.compile(r'(?i)failed to read'),
        'failed_to_write':re.compile(r'(?i)failed to write'),
        'failed_command':re.compile(r'(?i)command.{0,70}(?:failed|timeout|timed out)'),
        'no_ack':re.compile(r'(?i)(?:MAC_NO_ACK|DELIVERY_FAILED|(?:^|\W)NO_ACK(?:\W|$))'),
        'failed_to_other':re.compile(r'(?i)failed to'),
        'other_timeout':re.compile(r'(?i)(?:timeout|timed out)'),
        'owner_shutdown':re.compile(r'(?i)(?:stopping zigbee2mqtt|zigbee2mqtt stopped|shutting down|received SIGTERM|received SIGINT|stopping zigbee.herdsman|adapter disconnected|ncpneedsreset)'),
        'owner_fatal':re.compile(r'(?i)(?:unhandled rejection|uncaught exception|out of memory|fatal error|error while starting zigbee2mqtt)'),
        'ota_transfer':re.compile(r'(?i)(?:OTA updating|image block request|update progress|OTA update (?:completed|failed))')}
remove_private=re.compile(r'(?i)(?:0x)?[0-9a-f]{16}')
redact_sensitive=re.compile(r'(?i)(?:password|network.key|secret|token|mqtt.password)[^:]*[:=].*')
counts=collections.Counter();per_session=collections.defaultdict(collections.Counter);templates=collections.Counter();example={};transitions=[]
with tarfile.open(path[0],'r:gz') as archive:
 for file in sorted(m for m in archive if m.name.startswith('private/log/') and m.name.endswith('.log')):
  session=file.name.split('/')[2]
  for raw in archive.extractfile(file):
   line=raw.decode('utf-8','replace').strip()
   if not line:continue
   types=[key for key,rx in checks.items() if rx.search(line)]
   if not types:continue
   counts.update(types);per_session[session].update(types)
   if 'failed_to_send' in types or 'failed_to_read' in types or 'failed_to_write' in types or 'failed_command' in types or 'no_ack' in types:
    text=line.split('zh:')[-1]
    if redact_sensitive.search(text):continue
    text=remove_private.sub('[ID]',text)
    text=re.sub(r'\b\d{2,6}\b','[N]',text)
    text=re.sub(r'\"[^\"]{15,}\"','"[VALUE]"',text)
    shape=text[:145]
    templates[shape]+=1
    if shape not in example:example[shape]=line[:20]
   if ('owner_shutdown' in types or 'owner_fatal' in types) and len(transitions)<30:
    transitions.append({'session':session,'at':line[:21],'kind':'fatal' if 'owner_fatal' in types else 'shutdown'})
print('CATEGORY_COUNTS',json.dumps(counts,sort_keys=True))
print('SESSION_CATEGORIES',json.dumps(per_session,sort_keys=True))
print('TOP_FAILURE_TEMPLATES',json.dumps([{'sample_at':example[k],'count':v,'template':k} for k,v in templates.most_common(18)],ensure_ascii=False))
print('OWNER_TRANSITIONS',json.dumps(transitions))
