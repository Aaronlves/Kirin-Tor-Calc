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
    combo_path = WORKSPACE_ROOT / "entries" / "组合模型.kirin"
    combo_path.write_text(
        combo_path.read_text(encoding="utf-8")
        + """

chart compact "短区间组合曲线":
  x = combo.crit
  range = 0..0.3
  points = 7
  y:
    - combo.total

chart broad "宽区间组合曲线":
  x = combo.crit
  range = 0..1
  points = 11
  y:
    - combo.total
""",
        encoding="utf-8",
    )
    rotation_path = WORKSPACE_ROOT / "entries" / "循环分析.kirin"
    rotation_path.write_text(
        rotation_path.read_text(encoding="utf-8").rstrip()
        + """
  chart mana_trace "法力轨迹":
    kind = trajectory
    series:
      - actor.current_mana
  chart mana_trace_detail "法力轨迹副本":
    kind = trajectory
    series:
      - actor.current_mana
""",
        encoding="utf-8",
    )
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
