from __future__ import annotations

import json
from pathlib import Path

import pytest

from kirin_tor.engine import Engine
from kirin_tor.errors import DomainError, ExpressionError, ReferenceError, SchemaError
from kirin_tor.kirin_syntax import load_kirin_document, render_kirin_document
from kirin_tor.operations import evaluate, explain, scan_values
from kirin_tor.workspace import Workspace, initialize


ENTRY_SOURCE = """@kirin 2
@entry model

----
Exact model description.
This line is ordinary text: ---
	Tabs inside prose are preserved.
----

input x: number[dimensionless] = 0.25 in 0..1

require x >= 0

require x <= 1

field base: dimensionless = 2

field scaled: dimensionless = base * (1 + x)

function multiply(n: number[dimensionless]): dimensionless = scaled * n

output result: dimensionless = scaled

output doubled: dimensionless = multiply(2)
"""


def test_bundled_syntax_reference_examples_are_complete_and_valid(tmp_path: Path) -> None:
    reference_path = Path(__file__).parents[1] / "frontend" / "src" / "syntax-reference.json"
    sections = json.loads(reference_path.read_text(encoding="utf-8"))
    assert len(sections) >= 8
    assert len({section["id"] for section in sections}) == len(sections)
    assert any(section["id"] == "external-authoring" for section in sections)

    for section in sections:
        assert section["title"] and section["summary"] and section["rules"]
        root = initialize(tmp_path / section["id"])
        (root / "entries" / f"{section['id']}.kirin").write_text(
            section["code"],
            encoding="utf-8",
        )
        result = Engine(Workspace.load(root)).validate_all()
        assert result["status"] == "ok", section["id"]


def test_bundled_syntax_reference_catalog_is_complete_and_structured() -> None:
    root = Path(__file__).parents[1]
    sections = json.loads(
        (root / "frontend" / "src" / "syntax-reference.json").read_text(
            encoding="utf-8"
        )
    )
    catalog = json.loads(
        (
            root
            / "frontend"
            / "src"
            / "syntax-reference-catalog.json"
        ).read_text(encoding="utf-8")
    )

    section_ids = {section["id"] for section in sections}
    catalog_section_ids = [group["sectionId"] for group in catalog]
    assert len(catalog_section_ids) == len(set(catalog_section_ids))
    assert set(catalog_section_ids) == section_ids - {"external-authoring"}

    expected_symbols = {
        "document-header",
        "metadata-directives",
        "comments-and-prose",
        "input",
        "field",
        "require",
        "function",
        "output",
        "alias",
        "source",
        "display",
        "group",
        "preset",
        "table",
        "table-functions",
        "distribution",
        "distribution-observers",
        "distribution-transforms",
        "dimension",
        "unit",
        "numeric-domain",
        "symbolic-domain",
        "scalar-expression",
        "type",
        "object",
        "process-types",
        "process-expressions",
        "process-declarations",
        "process-effects",
        "scenario",
        "scenario-policies-decisions",
        "scenario-measures-objectives",
        "analysis",
        "analysis-chart",
        "static-chart",
    }
    symbols = [symbol for group in catalog for symbol in group["symbols"]]
    assert {symbol["id"] for symbol in symbols} == expected_symbols
    assert len(symbols) == len({symbol["id"] for symbol in symbols})

    for symbol in symbols:
        assert {
            "id",
            "name",
            "kind",
            "signature",
            "summary",
            "context",
            "fields",
        } <= set(symbol)
        assert all(symbol[key] for key in ("name", "kind", "signature", "summary", "context"))
        assert symbol["fields"]
        assert len(symbol["fields"]) == len(
            {field["name"] for field in symbol["fields"]}
        )
        for field in symbol["fields"]:
            assert set(field) == {
                "name",
                "requirement",
                "value",
                "default",
                "description",
            }
            assert all(field.values())


