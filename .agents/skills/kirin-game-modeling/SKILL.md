---
name: kirin-game-modeling
description: Model game mechanics, calculations, and theorycrafting questions as Kirin Tor sources or community-package content. Use when translating rules, coefficients, assumptions, expected values, thresholds, comparisons, or curves into a source-faithful model. Do not use for changing the language core unless the user separately asks for that implementation work.
---

# Kirin Tor Game Modeling

Produce useful game models without presenting assumptions or derived formulas as authoritative game facts.

## Separate the evidence

Keep these layers distinguishable to the degree the task needs:

- Published game rules, coefficients, patch data, or other supplied source material.
- Author assumptions and simplifications, including independence, steady-state rates, coverage, expected counts, and rounding locations.
- The derived mathematical model expressed in `.kirin`.
- Results produced by Kirin Tor for specified inputs.

When current game facts matter and are not supplied, verify them from current primary sources where practical. Record the relevant game or patch version and mark missing, unofficial, inferred, or uncertain values rather than inventing them.

## Choose an honest model boundary

- Read `docs/game-mechanics-capability-audit.md` when deciding whether a mechanic is directly expressible, requires an externally derived equivalent model, or remains unsupported.
- Keep game-specific names, formulas, and data in workspace or community-package sources rather than privileging them in the core.
- Use exact values, units, domains, presets, tables, distributions, or bounded Process state/event models only when their assumptions match the mechanic.
- Do not infer probabilistic independence, server rounding, hidden coefficients, or action priorities from keyword similarity or incomplete descriptions.
- If the requested mechanic exposes a core limitation, explain the gap separately. Do not modify the core without implementation authorization.

## Keep authoring light

Create the smallest readable source or package change that answers the theorycrafting question. Prefer clear descriptions and explicit assumptions over unnecessary abstraction.

Validate the changed source and evaluate one or more representative outputs when useful. Broader scans, plots, replay records, or comparison matrices are optional unless the request depends on them.
