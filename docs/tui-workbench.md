# Kirin Tor TUI workbench specification

## Product center

The TUI is a player-facing calculation and comparison workbench. Structured Kirin
documents remain the authoritative definitions, but document authoring is one
workspace rather than the application's default center.

The primary navigation uses ordinary terms familiar to players:

- **Calculate**: evaluate one target or compare multiple named variants;
- **Charts**: scan an input, inspect a table, and preview or export a chart;
- **Documents**: create, edit, validate, and save Kirin source documents;
- **Diagnostics**: inspect validation and dependency information;
- **Runs**: save, inspect, and replay reproducible calculations.

The UI must not replace these labels with invented magical vocabulary. Kirin Tor
identity is expressed through the eye mark, color, borders, and restrained motion.

## Authority and state

Kirin documents are the writable authority for entries, inputs, formulae,
entry-local presets, semantic declarations, output groups, and saved plot configurations. Calculations,
comparisons, charts, indexes, completion candidates, and UI controls are derived
views and must never silently write back to source documents.

The workbench may calculate from a complete, valid in-memory overlay containing
unsaved drafts. Such a result is visibly marked as based on unsaved changes. If
the overlay becomes invalid, no new result is produced; an earlier result may
remain visible only when marked stale.

Saving a run or exporting a durable artifact requires all participating source
documents to be saved and valid. Creating a plot from a curve exploration
creates an unsaved source draft and opens it in Documents.

## Calculation request

A calculation selects one output target and one or more named variants. Each
variant contains:

- an optional entry-local preset;
- zero or more temporary input overrides;
- the same numerical precision and display rules as the comparison;
- one result or one isolated error.

All variants in one comparison use the exact same validated workspace revision.
The first variant is the baseline. Numeric variants display exact and approximate
values, units, absolute difference, and percentage difference from the baseline.
Boolean results omit numeric differences. A failed variant does not erase valid
peer results.

The Calculate view may solve one numeric input for a requested output value and
optional range, or solve a finite linked system for several inputs. It uses the
first variant as the visible baseline so the applied preset and temporary inputs
are not implicit. Target search and order use author-declared groups; the UI does
not inject game-specific categories. Input edits are available as a typed form,
with the compact assignment field retained for advanced entry.

## Document lifecycle

`Ctrl+N` opens a new-document dialog for Entry or Plot. An Entry may start from
Blank, Data, Model, or Semantics templates. The type determines the folder; the
user supplies only the stable document ID.
Creation adds a draft to the in-memory overlay and does not write a file.

The UI distinguishes new, modified, and saved documents. Closing a modified
document and quitting with any dirty draft require an explicit save, discard, or
cancel decision. Saving validates the complete overlay and atomically replaces
all dirty source files only after validation succeeds.

CLI and TUI creation must use the same template builder. The TUI must not keep a
private template implementation.

## Charts

Charts may originate from a saved Plot document or an ad-hoc scan. Curve scans
select one numeric input axis, a finite range, point count, one or more output
targets, an optional preset, and temporary overrides. A grid scan selects two
numeric axes and one output and renders a heatmap. The chart and its data table
use one calculation result.

The user may instead scan the variants currently configured in Calculate. Every
curve uses the same axis and workspace revision and keeps the variant's preset
and overrides. A multi-variant interactive chart or heatmap cannot be converted
to a Plot source silently when its shape exceeds the saved Plot schema; its full
data remains exportable.

Animation is presentation only. A scan is computed once, then revealed or
transitioned without recomputing points per frame. Motion has Full, Reduced, and
Off modes and is disabled in automated tests.

## Runs

Durable runs use the existing immutable run-record format with embedded definition
snapshots. The TUI exposes the same save and replay services as the CLI; it does
not invoke CLI subprocesses. Replay results identify result match and environment
or dependency drift.

## Shared application layer

CLI and TUI are adapters over shared application services. Shared code owns:

- document draft construction and exclusive creation;
- override parsing and calculation/comparison requests;
- workspace indexes for grouped targets, inputs, presets, and plots;
- curve, grid, system-solve, and chart requests;
- run saving and replay orchestration;
- stable errors and artifact path rules.

The mathematical engine, structured source parser, and run-record authority are
not reimplemented in the TUI.

## Acceptance boundary

The redesigned TUI is accepted only after tests exercise real temporary
workspaces and real file writes for creation, validation, atomic saving, chart
export, run recording, and replay. A final player-oriented review checks whether
common theorycrafting tasks can be completed without dropping to the CLI.

The engine audit is separate from UI acceptance. It asks whether game mechanisms
can be defined for expected-value and equivalent-value calculations; real-time
combat simulation, event scheduling, agent behavior, and stochastic encounter
simulation are explicitly out of scope.
