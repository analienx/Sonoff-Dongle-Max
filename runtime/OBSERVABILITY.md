# P010 diagnostic-only BUSY pressure overlay

This overlay is **not a tuning profile**. It exists only to identify which Ember/NCP resource is saturated if P009 still produces a real `BUSY` send failure.

It is pinned to zigbee-herdsman 10.9.1 commit:

```text
0968f979d558874b17396c96b66382d4236bbdcd
```

## Behavior

On `SLStatus.BUSY` from exactly these production-relevant paths:

- ZCL group / multicast;
- ZCL broadcast;
- ZDO broadcast;

it performs one best-effort call to the existing read-only:

```text
ezspReadCounters()
```

and logs selected values under:

```text
[P010 PRESSURE]
```

It does **not** call `ezspReadAndClearCounters()`, does not retry the failed send and does not modify configuration, routing or queue sizing.

Selected counters:

```text
ASH_OVERFLOW_ERROR
ASH_FRAMING_ERROR
ASH_OVERRUN_ERROR
ALLOCATE_PACKET_BUFFER_FAILURE
PHY_TO_MAC_QUEUE_LIMIT_REACHED
NWK_RETRY_OVERFLOW
PHY_CCA_FAIL_COUNT
BROADCAST_TABLE_FULL
ADDRESS_CONFLICT_SENT
```

The diagnostic read is wrapped in its own try/catch. Failure to retrieve counters is logged but the original BUSY error still proceeds unchanged.

## Deployment boundary

Do not deploy this for the first P009 firmware-only acceptance run. Use it only if P009 still produces a residual BUSY and the existing hourly `[NCP COUNTERS]` data is not temporally precise enough to attribute that event.

This artifact is deliberately separate from the P009 EZSP policy overlay so observability and tuning cannot be confused.
