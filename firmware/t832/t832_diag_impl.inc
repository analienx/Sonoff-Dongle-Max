/*
 * T832-DIAG-R0 recorder/exporter.
 * Included once at the end of mt_debug.c so no project source-list change is needed.
 * Hot-path hooks: fixed writes only; no allocation, logging, flash, UART, or waits.
 */
#include <stdint.h>
#include <string.h>
#include <ti/drivers/dpl/ClockP.h>
#include "t832_diag.h"

#ifndef CODE_REVISION_NUMBER
#define CODE_REVISION_NUMBER 0u
#endif

#define T832_DIAG_CRITICAL_RECORDS 64u
#define T832_DIAG_ROUTINE_RECORDS 64u
#define T832_DIAG_EXPORT_MIN_MS 5000u
#define T832_DIAG_HEALTH_MS 10000u
#define T832_DIAG_RESOURCE_MS 60000u
#define T832_DIAG_PREFIX "T832D1:"
#define T832_DIAG_PREFIX_LEN 7u

typedef struct {
  uint32_t first_ms;
  uint32_t last_ms;
  uint16_t sequence;
  uint8_t kind;
  uint8_t flags;
  uint16_t a;
  uint16_t b;
  uint16_t c;
  uint16_t repeat_count;
} T832DiagRecord;

typedef struct {
  T832DiagRecord critical[T832_DIAG_CRITICAL_RECORDS];
  T832DiagRecord routine[T832_DIAG_ROUTINE_RECORDS];
  T832DiagRecord first_fault;
  uint32_t last_tick;
  uint32_t tick_wraps;
  uint32_t export_sequence;
  uint32_t record_sequence;
  uint32_t capabilities;
  uint32_t last_export_ms;
  uint32_t last_health_ms;
  uint32_t last_resource_ms;
  uint32_t mt_sched_ms;
  uint32_t mt_work_ms;
  uint32_t npi_work_ms;
  uint32_t zstack_work_ms;
  uint32_t tx_start_ms;
  uint32_t oldest_pending_ms;
  uint32_t af_oldest_ms;
  uint32_t nv_start_ms;
  uint32_t mt_schedule_count;
  uint32_t mt_work_count;
  uint32_t npi_rx_count;
  uint32_t npi_tx_count;
  uint32_t last_health_schedule_count;
  uint32_t reset_cause;
  uint16_t critical_head;
  uint16_t critical_count;
  uint16_t routine_head;
  uint16_t routine_count;
  uint16_t critical_overwrite;
  uint16_t routine_overwrite;
  uint16_t export_skipped;
  uint16_t rx_high_water;
  uint16_t normal_pending;
  uint16_t normal_pending_max;
  uint16_t tx_age_max;
  uint16_t af_outstanding;
  uint16_t af_outstanding_max;
  uint16_t mt_last_events;
  uint16_t mt_sticky_events;
  uint8_t mt_task_id;
  uint8_t sync_outstanding;
  uint8_t response_queued;
  uint8_t diag_pending;
  uint8_t transport_active;
  uint8_t first_fault_valid;
  uint8_t initialized;
  uint8_t reserved;
} T832DiagState;

_Static_assert(sizeof(T832DiagRecord) == 20u, "T832 diagnostic record must remain 20 bytes");
_Static_assert(sizeof(T832DiagState) <= 4096u, "T832 diagnostic static RAM budget exceeded");

extern uint32_t t832DiagResetCauseEarly;
static T832DiagState t832Diag;

static uint64_t T832Diag_nowMs(void)
{
  uint32_t tick = ClockP_getSystemTicks();
  uint32_t period_us = ClockP_getSystemTickPeriod();
  uint32_t key = OsalPort_enterCS();
  if (t832Diag.initialized && tick < t832Diag.last_tick) {
    t832Diag.tick_wraps++;
  }
  t832Diag.last_tick = tick;
  uint64_t ext = (((uint64_t)t832Diag.tick_wraps) << 32) | tick;
  OsalPort_leaveCS(key);
  return (ext * period_us) / 1000u;
}

