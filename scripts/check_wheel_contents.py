"""Fail when a wheel differs from the current installable source tree."""

from __future__ import annotations

import argparse
from pathlib import Path, PurePosixPath
from zipfile import ZipFile


PACKAGE = "kirin_tor"
WEB_ASSET_SUFFIXES = {".css", ".html", ".js"}
PROTOCOL_ASSET_SUFFIXES = {".json", ".mjs"}
GAME_SPECIFIC_MARKERS = (
    b"brewmaster",
    "酒仙".encode("utf-8"),
    b"world of warcraft",
    b"wow.yaml",
)


def expected_package_files(repository: Path) -> dict[str, bytes]:
    source = repository / "src" / PACKAGE
    expected: dict[str, bytes] = {}
    for path in source.rglob("*"):
        if not path.is_file():
            continue
        relative = path.relative_to(source)
        if (
            path.suffix == ".py"
            or (
                relative.parts[0] == "web_assets"
                and path.suffix in WEB_ASSET_SUFFIXES
            )
            or (
                relative.parts[0] == "protocol_assets"
                and (
                    path.suffix in PROTOCOL_ASSET_SUFFIXES
                    or path.name.endswith(".d.mts")
                )
            )
        ):
            member = str(PurePosixPath(PACKAGE, *relative.parts))
            expected[member] = path.read_bytes()
    return expected


def audit_wheel(
    wheel: Path, repository: Path
) -> tuple[set[str], set[str], set[str], set[str]]:
    expected = expected_package_files(repository)
    with ZipFile(wheel) as archive:
        actual = {
            member: archive.read(member)
            for member in archive.namelist()
            if member.startswith(f"{PACKAGE}/") and not member.endswith("/")
        }
    actual_names = set(actual)
    expected_names = set(expected)
    changed = {
        member
        for member in actual_names & expected_names
        if actual[member] != expected[member]
    }
    game_specific = {
        member
        for member, content in actual.items()
        if any(marker in content.lower() for marker in GAME_SPECIFIC_MARKERS)
    }
    return (
        actual_names - expected_names,
        expected_names - actual_names,
        changed,
        game_specific,
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Compare wheel package members with the current src/kirin_tor tree."
    )
    parser.add_argument("wheels", nargs="+", type=Path)
    parser.add_argument(
        "--repository",
        type=Path,
        default=Path(__file__).resolve().parents[1],
    )
    args = parser.parse_args()

    failed = False
    for wheel in args.wheels:
        unexpected, missing, changed, game_specific = audit_wheel(
            wheel, args.repository.resolve()
        )
        if unexpected or missing or changed or game_specific:
            failed = True
            print(f"Wheel content mismatch: {wheel}")
            for member in sorted(unexpected):
                print(f"  unexpected: {member}")
            for member in sorted(missing):
                print(f"  missing: {member}")
            for member in sorted(changed):
                print(f"  content differs: {member}")
            for member in sorted(game_specific):
                print(f"  game-specific runtime content: {member}")
        else:
            print(f"Wheel content matches current sources: {wheel}")
    if failed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
