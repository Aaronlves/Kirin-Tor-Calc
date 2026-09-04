#!/usr/bin/env python3
"""Generate or check all public Plugin API 2 artifacts."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from kirin_tor.plugin_artifacts import protocol_artifacts  # noqa: E402


REMOVED_ARTIFACTS = (
    "sdk/plugin/kirin-plugin-sdk.d.ts",
    "src/kirin_tor/protocol_assets/kirin-plugin-sdk.d.ts",
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    stale = []
    for relative in REMOVED_ARTIFACTS:
        path = ROOT / relative
        if args.check:
            if path.exists():
                stale.append(relative)
        else:
            path.unlink(missing_ok=True)
    for relative, expected in protocol_artifacts().items():
        path = ROOT / relative
        if args.check:
            if not path.is_file() or path.read_text(encoding="utf-8") != expected:
                stale.append(relative)
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(expected, encoding="utf-8")
    if stale:
        print("stale Plugin protocol artifacts:")
        for relative in stale:
            print(f"- {relative}")
        return 1
    print("Plugin protocol artifacts are current" if args.check else "Generated Plugin protocol artifacts")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
