# Kirin Tor Workbench Extension Plugin protocol v2

> 本文描述当前已实现的 v2 合同，包括 Model Catalog 2、Operation Service 2、生成式 SDK、
> host-owned result slot、持久偏好、Proposal 2 与本地作者工具。发布与发现的后续能力仍以
> [可规模化游戏插件平台提案](scalable-game-plugin-platform-proposal.md)为设计依据。

## Purpose

Workbench Extension Plugins add presentation and workflow surfaces to the local browser
workbench without changing Kirin Tor mathematical semantics. A plugin can contribute document
renderers, top-level views, workspace tools, declarative commands, and layout profiles. The
official workbench remains the host for source editing, validation, saving, Package resolution,
artifact boundaries, and recovery.

Plugins are executable local UI extensions. They are intentionally separate from Community
Packages, which remain data only. Installing a Community Package never installs, approves,
enables, or executes a Workbench Plugin.

Protocol v2 supports explicitly selected local directories. A plugin may use separately granted,
read-only mathematical permissions to query the revision-bound public Model Catalog and ask the host to
perform bounded calculations. Separately granted permissions can expose the current local buffer and
available data-only templates, persist bounded non-model preferences, present a core result in a
host-owned slot, and submit an atomic candidate transaction to the review queue; the core still owns
every parse, validation, evaluation, search and analysis. The protocol does not define a marketplace, remote installer, signature authority, native
executable plugin, mathematical backend plugin, or unrestricted main-page JavaScript extension.

## Community discovery

Public Workbench Plugin repositories may add the GitHub topic `kirin-tor-plugin`. The
workbench's explicit **Discover community plugins** action searches that topic and reads
`kirin.plugin.json` from each candidate repository's current default branch. GitHub normalizes
topic names to lower case.

Topic membership is a community self-declaration, not an official listing, security audit, or
compatibility promise. Before display, Kirin Tor strictly checks the current manifest schema, Plugin
API version, identifiers, contribution declarations, permissions, targets, profiles, and the
structural safety of entry paths. It does not download or validate the referenced static assets
during discovery. Repositories with missing, invalid, or incompatible manifests are counted but
not presented as compatible Plugins.

Discovery is an explicitly requested, read-only network projection. Results stay in the current
browser view and are not written to the workspace, Plugin requirements, Plugin lock, approval
registry, or content store. A displayed manifest blob SHA identifies only the manifest inspected
for that transient result; it is not the installed bundle's canonical content digest. The surface
offers a link to the public repository but no remote install action. Discovery never installs,
approves, enables, downloads, or executes Plugin content; Protocol v2 installation remains the
explicit local-directory flow defined below.

## Authority and trust boundary

- Local `.kirin` source remains the only editable definition authority.
- The core parser, validator, engine, Save All transaction, Package resolver, run records, and
  local-server authorization are not replaceable plugin services.
- Plugin views are projections. They cannot directly read or write workspace files, access the
  workbench session token, inspect the host DOM, or call authenticated APIs.
- Plugin assets run in an iframe with `sandbox="allow-scripts"` and without `allow-same-origin`.
  The plugin response forbids network connections, forms, popups, framing by another origin,
  inline scripts, and navigation of the host.
- The host sends bounded JSON context through `postMessage`. Plugin requests are checked against
  the contribution's declared permissions and executed by the host.
- A plugin crash or protocol error affects only its surface. The official generic projection and
  core views remain available.
- `kt web --safe-mode` suppresses all third-party contributions and asset serving regardless of
  workspace configuration.

