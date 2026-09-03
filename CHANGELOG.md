# Changelog

## Unreleased

- Unified neutral hover feedback and token-driven component transitions, and made relationship-node
  selection preserve the current layout while exposing role, source, formula, and lineage guidance.
- Stabilized all segmented-control selection surfaces without runtime geometry, expanded and
  highlighted Mantine menus with tool descriptions, widened and reflowed the Syntax Reference,
  and removed the bundled tutorial catalog, sources, API projection, and tutorial-only UI.
- Narrowed the supported browser and Playwright acceptance matrix to Chromium and WebKit while
  Firefox remains unable to start under Playwright 1.62.1 on macOS 27; this removes Firefox from
  the current support claim without treating the upstream launch failure as a Kirin Tor defect.
- Accepted exact percentage and compatible unit-quantity literals for static input defaults, and
  allowed delimiter-aware nested indentation in static and Process expression continuations.
- Added read-only bounded Process Analysis execution to the thin MCP server, with event traces
  omitted by default and no run record or artifact persistence.
- Raised the supported runtime to Python 3.12 or newer as a clean cutover, moved the
  cross-platform test matrix to Python 3.12 and 3.14, upgraded Matplotlib to the 3.11 line,
  removed the Python 3.9 `tomli` compatibility path, adopted the official MCP Python SDK v2,
  and moved package licensing metadata to the current SPDX form.
- Added a thin `kt mcp [WORKSPACE]` stdio server for durable source resources, the validated
  workspace index, the authoring contract, workspace/draft validation, exact static evaluation,
  target explanation, and single-source hash-guarded atomic writes. It reuses existing Kirin Tor
  services, exposes no browser-unsaved state or general execution surface, and creates no second
  source authority.
- Replaced the prefix-only editor-assistance path with one versioned authoring contract and
  cursor-contextual completion; added complete Process expression/runtime reference entries,
  dynamic Process/Scenario/Analysis symbols and direction-aware instance paths, Process locals,
  multiline expression completion and nested signature tracking, block indentation, line comments,
  exact reference deep links, token-sized diagnostics,
  quote/comment-safe punctuation fixes, aborted-request handling, and guaranteed revalidation of
  edits made while another validation is running. The former global completion and duplicated
  highlighter vocabulary are not retained as a compatibility mode.
- Consolidated language help into one Syntax Reference center and added a searchable official
  catalog of public declarations, signatures, contexts, required and optional fields, allowed
  values, defaults, limits, and short descriptions while retaining validated full examples.
- Tightened the sole `@kirin 2` language as a clean cutover: scalar field/function/output types
  are now preserved, enforced, and round-tripped; lowercase boolean literals have one meaning;
  Python-keyword or literal-reserved IDs, duplicate function parameters and block properties, unknown table or
  distribution properties, invalid leaf subtrees, noncanonical headers/source labels, and Scenario
  schedule-limit overflow are rejected instead of ignored or reinterpreted. No compatibility parser
  is retained for the previously accepted invalid forms.
- Preserved source labels in tolerant completion and added structure-type and type-field candidates
  from local and locked Package sources, including qualified owner and declared-type details.
- Retained explicit Package feature-line compatibility for 0.3 Packages on Kirin Tor 0.4 while
  continuing to apply the current strict parser, graph validation, and engine checks.
- Kept the browser workbench available when a locked Package graph cannot load: local documents,
  recovery, built-in/workspace templates, and Package repair controls remain accessible while
  validation-dependent operations stay blocked and the Package error remains visible.
- Added authenticated in-session workspace switching with staged server replacement, running-job
  exclusion, user-local launch preference updates, explicit dirty-draft recovery, and complete
  client-state isolation across the switch.
- Unified Workbench destination metadata, semantic heading and landmark levels, named floating-layer
  tokens, and in-Drawer subviews so management and confirmation flows no longer stack modal Drawers.

## 0.4.0 — 2026-09-03

