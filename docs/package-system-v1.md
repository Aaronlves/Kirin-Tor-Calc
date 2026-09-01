# Kirin community package protocol v1

## Purpose and authority

Kirin Tor provides a game-neutral mathematical language, validator, calculation engine, and
package protocol. It does not authoritatively maintain facts, mechanics, formulas, or named
semantics for any particular game.

A community package is an independently maintained GitHub repository or local development
directory. Its checked-in `kirin.package.toml` and `.kirin` sources are authoritative. A
workspace requirement file records which packages the user requested, `kirin.lock` records the
exact resolved package graph, and the downloaded package store plus any search or UI index are
rebuildable projections.

Packages are data only. Kirin never executes package scripts, binaries, Python modules, Git
hooks, or GitHub Actions. A package may contain ordinary project files, but only its manifest and
`.kirin` files under `entries/` participate in validation or calculation.

## Core and community boundary

The installed mathematical core owns exact numbers, booleans, `dimensionless`, arithmetic,
dimension algebra, unit conversion, constraints, functions, piecewise expressions, tables,
finite discrete distributions, bounded recurrences, finite analytical state models, and the
general document grammar. It may also provide uncontroversial game-neutral vocabulary such
as probability, non-negative integers, and physical time units.

The application distribution contains only the current Python modules, browser assets, and the
explicitly allowlisted game-neutral `.kirin` tutorials under `src/kirin_tor`. Tutorials are
read-only application resources and do not load as workspace documents until the author explicitly
copies one into an unsaved draft. Repository examples, test fixtures, and community game data are
not installed. Wheel builds discard any older `build/lib/kirin_tor` staging tree before copying
current sources, and CI compares every packaged `kirin_tor/` member with that source tree so deleted
starters or obsolete modules cannot survive through a stale local build directory.

Names such as damage, healing, attack power, armor, mana, rage, cooldown rules, critical-strike
rules, character classes, skills, items, encounters, and patch data belong to community packages.
The core gives those declarations no privileged meaning.

## Package layout

A package root contains exactly one `kirin.package.toml` and may contain recursively discovered
Kirin sources under `entries/`:

```text
kirin.package.toml
entries/
  example.kirin
README.md
LICENSE
```

At least one `.kirin` source is required. Package sources are read-only when loaded into a
workspace. Package directories must not contain symbolic links or hard links in downloaded
archives, and extraction must reject absolute paths, parent traversal, duplicate paths, excessive
file counts, and excessive byte sizes.

## Manifest

`kirin.package.toml` uses UTF-8 TOML:

```toml
schema = 1
name = "community.example"
version = "1.0.0"
namespace = "community_example"
description = "A concise package description"
license = "MIT"
requires_kirin = "0.3"

# Optional descriptive compatibility metadata. It is not inferred by the core.
game = "fictional-game"
game_version = "patch-1"

[dependencies.math]
source = "github:community/game-math"
version = "1.0.0"
```

Required fields are `schema`, `name`, `version`, `namespace`, `description`, `license`, and
`requires_kirin`.

- `schema` is exactly `1`.
- `name` is a dotted, lower-case public name. It is descriptive and is not a source identity.
- `version` is an exact `MAJOR.MINOR.PATCH` semantic version. V1 deliberately has no version
  range solver.
- `namespace` matches `[a-z][a-z0-9_]*` and scopes exported Kirin identifiers.
- `description` and `license` are non-empty text. `license` should normally be an SPDX identifier.
- `requires_kirin` is an exact supported `MAJOR.MINOR` feature line.
- `game` and `game_version` are optional descriptive compatibility values. Entry-level
  `@game-version` remains the calculation-time authority.
- Dependency aliases match `[a-z][a-z0-9_]*`. Each dependency specifies one normalized source and
  one exact version. Published GitHub packages may depend only on other GitHub sources. A local
  authoring package may temporarily use an absolute `path:` dependency; relative manifest paths
  are rejected because their meaning would change after content-addressed caching.

Unknown manifest fields are errors in v1. A manifest cannot define install hooks, executable
commands, environment variables, network callbacks, or file-replacement rules.

## Source identity and namespace

The immutable identity of an installed release is the tuple:

```text
(normalized source, version, resolved commit, canonical content SHA-256)
```

The human-readable package name does not replace source identity. Moving to another GitHub owner
therefore creates a new source unless the workspace requirement is explicitly changed.

Kirin source syntax v1 uses two-part `ENTRY.MEMBER` references. To preserve that syntax while
allowing independently authored packages, every package document ID must begin with
`NAMESPACE_`. Every dimension, unit, and reusable domain declared by a package must also begin
with `NAMESPACE_`. Examples for namespace `community_example` are
`community_example_model` and `community_example_resource`.

