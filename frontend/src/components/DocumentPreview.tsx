import { useEffect, useMemo, useRef, useState } from "react";
import { Badge, Box, Button, Checkbox, Code, Group, Modal, ScrollArea, SegmentedControl, Select, SimpleGrid, Stack, Text, TextInput } from "@mantine/core";
import { Crosshair, FileOutput, Maximize2, Save } from "lucide-react";

import { errorMessage } from "../api";
import type { WorkbenchController } from "../hooks/useWorkbench";
import type { DocumentItem, DocumentProjection, OperationResult, PluginSurfaceContribution } from "../types";
import { ChartCanvas } from "./ChartCanvas";
import { ProcessChartCanvas } from "./ProcessChartCanvas";
import { PluginSurface } from "./PluginSurface";
import { EmptyState, LoadingState, TechnicalResult } from "./ui";

function documentId(source: string): string | null {
  return source.match(/^@entry\s+([A-Za-z_][A-Za-z0-9_]*)(?:\s+"(?:[^"\\]|\\.)*")?$/m)?.[1] ?? null;
}

function displayedValue(result: OperationResult): string {
  for (const key of ["formatted", "approximate", "exact"]) {
    const value = result[key];
    if (value !== null && value !== undefined && value !== "") return String(value);
  }
  return "—";
}

interface DocumentPreviewProps {
  controller: WorkbenchController;
  document: DocumentItem;
  source: string;
  activeSymbolId?: string | null;
  onNavigateToSource(key: string, line?: number | null, column?: number | null): void;
}

function rendererMatches(
  renderer: PluginSurfaceContribution,
  entryId: string | null,
  packageName?: string,
): boolean {
  const match = renderer.match;
  if (!match || !entryId) return false;
  return match.document_ids.includes(entryId)
    || match.document_id_prefixes.some((prefix) => entryId.startsWith(prefix))
    || Boolean(packageName && match.package_names.includes(packageName));
}

