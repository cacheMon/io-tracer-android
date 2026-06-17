"""Integration-ish tests for WriteManager output and the /proc snapper.

These exercise real filesystem output in a temp dir and the live /proc tree, so
they run anywhere Linux/Android /proc semantics hold (including this CI box).
"""

import csv
import glob
import io
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.tracer import schema
from src.tracer.WriterManager import WriteManager
from src.tracer.snappers.ProcessSnapper import ProcessSnapper


def _read_csv_any(path):
    """Read a .csv or .csv.zst file into (header, rows)."""
    if path.endswith(".zst"):
        import zstandard
        with open(path, "rb") as fh:
            text = io.TextIOWrapper(
                zstandard.ZstdDecompressor().stream_reader(fh), encoding="utf-8")
            rows = list(csv.reader(text))
    else:
        with open(path) as fh:
            rows = list(csv.reader(fh))
    return rows[0], rows[1:]


def test_writer_creates_layout_and_header(tmp_path):
    wm = WriteManager(str(tmp_path), flush_threshold=2)
    # Appending two rows should auto-rotate the ds stream.
    wm.append("ds", "row-a")
    wm.append("ds", "row-b")
    files = glob.glob(str(tmp_path / "ds" / "ds_*.csv*"))
    assert len(files) == 1
    header, rows = _read_csv_any(files[0])
    assert header == schema.column_names("ds")
    assert [r[0] for r in rows] == ["row-a", "row-b"]


def test_writer_manifest_has_schema_and_clock(tmp_path):
    wm = WriteManager(str(tmp_path))
    wm.append("ds", "x")
    wm.flush_all()
    path = wm.write_manifest(extra={"events_enabled": ["block/block_rq_issue"]})
    with open(path) as f:
        manifest = json.load(f)
    assert manifest["schema_version"] == schema.SCHEMA_VERSION
    assert manifest["platform"] == "android"
    assert "mono_to_real_offset_ns" in manifest["clock"]
    assert manifest["events_enabled"] == ["block/block_rq_issue"]
    assert manifest["rows_written"]["ds"] == 1


def test_process_snapper_emits_valid_rows(tmp_path):
    wm = WriteManager(str(tmp_path))
    snapper = ProcessSnapper(wm, anonymous=False)
    count = snapper.take_snapshot()
    assert count > 0
    files = glob.glob(str(tmp_path / "process" / "process_*.csv*"))
    assert len(files) == 1
    header, rows = _read_csv_any(files[0])
    assert header == schema.column_names("process")
    assert len(rows) == count
    # Our own process should be present with a sane RSS.
    pids = {int(r[1]) for r in rows}
    assert os.getpid() in pids
    me = next(r for r in rows if int(r[1]) == os.getpid())
    assert float(me[5]) > 0  # rss_kb


def test_process_snapper_anonymizes(tmp_path):
    wm = WriteManager(str(tmp_path))
    ProcessSnapper(wm, anonymous=True).take_snapshot()
    files = glob.glob(str(tmp_path / "process" / "process_*.csv*"))
    _header, rows = _read_csv_any(files[0])
    # Hashed names are 12-char hex with no spaces/paths.
    for r in rows:
        assert " " not in r[2]
        assert len(r[2]) == 12
