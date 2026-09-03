# Kirin Tor browser workbench

## Product boundary

`kt web [WORKSPACE|SOURCE.kirin]` starts a local graphical workbench. An explicit path takes precedence, followed by the workspace containing the current directory and then the last remembered workspace. If none exists, the command asks for a folder and requires confirmation before initializing an ordinary directory; `kt web --choose` forces that selection again. The running workbench can open another existing workspace from Settings without starting a second server. The remembered path is user-local launch preference, not workspace or model authority. The workbench is an adapter over the same workspace, engine, operation, Package, artifact, and run-record services used by the CLI. It does not introduce another document model: local `entries/**/*.kirin` remain the only writable authority.

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

A missing, invalid, or incompatible Package keeps the locked Package graph inactive but does not
prevent the browser workbench from bootstrapping. The host continues to expose local documents,
recovered drafts, built-in and workspace templates, settings, and Package recovery controls. It
shows the Package failure as a persistent workspace diagnostic and lists the declared direct
requirements so they can be updated or removed. Package documents and templates remain unavailable,
and validation-dependent calculation and Save All operations remain strict until the complete graph
is valid again. The workbench never presents a partial Package graph as a valid workspace.

Host presentation follows the shared [Workbench design system](design-system.md). Its eight token families cover color, typography, spacing, dimensions, shape, elevation, motion, and stacking across Mantine, ordinary CSS, CodeMirror, and ECharts. Those tokens are application presentation, never document or calculation authority.

## Launch, process, and distribution boundary

The current workbench is a CLI-hosted local Web application, not an independently installed desktop
application. `kt web` selects or remembers a workspace, starts the authenticated loopback server in
the foreground process, and opens the session URL in the default browser. The browser is a client of
that process: closing a browser tab does not stop the server; `Ctrl+C` performs an orderly shutdown
of the server and its managed operation jobs, while termination of the host process ends the server
session. There is no background daemon that can reopen the workbench after the host process has
stopped.

An in-session workspace switch accepts an existing workspace root, one of its child directories, or
a `.kirin` source inside it. The server validates and constructs the replacement Workbench before
changing the active root, refuses to switch while a calculation job is running, remembers the new
root in the same user-local launch preference, and atomically replaces both the Workbench and its
operation-job manager. Authenticated API requests are serialized across that boundary so a
concurrent save or mutation cannot land in the previous workspace after the switch. The loopback
address and session token remain unchanged; the browser reloads its application state after success.
An invalid target leaves the current workspace untouched.

If local drafts are dirty, the browser requires explicit confirmation and flushes them to the
current workspace's bounded recovery cache before requesting the switch. They are not written to
authoritative `.kirin` files and are restored when that workspace is opened again. A deliberate
switch reload bypasses the ordinary unload warning only after the server has accepted the new
workspace; failed switches retain the current buffers and their normal unload protection.

Application installation and command discovery are outside Workbench state. `uv tool` is the
recommended distribution route, but adding its executable directory to the shell `PATH` is an
operating-system configuration action, normally performed with `uv tool update-shell`. The
Workbench cannot repair a missing `kt` command because it cannot run before the operating system has
resolved that command.

The current Workbench neither checks for nor automatically installs Kirin Tor application updates.
Its version projection reports the already installed version only. Updating `kirin-tor-cli` is an
explicit action performed outside the running Workbench with the installer or package manager that
owns that installation; the server exposes no API that invokes `uv`, `pip`, or another host package
manager, and it does not replace its own executable or Python environment. Package and Workbench
Plugin update actions affect workspace dependencies or explicitly approved plugin snapshots, not the
installed Kirin Tor application.

A future native or Electron host, bundled Python runtime, background launcher, or application
updater is not part of this implemented contract. Any such distribution layer requires a separate
accepted design and verification for process supervision, matched frontend/backend versions,
platform packaging, code signing, updates, and preservation of the loopback, session-token, source
authority, and Plugin isolation boundaries above.

## Views and CLI parity

