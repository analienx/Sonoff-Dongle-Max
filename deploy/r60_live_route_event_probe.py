#!/usr/bin/env python3
"""One short non-disruptive live test: on natural MTO route error read affected router.

No route failures induced, no second serial owner, no map/pairing/restart/flash.
Never writes network configuration; broker auth remains inside existing Z2M container.
"""
import importlib.util
import json
from pathlib import Path
import shlex

HELPER = Path(r'C:\Workspace\repos\config\skills\home-assistant-readonly\ha_readonly.py')
spec = importlib.util.spec_from_file_location('ha_readonly', HELPER)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

JS = r'''const fs=require('fs'),yaml=require('js-yaml'),mqtt=require('mqtt'),crypto=require('crypto');
let cfg;try{cfg=yaml.load(fs.readFileSync('/config/zigbee2mqtt/configuration.yaml','utf8'));}catch{console.log(JSON.stringify({status:'config_unavailable'}));process.exit(0)}
if(!cfg?.mqtt?.server){console.log(JSON.stringify({status:'mqtt_config_unavailable'}));process.exit(0)}
const base=cfg.mqtt.base_topic||'zigbee2mqtt';
const client=mqtt.connect(cfg.mqtt.server,{username:cfg.mqtt.user||undefined,password:cfg.mqtt.password||undefined,
 clientId:'r60-route-'+crypto.randomBytes(4).toString('hex'),connectTimeout:4000,reconnectPeriod:0,clean:true});
const started=Date.now();let inventory=null,wait=null,answered=false,finished=false,requestSent=false;
let routeErrorsSeen=0,eligibleEvents=0,chosen=null,key=null,replyTimer=null;
function done(status){if(finished)return;finished=true;clearTimeout(wait);clearTimeout(replyTimer);client.end(true);
 console.log(JSON.stringify({status,route_errors_seen:routeErrorsSeen,eligible_router_events:eligibleEvents,
  target_friendly_name:chosen?.friendly_name||null,attribute:key,read_requests_sent:Number(requestSent),
  fresh_nonretained_state_reply:answered,elapsed_ms:Date.now()-started}));}
function canRead(device){let result=null;function visit(ex){if(!ex||typeof ex!=='object')return;
 if((ex.property==='state'||ex.property==='brightness')&&(ex.access&4))result ||= ex.property;
 for(const feature of ex.features||[])visit(feature);}
 for(const expose of device.definition?.exposes||[])visit(expose);return result;}
const kill=setTimeout(()=>done('no_eligible_route_error_within_45s'),45000);wait=kill;
client.on('error',()=>done('mqtt_error'));
client.on('connect',()=>client.subscribe([base+'/bridge/devices',base+'/bridge/logging',base+'/bridge/state'],{qos:0},err=>{if(err)done('subscribe_failed');}));
client.on('message',(topic,buffer,packet)=>{
 if(finished)return;
 if(topic===base+'/bridge/devices'){
  try{const parsed=JSON.parse(buffer.toString());if(Array.isArray(parsed))inventory=parsed;}catch{}return;}
 if(topic===base+'/bridge/state'){
  const raw=buffer.toString();let online=(raw==='online'||raw==='true');
  if(!online){try{const parsed=JSON.parse(raw);online=(parsed==='online'||parsed===true||parsed?.state==='online');}catch{}}
  if(!online)done('bridge_not_online');return;}
 if(chosen && topic===base+'/'+chosen.friendly_name && !packet.retain && requestSent){
  try{const state=JSON.parse(buffer.toString());if(Object.prototype.hasOwnProperty.call(state,key)){answered=true;done('fresh_reply_after_route_error');}}catch{}return;}
 if(topic!==base+'/bridge/logging'||chosen||!inventory)return;
 let message;try{message=String(JSON.parse(buffer.toString()).message||'');}catch{return;}
 const match=/ROUTE_ERROR_MANY_TO_ONE_ROUTE_FAILURE for ["']?(\d+)/.exec(message);
 if(!match)return;routeErrorsSeen++;
 const nwk=Number(match[1]);const dev=inventory.find(d=>d.network_address===nwk&&d.type==='Router'
  && typeof d.friendly_name==='string'&&!/^BedroomBulb[123]$/.test(d.friendly_name)&&!d.disabled);
 if(!dev)return;const prop=canRead(dev);if(!prop)return;
 eligibleEvents++;chosen=dev;key=prop;clearTimeout(wait);
 const target=base+'/'+dev.friendly_name;
 client.subscribe(target,{qos:0},err=>{
  if(err){done('target_subscribe_failed');return;}
  requestSent=true;client.publish(target+'/get',JSON.stringify({[key]:''}),{qos:0,retain:false},e=>{if(e)done('read_publish_failed');});
  replyTimer=setTimeout(()=>done('no_fresh_reply_after_route_error'),12000);
 });
});'''

REMOTE = r'''import json,subprocess,sys
p=subprocess.run(['docker','ps','--filter','name=zigbee2mqtt','--format','{{.ID}}'],capture_output=True,text=True,timeout=6)
ids=[s.strip() for s in p.stdout.splitlines() if s.strip()]
if p.returncode or len(ids)!=1:print(json.dumps({'status':'owner_preflight_failed','owner_count':len(ids)}));sys.exit(0)
cid=ids[0]
def epoch():
 r=subprocess.run(['docker','inspect','-f','{{.State.StartedAt}}',cid],capture_output=True,text=True,timeout=6)
 return r.stdout.strip() if r.returncode==0 else None
before=epoch();x=subprocess.run(['docker','exec',cid,'node','-e',sys.argv[1]],capture_output=True,text=True,timeout=65)
after=epoch()
try: result=json.loads(x.stdout.strip().splitlines()[-1])
except (ValueError,IndexError):result={'status':'probe_process_failed'}
result['same_owner_epoch']=before is not None and before==after
result['one_owner_preflight']=True
print(json.dumps(result))'''

client=module.connect('ha')
try:
    _,stdout,stderr=client.exec_command('python3 -c '+shlex.quote(REMOTE)+' '+shlex.quote(JS),timeout=77)
    output=stdout.read().decode('utf-8','replace')
    status=stdout.channel.recv_exit_status()
    if status:raise RuntimeError('Live event probe exited nonzero: '+str(status))
    print(output[:2600])
finally:
    client.close()
