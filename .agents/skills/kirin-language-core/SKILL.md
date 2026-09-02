---
name: kirin-language-core
description: Develop, debug, review, or document the Kirin source language and mathematical core in the calculator project. Use for syntax, schema, units, expressions, validation, bounded mathematical models, engine behavior, authoring support derived from the language, and directly related tests. Do not use for work confined to the browser interface, package resolution, or release-only verification.
---

# Kirin Language Core

Make focused changes to Kirin's language and mathematical core without turning ordinary development into a formal review process.

## Work from current authority

- Inspect the current branch, relevant implementation, tests, and local diff before relying on earlier notes.
- Read only the documents needed for the task. Use `docs/kirin-syntax.md` for source syntax, `docs/schema-and-expressions.md` for semantic and safety contracts, and `docs/game-mechanics-capability-audit.md` when a claim concerns supported game-mechanic shapes.
- Treat `.kirin` files as the editable workspace authority. Keep canonical identifiers stable; aliases, labels, diagnostics, indexes, previews, and generated artifacts do not replace them.
- Preserve unrelated user changes in a dirty worktree.

## Implement proportionately

Locate the smallest relevant seam among parsing/rendering, schema construction, units and domains, restricted expressions, engine evaluation, limits, authoring assistance, and tests. Make the smallest coherent change that satisfies the request.

Maintain these invariants when they are relevant:

- Exact numbers, dimensions, units, domains, and retained conditions keep their mathematical meaning across parsing and evaluation.
- User-authored expressions remain restricted: do not introduce arbitrary imports, execution, attribute traversal, or unbounded computation.
- Finite distributions and Process execution remain explicitly bounded. Do not infer probabilistic independence that the author did not declare.
- Parser, renderer, schema, completion, diagnostics, and engine should agree on public syntax, but touch only the layers affected by the change.
- Update public documentation when the public language or behavior changes. Internal refactors do not require documentation churn.

Prefer existing abstractions and tests. Do not add registries, status files, approval gates, or broad compatibility layers merely to satisfy this skill.

## Verify according to risk

- For a small fix, run the narrowest relevant test or test file.
- For a new syntax or semantic behavior, add or update focused success and failure coverage when it provides real regression value.
- Expand to related suites when a change crosses parser, schema, engine, safety-limit, record, or authoring boundaries.
- Reserve the full test suite, packaging checks, frontend build, and cross-platform matrix for broad changes or release work.

Report what was actually verified. Automated checks establish only the behavior they exercised; do not claim broader release readiness or human acceptance.
