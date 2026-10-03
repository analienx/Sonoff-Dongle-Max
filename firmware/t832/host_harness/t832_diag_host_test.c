/* T832-DIAG-R0 host harness marker: recorder-behavior tests.
 *
 * Exercises the REAL ../t832_diag_impl.inc on the host with stubbed SDK
 * symbols (t832_host_sdk.h + stubs/ti/drivers/dpl/ClockP.h). Allocation is
 * forbidden: link with -Wl,--wrap=malloc,--wrap=calloc,--wrap=realloc,
 * --wrap=free so any heap use by the recorder fails the link.
 */
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "t832_host_sdk.h"

#define CODE_REVISION_NUMBER 8320001u

uint32_t t832DiagResetCauseEarly = 2u;

/* ---- controllable host stand-ins ---- */

static uint32_t host_tick;
static int host_cs_depth;
static int host_cs_max_depth;

uint32_t HostClock_getTicks(void) { return host_tick; }
uint32_t HostClock_getPeriodUs(void) { return 1000u; }
uint32_t ClockP_getSystemTicks(void) { return HostClock_getTicks(); }
uint32_t ClockP_getSystemTickPeriod(void) { return HostClock_getPeriodUs(); }

uint32_t HostCs_enter(void)
{
  host_cs_depth++;
  if (host_cs_depth > host_cs_max_depth) host_cs_max_depth = host_cs_depth;
  return (uint32_t)host_cs_depth;
}
void HostCs_leave(uint32_t key)
{
  (void)key;
  host_cs_depth--;
}
int HostCs_depth(void) { return host_cs_depth; }

#define HOST_MAX_FRAMES 8192u
static uint8_t host_frame_type[HOST_MAX_FRAMES];
static uint8_t host_frame_id[HOST_MAX_FRAMES];
static uint8_t host_frame_len[HOST_MAX_FRAMES];
static uint8_t host_frame_data[HOST_MAX_FRAMES][256];
static uint32_t host_frame_count;

void HostMdi_capture(uint8_t cmdType, uint8_t cmdId, uint8_t len,
                     const uint8_t *data)
{
  uint32_t i = host_frame_count;
  if (i >= HOST_MAX_FRAMES) {
    printf("FAIL: frame capture overflow\n");
    exit(1);
  }
  host_frame_type[i] = cmdType;
  host_frame_id[i] = cmdId;
  host_frame_len[i] = len;
  memcpy(host_frame_data[i], data, len);
  host_frame_count++;
}

#include "t832_diag_impl.inc"

/* ---- test utilities ---- */

static int failures;

#define CHECK(cond) do { \
    if (!(cond)) { \
      printf("FAIL %s:%d: %s\n", __FILE__, __LINE__, #cond); \
      failures++; \
    } \
  } while (0)

static void advance_ms(uint32_t ms) { host_tick += ms; }

static void fresh(uint8_t task_id)
{
  host_tick = 0u;
  host_cs_depth = 0;
  host_cs_max_depth = 0;
  host_frame_count = 0u;
  T832Diag_init(task_id);
  CHECK(host_cs_depth == 0);
}

/* Complete one diagnostic frame cycle the way the wire would: the export
 * marks diag_pending, TX start/finish clears it. */
static void wire_complete_last(uint16_t len)
{
  T832Diag_uartTxStart(len);
  T832Diag_uartTxFinished(len);
}

/* Emit exactly one frame: gates clear, 5 s elapsed. Returns frame index. */
static uint32_t emit_one(void)
{
  uint32_t before = host_frame_count;
  advance_ms(5000u);
  T832Diag_exportPoll();
  CHECK(host_frame_count == before + 1u);
  CHECK(host_cs_depth == 0);
  wire_complete_last(111u);
  return before;
}

typedef struct {
  uint16_t seq;
  uint8_t kind;
  uint8_t flags;
  uint16_t a;
  uint16_t b;
  uint16_t c;
  uint16_t repeat;
  uint16_t export_seq;
  uint32_t caps;
  uint16_t crit_over;
  uint16_t rout_over;
  uint16_t skipped;
} DecFrame;

static uint8_t hexval(uint8_t ch)
{
  if (ch >= '0' && ch <= '9') return (uint8_t)(ch - '0');
  return (uint8_t)(ch - 'A' + 10u);
}

