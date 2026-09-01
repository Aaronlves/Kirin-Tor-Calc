# Changelog

## Unreleased

- Prevented deleted game starters and obsolete modules from leaking out of a stale setuptools build directory; distribution CI now seeds an old layout and verifies the resulting wheel member-for-member against the current game-neutral source tree.
- Added visible insertion-cursor, active-line, focused/unfocused text-selection states, plus live line/column and selection counts in the editor status bar.
- Added an in-app, read-only Kirin syntax reference with Chinese and canonical-term search, concise rules, and copyable complete examples that are strictly validated against the current language implementation.
- Added workspace-wide search and draft-only replacement, save-before-write change review with read-only Git history, contextual syntax-reference links, and base/draft/disk three-way conflict merging.
- Added clean-workspace document path moves, validated duplication into a new unsaved entry, and dependency-safe removal into a recoverable `.kirin` trash area; entry IDs, aliases, and mathematical semantics remain source-authored.
- Added process-isolated cancellable browser operation jobs with truthful lifecycle stages while retaining mathematical timeouts.
- Added frontend CI gates for TypeScript, Chromium/Firefox/WebKit Playwright coverage, axe-core accessibility checks, Chromium/WebKit visual baselines, packaged asset synchronization, bundle budgets, and a 100-document validation benchmark.

## 0.3.0rc1 — 2026-09-01 (pre-release)

- Made `.kirin` v1 documents the sole editable workspace authority and reduced the public source model to `entry`; named presets, output groups, chart configuration, semantics, aliases, labels, and provenance now live in or derive from ordinary source documents.
- Made new workspaces game-neutral, removed privileged built-in game data, and retained probability, bounded integer/count domains, and physical time as neutral mathematical vocabulary.
- Added exact finite discrete distributions, pure bounded recurrences, and finite analytical state models with explicit normalization, unit, uniqueness, singularity, and computation limits; no sampling, implicit independence, or event timeline is inferred.
- Added versioned lookup/interpolation, finite products, exact scaled units, structured source metadata, dependency-version checks, player display formats, two-axis grids, and finite multi-variable system solving.
- Added the data-only community Package v1 protocol with strict manifests, exact dependency versions, namespace ownership, deterministic lockfiles, content-addressed read-only caches, bounded GitHub release extraction, offline verification, and immutable local snapshots.
- Added Package authoring and lifecycle commands, static workspace/Package creation templates, package provenance in CLI/browser projections and run snapshots, and replay that remains possible after Package removal; Package code and hooks are never executed.
- Replaced the Textual interface with the loopback-only `kt web` browser workbench and removed Textual/Plotext dependencies, terminal rendering, animations, narrow-layout logic, and obsolete TUI tests.
- Consolidated the browser around authoritative Documents and a derived Relationship Graph; Runs and Packages are workspace tools, while calculations, scans, transforms, solving, comparison, export, and replay continue through shared CLI/browser application services.
- Added multi-document in-memory drafts, debounced full-workspace validation, atomic Save All, external-change comparison, bounded restart-safe draft recovery, and read-only result, chart, formula, diagnostic, and relationship projections.
- Added Editor/Split/Preview focus modes, automatic source-default previews, expanded chart views, explicit SVG/PNG/CSV export, and bidirectional navigation between source and derived projections without adding editable form state to the inspector.
- Added Chinese-aware syntax highlighting, completion, structural snippets, labels, aliases, diagnostics, deterministic full-width punctuation fixes, safe whitespace formatting, document outlines, folding, find/replace, line navigation, and workspace document/symbol quick opening.
- Added tolerant symbol and reference indexing for incomplete drafts, hover and parameter information, definition navigation, alias-aware reference listing, validated formal-member rename, and undo history retained across document switches.
- Added member/document dependency graphs derived only from validated expression references, including local direction/depth exploration, current-document marking, connection counts, keyboard-readable fallbacks, and source traceability.
- Added immutable run-record provenance, definition snapshots, implementation/environment fingerprints, artifact hashes, failure replay, plot regeneration, multi-variant comparison records, and environment-drift reporting.
Breaking changes:

- YAML and the Textual authoring workflow are no longer parallel authorities; `.kirin` is the only editable definition format.
- New workspaces no longer install a privileged WoW starter, and persisted `@template` metadata and `info:` fields are removed.
- The browser inspector no longer accepts temporary calculation fields; experiments must be authored as source defaults or named presets.

## 0.2.0 — 2026-09-01

- Made named dimensions, units, and reusable numeric/boolean domains user-declared semantics on ordinary entries.
- Added the data-only `wow` initialization package; it has no privileged runtime behavior.
- Qualified external input identities as `entry_id.input_name`, with unqualified names accepted only when unambiguous.
- Added strict source validation, line/column diagnostics, aggregated checks, and default/preset constraint evaluation.
- Added integer and finite-value domains, fixed boolean fields, unit-polymorphic exact zero, and symbolic derivatives with additional free variables.
- Moved expression expansion and scan evaluation under process-enforced timeouts; added cross-platform process selection.
- Added safe, atomic, no-clobber artifact writes and workspace path containment by default.
- Upgraded run records to format v2 with source snapshots, implementation/environment fingerprints, artifact hashes, failure replay, and plot regeneration.
- Added `kt explain`, `kt new entry`, and `kt new plot`.
- Added Windows/macOS/Linux CI configuration and expanded automated coverage.

Breaking changes:

- Preset and CLI parameter identities are qualified when a short name is ambiguous.
- Named non-dimensionless units must be declared by an ordinary entry or starter package.
- Run format v1 is explicitly incompatible with run format v2.
