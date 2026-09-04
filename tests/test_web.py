from __future__ import annotations

import json
import shutil
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

import pytest

from kirin_tor.package_authoring import add_path_package, create_package_template
from kirin_tor.web import create_web_server
from kirin_tor.plugin_store import PluginManager
from kirin_tor.workspace import initialize


PROJECT_ROOT = Path(__file__).resolve().parents[1]
EXAMPLE_PLUGIN = PROJECT_ROOT / "examples" / "plugins" / "fictional-talent-tree"
EXAMPLE_PACKAGE = PROJECT_ROOT / "examples" / "packages" / "fictional-models"


class RunningServer:
    def __init__(
        self,
        root: Path,
        *,
        safe_mode: bool = False,
        plugin_approval_home: Path | None = None,
        preference_home: Path | None = None,
    ):
        self.server = create_web_server(
            root,
            safe_mode=safe_mode,
            plugin_approval_home=plugin_approval_home,
            preference_home=preference_home,
        )
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    def __enter__(self):
        self.thread.start()
        host, port = self.server.server_address[:2]
        self.base = f"http://{host}:{port}"
        return self

    def __exit__(self, *_args):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=3)

    def request(self, path: str, payload: dict | None = None, *, token: str | None = None):
        data = None if payload is None else json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(
            self.base + path,
            data=data,
            headers={
                "Host": urllib.parse.urlparse(self.base).netloc,
                "X-Kirin-Token": self.server.token if token is None else token,
                **({"Content-Type": "application/json"} if data is not None else {}),
            },
        )
        with urllib.request.urlopen(request, timeout=5) as response:
            return response.status, response.headers, response.read()


def decoded(data: bytes) -> dict:
    return json.loads(data.decode("utf-8"))


def test_web_bootstrap_serves_assets_and_requires_session_token(example_workspace: Path) -> None:
    with RunningServer(example_workspace) as running:
        assert running.server.request_queue_size >= 32
        with urllib.request.urlopen(running.base + "/", timeout=5) as response:
            html = response.read().decode("utf-8")
        assert "Kirin Tor 图形工作台" in html
        policy = response.headers["Content-Security-Policy"]
        assert "frame-ancestors 'none'" in policy
        assert "script-src 'self'" in policy
        assert "style-src 'self' 'unsafe-inline'" in policy
        assert response.headers.get("Access-Control-Allow-Origin") is None

        status, _headers, body = running.request("/api/bootstrap")
        result = decoded(body)
        assert status == 200
        assert result["workspace"] == str(example_workspace.resolve())
        assert any(item["path"] == "entries/组合模型.kirin" for item in result["documents"])
        assert any(item["value"] == "builtin:model" for item in result["templates"])
        assert "tutorials" not in result
        assert result["authoring_contract"]["version"] == 1
        assert "**" in result["authoring_contract"]["tokens"]["operators"]
        assert "^" not in result["authoring_contract"]["tokens"]["operators"]
        protocol = result["plugins"]["protocol"]
        assert protocol["api"] == "2"
        assert protocol["actions"]["compare"] == {
            "permission": "operation.compare",
            "handler": "operation",
            "operation": "compare",
        }
        assert protocol["actions"]["grid"]["operation"] == "grid"
        assert protocol["actions"]["model.query"]["handler"] == "catalog"
        assert protocol["limits"]["max_comparison_variants"] == 8
        revision = result["catalog"]["revision"]
        catalog_page = decoded(
            running.request(
                "/api/model",
                {
                    "action": "model.query",
                    "payload": {
                        "revision": revision,
                        "kind": ["output"],
                        "limit": 1,
                    },
                    "overlays": {},
                },
            )[2]
        )
        assert catalog_page["operation"] == "model.query"
        assert catalog_page["items"][0]["kind"] == "output"

        completion = decoded(running.request(
            "/api/completions",
            {
                "key": "entries/组合模型.kirin",
                "prefix": "平方根",
                "line": 20,
                "column": 40,
                "explicit": True,
                "overlays": {},
            },
        )[2])
        assert completion["status"] == "ok"
        with pytest.raises(urllib.error.HTTPError) as invalid_completion:
            running.request(
                "/api/completions",
                {"key": "entries/组合模型.kirin", "prefix": "x", "line": 0, "column": 1},
            )
        assert invalid_completion.value.code == 400

        status, _headers, body = running.request("/api/workspace/state")
        workspace_state = decoded(body)
        assert status == 200
        assert len(workspace_state["revision"]) == 64
        assert any(item["path"] == "entries/组合模型.kirin" for item in workspace_state["documents"])

        with pytest.raises(urllib.error.HTTPError) as failure:
            running.request("/api/bootstrap", token="wrong")
        assert failure.value.code == 403


