import { useEffect, useMemo, useRef } from "react";
import { GraphChart } from "echarts/charts";
import { LegendComponent, TooltipComponent } from "echarts/components";
import * as echarts from "echarts/core";
import { CanvasRenderer } from "echarts/renderers";
import type { EChartsOption } from "echarts";

import type { RelationshipEdge, RelationshipNode } from "../types";

echarts.use([GraphChart, LegendComponent, TooltipComponent, CanvasRenderer]);

const categoryOrder = ["document", "input", "field", "function", "table", "output"];
const categoryLabels: Record<string, string> = {
  document: "文档",
  input: "输入",
  field: "字段",
  function: "函数",
  table: "查表",
  output: "输出",
};
const categoryColors: Record<string, string> = {
  document: "#d97757",
  input: "#6fa7a0",
  field: "#a88bbb",
  function: "#c19a5b",
  table: "#85a56f",
  output: "#7599b2",
};

interface RelationshipGraphCanvasProps {
  nodes: RelationshipNode[];
  edges: RelationshipEdge[];
  compact?: boolean;
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
  onSelect,
}: RelationshipGraphCanvasProps) {
  const hostRef = useRef<HTMLDivElement>(null);
  const nodeMap = useMemo(() => new Map(nodes.map((node) => [node.id, node])), [nodes]);

  useEffect(() => {
    if (!hostRef.current) return;
    const chart = echarts.init(hostRef.current, undefined, { renderer: "canvas" });
    const degree = new Map<string, number>();
    const labelCounts = new Map<string, number>();
    for (const node of nodes) labelCounts.set(node.label, (labelCounts.get(node.label) || 0) + 1);
    for (const edge of edges) {
      degree.set(edge.source, (degree.get(edge.source) || 0) + 1);
      degree.set(edge.target, (degree.get(edge.target) || 0) + 1);
    }
    const categories = categoryOrder
      .filter((kind) => nodes.some((node) => node.kind === kind))
      .map((kind) => ({ name: categoryLabels[kind] || kind, itemStyle: { color: categoryColors[kind] || "#8d887d" } }));
    const categoryIndex = new Map(categories.map((category, index) => [category.name, index]));
    const option: EChartsOption = {
      animation: false,
      backgroundColor: "transparent",
      tooltip: {
        backgroundColor: "#1d1c18",
        borderColor: "#3a3832",
        borderWidth: 1,
        textStyle: { color: "#eeeae1", fontSize: 11 },
        formatter: (params: unknown) => {
          const item = params as { dataType?: string; data?: { id?: string } };
          if (item.dataType !== "node" || !item.data?.id) return "公式依赖";
          const node = nodeMap.get(item.data.id);
          if (!node) return "";
          return `<strong>${escapeHtml(node.label)}</strong><br/><span style="color:#99958b">${escapeHtml(node.id)} · ${escapeHtml(categoryLabels[node.kind] || node.kind)}</span>`;
        },
      },
      legend: compact ? undefined : [{
        top: 10,
        left: 12,
        data: categories.map((category) => category.name),
        textStyle: { color: "#8d887d", fontSize: 10 },
        itemWidth: 10,
        itemHeight: 10,
      }],
      series: [{
        type: "graph",
        selectedMode: "single",
        layout: "force",
        roam: true,
        draggable: true,
        data: nodes.map((node) => ({
          id: node.id,
          name: (labelCounts.get(node.label) || 0) > 1 ? `${node.document_id}.${node.label}` : node.label,
          category: categoryIndex.get(categoryLabels[node.kind] || node.kind) ?? 0,
          symbolSize: Math.min(compact ? 21 : 32, (compact ? 11 : 15) + Math.sqrt(degree.get(node.id) || 1) * 3),
          itemStyle: {
            color: categoryColors[node.kind] || "#8d887d",
            borderColor: "#171612",
            borderWidth: 1,
          },
          label: {
            show: nodes.length <= (compact ? 18 : 45),
            color: "#b9b5aa",
            fontSize: compact ? 9 : 10,
            position: "right",
          },
        })),
        links: edges.map((edge) => ({
          source: edge.source,
          target: edge.target,
          value: edge.count || 1,
        })),
        categories,
        force: {
          repulsion: compact ? 175 : 340,
          edgeLength: compact ? [55, 95] : [95, 175],
          gravity: compact ? 0.08 : 0.045,
          friction: 0.62,
        },
        edgeSymbol: ["none", "arrow"],
        edgeSymbolSize: [0, compact ? 4 : 6],
        lineStyle: { color: "source", opacity: 0.32, width: 1, curveness: 0.08 },
        emphasis: { focus: "adjacency", lineStyle: { opacity: 0.8, width: 1.5 } },
        select: { itemStyle: { borderColor: "#fff4e8", borderWidth: 2 } },
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
  }, [compact, edges, nodeMap, nodes, onSelect]);

  return <div ref={hostRef} className={`relationship-canvas${compact ? " is-compact" : ""}`} role="img" aria-label="公式与文档关系图" />;
}
