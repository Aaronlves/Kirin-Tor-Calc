# Kirin Tor browser workbench

## Product boundary

`kt web [WORKSPACE|SOURCE.kirin]` starts a local graphical workbench. It is an adapter over the same workspace, engine, operation, Package, artifact, and run-record services used by the CLI. It does not introduce another document model: local `entries/**/*.kirin` remain the only writable authority.

The server binds only to a loopback address. Each process creates a random session token, transfers it to browser session storage on first load, and removes it from the visible URL. API requests require that token and an allowed local Host and Origin. Responses disable caching, framing, referrer forwarding, MIME sniffing, inline scripts, and cross-origin connections. Runtime-generated CSS is allowed because CodeMirror mounts its base and theme styles dynamically; executable scripts remain same-origin packaged assets.

## Views and CLI parity

- Documents covers CLI list/show/new/check and adds multi-document drafts, atomic Save All, external-change detection, integrated diagnostics, formula explanation, completion, result evaluation, optional chart preview/export, and creation-time templates.
- Relationship Graph derives global document and member projections from validated formula references and provides source navigation. The document inspector shows a local zero-, one-, or two-hop projection from the same data.
- Runs is a workspace drawer for replay and explicit artifact regeneration.
- Packages is a workspace drawer for add, add-path, list, update, remove, restore, verify, Package new/check, and workspace initialization.

Advanced CLI operations remain available through the shared workbench operation API rather than being divided into permanent Calculate, Charts, or Math pages. A chart appears in a document only when its source defines `x/range/points/y`.

The Web adapter accepts valid unsaved document overlays for validation and non-durable exploration. A run record cannot be created until its documents have been saved, so the immutable record always names durable source authority.

Artifact paths stay inside the workspace by default and existing files are not overwritten. Document chart export and replay expose separate explicit controls for overwrite and working outside the workspace, matching the corresponding CLI authority expansion.

## Text-first interaction

Temporary parameter overrides are text, not a generated form. Authors may use canonical qualified names, an unambiguous short name, or a display label; exact percentages such as `25%` are normalized before evaluation. The first calculation has one baseline variant. Additional variants are created only when the author requests comparison.

Diagnostics live beside the document editor rather than in a duplicate top-level page. They retain stable codes and source locations, add Chinese author-facing explanations, and navigate back to the failing document and position. Formula expansion appears in the same document context.

## Interface system

The workbench uses one explicit grid hierarchy rather than stacking framework offsets and percentage split panes:

- the application shell is a two-column, two-row grid with a 224 px navigation rail and a 64 px header;
- the document view is a three-track grid: a 216–272 px source index, a flexible editor, and a 280–360 px inspector;
- page-level tools use twelve-part proportions, including 9/3 for the relationship graph and 4/8 for run history;
- adjacent workbench tracks share a single 1 px divider and never add their own outer margins.

The spacing scale is 4, 8, 12, 16, 24, and 32 px. Toolbars are 48 px high; buttons, inputs, and icon buttons are 32 px high. Actions have four stable levels: ember-filled primary, neutral-outline secondary, borderless toolbar, and red destructive. Green, amber, and red are reserved for success, dirty/warning, and error states. All controls are rectangular and use the same focus outline. The minimum supported content width is 1120 px; smaller layouts are not treated as an independent mobile product.

## Static creation templates

Templates are complete Entry source skeletons used only at creation time. A template may include optional chart fields. The workbench lists:

- built-in game-neutral skeletons;
- workspace templates under `templates/entries`;
- read-only Package templates at the same relative paths inside locked Package content.

Saving a local document as a template copies its current durable source into the workspace template catalog. Creating a document replaces the template header with the requested ID and produces an ordinary unsaved source draft. The new document does not store a template reference, inherit later changes, or consult the template at runtime. Removing a workspace template therefore never changes documents created from it.

Package templates are data-only authoritative Package content: they participate in the release content digest, immutable cache copy, install-time syntax and mathematical validation, and offline verification. They cannot contain or register executable hooks.

## Saving and conflicts

Every opened local document has an original source hash and an in-memory buffer. Save All first loads and validates the complete overlay. It then compares each original hash with the current disk file and rejects external changes. If all checks pass, all modified files are staged, flushed, and atomically replaced. Package documents never enter the writable overlay.

Closing or refreshing the browser with dirty buffers triggers the browser's unsaved-change warning. Stopping the terminal process stops the server; there is no background daemon or remote account state.
