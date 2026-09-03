---
name: kirin-documentation
description: Create, revise, or review Kirin Tor documentation. Use for README guidance, syntax and schema references, package and workbench documentation, capability boundaries, changelog entries, examples, and author-facing explanations. Do not use to change implementation unless the user also asks for code changes.
---

# Kirin Tor Documentation

Keep documentation accurate, useful to authors, and proportionate to the change.

## Write from evidence

- Inspect the current implementation, tests, CLI help, and directly relevant document before asserting behavior.
- Use `docs/kirin-syntax.md` for syntax, `docs/schema-and-expressions.md` for semantic and safety contracts, `docs/package-system-v1.md` for packages, `docs/web-workbench.md` for the browser product, and `docs/game-mechanics-capability-audit.md` for capability claims.
- Prefer the current repository over remembered behavior. Preserve the existing language and audience of the document unless the user asks to change them.

## Preserve clear boundaries

- Keep `.kirin` source authority distinct from indexes, previews, generated artifacts, lockfiles, caches, and run-record snapshots.
- Keep canonical identifiers distinct from Chinese-friendly aliases, labels, and explanations.
- Separate implemented behavior, tested behavior, design intention, known limitation, and human acceptance.
- Do not state that Kirin Tor can derive a complete gameplay loop when it only evaluates an author-supplied formula or equivalent model.

Make the smallest documentation update that resolves the request. Do not rewrite adjacent sections, add a changelog entry for every internal edit, or force documentation work to trigger code changes.

Verify commands, examples, links, or calculated outputs when they are central and cheap to check. Otherwise mark uncertainty or leave unsupported detail out. Report documentation-only work as documentation, not implementation.
