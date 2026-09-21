'use strict';
/** R60 diagnostics for stock Z2M 2.14.0 / herdsman 10.9.1. DO NOT deploy without gated review. */
const REQUEST = '/bridge/request/r60_neighbor';
const RESPONSE = 'bridge/response/r60_neighbor';
const MAX_NEIGHBORS = 26;
const COOLDOWN_MS = 600000;
const BUDGET_MS = 8000;

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
      const allowed = ['bad_request', 'probe_busy', 'cooldown', 'unsupported_owner', 'owner_queue_busy', 'neighbor_count_out_of_range', 'probe_budget_exceeded', 'neighbor_entry_error'];
      const error = allowed.includes(err.message) ? err.message : 'probe_failed';
      if (!this.stopped) await this.mqtt.publish(RESPONSE, JSON.stringify({transaction, status: 'error', error}));
    }
  }

  async snapshot() {
    // Private properties here are verified only against the EXACT pinned owner versions.
    // They are accessed on the already-running owner; never create another Ezsp or serial connection.
    const adapter = this.zigbee?.zhController?.adapter;
    const ezsp = adapter?.ezsp;
    if (!adapter || !ezsp || typeof ezsp.ezspNeighborCount !== 'function' ||
        typeof ezsp.ezspGetNeighbor !== 'function' || typeof adapter.queue?.count !== 'function') throw Error('unsupported_owner');
    if (adapter.queue.count() > 8) throw Error('owner_queue_busy');
    const started = Date.now();
    const count = await ezsp.ezspNeighborCount();
    if (!Number.isInteger(count) || count < 0 || count > MAX_NEIGHBORS) throw Error('neighbor_count_out_of_range');
    const entries = [];
    for (let index = 0; index < count; index++) {
      if (this.stopped || Date.now() - started >= BUDGET_MS) throw Error('probe_budget_exceeded');
      if (adapter.queue.count() > 8) throw Error('owner_queue_busy');
      const [status, row] = await ezsp.ezspGetNeighbor(index);
      if (status !== 0 || !row) throw Error('neighbor_entry_error');
      const {shortId, longId, averageLqi, inCost, outCost, age} = row;
      entries.push({index, shortId, longId, averageLqi, inCost, outCost, age});
    }
    return {captured_utc: new Date().toISOString(), count, max_supported: MAX_NEIGHBORS,
      elapsed_ms: Date.now() - started, entries};
  }
};
