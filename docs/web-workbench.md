# Kirin Tor browser workbench

## Product boundary

`kt web [WORKSPACE|SOURCE.kirin]` starts a local graphical workbench. It is an adapter over the same workspace, engine, operation, Package, artifact, and run-record services used by the CLI. It does not introduce another document model: local `entries/**/*.kirin` remain the only writable authority.

Explicitly installed Workbench Extension Plugins may add sandboxed document renderers, views, tools, commands, and layout profiles. They remain projections inside the stable host and cannot replace source validation, saving, Package resolution, recovery, or local-server authorization. Their executable approval is separate from Community Package installation. See [Workbench Extension Plugin protocol v1](workbench-plugin-system-v1.md).

The Package and Workbench Plugin management surfaces include explicit read-only community
discovery drawers. They query the fixed GitHub topics `kirin-tor-package` and
`kirin-tor-plugin` through the authenticated local Python adapter, show only current-protocol
manifests, and provide repository links without remote installation. Topic membership remains a
self-declaration; discovery writes no workspace, lock, approval, store, or personal-data record.

The server binds only to a loopback address. Each process creates a random session token, transfers it to browser session storage on first load, and removes it from the visible URL. API requests require that token and an allowed local Host and Origin. Responses disable caching, framing, referrer forwarding, MIME sniffing, inline scripts, and cross-origin connections. Runtime-generated CSS is allowed because CodeMirror mounts its base and theme styles dynamically; executable scripts remain same-origin packaged assets.

The workbench keeps the following authority boundary:

| State or surface | Author-editable | Persistence | Authority role |
| --- | --- | --- | --- |
| Local `.kirin` buffer | In the official editor | Unsaved overlay until Save All | Editable draft over the same source model; not durable authority |
| Local `.kirin` file | Through validated Save All or an external local editor/Agent | Durable workspace content | Authoritative local definition; validity is established separately |
| Package `.kirin` file | No | Locked Package content | Read-only authoritative dependency |
| Agent prompt, transcript, or activity state | No Workbench editing contract | Outside Kirin Tor | Not model authority and not displayed or recorded by Kirin Tor |
| Completion and symbol index | No | Rebuilt in memory | Tolerant authoring projection, not validation evidence |
| Bundled syntax reference | No | Versioned frontend content | Searchable writing aid whose examples are checked by the current validator |
| Bundled tutorial source | No | Versioned application resource | Game-neutral learning source; excluded from the workspace until explicitly copied |
| Result, chart, formula, diagnostic, and relationship inspector | No | Ephemeral | Derived projection of the current valid workspace overlay |
| `.kirin/workbench-recovery.json` | No direct editing contract | Bounded ignored control state | Crash/restart recovery only; never evaluated independently |
| Run snapshot or exported artifact | No definition editing | Durable output | Immutable evidence or export, not current source authority |

## Views and CLI parity

- Documents covers CLI list/show/new/check and adds multi-document drafts, atomic Save All, external-change detection, integrated diagnostics, formula explanation, completion, result evaluation, optional chart preview/export, and creation-time templates. An empty workspace replaces the three-pane editor with a welcome surface for the bundled basic-model, preset-comparison, and scan/chart tutorials.
- Relationship Graph derives global document and member projections from validated expression references and Process composition, then provides source navigation. Members include inputs, fields, functions, tables, finite distributions, objects, outputs, processes, scenarios, and analyses. Document projections use a deterministic circular layout; member projections retain a force layout. The document inspector shows a local zero-, one-, or two-hop projection from the same data, can limit traversal to dependencies or users, marks members of the current document, and reports both connection counts for the selected node.
- Syntax Reference is a read-only drawer opened from the navigation rail, workspace menu, or command palette. It searches Chinese labels, canonical syntax terms, external-Agent authoring boundaries, rule summaries, and example source. Each topic contains a complete copyable `.kirin` example; copying never inserts into or otherwise mutates the active editor. The reference is a writing aid rather than an alternative parser or validation result.
- Workspace Search searches local drafts, disk sources, and locked Package sources together. Replace All skips Package sources and returns ordinary unsaved local overlays; it never writes directly to disk. Change Review compares every dirty buffer with its opening or creation baseline before Save All and separately exposes read-only Git log and working-tree summaries when the workspace belongs to a repository.
- Runs is a workspace drawer for replay and explicit artifact regeneration.
- Packages is a workspace drawer for add, add-path, list, update, remove, restore, verify, Package new/check, and workspace initialization.