@pytest.mark.parametrize(
    "body, message",
    [
        ("@template model\n\noutput result: dimensionless = 1\n", "unknown or incomplete directive"),
        ("info:\n  note = text\n", "unknown v2 declaration"),
        ("field derived: dimensionless := 1 + 1\n", "field must use"),
    ],
)
def test_removed_source_forms_are_rejected(tmp_path: Path, body: str, message: str) -> None:
    root = initialize(tmp_path / "removed")
    (root / "entries" / "removed.kirin").write_text(
        """@kirin 2
@entry removed
""" + body,
        encoding="utf-8",
    )
    with pytest.raises(SchemaError, match=message):
        Workspace.load(root)


def test_kirin_entry_preset_groups_display_and_plot_use_existing_engine(tmp_path: Path) -> None:
    root = initialize(tmp_path / "workspace")
    source = ENTRY_SOURCE + """

group results "结果":
  - result
  - doubled

preset baseline "基线":
  model.x = 0.5

display result = percent digits 1

chart preview "Preview":
  x = model.x
  range = 0..1
  points = 3
  y:
    - model.result as "Result"
  using = model.baseline
  x_label = "Input"
  y_label = "Value"
  export_svg = "results/curve.svg"
  export_csv = "results/curve.csv"
"""
    (root / "entries" / "model.kirin").write_text(
        source,
        encoding="utf-8",
    )
    workspace = Workspace.load(root)
    result = Engine(workspace).validate_all()
    assert result["status"] == "ok"
    assert workspace.get_entry("model").raw["description"].endswith("Tabs inside prose are preserved.")
    assert workspace.get_entry("model").name == "model"
    assert evaluate(Engine(workspace), "model.result", "model.baseline")["exact"] == "3"
    assert evaluate(Engine(workspace), "model.doubled", "baseline")["exact"] == "6"
    assert workspace.get_entry("model").groups["results"].outputs == ("result", "doubled")
    assert workspace.get_entry("model").outputs["result"]["display"] == "percent"

    plot = workspace.get_chart("model")
    scan = scan_values(
        Engine(workspace), plot.x, f"{plot.range_start}:{plot.range_end}", plot.points, plot.y
    )
    assert [row["values"]["model.result"]["exact"] for row in scan["rows"]] == ["2", "3", "4"]
    assert plot.curve_labels == {"model.result": "Result"}
    assert plot.preset == "model.baseline"


def test_kirin_entry_supports_multiple_named_static_charts(tmp_path: Path) -> None:
    root = initialize(tmp_path / "multiple-charts")
    source = ENTRY_SOURCE + """

chart result_curve "结果曲线":
  x = model.x
  range = 0..1
  points = 3
  y:
    - model.result
  export_svg = "results/result.svg"

chart doubled_curve "倍增曲线":
  x = model.x
  range = 0..1
  points = 3
  y:
    - model.doubled
  export_svg = "results/doubled.svg"
"""
    path = root / "entries" / "model.kirin"
    path.write_text(source, encoding="utf-8")

    workspace = Workspace.load(root)
    assert Engine(workspace).validate_all()["status"] == "ok"
    assert list(workspace.charts) == ["model.result_curve", "model.doubled_curve"]
    assert workspace.get_chart("result_curve").qualified_id == "model.result_curve"
    assert workspace.get_chart("model.doubled_curve").label == "倍增曲线"
    with pytest.raises(ReferenceError, match="ambiguous"):
        workspace.get_chart("model")

    rendered = render_kirin_document(load_kirin_document(path))
    assert rendered.count("\nchart ") == 2
    assert 'chart result_curve "结果曲线":' in rendered
    assert 'chart doubled_curve "倍增曲线":' in rendered


