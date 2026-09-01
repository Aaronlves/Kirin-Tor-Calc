from __future__ import annotations

import json
import threading
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

import pytest

from kirin_tor.web import create_web_server


class RunningServer:
    def __init__(self, root: Path):
        self.server = create_web_server(root)
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
        with urllib.request.urlopen(running.base + "/", timeout=5) as response:
            html = response.read().decode("utf-8")
        assert "Kirin Tor 图形工作台" in html
        policy = response.headers["Content-Security-Policy"]
        assert "frame-ancestors 'none'" in policy
        assert "script-src 'self'" in policy
        assert "style-src 'self' 'unsafe-inline'" in policy

        status, _headers, body = running.request("/api/bootstrap")
        result = decoded(body)
        assert status == 200
        assert result["workspace"] == str(example_workspace.resolve())
        assert any(item["path"] == "entries/组合模型.kirin" for item in result["documents"])
        assert any(item["value"] == "builtin:model" for item in result["templates"])

        with pytest.raises(urllib.error.HTTPError) as failure:
            running.request("/api/bootstrap", token="wrong")
        assert failure.value.code == 403


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
        assert path.read_text(encoding="utf-8").endswith("// external edit\n")
