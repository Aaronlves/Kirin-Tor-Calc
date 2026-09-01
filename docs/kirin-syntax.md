# Kirin source syntax v1

Kirin source is the sole workspace source format. Every source is one `entry` document; formulas, presets, and optional chart configuration live in that same authority. Documents use the `.kirin` extension.

## Document header, comments, and prose

Every document starts with a format declaration and one document identity:

```text
@kirin 1
@entry skill_a
```

IDs use `[A-Za-z_][A-Za-z0-9_]*`. A line whose first non-space characters are `//` is an author comment and has no schema meaning. The typed document name currently defaults to its ID.

One document-level description may be enclosed by matching fences of three or more hyphens:

```text
----
This prose is preserved as description text.
A line containing --- is ordinary prose because the fence has four hyphens.
----
```

Fence contents are opaque UTF-8 text. Outside a prose fence, tabs are rejected and spaces control indentation.

## Entry

```text
@kirin 1
@entry model

// Model

inputs:
  x "Input": number[dimensionless] = 0.25 in 0..1
  enabled: boolean = true

fields:
  base: dimensionless = 2
  scaled: dimensionless = base * (1 + x)

constraints:
  x >= 0
  x <= 1

functions:
  multiply(n: number[dimensionless]) -> dimensionless =
    scaled * n

outputs:
  result "Result": dimensionless = scaled
```

Supported directives are `@game-version` and `@status`. Supported sections are:

- `sources`: one structured JSON object per line, including at least `kind` and `citation`; optional fields include `location`, `verified_at`, `digest`, and `game_version`.
- `aliases`: `UNICODE_NAME = ENTRY_ID.MEMBER`; aliases are local to this entry.
- `inputs`: `NAME ["LABEL"]: TYPE [= DEFAULT] [in MIN..MAX] [integer] [one-of [...]]`.
- `constraints`: one boolean expression per declaration; indented continuation lines are joined.
- `fields`: `NAME ["LABEL"]: TYPE = VALUE_OR_EXPRESSION`.
- `functions`: `NAME ["LABEL"](PARAMETERS) -> UNIT = EXPRESSION`.
- `tables`: versioned ordered lookup points, with explicit input and output units.
- `outputs`: `NAME ["LABEL"]: UNIT = EXPRESSION`.
- `groups`: author-defined named output groups; the engine supplies no built-in categories.
- `presets`: named input assignments belonging to this entry.
- `display`: output formatting as `number`, `integer`, `percent`, or `coefficient_percent`, optionally followed by `digits N`.

Types are `boolean`, `number[UNIT]`, or a named unit/domain. Function parameters use the same type and constraint spelling as inputs but cannot define defaults.

One-sided bounds use `*` for the open side: `in 0..*` or `in *..1`.

## Local aliases and display labels

Formal document and member IDs remain ASCII. An entry may give frequently used qualified
members a Unicode alias for formulas in that entry:

```text
aliases:
  法强 = character.spell_power
  暴击率 = character.crit
  技能 = fireball.expected

outputs:
  result "期望伤害": damage = 技能(法强, 暴击率)
```

An alias may target an input, field, output, or function. It may not shadow a declared
member or a built-in expression function, and other documents cannot reference it.
Dependencies, parameters, presets, CLI arguments, and run results continue to use
canonical qualified identities.

The optional quoted label on an input, field, function, or output is
presentation-only. Changing it does not change references. Chart previews and exports use
member labels by default; an explicit curve `as "LABEL"` still takes precedence.

## Dimensions, units, and domains

The mathematical core always provides `dimensionless`, physical `time`, `second`,
`millisecond`, and the game-neutral domains `probability`, `count`,
`nonnegative_integer`, and `positive_integer`. It does not provide damage, healing,
attributes, resources, classes, or any other game vocabulary.

Any entry may declare shared mathematical semantics:

```text
dimensions:
  damage "伤害"
  time "时间"

units:
  damage = damage
  time = time
  millisecond = 1/1000 * time
  damage_per_time = damage / time

domains:
  probability: number[dimensionless] in 0..1
  positive_integer: number[dimensionless] in 1..* integer
```

