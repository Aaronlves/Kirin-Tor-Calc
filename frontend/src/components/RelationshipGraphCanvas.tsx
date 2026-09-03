import { useEffect, useMemo, useRef } from "react";
import { GraphChart } from "echarts/charts";
import { LegendComponent, TooltipComponent } from "echarts/components";
import * as echarts from "echarts/core";
import { CanvasRenderer } from "echarts/renderers";
import type { EChartsOption } from "echarts";

import { initKirinEChart, KIRIN_ECHARTS_TOOLTIP_CLASS, kirinEChartsTokens, kirinGraphCategoryColors } from "../charts/kirinEChartsTheme";
import type { RelationshipEdge, RelationshipNode } from "../types";

echarts.use([GraphChart, LegendComponent, TooltipComponent, CanvasRenderer]);

const categoryOrder = ["document", "input", "field", "function", "table", "distribution", "object", "output", "process", "scenario", "analysis"];
const categoryLabels: Record<string, string> = {
  document: "文档",
  input: "输入",
  field: "字段",
  function: "函数",
  table: "查表",
  distribution: "有限分布",
  object: "类型化对象",
  output: "输出",
  process: "过程",
  scenario: "场景",
  analysis: "分析",
};
const emptyRootIds: string[] = [];

interface RelationshipGraphCanvasProps {
  nodes: RelationshipNode[];
  edges: RelationshipEdge[];
  compact?: boolean;
  layout?: "circular" | "force";
  rootIds?: string[];
  selectedId?: string | null;
  onSelect?(id: string): void;
}

function escapeHtml(value: string): string {
  return value.replace(/[&<>"]/g, (character) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
  })[character] || character);
}

