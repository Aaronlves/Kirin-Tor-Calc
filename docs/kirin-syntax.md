# Kirin Tor source syntax v2

Kirin Tor uses one public source format: `.kirin` with `@kirin 2`. Each file is one
`entry`; calculations, game data, named objects, fixed sequences, bounded Process definitions,
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
sums/products, lookup and interpolation, finite distribution functions, finite recurrence
functions, and finite-state analytical functions.

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

## Semantic interfaces for fixed cycles

Kirin Tor does not assume resource names such as mana, energy, rage, or charges. A type maps
author-chosen fields to named resource roles used by cycle analysis:

```text
type skill:
  mana_cost: mana = 0
  charge_cost: charge = 0
  charge_gain: charge = 0
  cast_time: time
  cooldown: time = 0 second
  cycle_step:
    occupies = cast_time
    cooldown = cooldown
    spends:
      mana = mana_cost
      charge = charge_cost
    gains:
      charge = charge_gain

type character_profile:
  starting_mana: mana
  maximum_mana: mana
  mana_per_time: mana_per_time
  starting_charge: charge
  maximum_charge: charge
  charge_per_time: charge_per_time
  cycle_profile:
    resources:
      mana:
        initial = starting_mana
        maximum = maximum_mana
        regeneration = mana_per_time
      charge:
        initial = starting_charge
        maximum = maximum_charge
        regeneration = charge_per_time
```

The mapping is written once on the type. Every skill object then contains only its own values:

```text
input haste "急速": probability = 20%

skill arcane_blast "奥术冲击":
  mana_cost = 30
  charge_gain = 1
  cast_time = 3/2 second / (1 + haste)
```

`spends` is applied at action start; `gains` is applied at action finish. Both sections are optional,
but `occupies` is required. Every named profile resource requires `initial`, `maximum`, and
`regeneration`. The resource name connects step effects to the profile; units are still independently
checked. A fixed cycle may use at most 64 resources and 256 spend/gain mappings per step.

Action cooldowns and discrete charges are opt-in roles on `cycle_step`; Kirin Tor does not infer
them from field names. A charged action type can be declared separately:

```text
type charged_skill:
  cast_time: time
  maximum_charges: positive_integer
  recharge_time: time
  cycle_step:
    occupies = cast_time
    charges:
      maximum = maximum_charges
      recharge = recharge_time
```

`cooldown` must be non-negative time and starts when the action starts. `charges.maximum` and
`charges.recharge` must appear together; the maximum is a positive integer up to 64 and recharge
time is positive. Charges begin full unless the interface also maps `charges.initial`. Missing
charges recover one after another, not in parallel. The same canonical skill object shares one
cooldown and one charge pool wherever its readable skill name occurs in the sequence.

For a deliberately single-resource model, the compact `cost` plus flat `initial`, `maximum`, and
`regeneration` interface remains valid and is normalized to the same state-vector engine.

## Fixed sequence analysis

```text
character_profile raid_profile "团队副本角色":
  starting_mana = 100
  maximum_mana = 100
  mana_per_time = 10
  starting_charge = 0
  maximum_charge = 4
  charge_per_time = 0

cycle main_rotation "主要循环":
  using = raid_profile
  sequence:
    - arcane_blast
    - arcane_blast
    - arcane_barrage
```

Analyze it with:

```bash
kt cycle rotation.main_rotation
kt cycle rotation.main_rotation --set rotation.haste=0.3 --json
```

The operation returns one of three exact outcomes:

- `continuous`: the declared sequence can repeat forever without inserted waits;
- `waiting`: it can repeat forever if Kirin Tor waits just long enough before a resource,
  cooldown, or charge constraint;
- `blocked`: a step can never execute, for example because its cost exceeds the maximum or the
  resource cannot recover.

The report includes every declared resource and unit, resource and action-readiness failures, all
constraints that jointly determine the first wait, the global step number, cycle and position,
waiting time per eventual cycle, waiting time per minute, and eventual cycle duration. Preset and
temporary input values are honored, and a cycle run can be saved and replayed like other operations.

The current timeline is deliberately exact and narrow:

1. A step checks all named `spends`, its action-local cooldown, and its available charge.
2. At action start it applies `spends`, starts `cooldown`, and consumes one charge when configured.
3. Every resource regenerates simultaneously during `occupies`, independently capped at its own
   `maximum`.
4. All cooldowns count down and all missing charges recharge during both `occupies` and inserted
   waits. Sequential charge recovery preserves partial progress toward the next charge.
5. All named `gains` are applied at action finish and capped.
6. If the next step fails several constraints, analysis waits for the slowest recoverable one; all
   resource and readiness states continue to advance during that shared wait.
7. A resource with zero passive regeneration can still be produced by earlier skills. If it is
   insufficient when required, waiting cannot repair the deficit and the sequence is blocked.

Current cycle analysis has a deterministic fixed sequence, non-negative spends/gains, positive
durations, bounded resource pools, action-local cooldowns, and sequential discrete charges. It does
not yet model conditional priorities, shared cooldown groups, cooldown or charge resets, random
procs, clipping, latency, or branching action lists. Those belong to later state-transition layers
and are not guessed from property names.

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

## Tables, finite distributions, recurrences, and state models

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

recurrence protection: probability:
  initial = chance
  steps = failures
  next(current, index) = min(current + increment, 1)

state_model proc_state:
  states:
    - ready
    - cooldown
  transitions:
    - ready -> ready @ 1 - chance
    - ready -> cooldown @ chance
    - cooldown -> ready @ 1
  rewards:
    reward value: damage:
      ready = hit
      cooldown = 0
```

Tables are ordered and exact. Finite distributions require probabilities in `0..1` that sum
exactly to one. Recurrences are pure and statically bounded to at most 1,000 steps. State models
are finite analytical systems, not event simulations; the current bounds are 16 states, 256
transitions, and 64 rewards.

## Bounded Process declarations

The public source parser, workspace loader, and canonical renderer now accept typed `process`
blocks. A Process declaration is lowered outside the legacy raw mapping into `ProcessAst` and then
immutable `ProcessIR`:

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
  decide every 1/2 second from 0 second phase decision:
    - wait
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
```

`scenario` lowering resolves every Process instance, input, local-to-global phase binding, event
connection, send, composite action, decision point, observation, stop condition, and mandatory
fuel bound. It rejects statically enumerable batch conflicts, invalid phase mappings, overlapping
decision points, and schedules that already exceed their declared event/decision fuel. `analysis`
resolves `run`, `compare`, `optimize`, `reach`, `steady`, or `cycle` requests and typed objectives.

No operation executes a Process yet, so these declarations currently establish and validate the
complete composition rather than produce a trace. Runtime fuel accounting and analysis execution
remain pending. The full contract and complete executable-target examples are documented in
[有界 Process 模型](bounded-process-model.md) and
[有界 Process 纸面模型](bounded-process-paper-models.md).

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

## Authoring boundary

The browser editor provides v2 snippets, syntax highlighting, completion for canonical and
multi-level paths, navigation, safe rename for scalar declarations, diagnostics, live scalar/chart/
cycle previews, and a syntax reference. These are tolerant projections over complete or incomplete
drafts. Generic document editing and validation preserve Process blocks, but Process-specific
completion, highlighting, outline items, previews, and execution are not implemented yet. Authoring
projections do not extend the grammar or make invalid source executable.