static uint8_t T832Diag_isCritical(uint8_t kind)
{
  return (kind == T832_DIAG_EV_NPI_RX_OVERFLOW ||
          kind == T832_DIAG_EV_NPI_WRITE_REJECT ||
          kind == T832_DIAG_EV_RESPONSE_ALLOC_FAIL ||
          kind == T832_DIAG_EV_FIRST_FAULT ||
          kind == T832_DIAG_EV_RX_BUFFER_FULL ||
          kind == T832_DIAG_EV_NV_FAULT);
}

static void T832Diag_record(uint8_t kind, uint16_t a, uint16_t b, uint16_t c)
{
  uint32_t ms = (uint32_t)T832Diag_nowMs();
  uint32_t key = OsalPort_enterCS();
  uint8_t critical = T832Diag_isCritical(kind);
  T832DiagRecord *ring = critical ? t832Diag.critical : t832Diag.routine;
  uint16_t cap = critical ? T832_DIAG_CRITICAL_RECORDS : T832_DIAG_ROUTINE_RECORDS;
  uint16_t *head = critical ? &t832Diag.critical_head : &t832Diag.routine_head;
  uint16_t *count = critical ? &t832Diag.critical_count : &t832Diag.routine_count;
  uint16_t *over = critical ? &t832Diag.critical_overwrite : &t832Diag.routine_overwrite;

  if (*count) {
    uint16_t last = (uint16_t)((*head + cap - 1u) % cap);
    T832DiagRecord *r = &ring[last];
    if (critical && r->kind == kind && r->a == a && r->b == b && r->c == c) {
      r->last_ms = ms;
      if (r->repeat_count != 0xFFFFu) r->repeat_count++;
      OsalPort_leaveCS(key);
      return;
    }
  }

  T832DiagRecord *r = &ring[*head];
  r->first_ms = ms;
  r->last_ms = ms;
  r->sequence = (uint16_t)(++t832Diag.record_sequence);
  r->kind = kind;
  r->flags = critical ? 1u : 0u;
  r->a = a;
  r->b = b;
  r->c = c;
  r->repeat_count = 1u;
  *head = (uint16_t)((*head + 1u) % cap);
  if (*count < cap) (*count)++; else (*over)++;

  if (critical && !t832Diag.first_fault_valid) {
    t832Diag.first_fault = *r;
    t832Diag.first_fault_valid = 1u;
  }
  OsalPort_leaveCS(key);
}

void T832Diag_init(uint8_t mtTaskId)
{
  memset(&t832Diag, 0, sizeof(t832Diag));
  t832Diag.mt_task_id = mtTaskId;
  t832Diag.capabilities =
      T832_DIAG_CAP_STARTUP | T832_DIAG_CAP_BDB |
      T832_DIAG_CAP_MT_PROGRESS | T832_DIAG_CAP_NPI_PROGRESS |
      T832_DIAG_CAP_RX_OVERFLOW | T832_DIAG_CAP_TX_FINISHED |
      T832_DIAG_CAP_COMMAND_PATH | T832_DIAG_CAP_SYNC_GATE |
      T832_DIAG_CAP_RX_HWM | T832_DIAG_CAP_QUEUE_APPROX |
      T832_DIAG_CAP_RESET_CAUSE | T832_DIAG_CAP_NETWORK_STATE |
      T832_DIAG_CAP_AGG_COUNTERS | T832_DIAG_CAP_TASK_MODES |
      T832_DIAG_CAP_NV_COMPACT | T832_DIAG_CAP_AF_AGE;
  t832Diag.reset_cause = t832DiagResetCauseEarly;
  t832Diag.initialized = 1u;
  T832Diag_record(T832_DIAG_EV_BOOT, (uint16_t)t832Diag.reset_cause,
                  mtTaskId, (uint16_t)t832Diag.capabilities);
}

void T832Diag_taskScheduled(uint8_t taskId, uint32_t events)
{
  t832Diag.mt_sched_ms = (uint32_t)T832Diag_nowMs();
  t832Diag.mt_schedule_count++;
  t832Diag.mt_last_events = (uint16_t)events;
  t832Diag.mt_sticky_events |= (uint16_t)events;
  (void)taskId;
}

