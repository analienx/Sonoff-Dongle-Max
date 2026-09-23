'use strict';
/** Read-only owner-integrated R60 diagnostics, pinned to Z2M 2.14.0 / herdsman 10.9.1. */
const REQUEST = '/bridge/request/r60_neighbor';
const RESPONSE = 'bridge/response/r60_neighbor';
const MAX_NEIGHBORS = 26;
const MAX_SOURCE_ROUTE_READS = 96;
const COOLDOWN_MS = 600000;
const BUDGET_MS = 8000;
const COUNTER_INDEX = Object.freeze({
  MAC_RX_BROADCAST: 0, MAC_TX_BROADCAST: 1, MAC_TX_UNICAST_SUCCESS: 3,
  MAC_TX_UNICAST_RETRY: 4, MAC_TX_UNICAST_FAILED: 5,
  APS_DATA_TX_UNICAST_SUCCESS: 9, APS_DATA_TX_UNICAST_FAILED: 11,
  ROUTE_DISCOVERY_INITIATED: 12, NEIGHBOR_ADDED: 13,
  NEIGHBOR_REMOVED: 14, NEIGHBOR_STALE: 15,
  ASH_OVERFLOW_ERROR: 18, ASH_FRAMING_ERROR: 19, ASH_OVERRUN_ERROR: 20,
  ALLOCATE_PACKET_BUFFER_FAILURE: 27, PHY_TO_MAC_QUEUE_LIMIT_REACHED: 29,
  TYPE_NWK_RETRY_OVERFLOW: 31, PHY_CCA_FAIL_COUNT: 32,
  BROADCAST_TABLE_FULL: 33, ADDRESS_CONFLICT_SENT: 40,
});

