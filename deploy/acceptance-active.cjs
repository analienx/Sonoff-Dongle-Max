/*
 * P009 acceptance: exact Z2M 2.14 active read-only 2x8 canary.
 * Reads MQTT credentials from local config and never prints them.
 *
 * Contract:
 * - exactly 16 unique scheduled transactions must complete;
 * - >=15 may succeed, but an incomplete/global-timeout run always fails;
 * - MQTT reconnect must never schedule a second stimulus stream;
 * - malformed response evidence is preserved and fails the correlated trial;
 * - script prints one JSON result even on operational failure so the supervisor
 *   can persist partial evidence before deciding STOPPED.
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
const EXPECTED = targets.length * 2;
const client = mqtt.connect(config.mqtt.server, {
  username: config.mqtt?.user,
  password: config.mqtt?.password,
  reconnectPeriod: 1000,
});
const results = [];
const scheduled = new Set();
let round = 0;
let index = 0;
let waiter = null;
let finished = false;
let started = false;
let globalTimedOut = false;
let malformedResponses = 0;
let reconnects = 0;
let initialConnectSeen = false;

function recordCurrentFailure(error) {
  if (!waiter) return;
  clearTimeout(waiter.timer);
  results.push({
    trial: waiter.trial,
    round: waiter.round,
    id: waiter.target.id,
    ok: false,
    ms: Date.now() - waiter.t0,
    error,
  });
  waiter = null;
  setTimeout(next, 400);
}

function next() {
  if (finished || waiter) return;
  if (index >= targets.length) {
    round += 1;
    if (round >= 2) return finish("completed");
    index = 0;
    return setTimeout(next, 3000);
  }
  const target = targets[index];
  const trial = `r${round}-i${index}`;
  index += 1;
  if (scheduled.has(trial)) {
    return finish(`duplicate scheduling detected for ${trial}`);
  }
  scheduled.add(trial);
  const transaction = `p009-canary-${trial}-${Date.now()}`;
  const payload = {
    id: target.id,
    endpoint: target.endpoint,
    cluster: target.cluster,
    configs: [{attribute: target.attribute, direction: 0}],
    transaction,
  };
  const t0 = Date.now();
  waiter = {
    trial,
    round,
    transaction,
    target,
    t0,
    timer: setTimeout(() => recordCurrentFailure("no correlated response in 12s"), 12000),
  };
  client.publish(REQ, JSON.stringify(payload), {qos: 1}, (err) => {
    if (err && waiter?.transaction === transaction) recordCurrentFailure(`publish error: ${err.message}`);
  });
}

function finish(reason) {
  if (finished) return;
  finished = true;
  if (waiter) {
    clearTimeout(waiter.timer);
    results.push({
      trial: waiter.trial,
      round: waiter.round,
      id: waiter.target.id,
      ok: false,
      ms: Date.now() - waiter.t0,
      error: `run terminated while trial pending: ${reason}`,
    });
    waiter = null;
  }
  const successes = results.filter((r) => r.ok).length;
  const uniqueResults = new Set(results.map((r) => r.trial));
  const completedExactly = results.length === EXPECTED && uniqueResults.size === EXPECTED && scheduled.size === EXPECTED;
  const pass = completedExactly && successes >= 15 && !globalTimedOut && malformedResponses === 0;
  const times = results.filter((r) => r.ok).map((r) => r.ms).sort((a, b) => a - b);
  const report = {
    test: "P009 active 2x8",
    ok: pass,
    expected: EXPECTED,
    completed: results.length,
    unique_completed: uniqueResults.size,
    scheduled: scheduled.size,
    successes,
    global_timeout: globalTimedOut,
    malformed_responses: malformedResponses,
    reconnects,
    finish_reason: reason,
    p50_ms: times.length ? times[Math.floor(times.length / 2)] : null,
    max_ms: times.length ? times[times.length - 1] : null,
    results,
  };
  console.log(JSON.stringify(report, null, 2));
  client.end(true, {}, () => process.exit(0));
}

client.on("error", (e) => {
  if (!finished) finish(`MQTT error: ${e.message}`);
});
client.on("connect", () => {
  if (initialConnectSeen) reconnects += 1;
  initialConnectSeen = true;
  if (started) return;
  client.subscribe(RESP, {qos: 1}, (err) => {
    if (err) return finish(`subscribe error: ${err.message}`);
    if (started) return;
    started = true;
    setTimeout(next, 1000);
  });
});
client.on("message", (topic, message) => {
  if (topic !== RESP || !waiter || finished) return;
  let data;
  try {
    data = JSON.parse(message.toString());
  } catch (e) {
    malformedResponses += 1;
    return recordCurrentFailure(`malformed JSON on response topic: ${e.message}`);
  }
  if (data.transaction !== waiter.transaction) return;
  clearTimeout(waiter.timer);
  const current = waiter;
  waiter = null;
  const ok = data.status === "ok";
  results.push({
    trial: current.trial,
    round: current.round,
    id: current.target.id,
    ok,
    ms: Date.now() - current.t0,
    error: ok ? null : `status=${data.status} ${String(data.error || "").slice(0, 180)}`,
  });
  setTimeout(next, 400);
});
setTimeout(() => {
  if (!finished) {
    globalTimedOut = true;
    finish("global timeout at 150s");
  }
}, 150000);
