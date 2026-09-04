/*
 * P009 acceptance: exact Z2M 2.14 active read-only 2x8 canary.
 * Reads MQTT credentials from local config and never prints them.
 */
"use strict";
const fs = require("node:fs");
const mqtt = require("/app/node_modules/.pnpm/mqtt@5.15.2/node_modules/mqtt");
const YAML = require("/app/node_modules/.pnpm/js-yaml@5.4.1/node_modules/js-yaml");
const config = YAML.load(fs.readFileSync("/config/zigbee2mqtt/configuration.yaml", "utf8"));
const base = (config.mqtt && config.mqtt.base_topic) || "zigbee2mqtt";
const targets = [
  {id: "WorkRoomLedMainDimmer", endpoint: 1, cluster: "genOnOff", attribute: "onOff"},
  {id: "WRSocketWindowRightR", endpoint: 1, cluster: "genOnOff", attribute: "onOff"},
  {id: "HALLSocketMain", endpoint: 1, cluster: "genOnOff", attribute: "onOff"},
  {id: "HallSocketBedroom", endpoint: 1, cluster: "genOnOff", attribute: "onOff"},
  {id: "KitchenSocketLeft", endpoint: 1, cluster: "genOnOff", attribute: "onOff"},
  {id: "BedroomSocketDoorL", endpoint: 1, cluster: "genOnOff", attribute: "onOff"},
  {id: "LivingRoomSocketTableLeft", endpoint: 1, cluster: "genOnOff", attribute: "onOff"},
  {id: "HallBreakerFA11", endpoint: 1, cluster: "genOnOff", attribute: "onOff"},
];
const RESP = `${base}/bridge/response/device/reporting/read`;
const REQ = `${base}/bridge/request/device/reporting/read`;
const client = mqtt.connect(config.mqtt.server, {username: config.mqtt?.user, password: config.mqtt?.password});
const results = [];
let round = 0;
let index = 0;
let waiter = null;
let finished = false;

function next() {
  if (finished) return;
  if (index >= targets.length) {
    round += 1;
    if (round >= 2) return finish();
    index = 0;
    return setTimeout(next, 3000);
  }
  const target = targets[index++];
  const transaction = `p009-canary-r${round}-i${index}-${Date.now()}`;
  const payload = {id: target.id, endpoint: target.endpoint, cluster: target.cluster, configs: [{attribute: target.attribute, direction: 0}], transaction};
  const t0 = Date.now();
  waiter = {transaction, target, t0, timer: setTimeout(() => {
    results.push({round, id: target.id, ok: false, ms: Date.now() - t0, error: "no correlated response in 12s"});
    waiter = null;
    next();
  }, 12000)};
  client.publish(REQ, JSON.stringify(payload), {qos: 1});
}

function finish() {
  if (finished) return;
  finished = true;
  const ok = results.filter((r) => r.ok).length;
  const times = results.filter((r) => r.ok).map((r) => r.ms).sort((a, b) => a - b);
  console.log(JSON.stringify({test: "P009 active 2x8", ok: ok >= 15, successes: ok, total: 16, p50_ms: times.length ? times[Math.floor(times.length / 2)] : null, max_ms: times.length ? times[times.length - 1] : null, results}, null, 2));
  client.end(true, {}, () => process.exit(ok >= 15 ? 0 : 2));
}

client.on("error", (e) => { console.error(`MQTT error: ${e.message}`); process.exit(1); });
client.on("connect", () => {
  client.subscribe(RESP, (err) => {
    if (err) { console.error(err.message); process.exit(1); }
    setTimeout(next, 1000);
  });
});
client.on("message", (topic, message) => {
  if (topic !== RESP || !waiter) return;
  let data;
  try { data = JSON.parse(message.toString()); } catch { return; }
  if (data.transaction !== waiter.transaction) return;
  clearTimeout(waiter.timer);
  const ok = data.status === "ok";
  results.push({round, id: waiter.target.id, ok, ms: Date.now() - waiter.t0, error: ok ? null : `status=${data.status} ${String(data.error || "").slice(0, 100)}`});
  waiter = null;
  setTimeout(next, 400);
});
setTimeout(() => { if (!finished) { console.error("GLOBAL TIMEOUT"); finish(); } }, 150000);
