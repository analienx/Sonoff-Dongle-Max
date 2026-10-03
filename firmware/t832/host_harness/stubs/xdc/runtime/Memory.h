/* T832-DIAG-R0 host harness: xdc Memory stats stub.
 *
 * Mirrors the small surface of <xdc/runtime/Memory.h> used by the recorder:
 * Memory_Stats layout (totalSize, totalFreeSize, largestFreeSize) and
 * Memory_getStats over the default heap instance. Backed by controllable
 * host variables in t832_diag_host_test.c.
 */
#ifndef T832_STUB_MEMORY_H
#define T832_STUB_MEMORY_H

#include <stdint.h>

typedef uint32_t xdc_SizeT;
typedef struct {
  xdc_SizeT totalSize;
  xdc_SizeT totalFreeSize;
  xdc_SizeT largestFreeSize;
} Memory_Stats;
typedef const void *xdc_runtime_IHeap_Handle;

void HostHeap_getStats(Memory_Stats *stats);

static inline void Memory_getStats(xdc_runtime_IHeap_Handle heap, Memory_Stats *stats)
{
  (void)heap;
  HostHeap_getStats(stats);
}

extern const xdc_runtime_IHeap_Handle Memory_defaultHeapInstance;

#endif