def test_kirin_static_charts_have_a_bounded_strict_schema(tmp_path: Path) -> None:
    root = initialize(tmp_path / "bounded-charts")
    path = root / "entries" / "model.kirin"
    chart = """

chart {chart_id}:
  x = model.x
  range = 0..1
  points = 3
  y:
    - model.result
"""
    path.write_text(
        ENTRY_SOURCE + "".join(chart.format(chart_id=f"curve_{index}") for index in range(65)),
        encoding="utf-8",
    )
    with pytest.raises(SchemaError, match="exceeds 64 static charts"):
        Workspace.load(root)

    path.write_text(
        ENTRY_SOURCE
        + """

chart repeated:
  x = model.x
  range = 0..1
  points = 3
  y:
    - model.result
  y:
    - model.doubled
""",
        encoding="utf-8",
    )
    with pytest.raises(SchemaError, match="duplicate chart property 'y'"):
        Workspace.load(root)


def test_kirin_reports_source_line_and_rejects_unknown_sections(tmp_path: Path) -> None:
    root = initialize(tmp_path / "workspace")
    path = root / "entries" / "broken.kirin"
    path.write_text(
        """@kirin 2
@entry broken

unknown:
  value
""",
        encoding="utf-8",
    )
    with pytest.raises(SchemaError, match="unknown v2 declaration") as caught:
        Workspace.load(root)
    assert caught.value.location.path == str(path)
    assert caught.value.location.field is None


def test_versioned_lookup_tables_support_exact_lookup_and_interpolation(tmp_path: Path) -> None:
    root = initialize(tmp_path / "lookup")
    (root / "entries" / "lookup.kirin").write_text(
        """@kirin 2
@entry lookup_model
@game-version "test-1"

source source_1:
  kind = "test"
  citation = "lookup fixture"
  game_version = "test-1"

input level: number[dimensionless] = 1 in 1..3

output exact: dimensionless = lookup(rating, level)

output interpolated: dimensionless = interpolate(rating, level)

table rating "等级换算":
  input = dimensionless
  output = dimensionless
  points:
    1 = 10
    3 = 30
""",
        encoding="utf-8",
    )
    workspace = Workspace.load(root)
    assert Engine(workspace).validate_all()["status"] == "ok"
    assert evaluate(Engine(workspace), "lookup_model.exact")["exact"] == "10"
    assert evaluate(
        Engine(workspace),
        "lookup_model.interpolated",
        overrides={"lookup_model.level": "2"},
    )["exact"] == "20"
    with pytest.raises(DomainError, match="domain condition failed"):
        evaluate(
            Engine(workspace),
            "lookup_model.exact",
            overrides={"lookup_model.level": "2"},
        )


def test_source_metadata_rejects_version_drift_and_invalid_digest(tmp_path: Path) -> None:
    root = initialize(tmp_path / "sources")
    path = root / "entries" / "source_model.kirin"
    path.write_text(
        """@kirin 2
@entry source_model
@game-version "patch-a"

source source_1:
  kind = "note"
  citation = "fixture"
  game_version = "patch-b"

output result: dimensionless = 1
""",
        encoding="utf-8",
    )
    with pytest.raises(SchemaError, match="source game_version must match"):
        Workspace.load(root)

    path.write_text(
        """@kirin 2
@entry source_model

source source_1:
  kind = "note"
  citation = "fixture"
  digest = "not-a-digest"

output result: dimensionless = 1
""",
        encoding="utf-8",
    )
    with pytest.raises(SchemaError, match="source digest must use sha256"):
        Workspace.load(root)


def test_workspace_overlay_validates_without_writing(tmp_path: Path) -> None:
    root = initialize(tmp_path / "workspace")
    path = root / "entries" / "draft.kirin"
    workspace = Workspace.load_with_overlay(root, path, ENTRY_SOURCE.replace("@entry model", "@entry draft"))
    assert "draft" in workspace.entries
    assert not path.exists()