void T832Diag_taskWork(uint8_t area, uint16_t detail)
{
  uint32_t now = (uint32_t)T832Diag_nowMs();
  if (area == T832_DIAG_WORK_MT) {
    t832Diag.mt_work_ms = now;
    t832Diag.mt_work_count++;
  } else if (area == T832_DIAG_WORK_NPI) {
    t832Diag.npi_work_ms = now;
  } else if (area == T832_DIAG_WORK_ZSTACK) {
    t832Diag.zstack_work_ms = now;
  }
  (void)detail;
}

void T832Diag_commandRx(uint8_t cmd0, uint8_t cmd1)
{
  if ((cmd0 & MT_RPC_CMD_TYPE_MASK) == MT_RPC_CMD_SREQ) {
    t832Diag.sync_outstanding = 1u;
    t832Diag.response_queued = 0u;
  }
  T832Diag_record(T832_DIAG_EV_MT_COMMAND_RX, cmd0, cmd1, t832Diag.sync_outstanding);
}

static uint8_t T832Diag_isAfDataRequest(uint8_t cmd0, uint8_t cmd1)
{
  uint8_t type = (uint8_t)(cmd0 & MT_RPC_CMD_TYPE_MASK);
  if ((cmd0 & MT_RPC_SUBSYSTEM_MASK) != MT_RPC_SYS_AF) return 0u;
  if (type != MT_RPC_CMD_SREQ && type != MT_RPC_CMD_AREQ) return 0u;
  return (uint8_t)(cmd1 == MT_AF_DATA_REQUEST ||
                   cmd1 == MT_AF_DATA_REQUEST_EXT ||
                   cmd1 == MT_AF_DATA_REQUEST_SRCRTG);
}

static void T832Diag_afResolveOne(void)
{
  if (t832Diag.af_outstanding) {
    t832Diag.af_outstanding--;
    if (!t832Diag.af_outstanding) t832Diag.af_oldest_ms = 0u;
  }
}

void T832Diag_commandDispatch(uint8_t cmd0, uint8_t cmd1)
{
  if (T832Diag_isAfDataRequest(cmd0, cmd1)) {
    if (!t832Diag.af_outstanding) {
      t832Diag.af_oldest_ms = (uint32_t)T832Diag_nowMs();
    }
    if (t832Diag.af_outstanding != 0xFFFFu) t832Diag.af_outstanding++;
    if (t832Diag.af_outstanding > t832Diag.af_outstanding_max) {
      t832Diag.af_outstanding_max = t832Diag.af_outstanding;
    }
  }
  T832Diag_record(T832_DIAG_EV_MT_COMMAND_DISPATCH, cmd0, cmd1, 0u);
}

void T832Diag_commandComplete(uint8_t cmd0, uint8_t cmd1, uint8_t status)
{
  if (status && T832Diag_isAfDataRequest(cmd0, cmd1)) T832Diag_afResolveOne();
  T832Diag_record(T832_DIAG_EV_MT_COMMAND_COMPLETE, cmd0, cmd1, status);
}

void T832Diag_responseQueued(uint8_t cmdType, uint8_t cmdId, uint8_t dataLen)
{
  if (((cmdType & MT_RPC_SUBSYSTEM_MASK) == MT_RPC_SYS_DBG) &&
      ((cmdType & MT_RPC_CMD_TYPE_MASK) == MT_RPC_CMD_AREQ) &&
      cmdId == MT_DEBUG_MSG) {
    return;
  }
  if (((cmdType & MT_RPC_CMD_TYPE_MASK) == MT_RPC_CMD_AREQ) &&
      ((cmdType & MT_RPC_SUBSYSTEM_MASK) == MT_RPC_SYS_AF) &&
      cmdId == MT_AF_DATA_CONFIRM) {
    T832Diag_afResolveOne();
  }
  if (t832Diag.normal_pending == 0u) t832Diag.oldest_pending_ms = (uint32_t)T832Diag_nowMs();
  if (t832Diag.normal_pending != 0xFFFFu) t832Diag.normal_pending++;
  if (t832Diag.normal_pending > t832Diag.normal_pending_max) {
    t832Diag.normal_pending_max = t832Diag.normal_pending;
  }
  if ((cmdType & MT_RPC_CMD_TYPE_MASK) == MT_RPC_CMD_SRSP) {
    t832Diag.response_queued = 1u;
    T832Diag_record(T832_DIAG_EV_RESPONSE_QUEUED, cmdType, cmdId, dataLen);
  }
}

