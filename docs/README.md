# IO-Tracer (Android) — Documentation

Two tools, one trace schema. The **[Android app](ANDROID_APP.md)** (the default)
and the **Python CLI** (see the [repository README](../README.md)) both collect
the same I/O streams and write the same columns — only the compression container
differs (`.csv.gz` for the app, `.csv.zst` for the CLI).

## Guides

- **[Android app](ANDROID_APP.md)** — build, install, run, and the app
  architecture. The recommended, on-device way to trace.
- **[Quick start without root](UNROOTED.md)** — what you can collect on an
  unrooted device (snapshot-only), and how to get root (emulator / Magisk /
  `userdebug`) for the full block trace.

## Reference

- **[Trace types & collection](TRACE_TYPES.md)** — the streams, how each one is
  collected, the collection pipeline, and the clock model.
- **[Trace format](TRACE_FORMAT.md)** — the exact CSV columns for every stream,
  the `manifest.json`, and how to read compressed traces.
- **[Block I/O events](traces/BLOCK_IO_EVENTS.md)** — deep dive on the primary
  `ds` stream: rwbs decoding and issue→complete latency recovery.

## Conventions

- **Schema source of truth:** [`src/tracer/schema.py`](../src/tracer/schema.py)
  (`SCHEMA_VERSION`), mirrored 1:1 by the app's `Schema.kt`. Bump the version
  whenever columns change.
- **Compression:** app → `.csv.gz`, CLI → `.csv.zst` (or plain `.csv` if
  `zstandard` is absent). The columns are identical either way.
- **Clock:** every record carries a trailing `mono_ns` (CLOCK_MONOTONIC) column —
  the common clock for correlating records across streams.
