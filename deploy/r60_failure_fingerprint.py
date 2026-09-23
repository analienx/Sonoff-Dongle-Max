#!/usr/bin/env python3
"""Offline-only failure fingerprint; never infer a proven Zigbee hop from a cached route."""
import json,sys
from pathlib import Path
from r60_rf_window import failure_firsthops

def fingerprint(stage):
    if not stage.get('valid'):raise ValueError('invalid_sample')
    z=stage['zcl'];devices=z['devices'];ncp=stage['metrics']
    failed=[d for d in devices if d.get('verified',0)<d.get('attempts',0)]
    bad_zero=[d for d in devices if d.get('verified',0)==0]
    grouped=failure_firsthops(z,stage['first'])
    hops=[g for g in grouped['cached_firsthop_groups'] if g['verified']<g['attempts']]
    return {'zcl_attempts':z['attempts'],'verified_zcl':z['verified'],
            'devices_with_any_failure':[d['name'] for d in failed],
            'devices_without_verified_response':[d['name'] for d in bad_zero],
            'cached_firsthop_groups_with_failures':hops,
            'mac_failure_fraction':ncp['mac_failure_fraction'],
            'cca_failures_per_min':ncp['cca_failures_per_min'],
            'neighbor_changes_per_min':ncp['neighbor_changes_per_min'],
            'source_route_occupancy':stage['second'].get('source_route_filled'),
            'resource_failure_events':ncp['resource_failure_events'],
            'interpretation':'MAC/CCA/churn and cached first-hop are associations. An A/B result cannot distinguish USB3 emission from antenna position; short windows cannot prove whole-mesh reliability.'}
if __name__=='__main__':
    path=Path(sys.argv[1]);print(json.dumps(fingerprint(json.loads(path.read_text(encoding='utf8'))),indent=2))