- Documents covers CLI list/show/new/check and adds directory-grouped local sources, Package/version groups, per-document file actions, multi-document drafts, atomic Save All, explicit draft discard, external-change detection, integrated diagnostics, formula explanation, completion, result evaluation, named static-chart preview/export, and creation-time templates. An empty workspace replaces the three-pane editor with a welcome surface for the bundled basic-model, preset-comparison, and scan/chart tutorials.
- Relationship Graph derives global document and member projections from validated expression references and Process composition, then provides source navigation. Members include inputs, fields, functions, tables, finite distributions, objects, outputs, processes, scenarios, and analyses. Document projections use a deterministic circular layout; member projections retain a force layout. The document inspector shows a local zero-, one-, or two-hop projection from the same data, can limit traversal to dependencies or users, marks members of the current document, and reports both connection counts for the selected node.
- Syntax Reference is a read-only drawer opened from the navigation rail or command palette. It searches Chinese labels, canonical syntax terms, external-Agent authoring boundaries, rule summaries, and example source. Each topic contains a complete copyable `.kirin` example; copying never inserts into or otherwise mutates the active editor. The reference is a writing aid rather than an alternative parser or validation result.
- Workspace Search searches local drafts, disk sources, and locked Package sources together. Replace All skips Package sources and returns ordinary unsaved local overlays; it never writes directly to disk. Change Review compares every dirty buffer with its opening or creation baseline before Save All, can discard one or all drafts without touching disk, and separately exposes read-only Git log and working-tree summaries when the workspace belongs to a repository. Discarding an existing document restores its opening baseline; discarding a new unsaved document removes that draft from the workbench.
- Runs is a workspace drawer for replay and explicit artifact regeneration.
- Packages is a workspace drawer for add, add-path, list, update, remove, restore, verify, Package new/check, and workspace initialization.

The Web adapter exposes shared compare, scan, grid, transform, differentiation, and solve operations so any task-specific browser flow can reuse the existing mathematical implementation. Transform, differentiation, solve, scan, and grid also have public CLI commands; multi-variant comparison currently remains an application/Web-adapter operation. The current interface does not expose generic forms for these advanced operations or divide them into permanent Calculate, Charts, or Math pages. Authors use the corresponding CLI commands where available until a concrete browser workflow is adopted. A static chart appears only when its Entry declares a named `chart` with `x/range/points/y`; one Entry may declare up to 64 independent static charts.

Browser operations run as isolated local jobs with explicit queued/running/completed/failed/cancelled states. The header reports active jobs and their current stage and can terminate their process trees; server-side mathematical timeouts remain a second independent bound. The UI reports truthful stages rather than estimating an unsupported completion percentage.

The Web adapter accepts valid unsaved document overlays for validation and non-durable exploration. A run record cannot be created until its documents have been saved, so the immutable record always names durable source authority.

Bundled tutorials are complete `.kirin` files, not form state or an alternate semantic model. Viewing one reads only the installed application resource. Copying asks for a formal document ID, replaces the example header and self-qualified references through the ordinary template expander, and returns an unsaved local draft. The source is not written until the author invokes Save All.

Artifact paths stay inside the workspace by default and existing files are not overwritten. Document chart export and replay expose separate explicit controls for overwrite and working outside the workspace, matching the corresponding CLI authority expansion.

## Text-first interaction

Preview and Formula derive automatically from the current valid draft and never require Calculate, Generate Chart, or Explain Formula actions. The result projection may expose a compact `临时试算` area containing only inputs on the selected result's dependency path. Each row shows the source-authored default beside an optional temporary value. Temporary values live only in component memory, are passed to the existing comparison operation as an ephemeral overlay, do not enter draft recovery, and never modify `.kirin` or become a second authority. `重置` clears them. `生成 preset 草稿` explicitly appends an ordinary unsaved preset block to the one source editor; `保存运行记录` is available only when all drafts are clean and therefore records a durable source snapshot plus the requested overrides. Result and Chart selectors still choose projections rather than mathematical operations, and timeout or arbitrary advanced-operation forms remain absent. Explicit export controls remain separate because paths, overwrite, and workspace-boundary expansion require an intentional author action.

