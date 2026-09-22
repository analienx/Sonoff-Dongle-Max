#!/usr/bin/env python3
"""Bounded multi-zone read-only ZCL samples via the existing Zigbee2MQTT owner.
Before chooses up to twelve gettable powered routers across >=4 rooms; after reuses
EXACTLY that sample. A fresh non-retained state is a response proxy, not an APS proof.
"""
import base64
import importlib.util
import json
from pathlib import Path
import shlex
import sys

HELPER = Path(r'C:\Workspace\repos\config\skills\home-assistant-readonly\ha_readonly.py')
spec = importlib.util.spec_from_file_location('ha_readonly', HELPER)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

JS = r'''const fs=require('fs'),yaml=require('js-yaml'),mqtt=require('mqtt'),crypto=require('crypto');
const cfg=yaml.load(fs.readFileSync('/config/zigbee2mqtt/configuration.yaml','utf8'))||{};
const base=cfg.mqtt?.base_topic||'zigbee2mqtt';
const fixed=JSON.parse(Buffer.from(process.argv[1]||'bnVsbA==','base64').toString('utf8'));
const ZONES=['Hall','Kitchen','LivingRoom','Workroom','Bathroom','Toilet','Entry','Balcony','Nursery','Corridor','Utility'];
const MAX=12, TIMEOUT=6500;
const client=mqtt.connect(cfg.mqtt.server,{username:cfg.mqtt.user||undefined,password:cfg.mqtt.password||undefined,
 reconnectPeriod:0,connectTimeout:4000,clean:true,clientId:'r60-multizone-'+crypto.randomBytes(5).toString('hex')});
let devices=null,active=null,errors=0,finished=false,begin=Date.now();
const globalTimeout=setTimeout(()=>finish({status:'global_timeout',results:[]}),125000);
function finish(r){if(finished)return;finished=true;clearTimeout(globalTimeout);client.end(true);
 console.log(JSON.stringify({...r,elapsed_ms:Date.now()-begin,route_error_messages:errors}));}
function gettable(es){return Array.isArray(es)&&es.some(e=>((e?.property==='state')&&((e.access&4)!==0))||gettable(e?.features));}
function zone(n){return ZONES.find(z=>n.startsWith(z))||null;}
function candidates(ds){return ds.filter(d=>d.type==='Router'&&d.supported!==false&&d.interview_completed!==false&&
 typeof d.friendly_name==='string'&&zone(d.friendly_name)&&!/^Bedroom/i.test(d.friendly_name)&&
 !/Breaker|MainMeter|Shutdown|Energy|Meter/i.test(d.friendly_name)&&gettable(d.definition?.exposes));}
function select(ds){const pool=candidates(ds),chosen=[],seen=new Set();
 for(let round=0;round<3;round++)for(const z of ZONES){
  const d=pool.find(d=>zone(d.friendly_name)===z&&!seen.has(d.friendly_name));
  if(d&&chosen.length<MAX){seen.add(d.friendly_name);chosen.push(d.friendly_name);}}
 return chosen;}
function read(name){return new Promise(resolve=>{
 let done=false,issued=Date.now(),topic=base+'/'+name;
 function close(x){if(done)return;done=true;clearTimeout(watch);active=null;resolve({name,...x});}
 const watch=setTimeout(()=>close({status:'no_verified_response',latency_ms:null}),TIMEOUT);
 active={topic,onState:(buf,packet)=>{if(packet.retain)return;
  try{const x=JSON.parse(buf.toString());if(Object.prototype.hasOwnProperty.call(x,'state'))
    close({status:'fresh_state',latency_ms:Date.now()-issued});}catch{}}};
 client.publish(topic+'/get',JSON.stringify({state:''}),{retain:false,qos:0},err=>{
   if(err)close({status:'mqtt_publish_error',latency_ms:null});});
});}
async function main(){if(!cfg.mqtt?.server)throw Error('no_mqtt_config');
 await new Promise((ok,no)=>{client.once('connect',ok);client.once('error',no);});
 await new Promise((ok,no)=>client.subscribe([base+'/bridge/devices',base+'/bridge/logging'],{qos:0},e=>e?no(e):ok()));
 for(let i=0;i<75&&!devices;i++)await new Promise(r=>setTimeout(r,100));
 if(!Array.isArray(devices))return finish({status:'device_inventory_unavailable',results:[]});
 const pool=new Set(candidates(devices).map(d=>d.friendly_name));
 const names=fixed===null?select(devices):fixed;
 if(!Array.isArray(names)||names.length<8||names.length>MAX||new Set(names).size!==names.length||
   names.some(n=>!pool.has(n))||new Set(names.map(zone)).size<4)
  return finish({status:'sample_validation_failed',results:[],eligible_count:pool.size});
 await new Promise((ok,no)=>client.subscribe(names.map(n=>base+'/'+n),{qos:0},e=>e?no(e):ok()));
 const results=[];
 for(const n of names){if(finished)return;results.push(await read(n));
  await new Promise(r=>setTimeout(r,350));}
 finish({status:'complete',names,results,eligible_count:pool.size,zone_count:new Set(names.map(zone)).size});
}
client.on('message',(topic,buf,packet)=>{
 if(topic===base+'/bridge/devices'){try{devices=JSON.parse(buf.toString());}catch{}return;}
 if(topic===base+'/bridge/logging'){
  try{if(String(JSON.parse(buf.toString()).message||'').includes('ROUTE_ERROR_'))errors++;}catch{}return;}
 if(active&&active.topic===topic)active.onState(buf,packet);
});
main().catch(()=>finish({status:'mqtt_or_runtime_error',results:[]}));'''

