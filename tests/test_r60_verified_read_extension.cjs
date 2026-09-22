'use strict';
const test=require('node:test'), assert=require('node:assert/strict');
const Probe=require('../runtime/r60_verified_read_extension.cjs');
const NAMES=['HallRouterOne','KitchenRouterOne','LivingRoomRouterOne','WorkroomRouterOne','BathroomRouterOne','HallRouterTwo','KitchenRouterTwo','LivingRoomRouterTwo','WorkroomRouterTwo','KitchenRouterThree','LivingRoomRouterThree'];
function harness(){
 const published=[], calls=[], bus={onMQTTMessage(_owner,handler){this.handler=handler},removeListeners(){this.handler=null}};
 const zigbee={zhController:{adapter:{}},resolveEntity(name){return {zh:{type:'Router',endpoints:[{
   supportsInputCluster:cluster=>cluster==='genOnOff',
   read:async(cluster,attrs)=>{calls.push([name,cluster,attrs]);return {onOff:true}}
 }]}}}};
 const mqtt={async publish(topic,message){published.push({topic,...JSON.parse(message)})}};
 const p=new Probe(zigbee,mqtt,null,null,bus,null,null,null,{get:()=>({mqtt:{base_topic:'zigbee2mqtt'}})});
 return {p,bus,published,calls};
}
test('invalid cohort never issues a ZCL read',async()=>{
 const h=harness();await h.p.start();await h.bus.handler({topic:'zigbee2mqtt/bridge/request/r60_zcl_read',
  message:JSON.stringify({action:'verify',transaction:'t1',names:['HallRouterOne','BedroomBulb1'],repeats:3})});
 assert.equal(h.published[0].status,'error');assert.equal(h.calls.length,0);
});
test('33 actual resolved endpoint.read responses, no state-MQTT correlation',async()=>{
 const h=harness();await h.p.start();await h.bus.handler({topic:'zigbee2mqtt/bridge/request/r60_zcl_read',
  message:JSON.stringify({action:'verify',transaction:'valid1',names:NAMES,repeats:3})});
 assert.equal(h.calls.length,33);assert.equal(h.published[0].status,'ok');
 assert.equal(h.published[0].data.results.length,33);
 assert.ok(h.published[0].data.results.every(r=>r.status==='zcl_verified'));
 assert.ok(h.calls.every(c=>c[1]==='genOnOff'&&JSON.stringify(c[2])==='["onOff"]'));
});