All static charts declared by the current Entry appear together in the existing Chart projection. One chart retains the ordinary full-width presentation. Multiple charts use a responsive grid: Split focus remains a single column at the inspector width, while Preview Only can grow to two or three columns as space permits. Each card retains its source label, canonical `ENTRY.CHART` identity, chart kind, source navigation, individual export, and full-window expansion; the projection also offers one explicit `导出全部图表` action for source-declared artifact paths. Chart canvases are instantiated only when their cards approach the visible scroll region, bounding initial browser work even when an Entry reaches the 64-chart limit. This is a fixed projection layout, not a draggable dashboard or notebook-cell system.

All calculation, Process, and relationship canvases use one registered Kirin Tor ECharts theme and shared renderer initialization. Line and trajectory charts expose a shared-axis Tooltip and Axis Pointer so hovering reports the current exact x/time value, units, and every visible series; heatmaps, decision surfaces, Pareto points, and variant comparisons expose type-specific item Tooltips. Clicking a static single-series plot or a nearby series point navigates to the canonical target definition. Process chart points and explicit card controls navigate to the owning Analysis declaration. The collapsible keyboard projection provides equivalent source actions and complete data rows. Hover, zoom, legend visibility, and navigation never mutate source or calculation state, and `.kirin` cannot embed arbitrary ECharts options or JavaScript formatters.

Diagnostics live beside the document editor rather than in a duplicate top-level page. The default scope reports only the current document and labels that count explicitly; an author can switch to the complete workspace scope and navigate any item back to its failing document and position. The inspector remains available when another document still has an error, even if the current document has no preview projection. Diagnostics retain stable codes and source locations and add Chinese author-facing explanations. Formula expansion appears in the same document context.

Preview results, chart definitions, formula explanations, diagnostics, and relationship nodes expose source navigation when their validated projection carries a source coordinate. Navigation restores Split focus mode, opens the authoritative `.kirin` document when necessary, and focuses the defining line instead of creating an editable projection.

The editor adds a tolerant authoring projection over complete or incomplete drafts. This projection may offer navigation and completion while strict workspace validation is failing, but it does not make an incomplete draft executable or saveable.

## Workbench Extension Plugins

The stable host discovers contributions only from enabled, locally approved, API-compatible plugin snapshots whose current cache content matches `kirin.plugins.lock`. The default Profile retains `documents` and `graph` and appends active plugin views; a contributed Profile supplies ordered view and tool lists, a default view, and an initial document focus mode. Switching Profile changes composition and layout state only. The dedicated Settings drawer always retains Plugin management, Package management, workspace identity, notification duration, layout preferences, platform-specific shortcut help, and a route back to the default Profile.

A matching document renderer is selected by validated canonical entry ID, ID prefix, or Package name. It receives a structured projection only after the complete overlay validates. The author can switch back to the generic result/chart projection without changing source or plugin state. Top-level plugin views and tools receive only the workspace summary unless their manifest declares another supported permission.

Every executable surface is an iframe with `sandbox="allow-scripts"` and no same-origin permission. Static module assets may be fetched from the exact loopback workbench origin, but the frame has no session token and its response sets `connect-src 'none'`. Host actions are limited to validated source navigation and bounded evaluation of an existing workspace target when the matching permission was declared. Save, recovery, Package mutation, plugin mutation, arbitrary operation forwarding, host DOM access, and filesystem access are never delegated.

Plugin installation, update, enable, disable, removal, verification, activation status, digest, and contribution counts are available from the built-in Plugins drawer and the corresponding CLI. `kt web --safe-mode` returns no active contributions and refuses plugin assets even when workspace control files request them. A malformed plugin control file is reported without preventing the core Safe Mode workbench from opening. Full protocol details are in [Workbench Extension Plugin protocol v1](workbench-plugin-system-v1.md).

The interface detects the current browser platform when rendering shortcut labels. `Ctrl/⌘` below means `Ctrl` on Windows and Linux, and `Command` on macOS; the handlers accept the corresponding modifier rather than assuming macOS key names.