void T832Diag_responseAllocFailed(uint8_t cmdType, uint8_t cmdId, uint16_t requested)
{
  if (((cmdType & MT_RPC_SUBSYSTEM_MASK) == MT_RPC_SYS_DBG) &&
      ((cmdType & MT_RPC_CMD_TYPE_MASK) == MT_RPC_CMD_AREQ) &&
      cmdId == MT_DEBUG_MSG) {
    t832Diag.diag_pending = 0u;
  }
  T832Diag_record(T832_DIAG_EV_RESPONSE_ALLOC_FAIL, cmdType, cmdId, requested);
}

void T832Diag_uartConfigured(uint32_t baud, uint8_t flow)
{
  T832Diag_record(T832_DIAG_EV_TRANSPORT_CONFIG, (uint16_t)(baud / 100u), flow, 0u);
}

void T832Diag_uartRx(uint16_t size, uint16_t occupancy)
{
  if (occupancy > t832Diag.rx_high_water) t832Diag.rx_high_water = occupancy;
  t832Diag.npi_work_ms = (uint32_t)T832Diag_nowMs();
  t832Diag.npi_rx_count += size;
}

void T832Diag_uartRxOverflow(uint16_t attempted, uint16_t occupancy)
{
  T832Diag_record(T832_DIAG_EV_NPI_RX_OVERFLOW, attempted, occupancy, t832Diag.rx_high_water);
}

void T832Diag_uartTxStart(uint16_t len)
{
  t832Diag.transport_active = 1u;
  t832Diag.tx_start_ms = (uint32_t)T832Diag_nowMs();
  (void)len;
}

void T832Diag_uartWriteRejected(uint16_t len, int16_t status)
{
  t832Diag.transport_active = 0u;
  T832Diag_record(T832_DIAG_EV_NPI_WRITE_REJECT, len, (uint16_t)status, 0u);
}

void T832Diag_uartTxFinished(uint16_t len)
{
  uint16_t age = (uint16_t)((uint32_t)T832Diag_nowMs() - t832Diag.tx_start_ms);
  uint8_t completedSyncResponse = (t832Diag.sync_outstanding && t832Diag.response_queued);
  t832Diag.transport_active = 0u;
  t832Diag.npi_work_ms = (uint32_t)T832Diag_nowMs();
  t832Diag.npi_tx_count++;
  if (age > t832Diag.tx_age_max) t832Diag.tx_age_max = age;
  if (t832Diag.diag_pending) {
    t832Diag.diag_pending = 0u;
  } else if (t832Diag.normal_pending) {
    t832Diag.normal_pending--;
    if (!t832Diag.normal_pending) t832Diag.oldest_pending_ms = 0u;
  }
  if (completedSyncResponse) {
    t832Diag.sync_outstanding = 0u;
    t832Diag.response_queued = 0u;
    T832Diag_record(T832_DIAG_EV_NPI_TX_FINISHED, len, age, t832Diag.normal_pending);
  }
}

void T832Diag_startup(uint8_t stage, uint8_t cmd0, uint8_t cmd1)
{
  uint8_t kind = T832_DIAG_EV_STARTUP_ENTRY;
  if (stage == 2u) kind = T832_DIAG_EV_STARTUP_BDB_REQUEST;
  else if (stage == 3u) kind = T832_DIAG_EV_STARTUP_BDB_RETURN;
  else if (stage == 4u) kind = T832_DIAG_EV_STARTUP_SRSP_QUEUE;
  t832Diag.zstack_work_ms = (uint32_t)T832Diag_nowMs();
  T832Diag_record(kind, cmd0, cmd1, stage);
}

