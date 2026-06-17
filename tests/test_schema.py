"""Tests for the cross-OS schema definition."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.tracer import schema


def test_every_stream_starts_with_timestamp_and_ends_with_mono_ns():
    for key in schema.STREAMS:
        cols = schema.column_names(key)
        assert cols[-1] == "mono_ns", key
        # First column is timestamp (or snapshot_timestamp for the fs snapshot).
        assert cols[0] in ("timestamp", "snapshot_timestamp"), key


def test_ds_shared_prefix_matches_linux_contract():
    # The first 10 ds columns are the cross-OS shared prefix.
    cols = schema.column_names("ds")
    assert cols[:10] == [
        "timestamp", "operation", "pid", "tid", "command",
        "sector", "size", "latency_ms", "device", "flags",
    ]


def test_fs_shared_prefix_matches_linux_contract():
    cols = schema.column_names("fs")
    assert cols[:12] == [
        "timestamp", "operation", "pid", "tid", "command", "filename",
        "size", "offset", "bytes_completed", "inode", "device", "flags",
    ]


def test_header_line_is_comma_joined():
    assert schema.header_line("ds") == ",".join(schema.column_names("ds"))


def test_manifest_block_is_serializable_and_versioned():
    import json
    block = schema.schema_for_manifest()
    assert block["schema_version"] == schema.SCHEMA_VERSION == 3
    # Must round-trip through JSON.
    json.loads(json.dumps(block))
    assert set(block["streams"]) == set(schema.STREAMS)
