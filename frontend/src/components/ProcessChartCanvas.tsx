import { useEffect, useMemo, useRef } from "react";
import { BarChart, LineChart, ScatterChart } from "echarts/charts";
import {
  DataZoomComponent,
  GridComponent,
  LegendComponent,
  TooltipComponent,
  VisualMapComponent,
} from "echarts/components";
import * as echarts from "echarts/core";
import { CanvasRenderer } from "echarts/renderers";
import type { EChartsOption } from "echarts";

import { initKirinEChart, KIRIN_ECHARTS_TOOLTIP_CLASS, kirinEChartsTokens } from "../charts/kirinEChartsTheme";

echarts.use([
  LineChart,
  ScatterChart,
  BarChart,
  GridComponent,
  TooltipComponent,
  LegendComponent,
  DataZoomComponent,
  VisualMapComponent,
  CanvasRenderer,
]);

type Row = Record<string, unknown>;
type ProcessChart = Record<string, unknown>;

function rows(chart: ProcessChart): Row[] {
  return Array.isArray(chart.rows) ? chart.rows as Row[] : [];
}

function approximate(value: unknown): number | null {
  if (value && typeof value === "object" && !Array.isArray(value)) {
    return approximate((value as Row).approximate ?? (value as Row).exact);
  }
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

function displayed(value: unknown): string {
  if (value && typeof value === "object" && !Array.isArray(value)) {
    const record = value as Row;
    return String(record.formatted ?? record.exact ?? record.approximate ?? "—");
  }
  return value === null || value === undefined ? "—" : String(value);
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
  return `${displayed(value)}${suffix}`;
}

type ProcessTooltipItem = {
  seriesName?: string;
  data?: { row?: Row; sourceName?: string };
};

function processTooltip(chart: ProcessChart, params: unknown): string {
  const items = (Array.isArray(params) ? params : [params]) as ProcessTooltipItem[];
  const firstRow = items.find((item) => item.data?.row)?.data?.row;
  if (!firstRow) return "";
  const kind = String(chart.kind ?? "");
  const units = chart.units && typeof chart.units === "object" ? chart.units as Row : {};
  if (kind === "trajectory") {
    const lines = items.map((item) => {
      const row = item.data?.row ?? {};
      const values = row.values && typeof row.values === "object" ? row.values as Row : {};
      const sourceName = String(item.data?.sourceName ?? "");
      return `${escapeHtml(item.seriesName || sourceName)}：${escapeHtml(withUnit(values[sourceName], units[sourceName]))}`;
    });
    const phase = firstRow.phase ? ` · ${escapeHtml(firstRow.phase)}` : "";
    return `<strong>time = ${escapeHtml(firstRow.time)}</strong>${phase}<br/>${lines.join("<br/>")}`;
  }
  if (kind === "decision_surface") {
    return [
      `${escapeHtml(firstRow.variant)} · decision time 1 = ${escapeHtml(firstRow.x)}`,
      `decision time 2 = ${escapeHtml(firstRow.y)}`,
      `<strong>${escapeHtml(String(chart.value_measure ?? "value"))} = ${escapeHtml(withUnit(firstRow.value, chart.unit))}</strong>`,
    ].join("<br/>");
  }
  if (kind === "pareto") {
    const frontier = firstRow.nondominated ? " · Pareto 前沿" : "";
    return [
      `<strong>${escapeHtml(firstRow.variant)}${frontier}</strong>`,
      `${escapeHtml(String(chart.x_measure ?? "x"))} = ${escapeHtml(withUnit(firstRow.x, chart.x_unit))}`,
      `${escapeHtml(String(chart.y_measure ?? "y"))} = ${escapeHtml(withUnit(firstRow.y, chart.y_unit))}`,
    ].join("<br/>");
  }
  const sourceName = String(items[0]?.data?.sourceName ?? "");
  const values = firstRow.values && typeof firstRow.values === "object" ? firstRow.values as Row : {};
  return [
    `<strong>${escapeHtml(firstRow.variant)} / ${escapeHtml(firstRow.objective)} / ${escapeHtml(firstRow.strategy)}</strong>`,
    `${escapeHtml(sourceName)} = ${escapeHtml(withUnit(values[sourceName], units[sourceName]))}`,
  ].join("<br/>");
}

function chartOption(chart: ProcessChart, interactive: boolean): EChartsOption {
  const kind = String(chart.kind ?? "");
  const sourceRows = rows(chart);
  const common: EChartsOption = {
    animation: false,
    grid: { left: 66, right: 38, top: 58, bottom: 66 },
    tooltip: { trigger: "item", className: KIRIN_ECHARTS_TOOLTIP_CLASS },
    legend: { top: 8 },
    dataZoom: [{ type: "inside", filterMode: "none" }],
  };
  if (kind === "trajectory") {
    const names = Array.isArray(chart.series) ? chart.series.map(String) : [];
    const groups = new Map<string, Row[]>();
    sourceRows.forEach((row) => {
      const key = `${String(row.variant)}/${String(row.objective)}/${String(row.strategy)}`;
      groups.set(key, [...(groups.get(key) ?? []), row]);
    });
    const markerTimes = Array.isArray(chart.markers)
      ? (chart.markers as Row[]).map((item) => approximate(item.time_approximate ?? item.time)).filter((item): item is number => item !== null)
      : [];
    return {
      ...common,
      tooltip: {
        trigger: "axis",
        className: KIRIN_ECHARTS_TOOLTIP_CLASS,
        axisPointer: { type: "line", label: { show: true } },
        formatter: (params: unknown) => processTooltip(chart, params),
      },
      xAxis: { type: "value", name: "time" },
      yAxis: { type: "value" },
      series: [...groups.entries()].flatMap(([group, groupRows], groupIndex) => names.map((name, seriesIndex) => ({
        id: `${group}/${name}`,
        name: `${group}/${name}`,
        type: "line" as const,
        cursor: interactive ? "pointer" : "default",
        showSymbol: groupRows.length <= 24,
        data: groupRows.map((row) => {
          const values = row.values && typeof row.values === "object" ? row.values as Row : {};
          return {
            value: [approximate(row.time_approximate ?? row.time), approximate(values[name])],
            row,
            sourceName: name,
          };
        }),
        markLine: groupIndex === 0 && seriesIndex === 0 ? {
          silent: true,
          symbol: ["none", "none"],
          lineStyle: { color: kirinEChartsTokens.pointer, opacity: 0.28, type: "dashed" },
          data: markerTimes.map((time) => ({ xAxis: time })),
        } : undefined,
      }))),
    };
  }
  if (kind === "decision_surface") {
    const values = sourceRows.map((row) => approximate(row.value)).filter((item): item is number => item !== null);
    return {
      ...common,
      tooltip: { trigger: "item", className: KIRIN_ECHARTS_TOOLTIP_CLASS, formatter: (params: unknown) => processTooltip(chart, params) },
      xAxis: { type: "value", name: "decision time 1" },
      yAxis: { type: "value", name: "decision time 2" },
      visualMap: { min: values.length ? Math.min(...values) : 0, max: values.length ? Math.max(...values) : 1, right: 0, calculable: true },
      series: [{
        id: String(chart.id ?? "decision_surface"),
        name: String(chart.value_measure ?? "value"),
        type: "scatter",
        cursor: interactive ? "pointer" : "default",
        symbolSize: 8,
        data: sourceRows.map((row) => ({
          value: [approximate(row.x_approximate ?? row.x), approximate(row.y_approximate ?? row.y), approximate(row.value)],
          row,
        })),
      }],
    };
  }
  if (kind === "pareto") {
    const variants = [...new Set(sourceRows.map((row) => String(row.variant)))];
    return {
      ...common,
      tooltip: { trigger: "item", className: KIRIN_ECHARTS_TOOLTIP_CLASS, formatter: (params: unknown) => processTooltip(chart, params) },
      xAxis: { type: "value", name: String(chart.x_measure ?? "x") },
      yAxis: { type: "value", name: String(chart.y_measure ?? "y") },
      series: variants.map((variant) => ({
        id: variant,
        name: variant,
        type: "scatter" as const,
        cursor: interactive ? "pointer" : "default",
        symbolSize: (value: unknown) => Array.isArray(value) && Number(value[2]) === 1 ? 11 : 6,
        data: sourceRows.filter((row) => row.variant === variant).map((row) => ({
          value: [approximate(row.x), approximate(row.y), row.nondominated ? 1 : 0],
          row,
        })),
      })),
    };
  }
  const names = Array.isArray(chart.series) ? chart.series.map(String) : [];
  const categories = sourceRows.map((row) => `${String(row.variant)}/${String(row.objective)}/${String(row.strategy)}`);
  return {
    ...common,
    tooltip: { trigger: "item", className: KIRIN_ECHARTS_TOOLTIP_CLASS, formatter: (params: unknown) => processTooltip(chart, params) },
    xAxis: { type: "category", data: categories, axisLabel: { rotate: 25 } },
    yAxis: { type: "value" },
    series: names.map((name) => ({
      id: name,
      name,
      type: "bar" as const,
      cursor: interactive ? "pointer" : "default",
      data: sourceRows.map((row) => {
        const values = row.values && typeof row.values === "object" ? row.values as Row : {};
        return { value: approximate(values[name]), row, sourceName: name };
      }),
    })),
  };
}

export function ProcessChartCanvas({ chart, onActivate }: { chart: ProcessChart; onActivate?: () => void }) {
  const hostRef = useRef<HTMLDivElement>(null);
  const onActivateRef = useRef(onActivate);
  const accessible = useMemo(() => rows(chart).map((row) => JSON.stringify(row)), [chart]);
  const interactive = Boolean(onActivate);

  useEffect(() => {
    onActivateRef.current = onActivate;
  }, [onActivate]);

  useEffect(() => {
    if (!hostRef.current) return;
    const instance = initKirinEChart(hostRef.current);
    instance.setOption(chartOption(chart, interactive), true);
    instance.on("click", (params: unknown) => {
      const item = params as { componentType?: string };
      if (item.componentType === "series") onActivateRef.current?.();
    });
    const observer = new ResizeObserver(() => instance.resize());
    observer.observe(hostRef.current);
    return () => {
      observer.disconnect();
      instance.dispose();
    };
  }, [chart, interactive]);

  return <div className="chart-visualization">
    <div className="chart-canvas" ref={hostRef} role="img" aria-label={`${String(chart.label ?? chart.id ?? "Process 图表")}；下方提供键盘数据列表`} />
    <details className="canvas-data-fallback">
      <summary>使用键盘查看 {accessible.length} 个图表数据点</summary>
      {onActivate && <div className="chart-source-targets" role="group" aria-label="分析图表源码"><button type="button" onClick={onActivate}>定位当前分析源码</button></div>}
      <ol className="chart-data-list">{accessible.map((row, index) => <li key={`${index}-${row}`} tabIndex={0}>{row}</li>)}</ol>
    </details>
  </div>;
}
