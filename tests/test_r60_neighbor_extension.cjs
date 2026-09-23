'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const Probe = require('../runtime/r60_neighbor_extension.cjs');

function fixture({count = 2, queued = 0, capacity = 254, filled = 2, entry = async i => [0, {shortId: i + 2, longId: `mock_${i}`, averageLqi: 100 + i, inCost: 1, outCost: 1, age: 0}], counters = Array(42).fill(0)} = {}) {
  const published = [], calls = [];
  let inOwnerQueue = false;
  const queue = {count: () => queued, async execute(fn) {
    assert.equal(inOwnerQueue, false, 'EZSP queue serialization');
    inOwnerQueue = true;
    try {return await fn();} finally {inOwnerQueue = false;}
  }};
  const call = (name, fn) => {assert.equal(inOwnerQueue, true, 'EZSP called without owner queue'); calls.push(name); return fn();};
  const ezsp = {
    async ezspNeighborCount() {return call('count', () => count);},
    async ezspGetNeighbor(i) {return call(`neighbor_${i}`, () => entry(i));},
    async ezspGetSourceRouteTableTotalSize() {return call('route_capacity', () => capacity);},
    async ezspGetSourceRouteTableFilledSize() {return call('route_filled', () => filled);},
    async ezspGetSourceRouteTableEntry(i) {return call(`route_${i}`, () => [0, i + 20, 255]);},
    async ezspReadCounters() {return call('read_counters', () => counters);},
  };
  const zigbee = {zhController: {adapter: {ezsp, queue}}};
  const mqtt = {async publish(topic, msg) {published.push({topic, ...JSON.parse(msg)});}};
  const bus = {onMQTTMessage(owner, handler) {this.handler = handler;}, removeListeners() {this.handler = null;}};
  const probe = new Probe(zigbee, mqtt, null, null, bus, null, null, null, {get: () => ({mqtt: {base_topic: 'zigbee2mqtt'}})});
  const send = async (action = 'snapshot', transaction = 't01', extras = {}) => {
    await probe.onMQTTMessage({topic: 'zigbee2mqtt/bridge/request/r60_neighbor', message: JSON.stringify({action, transaction, ...extras})});
    return published.at(-1);
  };
  return {probe, send, published, calls};
}

test('all NCP reads serialized, bounded to NCP tables, never clearing counters', async () => {
  const f = fixture();
  await f.probe.start();
  const answer = await f.send();
  assert.equal(answer.topic, 'bridge/response/r60_neighbor');
  assert.equal(answer.status, 'ok');
  assert.equal(answer.data.count, 2);
  assert.equal(answer.data.source_route_capacity, 254);
  assert.equal(answer.data.source_route_filled, 2);
  assert.equal(answer.data.source_route_entries.length, 2);
  assert.equal(answer.data.counters.BROADCAST_TABLE_FULL, 0);
  assert.deepEqual(f.calls, ['count', 'neighbor_0', 'neighbor_1', 'route_capacity', 'route_filled', 'route_0', 'route_1', 'read_counters']);
});

test('rejects malformed request before EZSP', async () => {
  const f = fixture();
  assert.equal((await f.send('snapshot', 't02', {limit: 999})).error, 'bad_request');
  assert.deepEqual(f.calls, []);
});

test('enforces cooldown without more NCP calls', async () => {
  const f = fixture();
  await f.send();
  const before = f.calls.length;
  assert.equal((await f.send('snapshot', 't02')).error, 'cooldown');
  assert.equal(f.calls.length, before);
});

test('rejects neighbor count beyond configured limit', async () => {
  const f = fixture({count: 27});
  assert.equal((await f.send()).error, 'neighbor_count_out_of_range');
  assert.deepEqual(f.calls, ['count']);
});

test('rejects owner queue pressure before NCP calls', async () => {
  const f = fixture({queued: 9});
  assert.equal((await f.send()).error, 'owner_queue_busy');
  assert.deepEqual(f.calls, []);
});

test('fails closed on neighbor read error', async () => {
  const f = fixture({entry: async () => [1, null]});
  assert.equal((await f.send()).error, 'neighbor_entry_error');
});

test('fails closed on invalid source route occupancy', async () => {
  const f = fixture({capacity: 20, filled: 21});
  assert.equal((await f.send()).error, 'invalid_source_route_capacity');
});

test('avoids large source route entry sweeps but reads counters', async () => {
  const f = fixture({filled: 97});
  const r = await f.send();
  assert.equal(r.status, 'ok');
  assert.equal(r.data.source_route_entries_truncated, true);
  assert.equal(r.data.source_route_entries.length, 0);
  assert.equal(f.calls.includes('read_counters'), true);
  assert.equal(f.calls.some(c => c.startsWith('route_') && c !== 'route_capacity' && c !== 'route_filled'), false);
});

test('rejects malformed counter vector', async () => {
  const f = fixture({counters: Array(20).fill(0)});
  assert.equal((await f.send()).error, 'invalid_counter_vector');
});

test('single-flight on concurrent requests', async () => {
  let release;
  const gate = new Promise(resolve => {release = resolve;});
  const f = fixture({count: 1, entry: async () => {await gate; return [0, {shortId: 9}];}});
  const first = f.send();
  await new Promise(resolve => setImmediate(resolve));
  assert.equal((await f.send('snapshot', 't02')).error, 'probe_busy');
  release(); await first;
  assert.equal(f.calls.filter(c => c === 'count').length, 1);
});

test('stopped extension issues no NCP calls and no response', async () => {
  const f = fixture();
  await f.probe.start(); await f.probe.stop(); await f.send();
  assert.equal(f.published.length, 0);
  assert.deepEqual(f.calls, []);
});