Unit expressions allow a positive exact scale, dimension names, multiplication, division, and exact integer or rational powers. Values are converted to one exact canonical scale during calculation and converted back to the declared unit for results, scans, tables, bounds, and solves. For example, `500 * millisecond + 1 * time` is exactly `3/2 time`.

Expressions use the existing restricted Kirin Tor expression language. They do not acquire assignment, imports, arbitrary Python calls, or implicit multiplication.

Community Package sources use the same syntax and parser. Package protocol v1 requires every
exported document, dimension, unit, and domain to begin with the manifest namespace prefix;
cross-Package references continue using those stable prefixed IDs. Package sources are read-only
inside a consuming workspace and cannot install executable extensions. See
[Kirin community package protocol v1](package-system-v1.md).

## Groups, presets, tables, and display

```text
groups:
  throughput "输出收益":
    result

presets:
  baseline "当前配装":
    model.x = 0.5
    selection.enabled = true

tables:
  rating "等级换算": dimensionless -> dimensionless:
    1 = 10
    3 = 30

display:
  result: percent digits 2
```

Group members must be local outputs and may appear in at most one group. Preset values must refer to declared inputs; use `entry.preset` outside the owning entry. `lookup(rating, key)` requires an exact table key, while `interpolate(rating, key)` linearly interpolates within the declared domain. Exact decimals need no quoting in Kirin source.

## Optional chart projection

```text
@kirin 1
@entry model

inputs:
  x: number[dimensionless] = 0

outputs:
  result: dimensionless = x

x: model.x
range: 0..1
points: 101

y:
  model.result as "Result"
  alternative.result as "Alternative"

preset: model.baseline
title: "Comparison"
x-label: "Input"
y-label: "Value"
export-svg: "results/curve.svg"
export-csv: "results/curve.csv"
```

When any chart key is present, `x`, `range`, `points`, and at least one indented `y` target are required together. Without them the document simply has no chart projection. A quoted label after `as` becomes the curve label. Browser-workbench export paths remain confined to the workspace.

## Browser workbench editing states

The local browser workbench has two top-level product spaces: Documents and Relationship Graph. Documents remain authoritative; diagnostics, formula explanation, results, charts, and local relationships are derived projections. Runs and Packages are workspace tools opened from the workspace menu rather than permanent destinations.

The Documents view retains an in-memory buffer for every opened document and validates them together as a workspace overlay. Its selector shows the first non-empty `//` comment as a presentation-only title alongside the stable relative path and its new/modified state. It reports three practical states:

- modified and invalid: diagnostics are shown and save/export is rejected;
- modified and valid: result, chart, formula, and relationship projections use the draft without writing it;
- saved and valid: the buffer matches the atomic on-disk write.

The document preview evaluates declared outputs and reveals a chart only when that document defines `x/range/points/y`. Temporary inputs use text with canonical names, unique local names, or display labels; exact percentages are normalized before the engine sees them. Unsaved but valid overlays may be explored, but durable run records require saved sources. Save All validates and atomically saves every modified buffer.

The Relationship Graph derives member-level edges from parsed formulas and aggregates them into a document-level projection. The document inspector uses the same graph data for a local zero-, one-, or two-hop projection; no relationship is guessed from comments or keyword overlap.

Workbench status text and common diagnostics are presented in Chinese without changing core error codes or CLI JSON. A diagnostic includes the relative source path, line and column, formal entry/field identity, a Chinese explanation, and the original technical message. When the failing line contains common full-width Chinese punctuation, the diagnostic suggests the corresponding Kirin punctuation rather than silently rewriting the source.

`Ctrl+Space` opens Kirin-aware completion. Use Up/Down, Enter, and Escape to navigate, insert, and close it. Candidate indexing is deliberately tolerant of incomplete drafts and includes every on-disk document plus every in-memory buffer. Formal IDs, Chinese display labels, and entry-local aliases are searchable. Units, domains, dimensions, built-in functions, booleans, and common constraint keywords are also included.

Chinese snippet triggers include `条目文档`, `输入`, `别名`, `字段`, `函数`, `查表`, `输出`, `分组`, `参数方案`, `显示`, `约束`, `来源`, `长说明`, `图表`, `分段`, and `条件`. Snippets preserve the current indentation and remove the internal cursor marker on insertion.
