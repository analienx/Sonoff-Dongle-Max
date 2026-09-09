/*
 * P009 acceptance: bounded Permit Join All test.
 * Default: up to 5 x 10-second windows, serial, no pairing, no retries.
 * In the all-success path this is exactly five trials. On the first hard
 * failure no further opening stimulus is scheduled; cleanup still runs.
 * Credentials are read locally and never printed.
 */
"use strict";
const fs = require("node:fs");
const mqtt = require("/app/node_modules/.pnpm/mqtt@5.15.2/node_modules/mqtt");
const YAML = require("/app/node_modules/.pnpm/js-yaml@5.4.1/node_modules/js-yaml");
const cfg = YAML.load(fs.readFileSync("/config/zigbee2mqtt/configuration.yaml", "utf8"));
const base = (cfg.mqtt && cfg.mqtt.base_topic) || "zigbee2mqtt";
const N_ALL = Number(process.env.NJ_ALL ?? 5);
const N_COORD = Number(process.env.NJ_COORD ?? 0);
const SECONDS = Number(process.env.NJ_SECONDS ?? 10);
if (!Number.isInteger(N_ALL) || N_ALL < 0 || N_ALL > 5) throw new Error("NJ_ALL must be 0..5");
if (!Number.isInteger(N_COORD) || N_COORD < 0 || N_COORD > 2) throw new Error("NJ_COORD must be 0..2");
if (!Number.isInteger(SECONDS) || SECONDS < 5 || SECONDS > 15) throw new Error("NJ_SECONDS must be 5..15");

const REQ = `${base}/bridge/request/permit_join`;
const RESP = `${base}/bridge/response/permit_join`;
const INFO = `${base}/bridge/info`;
const LOGGING = `${base}/bridge/logging`;
const client = mqtt.connect(cfg.mqtt.server, {
  username: cfg.mqtt?.user,
  password: cfg.mqtt?.password,
  reconnectPeriod: 1000,
});
const trials = [];
for (let i = 1; i <= N_ALL; i++) trials.push({kind: "all", device: undefined, ordinal: i});
for (let i = 1; i <= N_COORD; i++) trials.push({kind: "coord", device: "Coordinator", ordinal: i});
const results = [];
const events = [];
const malformed = [];
let lastInfo = null;
let started = false;
let reconnects = 0;
let initialConnectSeen = false;
let globalTimedOut = false;
let finished = false;
const deadline = Date.now() + 180000;

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
function remaining(maxMs) {
  return Math.max(1, Math.min(maxMs, deadline - Date.now()));
}
function addEvent(kind, message) {
  events.push({at: Date.now(), kind, message: String(message).slice(0, 500)});
  if (events.length > 800) events.shift();
}
const HARD = /SLStatus\.BUSY|status=BUSY|\bBUSY\b|ZIGBEE_MAX_MESSAGE_LIMIT_REACHED|MAX_MESSAGE_LIMIT_REACHED|NO_BUFFERS|MESSAGE_TOO_LONG|NCP.*reset|ASH.*(?:error|reset)|adapter.*disconnected|NETWORK_DOWN/i;
let emergencyCloseRequested = false;
function hardEvents(slice) {
  return slice.filter((e) => HARD.test(e.message));
}
function requestImmediateClose(reason) {
  if (emergencyCloseRequested || finished) return;
  emergencyCloseRequested = true;
  const transaction = `p009-emergency-close-${Date.now()}`;
  addEvent("emergency_close", `${reason} tx=${transaction}`);
  client.publish(REQ, JSON.stringify({time: 0, transaction}), {qos: 1}, (err) => {
    if (err) addEvent("emergency_close_publish_error", err.message);
  });
}

