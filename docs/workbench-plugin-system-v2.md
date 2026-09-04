# Kirin Tor Workbench Extension Plugin protocol v2

> 本文描述当前已实现的 v2 合同。后续 Operation Service、SDK、可信结果呈现与发布能力
> 仍以[可规模化游戏插件平台提案](scalable-game-plugin-platform-proposal.md)为设计依据。

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
perform bounded calculations. Separately granted draft permissions can expose the current local
buffer and submit a candidate to the host-owned review queue; the core still owns every parse,
validation, evaluation, search and analysis. The protocol does not define a marketplace, remote installer, signature authority, native
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
  "requires": {
    "kirin_feature": "0.4",
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
        "permissions": ["model.read", "document.read", "source.navigate", "operation.evaluate"]
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
`"1"`. Entry paths must identify existing `.html` files under `web/`.

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
- `draft.propose`: submit one complete candidate replacement for that same current local document;
  the host validates and queues it for human review but does not apply or save it;
- `source.navigate`: ask the host to open an authoritative document at a supplied source location;
- `operation.evaluate`: evaluate a canonical public output with optional validated preset and
  temporary input overrides;
- `operation.explain`: obtain the core formula, conditions, input contract and provenance for a
  canonical public output;
- `operation.compare`: compare one to 8 explicitly named preset/override variants of one output;
- `operation.scan`: perform a one-dimensional scan or two-dimensional grid over declared inputs,
  within the core's 10,000-point bound;
- `operation.solve`: solve a canonical public output for one of its declared input dependencies;
- `operation.analyze`: execute a source-declared, canonical Process Analysis with optional trace
  inclusion and the ordinary Scenario and analysis bounds.

The mathematical permissions expose only calculation results. Draft proposal permissions do not
permit direct mutation: at most 16 validated candidates wait in volatile host memory, each carrying
the submitting Plugin ID, version, contribution ID and content digest. Acceptance requires the
current buffer to equal the recorded baseline and repeats complete-workspace validation before the
candidate becomes an ordinary unsaved draft. Proposals are neither recovery state nor durable
authority and disappear on reload. No permission permits artifact export, run-record
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
| `propose-draft` | `draft.propose` | Host | — |
| `evaluate` | `operation.evaluate` | Operation service | `eval` |
| `explain` | `operation.explain` | Operation service | `explain` |
| `compare` | `operation.compare` | Operation service | `compare` |
| `scan` | `operation.scan` | Operation service | `scan` |
| `grid` | `operation.scan` | Operation service | `grid` |
| `solve` | `operation.solve` | Operation service | `solve` |
| `analyze` | `operation.analyze` | Operation service | `process_analysis` |
| `model.query` | `model.read` | Catalog | — |
| `model.get` | `model.read` | Catalog | — |
| `model.dependencies` | `model.read` | Catalog | — |
| `model.document` | `model.read` | Catalog | — |
| `model.capabilities` | `model.read` | Catalog | — |

This table documents the runtime registry rather than granting additional authority. Automated
conformance checks require the adapter branches to match this exact set, and the reference Plugin
executes every row in both supported browser engines.

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
`api: 2`. The minimum lifecycle is:

1. the frame sends `ready`;
2. the host validates the frame source and sends `activate` with contribution identity, the
   backend-published v2 capability descriptor, the fixed-size Catalog summary when authorized, and
   only the remaining context authorized by its permissions;
3. the host sends a new `context` message when the selected document, validated projection or
   validated Catalog revision changes;
4. the frame may send an `action` request for `navigate-source`, `propose-draft`, `evaluate`,
   `explain`, `compare`, `scan`, `grid`, `solve`, `analyze`, `model.query`, `model.get`,
   `model.dependencies`, `model.document`, or `model.capabilities` when its contribution declared
   the corresponding permission;
5. the host returns a correlated `action-result` or `action-error`;
6. unmounting the frame ends the capability session.

The host accepts messages only from the mounted frame's `contentWindow`, validates message shape,
IDs, sizes, action names, canonical targets, declared inputs, presets, point counts and permissions,
and never forwards arbitrary plugin payloads to a backend operation. Standard plugin calculations
use host-selected precision, display precision and timeout; Process Analysis retains the longer
host-selected ceiling while remaining cancellable from the Workbench. A result that would exceed
the plugin message-size limit is replaced with a correlated `result_too_large` error.

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

A `propose-draft` action names only the current local document and supplies a title, optional short
description, and complete candidate source. The host rejects empty, oversized, unchanged, stale,
read-only, invalid, or queue-overflow candidates. A successful response means only that the proposal
is awaiting review; it is not evidence of acceptance or persistence.

## Evidence and limitations

Passing protocol, Python, TypeScript, and browser tests establishes behavior for the checked
fixtures and browsers. It does not establish that third-party plugin code is trustworthy, that a
plugin's game presentation is factually correct, that every browser resource-exhaustion case is
contained, or that a future marketplace is safe. Plugin identity, source, version, content digest,
enabled state, approval state, API compatibility, and active contributions remain separately
inspectable.
