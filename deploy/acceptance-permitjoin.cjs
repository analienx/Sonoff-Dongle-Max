/*
 * P009 acceptance: bounded Permit Join All test.
 * Default: exactly 5 x 10-second windows, serial, no pairing, no retries.
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
const client = mqtt.connect(cfg.mqtt.server, {username: cfg.mqtt?.user, password: cfg.mqtt?.password});
const trials = [];
for (let i = 1; i <= N_ALL; i++) trials.push({kind: "all", device: undefined, transaction: `p009-all-${i}-${Date.now()}`});
for (let i = 1; i <= N_COORD; i++) trials.push({kind: "coord", device: "Coordinator", transaction: `p009-coord-${i}-${Date.now()}`});
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
let lastInfo = null;
let lines = [];
const results = [];

client.on("message", (topic, raw) => {
  if (topic === INFO) {
    try {
      const v = JSON.parse(raw.toString());
      lastInfo = {permit_join: v.permit_join, permit_join_end: v.permit_join_end ?? null, at: Date.now()};
    } catch {}
  } else if (topic === LOGGING) {
    try {
      const v = JSON.parse(raw.toString());
      const msg = String(v.message || "");
      if (/BUSY|MAX_MESSAGE_LIMIT_REACHED|NO_BUFFERS|MESSAGE_TOO_LONG|0xfffc|0xfffd|permit.?join/i.test(msg)) lines.push(`${v.level}: ${msg.slice(0, 350)}`);
    } catch {}
  }
});

async function one(t) {
  lines = [];
  const payload = {time: SECONDS, transaction: t.transaction};
  if (t.device) payload.device = t.device;
  const started = Date.now();
  const response = await new Promise((resolve, reject) => {
    const handler = (topic, raw) => {
      if (topic !== RESP) return;
      try {
        const v = JSON.parse(raw.toString());
        if (v.transaction === t.transaction) { client.off("message", handler); resolve(v); }
      } catch {}
    };
    client.on("message", handler);
    setTimeout(() => { client.off("message", handler); resolve(null); }, 10000);
    client.publish(REQ, JSON.stringify(payload), {qos: 0}, (err) => { if (err) reject(err); });
  });
  const responseAt = Date.now();
  await sleep(Math.max(0, SECONDS * 1000 + 2500 - (responseAt - started)));
  const busy = lines.filter((x) => /BUSY|MAX_MESSAGE_LIMIT_REACHED|NO_BUFFERS|MESSAGE_TOO_LONG/i.test(x));
  results.push({kind: t.kind, transaction: t.transaction, status: response?.status ?? null, error: response?.error ? String(response.error).slice(0, 180) : null, response_ms: response ? responseAt - started : null, busy, permit_after: lastInfo?.permit_join ?? null, evidence: lines});
  await sleep(3000);
}

async function main() {
  for (const t of trials) await one(t);
  client.publish(REQ, JSON.stringify({time: 0, transaction: `p009-close-${Date.now()}`}), {qos: 0});
  await sleep(3000);
  const finalPermit = lastInfo?.permit_join ?? null;
  const pass = results.length === trials.length && results.every((r) => r.status === "ok" && r.busy.length === 0) && finalPermit === false;
  console.log(JSON.stringify({test: "P009 permit join", ok: pass, counts: {all: N_ALL, coord: N_COORD}, seconds: SECONDS, final_permit: finalPermit, results}, null, 2));
  client.end(true, {}, () => process.exit(pass ? 0 : 2));
}
client.on("connect", () => {
  client.subscribe([RESP, INFO, LOGGING], (err) => {
    if (err) { console.error(err.message); process.exit(1); }
    setTimeout(() => main().catch((e) => { console.error(e.stack || e); process.exit(1); }), 1200);
  });
});
client.on("error", (e) => { console.error(`MQTT error: ${e.message}`); process.exit(1); });
setTimeout(() => { console.error("GLOBAL TIMEOUT"); process.exit(1); }, 180000);
