# Changelog

## Unreleased

- Added syntax-defined finite discrete distributions with exact expectation, variance, outcome probability, mapping, explicit independent convolution/repetition, and conditioning; validation enforces units, exact normalization, non-empty conditions, finite bounds, and no sampling or implicit independence.
- Added syntax-defined finite pure recurrences with constant or statically bounded integer step counts, unit preservation, cycle rejection, and a 1,000-step limit.
- Added syntax-defined finite analytical state models with exact transition-row validation, optional typed rewards, unique steady-state probabilities/rewards, hitting probabilities, and expected-step queries; singular systems fail explicitly and no event timeline is executed.

- Added the v1 data-only community Package protocol with strict TOML manifests, exact dependency versions, namespace ownership, transactional workspace requirements, deterministic JSON lockfiles, and content-addressed read-only caches.
- Added direct GitHub release resolution pinned to full commits, bounded safe archive extraction, canonical content hashes, offline verification, explicit restore/update/remove commands, and immutable local-package snapshots.
- Added `kt package new` and `kt package check` author workflows with a GitHub Actions template; community repositories remain the source authority and package code or hooks are never executed.
- Added workspace-defined and Package-distributed static Entry creation templates with optional chart configuration; Package templates are content-hashed, cached read-only, and validated before installation.
- Made new workspaces entirely game-neutral, removed the bundled WoW starter, and moved probability, integer/count domains, and physical time units into the game-neutral mathematical core.
- Added package provenance to CLI/browser views and immutable run snapshots, enforced declared package dependency and semantic boundaries, and preserved replay after package removal.
- Allowed data-only Package functions to transform workspace-supplied arguments without treating caller provenance as Package read authority; direct or undeclared Package reads remain rejected.

- Added the author-facing `.kirin` v1 source format as the sole workspace authority for entries, optional chart configurations, dimensions, units, and domains.
- Added the `kirin.workspace` marker plus the `.kirin` WoW starter package and examples.
- Switched `kt new` templates to `.kirin` and added in-memory workspace overlays for unsaved editor validation.
- Replaced the Textual TUI with the loopback-only `kt web` browser workbench and removed Textual/Plotext dependencies, terminal rendering, animations, narrow-layout logic, and TUI tests.
- Added multi-document draft buffers, live workspace diagnostics, atomic validated saves, external-change detection, graphical SVG/heatmap previews, and SVG/PNG/CSV export in the browser.
- Added entry-local Unicode aliases and presentation-only member labels, including default labels in explanations and generated charts.
- Added Chinese browser status and diagnostics with source locations and full-width punctuation suggestions; document selection shows the first `//` title alongside its path.
- Added `Ctrl+Space` completion for workspace members, Chinese labels and aliases, semantics, built-ins, and Chinese structural snippets.
- Built Documents, Calculate, Charts, Math, Runs, and Packages views while retaining structured documents as the only writable definition authority; diagnostics and formula previews remain in document context.
- Added canonical in-memory document drafts, unsaved-change decisions, multi-variant comparisons, player-label and percentage overrides, ad-hoc scan tables, chart-configured Entry drafts, aggregated diagnostic navigation, formula explanation, comparison run records, and replay.
- Added target-specific input guidance, baseline input solving, multi-variant comparison, dynamic chart tables, browser export coverage, and a tested World of Warcraft-style expected/equivalent mechanics capability audit.
- Added a Kirin Tor purple/gold/mana graphical theme without display-only animation controls.
- Moved template construction, override parsing, workspace indexes, comparison orchestration, artifact boundaries, and run recording into shared CLI/browser application services.
- Added a real Brewmaster workbook reproduction example for its damage, defense, and 1–20 target AOE/DPC/DPE tables, with regression checks against cached workbook values and real SVG/CSV export coverage.
- Reduced the public source model to `entry`; named parameter presets and optional chart configuration live inside entries, and output grouping is entirely author-defined.
- Added structured source/version metadata, dependency version checks, versioned lookup tables, interpolation, finite products, exact scaled units, player display formats, two-axis grids, and finite multi-variable system solving.
- Added searchable author groups, text-first temporary parameters, saved multi-curve Entry chart loading, two-input browser heatmaps, linked-equation solving, workspace-directory launch, and full Workbench-service regression coverage.
- Removed persisted `@template` metadata and `info:` fields, and unified constant and derived field declarations under `=`.
- Replaced the defense table's fixed dodge input with a 16-step finite expectation reproduced from the workbook's dodge sheet.

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