export function DocumentPreview({ controller, document, source, activeSymbolId = null, onNavigateToSource }: DocumentPreviewProps) {
  const entryId = documentId(source);
  const entryTargets = useMemo(() => entryId ? controller.workspaceIndex.targets.filter((target) => target.value.startsWith(`${entryId}.`)) : [], [controller.workspaceIndex.targets, entryId]);
  const entryTargetSignature = entryTargets.map((item) => item.value).join("\u0000");
  const chart = entryId ? controller.workspaceIndex.charts.find((item) => item.value === entryId) : undefined;
  const hasChart = Boolean(chart);
  const entryAnalyses = useMemo(() => entryId ? controller.workspaceIndex.analyses.filter((analysis) => analysis.value.startsWith(`${entryId}.`)) : [], [controller.workspaceIndex.analyses, entryId]);
  const entryAnalysisSignature = entryAnalyses.map((item) => item.value).join("\u0000");
  const matchingRenderers = useMemo(
    () => controller.pluginSummary.contributions.renderers.filter(
      (renderer) => rendererMatches(renderer, entryId, document.package?.name),
    ),
    [controller.pluginSummary.contributions.renderers, document.package?.name, entryId],
  );
  const [presentation, setPresentation] = useState<string>(matchingRenderers[0]?.id ?? "generic");
  const selectedRenderer = matchingRenderers.find((item) => item.id === presentation) ?? null;
  const [projection, setProjection] = useState<DocumentProjection | null>(null);
  const [projectionError, setProjectionError] = useState<string | null>(null);
  const [projectionLoading, setProjectionLoading] = useState(false);
  const presentationWasChosen = useRef(false);
  const [mode, setMode] = useState<"result" | "chart" | "process">("result");
  const [target, setTarget] = useState<string | null>(entryTargets[0]?.value ?? null);
  const [analysisTarget, setAnalysisTarget] = useState<string | null>(entryAnalyses[0]?.value ?? null);
  const [processChartId, setProcessChartId] = useState<string | null>(null);
  const [result, setResult] = useState<OperationResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [running, setRunning] = useState(false);
  const [exportOpened, setExportOpened] = useState(false);
  const [exportOut, setExportOut] = useState("");
  const [exportDataOut, setExportDataOut] = useState("");
  const [force, setForce] = useState(false);
  const [allowOutside, setAllowOutside] = useState(false);
  const [runId, setRunId] = useState("");
  const [exportResult, setExportResult] = useState<OperationResult | null>(null);
  const [expandedPreviewOpened, setExpandedPreviewOpened] = useState(false);
  const modeWasChosen = useRef(false);

  useEffect(() => {
    modeWasChosen.current = false;
    setTarget(entryTargets[0]?.value ?? null);
    setAnalysisTarget(entryAnalyses[0]?.value ?? null);
    setProcessChartId(null);
    setMode(entryTargets.length ? "result" : hasChart ? "chart" : "process");
    setResult(null);
    setError(null);
    setExportResult(null);
    setExpandedPreviewOpened(false);
    setPresentation(matchingRenderers[0]?.id ?? "generic");
    setProjection(null);
    setProjectionError(null);
    presentationWasChosen.current = false;
  }, [document.key]);

  useEffect(() => {
    setPresentation((selected) => {
      if (matchingRenderers.some((item) => item.id === selected)) return selected;
      if (selected === "generic" && presentationWasChosen.current) return selected;
      return matchingRenderers[0]?.id ?? "generic";
    });
  }, [matchingRenderers]);

  useEffect(() => {
    if (!selectedRenderer || controller.validation?.status !== "ok") {
      setProjectionLoading(false);
      return;
    }
    let active = true;
    setProjectionLoading(true);
    setProjectionError(null);
    const timer = window.setTimeout(() => {
      void controller.documentProjection(document.key).then(
        (result) => { if (active) setProjection(result); },
        (caught) => {
          if (active) {
            setProjection(null);
            setProjectionError(errorMessage(caught));
          }
        },
      ).finally(() => { if (active) setProjectionLoading(false); });
    }, 350);
    return () => {
      active = false;
      window.clearTimeout(timer);
    };
  }, [controller.documentProjection, controller.validation?.status, document.key, selectedRenderer, source]);

  useEffect(() => {
    setTarget((selected) => entryTargets.some((item) => item.value === selected) ? selected : entryTargets[0]?.value ?? null);
    setMode((selected) => {
      if (!modeWasChosen.current) {
        if (entryTargets.length) return "result";
        if (hasChart) return "chart";
        if (entryAnalyses.length) return "process";
      }
      if (selected === "chart" && !hasChart && entryTargets.length) return "result";
      if (selected === "result" && !entryTargets.length && hasChart) return "chart";
      if (selected === "process" && !entryAnalyses.length && entryTargets.length) return "result";
      return selected;
    });
    setAnalysisTarget((selected) => entryAnalyses.some((item) => item.value === selected) ? selected : entryAnalyses[0]?.value ?? null);
  }, [entryTargetSignature, entryAnalysisSignature, entryAnalyses, hasChart]);

  useEffect(() => {
    if (!activeSymbolId || !entryTargets.some((item) => item.value === activeSymbolId)) return;
    setTarget(activeSymbolId);
    setMode("result");
  }, [activeSymbolId, entryTargetSignature]);

  useEffect(() => {
    if (!activeSymbolId || !entryAnalyses.some((item) => item.value === activeSymbolId)) return;
    setAnalysisTarget(activeSymbolId);
    setMode("process");
  }, [activeSymbolId, entryAnalysisSignature, entryAnalyses]);

  useEffect(() => {
    setResult(null);
    setError(null);
    setExportResult(null);
    setProjection(null);
  }, [source]);

  const selectedTarget = entryTargets.find((item) => item.value === target);
  const selectedAnalysis = entryAnalyses.find((item) => item.value === analysisTarget);
  const relevantInputs = controller.workspaceIndex.inputs.filter((input) => selectedTarget?.inputs?.includes(input.value));

  useEffect(() => {
    const canPreview = Boolean(
      entryId
      && controller.validation?.status === "ok"
      && (mode === "chart" ? hasChart : mode === "process" ? analysisTarget : target),
    );
    if (!canPreview) {
      setRunning(false);
      return;
    }

    let active = true;
    setRunning(true);
    setError(null);
    const timer = window.setTimeout(() => {
      void (async () => {
        try {
          const nextResult = mode === "chart"
            ? await controller.operation("preview_plot", { config: entryId, precision: 30, display_digits: 12, timeout: 10 })
            : mode === "process"
                ? await controller.operation("process_analysis", { target: analysisTarget, timeout: 30 })
              : await controller.operation("eval", { target, precision: 30, display_digits: 12, timeout: 10 });
          if (active) {
            setResult(nextResult);
            if (mode === "process") {
              const charts = Array.isArray(nextResult.charts) ? nextResult.charts as Array<Record<string, unknown>> : [];
              setProcessChartId(charts.length ? String(charts[0].id) : null);
            }
          }
        } catch (caught) {
          if (active) {
            setError(errorMessage(caught));
            setResult(null);
          }
        } finally {
          if (active) setRunning(false);
        }
      })();
    }, 650);

    return () => {
      active = false;
      window.clearTimeout(timer);
    };
  }, [analysisTarget, controller.operation, controller.validation?.status, entryId, hasChart, mode, source, target]);

  const exportChart = async () => {
    if (!entryId) return;
    setRunning(true);
    try {
      const exported = await controller.operation("plot", { config: entryId, out: exportOut || null, data_out: exportDataOut || null, force, allow_outside_workspace: allowOutside, precision: 30, display_digits: 12, timeout: 10, save_run: runId.trim() || null });
      setExportResult(exported);
      setExportOpened(false);
    } catch (caught) {
      setError(errorMessage(caught));
    } finally {
      setRunning(false);
    }
  };

  const exportProcessCharts = async () => {
    if (!analysisTarget) return;
    setRunning(true);
    try {
      const exported = await controller.operation("export_process_charts", {
        target: analysisTarget,
        force: false,
        allow_outside_workspace: false,
        timeout: 30,
      });
      setExportResult(exported);
    } catch (caught) {
      setError(errorMessage(caught));
    } finally {
      setRunning(false);
    }
  };

  const processCharts = result && Array.isArray(result.charts)
    ? result.charts as Array<Record<string, unknown>>
    : [];
  const selectedProcessChart = processCharts.find((item) => String(item.id) === processChartId) ?? processCharts[0] ?? null;
  const processVariants = result && Array.isArray(result.variants)
    ? result.variants as Array<Record<string, unknown>>
    : [];
  const processOperation = String(result?.analysis_operation ?? "—");
  const processCountLabel = (() => {
    if (!result) return "0 个结果";
    if (processOperation === "optimize") return `${processVariants.length} 个方案`;
    if (processOperation === "compare" && Array.isArray(result.policies)) return `${result.policies.length} 个策略`;
    if ((processOperation === "run" || processOperation === "reach") && Array.isArray(result.outcomes)) return `${result.outcomes.length} 条路径`;
    if (processOperation === "cycle" && Array.isArray(result.runs)) return `${result.runs.length} 次迭代`;
    if (processOperation === "steady" && Array.isArray(result.states)) return `${result.states.length} 个状态`;
    return "1 个结果";
  })();

  if (!entryId) return <EmptyState title="文档声明无效" description="修复 @entry 文档头后，结果和图表投影会在这里出现。" />;
  if (!entryTargets.length && !hasChart && !entryAnalyses.length && !matchingRenderers.length) return <EmptyState title="这个文档没有可预览投影" description="定义 output、chart 或 analysis 后，相应投影会出现在这里。" />;

  const presentationSwitch = matchingRenderers.length > 0 ? (
    <SegmentedControl
      fullWidth
      size="xs"
      value={presentation}
      onChange={(value) => { presentationWasChosen.current = true; setPresentation(value); }}
      data={[
        ...(entryTargets.length || hasChart || entryAnalyses.length ? [{ value: "generic", label: "通用" }] : []),
        ...matchingRenderers.map((item) => ({ value: item.id, label: item.title })),
      ]}
    />
  ) : null;

  if (selectedRenderer) {
    return (
      <Stack h="100%" gap={0} className="plugin-document-projection">
        <Box p="sm" className="plugin-document-switch">{presentationSwitch}</Box>
        {controller.validation?.status !== "ok"
          ? <EmptyState title="插件投影等待有效文档" description="修复当前工作区问题后，工作台才会向沙箱插件发送结构化文档。" />
          : projectionLoading && !projection
            ? <LoadingState label="正在生成插件文档投影…" />
            : projectionError
              ? <EmptyState title="无法生成插件投影" description={projectionError} />
              : projection
                ? <PluginSurface
                    compact
                    controller={controller}
                    contribution={selectedRenderer}
                    projection={projection}
                    onNavigateToSource={onNavigateToSource}
                  />
                : null}
      </Stack>
    );
  }

  return (
    <>
      <ScrollArea h="100%" type="auto">
        <Stack p="md" gap="md">
          {presentationSwitch}
          <Box><Text className="result-label">DOCUMENT PROJECTION</Text><Text fw={650} fz="sm" mt={4}>{entryId}</Text><Text c="dimmed" fz="xs" mt={3}>从当前源码草稿和源码默认值即时派生，不接受临时参数。</Text></Box>
          {[entryTargets.length > 0, hasChart, entryAnalyses.length > 0].filter(Boolean).length > 1 && <SegmentedControl fullWidth size="xs" value={mode} onChange={(value) => { modeWasChosen.current = true; setMode(value as "result" | "chart" | "process"); setResult(null); }} data={[...(entryTargets.length ? [{ value: "result", label: "结果" }] : []), ...(hasChart ? [{ value: "chart", label: "图表" }] : []), ...(entryAnalyses.length ? [{ value: "process", label: "过程" }] : [])]} />}
          {mode === "result" && entryTargets.length > 1 && <Select label="查看结果" searchable value={target} onChange={(value) => { setTarget(value); setResult(null); }} data={entryTargets.map((item) => ({ value: item.value, label: `${item.group_label ? `${item.group_label} / ` : ""}${item.label}` }))} />}
          {mode === "process" && entryAnalyses.length > 1 && <Select label="过程分析" searchable value={analysisTarget} onChange={(value) => { setAnalysisTarget(value); setResult(null); }} data={entryAnalyses.map((item) => ({ value: item.value, label: item.label }))} />}
          {mode === "result" && relevantInputs.length > 0 && <Box className="preview-inputs"><Text className="result-label">相关输入</Text>{relevantInputs.map((input) => <Group key={input.value} justify="space-between" wrap="nowrap" mt={7}><span><strong>{input.label}</strong><small>{input.value}</small></span><Code>{String(input.default ?? "—")}</Code></Group>)}</Box>}
          {running && !result && <LoadingState label={mode === "chart" ? "正在生成图表…" : mode === "process" ? "正在搜索过程策略…" : "正在计算结果…"} />}
          {error && <Box className="inline-error compact"><Text fw={650}>投影未完成</Text><Text c="dimmed" fz="xs" mt={5}>{error}</Text></Box>}
          {result && mode === "result" && <Stack gap="md" className={`document-result-preview${activeSymbolId === target ? " is-source-linked" : ""}`}><Box><Group justify="space-between" wrap="nowrap"><Text className="result-label">{selectedTarget?.label || target}</Text>{selectedTarget?.line && <Button variant="subtle" color="gray" size="compact-xs" leftSection={<Crosshair size={13} />} onClick={() => onNavigateToSource(document.key, selectedTarget.line, selectedTarget.column)}>定位结果源码</Button>}</Group><Text className="document-result-value">{displayedValue(result)}</Text><Group gap={6} mt="xs">{Boolean(result.unit) && <Badge variant="outline" color="gray">{String(result.unit)}</Badge>}<Code>{String(result.exact ?? "—")}</Code></Group></Box><TechnicalResult result={result} /></Stack>}
          {result && mode === "process" && <Stack gap="md" className={`document-result-preview${activeSymbolId === analysisTarget ? " is-source-linked" : ""}`}>
            <Group justify="space-between" wrap="nowrap"><Box><Text className="result-label">PROCESS ANALYSIS</Text><Text fw={650}>{selectedAnalysis?.label || analysisTarget}</Text></Box><Group gap={4}>{selectedAnalysis?.line && <Button variant="subtle" color="gray" size="compact-xs" leftSection={<Crosshair size={13} />} onClick={() => onNavigateToSource(document.key, selectedAnalysis.line, selectedAnalysis.column)}>定位分析源码</Button>}<Button variant="default" size="xs" leftSection={<FileOutput size={13} />} loading={running} onClick={() => { void exportProcessCharts(); }}>导出全部图表</Button></Group></Group>
            <Group gap={6}><Badge variant="light" color="green">{processCountLabel}</Badge><Badge variant="outline" color="gray">{processOperation}</Badge><Badge variant="outline" color="gray">{String(result.random_semantics ?? "deterministic_scenario")}</Badge>{result.explored_branches !== undefined && <Badge variant="outline" color="gray">搜索 {String(result.explored_branches)}</Badge>}</Group>
            {processOperation === "optimize" && <SimpleGrid cols={{ base: 1, lg: Math.min(2, Math.max(1, processVariants.length)) }}>
              {processVariants.map((variant) => {
                const objectives = Array.isArray(variant.objectives) ? variant.objectives as Array<Record<string, unknown>> : [];
                return <Box key={String(variant.variant)} className="preview-inputs"><Text className="result-label">{String(variant.variant)}</Text>{objectives.map((objective) => {
                  const proof = objective.proof && typeof objective.proof === "object" ? objective.proof as Record<string, unknown> : {};
                  const strategies = Array.isArray(objective.optimal_strategies) ? objective.optimal_strategies as Array<Record<string, unknown>> : [];
                  return <Box key={String(objective.objective)} mt="sm"><Group justify="space-between"><Text fw={650} fz="sm">{String(objective.objective)}</Text><Group gap={4}><Badge variant="outline" color="gray">{strategies.length} 个并列最优</Badge><Badge color={proof.level === "exact_global" ? "green" : proof.level === "global_with_error_bound" ? "blue" : "yellow"}>{String(proof.level ?? "—")}</Badge></Group></Group>{strategies.map((strategy, index) => {
                    const run = strategy.run && typeof strategy.run === "object" ? strategy.run as Record<string, unknown> : {};
                    const decisions = Array.isArray(run.decisions) ? run.decisions as Array<Record<string, unknown>> : [];
                    const measures = strategy.measures && typeof strategy.measures === "object" ? strategy.measures as Record<string, unknown> : {};
                    return <Box key={`${String(objective.objective)}-${index}`} mt="xs"><Text c="dimmed" fz="xs">策略 {index + 1} · 释放：{decisions.length ? decisions.map((item) => `${String(item.time)} ${String(item.choice)}`).join("；") : "不释放"}</Text><Group gap={4} mt={6}>{Object.entries(measures).map(([name, value]) => <Code key={name}>{name}={String(value)}</Code>)}</Group></Box>;
                  })}</Box>;
                })}</Box>;
              })}
            </SimpleGrid>}
            {processCharts.length > 0 && <Box className="document-chart-preview"><Group justify="space-between" mb="sm"><Select label="分析图表" value={String(selectedProcessChart?.id ?? "")} onChange={setProcessChartId} data={processCharts.map((item) => ({ value: String(item.id), label: String(item.label ?? item.id) }))} /><Badge variant="outline" color="gray">{String(selectedProcessChart?.kind ?? "—")}</Badge></Group>{selectedProcessChart && <ProcessChartCanvas chart={selectedProcessChart} />}</Box>}
            <TechnicalResult result={result} />
          </Stack>}
          {result && mode === "chart" && <Stack gap="sm" className="document-chart-preview"><Group justify="space-between"><Text className="result-label">图表预览</Text><Group gap={4}>{chart?.line && <Button variant="subtle" color="gray" size="compact-xs" leftSection={<Crosshair size={13} />} onClick={() => onNavigateToSource(document.key, chart.line, chart.column)}>定位图表源码</Button>}<Button variant="default" size="xs" leftSection={<Maximize2 size={13} />} onClick={() => setExpandedPreviewOpened(true)}>展开预览</Button><Button variant="default" size="xs" leftSection={<FileOutput size={13} />} onClick={() => setExportOpened(true)}>导出</Button></Group></Group><ChartCanvas result={result} /><Group gap={6}><Badge variant="light" color="green">{Array.isArray(result.rows) ? result.rows.length : 0} 个采样点</Badge><Badge variant="outline" color="gray">{String(result.x || "—")}</Badge></Group><TechnicalResult result={result} /></Stack>}
          {exportResult && <Box className="export-success"><Save size={16} /><span><strong>图表已导出</strong><small>{String(exportResult.out || "已使用文档声明的输出路径")}</small></span></Box>}
        </Stack>
      </ScrollArea>

      <Modal opened={exportOpened} onClose={() => setExportOpened(false)} title="导出当前文档图表" centered>
        <Stack><Text c="dimmed" fz="xs">路径留空时使用文档中声明的导出路径。</Text><TextInput label="图像路径" placeholder="使用文档定义" value={exportOut} onChange={(event) => setExportOut(event.currentTarget.value)} /><TextInput label="CSV 路径" placeholder="使用文档定义或不导出数据" value={exportDataOut} onChange={(event) => setExportDataOut(event.currentTarget.value)} /><SimpleGrid cols={2}><Checkbox label="覆盖已有文件" checked={force} onChange={(event) => setForce(event.currentTarget.checked)} /><Checkbox label="允许工作区外路径" checked={allowOutside} onChange={(event) => setAllowOutside(event.currentTarget.checked)} /></SimpleGrid><TextInput label="运行记录 ID" disabled={controller.dirtyCount > 0} description={controller.dirtyCount ? "请先保存全部草稿。" : "可选"} value={runId} onChange={(event) => setRunId(event.currentTarget.value)} /><Group justify="flex-end"><Button variant="default" onClick={() => setExportOpened(false)}>取消</Button><Button loading={running} onClick={() => { void exportChart(); }}>生成文件</Button></Group></Stack>
      </Modal>
      <Modal fullScreen opened={expandedPreviewOpened} onClose={() => setExpandedPreviewOpened(false)} title="展开图表预览">
        {result && mode === "chart" && <div className="expanded-chart-preview"><ChartCanvas result={result} /></div>}
      </Modal>
    </>
  );
}
