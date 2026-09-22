'use strict';
/** Fixed, read-only owner-local ZCL probe; no commands, pairing, reconfiguration or second serial owner. */
const REQUEST='/bridge/request/r60_zcl_read', RESPONSE='bridge/response/r60_zcl_read';
const allowedName=n=>typeof n==='string'&&/^(Hall|Kitchen|LivingRoom|Workroom|Bathroom|Toilet|Entry|Balcony|Nursery|Corridor|Utility)[A-Za-z0-9_]{2,70}$/.test(n)&&
 !/Bedroom|Circle|Workroom.*(?:Left|Right).*Dimmer|Workroom.*Dimmer.*(?:Left|Right)/i.test(n);
const MAX_ATTEMPTS=3, MIN_SPACING_MS=350;
const pause=ms=>new Promise(resolve=>setTimeout(resolve,ms));
module.exports=class R60VerifiedReadExtension {
 constructor(zigbee,mqtt,_state,_publish,eventBus,_toggle,_restart,_add,settings){
  this.zigbee=zigbee;this.mqtt=mqtt;this.eventBus=eventBus;this.base=settings?.get?.()?.mqtt?.base_topic||'zigbee2mqtt';
  this.busy=false;this.stopped=false;this.lastRun=0;this.handler=this.onMQTTMessage.bind(this);
 }
 async start(){this.stopped=false;this.eventBus.onMQTTMessage(this,this.handler);}
 async stop(){this.stopped=true;this.eventBus.removeListeners(this);}
 async onMQTTMessage(event){
  if(event.topic!==this.base+REQUEST||this.stopped)return;
  let transaction=null;
  try{
   if(typeof event.message!=='string'||event.message.length>1024)throw Error('bad_request');
   const q=JSON.parse(event.message);transaction=q?.transaction;
   if(!q||q.action!=='verify'||! /^[A-Za-z0-9_-]{1,32}$/.test(transaction||'')||
    !Array.isArray(q.names)||q.names.length<8||q.names.length>12||
    new Set(q.names).size!==q.names.length||q.names.some(n=>!allowedName(n))||
    q.repeats!==3||Object.keys(q).some(k=>!['action','transaction','names','repeats'].includes(k)))throw Error('bad_request');
   if(this.busy||Date.now()-this.lastRun<600000)throw Error('busy_or_cooldown');
   if(!this.zigbee?.zhController?.adapter||typeof this.zigbee.resolveEntity!=='function')throw Error('unsupported_owner');
   this.busy=true;this.lastRun=Date.now();let results=[];
   try {for(let round=0;round<q.repeats;round++)for(const name of q.names){
     if(this.stopped)throw Error('stopped');
     const d=this.zigbee.resolveEntity(name);const zh=d?.zh;
     if(!zh||zh.type!=='Router'||!Array.isArray(zh.endpoints)){
       results.push({name,round,status:'unavailable_or_not_router'});continue;
     }
     const ep=zh.endpoints.find(e=>typeof e.supportsInputCluster==='function'&&e.supportsInputCluster('genOnOff'));
     if(!ep||typeof ep.read!=='function'){
       results.push({name,round,network_address:zh.networkAddress,status:'unsupported_genOnOff_read'});continue;
     }
     const started=Date.now();
     try {const answer=await ep.read('genOnOff',['onOff']);
       results.push({name,round,network_address:zh.networkAddress,status:answer&&Object.prototype.hasOwnProperty.call(answer,'onOff')?'zcl_verified':'zcl_empty_response',
         latency_ms:Date.now()-started});
     }catch(err){results.push({name,round,network_address:zh.networkAddress,status:'zcl_read_failed',latency_ms:Date.now()-started,
       reason:/timeout|timed out/i.test(String(err?.message||''))?'timeout':'read_error'});}
     await pause(MIN_SPACING_MS);
   }}finally{this.busy=false;}
   if(!this.stopped)await this.mqtt.publish(RESPONSE,JSON.stringify({transaction,status:'ok',data:{results,names:q.names,repeats:q.repeats}}));
  }catch(err){const reasons=['bad_request','busy_or_cooldown','unsupported_owner','stopped'];
   if(!this.stopped)await this.mqtt.publish(RESPONSE,JSON.stringify({transaction,status:'error',error:reasons.includes(err?.message)?err.message:'probe_failed'}));}
 }
};