module.exports = class R60NeighborExtension {
  constructor(zigbee, mqtt, _state, _publish, eventBus, _toggle, _restart, _add, settings) {
    this.zigbee = zigbee;
    this.mqtt = mqtt;
    this.eventBus = eventBus;
    this.topic = (settings?.get?.()?.mqtt?.base_topic || 'zigbee2mqtt') + REQUEST;
    this.busy = false;
    this.stopped = false;
    this.lastAccepted = -Infinity;
    this.onMQTTMessage = this.onMQTTMessage.bind(this);
  }

  async start() {
    this.stopped = false;
    this.eventBus.onMQTTMessage(this, this.onMQTTMessage);
  }

  async stop() {
    this.stopped = true;
    this.eventBus.removeListeners(this);
  }

  async onMQTTMessage(event) {
    if (event.topic !== this.topic || this.stopped) return;
    let transaction = null;
    try {
      if (typeof event.message !== 'string' || event.message.length > 256) throw Error('bad_request');
      const input = JSON.parse(event.message);
      if (!input || Array.isArray(input) || input.action !== 'snapshot' ||
          !/^[A-Za-z0-9_-]{1,32}$/.test(input.transaction || '') ||
          Object.keys(input).some(k => !['action', 'transaction'].includes(k))) throw Error('bad_request');
      transaction = input.transaction;
      if (this.busy) throw Error('probe_busy');
      if (Date.now() - this.lastAccepted < COOLDOWN_MS) throw Error('cooldown');
      this.busy = true;
      this.lastAccepted = Date.now();
      let response;
      try {
        response = await this.snapshot();
      } finally {
        this.busy = false;
      }
      if (!this.stopped) await this.mqtt.publish(RESPONSE, JSON.stringify({transaction, status: 'ok', data: response}));
    } catch (err) {
      const allowed = ['bad_request', 'probe_busy', 'cooldown', 'unsupported_owner', 'owner_queue_busy',
        'neighbor_count_out_of_range', 'probe_budget_exceeded', 'neighbor_entry_error',
        'invalid_source_route_capacity', 'source_route_entry_error', 'invalid_counter_vector'];
      const error = allowed.includes(err.message) ? err.message : 'probe_failed';
      if (!this.stopped) await this.mqtt.publish(RESPONSE, JSON.stringify({transaction, status: 'error', error}));
    }
  }

  async snapshot() {
    // Never open a second EZSP owner, clear NCP counters, send management frames, or mutate routing.
    const adapter = this.zigbee?.zhController?.adapter;
    const ezsp = adapter?.ezsp;
    if (!adapter || !ezsp || typeof ezsp.ezspNeighborCount !== 'function' ||
        typeof ezsp.ezspGetNeighbor !== 'function' ||
        typeof ezsp.ezspGetSourceRouteTableTotalSize !== 'function' ||
        typeof ezsp.ezspGetSourceRouteTableFilledSize !== 'function' ||
        typeof ezsp.ezspGetSourceRouteTableEntry !== 'function' ||
        typeof ezsp.ezspReadCounters !== 'function' ||
        typeof adapter.queue?.count !== 'function' ||
        typeof adapter.queue?.execute !== 'function') throw Error('unsupported_owner');
    if (adapter.queue.count() > 8) throw Error('owner_queue_busy');
    const started = Date.now();
    const read = async (fn) => {
      if (this.stopped || Date.now() - started >= BUDGET_MS) throw Error('probe_budget_exceeded');
      if (adapter.queue.count() > 8) throw Error('owner_queue_busy');
      return await adapter.queue.execute(fn);
    };
    const count = await read(() => ezsp.ezspNeighborCount());
    if (!Number.isInteger(count) || count < 0 || count > MAX_NEIGHBORS) throw Error('neighbor_count_out_of_range');
    const entries = [];
    for (let index = 0; index < count; index++) {
      const [status, row] = await read(() => ezsp.ezspGetNeighbor(index));
      if (status !== 0 || !row) throw Error('neighbor_entry_error');
      const {shortId, longId, averageLqi, inCost, outCost, age} = row;
      entries.push({index, shortId, longId, averageLqi, inCost, outCost, age});
    }
    const sourceRouteCapacity = await read(() => ezsp.ezspGetSourceRouteTableTotalSize());
    const sourceRouteFilled = await read(() => ezsp.ezspGetSourceRouteTableFilledSize());
    if (!Number.isInteger(sourceRouteCapacity) || sourceRouteCapacity < 1 || sourceRouteCapacity > 254 ||
        !Number.isInteger(sourceRouteFilled) || sourceRouteFilled < 0 ||
        sourceRouteFilled > sourceRouteCapacity) throw Error('invalid_source_route_capacity');
    const sourceRouteEntries = [];
    if (sourceRouteFilled <= MAX_SOURCE_ROUTE_READS) {
      for (let index = 0; index < sourceRouteFilled; index++) {
        const [status, destination, closerIndex] = await read(() => ezsp.ezspGetSourceRouteTableEntry(index));
        if (status !== 0 || !Number.isInteger(destination) || !Number.isInteger(closerIndex))
          throw Error('source_route_entry_error');
        sourceRouteEntries.push({index, destination, closerIndex});
      }
    }
    const vector = await read(() => ezsp.ezspReadCounters()); // non-clearing, no hourly counter epoch assumption
    if (!Array.isArray(vector) || vector.length < 42 ||
        !Object.values(COUNTER_INDEX).every(index => Number.isInteger(vector[index]) && vector[index] >= 0))
      throw Error('invalid_counter_vector');
    const counters = Object.fromEntries(Object.entries(COUNTER_INDEX).map(([name, index]) => [name, vector[index]]));
    return {captured_utc: new Date().toISOString(), count, max_supported: MAX_NEIGHBORS,
      source_route_filled: sourceRouteFilled, source_route_capacity: sourceRouteCapacity,
      source_route_entries: sourceRouteEntries, source_route_entries_truncated: sourceRouteFilled > MAX_SOURCE_ROUTE_READS,
      counters, elapsed_ms: Date.now() - started, entries};
  }
};
