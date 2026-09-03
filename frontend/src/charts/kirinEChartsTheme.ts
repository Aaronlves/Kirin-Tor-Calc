import * as echarts from "echarts/core";

import tokens from "../design/tokens.json";

export const KIRIN_ECHARTS_THEME_NAME = "kirin-tor";
export const KIRIN_ECHARTS_TOOLTIP_CLASS = "kirin-chart-tooltip";

export const kirinEChartsTokens = {
  background: "transparent",
  text: tokens.color.chart.text,
  legendText: tokens.color.chart.legend,
  axisText: tokens.color.chart.axis,
  axisTextMuted: tokens.color.chart.axisMuted,
  axisLine: tokens.color.chart.axisLine,
  splitLine: tokens.color.chart.splitLine,
  tooltipBackground: tokens.color.chart.tooltip,
  tooltipBorder: tokens.color.border.floating,
  tooltipText: tokens.color.text.strong,
  tooltipMuted: tokens.color.chart.tooltipMuted,
  pointer: tokens.color.chart.pointer,
  pointerLabelBackground: tokens.color.chart.pointerLabel,
  emphasis: tokens.color.chart.emphasis,
  graphFallback: tokens.color.chart.graphFallback,
  graphNodeBorder: tokens.color.chart.graphNodeBorder,
  graphRootBorder: tokens.color.chart.graphRootBorder,
  graphSelectedBorder: tokens.color.palette.orange[0],
  dataZoomBackground: tokens.color.surface.control,
  dataZoomBorder: tokens.color.chart.dataZoom,
  dataZoomFiller: tokens.color.chart.dataZoomFill,
  accent: tokens.color.accent.chart,
  heatmapAreas: [tokens.color.surface.control, tokens.color.surface.floating],
  heatmapScale: tokens.color.chart.heatmap,
  series: tokens.color.chart.series,
  fontSizeMeta: Number.parseInt(tokens.typography.size.meta),
  fontSizeBody: Number.parseInt(tokens.typography.size.body),
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
  axisLabel: { color: kirinEChartsTokens.axisText, fontSize: kirinEChartsTokens.fontSizeMeta },
  splitLine: { lineStyle: { color: kirinEChartsTokens.splitLine } },
};

export const kirinEChartsTheme = {
  color: [...kirinEChartsTokens.series],
  backgroundColor: kirinEChartsTokens.background,
  textStyle: {
    color: kirinEChartsTokens.text,
    fontFamily: tokens.typography.family.sans,
  },
  title: {
    textStyle: { color: kirinEChartsTokens.tooltipText },
    subtextStyle: { color: kirinEChartsTokens.text },
  },
  legend: {
    textStyle: { color: kirinEChartsTokens.legendText, fontSize: kirinEChartsTokens.fontSizeMeta },
  },
  tooltip: {
    confine: true,
    backgroundColor: kirinEChartsTokens.tooltipBackground,
    borderColor: kirinEChartsTokens.tooltipBorder,
    borderWidth: 1,
    borderRadius: Number.parseInt(tokens.shape.radius),
    padding: [Number.parseInt(tokens.space["2"]), Number.parseInt(tokens.space.dense)],
    textStyle: { color: kirinEChartsTokens.tooltipText, fontSize: kirinEChartsTokens.fontSizeBody },
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
    textStyle: { color: kirinEChartsTokens.axisText, fontSize: kirinEChartsTokens.fontSizeMeta },
  },
  visualMap: {
    textStyle: { color: kirinEChartsTokens.axisText, fontSize: kirinEChartsTokens.fontSizeMeta },
  },
};

echarts.registerTheme(KIRIN_ECHARTS_THEME_NAME, kirinEChartsTheme);

export function initKirinEChart(host: HTMLElement) {
  return echarts.init(host, KIRIN_ECHARTS_THEME_NAME, { renderer: "canvas" });
}
