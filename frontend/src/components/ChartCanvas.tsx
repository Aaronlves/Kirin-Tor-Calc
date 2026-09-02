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

const colors = ["#d97757", "#85a56f", "#7599b2", "#c19a5b", "#a88bbb", "#d16f78", "#6fa7a0", "#9a9388"];

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

function lineOption(result: OperationResult): EChartsOption {
  const rows = Array.isArray(result.rows) ? result.rows as Array<Record<string, unknown>> : [];
  const targets = Array.isArray(result.targets) ? result.targets.map(String) : [];
  const labels = result.labels && typeof result.labels === "object" ? result.labels as Record<string, string> : {};
  const xValues = rows.map((row) => numeric(row.x_approximate ?? row.x) ?? String(row.x ?? ""));
  const isNumericAxis = xValues.every((value) => typeof value === "number");
  return {
    animation: false,
    color: colors,
    backgroundColor: "transparent",
    textStyle: { color: "#9c998f", fontFamily: "Inter, sans-serif" },
    grid: { left: 52, right: 18, top: 56, bottom: 72, containLabel: false },
    legend: {
      top: 10,
      left: 10,
      itemWidth: 16,
      itemHeight: 2,
      textStyle: { color: "#b8b4aa", fontSize: 11 },
      data: targets.map((target) => labels[target] || target),
    },
    tooltip: {
      trigger: "axis",
      backgroundColor: "#1d1c18",
      borderColor: "#3a3832",
      borderWidth: 1,
      textStyle: { color: "#eeeae1", fontSize: 12 },
      axisPointer: { lineStyle: { color: "#69645b", type: "dashed" } },
    },
    dataZoom: [
      { type: "inside", filterMode: "none" },
      {
        type: "slider",
        height: 18,
        bottom: 18,
        borderColor: "#34322d",
        backgroundColor: "#151512",
        fillerColor: "rgba(217, 119, 87, .18)",
        handleStyle: { color: "#d97757", borderColor: "#d97757" },
        textStyle: { color: "#8f8a80", fontSize: 11 },
      },
    ],
    xAxis: {
      type: isNumericAxis ? "value" : "category",
      name: `${String(result.x_display_label || result.x || "横轴")}${result.x_unit ? ` [${String(result.x_unit)}]` : ""}`,
      nameLocation: "middle",
      nameGap: 46,
      boundaryGap: false,
      data: isNumericAxis ? undefined : xValues,
      axisLine: { lineStyle: { color: "#45423b" } },
      axisTick: { lineStyle: { color: "#45423b" } },
      axisLabel: { color: "#918d84", fontSize: 11, hideOverlap: true },
      splitLine: { lineStyle: { color: "#25241f" } },
    } as EChartsOption["xAxis"],
    yAxis: {
      type: "value",
      axisLine: { show: false },
      axisLabel: { color: "#918d84", fontSize: 11 },
      splitLine: { lineStyle: { color: "#25241f" } },
    },
    series: targets.map((target, targetIndex) => ({
      name: labels[target] || target,
      type: "line",
      showSymbol: rows.length <= 24,
      symbolSize: 5,
      smooth: false,
      connectNulls: false,
      lineStyle: { width: 2 },
      emphasis: { focus: "series" },
      data: rows.map((row, rowIndex) => {
        const values = row.values && typeof row.values === "object" ? row.values as Record<string, unknown> : {};
        const y = valueFromCell(values[target]);
        return isNumericAxis ? [xValues[rowIndex], y] : y;
      }),
      z: targets.length - targetIndex,
    })),
  };
}

function heatmapOption(result: OperationResult): EChartsOption {
  const rows = Array.isArray(result.rows) ? result.rows as Array<Record<string, unknown>> : [];
  const xValues = [...new Set(rows.map((row) => String(row.x ?? "")))];
  const yValues = [...new Set(rows.map((row) => String(row.y ?? "")))];
  const data = rows.map((row) => [
    xValues.indexOf(String(row.x ?? "")),
    yValues.indexOf(String(row.y ?? "")),
    valueFromCell(row.value),
  ]);
  const numbers = data.map((item) => item[2]).filter((value): value is number => typeof value === "number");
  const min = numbers.length ? Math.min(...numbers) : 0;
  const max = numbers.length ? Math.max(...numbers) : 1;
  return {
    animation: false,
    backgroundColor: "transparent",
    textStyle: { color: "#9c998f", fontFamily: "Inter, sans-serif" },
    grid: { left: 84, right: 88, top: 38, bottom: 66 },
    tooltip: {
      position: "top",
      backgroundColor: "#1d1c18",
      borderColor: "#3a3832",
      textStyle: { color: "#eeeae1" },
      formatter: (params: unknown) => {
        const item = params as { data: [number, number, number | null] };
        return `${String(result.x)} = ${xValues[item.data[0]]}<br/>${String(result.y)} = ${yValues[item.data[1]]}<br/><strong>${item.data[2] ?? "无效"}</strong>`;
      },
    },
    xAxis: {
      type: "category",
      data: xValues,
      name: String(result.x || "横轴"),
      nameLocation: "middle",
      nameGap: 40,
      splitArea: { show: true, areaStyle: { color: ["#151512", "#171714"] } },
      axisLine: { lineStyle: { color: "#45423b" } },
      axisLabel: { color: "#817d74", hideOverlap: true },
    },
    yAxis: {
      type: "category",
      data: yValues,
      name: String(result.y || "纵轴"),
      splitArea: { show: true, areaStyle: { color: ["#151512", "#171714"] } },
      axisLine: { lineStyle: { color: "#45423b" } },
      axisLabel: { color: "#817d74", hideOverlap: true },
    },
    visualMap: {
      min,
      max,
      calculable: true,
      orient: "vertical",
      right: 12,
      top: "center",
      textStyle: { color: "#918d84", fontSize: 11 },
      inRange: { color: ["#2a2521", "#7a4738", "#d97757", "#e8b86d"] },
    },
    series: [{
      name: String(result.target_label || result.target || "结果"),
      type: "heatmap",
      data,
      label: { show: data.length <= 100, color: "#f5efe6", fontSize: 11 },
      emphasis: { itemStyle: { borderColor: "#f2efe8", borderWidth: 1 } },
    }],
  };
}

export function ChartCanvas({ result }: { result: OperationResult }) {
  const hostRef = useRef<HTMLDivElement>(null);
  const rows = accessibleRows(result);
  const label = result.operation === "grid" ? "计算热力图" : "计算曲线";

  useEffect(() => {
    if (!hostRef.current) return;
    const chart = echarts.init(hostRef.current, undefined, { renderer: "canvas" });
    chart.setOption(result.operation === "grid" ? heatmapOption(result) : lineOption(result), true);
    const observer = new ResizeObserver(() => chart.resize());
    observer.observe(hostRef.current);
    return () => {
      observer.disconnect();
      chart.dispose();
    };
  }, [result]);

  return (
    <div className="chart-visualization">
      <div className="chart-canvas" ref={hostRef} role="img" aria-label={`${label}；下方提供键盘数据列表`} />
      <details className="canvas-data-fallback">
        <summary>使用键盘查看 {rows.length} 个图表数据点</summary>
        <ol className="chart-data-list" aria-label={`${label}数据`}>
          {rows.map((row, index) => <li key={`${index}-${row}`} tabIndex={0}>{row}</li>)}
        </ol>
      </details>
    </div>
  );
}
