"""
Pure parsing helpers that turn raw ftrace ``trace_pipe`` lines into trace rows.

These functions have **no I/O side effects** so they are fully unit-testable
without a device. ``FtraceManager`` feeds them lines read from
``/sys/kernel/tracing/trace_pipe``; the block pairer correlates issue/complete
events to recover device latency, mirroring the Linux eBPF tracer's ``ds`` stream.

ftrace common line format (one event)::

    <comm>-<pid> [<cpu>] <flags> <timestamp>: <event>: <body>

e.g.::

    kworker/2:1-1234  [002] d..1 1234.567890: block_rq_issue: 8,0 W 8192 () 779 + 16 [kworker/2:1]
"""

import re


# Common ftrace record header. ``comm`` may contain dashes/slashes/colons, so the
# pid is anchored as the digit-run immediately preceding the " [cpu]" field.
_LINE_RE = re.compile(
    r"^\s*(?P<comm>.+?)-(?P<pid>\d+)\s+"
    r"\[(?P<cpu>\d+)\]\s+"
    r"(?P<flags>\S+)\s+"
    r"(?P<ts>\d+\.\d+):\s+"
    r"(?P<event>[\w:]+):\s*"
    r"(?P<body>.*)$"
)


def parse_common(line: str):
    """Parse the ftrace common header. Returns a dict or ``None`` if unmatched."""
    m = _LINE_RE.match(line)
    if not m:
        return None
    d = m.groupdict()
    d["pid"] = int(d["pid"])
    d["cpu"] = int(d["cpu"])
    # ftrace timestamp is seconds.microseconds (trace_clock=mono => CLOCK_MONOTONIC).
    d["mono_ns"] = int(round(float(d["ts"]) * 1e9))
    return d


# ---------------------------------------------------------------------------
# rwbs decoding (block layer read/write/barrier/sync string)
# ---------------------------------------------------------------------------

# First char selects the base operation.
_RWBS_OP = {
    "R": "read",
    "W": "write",
    "D": "discard",
    "E": "secure_erase",
    "F": "flush",
    "N": "none",
}
# Remaining chars are sub-flags.
_RWBS_FLAG = {
    "S": "sync",
    "M": "meta",
    "A": "ahead",
    "P": "prio",
    "B": "barrier",
    "F": "fua",
}


def decode_rwbs(rwbs: str):
    """Decode an rwbs string into ``(base_operation, flags_str)``.

    Examples::

        "R"   -> ("read", "")
        "WS"  -> ("write", "sync")
        "RM"  -> ("read", "meta")
        "WFS" -> ("write", "fua|sync")
    """
    if not rwbs:
        return "", ""
    op = _RWBS_OP.get(rwbs[0], "")
    flags = [_RWBS_FLAG[c] for c in rwbs[1:] if c in _RWBS_FLAG]
    return op, "|".join(flags)


# ---------------------------------------------------------------------------
# block_rq_issue / block_rq_complete bodies
# ---------------------------------------------------------------------------

# issue:    "8,0 W 8192 () 779 + 16 [comm]"   (dev rwbs bytes (cmd) sector + nsect [comm])
# complete: "8,0 W () 779 + 16 [0]"           (dev rwbs (cmd) sector + nsect [error])
_ISSUE_RE = re.compile(
    r"^(?P<dev>\d+,\d+)\s+(?P<rwbs>\S+)\s+(?P<bytes>\d+)\s+\(.*?\)\s+"
    r"(?P<sector>\d+)\s+\+\s+(?P<nsect>\d+)"
)
_COMPLETE_RE = re.compile(
    r"^(?P<dev>\d+,\d+)\s+(?P<rwbs>\S+)\s+\(.*?\)\s+"
    r"(?P<sector>\d+)\s+\+\s+(?P<nsect>\d+)\s+\[(?P<err>-?\d+)\]"
)


def _dev_to_majmin(dev: str) -> str:
    """ftrace prints the device as ``maj,min``; the schema wants ``maj:min``."""
    return dev.replace(",", ":")


