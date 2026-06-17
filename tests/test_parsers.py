"""Tests for ftrace line parsing and block issue/complete pairing."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.tracer import parsers


def test_parse_common_basic():
    line = ("           <...>-1234  [002] d..1 1234.567890: "
            "block_rq_issue: 8,0 W 8192 () 779 + 16 [kworker/2:1]")
    c = parsers.parse_common(line)
    assert c is not None
    assert c["pid"] == 1234
    assert c["cpu"] == 2
    assert c["event"] == "block_rq_issue"
    assert c["mono_ns"] == 1234567890000
    assert c["body"].startswith("8,0 W 8192")


def test_parse_common_comm_with_dashes_and_slashes():
    line = "kworker/2:1-1234  [002] .... 100.000001: block_rq_complete: 8,0 R () 5 + 8 [0]"
    c = parsers.parse_common(line)
    assert c["comm"] == "kworker/2:1"
    assert c["pid"] == 1234


def test_parse_common_rejects_junk():
    assert parsers.parse_common("not an ftrace line") is None
    assert parsers.parse_common("") is None


def test_decode_rwbs():
    assert parsers.decode_rwbs("R") == ("read", "")
    assert parsers.decode_rwbs("W") == ("write", "")
    assert parsers.decode_rwbs("WS") == ("write", "sync")
    assert parsers.decode_rwbs("RM") == ("read", "meta")
    assert parsers.decode_rwbs("WMA") == ("write", "meta|ahead")
    assert parsers.decode_rwbs("D") == ("discard", "")
    assert parsers.decode_rwbs("F") == ("flush", "")
    assert parsers.decode_rwbs("") == ("", "")


def test_parse_block_issue_and_complete():
    issue = parsers.parse_block_issue("8,0 W 8192 () 779 + 16 [kworker/2:1]")
    assert issue == {"device": "8:0", "rwbs": "W", "bytes": 8192,
                     "sector": 779, "nsect": 16}
    comp = parsers.parse_block_complete("8,0 W () 779 + 16 [0]")
    assert comp["device"] == "8:0"
    assert comp["sector"] == 779
    assert comp["nsect"] == 16
    assert comp["errno"] == 0


def test_block_pairer_matches_and_computes_latency():
    pairer = parsers.BlockPairer()
    issue = parsers.parse_common(
        "app-100 [001] .... 10.000000: block_rq_issue: 259,0 WS 4096 () 2048 + 8 [app]")
    complete = parsers.parse_common(
        "swapper-0 [003] d.h. 10.002000: block_rq_complete: 259,0 WS () 2048 + 8 [0]")
    pairer.on_issue(issue)
    assert pairer.inflight_count() == 1
    row = pairer.on_complete(complete)
    assert row is not None
    assert pairer.inflight_count() == 0
    # Operation + flags split out of rwbs.
    assert row["operation"] == "write"
    assert row["flags"] == "sync"
    # Submitter identity comes from the issue, not the (interrupt) completion.
    assert row["pid"] == 100
    assert row["command"] == "app"
    assert row["size"] == 4096
    assert row["device"] == "259:0"
    assert row["sector"] == 2048
    # 10.002 - 10.000 = 2 ms.
    assert abs(row["latency_ms"] - 2.0) < 1e-6
    # cpu of the completion.
    assert row["cpu_id"] == 3
    assert row["request_id"] == 1


def test_block_pairer_complete_without_issue():
    pairer = parsers.BlockPairer()
    complete = parsers.parse_common(
        "x-1 [000] .... 5.0: block_rq_complete: 8,0 R () 99 + 8 [0]")
    row = pairer.on_complete(complete)
    assert row is not None
    assert row["latency_ms"] == ""        # unknown without a matching issue
    assert row["size"] == 8 * 512         # derived from sector count
    assert row["operation"] == "read"
    assert row["request_id"] == ""


def test_block_pairer_distinguishes_reused_sector():
    pairer = parsers.BlockPairer()
    pairer.on_issue(parsers.parse_common(
        "a-1 [0] .... 1.0: block_rq_issue: 8,0 R 512 () 10 + 1 [a]"))
    r1 = pairer.on_complete(parsers.parse_common(
        "a-1 [0] .... 1.001: block_rq_complete: 8,0 R () 10 + 1 [0]"))
    pairer.on_issue(parsers.parse_common(
        "b-2 [0] .... 2.0: block_rq_issue: 8,0 R 512 () 10 + 1 [b]"))
    r2 = pairer.on_complete(parsers.parse_common(
        "b-2 [0] .... 2.001: block_rq_complete: 8,0 R () 10 + 1 [0]"))
    assert r1["request_id"] == 1
    assert r2["request_id"] == 2
    assert r1["pid"] == 1 and r2["pid"] == 2
