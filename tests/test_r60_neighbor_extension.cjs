'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const Probe = require('../runtime/r60_neighbor_extension.cjs');

function fixture({count = 2, queued = 0, entry = async i => [0, {shortId: i + 2, longId: `mock_${i}`, averageLqi: 100 + i, inCost: 1, outCost: 1, age: 0}]} = {}) {
  const published = [];
  const calls = [];
  const ezsp = {
    async ezspNeighborCount() {calls.push('count'); return count;},
    async ezspGetNeighbor(i) {calls.push(i); return entry(i);},
  };
  const zigbee = {zhController: {adapter: {ezsp, queue: {count: () => queued}}}};
  const mqtt = {async publish(topic, msg) {published.push({topic, ...JSON.parse(msg)});}};
  const bus = {onMQTTMessage(owner, handler) {this.handler = handler;}, removeListeners() {this.handler = null;}};
  const probe = new Probe(zigbee, mqtt, null, null, bus, null, null, null, {get: () => ({mqtt: {base_topic: 'zigbee2mqtt'}})});
  const send = async (action = 'snapshot', transaction = 't01', extras = {}) => {
    await probe.onMQTTMessage({topic: 'zigbee2mqtt/bridge/request/r60_neighbor', message: JSON.stringify({action, transaction, ...extras})});
    return published.at(-1);
  };
  return {probe, mqtt, bus, send, published, calls};
}

test('owner count plus indexed rows; no network-wide requests or second owner', async () => {
  const f = fixture();
  await f.probe.start();
  const answer = await f.send();
  assert.equal(answer.topic, 'bridge/response/r60_neighbor');
  assert.equal(answer.status, 'ok');
  assert.equal(answer.data.count, 2);
  assert.deepEqual(f.calls, ['count', 0, 1]);
  assert.equal(answer.data.entries[0].shortId, 2);
  assert.equal(answer.data.entries[1].averageLqi, 101);
});

test('rejects unsupported request shape before any EZSP call', async () => {
  const f = fixture();
  assert.equal((await f.send('snapshot', 't02', {limit: 999})).error, 'bad_request');
  assert.deepEqual(f.calls, []);
});

test('enforces cooldown without additional owner calls', async () => {
  const f = fixture();
  await f.send();
  assert.equal((await f.send('snapshot', 't02')).error, 'cooldown');
  assert.deepEqual(f.calls, ['count', 0, 1]);
});

test('rejects a count beyond the verified 26-entry maximum', async () => {
  const f = fixture({count: 27});
  assert.equal((await f.send()).error, 'neighbor_count_out_of_range');
  assert.deepEqual(f.calls, ['count']);
});

test('bails out if active owner queue is busy', async () => {
  const f = fixture({queued: 9});
  assert.equal((await f.send()).error, 'owner_queue_busy');
  assert.deepEqual(f.calls, []);
});

test('reports an entry status failure without reporting a complete snapshot', async () => {
  const f = fixture({entry: async () => [1, null]});
  assert.equal((await f.send()).error, 'neighbor_entry_error');
});

test('blocks concurrent snapshots with one-flight guard', async () => {
  let release;
  const gate = new Promise(resolve => {release = resolve;});
  const f = fixture({count: 1, entry: async () => {await gate; return [0, {shortId: 9}];}});
  const first = f.send();
  await new Promise(resolve => setImmediate(resolve));
  const second = await f.send('snapshot', 't02');
  assert.equal(second.error, 'probe_busy');
  release();
  await first;
  assert.equal(f.calls.filter(x => x === 'count').length, 1);
});

test('stopped extension never emits a new reply or issues a query', async () => {
  const f = fixture();
  await f.probe.start();
  await f.probe.stop();
  await f.send();
  assert.equal(f.published.length, 0);
  assert.deepEqual(f.calls, []);
});