- Added up to 64 independently named static charts per Entry with stable `ENTRY.CHART` identities, responsive and deferred-rendering static/Process chart grids, individual expansion/export, and explicit export-all.
- Added an in-flow non-authoritative result trial area that compares temporary dependency-input values with source defaults, resets without touching source, can append an unsaved preset draft to the existing editor, and saves run records only against clean durable source.
- Unified calculation, Process, and relationship canvases under one registered Kirin Tor ECharts theme; added exact/unit-aware axis and item Tooltips plus pointer and keyboard source navigation without exposing arbitrary ECharts options to source documents.
- Consolidated Workbench color, typography, spacing, size, shape, shadow, motion, and layer decisions into one generated eight-family design-token system consumed by Mantine, CSS, CodeMirror, and ECharts, with build-time drift enforcement and reduced-motion handling.
- Kept CodeMirror text selections visible above the active-line surface while retaining distinct focused and unfocused selection colors and status-bar selection counts.
- Replaced CodeMirror's default find/replace skin with localized, rectangular, token-governed controls and explicit hover, checked, focus, and selected-match states.
- Kept the editor focus frame continuous above CodeMirror gutters, search panels, active lines, and horizontally overflowing content without intercepting pointer input.
- Extended document-row hover and selection surfaces through their trailing action buttons, and centered compact-navigation labels beneath their icons.
- Unified host, CodeMirror, and ECharts tooltip surfaces; confined editor and chart tooltips to their owning regions and rejected native host `title` tooltips at the design-system gate.
- Raised muted and quiet text tokens to preserve WCAG AA contrast on selected tutorial surfaces.

## 0.3.0rc3 — 2026-09-03 (pre-release)

- Added credential-free PyPI publication through GitHub trusted publishing and documented the persistent `uv tool` installation, upgrade, launch, and removal path.

## 0.3.0rc2 — 2026-09-03 (pre-release)