void T832Diag_networkState(uint8_t onNetwork, uint8_t nwkState)
{
  T832Diag_record(T832_DIAG_EV_NETWORK_STATE, onNetwork, nwkState, 0u);
}

void T832Diag_bdb(uint8_t stage, uint16_t detail)
{
  t832Diag.zstack_work_ms = (uint32_t)T832Diag_nowMs();
  T832Diag_record(stage == 1u ? T832_DIAG_EV_BDB_DISPATCH : T832_DIAG_EV_BDB_RETURN,
                  stage, detail, 0u);
}

void T832Diag_rxBufferFull(void)
{
  T832Diag_record(T832_DIAG_EV_RX_BUFFER_FULL, 0u, 0u, 0u);
}

void T832Diag_nvEvent(uint8_t stage, uint16_t b, uint16_t c)
{
  (void)c;
  if (stage == 1u) {
    t832Diag.nv_start_ms = (uint32_t)T832Diag_nowMs();
    T832Diag_record(T832_DIAG_EV_NV_EVENT, 1u, b, 0u);
  } else if (stage == 2u || stage == 3u) {
    uint16_t dur = (uint16_t)((uint32_t)T832Diag_nowMs() - t832Diag.nv_start_ms);
    T832Diag_record(stage == 3u ? T832_DIAG_EV_NV_FAULT : T832_DIAG_EV_NV_EVENT,
                    stage, b, dur);
  } else if (stage == 4u) {
    T832Diag_record(T832_DIAG_EV_NV_FAULT, 4u, b, 0u);
  }
}

void T832Diag_nvInit(uint8_t action)
{
  if (action >= 2u) {
    T832Diag_record(T832_DIAG_EV_NV_FAULT, 0u, action, 0u);
  } else {
    T832Diag_record(T832_DIAG_EV_NV_EVENT, 5u, action, 0u);
  }
}

static uint8_t T832Diag_pop(T832DiagRecord *out)
{
  uint32_t key = OsalPort_enterCS();
  T832DiagRecord *ring = 0;
  uint16_t cap = 0;
  uint16_t *count = 0;
  uint16_t *head = 0;

  if (t832Diag.critical_count) {
    ring = t832Diag.critical; cap = T832_DIAG_CRITICAL_RECORDS;
    count = &t832Diag.critical_count; head = &t832Diag.critical_head;
  } else if (t832Diag.routine_count) {
    ring = t832Diag.routine; cap = T832_DIAG_ROUTINE_RECORDS;
    count = &t832Diag.routine_count; head = &t832Diag.routine_head;
  } else {
    OsalPort_leaveCS(key);
    return 0u;
  }
  uint16_t tail = (uint16_t)((*head + cap - *count) % cap);
  *out = ring[tail];
  (*count)--;
  OsalPort_leaveCS(key);
  return 1u;
}

static void T832Diag_put16(uint8_t **p, uint16_t v)
{
  *(*p)++ = (uint8_t)v;
  *(*p)++ = (uint8_t)(v >> 8);
}

static void T832Diag_put32(uint8_t **p, uint32_t v)
{
  T832Diag_put16(p, (uint16_t)v);
  T832Diag_put16(p, (uint16_t)(v >> 16));
}

static void T832Diag_put64(uint8_t **p, uint64_t v)
{
  T832Diag_put32(p, (uint32_t)v);
  T832Diag_put32(p, (uint32_t)(v >> 32));
}

static void T832Diag_hex(const uint8_t *src, uint8_t len, uint8_t *dst)
{
  static const char h[] = "0123456789ABCDEF";
  uint8_t i;
  for (i = 0; i < len; i++) {
    dst[2u * i] = (uint8_t)h[src[i] >> 4];
    dst[2u * i + 1u] = (uint8_t)h[src[i] & 0x0Fu];
  }
}