def test_fractional_unit_and_parameter_one_of_round_trip(tmp_path: Path) -> None:
    raw = {
        "schema_version": 1,
        "id": "semantics",
        "name": "semantics",
        "type": "entry",
        "semantics": {
            "dimensions": {"length": {}},
            "units": {"root_length": {"dimensions": {"length": "1/2"}}},
        },
        "inputs": {},
        "constraints": [],
        "fields": {},
        "functions": {
            "choose": {
                "parameters": {
                    "n": {
                        "value_type": "number",
                        "unit": "dimensionless",
                        "allowed_values": ["0", "1", "2"],
                    },
                    "enabled": {"value_type": "boolean"},
                },
                "expression": "if_else(enabled, n, 0)",
                "unit": "dimensionless",
                "label": "选择",
            }
        },
        "outputs": {},
    }
    path = tmp_path / "semantics.kirin"
    path.write_text(render_kirin_document(raw), encoding="utf-8")
    loaded = load_kirin_document(path)
    assert loaded.raw == raw


def test_static_input_defaults_accept_percentages_and_unit_quantities(
    tmp_path: Path,
) -> None:
    root = initialize(tmp_path / "input-literals")
    path = root / "entries" / "defaults.kirin"
    path.write_text(
        """@kirin 2
@entry defaults

domain proc_chance: dimensionless in 0..1

input chance: proc_chance = 25%
input delay: time = 1500 millisecond in 1..2

output normalized_chance: dimensionless = chance
output normalized_delay: time = delay
""",
        encoding="utf-8",
    )
    workspace = Workspace.load(root)
    entry = workspace.get_entry("defaults")
    assert entry.inputs["chance"].default == "1/4"
    assert entry.inputs["delay"].default == "3/2"
    assert evaluate(Engine(workspace), "defaults.normalized_chance")["exact"] == "1/4"
    assert evaluate(Engine(workspace), "defaults.normalized_delay")["exact"] == "3/2"


def test_static_input_default_units_must_match_the_declared_dimension(
    tmp_path: Path,
) -> None:
    root = initialize(tmp_path / "bad-input-unit")
    (root / "entries" / "bad.kirin").write_text(
        """@kirin 2
@entry bad

dimension damage
unit damage = damage

input amount: damage = 1 second
output result: damage = amount
""",
        encoding="utf-8",
    )
    with pytest.raises(SchemaError, match="input default unit 'second' is incompatible"):
        Workspace.load(root)


def test_static_expression_continuations_allow_readable_nested_indentation(
    tmp_path: Path,
) -> None:
    root = initialize(tmp_path / "nested-expression")
    (root / "entries" / "nested.kirin").write_text(
        """@kirin 2
@entry nested

output result: dimensionless = max(
  1,
    min(
      2,
      3
    )
)
""",
        encoding="utf-8",
    )
    assert evaluate(Engine(Workspace.load(root)), "nested.result")["exact"] == "2"


def test_static_boolean_and_numeric_domain_result_types_round_trip(
    tmp_path: Path,
) -> None:
    root = initialize(tmp_path / "typed-results")
    path = root / "entries" / "typed.kirin"
    path.write_text(
        """@kirin 2
@entry typed

domain rank: dimensionless in 1..3 integer

input enabled: boolean = true
input level: rank = 2

field disabled: boolean = not enabled
field fixed_rank: rank = 2

function choose(flag: boolean): boolean = if_else(flag, true, false)

output selected: boolean = choose(enabled)
output selected_rank: rank = level

type options:
  visible: boolean = true

options defaults:

output visible: boolean = defaults.visible
""",
        encoding="utf-8",
    )

    workspace = Workspace.load(root)
    engine = Engine(workspace)
    assert engine.validate_all()["status"] == "ok"
    assert engine.resolve_target("typed.disabled").is_boolean
    assert engine.resolve_target("typed.fixed_rank").expr == 2
    assert engine.resolve_target("typed.selected").is_boolean
    assert engine.resolve_target("typed.visible").is_boolean
    assert not engine.resolve_target("typed.selected_rank").is_boolean
    assert evaluate(engine, "typed.selected_rank")["unit"] == "dimensionless"

    rendered = render_kirin_document(load_kirin_document(path))
    assert "field disabled: boolean = not enabled" in rendered
    assert "field fixed_rank: rank = 2" in rendered
    assert "function choose(flag: boolean): boolean" in rendered
    assert "output selected: boolean = choose(enabled)" in rendered
    assert "output selected_rank: rank = level" in rendered
    assert "visible: boolean = true" in rendered
    reparsed = load_kirin_document(path, rendered)
    assert reparsed.raw == load_kirin_document(path).raw


