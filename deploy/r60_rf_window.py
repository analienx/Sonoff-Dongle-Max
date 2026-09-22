#!/usr/bin/env python3
"""Offline-only paired NCP neighbor/RF analysis. No HA access."""
import json
from collections import Counter
from pathlib import Path
from statistics import median


def load_private(snapshot):
    path=Path(snapshot['private_result_path'])
    if not path.is_file() or 'sonoff-private' not in path.parts:
        raise ValueError('missing_private_ncp_result')
    result=json.loads(path.read_text(encoding='utf-8'))
    if result.get('status')!='ok' or result.get('extension_absent_after') is not True:
        raise ValueError('ncp_snapshot_or_cleanup_failed')
    row=result.get('snapshot')
    if not isinstance(row,dict) or not isinstance(row.get('entries'),list):
        raise ValueError('missing_ncp_neighbor_rows')
    if row.get('count')!=len(row['entries']):
        raise ValueError('incomplete_neighbor_table')
    return row


def compare(first, second):
    a,b=load_private(first),load_private(second)
    def indexed(row):
        return {str(item['longId']).lower():item for item in row['entries'] if 'longId' in item}
    x,y=indexed(a),indexed(b)
    if len(x)!=len(a['entries']) or len(y)!=len(b['entries']):
        raise ValueError('duplicate_or_missing_neighbor_identity')
    common=x.keys()&y.keys()
    lqis=[z['averageLqi'] for z in b['entries']]
    return {'neighbor_count_first':len(x),'neighbor_count_second':len(y),
            'distinct_departed':len(x.keys()-y.keys()),'distinct_entered':len(y.keys()-x.keys()),
            'stable_neighbors':len(common),'changed_lqi':sum(x[k]['averageLqi']!=y[k]['averageLqi'] for k in common),
            'median_lqi_after':median(lqis) if lqis else None,
            'outbound_cost_zero_after':sum(z.get('outCost')==0 for z in b['entries']),
            'first_source_route_filled':a.get('source_route_filled'),
            'second_source_route_filled':b.get('source_route_filled')}


def fingerprint(cohort, ncp_pair=None):
    records=[r for r in cohort.get('results',[]) if r.get('status')!='excluded_by_design']
    counts=Counter((r.get('name','').split('Socket')[0].split('Bulb')[0],r.get('status')) for r in records)
    failed=[r['name'] for r in records if r.get('status') not in ('fresh_state','zcl_verified')]
    result={'attempts':len(records),'proxies':sum(r.get('status')=='fresh_state' for r in records),
            'verified_zcl':sum(r.get('status')=='zcl_verified' for r in records),
            'inconclusive_or_failed':failed,'zone_status':[{'zone':k[0],'status':k[1],'count':v} for k,v in sorted(counts.items())],
            'path_attribution':'not_collected; no first-hop assertion'}
    if ncp_pair is not None:result['neighbors']=compare(*ncp_pair)
    return result

def route_firsthop(row, nwk):
    """Best-effort cached source-route first hop; NOT an on-air path trace."""
    if not isinstance(nwk,int) or not 0<=nwk<=65535:
        return {'status':'no_current_network_address'}
    entries=row.get('source_route_entries')
    if not isinstance(entries,list) or row.get('source_route_entries_truncated'):
        return {'status':'source_routes_unavailable'}
    routes={x['index']:x for x in entries if isinstance(x,dict) and
            isinstance(x.get('index'),int) and isinstance(x.get('destination'),int)}
    matches=[x for x in entries if x.get('destination')==nwk]
    if len(matches)!=1:return {'status':'no_unique_cached_route'}
    route=matches[0];seen=set()
    while True:
        idx=route['index']
        if idx in seen:return {'status':'cached_route_cycle'}
        seen.add(idx);parent=route.get('closerIndex')
        if parent==255:
            hop=route['destination']
            neighbors={x.get('shortId') for x in row.get('entries',[])}
            return {'status':'cached_firsthop_in_neighbor_table' if hop in neighbors else 'cached_firsthop_not_neighbor',
                    'firsthop_short':hop,'cached_hops':len(seen)-1}
        if parent not in routes:return {'status':'invalid_closer_index'}
        route=routes[parent]

def failure_firsthops(zcl_result, snapshot):
    row=load_private(snapshot)
    grouped={}
    for d in zcl_result.get('devices',[]):
        address=d.get('network_address')
        resolved=route_firsthop(row,address)
        if resolved['status']!='cached_firsthop_in_neighbor_table':continue
        hop=resolved['firsthop_short']
        record=grouped.setdefault(hop,{'devices':[],'attempts':0,'verified':0})
        record['devices'].append(d['name']);record['attempts']+=d.get('attempts',0);record['verified']+=d.get('verified',0)
    return {'cached_firsthop_groups':list(grouped.values()),
            'attribution':'cached source-route table at snapshot time; paths may change; no direct transmission trace'}