client.on("message", (topic, raw, packet) => {
  if (topic === INFO) {
    try {
      const v = JSON.parse(raw.toString());
      lastInfo = {permit_join: v.permit_join, permit_join_end: v.permit_join_end ?? null, at: Date.now(), retained: !!packet?.retain};
      addEvent("bridge_info", `permit_join=${String(v.permit_join)} permit_join_end=${String(v.permit_join_end ?? null)}`);
    } catch (e) {
      malformed.push({at: Date.now(), topic, error: e.message});
      addEvent("malformed", `${topic}: ${e.message}`);
    }
  } else if (topic === LOGGING) {
    try {
      const v = JSON.parse(raw.toString());
      const msg = String(v.message || "");
      if (/BUSY|MAX_MESSAGE_LIMIT_REACHED|NO_BUFFERS|MESSAGE_TOO_LONG|0xfffc|0xfffd|permit.?join|NETWORK_DOWN|ASH|reset|disconnected/i.test(msg)) {
        addEvent("z2m_log", `${v.level}: ${msg}`);
      }
      if (HARD.test(msg)) requestImmediateClose(`hard runtime event: ${msg.slice(0, 180)}`);
    } catch (e) {
      malformed.push({at: Date.now(), topic, error: e.message});
      addEvent("malformed", `${topic}: ${e.message}`);
    }
  }
});

function requestPermit(payload, transaction, timeoutMs = 10000) {
  return new Promise((resolve) => {
    let done = false;
    const finish = (value) => {
      if (done) return;
      done = true;
      clearTimeout(timer);
      client.off("message", handler);
      resolve(value);
    };
    const handler = (topic, raw) => {
      if (topic !== RESP) return;
      let v;
      try {
        v = JSON.parse(raw.toString());
      } catch (e) {
        malformed.push({at: Date.now(), topic, error: e.message});
        addEvent("malformed", `${topic}: ${e.message}`);
        return finish({status: null, error: `malformed response JSON: ${e.message}`, malformed: true});
      }
      if (v.transaction === transaction) finish(v);
    };
    const timer = setTimeout(() => finish(null), remaining(timeoutMs));
    client.on("message", handler);
    client.publish(REQ, JSON.stringify(payload), {qos: 1}, (err) => {
      if (err) finish({status: null, error: `publish error: ${err.message}`});
    });
  });
}

async function waitForFreshPermitFalse(notBefore, timeoutMs = 7000) {
  const until = Date.now() + remaining(timeoutMs);
  while (Date.now() < until) {
    if (lastInfo && lastInfo.at >= notBefore && lastInfo.permit_join === false && lastInfo.retained === false) return {...lastInfo};
    await sleep(150);
  }
  return null;
}

async function one(t) {
  const eventStart = events.length;
  const transaction = `p009-${t.kind}-${t.ordinal}-${Date.now()}`;
  const payload = {time: SECONDS, transaction};
  if (t.device) payload.device = t.device;
  const startedAt = Date.now();
  addEvent("trial_start", `${t.kind}#${t.ordinal} tx=${transaction}`);
  const response = await requestPermit(payload, transaction, 10000);
  const responseAt = Date.now();
  const expectedEnd = startedAt + SECONDS * 1000;
  const immediateHard = hardEvents(events.slice(eventStart)).length > 0;
  if (!immediateHard && Date.now() < expectedEnd + 1200) await sleep(remaining(expectedEnd + 1200 - Date.now()));
  const closureNotBefore = immediateHard ? startedAt : expectedEnd - 500;
  const permitAfter = await waitForFreshPermitFalse(closureNotBefore, 7000);
  const evidence = events.slice(eventStart);
  const hard = hardEvents(evidence);
  const pressure = hard.filter((e) => /BUSY|MAX_MESSAGE_LIMIT_REACHED|NO_BUFFERS|MESSAGE_TOO_LONG/i.test(e.message));
  const statusOk = response?.status === "ok";
  const freshClosed = permitAfter?.permit_join === false && permitAfter?.retained === false;
  const ok = statusOk && hard.length === 0 && freshClosed && malformed.length === 0;
  const rec = {
    kind: t.kind,
    ordinal: t.ordinal,
    transaction,
    ok,
    status: response?.status ?? null,
    error: response?.error ? String(response.error).slice(0, 220) : response ? null : "no correlated permit_join response",
    response_ms: response ? responseAt - startedAt : null,
    fresh_permit_false: freshClosed,
    permit_after: permitAfter,
    pressure,
    hard,
    evidence,
  };
  results.push(rec);
  addEvent("trial_result", `${t.kind}#${t.ordinal} ok=${ok}`);
  return rec;
}

