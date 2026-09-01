"""Serve a disposable workspace and the freshly built frontend for Playwright."""

from __future__ import annotations

import shutil
from pathlib import Path

import kirin_tor.web as web
from kirin_tor.web import WorkbenchHTTPServer
from kirin_tor.workbench import Workbench
from kirin_tor.plugin_store import PluginManager


PROJECT_ROOT = Path(__file__).resolve().parents[2]
FRONTEND_ROOT = PROJECT_ROOT / "frontend"
WORKSPACE_ROOT = FRONTEND_ROOT / ".e2e-workspace"
SOURCE_WORKSPACE = PROJECT_ROOT / "examples" / "虚构技能工作区"
SOURCE_PLUGIN = PROJECT_ROOT / "examples" / "plugins" / "fictional-talent-tree"


def main() -> None:
    shutil.rmtree(WORKSPACE_ROOT, ignore_errors=True)
    shutil.copytree(SOURCE_WORKSPACE, WORKSPACE_ROOT)
    approval_home = WORKSPACE_ROOT / ".e2e-plugin-user"
    plugin_manager = PluginManager(WORKSPACE_ROOT, approval_home=approval_home)
    plugin_manager.add_path("talents", SOURCE_PLUGIN)
    plugin_manager.set_enabled("talents", False)
    web.ASSET_ROOT = FRONTEND_ROOT / "dist"
    server = WorkbenchHTTPServer(
        ("127.0.0.1", 8766),
        Workbench(WORKSPACE_ROOT, plugin_approval_home=approval_home),
        "kirin-e2e-token",
    )
    try:
        server.serve_forever()
    finally:
        server.server_close()
        shutil.rmtree(WORKSPACE_ROOT, ignore_errors=True)


if __name__ == "__main__":
    main()
