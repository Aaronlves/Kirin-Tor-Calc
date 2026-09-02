# Kirin Tor source syntax v2

Kirin Tor uses one public source format: `.kirin` with `@kirin 2`. Each file is one
`entry`; calculations, game data, named objects, bounded Process definitions,
presets, and optional charts can live in the same file. The source remains the editable authority.
Indexes, previews, and run records are derived projections.

The surface language deliberately reuses four forms:

```text
keyword name: type = expression

kind name "可选显示名":
  property = value

block:
  - ordered item

object.child.leaf
```

There are no section containers such as `inputs:` or `outputs:` in v2.

## Document header, labels, comments, and prose

```text
@kirin 2
@entry rotation "奥术循环"
@game-version "11.2.0"
@status "draft"

// This comment has no schema meaning.

----
Free-form UTF-8 explanation, evidence notes, and scope boundaries.
Tabs and text that resemble syntax are preserved inside this fence.
----
```

Formal IDs use `[A-Za-z_][A-Za-z0-9_]*`. The quoted entry label and other quoted labels
are presentation-only and may use Chinese. The supported directives are `@game-version` and
`@status`. Outside prose fences, indentation uses spaces; tabs are rejected.

Only `@kirin 2` is public. A v1 file fails explicitly instead of being guessed or silently
translated.

## Scalar declarations and expressions

```text
input crit "暴击率": probability = 25%
input targets "目标数": count = 3 in 1..8
input enabled "启用": boolean = true

field base "基础伤害": damage = 1000
field adjusted "修正伤害": damage = base * (1 + crit)

require targets >= 1

function per_target(n: count): damage = adjusted / n

output result "结果": damage = if_else(enabled, per_target(targets), 0)
display result = integer
```

- `input` declares a variable and may add a default, `in MIN..MAX`, `integer`, or
  `one-of [A, B, ...]`.
- `field` declares a literal or derived value.
- `require` adds a boolean condition to the entry.
- `function` declares explicit parameters. Parameters may have ranges and allowed values but no
  defaults.
- `output` declares a public scalar result.
- `display` changes presentation only: `number`, `integer`, `percent`, or
  `coefficient_percent`, optionally followed by `digits N`.

Types are `boolean`, `number[UNIT]`, a named unit, or a named domain. Exact integers,
decimals, fractions, and percentages are accepted. `25%` means exactly `25 / 100`.
Whitespace makes a numeric unit literal readable: `3/2 second` is lowered to
`3/2 * second`. General implicit multiplication is not accepted.

Expressions remain restricted mathematical expressions. They do not support assignment,
imports, arbitrary Python calls, mutation, or executable hooks. Supported families include
arithmetic and comparisons, `if_else`, `piecewise`, `min`, `max`, `abs`, `sqrt`, exact finite
sums/products, lookup and interpolation, and finite distribution functions. Time- and path-dependent
state changes belong to Process declarations rather than scalar-expression built-ins.

## Dimensions, units, and domains

The core provides `dimensionless`, physical `time`, `second`, `millisecond`, and the
game-neutral domains `probability`, `count`, `nonnegative_integer`, and `positive_integer`.
Game vocabulary is ordinary source data:

```text
dimension damage "伤害"
dimension resource "资源"

unit damage = damage
unit resource = resource
unit resource_per_time = resource / time
unit damage_per_resource = damage / resource

domain rank: number[dimensionless] in 1..3 integer

domain dot_mode "周期模式":
  - snapshot "快照"
  - dynamic "动态"
```

Unit expressions allow a positive exact scale, dimensions, multiplication, division, and exact
integer or rational powers. Values are converted to an exact canonical scale and displayed in the
declared unit. Kirin Tor never infers a unit from a field name.

A block-form domain is a closed symbolic domain. Its ASCII symbols are stable values; quoted
labels are presentation-only. Symbolic domains cannot declare units, numeric bounds, or `integer`.
A short symbol is accepted when the expected symbolic type identifies its domain; where the same
symbol exists in several domains and context does not resolve it, use `domain_id.symbol`.

## Closed types and named objects

A `type` gives a reusable set of allowed properties. An object declaration uses that type name as
its first word:

```text
type coefficient:
  direct: damage
  periodic: damage

type skill:
  cost: resource
  occupies: time
  coefficient: coefficient

skill arcane_blast "奥术冲击":
  cost = 30
  occupies = 3/2 second
  coefficient:
    direct = 1000 damage
    periodic = 250 damage

output dot "持续部分": damage = arcane_blast.coefficient.periodic
```

Objects are closed: an unknown property is an error, as is a missing required property. A field can
be optional with `?`, or supply a default:

```text
type skill:
  cost: resource = 0
  cooldown?: time
```

Member paths are statically resolved and may have multiple levels:

- `arcane_blast.cost` inside the owning entry;
- `skills.arcane_blast.cost` from another entry;
- `arcane_blast.coefficient.periodic` for a nested structure.

A type can be reused from another entry as `entry.type`. Type and field names are stable ASCII
identity; quoted labels remain presentation-only.

## Aliases and structured sources

```text
alias 法强 = character.spell_power
alias 周期伤害 = skills.arcane_blast.coefficient.periodic

source hotfix_note:
  citation = "Patch note URL or bibliographic citation"
  location = "Section 3"
  verified_at = "2026-09-02"
```

An alias is local to its entry and may target a multi-level member path. Dependencies, CLI targets,
presets, and run records continue to use canonical paths. A source block requires `citation`; its
declaration name becomes `kind`. Optional properties are `location`, `verified_at`, `digest`, and
`game_version`.

## Groups and presets

```text
group summary "摘要":
  - result
  - dot

preset raid "团队副本":
  rotation.haste = 20%
  rotation.targets = 1
```

Groups organize local outputs without changing mathematics. Presets store named assignments to
formal inputs. One-sided ranges use `*`, as in `in 0..*`.

## Tables and finite distributions

```text
table rating:
  input = dimensionless
  output = dimensionless
  points:
    1 = 10
    3 = 30

distribution proc: damage:
  outcomes:
    - 0 @ 1 - chance
    - hit @ chance
```

Tables are ordered and exact. Finite distributions require probabilities in `0..1` that sum
exactly to one. Bounded iteration uses Process state plus a finite event chain; finite transition
systems use Process branches with `reach` or `steady` analysis. The former `recurrence` and
`state_model` declarations were removed in the single-language Process cutover.

## Bounded Process declarations

The public source parser, workspace loader, and canonical renderer accept typed `process` blocks.
A Process declaration is lowered into `ProcessAst` and then immutable `ProcessIR`:

```text
process delayed_damage "伤害延迟池":
  input maximum_health: health
  input conversion: probability = 80%
  state health: health = maximum_health in 0 health..maximum_health
  state pool: damage = 0 damage in 0 damage..30000 damage
  key pool_tick
  phase periodic_tick
  event input incoming_damage(amount: damage reduce sum)
  event internal stagger_tick()

  on incoming_damage(amount):
    let delayed: damage = amount * conversion
    next health = max(0 health, health - (amount - delayed))
    next pool = pool + delayed
    replace stagger_tick() after 1/2 second phase periodic_tick key event.id

  observe alive: boolean = health > 0 health
```

The accepted Process surface includes typed inputs and state, requirements, keys, local phase
slots, input/output/internal events, guarded actions and handlers, closed flow expressions,
`let`/`next`, event emission, keyed schedule/replace/cancel, finite nested `when`, finite
independent/joint branches, and observations. Value types additionally include `event_id`,
`list[TYPE, CAPACITY]`, and `map[KEY, VALUE, CAPACITY]`.

Loading now performs full Process expression type inference, lowers expressions to a safe immutable
evaluation IR, and rejects possible duplicate state or schedule-key writes within one transition.

The same source can declare a composition and an analysis request:

```text
scenario survival:
  phases:
    - incoming
    - decision
  use actor = delayed_damage:
    maximum_health = 100 health
    conversion = 80%
    phase periodic_tick = incoming
  every 1/2 second from 1/2 second phase incoming:
    send actor.incoming_damage(amount = 50 health)
  policy always_wait:
    otherwise wait
  decide every 1/2 second from 0 second phase decision:
    - wait
  measure survival_time: time = first_time(not actor.alive, default = horizon)
  objective longest_survival:
    maximize survival_time
  stop when not actor.alive
  bounds:
    horizon = 60 second
    maximum_events = 1000
    maximum_decisions = 121
    maximum_branches = 10000
    maximum_entities = 1

analysis survival_run:
  using = survival
  operation = run
  policy = always_wait

analysis survival_search:
  using = survival
  operation = optimize
  objectives:
    - longest_survival
```

