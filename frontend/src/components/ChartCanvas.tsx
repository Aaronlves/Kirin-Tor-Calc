import { useEffect, useRef } from "react";
import * as echarts from "echarts/core";
import { HeatmapChart, LineChart } from "echarts/charts";
import {
  DataZoomComponent,
  GridComponent,
  LegendComponent,
  TitleComponent,
  TooltipComponent,
  VisualMapComponent,
} from "echarts/components";
import { CanvasRenderer } from "echarts/renderers";
import type { EChartsOption } from "echarts";

import { initKirinEChart, KIRIN_ECHARTS_TOOLTIP_CLASS, kirinEChartsTokens } from "../charts/kirinEChartsTheme";
import type { OperationResult } from "../types";

echarts.use([
  LineChart,
  HeatmapChart,
  GridComponent,
  TooltipComponent,
  LegendComponent,
  TitleComponent,
  DataZoomComponent,
  VisualMapComponent,
  CanvasRenderer,
]);

function numeric(value: unknown): number | null {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

function valueFromCell(cell: unknown): number | null {
  if (!cell || typeof cell !== "object") return numeric(cell);
  const record = cell as Record<string, unknown>;
  return numeric(record.approximate ?? record.exact);
}

function displayedCell(cell: unknown): string {
  if (cell && typeof cell === "object") {
    const record = cell as Record<string, unknown>;
    for (const key of ["formatted", "exact", "approximate"]) {
      if (record[key] !== null && record[key] !== undefined) return String(record[key]);
    }
  }
  return cell === null || cell === undefined ? "无效" : String(cell);
}

function escapeHtml(value: unknown): string {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function withUnit(value: unknown, unit: unknown): string {
  const suffix = unit && unit !== "dimensionless" ? ` ${String(unit)}` : "";
  return `${displayedCell(value)}${suffix}`;
}

function lineTooltip(result: OperationResult, params: unknown): string {
  const items = (Array.isArray(params) ? params : [params]) as Array<{
    seriesId?: string;
    seriesName?: string;
    data?: { rowIndex?: number };
  }>;
  const sourceRows = Array.isArray(result.rows) ? result.rows as Array<Record<string, unknown>> : [];
  const rowIndex = items.find((item) => Number.isInteger(item.data?.rowIndex))?.data?.rowIndex;
  const row = rowIndex === undefined ? null : sourceRows[rowIndex];
  if (!row) return "";
  const values = row.values && typeof row.values === "object" ? row.values as Record<string, unknown> : {};
  const units = result.units && typeof result.units === "object" ? result.units as Record<string, unknown> : {};
  const xLabel = String(result.x_display_label || result.x || "横轴");
  const lines = items.map((item) => {
    const target = String(item.seriesId || "");
    return `${escapeHtml(item.seriesName || target)}：${escapeHtml(withUnit(values[target], units[target]))}`;
  });
  return `<strong>${escapeHtml(xLabel)} = ${escapeHtml(withUnit(row.x, result.x_unit))}</strong><br/>${lines.join("<br/>")}`;
}

function heatmapTooltip(result: OperationResult, row: Record<string, unknown>): string {
  return [
    `${escapeHtml(String(result.x || "横轴"))} = ${escapeHtml(withUnit(row.x, result.x_unit))}`,
    `${escapeHtml(String(result.y || "纵轴"))} = ${escapeHtml(withUnit(row.y, result.y_unit))}`,
    `<strong>${escapeHtml(String(result.target_label || result.target || "结果"))} = ${escapeHtml(withUnit(row.value, result.unit))}</strong>`,
  ].join("<br/>");
}

function accessibleRows(result: OperationResult): string[] {
  const rows = Array.isArray(result.rows) ? result.rows as Array<Record<string, unknown>> : [];
  if (result.operation === "grid") {
    return rows.map((row) => (
      `${String(result.x || "横轴")} ${displayedCell(row.x)}；${String(result.y || "纵轴")} ${displayedCell(row.y)}；结果 ${displayedCell(row.value)}`
    ));
  }
  const targets = Array.isArray(result.targets) ? result.targets.map(String) : [];
  const labels = result.labels && typeof result.labels === "object" ? result.labels as Record<string, string> : {};
  return rows.map((row) => {
    const values = row.values && typeof row.values === "object" ? row.values as Record<string, unknown> : {};
    const rendered = targets.map((target) => `${labels[target] || target} ${displayedCell(values[target])}`);
    return `${String(result.x_display_label || result.x || "横轴")} ${displayedCell(row.x ?? row.x_approximate)}；${rendered.join("；")}`;
  });
}

function chartTargets(result: OperationResult): Array<{ id: string; label: string }> {
  const labels = result.labels && typeof result.labels === "object" ? result.labels as Record<string, string> : {};
  const targets = result.operation === "grid"
    ? [result.target].filter((target): target is string => typeof target === "string" && Boolean(target))
    : Array.isArray(result.targets) ? result.targets.map(String) : [];
  return [...new Set(targets)].map((id) => ({ id, label: labels[id] || String(result.target_label || id) }));
}

function lineOption(result: OperationResult, interactive: boolean): EChartsOption {
  const rows = Array.isArray(result.rows) ? result.rows as Array<Record<string, unknown>> : [];
  const targets = Array.isArray(result.targets) ? result.targets.map(String) : [];
  const labels = result.labels && typeof result.labels === "object" ? result.labels as Record<string, string> : {};
  const xValues = rows.map((row) => numeric(row.x_approximate ?? row.x) ?? String(row.x ?? ""));
  const isNumericAxis = xValues.every((value) => typeof value === "number");
  return {
    animation: false,
    grid: { left: 52, right: 18, top: 56, bottom: 72, containLabel: false },
    legend: {
      top: 10,
      left: 10,
      itemWidth: 16,
      itemHeight: 2,
      textStyle: { fontSize: 11 },
      data: targets.map((target) => labels[target] || target),
    },
    tooltip: {
      trigger: "axis",
      className: KIRIN_ECHARTS_TOOLTIP_CLASS,
      axisPointer: { type: "line", label: { show: true } },
      formatter: (params: unknown) => lineTooltip(result, params),
    },
    dataZoom: [
      { type: "inside", filterMode: "none" },
      {
        type: "slider",
        height: 18,
        bottom: 18,
        borderColor: kirinEChartsTokens.dataZoomBorder,
        backgroundColor: kirinEChartsTokens.dataZoomBackground,
        fillerColor: kirinEChartsTokens.dataZoomFiller,
        handleStyle: { color: kirinEChartsTokens.accent, borderColor: kirinEChartsTokens.accent },
        textStyle: { color: kirinEChartsTokens.axisText, fontSize: 11 },
      },
    ],
    xAxis: {
      type: isNumericAxis ? "value" : "category",
      name: `${String(result.x_display_label || result.x || "横轴")}${result.x_unit ? ` [${String(result.x_unit)}]` : ""}`,
      nameLocation: "middle",
      nameGap: 46,
      boundaryGap: false,
      data: isNumericAxis ? undefined : xValues,
      axisLabel: { hideOverlap: true },
    } as EChartsOption["xAxis"],
    yAxis: {
      type: "value",
      axisLine: { show: false },
    },
    series: targets.map((target, targetIndex) => ({
      id: target,
      name: labels[target] || target,
      type: "line",
      cursor: interactive ? "pointer" : "default",
      showSymbol: rows.length <= 24,
      symbolSize: interactive ? 10 : 5,
      smooth: false,
      connectNulls: false,
      lineStyle: { width: 2 },
      emphasis: { focus: "series" },
      data: rows.map((row, rowIndex) => {
        const values = row.values && typeof row.values === "object" ? row.values as Record<string, unknown> : {};
        const y = valueFromCell(values[target]);
        return {
          value: isNumericAxis ? [xValues[rowIndex], y] : y,
          rowIndex,
          target,
        };
      }),
      z: targets.length - targetIndex,
    })),
  };
}

function heatmapOption(result: OperationResult, interactive: boolean): EChartsOption {
  const rows = Array.isArray(result.rows) ? result.rows as Array<Record<string, unknown>> : [];
  const xValues = [...new Set(rows.map((row) => String(row.x ?? "")))];
  const yValues = [...new Set(rows.map((row) => String(row.y ?? "")))];
  const values = rows.map((row) => [
    xValues.indexOf(String(row.x ?? "")),
    yValues.indexOf(String(row.y ?? "")),
    valueFromCell(row.value),
  ]);
  const data = values.map((value, rowIndex) => ({ value, rowIndex, target: String(result.target || "result") }));
  const numbers = values.map((item) => item[2]).filter((value): value is number => typeof value === "number");
  const min = numbers.length ? Math.min(...numbers) : 0;
  const max = numbers.length ? Math.max(...numbers) : 1;
  return {
    animation: false,
    grid: { left: 84, right: 88, top: 38, bottom: 66 },
    tooltip: {
      position: "top",
      className: KIRIN_ECHARTS_TOOLTIP_CLASS,
      formatter: (params: unknown) => {
        const item = params as { data?: { rowIndex?: number } };
        const row = Number.isInteger(item.data?.rowIndex) ? rows[item.data?.rowIndex ?? -1] : null;
        return row ? heatmapTooltip(result, row) : "";
      },
    },
    xAxis: {
      type: "category",
      data: xValues,
      name: String(result.x || "横轴"),
      nameLocation: "middle",
      nameGap: 40,
      splitArea: { show: true, areaStyle: { color: [...kirinEChartsTokens.heatmapAreas] } },
      axisLabel: { color: kirinEChartsTokens.axisTextMuted, hideOverlap: true },
    },
    yAxis: {
      type: "category",
      data: yValues,
      name: String(result.y || "纵轴"),
      splitArea: { show: true, areaStyle: { color: [...kirinEChartsTokens.heatmapAreas] } },
      axisLabel: { color: kirinEChartsTokens.axisTextMuted, hideOverlap: true },
    },
    visualMap: {
      min,
      max,
      calculable: true,
      orient: "vertical",
      right: 12,
      top: "center",
      inRange: { color: [...kirinEChartsTokens.heatmapScale] },
    },
    series: [{
      id: String(result.target || "result"),
      name: String(result.target_label || result.target || "结果"),
      type: "heatmap",
      cursor: interactive ? "pointer" : "default",
      data,
      label: { show: data.length <= 100, color: kirinEChartsTokens.tooltipText, fontSize: 11 },
      emphasis: { itemStyle: { borderColor: kirinEChartsTokens.emphasis, borderWidth: 1 } },
    }],
  };
}

export function ChartCanvas({ result, onSelectTarget }: { result: OperationResult; onSelectTarget?: (target: string) => void }) {
  const hostRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<ReturnType<typeof initKirinEChart> | null>(null);
  const rows = accessibleRows(result);
  const targets = chartTargets(result);
  const label = result.operation === "grid" ? "计算热力图" : "计算曲线";
  const interactive = Boolean(onSelectTarget);

  useEffect(() => {
    if (!hostRef.current) return;
    const chart = initKirinEChart(hostRef.current);
    chartRef.current = chart;
    chart.setOption(result.operation === "grid" ? heatmapOption(result, interactive) : lineOption(result, interactive), true);
    const observer = new ResizeObserver(() => chart.resize());
    observer.observe(hostRef.current);
    return () => {
      observer.disconnect();
      chartRef.current = null;
      chart.dispose();
    };
  }, [interactive, result]);

  const activateTargetAtPoint = (point: [number, number]) => {
    const chart = chartRef.current;
    if (!chart || !hostRef.current) return;
    const width = hostRef.current.clientWidth;
    const height = hostRef.current.clientHeight;
    const gridBounds = result.operation === "grid"
      ? { left: 84, right: 88, top: 38, bottom: 66 }
      : { left: 52, right: 18, top: 56, bottom: 72 };
    if (
      point[0] < gridBounds.left
      || point[0] > width - gridBounds.right
      || point[1] < gridBounds.top
      || point[1] > height - gridBounds.bottom
    ) return;
    if (result.operation === "grid") {
      if (targets[0]) onSelectTarget?.(targets[0].id);
      return;
    }
    if (targets.length === 1) {
      onSelectTarget?.(targets[0].id);
      return;
    }
    const sourceRows = Array.isArray(result.rows) ? result.rows as Array<Record<string, unknown>> : [];
    let nearest: { target: string; distance: number } | null = null;
    for (const target of targets) {
      for (const row of sourceRows) {
        const values = row.values && typeof row.values === "object" ? row.values as Record<string, unknown> : {};
        const y = valueFromCell(values[target.id]);
        const x = numeric(row.x_approximate ?? row.x) ?? String(row.x ?? "");
        if (y === null) continue;
        const candidate = chart.convertToPixel({ xAxisIndex: 0, yAxisIndex: 0 }, [x, y]);
        if (!Array.isArray(candidate) || candidate.length < 2) continue;
        const distance = Math.hypot(Number(candidate[0]) - point[0], Number(candidate[1]) - point[1]);
        if (!Number.isFinite(distance) || (nearest && nearest.distance <= distance)) continue;
        nearest = { target: target.id, distance };
      }
    }
    if (nearest && nearest.distance <= 18) onSelectTarget?.(nearest.target);
  };

  return (
    <div className="chart-visualization">
      <div className="chart-canvas" ref={hostRef} role="img" aria-label={`${label}；下方提供键盘数据列表`} onClickCapture={(event) => {
        const rect = event.currentTarget.getBoundingClientRect();
        activateTargetAtPoint([event.clientX - rect.left, event.clientY - rect.top]);
      }} />
      <details className="canvas-data-fallback">
        <summary>使用键盘查看 {rows.length} 个图表数据点</summary>
        {onSelectTarget && targets.length > 0 && <div className="chart-source-targets" role="group" aria-label="图表系列源码">
          {targets.map((target) => <button type="button" key={target.id} onClick={() => onSelectTarget(target.id)}>定位 {target.label} 源码</button>)}
        </div>}
        <ol className="chart-data-list" aria-label={`${label}数据`}>
          {rows.map((row, index) => <li key={`${index}-${row}`} tabIndex={0}>{row}</li>)}
        </ol>
      </details>
    </div>
  );
}
