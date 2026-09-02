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

function chartOption(chart: ProcessChart): EChartsOption {
  const kind = String(chart.kind ?? "");
  const sourceRows = rows(chart);
  const common: EChartsOption = {
    animation: false,
    backgroundColor: "transparent",
    textStyle: { color: "#9c998f", fontFamily: "Inter, sans-serif" },
    grid: { left: 66, right: 38, top: 58, bottom: 66 },
    tooltip: { trigger: "item", backgroundColor: "#1d1c18", borderColor: "#3a3832", textStyle: { color: "#eeeae1" } },
    legend: { top: 8, textStyle: { color: "#b8b4aa", fontSize: 10 } },
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
      xAxis: { type: "value", name: "time", axisLabel: { color: "#817d74" }, splitLine: { lineStyle: { color: "#25241f" } } },
      yAxis: { type: "value", axisLabel: { color: "#817d74" }, splitLine: { lineStyle: { color: "#25241f" } } },
      series: [...groups.entries()].flatMap(([group, groupRows], groupIndex) => names.map((name, seriesIndex) => ({
        name: `${group}/${name}`,
        type: "line" as const,
        showSymbol: groupRows.length <= 24,
        data: groupRows.map((row) => {
          const values = row.values && typeof row.values === "object" ? row.values as Row : {};
          return [approximate(row.time_approximate ?? row.time), approximate(values[name])];
        }),
        markLine: groupIndex === 0 && seriesIndex === 0 ? {
          silent: true,
          symbol: ["none", "none"],
          lineStyle: { color: "#77736a", opacity: 0.28, type: "dashed" },
          data: markerTimes.map((time) => ({ xAxis: time })),
        } : undefined,
      }))),
    };
  }
  if (kind === "decision_surface") {
    const values = sourceRows.map((row) => approximate(row.value)).filter((item): item is number => item !== null);
    return {
      ...common,
      xAxis: { type: "value", name: "decision time 1", axisLabel: { color: "#817d74" } },
      yAxis: { type: "value", name: "decision time 2", axisLabel: { color: "#817d74" } },
      visualMap: { min: values.length ? Math.min(...values) : 0, max: values.length ? Math.max(...values) : 1, right: 0, calculable: true, textStyle: { color: "#817d74" } },
      series: [{
        name: String(chart.value_measure ?? "value"),
        type: "scatter",
        symbolSize: 8,
        data: sourceRows.map((row) => [approximate(row.x_approximate ?? row.x), approximate(row.y_approximate ?? row.y), approximate(row.value)]),
      }],
    };
  }
  if (kind === "pareto") {
    const variants = [...new Set(sourceRows.map((row) => String(row.variant)))];
    return {
      ...common,
      xAxis: { type: "value", name: String(chart.x_measure ?? "x"), axisLabel: { color: "#817d74" } },
      yAxis: { type: "value", name: String(chart.y_measure ?? "y"), axisLabel: { color: "#817d74" } },
      series: variants.map((variant) => ({
        name: variant,
        type: "scatter" as const,
        symbolSize: (value: unknown) => Array.isArray(value) && Number(value[2]) === 1 ? 11 : 6,
        data: sourceRows.filter((row) => row.variant === variant).map((row) => [approximate(row.x), approximate(row.y), row.nondominated ? 1 : 0]),
      })),
    };
  }
  const names = Array.isArray(chart.series) ? chart.series.map(String) : [];
  const categories = sourceRows.map((row) => `${String(row.variant)}/${String(row.objective)}/${String(row.strategy)}`);
  return {
    ...common,
    xAxis: { type: "category", data: categories, axisLabel: { color: "#817d74", rotate: 25 } },
    yAxis: { type: "value", axisLabel: { color: "#817d74" } },
    series: names.map((name) => ({
      name,
      type: "bar" as const,
      data: sourceRows.map((row) => {
        const values = row.values && typeof row.values === "object" ? row.values as Row : {};
        return approximate(values[name]);
      }),
    })),
  };
}

export function ProcessChartCanvas({ chart }: { chart: ProcessChart }) {
  const hostRef = useRef<HTMLDivElement>(null);
  const accessible = useMemo(() => rows(chart).map((row) => JSON.stringify(row)), [chart]);

  useEffect(() => {
    if (!hostRef.current) return;
    const instance = echarts.init(hostRef.current, undefined, { renderer: "canvas" });
    instance.setOption(chartOption(chart), true);
    const observer = new ResizeObserver(() => instance.resize());
    observer.observe(hostRef.current);
    return () => {
      observer.disconnect();
      instance.dispose();
    };
  }, [chart]);

  return <div className="chart-visualization">
    <div className="chart-canvas" ref={hostRef} role="img" aria-label={`${String(chart.label ?? chart.id ?? "Process 图表")}；下方提供键盘数据列表`} />
    <details className="canvas-data-fallback">
      <summary>使用键盘查看 {accessible.length} 个图表数据点</summary>
      <ol className="chart-data-list">{accessible.map((row, index) => <li key={`${index}-${row}`} tabIndex={0}>{row}</li>)}</ol>
    </details>
  </div>;
}
