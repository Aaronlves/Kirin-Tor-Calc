"""Read-only discovery of self-declared Kirin community repositories."""

from __future__ import annotations

import base64
import binascii
import json
import os
import re
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping, Optional, Protocol, Tuple

from .errors import DiscoveryError, PackageError, ParameterError, PluginError
from .limits import (
    MAX_DISCOVERY_JSON_BYTES,
    MAX_DISCOVERY_QUERY_LENGTH,
    MAX_DISCOVERY_RESULTS_PER_PAGE,
    MAX_PACKAGE_MANIFEST_BYTES,
    MAX_PLUGIN_MANIFEST_BYTES,
    PACKAGE_NETWORK_TIMEOUT_SECONDS,
)
from .package_manifest import (
    PACKAGE_MANIFEST,
    current_feature_line,
    load_package_manifest,
    source_kind,
)
from .plugin_manifest import PLUGIN_MANIFEST, load_plugin_manifest


PLUGIN_DISCOVERY_TOPIC = "kirin-tor-plugin"
PACKAGE_DISCOVERY_TOPIC = "kirin-tor-package"
DISCOVERY_TOPICS = {
    "plugin": PLUGIN_DISCOVERY_TOPIC,
    "package": PACKAGE_DISCOVERY_TOPIC,
}
DISCOVERY_MANIFESTS = {
    "plugin": PLUGIN_MANIFEST,
    "package": PACKAGE_MANIFEST,
}

_GITHUB_REPOSITORY_RE = re.compile(
    r"^(?P<owner>[A-Za-z0-9](?:[A-Za-z0-9-]{0,38}))/(?P<repo>[A-Za-z0-9_.-]+)$"
)
_SHA_RE = re.compile(r"^[0-9a-fA-F]{40}$")


class DiscoveryClient(Protocol):
    def search_repositories(
        self, *, topic: str, query: str, page: int, per_page: int
    ) -> Mapping[str, object]: ...

    def read_repository_file(
        self, repository: str, path: str, ref: str, *, max_bytes: int
    ) -> Tuple[bytes, str]: ...


class _ManifestMissing(Exception):
    pass


class _ManifestInvalid(Exception):
    pass