/* Decode captured frame i into DecFrame; returns 0 when it is not a T832D1 frame. */
static int decode_frame(uint32_t i, DecFrame *out)
{
  uint8_t raw[52];
  uint32_t k;
  if (host_frame_len[i] != 111u) return 0;
  if (memcmp(host_frame_data[i], "T832D1:", 7) != 0) return 0;
  for (k = 0; k < 52u; k++) {
    raw[k] = (uint8_t)((hexval(host_frame_data[i][7 + 2u * k]) << 4) |
                       hexval(host_frame_data[i][7 + 2u * k + 1u]));
  }
  if (memcmp(raw, "T8D1", 4) != 0) return 0;
  out->export_seq = (uint16_t)(raw[6] | ((uint16_t)raw[7] << 8));
  out->caps = (uint32_t)raw[18] | ((uint32_t)raw[19] << 8) |
              ((uint32_t)raw[20] << 16) | ((uint32_t)raw[21] << 24);
  out->crit_over = (uint16_t)(raw[22] | ((uint16_t)raw[23] << 8));
  out->rout_over = (uint16_t)(raw[24] | ((uint16_t)raw[25] << 8));
  out->skipped = (uint16_t)(raw[26] | ((uint16_t)raw[27] << 8));
  out->seq = (uint16_t)(raw[32] | ((uint16_t)raw[33] << 8));
  out->kind = raw[34];
  out->flags = raw[35];
  out->a = (uint16_t)(raw[36] | ((uint16_t)raw[37] << 8));
  out->b = (uint16_t)(raw[38] | ((uint16_t)raw[39] << 8));
  out->c = (uint16_t)(raw[40] | ((uint16_t)raw[41] << 8));
  out->repeat = (uint16_t)(raw[42] | ((uint16_t)raw[43] << 8));
  return 1;
}

/* Find the most recently emitted frame with the given record kind. */
static int find_kind(uint8_t kind, DecFrame *out)
{
  uint32_t i = host_frame_count;
  DecFrame f;
  while (i > 0u) {
    i--;
    if (decode_frame(i, &f) && f.kind == kind) {
      *out = f;
      return 1;
    }
  }
  return 0;
}

/* Drain every pending record through the real export path. Periodic
 * HEALTH/RESOURCE snapshots are disarmed while draining (they are covered
 * by dedicated tests): the steady-state firmware intentionally generates
 * aggregate records faster than a stalled link could drain them. */
static void drain_all(void)
{
  uint32_t guard = 0u;
  while ((t832Diag.critical_count || t832Diag.routine_count) && guard < 600u) {
    uint32_t before = host_frame_count;
    t832Diag.last_health_ms = host_tick;
    t832Diag.last_resource_ms = host_tick;
    T832Diag_exportPoll();
    if (host_frame_count == before) {
      advance_ms(5000u);
      t832Diag.last_health_ms = host_tick;
      t832Diag.last_resource_ms = host_tick;
      T832Diag_exportPoll();
    }
    wire_complete_last(111u);
    guard++;
  }
  CHECK(guard < 600u);
  CHECK(host_cs_depth == 0);
}

static void test_sizes(void)
{
  printf("sizes: record=%u state=%u\n",
         (unsigned)sizeof(T832DiagRecord), (unsigned)sizeof(T832DiagState));
  CHECK(sizeof(T832DiagRecord) == 20u);
  CHECK(sizeof(T832DiagState) <= 4096u);
}

static void test_boot_and_caps(void)
{
  DecFrame f;
  fresh(9u);
  CHECK(t832Diag.capabilities == 0xFFFFu);
  emit_one();
  CHECK(find_kind(1u, &f));
  CHECK(f.a == 2u);
  CHECK(f.b == 9u);
  CHECK((f.caps & 0xFFFFu) == 0xFFFFu);
}

static void test_sync_gate(void)
{
  DecFrame f;
  uint32_t n;
  fresh(9u);
  emit_one();
  n = host_frame_count;
  /* SREQ SYS_PING outstanding: export must stall and count a skip. */
  T832Diag_commandRx(0x21u, 0x01u);
  advance_ms(5000u);
  T832Diag_exportPoll();
  CHECK(host_frame_count == n);
  /* Complete the sync round-trip: SRSP queued then physically finished. */
  T832Diag_commandDispatch(0x21u, 0x01u);
  T832Diag_commandComplete(0x21u, 0x01u, 0u);
  T832Diag_responseQueued(0x61u, 0x01u, 3u);
  T832Diag_uartTxStart(20u);
  T832Diag_uartTxFinished(20u);
  advance_ms(5000u);
  T832Diag_exportPoll();
  CHECK(host_frame_count == n + 1u);
  wire_complete_last(111u);
  drain_all();
  CHECK(find_kind(4u, &f));
  CHECK(f.skipped >= 1u);
}

