# Kirin source syntax v1

Kirin source is the sole workspace source format. Its public document types are `entry` and `plot`; named parameter presets live inside entries. Documents use the `.kirin` extension.

## Document header, comments, and prose

Every document starts with a format declaration and one document identity:

```text
@kirin 1
@entry skill_a
```

The other identity is `@plot ID`. IDs use `[A-Za-z_][A-Za-z0-9_]*`. A line whose first non-space characters are `//` is an author comment and has no schema meaning. The typed document name currently defaults to its ID.

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
@template model

// Model

inputs:
  x "Input": number[dimensionless] = 0.25 in 0..1
  enabled: boolean = true

fields:
  base: dimensionless = 2
  scaled: dimensionless := base * (1 + x)

constraints:
  x >= 0
  x <= 1

functions:
  multiply(n: number[dimensionless]) -> dimensionless =
    scaled * n

outputs:
  result "Result": dimensionless = scaled
```

Supported directives are `@template`, `@game-version`, and `@status`. Supported sections are:

- `sources`: one structured JSON object per line, including at least `kind` and `citation`; optional fields include `location`, `verified_at`, `digest`, and `game_version`.
- `aliases`: `UNICODE_NAME = ENTRY_ID.MEMBER`; aliases are local to this entry.
- `inputs`: `NAME ["LABEL"]: TYPE [= DEFAULT] [in MIN..MAX] [integer] [one-of [...]]`.
- `constraints`: one boolean expression per declaration; indented continuation lines are joined.
- `fields`: `NAME ["LABEL"]: TYPE = VALUE` or `:= EXPRESSION`.
- `info`: `NAME ["LABEL"] = JSON_VALUE`; exact decimal values must be quoted.
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

The optional quoted label on an input, field, info field, function, or output is
presentation-only. Changing it does not change references. Plot previews and exports use
member labels by default; an explicit plot `as "LABEL"` still takes precedence.

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

## Plot

```text
@kirin 1
@plot curve

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

`x`, `range`, `points`, and at least one indented `y` target are required. A quoted label after `as` becomes the curve label. Export paths remain confined to the workspace in the TUI.

## TUI editing states

The TUI is a calculation and comparison workbench with Calculate, Charts, Documents, Diagnostics, and Runs entry points. Documents remain the authoritative definitions; calculations, charts, selectors, and comparison tables are derived views.

The Documents view retains an in-memory buffer for every opened document and validates them together as a workspace overlay. `Ctrl+N` creates an in-memory draft without writing a file. `Ctrl+P` switches documents without discarding drafts. Its selector shows the first non-empty `//` comment as a presentation-only title alongside the stable relative path and its new/modified state. It reports three practical states:

- modified and invalid: diagnostics are shown and save/export is rejected;
- modified and valid: calculations and plot preview use the draft without writing it;
- saved and valid: the buffer matches the atomic on-disk write.

The Calculate view evaluates one declared output for one or more named variants against the same validated workspace revision. Targets are ordered and searched by author-defined groups. Variant inputs may use a typed form or advanced text with canonical names, unique local names, or display labels; exact percentages are normalized before the engine sees them. It can solve one input against a requested output value or solve a finite linked system using the first variant as the baseline. Unsaved but valid overlays may be explored, but durable run records require saved sources.

The Charts view performs either an ad-hoc curve scan or a two-input heatmap and uses the same result for its preview and data table. It may alternatively scan the variants currently configured on Calculate as named curves on one shared axis, and it can load every curve from a saved Plot. A single-preset curve exploration may create a Plot source draft; multi-variant curves and heatmaps remain interactive results and can export their data rather than being silently converted to a different source shape. `Ctrl+S` validates and saves every modified buffer. `Ctrl+E` does the same, then recomputes the current saved Plot document and replaces its configured SVG/CSV exports.

TUI status text and common diagnostics are presented in Chinese without changing core error codes or CLI JSON. A diagnostic includes the relative source path, line and column, formal entry/field identity, a Chinese explanation, and the original technical message. When the failing line contains common full-width Chinese punctuation, the diagnostic suggests the corresponding Kirin punctuation rather than silently rewriting the source.

The editor applies Kirin-specific highlighting without treating the file as another language. Directives, section names, declarations, aliases, qualified references, calls, types, strings, exact numbers, booleans, comments, and prose fences receive distinct styles.

`Ctrl+Space` opens completion. Use Up/Down, Enter, and Escape to navigate, insert, and close it. Candidate indexing is deliberately tolerant of incomplete drafts and includes every on-disk document plus every in-memory buffer. Formal IDs, Chinese display labels, and entry-local aliases are searchable; function candidates place the cursor inside the call. Units, domains, dimensions, built-in functions, booleans, and common constraint keywords are also included.

Chinese snippet triggers include `条目文档`, `图表文档`, `输入`, `别名`, `字段`, `函数`, `查表`, `输出`, `分组`, `参数方案`, `显示`, `约束`, `说明字段`, `来源`, `长说明`, `图表`, `分段`, and `条件`. Snippets preserve the current indentation and use an internal cursor marker that is removed on insertion.