def test_web_bootstrap_degrades_when_the_package_graph_is_unavailable(
    example_workspace: Path,
    tmp_path: Path,
) -> None:
    package = create_package_template(
        tmp_path / "package",
        name="community.unavailable",
        namespace="community_unavailable",
    )
    resolution = add_path_package(example_workspace, "unavailable", package)
    shutil.rmtree(resolution.packages[0].root)

    with RunningServer(example_workspace) as running:
        status, _headers, body = running.request("/api/bootstrap")
        bootstrap = decoded(body)

        assert status == 200
        assert bootstrap["status"] == "ok"
        assert bootstrap["packages"] == []
        assert bootstrap["package_state"]["status"] == "error"
        assert bootstrap["package_state"]["error"]["code"] == "package_error"
        assert bootstrap["package_state"]["requirements"] == [
            {
                "alias": "unavailable",
                "source": f"path:{package.resolve()}",
                "version": "1.0.0",
            }
        ]
        assert bootstrap["validation"]["code"] == "package_error"
        assert any(item["path"] == "entries/组合模型.kirin" for item in bootstrap["documents"])
        assert any(item["value"] == "builtin:model" for item in bootstrap["templates"])

        status, _headers, body = running.request(
            "/api/document?key=" + urllib.parse.quote("entries/组合模型.kirin")
        )
        assert status == 200
        assert decoded(body)["path"] == "entries/组合模型.kirin"

        status, _headers, body = running.request(
            "/api/document/create",
            {"template": "builtin:model", "document_id": "degraded_draft"},
        )
        assert status == 200
        assert decoded(body)["path"] == "entries/degraded_draft.kirin"
        assert not (example_workspace / "entries" / "degraded_draft.kirin").exists()

        status, _headers, body = running.request(
            "/api/package",
            {"action": "remove", "payload": {"alias": "unavailable"}},
        )
        assert status == 200
        assert decoded(body)["packages"] == []
        assert decoded(running.request("/api/bootstrap")[2])["package_state"]["status"] == "ok"


def test_web_switches_workspaces_atomically_and_preserves_session_boundaries(
    example_workspace: Path,
    tmp_path: Path,
    monkeypatch,
) -> None:
    target = initialize(tmp_path / "另一个工作区")
    target_source = target / "entries" / "target.kirin"
    target_source.write_text(
        '@kirin 2\n@entry target "另一个工作区"\n\noutput value: dimensionless = 2\n',
        encoding="utf-8",
    )
    preference_home = tmp_path / "workbench-user"
    plugin_approval_home = tmp_path / "plugin-user"

    with RunningServer(
        example_workspace,
        safe_mode=True,
        plugin_approval_home=plugin_approval_home,
        preference_home=preference_home,
    ) as running:
        status, _headers, body = running.request(
            "/api/workspace/open",
            {"path": str(target_source)},
        )
        switched = decoded(body)

        assert status == 200
        assert switched == {
            "status": "ok",
            "workspace": str(target.resolve()),
            "previous_workspace": str(example_workspace.resolve()),
            "changed": True,
        }
        assert running.server.operation_jobs.root == target.resolve()
        bootstrap = decoded(running.request("/api/bootstrap")[2])
        assert bootstrap["workspace"] == str(target.resolve())
        assert bootstrap["plugins"]["safe_mode"] is True
        assert [item["path"] for item in bootstrap["documents"]] == ["entries/target.kirin"]
        assert json.loads(
            (preference_home / "workbench-preferences.json").read_text(encoding="utf-8")
        ) == {
            "schema": 1,
            "default_workspace": str(target.resolve()),
        }

        unchanged = decoded(
            running.request("/api/workspace/open", {"path": str(target)})[2]
        )
        assert unchanged["changed"] is False

        ordinary = tmp_path / "ordinary-directory"
        ordinary.mkdir()
        with pytest.raises(urllib.error.HTTPError) as invalid:
            running.request("/api/workspace/open", {"path": str(ordinary)})
        assert invalid.value.code == 400
        assert decoded(running.request("/api/bootstrap")[2])["workspace"] == str(target.resolve())

        monkeypatch.setattr(running.server.operation_jobs, "has_running_jobs", lambda: True)
        with pytest.raises(urllib.error.HTTPError) as busy:
            running.request(
                "/api/workspace/open",
                {"path": str(example_workspace)},
            )
        assert busy.value.code == 400
        assert decoded(running.request("/api/bootstrap")[2])["workspace"] == str(target.resolve())