| Command | Shortcut | Contract |
| --- | --- | --- |
| Save All | `Ctrl/⌘+S` | Strictly validates and atomically saves all writable drafts |
| Completion | `Ctrl+Space` | Searches built-ins, snippets, disk sources, and in-memory drafts |
| Find/replace | `Ctrl/⌘+F` | Edits the current in-memory document |
| Go to line | `Ctrl/⌘+G` | Navigates within the current document |
| Document outline | `Ctrl/⌘+Shift+O` | Navigates the tolerant current-document symbol index |
| Safe formatting | `Ctrl/⌘+Shift+F` | Normalizes safe whitespace without schema re-rendering |
| Go to definition | `F12` or Ctrl/⌘-click | Opens the indexed source definition, including another document |
| Definitions and references | `Shift+F12` | Lists definitions, direct references, and alias-mediated uses |
| Validated member rename in the editor | `F2` | Produces validated writable overlays; it never edits Package source |
| Rename or move a real `.kirin` file from the document list | `F2` | Opens the filesystem-path operation without changing the canonical `@entry` ID |
| Workspace command/open search | `Ctrl/⌘+K` or `Ctrl/⌘+P` | Searches views, tools, documents, and symbols |

Workspace Search, Change Review, run history, and plugin-contributed tools are available from the explicit Workspace Tools button and command palette. Package, plugin, notification, navigation, document-layout, shortcut, workspace-identity, and interface Profile controls live under the separate Settings button. The current workspace name is always visible in the header; its full local path is available from Settings and from the navigation-rail workspace control. Search results navigate to exact source coordinates. A workspace replacement always opens Change Review when it produces edits, so Save All remains a separate author decision.

Ordinary success and informational notifications close after four seconds by default, with a Settings choice of three, four, six, or eight seconds and at most three visible at once. Failures, conflicts, and other notifications that require an author decision remain visible until dismissed or resolved.

The fold gutter collapses indented declaration blocks and prose blocks. Hover shows a symbol's canonical identity, kind, signature, and unit or domain detail; completion details, symbol hover, and diagnostics can open the relevant bundled syntax topic without inserting text. The status bar shows the active function signature and parameter number together with the current line/column or selected character/line count. Focused and unfocused selections remain visibly distinct, and the insertion cursor and active line use the same ember interaction accent. The command palette also exposes Editor Only, Split, and Preview Only layout modes. Focus mode is remembered locally and changes only layout visibility, never source or projection semantics.

Safe rename updates the definition, local short references, and qualified cross-document references together while retaining Chinese aliases. It first produces ordinary in-memory `.kirin` overlays and validates the resulting workspace; Package definitions and Package source remain read-only. Formatting is deliberately source-preserving: it normalizes indentation tabs, trailing whitespace outside prose fences, excess blank lines, and the final newline without re-rendering or deleting comments. Known full-width punctuation diagnostics expose an explicit quick fix but are never rewritten automatically.

Cursor movement links source to the currently visible result, formula, or local-relationship projection when both sides identify the same symbol. This complements the existing projection-to-source controls without making preview state authoritative.

CodeMirror has an explicit accessible name and visible focus outline. Canvas relationship graphs and calculation charts expose a collapsible keyboard-readable node or data list with source-navigation actions matching their pointer interactions. Every generated chart can be expanded into a full-window preview without creating another editable surface.

Entries containing named Process Analysis declarations expose a `过程` projection beside ordinary
results and static charts. The projection runs the same backend Analysis, summarizes non-optimization
operations by their actual path/policy/state count, shows every tied variant/objective optimum with
proof level, release times and all Measures, and shows all declared trajectory/search charts in the
same responsive, deferred-rendering grid. `导出全部图表` is an explicit operation that
uses the source-declared SVG/CSV paths and the same workspace confinement and overwrite checks; live
preview rows and rendered canvases remain derived, read-only state.

## Interface system

The workbench uses one explicit grid hierarchy rather than stacking framework offsets and percentage split panes:

