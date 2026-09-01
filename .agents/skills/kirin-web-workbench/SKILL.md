---
name: kirin-web-workbench
description: Develop, debug, review, or document the Kirin browser workbench in the calculator project. Use for the React and TypeScript interface, CodeMirror editing, ECharts previews, workbench state, the local Python web adapter, packaged web assets, and directly related tests. Do not use for changes confined to mathematical semantics, package resolution, or release preparation.
---

# Kirin Web Workbench

Make focused browser-workbench changes while preserving Kirin's text-first product boundary.

## Use current boundaries

- Inspect the current branch, local diff, and the files involved in the request. The frontend has replaced the earlier Textual interface, so do not rely on old TUI assumptions.
- Read `docs/web-workbench.md` when behavior, layout, saving, security, or CLI parity matters. Read `frontend/README.md` when the build or packaged-asset handoff matters.
- Keep local `.kirin` documents as the only writable authority. UI state, indexes, previews, generated artifacts, and API payloads are adapters or projections.
- Preserve unrelated user changes.

## Implement proportionately

Trace only the relevant slice through components, hooks, TypeScript types, API calls, `workbench.py`, and `web.py`. Avoid introducing a second document model or a broad frontend refactor for a small request.

When relevant, preserve these behaviors:

- Unsaved document overlays may be validated and explored, but durable run records refer to saved sources.
- Save All remains atomic and detects external changes. Package documents remain read-only.
- Canonical IDs remain stable beneath Chinese-friendly labels, aliases, completion, and diagnostics.
- The local server's loopback, session-token, Host/Origin, and response-header protections are not weakened accidentally.

## Verify according to risk

- For TypeScript behavior, run the frontend typecheck or build when it is a useful check.
- For Python adapter behavior, run the relevant tests such as `tests/test_web.py` or `tests/test_workbench.py`.
- Use the available Playwright workflow for real interaction, editor, layout, or browser-state problems when browser evidence is material. Do not require screenshots or end-to-end automation for every small UI edit.
- Expand verification only when the change crosses the frontend/API boundary or affects saving, artifacts, records, or local-server security.

Report the checks actually run and keep human visual acceptance distinct from build or test success.