The Web adapter exposes shared compare, scan, grid, transform, differentiation, and solve operations so any task-specific browser flow can reuse the existing mathematical implementation. Transform, differentiation, solve, scan, and grid also have public CLI commands; multi-variant comparison currently remains an application/Web-adapter operation. The current interface does not expose generic parameter forms for these advanced operations or divide them into permanent Calculate, Charts, or Math pages. Authors use the corresponding CLI commands where available until a concrete browser workflow is adopted. A chart appears in a document only when its source defines `x/range/points/y`.

Browser operations run as isolated local jobs with explicit queued/running/completed/failed/cancelled states. The header reports active jobs and their current stage and can terminate their process trees; server-side mathematical timeouts remain a second independent bound. The UI reports truthful stages rather than estimating an unsupported completion percentage.

The Web adapter accepts valid unsaved document overlays for validation and non-durable exploration. A run record cannot be created until its documents have been saved, so the immutable record always names durable source authority.

Bundled tutorials are complete `.kirin` files, not form state or an alternate semantic model. Viewing one reads only the installed application resource. Copying asks for a formal document ID, replaces the example header and self-qualified references through the ordinary template expander, and returns an unsaved local draft. The source is not written until the author invokes Save All.

Artifact paths stay inside the workspace by default and existing files are not overwritten. Document chart export and replay expose separate explicit controls for overwrite and working outside the workspace, matching the corresponding CLI authority expansion.

## Text-first interaction

The document inspector is read-only: Preview and Formula derive automatically from the current valid draft and its source-declared defaults. It must not expose temporary-parameter, preset, timeout, or other calculation-input fields, and it must not require Calculate, Generate Chart, or Explain Formula actions. Output and Result/Chart selectors choose which projection to inspect; they do not supply calculation parameters or modify source. To change the inspector's default result, the author edits an input default in `.kirin`; reusable alternatives remain named source presets consumed by explicit CLI or separate task-specific workflows rather than inspector state. Explicit export controls remain separate because paths, overwrite, and workspace-boundary expansion require an intentional author action.

Diagnostics live beside the document editor rather than in a duplicate top-level page. They retain stable codes and source locations, add Chinese author-facing explanations, and navigate back to the failing document and position. Formula expansion appears in the same document context.

Preview results, chart definitions, formula explanations, diagnostics, and relationship nodes expose source navigation when their validated projection carries a source coordinate. Navigation restores Split focus mode, opens the authoritative `.kirin` document when necessary, and focuses the defining line instead of creating an editable projection.

The editor adds a tolerant authoring projection over complete or incomplete drafts. This projection may offer navigation and completion while strict workspace validation is failing, but it does not make an incomplete draft executable or saveable.

## Workbench Extension Plugins

The stable host discovers contributions only from enabled, locally approved, API-compatible plugin snapshots whose current cache content matches `kirin.plugins.lock`. The default Profile retains `documents` and `graph` and appends active plugin views; a contributed Profile supplies ordered view and tool lists, a default view, and an initial document focus mode. Switching Profile changes composition and layout state only. The workspace menu always retains Plugin management and a route back to the default Profile.

A matching document renderer is selected by validated canonical entry ID, ID prefix, or Package name. It receives a structured projection only after the complete overlay validates. The author can switch back to the generic result/chart projection without changing source or plugin state. Top-level plugin views and tools receive only the workspace summary unless their manifest declares another supported permission.

Every executable surface is an iframe with `sandbox="allow-scripts"` and no same-origin permission. Static module assets may be fetched from the exact loopback workbench origin, but the frame has no session token and its response sets `connect-src 'none'`. Host actions are limited to validated source navigation and bounded evaluation of an existing workspace target when the matching permission was declared. Save, recovery, Package mutation, plugin mutation, arbitrary operation forwarding, host DOM access, and filesystem access are never delegated.

Plugin installation, update, enable, disable, removal, verification, activation status, digest, and contribution counts are available from the built-in Plugins drawer and the corresponding CLI. `kt web --safe-mode` returns no active contributions and refuses plugin assets even when workspace control files request them. A malformed plugin control file is reported without preventing the core Safe Mode workbench from opening. Full protocol details are in [Workbench Extension Plugin protocol v1](workbench-plugin-system-v1.md).

| Command | Shortcut | Contract |
| --- | --- | --- |
| Save All | `Mod+S` | Strictly validates and atomically saves all writable drafts |
| Completion | `Ctrl+Space` | Searches built-ins, snippets, disk sources, and in-memory drafts |
| Find/replace | `Mod+F` | Edits the current in-memory document |
| Go to line | `Mod+G` | Navigates within the current document |
| Document outline | `Mod+Shift+O` | Navigates the tolerant current-document symbol index |
| Safe formatting | `Mod+Shift+F` | Normalizes safe whitespace without schema re-rendering |
| Go to definition | `F12` or Mod-click | Opens the indexed source definition, including another document |
| Definitions and references | `Shift+F12` | Lists definitions, direct references, and alias-mediated uses |
| Validated rename | `F2` | Produces validated writable overlays; it never edits Package source |
| Workspace command/open search | `Mod+K` or `Mod+P` | Searches views, tools, documents, and symbols |