- Added typed bounded-Process expression, Process, Scenario, Policy, and Analysis AST/IR; symbolic domains; canonical round trips; exact safe expression evaluation; transition and static batch conflict validation; explicit phase mapping; and visible event/decision fuel preflight.
- Added the deterministic bounded-Process runtime with exact time and flow, phase-start snapshots, explicit reducers, stable event identities, keyed schedule/replace/cancel, guarded composite actions, state/domain checks, dynamic fuel enforcement, stop conditions, and replay-stable traces.
- Added exact finite random-path enumeration, source-declared conditional and fixed-sequence policies, and named `run`, `compare`, deterministic bounded `optimize`, `reach`, finite-state `steady`, and repeated-state `cycle` Process analyses. `kt analyze` returns a structured result and saved runs replay through the same Analysis entry without implicit sampling.
- Added typed Scenario Measures over public observation snapshots, public output events, and engine time: final value, extrema, event sum/count, condition duration, explicit-default first occurrence, stop time, maximum drawdown, total variation, and time-weighted variance. Scenario Objectives now provide named constrained lexicographic goals; one Analysis may optimize several independently and returns every tied optimal strategy with every Measure plus an explicit `exact_global` proof record for exhaustive finite policy search.
- Added decisions triggered after public events, on false-to-true state conditions, and at a bounded number of free continuous action times. Affine non-strict flow crossings are solved at exact rational roots; unproved flow crossings are rejected. Explicit `adaptive_dyadic` tolerance and evaluation budgets produce replayable `best_found` results without claiming a fixed grid or global proof; effective solver controls and explicit absent approximations are retained across request, result, and run record.
- Added named Scenario input variants. An optimize Analysis can select several variants, independently search every declared Objective for each one, and return a structured variant-by-objective result containing the actual public input overrides, strategy trace, proof, constraints, and all Measures.
- Added multiple derived charts per Process Analysis: same-unit trajectory overlays for run/compare/optimize/reach/cycle with public-event/decision markers, two-decision search surfaces, author-directed Pareto projections with an explicit nondominated frontier, and variant comparisons. Chart data is included in analysis results, while `kt analyze --export-charts` performs explicit workspace-confined SVG/CSV export.
- Added strict finite output expectation for random Process analyses: every finite branch is executed to a complete trajectory, every Measure is evaluated per outcome, and numeric Measure expectations are then combined with exact probabilities. Results label this separately from deterministic representative-input scenarios; no sampling is substituted.
- Added Process Analysis to the browser workbench index and in-flow document preview, including variant/objective summaries, proof labels, release times, interactive multi-chart selection, and explicit export-all. Added Process authoring snippets, top-level outline/highlighting vocabulary, contextual syntax help, and synchronized packaged frontend assets.
- Added lightweight local-source revision polling so Agent- or tool-written `.kirin` documents appear automatically, clean buffers reload and revalidate, and dirty drafts open the existing conflict comparison without exposing Agent or CLI activity. The in-app authoring reference, command palette, empty-workspace guidance, and conflict handling now link this file-mediated workflow to its authority limits without inventing Agent syntax, completion, or highlighting.
- Aligned CodeMirror highlighting and contextual syntax recommendations with the current Process/Scenario/Analysis grammar: current nested declarations and analysis controls are highlighted, prose fences remain opaque author text, obsolete cycle/state-model resource vocabulary is no longer colored as current syntax, and completion help prefers the inserted construct over its generic candidate kind.
- Replaced public `.kirin` v1 section syntax with the single-declaration `@kirin 2` grammar; migrated built-in tutorials, examples, templates, Package scaffolds, syntax help, completion, highlighting, and tests. V1 source is now rejected rather than maintained as a second public dialect.
- Added closed reusable structure types, named typed objects, exact percentage and numeric-unit literals, and statically resolved multi-level paths such as `entry.skill.coefficient.periodic`.
- Completed the single-language Process cutover: removed the old `recurrence`, `state_model`, and `cycle` declarations, state-model expression functions, `cycle_step`/`cycle_profile` contracts, `kt cycle`, and the independent fixed-timeline executor. Bounded iteration, finite random transitions, fixed policies, resources, cooldowns, charges, reachability, steady state, and cycle proofs now use ordinary Process/Scenario/Analysis semantics.
- Added Workbench Extension Plugin protocol v1 with strict local manifests, immutable content-addressed snapshots, separate user-local executable approvals, requirements/lock files, offline verification, enable/disable/remove/update commands, and `kt web --safe-mode` recovery.
- Added sandboxed document renderers, top-level plugin views, workspace tools, declarative commands, and composable layout Profiles. Plugin frames receive permission-filtered validated projections through a bounded message protocol and cannot access the host DOM, session token, filesystem, network, Save All, or Package mutation.
- Added a game-neutral fictional talent-tree example and focused Python, CLI, HTTP-security, TypeScript, and real-browser plugin coverage; the example demonstrates source navigation and host-brokered evaluation without shipping real game data.
- Added an empty-workspace welcome surface and a persistent tutorial library with three strictly validated, game-neutral `.kirin` examples; viewing remains read-only and explicit copying creates only an unsaved source draft.
- Prevented deleted game starters and obsolete modules from leaking out of a stale setuptools build directory; distribution CI now seeds an old layout and verifies the resulting wheel member-for-member against the current game-neutral source tree.
- Added visible insertion-cursor, active-line, focused/unfocused text-selection states, plus live line/column and selection counts in the editor status bar.
- Added an in-app, read-only Kirin Tor syntax reference with Chinese and canonical-term search, concise rules, and copyable complete examples that are strictly validated against the current language implementation.
- Added workspace-wide search and draft-only replacement, save-before-write change review with read-only Git history, contextual syntax-reference links, and base/draft/disk three-way conflict merging.
- Added clean-workspace document path moves, validated duplication into a new unsaved entry, and dependency-safe removal into a recoverable `.kirin` trash area; entry IDs, aliases, and mathematical semantics remain source-authored.
- Added process-isolated cancellable browser operation jobs with truthful lifecycle stages while retaining mathematical timeouts.
- Added frontend CI gates for TypeScript, Chromium/Firefox/WebKit Playwright coverage, axe-core accessibility checks, Chromium/WebKit visual baselines, packaged asset synchronization, bundle budgets, and a 100-document validation benchmark.

Breaking changes:

- All editable and Package `.kirin` documents must use `@kirin 2`; v1 section syntax is no longer accepted.
- The pre-release `recurrence`, `state_model`, `cycle`, `cycle_step`, and `cycle_profile` syntax and `kt cycle` command are removed. Unsupported source is rejected by the ordinary v2 grammar; no migration-only parser or authoring compatibility is retained.
- Structure `type` bodies accept declared fields only; the undocumented generic interface mapping layer is removed.
- `kirin.workspace` accepts only the `@kirin-workspace 1` marker plus blank lines or comments; workspace settings, including pre-release starter metadata, are rejected.
- `parse_kirin_source` and `load_kirin_document` now return typed source containers instead of tuples; callers use explicit `.raw`, `.positions`, `.process_asts`, `.scenario_asts`, `.analysis_asts`, `.text`, and `.sha256` fields.

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
