"""End-to-end wiring test for the orchestrator's ftrace -> ds path.

Feeds synthetic ftrace lines through AndroidIOTracer._handle_line (no device
needed) and checks a correct, schema-shaped ds CSV is produced.
"""

import csv
import glob
import io
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.tracer import schema
from src.tracer.AndroidIOTracer import AndroidIOTracer


def _read_csv_any(path):
    if path.endswith(".zst"):
        import zstandard
        with open(path, "rb") as fh:
            text = io.TextIOWrapper(
                zstandard.ZstdDecompressor().stream_reader(fh), encoding="utf-8")
            return list(csv.reader(text))
    with open(path) as fh:
        return list(csv.reader(fh))


def test_handle_lines_produce_ds_rows(tmp_path):
    tracer = AndroidIOTracer(str(tmp_path))
    lines = [
        "app-100 [001] .... 10.000000: block_rq_issue: 259,0 R 4096 () 2048 + 8 [app]",
        "swapper-0 [003] d.h. 10.001500: block_rq_complete: 259,0 R () 2048 + 8 [0]",
        "dd-200 [000] .... 11.000000: block_rq_issue: 259,0 WS 8192 () 4096 + 16 [dd]",
        "ksoftirqd-9 [002] d.h. 11.005000: block_rq_complete: 259,0 WS () 4096 + 16 [0]",
        "this line is not an ftrace event and must be ignored",
    ]
    for ln in lines:
        tracer._handle_line(ln)

    assert tracer.ds_rows == 2
    assert tracer.lines_seen == 5

    tracer.wm.flush("ds")
    files = glob.glob(str(tmp_path / "ds" / "ds_*.csv*"))
    assert len(files) == 1
    rows = _read_csv_any(files[0])
    assert rows[0] == schema.column_names("ds")

    by_op = {r[1]: r for r in rows[1:]}
    assert set(by_op) == {"read", "write"}

    read = by_op["read"]
    assert read[2] == "100"           # pid from issue
    assert read[4] == "app"           # command from issue
    assert read[6] == "4096"          # size
    assert abs(float(read[7]) - 1.5) < 1e-6   # latency_ms
    assert read[8] == "259:0"         # device
    assert read[9] == ""              # no flags for plain read
    assert read[10] == "3"            # cpu_id of completion

    write = by_op["write"]
    assert write[9] == "sync"         # WS -> flags=sync
    assert abs(float(write[7]) - 5.0) < 1e-6


def test_snapshot_only_session_writes_manifest(tmp_path):
    # Force the no-tracefs path by pointing at a nonexistent tracefs.
    tracer = AndroidIOTracer(str(tmp_path), tracefs_path="/nonexistent/tracefs")
    assert not tracer.ftrace.available
    tracer.wm.flush_all()
    path = tracer.wm.write_manifest()
    assert os.path.exists(path)