Workspace Search and Change Review are available from the workspace menu and command palette. Search results navigate to exact source coordinates. A workspace replacement always opens Change Review when it produces edits, so Save All remains a separate author decision.

The fold gutter collapses indented declaration blocks and prose blocks. Hover shows a symbol's canonical identity, kind, signature, and unit or domain detail; completion details, symbol hover, and diagnostics can open the relevant bundled syntax topic without inserting text. The status bar shows the active function signature and parameter number together with the current line/column or selected character/line count. Focused and unfocused selections remain visibly distinct, and the insertion cursor and active line use the same ember interaction accent. The command palette also exposes Editor Only, Split, and Preview Only layout modes. Focus mode is remembered locally and changes only layout visibility, never source or projection semantics.

Safe rename updates the definition, local short references, and qualified cross-document references together while retaining Chinese aliases. It first produces ordinary in-memory `.kirin` overlays and validates the resulting workspace; Package definitions and Package source remain read-only. Formatting is deliberately source-preserving: it normalizes indentation tabs, trailing whitespace outside prose fences, excess blank lines, and the final newline without re-rendering or deleting comments. Known full-width punctuation diagnostics expose an explicit quick fix but are never rewritten automatically.

Cursor movement links source to the currently visible result, formula, or local-relationship projection when both sides identify the same symbol. This complements the existing projection-to-source controls without making preview state authoritative.

CodeMirror has an explicit accessible name and visible focus outline. Canvas relationship graphs and calculation charts expose a collapsible keyboard-readable node or data list. Generated charts can be expanded into a full-window preview without creating another editable surface.

Entries containing named Process Analysis declarations expose a `过程` projection beside ordinary
results and static charts. The projection runs the same backend Analysis, summarizes non-optimization
operations by their actual path/policy/state count, shows every tied variant/objective optimum with
proof level, release times and all Measures, and allows
selection among all declared trajectory/search charts. `导出全部图表` is an explicit operation that
uses the source-declared SVG/CSV paths and the same workspace confinement and overwrite checks; live
preview rows and rendered canvases remain derived, read-only state.

## Interface system

The workbench uses one explicit grid hierarchy rather than stacking framework offsets and percentage split panes:

- the application shell is a two-column, two-row grid with a 224 px navigation rail and a 64 px header; below 1320 px the rail defaults to its 64 px compact state, and the author choice is remembered locally;
- the document view is a three-track grid with a 216–272 px source index, a flexible editor, and a 280–360 px inspector; the header switches between Editor Only, Split, and Preview Only focus modes, and remembers the author's choice locally;
- page-level tools use twelve-part proportions, including 9/3 for the relationship graph and 4/8 for run history;
- adjacent workbench tracks share a single 1 px divider and never add their own outer margins.

The spacing scale is 4, 8, 12, 16, 24, and 32 px. Toolbars are 48 px high; buttons, inputs, and icon buttons are 32 px high. Actions have four stable levels: ember-filled primary, neutral-outline secondary, borderless toolbar, and red destructive. Green, amber, and red are reserved for success, dirty/warning, and error states. All controls are rectangular and use the same focus outline. The minimum supported content width is 1120 px; smaller layouts are not treated as an independent mobile product.

## Static creation templates

Templates are complete Entry source skeletons used only at creation time. A template may include optional chart fields. The workbench lists:

- built-in game-neutral skeletons;
- bundled game-neutral tutorial sources;
- workspace templates under `templates/entries`;
- read-only Package templates at the same relative paths inside locked Package content.

Saving a local document as a template copies its current durable source into the workspace template catalog. Creating a document replaces the template header with the requested ID and produces an ordinary unsaved source draft. The new document does not store a template reference, inherit later changes, or consult the template at runtime. Removing a workspace template therefore never changes documents created from it.

Package templates are data-only authoritative Package content: they participate in the release content digest, immutable cache copy, install-time syntax and mathematical validation, and offline verification. They cannot contain or register executable hooks.

## External Agent authoring

An external Agent is an ordinary local authoring tool to which the host environment has separately
granted filesystem access. It is not a Process actor, Workbench Plugin, authenticated browser
client, or new Kirin Tor authority layer. The workbench does not grant that access and exposes no Agent
control protocol. The Agent may create or edit writable `entries/**/*.kirin` directly; it does not
need to drive the browser or invoke the Kirin Tor CLI to write a document.