async function cleanup() {
  const transaction = `p009-close-${Date.now()}`;
  const startedAt = Date.now();
  addEvent("cleanup_start", `tx=${transaction}`);
  const response = await requestPermit({time: 0, transaction}, transaction, 10000);
  const closed = await waitForFreshPermitFalse(startedAt, 7000);
  const ok = response?.status === "ok" && closed?.permit_join === false;
  addEvent("cleanup_result", `ok=${ok} status=${String(response?.status ?? null)} permit=${String(closed?.permit_join ?? null)}`);
  return {
    ok,
    transaction,
    status: response?.status ?? null,
    error: response?.error ? String(response.error).slice(0, 220) : response ? null : "no correlated cleanup response",
    fresh_permit_false: closed?.permit_join === false,
    observed: closed,
  };
}

async function main() {
  let hardStop = null;
  let cleanupResult = null;
  try {
    for (const t of trials) {
      if (Date.now() >= deadline) {
        globalTimedOut = true;
        hardStop = "global deadline reached before next trial";
        break;
      }
      const rec = await one(t);
      if (!rec.ok) {
        hardStop = `first failed trial ${t.kind}#${t.ordinal}`;
        break;
      }
      await sleep(3000);
    }
  } catch (e) {
    hardStop = `exception: ${e.stack || e}`;
  } finally {
    try {
      cleanupResult = await cleanup();
      if (!cleanupResult.ok && !hardStop) hardStop = "final cleanup could not prove permit_join=false";
    } catch (e) {
      cleanupResult = {ok: false, error: String(e.stack || e).slice(0, 500)};
      if (!hardStop) hardStop = "cleanup exception";
    }
  }
  const allCompleted = results.length === trials.length;
  const allPassed = allCompleted && results.every((r) => r.ok);
  const pass = allPassed && cleanupResult?.ok === true && !hardStop && !globalTimedOut && malformed.length === 0;
  const report = {
    test: "P009 permit join",
    ok: pass,
    requested: {all: N_ALL, coord: N_COORD},
    attempted: results.length,
    seconds: SECONDS,
    fail_fast: true,
    hard_stop: hardStop,
    global_timeout: globalTimedOut,
    reconnects,
    malformed,
    cleanup: cleanupResult,
    final_permit: cleanupResult?.observed?.permit_join ?? lastInfo?.permit_join ?? null,
    results,
    event_log: events,
  };
  console.log(JSON.stringify(report, null, 2));
  finished = true;
  client.end(true, {}, () => process.exit(0));
}

client.on("connect", () => {
  if (initialConnectSeen) reconnects += 1;
  initialConnectSeen = true;
  if (started) return;
  client.subscribe([RESP, INFO, LOGGING], {qos: 1}, (err) => {
    if (err) {
      console.log(JSON.stringify({test: "P009 permit join", ok: false, hard_stop: `subscribe error: ${err.message}`, results: [], cleanup: null}, null, 2));
      return client.end(true, {}, () => process.exit(0));
    }
    if (started) return;
    started = true;
    setTimeout(() => main().catch((e) => {
      console.log(JSON.stringify({test: "P009 permit join", ok: false, hard_stop: String(e.stack || e), results, event_log: events}, null, 2));
      client.end(true, {}, () => process.exit(0));
    }), 1200);
  });
});
client.on("error", (e) => {
  addEvent("mqtt_error", e.message);
});
setTimeout(() => {
  if (!finished) {
    globalTimedOut = true;
    addEvent("global_timeout", "180s deadline reached");
    requestImmediateClose("global deadline reached");
    if (!started) {
      finished = true;
      console.log(JSON.stringify({test: "P009 permit join", ok: false, hard_stop: "MQTT connect/subscribe did not start before 180s deadline", global_timeout: true, results: [], cleanup: null, event_log: events}, null, 2));
      client.end(true, {}, () => process.exit(0));
    }
  }
}, 180000);
setTimeout(() => {
  if (!finished) {
    finished = true;
    addEvent("forced_exit", "195s absolute process bound reached after best-effort cleanup window");
    console.log(JSON.stringify({test: "P009 permit join", ok: false, hard_stop: "absolute process deadline", global_timeout: true, results, event_log: events}, null, 2));
    client.end(true, {}, () => process.exit(2));
  }
}, 195000);
