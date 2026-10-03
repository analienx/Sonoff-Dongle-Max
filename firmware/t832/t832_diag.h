#ifndef T832_DIAG_H
#define T832_DIAG_H

#include <stdint.h>

#define T832_DIAG_SCHEMA_VERSION 1u
#define T832_DIAG_TICK_EVENT 0x4000u
#define T832_DIAG_CAP_STARTUP       (1u << 0)
#define T832_DIAG_CAP_BDB           (1u << 1)
#define T832_DIAG_CAP_MT_PROGRESS   (1u << 2)
#define T832_DIAG_CAP_NPI_PROGRESS  (1u << 3)
#define T832_DIAG_CAP_RX_OVERFLOW   (1u << 4)
#define T832_DIAG_CAP_TX_FINISHED   (1u << 5)
#define T832_DIAG_CAP_COMMAND_PATH  (1u << 6)
#define T832_DIAG_CAP_SYNC_GATE     (1u << 7)
#define T832_DIAG_CAP_RX_HWM        (1u << 8)
#define T832_DIAG_CAP_QUEUE_APPROX  (1u << 9)
#define T832_DIAG_CAP_RESET_CAUSE   (1u << 10)
#define T832_DIAG_CAP_NETWORK_STATE (1u << 11)
#define T832_DIAG_CAP_AGG_COUNTERS  (1u << 12)

enum {
  T832_DIAG_EV_BOOT = 1,
  T832_DIAG_EV_MT_COMMAND_RX,
  T832_DIAG_EV_MT_COMMAND_DISPATCH,
  T832_DIAG_EV_MT_COMMAND_COMPLETE,
  T832_DIAG_EV_RESPONSE_QUEUED,
  T832_DIAG_EV_RESPONSE_ALLOC_FAIL,
  T832_DIAG_EV_NPI_RX_PROGRESS,
  T832_DIAG_EV_NPI_RX_OVERFLOW,
  T832_DIAG_EV_NPI_WRITE_REJECT,
  T832_DIAG_EV_NPI_TX_FINISHED,
  T832_DIAG_EV_TASK_SCHEDULE,
  T832_DIAG_EV_TASK_WORK,
  T832_DIAG_EV_STARTUP_ENTRY,
  T832_DIAG_EV_STARTUP_BDB_REQUEST,
  T832_DIAG_EV_STARTUP_BDB_RETURN,
  T832_DIAG_EV_STARTUP_SRSP_QUEUE,
  T832_DIAG_EV_BDB_DISPATCH,
  T832_DIAG_EV_BDB_RETURN,
  T832_DIAG_EV_HEALTH,
  T832_DIAG_EV_RESOURCE,
  T832_DIAG_EV_EXPORT_SKIP,
  T832_DIAG_EV_FIRST_FAULT,
  T832_DIAG_EV_RX_BUFFER_FULL,
  T832_DIAG_EV_NETWORK_STATE,
  T832_DIAG_EV_TRANSPORT_CONFIG
};

enum {
  T832_DIAG_WORK_MT = 1,
  T832_DIAG_WORK_NPI = 2,
  T832_DIAG_WORK_ZSTACK = 3
};

void T832Diag_init(uint8_t mtTaskId);
void T832Diag_taskScheduled(uint8_t taskId, uint32_t events);
void T832Diag_taskWork(uint8_t area, uint16_t detail);
void T832Diag_commandRx(uint8_t cmd0, uint8_t cmd1);
void T832Diag_commandDispatch(uint8_t cmd0, uint8_t cmd1);
void T832Diag_commandComplete(uint8_t cmd0, uint8_t cmd1, uint8_t status);
void T832Diag_responseQueued(uint8_t cmdType, uint8_t cmdId, uint8_t dataLen);
void T832Diag_responseAllocFailed(uint8_t cmdType, uint8_t cmdId, uint16_t requested);
void T832Diag_uartConfigured(uint32_t baud, uint8_t flow);
void T832Diag_uartRx(uint16_t size, uint16_t occupancy);
void T832Diag_uartRxOverflow(uint16_t attempted, uint16_t occupancy);
void T832Diag_uartTxStart(uint16_t len);
void T832Diag_uartWriteRejected(uint16_t len, int16_t status);
void T832Diag_uartTxFinished(uint16_t len);
void T832Diag_startup(uint8_t stage, uint8_t cmd0, uint8_t cmd1);
void T832Diag_networkState(uint8_t onNetwork, uint8_t nwkState);
void T832Diag_bdb(uint8_t stage, uint16_t detail);
void T832Diag_rxBufferFull(void);
void T832Diag_exportPoll(void);

#endif