@pytest.mark.parametrize(
    "declaration",
    [
        "field bad: boolean = 1",
        "field bad: dimensionless = true",
        "output bad: boolean = 1",
        "output bad: dimensionless = 1 < 2",
        "function bad(): boolean = 1",
        "function bad(): dimensionless = 1 < 2",
    ],
)
def test_static_result_declarations_reject_wrong_value_types(
    tmp_path: Path, declaration: str
) -> None:
    root = initialize(tmp_path / declaration.split()[0])
    (root / "entries" / "bad.kirin").write_text(
        f"@kirin 2\n@entry bad\n\n{declaration}\n",
        encoding="utf-8",
    )
    with pytest.raises(SchemaError, match="boolean|numeric"):
        Engine(Workspace.load(root)).validate_all()


def test_static_numeric_domain_results_enforce_domain_conditions(
    tmp_path: Path,
) -> None:
    root = initialize(tmp_path / "result-domain")
    (root / "entries" / "bad.kirin").write_text(
        """@kirin 2
@entry bad

domain rank: dimensionless in 1..3 integer

output value: rank = 4
""",
        encoding="utf-8",
    )
    with pytest.raises(DomainError, match="domain condition failed"):
        Engine(Workspace.load(root)).validate_all()


@pytest.mark.parametrize(
    "source, message",
    [
        (
            "@kirin 2\n@entry bad\n\ninput class: dimensionless = 1\n",
            "reserved by the expression language",
        ),
        (
            "@kirin 2\n@entry bad\n\nprocess p:\n  state true: boolean = false\n",
            "reserved by the expression language",
        ),
        (
            "@kirin 2\n@entry bad\n\noutput result: boolean = True\n",
            "lowercase true or false",
        ),
    ],
)
def test_expression_reserved_identifiers_and_noncanonical_booleans_are_rejected(
    tmp_path: Path, source: str, message: str
) -> None:
    root = initialize(tmp_path / "reserved")
    (root / "entries" / "bad.kirin").write_text(source, encoding="utf-8")
    with pytest.raises((SchemaError, ExpressionError), match=message):
        Engine(Workspace.load(root)).validate_all()


def test_leaf_declarations_reject_nested_source(tmp_path: Path) -> None:
    root = initialize(tmp_path / "nested")
    path = root / "entries" / "bad.kirin"
    path.write_text(
        """@kirin 2
@entry bad

input x: dimensionless = 1
  ignored syntax
""",
        encoding="utf-8",
    )
    with pytest.raises(SchemaError, match="input declaration may not contain a block"):
        Workspace.load(root)

    path.write_text(
        """@kirin 2
@entry bad

input x: dimensionless = 1
output result: dimensionless = x
chart preview:
  x = bad.x
    ignored syntax
  range = 0..1
  points = 2
  y:
    - bad.result
""",
        encoding="utf-8",
    )
    with pytest.raises(SchemaError, match="chart property may not contain a block"):
        Workspace.load(root)