def test_web_serves_only_active_sandboxed_plugin_assets_and_projections(
    example_workspace: Path,
) -> None:
    approval_home = example_workspace.parent / "plugin-approval"
    add_path_package(example_workspace, "fictional_models", EXAMPLE_PACKAGE)
    installed = PluginManager(example_workspace, approval_home=approval_home).add_path(
        "talents", EXAMPLE_PLUGIN
    )
    digest = installed["plugins"][0]["content_sha256"]
    with RunningServer(example_workspace, plugin_approval_home=approval_home) as running:
        bootstrap = decoded(running.request("/api/bootstrap")[2])
        assert bootstrap["plugins"]["plugins"][0]["status"] == "active"
        assert bootstrap["plugins"]["contributions"]["renderers"][0]["entry_url"].startswith(
            f"/plugins/{digest}/"
        )

        status, _headers, body = running.request(
            "/api/document/projection",
            {"key": "entries/组合模型.kirin", "overlays": {}},
        )
        projection = decoded(body)
        assert status == 200
        assert projection["document"]["id"] == "combo"
        assert projection["document"]["content"]["outputs"]["total"]["expression"]
        assert {item["id"] for item in projection["members"]} >= {"combo.crit", "combo.total"}
        assert {item["path"] for item in projection["members"]} == {"entries/组合模型.kirin"}
        assert all("source" not in item and "resolved" not in item for item in projection["workspace"]["packages"])

        with urllib.request.urlopen(
            running.base + f"/plugins/{digest}/web/index.html", timeout=5
        ) as response:
            assert response.status == 200
            policy = response.headers["Content-Security-Policy"]
            assert "connect-src 'none'" in policy
            assert "form-action 'none'" in policy
            assert response.headers["Access-Control-Allow-Origin"] == "null"
            assert response.headers.get("X-Frame-Options") is None
            assert b"Fictional Talent Workbench" in response.read()
        with urllib.request.urlopen(
            running.base + f"/plugins/{digest}/web/plugin.js", timeout=5
        ) as response:
            assert response.headers["Content-Type"].startswith("text/javascript")
            assert response.headers["Access-Control-Allow-Origin"] == "null"

    with RunningServer(
        example_workspace,
        safe_mode=True,
        plugin_approval_home=approval_home,
    ) as safe:
        bootstrap = decoded(safe.request("/api/bootstrap")[2])
        assert bootstrap["plugins"]["safe_mode"] is True
        assert bootstrap["plugins"]["contributions"]["renderers"] == []
        with pytest.raises(urllib.error.HTTPError) as unavailable:
            urllib.request.urlopen(
                safe.base + f"/plugins/{digest}/web/index.html", timeout=5
            )
        assert unavailable.value.code == 404


def test_web_validates_saves_and_calculates_from_shared_services(example_workspace: Path) -> None:
    relative = "entries/组合模型.kirin"
    source_path = example_workspace / relative
    original = source_path.read_text(encoding="utf-8")
    modified = original.replace("crit \"暴击率\": probability = 0.25", "crit \"暴击率\": probability = 0.30")
    with RunningServer(example_workspace) as running:
        status, _headers, body = running.request(
            "/api/validate", {"overlays": {relative: modified}}
        )
        validation = decoded(body)
        assert status == 200
        assert validation["status"] == "ok"

        status, _headers, body = running.request(
            "/api/operation",
            {
                "operation": "eval",
                "payload": {"target": "combo.total", "preset": "presets.baseline"},
                "overlays": {relative: modified},
            },
        )
        result = decoded(body)
        assert status == 200
        assert result["exact"] == "2750"

        digest = decoded(running.request(f"/api/document?key={urllib.parse.quote(relative)}")[2])["source_sha256"]
        status, _headers, body = running.request(
            "/api/save",
            {"overlays": {relative: modified}, "expected": {relative: digest}},
        )
        saved = decoded(body)
        assert status == 200
        assert saved["saved"][0]["path"] == relative
        assert source_path.read_text(encoding="utf-8") == modified


def test_web_operation_jobs_report_stages_and_results(example_workspace: Path) -> None:
    with RunningServer(example_workspace) as running:
        status, _headers, body = running.request(
            "/api/operation/job",
            {"action": "start", "operation": "version", "payload": {}, "overlays": {}},
        )
        job = decoded(body)
        assert status == 200
        assert job["state"] in {"running", "completed"}
        assert job["stage"] in {"executing", "completed"}
        deadline = time.monotonic() + 5
        while job["state"] == "running" and time.monotonic() < deadline:
            time.sleep(0.05)
            job = decoded(running.request(
                "/api/operation/job",
                {"action": "status", "job_id": job["job_id"]},
            )[2])
        assert job["state"] == "completed"
        assert job["cancellable"] is False
        assert job["result"]["status"] == "ok"

        slow = decoded(running.request(
            "/api/operation/job",
            {
                "action": "start",
                "operation": "scan",
                "payload": {
                    "x": "combo.crit",
                    "range": "0:1",
                    "points": 10_000,
                    "targets": ["combo.total"],
                    "timeout": 300,
                },
                "overlays": {},
            },
        )[2])
        cancelled = decoded(running.request(
            "/api/operation/job",
            {"action": "cancel", "job_id": slow["job_id"]},
        )[2])
        assert cancelled["state"] == "cancelled"
        assert cancelled["error"]["code"] == "operation_cancelled"


