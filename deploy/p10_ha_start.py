"""Start Zigbee2MQTT exactly once after a verified two-layer cutover/rollback.

Inert by default. This is NOT an IEEE/NVRAM restore, physical radio isolation,
or network acceptance. Operator physically confirms the radio isolation first.
"""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import sys

from p10_data_bundle import addon_info, load_ha
from p10_ha_state import addon_quiescent
from p10_ha_apply import PHRASES, live_plan, ADDON

START_PHRASES={'target':'START_MR4U_AFTER_SONOFF_ISOLATION',
               'rollback':'RESTART_ORIGINAL_SONOFF_AFTER_MR4U_ISOLATION'}
NEEDED={'target':{'source-isolated','source-backup-preserved','effective-ieee-verified','exclusive-radio-client'},
        'rollback':{'target-isolated','original-sonoff-state-preserved'}}


def prestart(stage:Path,phase:str) -> dict:
    # After deploying target config, it is the *rollback* operation which would
    # now see the expected running YAML/options. Reverse this for SONOFF.
    to_apply = 'rollback' if phase=='target' else 'target'
    report=live_plan(stage,to_apply)
    ready=report['safe_to_apply_config']
    return {'phase':phase,'addon_stopped_and_both_config_layers_match':ready,
            'radio_physical_isolation_automatically_verified':False,
            'start_performed':False,'manual_radio_attestations_required':sorted(NEEDED[phase])}


def start(stage:Path,phase:str,approval:str,ack:list[str]) -> dict:
    if approval != START_PHRASES[phase]:
        raise ValueError('Exact phase-specific start approval phrase required')
    if not NEEDED[phase] <= set(ack):
        raise ValueError('Missing physical coordinator and network restore attestations')
    plan=prestart(stage,phase)
    if not plan['addon_stopped_and_both_config_layers_match']:
        raise RuntimeError('Current add-on or config does not match the staged coordinator')
    client=load_ha()
    try:
        addon_quiescent(client)  # Accept crashed error state only with exited container.
        _,out,_=client.exec_command('ha apps start '+ADDON+' --no-progress --raw-json',timeout=None)
        out.channel.settimeout(None)
        raw=out.read().decode('utf-8',errors='replace')
        if out.channel.recv_exit_status()!=0 or (raw.strip() and json.loads(raw).get('result')!='ok'):
            raise RuntimeError('Supervisor refused start; do not blindly retry')
        running=addon_info(client).get('state')=='started'
        if not running: raise RuntimeError('Add-on did not reach started state')
        return {'phase':phase,'addon_started':True,'application_message_delivery_verified':False,
                'coordinator_network_restore_verified_by_this_script':False,
                'next_step':'Inspect startup logs and run full private device/function acceptance'}
    finally:
        client.close()


def main(argv=None) -> int:
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--stage',required=True,type=Path)
    p.add_argument('--phase',required=True,choices=tuple(START_PHRASES))
    p.add_argument('--execute',action='store_true')
    p.add_argument('--approval',default='')
    p.add_argument('--ack',action='append',default=[],choices=tuple(set().union(*NEEDED.values())))
    a=p.parse_args(argv)
    try:
        result=start(a.stage,a.phase,a.approval,a.ack) if a.execute else prestart(a.stage,a.phase)
        print(json.dumps(result,sort_keys=True,indent=2))
        return 0
    except (OSError,RuntimeError,ValueError,KeyError,TypeError) as exc:
        print('P10_HA_START_ERROR: '+str(exc)[:180],file=sys.stderr)
        return 2


if __name__=='__main__':
    raise SystemExit(main())