class GitHubDiscoveryClient:
    """Bounded public-GitHub client used only after an explicit discovery action."""

    api_host = "api.github.com"

    def __init__(
        self,
        token: Optional[str] = None,
        timeout: float = PACKAGE_NETWORK_TIMEOUT_SECONDS,
    ):
        self.token = token if token is not None else os.environ.get("GITHUB_TOKEN")
        self.timeout = timeout

    def _headers(self) -> dict:
        headers = {
            "Accept": "application/vnd.github+json",
            "User-Agent": "kirin-tor-community-discovery",
        }
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        return headers

    def _json_get(
        self,
        url: str,
        *,
        max_bytes: int,
        candidate_manifest: bool = False,
    ) -> Mapping[str, object]:
        request = urllib.request.Request(url, headers=self._headers())
        try:
            response = urllib.request.urlopen(request, timeout=self.timeout)
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                raise _ManifestMissing() from exc
            detail = "；可设置 GITHUB_TOKEN 后重试" if exc.code in {403, 429} else ""
            raise DiscoveryError(f"GitHub 发现请求失败（HTTP {exc.code}）{detail}") from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise DiscoveryError(f"GitHub 发现请求失败：{exc}") from exc
        with response:
            final = urllib.parse.urlparse(response.geturl())
            if final.scheme != "https" or (final.hostname or "").lower() != self.api_host:
                raise DiscoveryError("GitHub 发现请求被重定向到非允许主机")
            content_length = response.headers.get("Content-Length")
            try:
                declared = int(content_length) if content_length else 0
            except ValueError as exc:
                error = _ManifestInvalid if candidate_manifest else DiscoveryError
                raise error("GitHub 发现响应的 Content-Length 无效") from exc
            if declared > max_bytes:
                error = _ManifestInvalid if candidate_manifest else DiscoveryError
                raise error("GitHub 发现响应超过大小限制")
            payload = response.read(max_bytes + 1)
            if len(payload) > max_bytes:
                error = _ManifestInvalid if candidate_manifest else DiscoveryError
                raise error("GitHub 发现响应超过大小限制")
        try:
            value = json.loads(payload.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            error = _ManifestInvalid if candidate_manifest else DiscoveryError
            raise error("GitHub 发现响应不是有效 JSON") from exc
        if not isinstance(value, dict):
            error = _ManifestInvalid if candidate_manifest else DiscoveryError
            raise error("GitHub 发现响应必须是对象")
        return value

    def search_repositories(
        self, *, topic: str, query: str, page: int, per_page: int
    ) -> Mapping[str, object]:
        terms = [f"topic:{topic}", "archived:false"]
        if query:
            terms.extend(query.split())
        parameters = urllib.parse.urlencode(
            {
                "q": " ".join(terms),
                "sort": "updated",
                "order": "desc",
                "page": page,
                "per_page": per_page,
            }
        )
        return self._json_get(
            f"https://{self.api_host}/search/repositories?{parameters}",
            max_bytes=MAX_DISCOVERY_JSON_BYTES,
        )

    def read_repository_file(
        self, repository: str, path: str, ref: str, *, max_bytes: int
    ) -> Tuple[bytes, str]:
        match = _GITHUB_REPOSITORY_RE.fullmatch(repository)
        if match is None:
            raise DiscoveryError("GitHub 发现结果包含无效仓库身份")
        owner = urllib.parse.quote(match.group("owner"), safe="")
        repo = urllib.parse.quote(match.group("repo"), safe="")
        encoded_path = "/".join(urllib.parse.quote(part, safe="") for part in path.split("/"))
        parameters = urllib.parse.urlencode({"ref": ref})
        value = self._json_get(
            f"https://{self.api_host}/repos/{owner}/{repo}/contents/{encoded_path}?{parameters}",
            max_bytes=max(MAX_DISCOVERY_JSON_BYTES // 2, max_bytes * 2),
            candidate_manifest=True,
        )
        if value.get("type") != "file" or value.get("encoding") != "base64":
            raise _ManifestInvalid("GitHub manifest 响应不是普通 Base64 文件")
        encoded = value.get("content")
        sha = value.get("sha")
        if not isinstance(encoded, str) or not isinstance(sha, str) or not _SHA_RE.fullmatch(sha):
            raise _ManifestInvalid("GitHub manifest 响应缺少内容或 blob SHA")
        try:
            compact = "".join(encoded.split()).encode("ascii")
            content = base64.b64decode(compact, validate=True)
        except (UnicodeEncodeError, binascii.Error) as exc:
            raise _ManifestInvalid("GitHub manifest 响应包含无效 Base64") from exc
        if len(content) > max_bytes:
            raise _ManifestInvalid("GitHub manifest 超过大小限制")
        return content, sha.lower()


@dataclass(frozen=True)
class RepositoryCandidate:
    full_name: str
    default_branch: str
    description: str
    updated_at: str
    stars: int
    forks: int

    @property
    def source(self) -> str:
        return "github:" + self.full_name.lower()

    @property
    def url(self) -> str:
        return "https://github.com/" + self.full_name


def _query(value: object) -> str:
    query = str(value or "").strip()
    if len(query) > MAX_DISCOVERY_QUERY_LENGTH:
        raise ParameterError(
            f"discovery query exceeds {MAX_DISCOVERY_QUERY_LENGTH} characters"
        )
    if any(not (character.isalnum() or character in " -_.") for character in query):
        raise ParameterError(
            "discovery query may contain only letters, numbers, spaces, hyphens, underscores, and dots"
        )
    return query


def _positive_page(value: object) -> int:
    try:
        page = int(value)
    except (TypeError, ValueError) as exc:
        raise ParameterError("discovery page must be a positive integer") from exc
    if page < 1 or page > 50:
        raise ParameterError("discovery page must be from 1 to 50")
    return page


def _repository(raw: object) -> Optional[RepositoryCandidate]:
    if not isinstance(raw, dict):
        return None
    full_name = raw.get("full_name")
    default_branch = raw.get("default_branch")
    archived = raw.get("archived")
    if (
        not isinstance(full_name, str)
        or _GITHUB_REPOSITORY_RE.fullmatch(full_name) is None
        or not isinstance(default_branch, str)
        or not default_branch
        or len(default_branch) > 255
        or archived is True
    ):
        return None
    description = raw.get("description")
    updated_at = raw.get("updated_at")
    stars = raw.get("stargazers_count")
    forks = raw.get("forks_count")
    return RepositoryCandidate(
        full_name=full_name,
        default_branch=default_branch,
        description=description if isinstance(description, str) else "",
        updated_at=updated_at if isinstance(updated_at, str) else "",
        stars=stars if isinstance(stars, int) and not isinstance(stars, bool) and stars >= 0 else 0,
        forks=forks if isinstance(forks, int) and not isinstance(forks, bool) and forks >= 0 else 0,
    )


def _inspect_plugin(content: bytes) -> dict:
    with tempfile.TemporaryDirectory(prefix="kirin-plugin-discovery-") as directory:
        root = Path(directory)
        (root / PLUGIN_MANIFEST).write_bytes(content)
        manifest = load_plugin_manifest(root, check_entries=False)
    return {
        "id": manifest.id,
        "name": manifest.name,
        "version": manifest.version,
        "api": manifest.api,
        "description": manifest.description,
        "license": manifest.license,
    }


def _inspect_package(content: bytes) -> dict:
    with tempfile.TemporaryDirectory(prefix="kirin-package-discovery-") as directory:
        root = Path(directory)
        (root / PACKAGE_MANIFEST).write_bytes(content)
        manifest = load_package_manifest(root, check_compatibility=True)
    if any(source_kind(dependency.source) != "github" for dependency in manifest.dependencies):
        raise PackageError("published topic package may depend only on GitHub sources")
    result = {
        "name": manifest.name,
        "version": manifest.version,
        "namespace": manifest.namespace,
        "requires_kirin": manifest.requires_kirin,
        "description": manifest.description,
        "license": manifest.license,
    }
    if manifest.game is not None:
        result["game"] = manifest.game
    if manifest.game_version is not None:
        result["game_version"] = manifest.game_version
    return result


def discover_community(
    kind: str,
    *,
    query: object = "",
    page: object = 1,
    client: Optional[DiscoveryClient] = None,
) -> dict:
    """Return current-protocol topic candidates without installing or persisting anything."""

    if kind not in DISCOVERY_TOPICS:
        raise ParameterError(f"unknown community discovery kind: {kind}")
    normalized_query = _query(query)
    normalized_page = _positive_page(page)
    topic = DISCOVERY_TOPICS[kind]
    manifest_name = DISCOVERY_MANIFESTS[kind]
    per_page = MAX_DISCOVERY_RESULTS_PER_PAGE
    github = client or GitHubDiscoveryClient()
    payload = github.search_repositories(
        topic=topic,
        query=normalized_query,
        page=normalized_page,
        per_page=per_page,
    )
    raw_items = payload.get("items")
    total_count = payload.get("total_count")
    if not isinstance(raw_items, list) or not isinstance(total_count, int) or total_count < 0:
        raise DiscoveryError("GitHub repository search response is incomplete")

    items = []
    skipped = 0
    manifest_limit = MAX_PLUGIN_MANIFEST_BYTES if kind == "plugin" else MAX_PACKAGE_MANIFEST_BYTES
    for raw in raw_items:
        repository = _repository(raw)
        if repository is None:
            skipped += 1
            continue
        try:
            content, manifest_sha = github.read_repository_file(
                repository.full_name,
                manifest_name,
                repository.default_branch,
                max_bytes=manifest_limit,
            )
            manifest = _inspect_plugin(content) if kind == "plugin" else _inspect_package(content)
        except (_ManifestMissing, _ManifestInvalid, PackageError, PluginError):
            skipped += 1
            continue
        items.append(
            {
                "kind": kind,
                "topic": topic,
                "repository": repository.full_name,
                "source": repository.source,
                "repository_url": repository.url,
                "repository_description": repository.description,
                "default_branch": repository.default_branch,
                "manifest_sha": manifest_sha,
                "updated_at": repository.updated_at,
                "stars": repository.stars,
                "forks": repository.forks,
                **manifest,
            }
        )

    capped_total = min(total_count, 1000)
    return {
        "status": "ok",
        "kind": kind,
        "topic": topic,
        "query": normalized_query,
        "page": normalized_page,
        "per_page": per_page,
        "total_repositories": total_count,
        "inspected_repositories": len(raw_items),
        "skipped_repositories": skipped,
        "has_previous": normalized_page > 1,
        "has_next": normalized_page * per_page < capped_total,
        "checked_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "items": items,
        "notice": "Topic 与兼容 manifest 仅用于发现；结果未经审核，也不会安装、批准或启用内容。",
    }