export function RelationshipGraphCanvas({
  nodes,
  edges,
  compact = false,
  layout = "force",
  rootIds = emptyRootIds,
  selectedId = null,
  onSelect,
}: RelationshipGraphCanvasProps) {
  const hostRef = useRef<HTMLDivElement>(null);
  const sortedNodes = useMemo(
    () => [...nodes].sort((left, right) => left.kind.localeCompare(right.kind) || left.id.localeCompare(right.id)),
    [nodes],
  );
  const nodeMap = useMemo(() => new Map(sortedNodes.map((node) => [node.id, node])), [sortedNodes]);
  const rootIdSet = useMemo(() => new Set(rootIds), [rootIds]);
  const connectionCounts = useMemo(() => {
    const counts = new Map<string, { dependencies: number; users: number }>();
    for (const node of sortedNodes) counts.set(node.id, { dependencies: 0, users: 0 });
    for (const edge of edges) {
      const source = counts.get(edge.source);
      const target = counts.get(edge.target);
      if (source) source.users += 1;
      if (target) target.dependencies += 1;
    }
    return counts;
  }, [edges, sortedNodes]);

  useEffect(() => {
    if (!hostRef.current) return;
    const chart = initKirinEChart(hostRef.current);
    const degree = new Map<string, number>();
    const labelCounts = new Map<string, number>();
    for (const node of sortedNodes) labelCounts.set(node.label, (labelCounts.get(node.label) || 0) + 1);
    for (const edge of edges) {
      degree.set(edge.source, (degree.get(edge.source) || 0) + 1);
      degree.set(edge.target, (degree.get(edge.target) || 0) + 1);
    }
    const categories = categoryOrder
      .filter((kind) => sortedNodes.some((node) => node.kind === kind))
      .map((kind) => ({ name: categoryLabels[kind] || kind, itemStyle: { color: kirinGraphCategoryColors[kind] || kirinEChartsTokens.graphFallback } }));
    const categoryIndex = new Map(categories.map((category, index) => [category.name, index]));
    const option: EChartsOption = {
      animation: false,
      tooltip: {
        className: KIRIN_ECHARTS_TOOLTIP_CLASS,
        formatter: (params: unknown) => {
          const item = params as { dataType?: string; data?: { id?: string } };
          if (item.dataType !== "node" || !item.data?.id) return "公式依赖";
          const node = nodeMap.get(item.data.id);
          if (!node) return "";
          const scope = rootIdSet.has(node.id) ? " · 当前文档" : "";
          return `<strong>${escapeHtml(node.label)}</strong><br/><span style="color:${kirinEChartsTokens.tooltipMuted}">${escapeHtml(node.id)} · ${escapeHtml(categoryLabels[node.kind] || node.kind)}${scope}</span>`;
        },
      },
      legend: compact ? undefined : [{
        top: 10,
        left: 12,
        data: categories.map((category) => category.name),
        textStyle: { color: kirinEChartsTokens.legendText, fontSize: kirinEChartsTokens.fontSizeMeta },
        itemWidth: 10,
        itemHeight: 10,
      }],
      series: [{
        type: "graph",
        selectedMode: "single",
        layout,
        roam: true,
        draggable: layout === "force",
        data: sortedNodes.map((node) => ({
          id: node.id,
          name: (labelCounts.get(node.label) || 0) > 1 ? `${node.document_id}.${node.label}` : node.label,
          selected: node.id === selectedId,
          category: categoryIndex.get(categoryLabels[node.kind] || node.kind) ?? 0,
          symbolSize: Math.min(compact ? 25 : 38, (compact ? 13 : 17) + Math.sqrt(degree.get(node.id) || 1) * 3 + (rootIdSet.has(node.id) ? 2 : 0)),
          itemStyle: {
            color: kirinGraphCategoryColors[node.kind] || kirinEChartsTokens.graphFallback,
            borderColor: rootIdSet.has(node.id) ? kirinEChartsTokens.graphRootBorder : kirinEChartsTokens.graphNodeBorder,
            borderWidth: rootIdSet.has(node.id) ? 2 : 1,
          },
          label: {
            show: sortedNodes.length <= (compact ? 18 : 45),
            color: kirinEChartsTokens.legendText,
            fontSize: compact ? kirinEChartsTokens.fontSizeMeta : kirinEChartsTokens.fontSizeBody,
            position: "right",
          },
        })),
        links: edges.map((edge) => ({
          source: edge.source,
          target: edge.target,
          value: edge.count || 1,
        })),
        categories,
        ...(layout === "force" ? {
          force: {
            repulsion: compact ? 210 : 410,
            edgeLength: compact ? [68, 112] : [110, 190],
            gravity: compact ? 0.065 : 0.035,
            friction: 0.58,
          },
        } : { circular: { rotateLabel: false } }),
        edgeSymbol: ["none", "arrow"],
        edgeSymbolSize: [0, compact ? 5 : 7],
        lineStyle: { color: "source", opacity: 0.48, width: 1.25, curveness: 0.08 },
        emphasis: { focus: "adjacency", lineStyle: { opacity: 1, width: 2 } },
        select: { itemStyle: { borderColor: kirinEChartsTokens.graphSelectedBorder, borderWidth: 2 } },
      }],
    };
    chart.setOption(option, true);
    chart.on("click", (params: unknown) => {
      const item = params as { dataType?: string; data?: { id?: string } };
      if (item.dataType === "node" && item.data?.id) onSelect?.(item.data.id);
    });
    const observer = new ResizeObserver(() => chart.resize());
    observer.observe(hostRef.current);
    return () => {
      observer.disconnect();
      chart.dispose();
    };
  }, [compact, edges, layout, nodeMap, onSelect, rootIdSet, selectedId, sortedNodes]);

  return (
    <div className={`relationship-visualization${compact ? " is-compact" : ""}`}>
      <div ref={hostRef} className="relationship-canvas" role="img" aria-label="公式与文档关系图；下方提供键盘节点列表" />
      <details className="canvas-data-fallback">
        <summary>使用键盘浏览 {sortedNodes.length} 个节点</summary>
        <div className="relationship-node-list" role="list" aria-label="关系图节点">
          {sortedNodes.map((node) => {
            const count = connectionCounts.get(node.id);
            return (
              <div key={node.id} role="listitem">
                <button
                  type="button"
                  aria-pressed={selectedId === node.id}
                  onClick={() => onSelect?.(node.id)}
                >
                  <strong>{node.label}</strong>
                  <small>{node.id} · {categoryLabels[node.kind] || node.kind} · {count?.dependencies || 0} 个依赖 · {count?.users || 0} 个使用者{rootIdSet.has(node.id) ? " · 当前文档" : ""}</small>
                </button>
              </div>
            );
          })}
        </div>
      </details>
    </div>
  );
}