def parse_block_issue(body: str):
    """Parse a ``block_rq_issue`` body. Returns a dict or ``None``."""
    m = _ISSUE_RE.match(body.strip())
    if not m:
        return None
    return {
        "device": _dev_to_majmin(m["dev"]),
        "rwbs": m["rwbs"],
        "bytes": int(m["bytes"]),
        "sector": int(m["sector"]),
        "nsect": int(m["nsect"]),
    }


def parse_block_complete(body: str):
    """Parse a ``block_rq_complete`` body. Returns a dict or ``None``."""
    m = _COMPLETE_RE.match(body.strip())
    if not m:
        return None
    return {
        "device": _dev_to_majmin(m["dev"]),
        "rwbs": m["rwbs"],
        "sector": int(m["sector"]),
        "nsect": int(m["nsect"]),
        "errno": int(m["err"]),
    }


class BlockPairer:
    """Correlate ``block_rq_issue`` with ``block_rq_complete`` to recover latency.

    Keyed by ``(device, sector)`` — CPU is intentionally excluded from the key
    because a request may be issued on one CPU and completed via an interrupt on
    another (same reasoning as the Linux tracer). A monotonic ``request_id`` is
    assigned at issue time so that distinct I/Os reusing the same ``(dev, sector)``
    pair remain distinguishable.

    ``on_issue``/``on_complete`` each accept a parsed common-header dict (from
    :func:`parse_common`). ``on_complete`` returns an ordered tuple of ``ds``
    schema field values when a matching issue is found, else ``None``.
    """

    def __init__(self):
        self._inflight: dict[tuple, dict] = {}
        self._next_request_id = 1

    def on_issue(self, common: dict):
        info = parse_block_issue(common["body"])
        if info is None:
            return
        key = (info["device"], info["sector"])
        self._inflight[key] = {
            "issue_mono_ns": common["mono_ns"],
            "pid": common["pid"],
            "comm": common["comm"],
            "bytes": info["bytes"],
            "nsect": info["nsect"],
            "rwbs": info["rwbs"],
            "request_id": self._next_request_id,
        }
        self._next_request_id += 1

    def on_complete(self, common: dict):
        info = parse_block_complete(common["body"])
        if info is None:
            return None
        key = (info["device"], info["sector"])
        issued = self._inflight.pop(key, None)

        # rwbs from the issue is most reliable for op/flags; fall back to complete.
        rwbs = (issued or {}).get("rwbs") or info["rwbs"]
        operation, flags = decode_rwbs(rwbs)

        if issued is not None:
            latency_ms = (common["mono_ns"] - issued["issue_mono_ns"]) / 1e6
            size = issued["bytes"] or issued["nsect"] * 512
            pid = issued["pid"]
            command = issued["comm"][:16]
            request_id = issued["request_id"]
        else:
            # Completion with no recorded issue (started before tracing began).
            latency_ms = ""
            size = info["nsect"] * 512
            pid = common["pid"]
            command = common["comm"][:16]
            request_id = ""

        # ds schema order (without the trailing mono_ns, which the writer appends):
        # timestamp, operation, pid, tid, command, sector, size, latency_ms,
        # device, flags, cpu_id, ppid, queue_latency_ms, command_flags,
        # operation_code, request_id
        return {
            "operation": operation,
            "pid": pid,
            "tid": "",                 # ftrace block tracepoints don't expose tid
            "command": command,
            "sector": info["sector"],
            "size": size,
            "latency_ms": round(latency_ms, 3) if latency_ms != "" else "",
            "device": info["device"],
            "flags": flags,
            "cpu_id": common["cpu"],
            "ppid": "",
            "queue_latency_ms": "",     # requires block_rq_insert pairing (optional)
            "command_flags": "",        # not exposed via ftrace text on modern kernels
            "operation_code": "",
            "request_id": request_id,
            "mono_ns": common["mono_ns"],
        }

    def inflight_count(self) -> int:
        return len(self._inflight)