The author sees the resulting source, diagnostics, and derived projections. The workbench does not
embed an Agent activity feed, prompt history, CLI transcript, terminal, file-operation log, or
hidden Agent-authored model state. Conversely, an external Agent cannot read the browser's unsaved
buffers through this mechanism. Every durable definition remains inspectable as ordinary `.kirin`
source. Empty-workspace guidance and the external-conflict dialog link directly to the in-app
Agent/external-editor reference; this contextual help does not add an `Agent` keyword, completion,
snippet, or highlighting class because the public language has not changed.

Direct external writes occur outside the Save All transaction. Kirin Tor therefore does not promise an
atomic multi-document update or suppress a temporarily incomplete source while an external tool is
writing several files. Every observed disk state is parsed and validated normally; invalid or
incomplete source remains visible with diagnostics and cannot be evaluated as if it were valid. An
external tool that needs a single coherent multi-file cutover must provide its own atomic write
discipline. This file-mediated contract is not simultaneous cursor sharing, CRDT collaboration, or
a general Agent execution protocol.

## Saving and conflicts

Every opened local document has an original source hash and an in-memory buffer. Save All first loads and validates the complete overlay. It then compares each original hash with the current disk file and rejects external changes. If all checks pass, all modified files are staged, flushed, and atomically replaced. Package documents never enter the writable overlay. A rejected external change keeps the draft intact and opens a base/draft/disk comparison. When a verified common base is available, a three-way merge combines non-overlapping edits and returns the result as an unsaved draft; overlapping edits remain explicit conflict markers. Recovered drafts without a verified base cannot invoke automatic merge. The author may also continue editing, download a `.workbench-draft.kirin` recovery copy, or explicitly replace the buffer with the current disk version.

While the page is visible, the browser polls a lightweight revision containing local document
metadata and source hashes, but no source bodies. A newly created local document appears without a
page refresh. If an already opened buffer is clean, an external write reloads that source and revalidates
the derived preview automatically. If the buffer contains an unsaved draft, the external write never
overwrites it and instead opens the same base/draft/disk comparison. If a dirty source is removed from
disk, its buffer is retained as a new unsaved document that Save All can recreate. Locked Package
documents are outside this local-write monitor.

The lightweight monitor is a discovery mechanism, not another persistence layer. It does not write
source, acknowledge Agent operations, or change the authority and validation rules above.

Document file actions require a clean workspace and an unchanged source hash. Move changes only an `entries/**/*.kirin` file path; it does not rename the source-authored `@entry` ID, aliases, members, or mathematical semantics. Duplicate asks for a new ASCII entry ID, updates the copied document's self-qualified references, validates the candidate workspace, and opens an unsaved draft. Remove first moves the file to `.kirin/trash/documents` and validates the remaining workspace; any broken reference or semantic dependency restores the original file and rejects the action. These actions never mutate locked Package documents.

While drafts are dirty, the workbench atomically mirrors at most 100 drafts and 5 MiB into ignored control state at `.kirin/workbench-recovery.json`. This cache is not source authority, is never evaluated independently, and is cleared after a successful Save All. A later workbench process restores a matching draft as an unsaved overlay; if the recorded base hash differs from disk, it opens the same explicit conflict comparison instead of silently choosing a version. CodeMirror undo history is retained when switching among documents during the current browser session.

Closing or refreshing the browser with dirty buffers triggers the browser's unsaved-change warning. Stopping the terminal process stops the server; there is no background daemon or remote account state.

## Verification boundary

The Playwright acceptance suite verifies the empty-workspace tutorial flow, the three remembered focus modes, document switching and creation validation, completion insertion, current-document and workspace replacement, save review, document duplication, contextual syntax help, find/replace and undo, outlines, definition/reference navigation, parameter hints, validated rename, automatic read-only result/chart/formula projection, source traceability, diagnostic quick fixes, keyboard-readable graph data, syntax-reference opening/search/copy behavior, draft recovery, clean external-source reload, external document discovery, and dirty-draft conflict handling. It runs against Chromium, Firefox, and WebKit; axe-core checks the welcome surface, main authoring surface, and syntax drawer, while Chromium and WebKit retain visual layout baselines. Python tests separately cover the workbench services, cancellable operation jobs, document lifecycle validation, Web adapter, authoring index, source validation, and strict validation of every bundled tutorial and syntax-reference example.

CI runs the Python matrix plus TypeScript checking, all three browser projects, accessibility checks, visual baselines, packaged-asset synchronization, explicit JavaScript/CSS bundle budgets, and a 100-document validation benchmark. These establish regression and bounded performance evidence for the tested fixtures. They do not by themselves establish human usability acceptance, every operating-system/browser combination, or a mobile product contract below the documented minimum width.
