from __future__ import annotations

import json
from pathlib import Path

import pytest

from kirin_tor.community_discovery import (
    PACKAGE_DISCOVERY_TOPIC,
    PLUGIN_DISCOVERY_TOPIC,
    discover_community,
)
from kirin_tor.package_manifest import current_feature_line
from kirin_tor.errors import ParameterError
from kirin_tor.workbench import Workbench
from kirin_tor.workspace import initialize


def _plugin_manifest() -> bytes:
    return json.dumps(
        {
            "schema": 2,
            "id": "community.example-browser",
            "name": "Example Browser",
            "version": "1.0.0",
            "api": "2",
            "description": "A discovered fixture plugin.",
            "license": "MIT",
            "requires": {"kirin_feature": current_feature_line(), "interfaces": []},
            "contributes": {
                "views": [
                    {
                        "id": "community.example-browser.main",
                        "title": "Example",
                        "entry": "web/index.html",
                        "permissions": ["workspace.summary"],
                    }
                ]
            },
        }
    ).encode("utf-8")


def _package_manifest() -> bytes:
    return f'''schema = 2
name = "community.example"
version = "1.2.3"
namespace = "community_example"
description = "A discovered fixture package."
license = "MIT"
requires_kirin = "{current_feature_line()}"
game = "fictional-game"
'''.encode("utf-8")


class FakeDiscoveryClient:
    def __init__(self, manifests: dict[str, bytes]):
        self.manifests = manifests
        self.searches = []
        self.reads = []

    def search_repositories(self, *, topic: str, query: str, page: int, per_page: int):
        self.searches.append((topic, query, page, per_page))
        return {
            "total_count": 2,
            "items": [
                {
                    "full_name": "Community/Valid",
                    "default_branch": "main",
                    "description": "Repository description",
                    "updated_at": "2026-09-01T00:00:00Z",
                    "stargazers_count": 7,
                    "forks_count": 2,
                    "archived": False,
                },
                {
                    "full_name": "Community/Invalid",
                    "default_branch": "main",
                    "description": None,
                    "updated_at": "2026-08-01T00:00:00Z",
                    "stargazers_count": 1,
                    "forks_count": 0,
                    "archived": False,
                },
            ],
        }

    def read_repository_file(
        self, repository: str, path: str, ref: str, *, max_bytes: int
    ):
        self.reads.append((repository, path, ref, max_bytes))
        return self.manifests[repository], "a" * 40


def test_plugin_topic_discovery_returns_only_compatible_manifests() -> None:
    client = FakeDiscoveryClient(
        {
            "Community/Valid": _plugin_manifest(),
            "Community/Invalid": b"{}",
        }
    )

    result = discover_community(
        "plugin", query="browser", page=1, client=client
    )

    assert client.searches[0][:3] == (PLUGIN_DISCOVERY_TOPIC, "browser", 1)
    assert result["topic"] == "kirin-tor-plugin"
    assert result["skipped_repositories"] == 1
    assert result["items"] == [
        {
            "kind": "plugin",
            "topic": "kirin-tor-plugin",
            "repository": "Community/Valid",
            "source": "github:community/valid",
            "repository_url": "https://github.com/Community/Valid",
            "repository_description": "Repository description",
            "default_branch": "main",
            "manifest_sha": "a" * 40,
            "updated_at": "2026-09-01T00:00:00Z",
            "stars": 7,
            "forks": 2,
            "id": "community.example-browser",
            "name": "Example Browser",
            "version": "1.0.0",
            "api": "2",
            "description": "A discovered fixture plugin.",
            "license": "MIT",
            "requires": {"kirin_feature": current_feature_line(), "interfaces": []},
        }
    ]
    assert all(path == "kirin.plugin.json" for _, path, _, _ in client.reads)


def test_package_topic_discovery_uses_the_package_protocol() -> None:
    client = FakeDiscoveryClient(
        {
            "Community/Valid": _package_manifest(),
            "Community/Invalid": b"schema = 99\n",
        }
    )

    result = discover_community("package", page=2, client=client)

    assert client.searches[0][:3] == (PACKAGE_DISCOVERY_TOPIC, "", 2)
    assert result["topic"] == "kirin-tor-package"
    assert result["has_previous"] is True
    assert result["items"][0]["name"] == "community.example"
    assert result["items"][0]["namespace"] == "community_example"
    assert result["items"][0]["game"] == "fictional-game"
    assert result["skipped_repositories"] == 1
    assert all(path == "kirin.package.toml" for _, path, _, _ in client.reads)


def test_plugin_discovery_skips_an_incompatible_kirin_feature() -> None:
    raw = json.loads(_plugin_manifest())
    raw["requires"]["kirin_feature"] = "99.0"
    client = FakeDiscoveryClient(
        {
            "Community/Valid": json.dumps(raw).encode("utf-8"),
            "Community/Invalid": b"{}",
        }
    )

    result = discover_community("plugin", client=client)

    assert result["items"] == []
    assert result["skipped_repositories"] == 2


def test_workbench_discovery_actions_are_read_only_and_kind_specific(
    tmp_path: Path, monkeypatch,
) -> None:
    root = initialize(tmp_path / "workspace")
    before = sorted(path.relative_to(root).as_posix() for path in root.rglob("*"))
    calls = []

    def fake_discover(kind: str, *, query: object = "", page: object = 1):
        calls.append((kind, query, page))
        return {"status": "ok", "kind": kind, "items": []}

    monkeypatch.setattr("kirin_tor.workbench.discover_community", fake_discover)
    workbench = Workbench(root)

    assert workbench.plugin_action("discover", {"query": "ui", "page": 3})["kind"] == "plugin"
    assert workbench.package_action("discover", {"query": "wow", "page": 2})["kind"] == "package"
    assert calls == [("plugin", "ui", 3), ("package", "wow", 2)]
    assert sorted(path.relative_to(root).as_posix() for path in root.rglob("*")) == before


def test_discovery_query_cannot_replace_the_fixed_topic() -> None:
    client = FakeDiscoveryClient({})
    with pytest.raises(ParameterError, match="query may contain only"):
        discover_community("plugin", query="topic:other", client=client)
    assert client.searches == []