void T832Diag_exportPoll(void)
{
  uint64_t now64 = T832Diag_nowMs();
  uint32_t now = (uint32_t)now64;

  if ((uint32_t)(now - t832Diag.last_health_ms) >= T832_DIAG_HEALTH_MS) {
    uint32_t scheduled = t832Diag.mt_schedule_count - t832Diag.last_health_schedule_count;
    uint32_t mtAge32 = now - t832Diag.mt_work_ms;
    uint32_t npiAge32 = now - t832Diag.npi_work_ms;
    uint16_t scheduleCount = scheduled > 0xFFFFu ? 0xFFFFu : (uint16_t)scheduled;
    uint16_t mtAge = mtAge32 > 0xFFFFu ? 0xFFFFu : (uint16_t)mtAge32;
    uint16_t npiAge = npiAge32 > 0xFFFFu ? 0xFFFFu : (uint16_t)npiAge32;
    T832Diag_record(T832_DIAG_EV_HEALTH, scheduleCount, mtAge, npiAge);
    T832Diag_record(T832_DIAG_EV_TASK_EVENTS, t832Diag.mt_last_events,
                    t832Diag.mt_sticky_events,
                    (uint16_t)(t832Diag.mt_schedule_count & 0xFFFFu));
    {
      uint32_t afAge32 = t832Diag.af_outstanding ?
          now - t832Diag.af_oldest_ms : 0u;
      uint16_t afAge = afAge32 > 0xFFFFu ? 0xFFFFu : (uint16_t)afAge32;
      T832Diag_record(T832_DIAG_EV_AF_STATE, t832Diag.af_outstanding, afAge,
                      t832Diag.af_outstanding_max);
    }
    t832Diag.last_health_schedule_count = t832Diag.mt_schedule_count;
    t832Diag.last_health_ms = now;
  }

  if ((uint32_t)(now - t832Diag.last_resource_ms) >= T832_DIAG_RESOURCE_MS) {
    uint32_t zigAge32 = now - t832Diag.zstack_work_ms;
    uint16_t zigAge = zigAge32 > 0xFFFFu ? 0xFFFFu : (uint16_t)zigAge32;
    T832Diag_record(T832_DIAG_EV_RESOURCE, 1u,
                    t832Diag.rx_high_water, t832Diag.normal_pending_max);
    T832Diag_record(T832_DIAG_EV_RESOURCE, 2u,
                    t832Diag.tx_age_max, zigAge);
    t832Diag.last_resource_ms = now;
  }

  if ((uint32_t)(now - t832Diag.last_export_ms) < T832_DIAG_EXPORT_MIN_MS) return;

  if (t832Diag.sync_outstanding || t832Diag.transport_active ||
      t832Diag.diag_pending || t832Diag.normal_pending) {
    if (t832Diag.export_skipped != 0xFFFFu) t832Diag.export_skipped++;
    return;
  }

  T832DiagRecord rec;
  if (!T832Diag_pop(&rec)) return;

  uint8_t bin[52];
  uint8_t *p = bin;
  *p++ = 'T'; *p++ = '8'; *p++ = 'D'; *p++ = '1';
  *p++ = T832_DIAG_SCHEMA_VERSION;
  *p++ = 1u;
  T832Diag_put16(&p, (uint16_t)(++t832Diag.export_sequence));
  T832Diag_put16(&p, 1u);
  T832Diag_put64(&p, now64);
  T832Diag_put32(&p, (uint32_t)CODE_REVISION_NUMBER);
  T832Diag_put32(&p, t832Diag.capabilities);
  T832Diag_put16(&p, t832Diag.critical_overwrite);
  T832Diag_put16(&p, t832Diag.routine_overwrite);
  T832Diag_put16(&p, t832Diag.export_skipped);
  memcpy(p, &rec, sizeof(rec));
  p += sizeof(rec);

  uint8_t out[112];
  memcpy(out, T832_DIAG_PREFIX, T832_DIAG_PREFIX_LEN);
  T832Diag_hex(bin, (uint8_t)(p - bin), out + T832_DIAG_PREFIX_LEN);
  uint8_t outLen = (uint8_t)(T832_DIAG_PREFIX_LEN + 2u * (p - bin));

  t832Diag.diag_pending = 1u;
  t832Diag.last_export_ms = now;
  MT_BuildAndSendZToolResponse(
      ((uint8_t)MT_RPC_CMD_AREQ | (uint8_t)MT_RPC_SYS_DBG),
      MT_DEBUG_MSG, outLen, out);
}