`scenario` lowering resolves every Process instance, input, local-to-global phase binding, event
connection, send, composite action, decision point, observation, stop condition, and mandatory
fuel bound. It rejects statically enumerable batch conflicts, invalid phase mappings, overlapping
decision points, and schedules that already exceed their declared event/decision fuel. `analysis`
resolves `run`, `compare`, `optimize`, `reach`, `steady`, or `cycle` requests, typed trajectory
Measures, and named constrained lexicographic Objectives.

The deterministic runtime API executes a lowered scenario with exact time, simultaneous phase
snapshots, reducers, flow, guards, stable event IDs, keyed scheduling, state/domain checks, stop
conditions, runtime fuel enforcement, and a replay-stable trace. A scenario with ambiguous decision
choices requires an explicit selector; random branches are rejected by this deterministic path.
`run`, source-Policy `compare`, deterministic bounded `optimize`, exact random `reach`, finite-state
`steady`, and exact repeated-state `cycle` are dispatched through `kt analyze ENTRY.ANALYSIS` and
can be saved/replayed with embedded source snapshots. The finite optimizer returns every Measure for
each selected Objective and labels exhaustive finite policy enumeration as `exact_global`; it uses
no hidden time grid or numerical tolerance. The browser workbench exposes the same named Analysis,
variant/objective table, proof labels, traces, and multi-chart projections in the document flow. The
full contract and complete examples are documented in
[有界 Process 模型](bounded-process-model.md) and
[有界 Process 纸面模型](bounded-process-paper-models.md).

Besides `decide every`, a Scenario may use `decide after INSTANCE.PUBLIC_EVENT`, `decide when
CONDITION`, or `decide continuously up to COUNT times from START until END`. Exact affine flow
crossings use rational roots. General free-time search requires an Analysis `search:` block with
`method = adaptive_dyadic`, an explicit `time_tolerance`, and `maximum_evaluations`; its proof level
is `best_found`, not global optimality.

For a finite random Process, Analysis evaluates every complete path Measure before combining exact
numeric `measure_expectations`, and labels the result `strict_finite_output_expectation`. A source
that merely supplies average damage as deterministic events remains a `deterministic_scenario`;
Kirin does not identify the two or silently substitute sampling.

## Chart projection

```text
chart preview "伤害曲线":
  x = model.targets
  range = 1..8
  points = 8
  y:
    - model.result as "总伤害"
  using = model.raid
  x_label = "目标数"
  y_label = "伤害"
  export_svg = "results/damage.svg"
  export_csv = "results/damage.csv"
```

One entry may declare one chart. `x`, `range`, `points`, and at least one `y` item are required.
Preview is derived from the current source; export paths are explicit and confined to the workspace
unless the caller deliberately opts out.

This one-chart limit applies only to the static scan chart above. A Process `analysis` may contain up
to 64 chart blocks with `kind = trajectory|decision_surface|pareto|variant_comparison`. Trajectory
series read public observations and may mark `event INSTANCE.PUBLIC_EVENT` or `decision ACTION`;
Pareto axes require explicit `x_direction` and `y_direction`. Their structured rows are derived from
optimal runs and bounded search candidates. `kt analyze ENTRY.ANALYSIS --export-charts` writes each
configured SVG/CSV explicitly; preview data itself never becomes editable authority.

## Authoring boundary

The browser editor provides v2 snippets, syntax highlighting, completion for canonical and
multi-level paths, navigation, safe rename for scalar declarations, diagnostics, and live scalar,
chart and Process Analysis previews. Process/Scenario/Analysis have insertion snippets,
top-level outline identities, contextual syntax help, variant/objective result tables, proof badges,
interactive multi-chart selection, and explicit export-all. These authoring projections do not
extend the grammar or make invalid source executable.
