import * as echarts from "echarts/core";

export const KIRIN_ECHARTS_THEME_NAME = "kirin-tor";
export const KIRIN_ECHARTS_TOOLTIP_CLASS = "kirin-chart-tooltip";

export const kirinEChartsTokens = {
  background: "transparent",
  text: "#9c998f",
  legendText: "#b8b4aa",
  axisText: "#918d84",
  axisTextMuted: "#817d74",
  axisLine: "#45423b",
  splitLine: "#25241f",
  tooltipBackground: "#1d1c18",
  tooltipBorder: "#3a3832",
  tooltipText: "#eeeae1",
  tooltipMuted: "#99958b",
  pointer: "#69645b",
  pointerLabelBackground: "#292824",
  emphasis: "#f2efe8",
  graphFallback: "#8d887d",
  graphNodeBorder: "#171612",
  graphRootBorder: "#df8665",
  graphSelectedBorder: "#fff4e8",
  dataZoomBackground: "#151512",
  dataZoomBorder: "#34322d",
  dataZoomFiller: "rgba(217, 119, 87, .18)",
  accent: "#d97757",
  heatmapAreas: ["#151512", "#171714"],
  heatmapScale: ["#2a2521", "#7a4738", "#d97757", "#e8b86d"],
  series: ["#d97757", "#85a56f", "#7599b2", "#c19a5b", "#a88bbb", "#d16f78", "#6fa7a0", "#9a9388"],
} as const;

export const kirinGraphCategoryColors: Record<string, string> = {
  document: kirinEChartsTokens.series[0],
  input: kirinEChartsTokens.series[6],
  field: kirinEChartsTokens.series[4],
  function: kirinEChartsTokens.series[3],
  table: kirinEChartsTokens.series[1],
  distribution: kirinEChartsTokens.series[5],
  object: kirinEChartsTokens.series[7],
  output: kirinEChartsTokens.series[2],
  process: kirinEChartsTokens.series[0],
  scenario: kirinEChartsTokens.series[6],
  analysis: kirinEChartsTokens.series[3],
};

const axisTheme = {
  axisLine: { lineStyle: { color: kirinEChartsTokens.axisLine } },
  axisTick: { lineStyle: { color: kirinEChartsTokens.axisLine } },
  axisLabel: { color: kirinEChartsTokens.axisText, fontSize: 11 },
  splitLine: { lineStyle: { color: kirinEChartsTokens.splitLine } },
};

export const kirinEChartsTheme = {
  color: [...kirinEChartsTokens.series],
  backgroundColor: kirinEChartsTokens.background,
  textStyle: {
    color: kirinEChartsTokens.text,
    fontFamily: "Inter, sans-serif",
  },
  title: {
    textStyle: { color: kirinEChartsTokens.tooltipText },
    subtextStyle: { color: kirinEChartsTokens.text },
  },
  legend: {
    textStyle: { color: kirinEChartsTokens.legendText, fontSize: 11 },
  },
  tooltip: {
    backgroundColor: kirinEChartsTokens.tooltipBackground,
    borderColor: kirinEChartsTokens.tooltipBorder,
    borderWidth: 1,
    textStyle: { color: kirinEChartsTokens.tooltipText, fontSize: 12 },
  },
  axisPointer: {
    lineStyle: { color: kirinEChartsTokens.pointer, type: "dashed" },
    label: {
      show: true,
      color: kirinEChartsTokens.tooltipText,
      backgroundColor: kirinEChartsTokens.pointerLabelBackground,
    },
  },
  categoryAxis: axisTheme,
  valueAxis: axisTheme,
  logAxis: axisTheme,
  timeAxis: axisTheme,
  dataZoom: {
    borderColor: kirinEChartsTokens.dataZoomBorder,
    backgroundColor: kirinEChartsTokens.dataZoomBackground,
    fillerColor: kirinEChartsTokens.dataZoomFiller,
    textStyle: { color: kirinEChartsTokens.axisText, fontSize: 11 },
  },
  visualMap: {
    textStyle: { color: kirinEChartsTokens.axisText, fontSize: 11 },
  },
};

echarts.registerTheme(KIRIN_ECHARTS_THEME_NAME, kirinEChartsTheme);

export function initKirinEChart(host: HTMLElement) {
  return echarts.init(host, KIRIN_ECHARTS_THEME_NAME, { renderer: "canvas" });
}
