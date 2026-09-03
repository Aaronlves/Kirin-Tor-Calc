---
name: kirin-package-development
description: Develop, debug, or review Kirin Tor's community package system. Use for manifests, requirements, lockfiles, GitHub or local resolution, the content store, package authoring, provenance, templates, and related tests. Do not use for ordinary language-core work, documentation-only requests, or consumer workspace content.
---

# Kirin Tor Package Development

Make focused package-system changes while keeping community data separate from Kirin Tor's game-neutral core.

## Use current authority

- Inspect the relevant package implementation and local diff before changing package behavior.
- Read `docs/package-system-v1.md` for public protocol and authority boundaries. Consult other documents only when the change actually crosses into language syntax, records, or the browser workbench.
- Do not perform live package mutations or network operations unless the user's request includes them.

## Preserve the trust boundary

Apply these constraints when they are relevant to the requested change:

- Packages are data only. Do not add execution of package scripts, hooks, binaries, Python modules, or workflows.
- `kirin.packages.toml` records requested dependencies, `kirin.lock` records the resolved graph, and the content-addressed store is a rebuildable cache.
- Source, version, resolved commit or path, namespace, and canonical content digest retain distinct roles.
- Installed package documents and templates remain immutable inputs to a workspace; local authoring paths do not silently mutate cached content.
- Archive paths, redirects, counts, sizes, digests, dependency graphs, and staged replacement deserve stricter checks only when the change touches them.

Prefer the smallest change in `package_manifest.py`, `package_store.py`, `package_authoring.py`, workspace loading, CLI or workbench adapters, and their direct tests. Do not redesign the protocol for an internal implementation cleanup.

## Verify according to risk

- Run focused cases from `tests/test_package_system.py` for ordinary behavior.
- Add a targeted regression case for changed parsing, identity, graph, cache, archive, or atomicity behavior.
- Use broader safety and workspace tests when a trust boundary crosses modules.
- Do not require live GitHub access, the full suite, or a security audit for every package edit; use them only when the behavior under review needs that evidence.

State whether verification was offline, mocked, or live, and do not treat code tests as proof that community-authored game data is correct.
