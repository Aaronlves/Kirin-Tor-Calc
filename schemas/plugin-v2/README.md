# Plugin API 2 generated contracts

These JSON Schemas and catalogs are generated from Kirin Tor's Python Plugin protocol definition.
They describe the strict manifest, frame messages, Model Catalog requests/descriptors, operation
capabilities, hard limits, and stable errors.

Do not edit the JSON files directly. Run `python scripts/generate_plugin_protocol.py` after changing
the source contract, and use `--check` in CI or review to detect drift.