def test_function_parameters_and_closed_blocks_reject_duplicates_and_unknowns(
    tmp_path: Path,
) -> None:
    root = initialize(tmp_path / "closed")
    path = root / "entries" / "bad.kirin"
    path.write_text(
        """@kirin 2
@entry bad

function choose(x: dimensionless, x: dimensionless): dimensionless = x
""",
        encoding="utf-8",
    )
    with pytest.raises(SchemaError, match="duplicate function parameter 'x'"):
        Workspace.load(root)

    path.write_text(
        """@kirin 2
@entry bad

table values:
  input = dimensionless
  output = dimensionless
  typo = ignored
  points:
    1 = 1
""",
        encoding="utf-8",
    )
    with pytest.raises(SchemaError, match="unknown table property 'typo'"):
        Workspace.load(root)

    path.write_text(
        """@kirin 2
@entry bad

distribution roll: dimensionless:
  outcomes:
    - 1 @ 1
  outcomes:
    - 2 @ 1
""",
        encoding="utf-8",
    )
    with pytest.raises(SchemaError, match="duplicate distribution property 'outcomes'"):
        Workspace.load(root)


def test_headers_and_source_labels_reject_noncanonical_forms(tmp_path: Path) -> None:
    root = initialize(tmp_path / "headers")
    path = root / "entries" / "bad.kirin"
    path.write_text("  @kirin 2\n@entry bad\n", encoding="utf-8")
    with pytest.raises(SchemaError, match="first declaration"):
        Workspace.load(root)

    path.write_text(
        '@kirin 2\n@entry bad\n\nsource note "discarded":\n  citation = "fixture"\n',
        encoding="utf-8",
    )
    with pytest.raises(SchemaError, match="do not support display labels"):
        Workspace.load(root)


def test_workspace_marker_is_game_neutral_and_rejects_settings(tmp_path: Path) -> None:
    root = initialize(tmp_path / "workspace")
    marker = root / "kirin.workspace"
    marker.write_text("@kirin-workspace 1\n", encoding="utf-8")
    assert Workspace.load(root).documents == {}

    marker.write_text("@kirin-workspace 1\nstarter: none\n", encoding="utf-8")
    with pytest.raises(SchemaError, match="workspace marker does not accept settings"):
        Workspace.load(root)


def test_chinese_local_aliases_and_member_labels(tmp_path: Path) -> None:
    root = initialize(tmp_path / "workspace")
    (root / "entries" / "base.kirin").write_text(
        """@kirin 2
@entry base

input amount "基础值": number[dimensionless] = 2

function double "翻倍"(value: number[dimensionless]): dimensionless = value * 2
""",
        encoding="utf-8",
    )
    (root / "entries" / "model.kirin").write_text(
        """@kirin 2
@entry model

alias 基础 = base.amount

alias 加倍 = base.double

output result "总计": dimensionless = 加倍(基础)
""",
        encoding="utf-8",
    )

    workspace = Workspace.load(root)
    engine = Engine(workspace)
    assert engine.validate_all()["status"] == "ok"
    assert workspace.get_entry("model").aliases == {"基础": "base.amount", "加倍": "base.double"}
    assert workspace.get_entry("base").inputs["amount"].label == "基础值"
    assert evaluate(engine, "model.result")["exact"] == "4"
    assert explain(engine, "model.result")["label"] == "总计"

    scan = scan_values(engine, "base.amount", "1:2", 2, ["model.result"])
    assert scan["x_display_label"] == "基础值"
    assert scan["labels"] == {"model.result": "总计"}


def test_alias_cannot_conflict_with_a_formal_member(tmp_path: Path) -> None:
    root = initialize(tmp_path / "workspace")
    path = root / "entries" / "collision.kirin"
    path.write_text(
        """@kirin 2
@entry collision

alias x = collision.result

input x: number[dimensionless] = 1

output result: dimensionless = x
""",
        encoding="utf-8",
    )
    with pytest.raises(SchemaError, match="conflicts with a declared member"):
        Workspace.load(root)


def test_unused_alias_target_is_still_validated(tmp_path: Path) -> None:
    root = initialize(tmp_path / "workspace")
    (root / "entries" / "model.kirin").write_text(
        """@kirin 2
@entry model

alias 缺失 = missing.value

output result: dimensionless = 1
""",
        encoding="utf-8",
    )
    with pytest.raises(ReferenceError, match="missing reference"):
        Engine(Workspace.load(root)).validate_all()
