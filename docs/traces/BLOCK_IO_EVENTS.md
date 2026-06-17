# Block I/O Events (Android)

**Description:** Block-level device I/O operations, the primary trace stream on
Android. Provides insight into physical storage activity (eMMC/UFS/loop devices).

**Source:** ftrace tracepoints under `/sys/kernel/tracing/events/block/`:

- `block_rq_issue` — request dispatched to the device (records start time + size)
- `block_rq_complete` — request finished (computes latency, carries error code)

These are the Android counterpart of the Linux tracer's eBPF block kprobes and
produce the identical [`ds` schema](../TRACE_FORMAT.md#1-block-device-traces-ds).

## CSV Columns

```csv
timestamp,operation,pid,tid,command,sector,size,latency_ms,device,flags,cpu_id,ppid,queue_latency_ms,command_flags,operation_code,request_id,mono_ns
```

| Field | Source | Notes |
|-------|--------|-------|
| `timestamp` | `mono_ns` + manifest offset | wall-clock of completion |
| `operation` | rwbs first char | `read`/`write`/`discard`/`flush`/… |
| `pid` | issue line task-pid | submitting process |
| `tid` | — | empty (not in ftrace block text) |
| `command` | issue line comm | ≤16 chars |
| `sector` | issue/complete body | starting LBA (512-byte units) |
| `size` | issue `bytes` (else `nsect`×512) | I/O size in bytes |
| `latency_ms` | complete_ts − issue_ts | empty if issue not seen |
| `device` | `maj,min` → `maj:min` | block device |
| `flags` | rwbs remaining chars | `sync\|meta\|ahead\|…` |
| `cpu_id` | completion CPU | from the complete line header |
| `ppid`, `queue_latency_ms`, `command_flags`, `operation_code` | — | empty (unavailable via ftrace text) |
| `request_id` | assigned at issue | monotonic per session |
| `mono_ns` | ftrace timestamp (`trace_clock=mono`) | completion time, CLOCK_MONOTONIC ns |

## Latency Measurement

Device latency = `block_rq_complete` time − `block_rq_issue` time.

**Key matching:** issue and complete are correlated by `(device, sector)`. CPU is
intentionally excluded from the key, because a request may be **issued on one CPU
and completed via an interrupt on another**. A monotonic `request_id` is assigned
at issue so that distinct I/Os reusing the same `(device, sector)` remain
distinguishable. A completion seen without a preceding issue (I/O started before
tracing began) is still emitted, with an empty `latency_ms` and `size` derived
from the sector count.

## rwbs Decoding

The first character of the rwbs string selects the base operation; the remaining
characters are sub-flags moved into the `flags` column:

| Char | Meaning (first / subsequent) |
|------|------------------------------|
| `R` | read |
| `W` | write |
| `D` | discard |
| `E` | secure_erase |
| `F` | flush / fua |
| `N` | none |
| `S` | sync |
| `M` | meta |
| `A` | ahead |
| `P` | prio |
| `B` | barrier |

**Examples:** `R` → `read`, `(no flags)`; `WS` → `write`, `sync`;
`RM` → `read`, `meta`; `WMA` → `write`, `meta|ahead`.

## Example ftrace lines

```
   app-100  [001] .... 10.000000: block_rq_issue: 259,0 WS 4096 () 2048 + 8 [app]
swapper-0  [003] d.h. 10.002000: block_rq_complete: 259,0 WS () 2048 + 8 [0]
```

→ one `ds` row: `operation=write, flags=sync, pid=100, command=app, sector=2048,
size=4096, device=259:0, latency_ms=2.0, cpu_id=3, request_id=1`.

**Output File:** `ds/ds_*.csv.zst`
