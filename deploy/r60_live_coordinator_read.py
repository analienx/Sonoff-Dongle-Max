#!/usr/bin/env python3
"""One bounded live ZCL read on HallBulb1 via existing Z2M; no second serial owner.

Uses canonical host-key-verified SSH, the installed Zigbee2MQTT MQTT client,
reads broker auth inside the container without displaying or passing secrets,
and prints only sanitized read outcome. No HA config writes, map, pairing or flash.
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
let cfg;
try{cfg=yaml.load(fs.readFileSync('/config/zigbee2mqtt/configuration.yaml','utf8'));}catch{console.log(JSON.stringify({status:'config_unavailable'}));process.exit(0)}
if(!cfg?.mqtt?.server){console.log(JSON.stringify({status:'mqtt_config_unavailable'}));process.exit(0)}
const base=cfg.mqtt.base_topic||'zigbee2mqtt', target=base+'/HallBulb1';
const client=mqtt.connect(cfg.mqtt.server,{username:cfg.mqtt.user||undefined,password:cfg.mqtt.password||undefined,
 clientId:'r60-live-read-'+crypto.randomBytes(4).toString('hex'),connectTimeout:4000,reconnectPeriod:0,clean:true});
let sent=0,fresh=false,firstMs=null,routeErrors=0,targetErrors=0,started=Date.now(),finished=false;
function done(status){if(finished)return;finished=true;clearTimeout(kill);client.end(true);
 console.log(JSON.stringify({status,requests_sent:sent,fresh_nonretained_brightness_response:fresh,first_response_ms:firstMs,
  route_error_log_messages:routeErrors,target_error_log_messages:targetErrors,elapsed_ms:Date.now()-started}));}
const kill=setTimeout(()=>done('bounded_timeout'),28000);
client.on('error',()=>done('mqtt_error'));
client.on('message',(topic,buffer,packet)=>{
 if(topic===target && !packet.retain && sent){try{const state=JSON.parse(buffer.toString());
 if(Object.prototype.hasOwnProperty.call(state,'brightness')){fresh=true;firstMs ??= Date.now()-started;done('fresh_state_received');}}
 catch{}}
 if(topic===base+'/bridge/logging'){
 try{const obj=JSON.parse(buffer.toString()),text=String(obj.message||'');
 if(text.includes('ROUTE_ERROR_'))routeErrors++;
 if(text.includes('HallBulb1') && /failed|error|timed out/i.test(text))targetErrors++;}catch{}}
});
client.on('connect',()=>client.subscribe([target,base+'/bridge/logging'],{qos:0},err=>{
 if(err){done('subscribe_failed');return;}
 function request(){if(finished)return;sent++;client.publish(target+'/get',JSON.stringify({brightness:''}),{qos:0,retain:false},e=>{
 if(e)done('publish_failed');});}
 request();setTimeout(()=>{if(!finished)request();},12000);
}));'''

REMOTE = r'''import json,subprocess,sys
p=subprocess.run(['docker','ps','--filter','name=zigbee2mqtt','--format','{{.ID}}'],capture_output=True,text=True,timeout=6)
ids=[s.strip() for s in p.stdout.splitlines() if s.strip()]
if p.returncode or len(ids)!=1:
 print(json.dumps({'status':'owner_preflight_failed','owner_count':len(ids)}));sys.exit(0)
cid=ids[0]
def epoch():
 r=subprocess.run(['docker','inspect','-f','{{.State.StartedAt}}',cid],capture_output=True,text=True,timeout=6)
 return r.stdout.strip() if r.returncode==0 else None
before=epoch()
x=subprocess.run(['docker','exec',cid,'node','-e',sys.argv[1]],capture_output=True,text=True,timeout=33)
after=epoch()
try: result=json.loads(x.stdout.strip().splitlines()[-1])
except (ValueError,IndexError):result={'status':'probe_process_failed'}
result['same_owner_epoch']=before is not None and before==after
result['owner_running_since_utc']=before
result['one_owner_preflight']=True
print(json.dumps(result))'''

client = module.connect('ha')
try:
    command = 'python3 -c '+shlex.quote(REMOTE)+' '+shlex.quote(JS)
    _, stdout, stderr = client.exec_command(command, timeout=45)
    result = stdout.read().decode('utf-8','replace')
    code = stdout.channel.recv_exit_status()
    if code: raise RuntimeError('Live probe did not finish cleanly (status '+str(code)+')')
    print(result[:3000])
finally:
    client.close()
