# Kirin Tor Workbench Extension Plugin protocol v1

## Purpose

Workbench Extension Plugins add presentation and workflow surfaces to the local browser
workbench without changing Kirin Tor mathematical semantics. A plugin can contribute document
renderers, top-level views, workspace tools, declarative commands, and layout profiles. The
official workbench remains the host for source editing, validation, saving, Package resolution,
artifact boundaries, and recovery.

Plugins are executable local UI extensions. They are intentionally separate from Community
Packages, which remain data only. Installing a Community Package never installs, approves,
enables, or executes a Workbench Plugin.

Protocol v1 supports explicitly selected local directories. It does not define a marketplace,
remote installer, signature authority, native executable plugin, mathematical backend plugin,
or unrestricted main-page JavaScript extension.

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
approves, enables, downloads, or executes Plugin content; Protocol v1 installation remains the
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

Sandboxed iframes are an authority boundary, not a complete resource sandbox. A plugin can still
consume browser CPU or memory while its frame is mounted. Protocol v1 therefore gives the author
an always-available disable action and Safe Mode recovery; stronger process-level browser
isolation is outside v1.

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

`kirin.plugin.json` uses schema 1:

```json
{
  "schema": 1,
  "id": "community.example-talents",
  "name": "Example Talent Workbench",
  "version": "1.0.0",
  "api": "1",
  "description": "A fictional talent-tree presentation plugin.",
  "license": "MIT",
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
        "permissions": ["document.read", "source.navigate"]
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

Protocol v1 permissions are:

- `workspace.summary`: receive bounded document and installed-Package metadata;
- `document.read`: receive the selected validated document projection, including structured
  source content, canonical IDs, Package provenance, and source coordinates;
- `source.navigate`: ask the host to open an authoritative document at a supplied source location;
- `operation.evaluate`: ask the host to evaluate a canonical target through the ordinary bounded
  operation service.

No permission grants raw filesystem, environment, process, credential, session-token, arbitrary
HTTP, Save All, Package mutation, or unrestricted operation access.

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

All requirement, lock, and store changes are staged and validated before authority files are
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
`api: 1`. The minimum lifecycle is:

1. the frame sends `ready`;
2. the host validates the frame source and sends `activate` with contribution identity and only
   the context authorized by its permissions;
3. the host sends a new `context` message when the selected document or validated projection
   changes;
4. the frame may send an `action` request for `navigate-source` or `evaluate`;
5. the host returns a correlated `action-result` or `action-error`;
6. unmounting the frame ends the capability session.

The host accepts messages only from the mounted frame's `contentWindow`, validates message shape,
IDs, sizes, action names, canonical targets, and declared permissions, and never forwards arbitrary
plugin payloads to a backend operation.

## Evidence and limitations

Passing protocol, Python, TypeScript, and browser tests establishes behavior for the checked
fixtures and browsers. It does not establish that third-party plugin code is trustworthy, that a
plugin's game presentation is factually correct, that every browser resource-exhaustion case is
contained, or that a future marketplace is safe. Plugin identity, source, version, content digest,
enabled state, approval state, API compatibility, and active contributions remain separately
inspectable.