The package loader rejects two different resolved packages that claim the same namespace. It
also rejects duplicate document IDs and conflicting mathematical declarations across the final
package graph. There is no implicit local override of package content. V1 uses explicit exported
prefixes so formulas, plots, records, and editor tooling keep one stable grammar.

## Workspace requirements

`kirin.packages.toml` is the user-authored authority for direct dependencies:

```toml
schema = 1

[packages.example]
source = "github:community/example"
version = "1.0.0"
```

For local authoring, `source` may be `path:../example`. A local requirement still records and
loads an immutable cached snapshot; editing the source directory does not silently change a
validated workspace. Running package update or restore is required to accept changed content.

Aliases are local presentation handles used by package-management commands. They do not change
Kirin document IDs or source identities.

## GitHub resolution

The normalized public source spelling is `github:OWNER/REPOSITORY`. V1 accepts public GitHub
repositories and optionally uses `GITHUB_TOKEN` for authenticated API and archive requests.

For version `1.2.3`, the resolver tries tag `v1.2.3` and then `1.2.3`, resolves the tag to a full
commit SHA through GitHub, and downloads the source archive by commit. The embedded manifest
version must equal the requested version. Branches and arbitrary refs are not accepted as normal
release dependencies.

Redirects may only end at HTTPS GitHub-controlled archive hosts. A bounded timeout, response-size
limit, archive member limit, and extracted-size limit apply. The package content digest is
calculated over the manifest and participating `.kirin` source path/content pairs in canonical
sorted order, not over transport-specific archive bytes.

## Lockfile and store

`kirin.lock` is generated JSON with `lock_version: 1`. It records:

- every direct alias;
- every transitive normalized source;
- package name, namespace, and exact version;
- Git commit for GitHub packages or normalized source path for local development packages;
- canonical content SHA-256;
- exact dependency source/version edges.

The lockfile contains no mutable branch names and no credentials. Package content is stored under
the workspace-owned content-addressed directory `.kirin/packages/SHA256/`. The directory is a
cache and should not be committed. Loading is offline and never updates it implicitly.

With an existing lockfile, `kt package restore` reconstructs missing content from the locked
commit and digest without resolving release tags again. With no lockfile it performs the initial
resolution. Only explicit add or update operations may resolve a tag to a different commit.
`kt package verify` performs no network access and verifies the lock graph, cached manifest,
namespace ownership, and canonical content digest.

Package mutations are staged and fully validated before requirements and lock files are replaced.
Failure leaves the previous declared and locked graph active.

## CLI contract

Consumer commands:

```text
kt package add ALIAS github:OWNER/REPO 1.0.0
kt package add-path ALIAS PATH
kt package remove ALIAS
kt package update ALIAS VERSION
kt package restore
kt package verify
kt package list
```

Author commands:

```text
kt package new DIRECTORY --name NAME --namespace NAMESPACE
kt package check [DIRECTORY]
```

`package new` creates data-only source, documentation, license placeholder, and GitHub Actions
validation templates. `package check` validates the manifest, namespace, dependency closure,
all Kirin sources, and all mathematical references without publishing anything.

Packages may additionally ship static creation templates under `templates/entries/**/*.kirin`.
These files may contain optional `x/y` chart configuration and are included in the Package content digest and
immutable cache snapshot. Installation and `package check` expand and validate each template
against the resolved dependency graph. A selected template creates one independent workspace
source draft; no template identity or runtime inheritance is written into that document.

## Provenance and records

Each loaded document retains its package source, package name, namespace, version, resolved
commit when available, and content digest. CLI and browser-workbench document listings expose this origin and
mark package documents read-only.

Immutable calculation records continue embedding the exact participating Kirin source snapshots.
They additionally record package release identity for auditability. Replay therefore remains
possible after the package is removed or its remote repository becomes unavailable.

## Compatibility and migration

New workspaces are always game-neutral and no longer accept a built-in game starter selection.
The legacy `initial-package` workspace line remains readable for existing workspaces but has no
runtime authority. The previously bundled game-specific starter is removed from new installations.
Repository examples may exercise game-mechanic capabilities, but
they remain outside both wheel and source-distribution payloads; reusable game-specific content
belongs in independently versioned community packages.

V1 success requires local-path and GitHub packages to share one resolver, one validator, one
lockfile, one content store, and one read-only workspace loading path. A test or successful build
does not by itself establish the correctness of community game data; package authors remain
responsible for their sources and claims.
