"""Bundled, game-neutral Kirin Tor tutorials presented as read-only source."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Tuple


TUTORIAL_SOURCE_ROOT = Path(__file__).resolve().parent / "tutorial_sources"


@dataclass(frozen=True)
class TutorialInfo:
    tutorial_id: str
    title: str
    description: str
    document_id: str
    duration: str
    learning_points: Tuple[str, ...]
    filename: str

    @property
    def source_path(self) -> Path:
        return TUTORIAL_SOURCE_ROOT / self.filename

    @property
    def template_value(self) -> str:
        return f"tutorial:{self.tutorial_id}"

    def as_dict(self) -> dict:
        return {
            "id": self.tutorial_id,
            "title": self.title,
            "description": self.description,
            "document_id": self.document_id,
            "duration": self.duration,
            "learning_points": list(self.learning_points),
            "template": self.template_value,
            "source": self.source_path.read_text(encoding="utf-8"),
        }


_TUTORIALS: Tuple[TutorialInfo, ...] = (
    TutorialInfo(
        "basic-model",
        "基础公式",
        "从输入、字段和输出开始，观察源码默认值如何自动形成只读预览。",
        "tutorial_basic",
        "约 3 分钟",
        (
            "修改单价、数量或折扣的默认值",
            "观察字段如何复用输入组成公式",
            "增加一个 output 并让诊断即时校验",
        ),
        "basic_model.kirin",
    ),
    TutorialInfo(
        "preset-comparison",
        "参数方案与比较",
        "用命名参数方案保存可复用假设，并保持正式输入标识稳定。",
        "tutorial_variants",
        "约 4 分钟",
        (
            "区分默认输入与命名参数方案",
            "修改方案中的限定输入名称和值",
            "用输出分组组织多个可比较结果",
        ),
        "preset_comparison.kirin",
    ),
    TutorialInfo(
        "scan-chart",
        "扫描与图表",
        "声明扫描轴、范围和曲线，让编辑器旁边自动出现图表预览。",
        "tutorial_curve",
        "约 5 分钟",
        (
            "修改 range 与 points 控制扫描范围",
            "为多条 y 曲线设置清晰标签",
            "从只读图表预览显式导出 SVG 或 CSV",
        ),
        "scan_chart.kirin",
    ),
)


def list_tutorials() -> Tuple[TutorialInfo, ...]:
    """Return the stable bundled tutorial catalog."""
    return _TUTORIALS
