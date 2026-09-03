---
name: kirin-testing
description: Plan, add, run, or diagnose tests for Kirin Tor. Use for focused regression coverage, selecting relevant Python or frontend checks, isolating failures, and explaining what the evidence establishes. Do not use as a requirement to run the entire project matrix after every ordinary change.
---

# Kirin Tor Testing

Choose the smallest test effort that gives useful confidence for the requested change.

## Select by affected behavior

- Inspect the current diff and existing neighboring tests before adding new coverage.
- Prefer behavior-level assertions over tests coupled to implementation structure, generated wording, or incidental formatting.
- Extend an existing test module when it already owns the behavior; create a new module only for a genuinely distinct capability.
- Keep exact mathematical expectations exact when possible, and test error codes or structured fields when message prose is not the contract.

Useful starting points include:

- Language and engine changes: the narrow syntax, semantic, operation, capability, or safety test module.
- Package changes: `tests/test_package_system.py` and only the additional workspace or record cases affected.
- Workbench server changes: `tests/test_web.py` or `tests/test_workbench.py`.
- Frontend TypeScript changes: frontend typecheck or build; use real-browser automation only when interaction or rendered state is the subject.

## Scale with risk

- A small fix normally needs one focused regression test and its containing test file.
- Cross-module semantics may justify several related test files.
- The full Python suite, frontend production build, wheel checks, and operating-system matrix belong to broad integration or release work.

When diagnosing, reproduce first and distinguish a product regression from a stale test, environment issue, or unrelated existing failure. Do not rewrite implementation merely to make a weak test pass.

Report the command, outcome, and scope of evidence. A passing focused test does not establish release readiness or human acceptance.