An external Agent with separately granted host-filesystem access is not a Workbench Plugin and does
not receive a plugin permission. It may edit writable local `.kirin` source outside the browser, after
which the official workbench performs its ordinary external-change synchronization and validation.
That host-level capability does not weaken the iframe sandbox: plugin code still cannot read or write
files, inspect Agent activity, or obtain the browser's dirty buffers. See the
[browser workbench contract](web-workbench.md#external-agent-authoring).

Sandboxed iframes are an authority boundary, not a complete resource sandbox. A plugin can still
consume browser CPU or memory while its frame is mounted. Protocol v2 therefore gives the author
an always-available disable action and Safe Mode recovery; stronger process-level browser
isolation is outside v2.

## Bundle layout

A plugin source directory contains one strict UTF-8 JSON manifest and static browser assets:

```text
kirin.plugin.json
web/
  talent-tree.html
  talent-tree.js
  talent-tree.css
  icons/
    example.webp
README.md
LICENSE
```

The installed content digest covers every regular file in canonical relative-path order. Symbolic
links, hard links, device files, absolute paths, parent traversal, duplicate normalized paths,
excessive file counts, and excessive total bytes are rejected. Installation copies the validated
bundle into the workspace-owned content-addressed store
`.kirin/plugins/<canonical-content-sha256>/`; the source directory is never executed in place.

Each HTML entry point and every asset it loads must remain inside the installed bundle. HTML,
JavaScript, CSS, JSON, common raster/vector image files, and web fonts are static assets; the
server sends `nosniff` and an explicit media type.

## Manifest

`kirin.plugin.json` uses schema 2:

```json
{
  "schema": 2,
  "id": "community.example-talents",
  "name": "Example Talent Workbench",
  "version": "1.0.0",
  "api": "2",
  "description": "A fictional talent-tree presentation plugin.",
  "license": "MIT",
  "storage": {
    "preferences": {"schema": 1}
  },
  "requires": {
    "kirin_feature": "0.6",
    "interfaces": [
      {"id": "fictional.theorycraft-model", "revision": 2}
    ]
  },
  "contributes": {
    "renderers": [
      {
        "id": "community.example-talents.talent-tree",
        "title": "天赋树",
        "entry": "web/talent-tree.html",
        "priority": 100,
        "match": {
          "document_ids": ["fictional_talents"],
          "document_id_prefixes": [],
          "package_names": []
        },
        "permissions": [
          "model.read", "document.read", "draft.read", "template.read",
          "proposal.submit", "result.present", "storage.preferences",
          "source.navigate", "operation.evaluate"
        ]
      }
    ],
    "views": [
      {
        "id": "community.example-talents.builds",
        "title": "Build 浏览器",
        "entry": "web/builds.html",
        "permissions": ["workspace.summary", "source.navigate"]
      }
    ],
    "tools": [
      {
        "id": "community.example-talents.audit",
        "title": "天赋检查",
        "entry": "web/audit.html",
        "permissions": ["document.read", "source.navigate"]
      }
    ],
    "commands": [
      {
        "id": "community.example-talents.open-builds",
        "title": "打开 Build 浏览器",
        "description": "打开插件提供的 Build 页面。",
        "action": "open-view",
        "target": "community.example-talents.builds"
      }
    ],
    "profiles": [
      {
        "id": "community.example-talents.authoring",
        "title": "天赋创作",
        "description": "以源码编辑和天赋预览为中心的布局。",
        "views": ["documents", "community.example-talents.builds", "graph"],
        "tools": ["community.example-talents.audit", "runs", "packages", "plugins"],
        "default_view": "documents",
        "document_focus_mode": "split"
      }
    ]
  }
}
```

Unknown fields are errors. `id` is a dotted lower-case public identifier. Contribution IDs must
begin with `<plugin-id>.`; versions are exact `MAJOR.MINOR.PATCH` values, and `api` is exactly
`"2"`. Entry paths must identify existing `.html` files under `web/`.

Every renderer must declare at least one exact document ID, document-ID prefix, or Package name.
Matching uses validated canonical document identity and Package provenance, never the displayed
title, filename, comment text, label, or keyword similarity. When multiple renderers match, the
host sorts by descending priority and then stable contribution ID. The author can return to the
generic projection at any time.

Protocol v2 permissions are:

- `workspace.summary`: receive bounded document and installed-Package metadata;
- `model.read`: receive a fixed-size Catalog summary and request revision-bound `model.query`,
  `model.get`, `model.dependencies`, `model.document`, and `model.capabilities` projections. The
  Catalog covers Entries, semantics, structures, static members, Process, Scenario, Analysis,
  charts, and source/evidence blocks; local Package paths and raw `.kirin` source are not included;
- `document.read`: receive the selected validated document projection, including structured
  source content, canonical IDs, Package provenance, and source coordinates;
- `draft.read`: receive the exact currently loaded local document buffer, up to the Plugin bridge's
  400,000-byte limit; locked Package source is never exposed by this permission;
- `template.read`: receive the bounded built-in, workspace and immutable Package creation-template
  catalog, including explicitly declared structured binding names but no Package filesystem paths;
- `proposal.submit`: submit one bounded, all-or-nothing transaction containing
  `create-from-template`, `create-document`, and/or `replace-document` changes under local
  `entries/`; the host validates and queues it for human review but does not apply or save it;
- `result.present`: ask the host to render a result handle previously issued to the same mounted
  contribution in an adjacent host-owned slot; the Plugin can supply only a short title and order;
- `storage.preferences`: use a manifest-schema-versioned, bounded JSON preference namespace isolated
  by local user, workspace, and Plugin ID; this state never enters source evaluation;
- `source.navigate`: ask the host to open an authoritative document at a supplied source location;
- `operation.evaluate`: evaluate one canonical public output, or use `evaluate-many` for at most
  64 outputs under one shared workspace revision, preset and canonical override preparation;
- `operation.explain`: obtain the core formula, conditions, input contract and provenance for a
  canonical public output;
- `operation.compare`: compare one to 8 explicitly named preset/override variants of one output;
- `operation.scan`: perform a one-dimensional scan or two-dimensional grid over declared inputs,
  within the core's 10,000-point bound;
- `operation.solve`: solve a canonical public output for one of its declared input dependencies;
- `operation.analyze`: execute a source-declared, canonical Process Analysis with optional trace
  inclusion and the ordinary Scenario and analysis bounds as a cancellable job;
- `operation.job`: query or cancel only jobs created by the same mounted contribution. It does not
  expose another Plugin's request or result.

The mathematical permissions expose only calculation results. `result.present` does not trust the
iframe's rendering: the host resolves an opaque contribution-owned operation handle and renders a
bounded direct summary from the unchanged result envelope, plus revision, warnings, provenance and a
source action outside the frame. Complex structures are identified as structured results rather than
being reinterpreted by the host slot. A model revision change
marks the slot stale. `storage.preferences` accepts only bounded JSON-safe values and requires
`storage.preferences.schema` in the manifest; a schema change resets only that Plugin/workspace
namespace.

Proposal permissions do not permit direct mutation: at most 16 validated transactions wait in
volatile host memory, each carrying the submitting Plugin ID, version, contribution ID and content
digest. A transaction may affect at most 16 local documents and is accepted or rejected as one unit.
Acceptance requires unchanged revision/baselines and repeats complete-workspace validation before
all changes become ordinary unsaved drafts. Only then do normal recovery and Save All rules apply.
Queued Proposals are not themselves recovery state or durable authority and disappear on reload.
No permission permits artifact export, run-record
creation, arbitrary operation names, arbitrary expressions as targets, direct source mutation, Package
mutation, or caller-selected timeouts. Presets, outputs, analyses, scan variables and override names
must already exist in the current validated model catalog. Solve right-hand sides and scan ranges are
still parsed and checked by the ordinary mathematical core.

No permission grants raw filesystem, environment, process, credential, session-token, arbitrary
HTTP, Save All, Package mutation, host-application installation or update, or unrestricted operation
access.

The backend-published v2 conformance matrix is:

| Frame action | Required permission | Handler | Exact backend operation |
| --- | --- | --- | --- |
| `navigate-source` | `source.navigate` | Host | — |
| `proposal.submit` | `proposal.submit` | Proposal service | — |
| `result.present` | `result.present` | Host result registry | — |
| `storage.get` | `storage.preferences` | Preference service | — |
| `storage.set` | `storage.preferences` | Preference service | — |
| `storage.delete` | `storage.preferences` | Preference service | — |
| `evaluate` | `operation.evaluate` | Operation service | `eval` |
| `evaluate-many` | `operation.evaluate` | Operation service | `evaluate_many` |
| `explain` | `operation.explain` | Operation service | `explain` |
| `compare` | `operation.compare` | Operation service | `compare` |
| `scan` | `operation.scan` | Operation service | `scan` |
| `grid` | `operation.scan` | Operation service | `grid` |
| `solve` | `operation.solve` | Operation service | `solve` |
| `analyze` | `operation.analyze` | Operation job service | `process_analysis` |
| `job.status` | `operation.job` | Owner-scoped job service | — |
| `job.cancel` | `operation.job` | Owner-scoped job service | — |
| `model.query` | `model.read` | Catalog | — |
| `model.get` | `model.read` | Catalog | — |
| `model.dependencies` | `model.read` | Catalog | — |
| `model.document` | `model.read` | Catalog | — |
| `model.capabilities` | `model.read` | Catalog | — |

This table documents the runtime registry rather than granting additional authority. Automated
conformance checks require each action to declare the complete capability fields and require the
browser adapter to cover the seven generic handler classes without per-operation constants. The
reference Plugin executes every row in both supported browser engines.

## Requirements, lock, approval, and activation

The workspace-authored `kirin.plugins.toml` records requested local plugins, aliases, exact
versions, and enabled state. `kirin.plugins.lock` records the resolved source path and canonical
content digest. The `.kirin/plugins/` store is a rebuildable local cache and is ignored by Git.

Executable approval is deliberately not stored in either workspace file. A local user approval
registry outside the workspace records approved content digests. `plugin add-path` is an explicit
approval action; updating a source produces a new digest and requires approval of that new content.
A checked-out repository can therefore request a plugin but cannot make previously unseen code
active by committing requirements, a lockfile, or a cache directory.

The CLI and workbench management surface provide:

```text
kt plugin add-path ALIAS DIRECTORY
kt plugin update-path ALIAS
kt plugin enable ALIAS
kt plugin disable ALIAS
kt plugin remove ALIAS
kt plugin verify
kt plugin list
kt web --safe-mode
```

Plugin authors additionally have offline, non-executing commands:

```text
kt plugin new DIRECTORY --id ID
kt plugin check [DIRECTORY] [--workspace WORKSPACE]
kt plugin test [DIRECTORY] --workspace WORKSPACE
kt plugin bundle [DIRECTORY] [--out ARCHIVE] [--force]
```

`new` vendors the generated dependency-free SDK. `check` validates the strict manifest, static
files, permissions, digest, and optional interface compatibility. `test` copies the selected
workspace into an isolated temporary directory, removes installed Plugin state, and runs
offline protocol/interface fixtures without executing Plugin JavaScript. `bundle` writes a
deterministic static archive outside the source root, refuses to overwrite unless `--force` is
explicit, and never invokes npm, a build script, hook, or executable shipped by the Plugin.

Plugin manifest schema 2 requires an exact Kirin feature line and zero or more exact model
interface ID/revision pairs. Before activation the host reports every requirement as `satisfied`,
`missing`, `revision-mismatch`, `ambiguous`, `invalid-provider`, or `kirin-incompatible`. An
incompatible Plugin remains visible with provider version and digest details but contributes no
surface and cannot serve assets. Installing a Plugin never installs or updates a Package.

`kirin.plugins.toml` and `kirin.plugins.lock` remain independently versioned schema-1 control
records. All requirement, lock, and store changes are staged and validated before authority files are
replaced. Disabled, missing, digest-mismatched, invalid, unapproved, or API-incompatible plugins
remain visible in management diagnostics but contribute no executable surfaces.

## Host contribution model

The official host owns stable built-in IDs:

- views: `documents`, `graph`;
- tools: `runs`, `packages`, `plugins`, `syntax`, `search`, `changes`;
- profile: `default`.

An active plugin may contribute:

- `renderer`: a document-specific projection shown beside the generic result/chart projection;
- `view`: a top-level page inside the stable navigation shell;
- `tool`: a workspace drawer surface;
- `command`: one declarative `open-view`, `open-tool`, or `activate-profile` action;
- `profile`: ordered visible view/tool lists, a default view, and an initial document focus mode.

Profiles compose the stable host; they do not replace authentication, plugin management, recovery,
or Safe Mode. A profile may omit `documents`, but it cannot remove the recovery route back to the
default profile.

## Frame protocol

Frames and the host exchange JSON messages with `protocol: "kirin-workbench-plugin"` and
`api: "2"`. The minimum lifecycle is:

1. the frame sends `ready`;
2. the host validates the frame source and sends `activate` with contribution identity, the
   backend-published v2 capability descriptor, the fixed-size Catalog summary when authorized, and
   only the remaining context authorized by its permissions;
3. the host sends a new `context` message when the selected document, validated projection or
   validated Catalog revision changes;
4. the frame may send an `action` request for `navigate-source`, `proposal.submit`,
   `result.present`, `storage.get`, `storage.set`, `storage.delete`, `evaluate`, `evaluate-many`,
   `explain`, `compare`, `scan`, `grid`, `solve`, `analyze`, `job.status`,
   `job.cancel`, `model.query`, `model.get`, `model.dependencies`, `model.document`, or
   `model.capabilities` when its contribution declared the corresponding permission;
5. the host returns a correlated `action-result` or `action-error`;
6. `analyze` returns an opaque job handle; the host emits `job-update` events with truthful
   queued/running/completed/failed/cancelled stages, while the SDK also exposes status, wait and
   cancel helpers;
7. unmounting or reloading the frame ends the capability session and cancels its still-live jobs,
   as declared by the capability's `unload_policy`.

The host accepts messages only from the mounted frame's `contentWindow`, validates message shape,
IDs, sizes, action names, workspace revision, canonical targets, declared inputs, presets, point
counts and permissions, and never forwards arbitrary plugin payloads to a backend operation.
Operation Service rejects unknown request fields. Standard calculations use host-selected precision,
display precision and timeout; no public payload accepts a run-record ID or artifact path. Process
Analysis uses the longer host-selected ceiling in a process tree that can be cancelled both by its
own contribution and by the global Workbench control. A result that would exceed the message limit
is replaced with a correlated `result_too_large` error.

Synchronous Operation Service results use one envelope containing an opaque operation ID, current
revision, canonical targets, applied preset/overrides, target and dependency origins, warnings, and
the unchanged mathematical result. `evaluate-many` uses one validated Workspace and one Engine;
its individual result rows are mathematically identical to separate `evaluate` calls with the same
relevant inputs while reusing one Workspace and Engine instance.

`/api/bootstrap` publishes the same descriptor at `plugins.protocol`, and every `activate` or
`context` message carries it as `capabilities`. It identifies the Plugin API version, all supported
action-to-permission and action-to-backend-operation mappings, and the current bridge limits. The
backend registry is authoritative; the browser adapter consumes these values instead of maintaining
a second set of limits. In particular, both the Plugin host and application service enforce the
same eight-variant comparison limit.

Catalog requests must echo the opaque `catalog.revision` received in the current context. Query
results are ordered by canonical ID and kind; `limit` defaults to 50 and is capped at 100. An opaque
cursor is bound to the revision and normalized filters, so it cannot be reused after a model change
or with another query. A stale revision returns `stale_revision`. `model.get` retrieves one
descriptor, `model.dependencies` traverses only bounded direct dependencies, and `model.document`
returns structured descriptors without raw source. Every descriptor separates Package-release
`origin`, ordinary `source_location`, game-neutral `contract`, direct dependencies, interface
membership, and kind-specific `payload`.

## Generated schemas and SDK

`src/kirin_tor/plugin_protocol.py` is the generation source for action names, permissions, request
and result schemas, hard limits, timeout/execution class, overlay/run/artifact policy, unload policy,
events, and stable error codes. `scripts/generate_plugin_protocol.py` deterministically produces:

- JSON Schemas and operation/limit/error catalogs under `schemas/plugin-v2/`;
- the checked frontend contract in `frontend/src/generated/pluginProtocol.ts`;
- the dependency-free ESM SDK and TypeScript declaration under `sdk/plugin/`;
- an installed-package copy under `kirin_tor/protocol_assets/`;
- the vendored SDK used by the reference Plugin.

`python scripts/generate_plugin_protocol.py --check` fails on drift and is part of CI. The SDK owns
the API handshake, correlated requests, runtime request validation, revision injection and updates,
capability/permission checks, bounded pagination, stable errors, job updates/wait/cancel, message
size preflight and disposal. It contains no mathematical formulas, Package resolver or source-write
implementation. The reference Plugin imports `createKirinPlugin` and contains no handwritten
`postMessage` protocol, request-ID map, revision plumbing, or copied calculation formula.

`operations.*` returns a revision-bound opaque operation ID. `results.present` accepts only such a
handle produced by the same live contribution; the host owns the neighboring result DOM, bounded summary,
provenance link, trust label, and stale state. It does not validate arbitrary numbers rendered inside
the iframe.

`storage.get/set/delete` address only the calling Plugin's manifest-declared preference namespace.
The host enforces key, value, nesting, item-count and total-byte limits and resets the namespace when
its positive integer storage schema changes. The Plugin manager exposes an explicit clear action.

`proposals.submit` supplies a title, optional short description and one bounded change array. Template
creation uses data-only templates whose binding points are explicitly declared in the template;
bindings are parsed and canonically rendered rather than interpolated as raw source. Direct creation
must provide a complete matching Entry, while replacement requires the current local document key and
base SHA-256. The host rejects oversized, duplicate-target, stale, Package-owned, invalid, or
queue-overflow transactions. A successful response means only that one whole transaction is awaiting
review; it is not evidence of acceptance or persistence.

## Evidence and limitations

Passing protocol, Python, TypeScript, and browser tests establishes behavior for the checked
fixtures and browsers. It does not establish that third-party plugin code is trustworthy, that a
plugin's game presentation is factually correct, that every browser resource-exhaustion case is
contained, or that a future marketplace is safe. Plugin identity, source, version, content digest,
enabled state, approval state, API compatibility, and active contributions remain separately
inspectable.