- the application shell is a two-column, two-row grid with a 224 px navigation rail and a 64 px header; below 1320 px the rail defaults to its 72 px compact state with visible labels, and the author choice is remembered locally and can also be changed in Settings;
- the document view is a three-track grid with a 216–260 px source index, a flexible editor, and a 320–420 px inspector; the inspector collapses to a 40 px rail when the current document has no useful projection, while the header also switches between Editor Only, Split, and Preview Only focus modes and remembers the author's choice locally;
- built-in destinations share one metadata registry for navigation groups, header identity, command-palette actions, tool-menu entries, titles, and presentation mode; Documents belongs to Creation, the relationship graph to Understanding, syntax to Reference, and workspace operations or extension management to their corresponding tool-menu groups;
- the relationship graph uses a 9/3 page grid; contextual tools use one right-side modal Drawer, while run history retains a 4/8 list/detail grid inside it;
- a tool may replace its own body with an in-Drawer subview for discovery, authoring, forms, or confirmation, but it never opens another modal Drawer on top of the tool;
- adjacent workbench tracks share a single 1 px divider and never add their own outer margins.

The shell owns the single level-one page heading. Main-view sections begin at level two; a tool
Drawer owns level two and its body begins at level three. Document index, editor, inspector,
relationship graph, and run-history panes expose stable labelled landmarks even when their visual
contents are empty or loading. Lists retain separate list-item and interactive-button semantics.

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
documents are outside this local-write monitor. If a document is opened, edited, created, moved, or
discarded while a polling request is in flight, that stale response is ignored and reconciled again on
the next poll; background synchronization cannot replace newer editor state. A delayed document-open
response likewise fills only a still-unloaded buffer and never overwrites text entered while it was loading.

The lightweight monitor is a discovery mechanism, not another persistence layer. It does not write
source, acknowledge Agent operations, or change the authority and validation rules above.

Document file actions require a clean workspace and an unchanged source hash. Move changes only an `entries/**/*.kirin` file path; it does not rename the source-authored `@entry` ID, aliases, members, or mathematical semantics. Duplicate asks for a new ASCII entry ID, updates the copied document's self-qualified references, validates the candidate workspace, and opens an unsaved draft. Remove first moves the file to `.kirin/trash/documents` and validates the remaining workspace; any broken reference or semantic dependency restores the original file and rejects the action. These actions never mutate locked Package documents.

While drafts are dirty, the workbench atomically mirrors at most 100 drafts and 5 MiB into ignored control state at `.kirin/workbench-recovery.json`. This cache is not source authority and is never evaluated independently. Recovery writes are serialized in user-action order; a successful Save All or explicit discard clears the corresponding cached drafts before that action completes, so an older delayed write cannot resurrect them. A later workbench process restores a matching draft as an unsaved overlay; if the recorded base hash differs from disk, it opens the same explicit conflict comparison instead of silently choosing a version. CodeMirror undo history is retained when switching among documents during the current browser session.

Closing or refreshing the browser with dirty buffers triggers the browser's unsaved-change warning. Stopping the terminal process stops the server; there is no background daemon or remote account state.

## Verification boundary

The Playwright acceptance suite verifies the empty-workspace tutorial flow, the three remembered focus modes, persistent workspace identity and Settings, platform-correct shortcuts, configurable notification timeout, directory grouping, real-file move, document switching and creation validation, completion insertion, current-document and workspace diagnostic scopes, current-document and workspace replacement, save review, single/all draft discard, new-draft removal, document duplication, contextual syntax help, find/replace and undo, outlines, definition/reference navigation, parameter hints, validated rename, automatic result/chart/formula projection, non-authoritative trial comparison, run-record and preset-draft actions, multiple static and Process charts, source traceability, diagnostic quick fixes, keyboard-readable graph data, syntax-reference opening/search/copy behavior, draft recovery, clean external-source reload, external document discovery, and dirty-draft conflict handling. It runs against Chromium, Firefox, and WebKit; axe-core checks the welcome surface, main authoring surface, Settings, syntax drawer, and dialogs, while Chromium and WebKit retain visual layout baselines. Python tests separately cover the workbench services, cancellable operation jobs, document lifecycle validation, Web adapter, authoring index, source validation, and strict validation of every bundled tutorial and syntax-reference example.

CI runs the Python matrix plus TypeScript checking, all three browser projects, accessibility checks, visual baselines, packaged-asset synchronization, explicit JavaScript/CSS bundle budgets, and a 100-document validation benchmark. These establish regression and bounded performance evidence for the tested fixtures. They do not by themselves establish human usability acceptance, every operating-system/browser combination, or a mobile product contract below the documented minimum width.
