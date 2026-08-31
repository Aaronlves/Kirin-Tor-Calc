# Changelog

## Unreleased

- Added the author-facing `.kirin` v1 source format as the sole workspace authority for entries, scenarios, plots, dimensions, units, and domains.
- Added the `kirin.workspace` marker plus the `.kirin` WoW starter package and examples.
- Switched `kt new` templates to `.kirin` and added in-memory workspace overlays for unsaved editor validation.
- Added the optional Textual single-editor workbench with multi-document draft buffers, live workspace diagnostics, Plotext terminal previews, validated saves, and one-key SVG/CSV plot export.
- Added entry-local Unicode aliases and presentation-only member labels, including default labels in explanations and generated charts.
- Added Chinese TUI status and diagnostics with source locations and full-width punctuation suggestions; document selection now shows the first `//` title alongside its path.
- Added Kirin-specific editor highlighting plus `Ctrl+Space` completion for workspace members, Chinese labels and aliases, semantics, built-ins, and Chinese structural snippets.

## 0.2.0 — 2026-09-01

- Made named dimensions, units, and reusable numeric/boolean domains user-declared semantics on ordinary entries.
- Added the data-only `wow` initialization package; it has no privileged runtime behavior.
- Qualified external input identities as `entry_id.input_name`, with unqualified names accepted only when unambiguous.
- Added strict source validation, line/column diagnostics, aggregated checks, and default/scenario constraint evaluation.
- Added integer and finite-value domains, fixed boolean fields, unit-polymorphic exact zero, and symbolic derivatives with additional free variables.
- Moved expression expansion and scan evaluation under process-enforced timeouts; added cross-platform process selection.
- Added safe, atomic, no-clobber artifact writes and workspace path containment by default.
- Upgraded run records to format v2 with source snapshots, implementation/environment fingerprints, artifact hashes, failure replay, and plot regeneration.
- Added `kt explain`, `kt new entry`, `kt new scenario`, and `kt new plot`.
- Added Windows/macOS/Linux CI configuration and expanded automated coverage.

Breaking changes:

- Scenario and CLI parameter identities are now qualified when a short name is ambiguous.
- Named non-dimensionless units must be declared by an ordinary entry or starter package.
- Run format v1 is explicitly incompatible with run format v2.
