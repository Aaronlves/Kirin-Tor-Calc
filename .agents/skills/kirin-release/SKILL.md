---
name: kirin-release
description: Prepare, verify, or review a Kirin Tor release. Use for versioning, changelog and README release consistency, CI, frontend production assets, Python packaging, wheel inspection, installation smoke tests, tags, or publication readiness. Do not activate for ordinary feature development merely because tests are involved.
---

# Kirin Tor Release

Assemble proportionate release evidence without confusing preparation with publication.

## Establish the release target

- Inspect the current branch, working tree, version declarations, recent changes, and the user's requested release scope.
- Check `pyproject.toml`, `CHANGELOG.md`, relevant README sections, `.github/workflows/`, `frontend/`, and packaged `src/kirin_tor/web_assets/` only as needed.
- Treat uncommitted user changes carefully. Do not tag, push, upload, publish, or overwrite distribution artifacts unless the user explicitly asks for that action.

## Verify the deliverable

Choose checks that fit the release:

- Run the full relevant Python suite for an actual release candidate; include focused diagnosis if it fails.
- Typecheck and build the frontend when the release contains or packages frontend changes, then verify the intended asset handoff.
- Build and inspect the wheel when Python packaging or bundled assets changed. A smoke installation may verify the CLI and local web entry point.
- Check version, documentation, changelog, package metadata, generated artifacts, and CI configuration for obvious drift.
- Use CI for operating-system evidence when available; do not imply that one local machine proves the full matrix.

Avoid ceremonial files, approval ledgers, or exhaustive reports for this internal tool. A concise checklist with commands and outcomes is enough.

Distinguish local verification, CI results, packaging readiness, publication, and human acceptance. Stop before any external release action that was not authorized.