REMOTE = r'''import json,subprocess,sys
p=subprocess.run(['docker','ps','--filter','name=zigbee2mqtt','--format','{{.ID}}'],capture_output=True,text=True,timeout=6)
ids=[s.strip() for s in p.stdout.splitlines() if s.strip()]
if p.returncode or len(ids)!=1:
 print(json.dumps({'status':'owner_preflight_failed','owner_count':len(ids)}));sys.exit(0)
cid=ids[0]
def epoch():
 q=subprocess.run(['docker','inspect','-f','{{.State.StartedAt}}',cid],capture_output=True,text=True,timeout=6)
 return q.stdout.strip() if q.returncode==0 else None
before=epoch()
x=subprocess.run(['docker','exec',cid,'node','-e',sys.argv[1],sys.argv[2]],capture_output=True,text=True,timeout=135)
after=epoch()
try: result=json.loads(x.stdout.strip().splitlines()[-1])
except (ValueError,IndexError):result={'status':'probe_process_failed'}
result['same_owner_epoch']=before is not None and before==after
result['owner_epoch']=before
print(json.dumps(result))'''

def run(fixed=None):
    if fixed is not None and (not isinstance(fixed,list) or not 8<=len(fixed)<=12 or
                              any(not isinstance(x,str) or not x or len(x)>90 for x in fixed)):
        raise ValueError('invalid_frozen_target_list')
    encoded=base64.b64encode(json.dumps(fixed).encode()).decode()
    cli=module.connect('ha')
    try:
        cmd='python3 -c '+shlex.quote(REMOTE)+' '+shlex.quote(JS)+' '+shlex.quote(encoded)
        _,out,err=cli.exec_command(cmd,timeout=160)
        raw=out.read().decode('utf8','replace')
        if out.channel.recv_exit_status(): raise RuntimeError('remote_read_failed')
        result=json.loads(raw.strip().splitlines()[-1])
        if result.get('status')!='complete' or result.get('same_owner_epoch') is not True:
            raise RuntimeError('multizone_probe_incomplete:'+str(result.get('status')))
        if result.get('zone_count',0)<4 or len(result.get('results',[]))!=len(result.get('names',[])):
            raise RuntimeError('insufficient_verified_sample')
        return result
    finally: cli.close()

if __name__=='__main__':
    fixed=json.loads(base64.b64decode(sys.argv[1]).decode()) if len(sys.argv)>1 else None
    print(json.dumps(run(fixed),sort_keys=True))