def test_web_creates_static_template_drafts_without_writing(example_workspace: Path) -> None:
    with RunningServer(example_workspace) as running:
        _status, _headers, body = running.request(
            "/api/document/create",
            {"template": "builtin:model", "document_id": "web_model"},
        )
        result = decoded(body)
        assert result["path"] == "entries/web_model.kirin"
        assert "@entry web_model" in result["text"]
        assert not (example_workspace / result["path"]).exists()


def test_web_manages_workspace_templates_and_returns_author_diagnostics(
    example_workspace: Path,
) -> None:
    with RunningServer(example_workspace) as running:
        status, _headers, body = running.request(
            "/api/template",
            {
                "action": "save",
                "payload": {"document_id": "combo", "template_id": "saved_combo"},
            },
        )
        assert status == 200
        saved = decoded(body)
        assert saved["path"] == "templates/entries/saved_combo.kirin"

        templates = decoded(running.request("/api/bootstrap")[2])["templates"]
        selected = next(item for item in templates if item["id"] == "saved_combo")
        assert selected["origin"] == "workspace"

        status, _headers, body = running.request(
            "/api/template",
            {"action": "remove", "payload": {"template": selected["value"]}},
        )
        assert status == 200
        assert not (example_workspace / "templates" / "entries" / "saved_combo.kirin").exists()

        broken = example_workspace / "templates" / "entries" / "broken.kirin"
        broken.write_text("// missing header\n", encoding="utf-8")
        templates = decoded(running.request("/api/bootstrap")[2])["templates"]
        invalid_template = next(item for item in templates if item["id"] == "broken")
        assert "@entry" in invalid_template["error"]
        with pytest.raises(urllib.error.HTTPError) as invalid_creation:
            running.request(
                "/api/document/create",
                {"template": invalid_template["value"], "document_id": "will_not_exist"},
            )
        assert invalid_creation.value.code == 400

        relative = "entries/组合模型.kirin"
        source = (example_workspace / relative).read_text(encoding="utf-8")
        invalid = source + "\nunknown：\n"
        status, _headers, body = running.request(
            "/api/validate", {"overlays": {relative: invalid}}
        )
        diagnostic = decoded(body)
        assert status == 200
        assert diagnostic["status"] == "error"
        assert "全角符号" in diagnostic["errors"][0]["author_message"]


def test_web_refuses_to_overwrite_an_external_document_change(
    example_workspace: Path,
) -> None:
    relative = "entries/组合模型.kirin"
    path = example_workspace / relative
    with RunningServer(example_workspace) as running:
        opened = decoded(
            running.request(f"/api/document?key={urllib.parse.quote(relative)}")[2]
        )
        draft = opened["text"] + "\n// workbench draft\n"
        path.write_text(opened["text"] + "\n// external edit\n", encoding="utf-8")
        with pytest.raises(urllib.error.HTTPError) as failure:
            running.request(
                "/api/save",
                {
                    "overlays": {relative: draft},
                    "expected": {relative: opened["source_sha256"]},
                },
            )
        assert failure.value.code == 400
        payload = decoded(failure.value.read())
        assert payload["code"] == "workspace_error"
        assert "changed outside" in payload["message"]
        assert payload["location"]["path"] == relative
        assert path.read_text(encoding="utf-8").endswith("// external edit\n")


def test_web_exposes_authoring_actions_and_recovery_cache(example_workspace: Path) -> None:
    relative = "entries/组合模型.kirin"
    original = (example_workspace / relative).read_text(encoding="utf-8")
    with RunningServer(example_workspace) as running:
        bootstrap = decoded(running.request("/api/bootstrap")[2])
        assert any(item["id"] == "combo.total" for item in bootstrap["authoring"]["symbols"])
        status, _headers, body = running.request(
            "/api/authoring",
            {
                "action": "rename",
                "payload": {"symbol": "combo.total", "new_name": "combined_total"},
                "overlays": {},
            },
        )
        renamed = decoded(body)
        assert status == 200
        assert renamed["renamed_to"] == "combo.combined_total"
        assert (example_workspace / relative).read_text(encoding="utf-8") == original

        status, _headers, _body = running.request(
            "/api/recovery",
            {
                "drafts": {
                    relative: {
                        "text": original + "\n// recovery\n",
                        "base_sha256": bootstrap["documents"][0]["source_sha256"],
                        "document": next(item for item in bootstrap["documents"] if item["path"] == relative),
                    }
                }
            },
        )
        assert status == 200
        recovered = decoded(running.request("/api/bootstrap")[2])["recovery"]["drafts"]
        assert recovered[relative]["text"].endswith("// recovery\n")