static void test_flood_and_coalesce(void)
{
  uint32_t k;
  DecFrame f;
  fresh(9u);
  for (k = 0; k < 200u; k++) {
    T832Diag_taskWork(T832_DIAG_WORK_MT, 0u);
    T832Diag_commandRx(0x41u, 0x81u);
  }
  CHECK(t832Diag.routine_overwrite > 0u);
  CHECK(t832Diag.critical_count == 0u);
  for (k = 0; k < 70u; k++) {
    T832Diag_uartRxOverflow(300u, 250u);
  }
  CHECK(t832Diag.critical_count == 1u);
  CHECK(t832Diag.critical_overwrite == 0u);
  drain_all();
  CHECK(find_kind(8u, &f));
  CHECK((f.flags & 1u) == 1u);
  CHECK(f.repeat == 70u);
  CHECK(f.a == 300u);
}

static void test_diag_traffic_excluded(void)
{
  uint16_t before;
  fresh(9u);
  emit_one();
  before = t832Diag.normal_pending;
  T832Diag_responseQueued(0x48u, 0x80u, 111u);
  CHECK(t832Diag.normal_pending == before);
  T832Diag_responseAllocFailed(0x48u, 0x80u, 120u);
  CHECK(t832Diag.diag_pending == 0u);
}

static void test_task_events(void)
{
  DecFrame f;
  fresh(9u);
  emit_one();
  T832Diag_taskScheduled(9u, 0x0008u);
  T832Diag_taskScheduled(9u, 0x0010u);
  T832Diag_taskWork(T832_DIAG_WORK_MT, SYS_EVENT_MSG);
  advance_ms(10000u);
  T832Diag_exportPoll();
  wire_complete_last(111u);
  drain_all();
  CHECK(find_kind(26u, &f));
  CHECK(f.a == 0x0010u);
  CHECK(f.b == 0x0018u);
}

static void test_af_outstanding(void)
{
  DecFrame f;
  fresh(9u);
  emit_one();
  T832Diag_commandDispatch(0x24u, 0x01u);
  T832Diag_commandDispatch(0x44u, 0x02u);
  CHECK(t832Diag.af_outstanding == 2u);
  CHECK(t832Diag.af_outstanding_max == 2u);
  T832Diag_commandDispatch(0x45u, 0x01u);
  CHECK(t832Diag.af_outstanding == 2u);
  T832Diag_responseQueued(0x44u, 0x80u, 3u);
  CHECK(t832Diag.af_outstanding == 1u);
  T832Diag_commandDispatch(0x24u, 0x03u);
  T832Diag_commandComplete(0x24u, 0x03u, 1u);
  CHECK(t832Diag.af_outstanding == 1u);
  T832Diag_responseQueued(0x44u, 0x80u, 3u);
  CHECK(t832Diag.af_outstanding == 0u);
  /* Complete the two queued normal frames on the wire. */
  T832Diag_uartTxStart(10u);
  T832Diag_uartTxFinished(10u);
  T832Diag_uartTxStart(10u);
  T832Diag_uartTxFinished(10u);
  CHECK(t832Diag.normal_pending == 0u);
  advance_ms(10000u);
  T832Diag_exportPoll();
  wire_complete_last(111u);
  drain_all();
  CHECK(find_kind(28u, &f));
  CHECK(f.c == 2u);
}

static void test_nv_events(void)
{
  DecFrame f;
  fresh(9u);
  emit_one();
  T832Diag_nvInit(0u);
  T832Diag_nvEvent(1u, 100u, 0u);
  advance_ms(50u);
  T832Diag_nvEvent(2u, 0u, 0u);
  T832Diag_nvEvent(3u, 16u, 0u);
  T832Diag_nvEvent(4u, 5u, 0u);
  T832Diag_nvInit(3u);
  CHECK(t832Diag.critical_count == 3u);
  drain_all();
  CHECK(find_kind(27u, &f));
  CHECK(find_kind(29u, &f));
  CHECK(f.a == 0u);
  CHECK(f.b == 3u);
}

static void test_frame_budget(void)
{
  uint32_t i;
  DecFrame f;
  fresh(9u);
  T832Diag_uartRxOverflow(400u, 300u);
  drain_all();
  for (i = 0; i < host_frame_count; i++) {
    CHECK(host_frame_len[i] == 111u);
    CHECK(host_frame_len[i] <= 240u);
    CHECK(host_frame_type[i] == (MT_RPC_CMD_AREQ | MT_RPC_SYS_DBG));
    CHECK(host_frame_id[i] == MT_DEBUG_MSG);
  }
  CHECK(find_kind(8u, &f));
}

int main(void)
{
  test_sizes();
  test_boot_and_caps();
  test_sync_gate();
  test_flood_and_coalesce();
  test_diag_traffic_excluded();
  test_task_events();
  test_af_outstanding();
  test_nv_events();
  test_frame_budget();
  if (failures) {
    printf("HARNESS RESULT: FAIL (%d)\n", failures);
    return 1;
  }
  printf("HARNESS RESULT: PASS\n");
  return 0;
}
