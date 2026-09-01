"""Small, reproducible validation budget for a synthetic Kirin workspace."""

from __future__ import annotations

import argparse
import tempfile
import time
from pathlib import Path

from kirin_tor.workbench import Workbench
from kirin_tor.workspace import initialize


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--documents", type=int, default=100)
    parser.add_argument("--budget-seconds", type=float, default=8.0)
    args = parser.parse_args()
    if args.documents < 1 or args.documents > 1_000:
        parser.error("--documents must be between 1 and 1000")

    with tempfile.TemporaryDirectory(prefix="kirin-workbench-benchmark-") as temporary:
        root = initialize(Path(temporary) / "workspace")
        for index in range(args.documents):
            document_id = f"benchmark_{index:04d}"
            (root / "entries" / f"{document_id}.kirin").write_text(
                f"""@kirin 1
@entry {document_id}

outputs:
  value "基准值": dimensionless = {index}
""",
                encoding="utf-8",
            )
        started = time.perf_counter()
        result = Workbench(root).validate({})
        elapsed = time.perf_counter() - started
        if result.get("status") != "ok":
            raise SystemExit(f"validation failed: {result}")
        print(f"Validated {args.documents} documents in {elapsed:.3f}s (budget {args.budget_seconds:.3f}s)")
        if elapsed > args.budget_seconds:
            raise SystemExit("workbench validation exceeded its benchmark budget")


if __name__ == "__main__":
    main()
