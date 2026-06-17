"""Tests for utility helpers."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.utility import utils


def test_simple_hash_stable_and_truncated():
    a = utils.simple_hash("hello", 16)
    b = utils.simple_hash("hello", 16)
    assert a == b
    assert len(a) == 16
    assert utils.simple_hash("hello") != utils.simple_hash("world")


def test_anonymize_path_preserves_depth_and_root():
    out = utils.anonymize_path("/data/user/0/com.app/files/db.sqlite")
    assert out.startswith("/")
    # Same number of components, none in cleartext.
    assert out.count("/") == "/data/user/0/com.app/files/db.sqlite".count("/")
    assert "com.app" not in out
    assert "data" not in out
    # Extension preserved for the leaf.
    assert out.endswith(".sqlite")


def test_format_csv_row_quotes_and_handles_none():
    assert utils.format_csv_row("a", "b,c", None, 3) == 'a,"b,c",,3'


def test_machine_id_is_16_hex():
    mid = utils.capture_machine_id()
    assert len(mid) == 16
    int(mid, 16)  # must be valid hex


def test_mono_offset_round_trips_to_now():
    import datetime
    import time
    offset = utils.mono_to_real_offset_ns()
    mono = time.monotonic_ns()
    s = utils.mono_ns_to_datetime_str(mono, offset)
    # Parses and is within a few seconds of now.
    dt = datetime.datetime.strptime(s, "%Y-%m-%d %H:%M:%S.%f")
    assert abs((datetime.datetime.now() - dt).total_seconds()) < 5
