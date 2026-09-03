import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { Badge, Box, Button, Checkbox, Code, Group, Modal, ScrollArea, SegmentedControl, Select, SimpleGrid, Stack, Text, TextInput } from "@mantine/core";
import { notifications } from "@mantine/notifications";
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

function appendPresetDraft(source: string, presetId: string, label: string, overrides: Record<string, string>): string {
  const heading = `preset ${presetId}${label.trim() ? ` ${JSON.stringify(label.trim())}` : ""}:`;
  const assignments = Object.entries(overrides).map(([name, value]) => `  ${name} = ${value}`);
  return `${source.trimEnd()}\n\n${heading}\n${assignments.join("\n")}\n`;
}

function DeferredChart({ label, children }: { label: string; children: ReactNode }) {
  const hostRef = useRef<HTMLDivElement>(null);
  const [ready, setReady] = useState(false);

  useEffect(() => {
    const host = hostRef.current;
    if (!host || ready) return;
    if (!("IntersectionObserver" in window)) {
      setReady(true);
      return;
    }
    const observer = new IntersectionObserver((entries) => {
      if (!entries.some((entry) => entry.isIntersecting)) return;
      setReady(true);
      observer.disconnect();
    }, { rootMargin: "240px 0px" });
    observer.observe(host);
    return () => observer.disconnect();
  }, [ready]);

  return <div className="deferred-chart" ref={hostRef} aria-label={label}>
    {ready ? children : <LoadingState label="图表进入可视区域后加载…" />}
  </div>;
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
  const entryCharts = useMemo(() => entryId ? controller.workspaceIndex.charts.filter((item) => item.owner_id === entryId) : [], [controller.workspaceIndex.charts, entryId]);
  const entryChartSignature = entryCharts.map((item) => item.value).join("\u0000");
  const hasChart = entryCharts.length > 0;
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
  const [trialValues, setTrialValues] = useState<Record<string, string>>({});
  const [presetOpened, setPresetOpened] = useState(false);
  const [presetId, setPresetId] = useState("trial_preset");
  const [presetLabel, setPresetLabel] = useState("试算方案");
  const [runOpened, setRunOpened] = useState(false);
  const [trialRunId, setTrialRunId] = useState("");
  const [savingRun, setSavingRun] = useState(false);
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
  const [exportChartConfig, setExportChartConfig] = useState<string | null>(null);
  const [expandedPreview, setExpandedPreview] = useState<{ kind: "static" | "process"; chart: Record<string, unknown> } | null>(null);
  const modeWasChosen = useRef(false);

  useEffect(() => {
    modeWasChosen.current = false;
    setTarget(entryTargets[0]?.value ?? null);
    setAnalysisTarget(entryAnalyses[0]?.value ?? null);
    setTrialValues({});
    setPresetOpened(false);
    setRunOpened(false);
    setMode(entryTargets.length ? "result" : hasChart ? "chart" : "process");
    setResult(null);
    setError(null);
    setExportResult(null);
    setExpandedPreview(null);
    setExportChartConfig(null);
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
  }, [entryTargetSignature, entryAnalysisSignature, entryAnalyses, entryChartSignature, hasChart]);

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
  const navigateToTargetSource = (targetId: string) => {
    const symbol = controller.authoringIndex.symbols.find((item) => item.id === targetId);
    if (!symbol) return;
    onNavigateToSource(
      symbol.definition.key,
      symbol.definition.line,
      symbol.definition.column,
    );
  };
  const navigateToAnalysisSource = () => {
    if (!selectedAnalysis?.line) return;
    onNavigateToSource(document.key, selectedAnalysis.line, selectedAnalysis.column);
  };
  const relevantInputs = controller.workspaceIndex.inputs.filter((input) => selectedTarget?.inputs?.includes(input.value));
  const trialOverrides = useMemo(() => {
    const overrides: Record<string, string> = {};
    for (const input of relevantInputs) {
      const value = trialValues[input.value]?.trim();
      if (value) overrides[input.value] = value;
    }
    return overrides;
  }, [relevantInputs, trialValues]);
  const trialSignature = JSON.stringify(trialOverrides);
  const hasTrial = Object.keys(trialOverrides).length > 0;
  const normalizedPresetId = presetId.trim();
  const currentPresetIdValid = /^[A-Za-z_][A-Za-z0-9_]*$/.test(normalizedPresetId)
    && !new RegExp(`^preset\\s+${normalizedPresetId}(?:\\s|:)`, "m").test(source);
  const trialRunIdValid = /^[A-Za-z0-9_-]+$/.test(trialRunId.trim());

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
            ? await controller.operation("preview_plots", { entry: entryId, precision: 30, display_digits: 12, timeout: 10 })
            : mode === "process"
                ? await controller.operation("process_analysis", { target: analysisTarget, timeout: 30 })
              : hasTrial
                ? await controller.operation("compare", {
                    target,
                    variants: [
                      { name: "源码默认值" },
                      { name: "当前试算", overrides: trialOverrides },
                    ],
                    precision: 30,
                    display_digits: 12,
                    timeout: 10,
                  })
                : await controller.operation("eval", { target, precision: 30, display_digits: 12, timeout: 10 });
          if (active) {
            setResult(nextResult);
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
  }, [analysisTarget, controller.operation, controller.validation?.status, entryChartSignature, entryId, hasChart, hasTrial, mode, source, target, trialSignature]);

  const createPresetDraft = () => {
    const normalizedId = presetId.trim();
    if (!currentPresetIdValid || !Object.keys(trialOverrides).length) return;
    controller.updateBuffer(document.key, appendPresetDraft(source, normalizedId, presetLabel, trialOverrides));
    setPresetOpened(false);
    notifications.show({ color: "orange", title: "参数方案草稿已生成", message: `${normalizedId} 已加入当前编辑缓冲；保存全部后才会成为权威源码。` });
  };

  const saveTrialRun = async () => {
    if (!target || !trialRunIdValid || controller.dirtyCount > 0) return;
    setSavingRun(true);
    try {
      const nextResult = hasTrial
        ? await controller.operation("compare", {
            target,
            variants: [
              { name: "源码默认值" },
              { name: "当前试算", overrides: trialOverrides },
            ],
            precision: 30,
            display_digits: 12,
            timeout: 10,
            save_run: trialRunId.trim(),
          })
        : await controller.operation("eval", {
            target,
            precision: 30,
            display_digits: 12,
            timeout: 10,
            save_run: trialRunId.trim(),
          });
      setResult(nextResult);
      setRunOpened(false);
      notifications.show({ color: "green", title: "运行记录已保存", message: `${trialRunId.trim()} 已记录当前结果和已保存源码快照。` });
    } catch (caught) {
      setError(errorMessage(caught));
    } finally {
      setSavingRun(false);
    }
  };

  const exportChart = async () => {
    if (!exportChartConfig) return;
    setRunning(true);
    try {
      const exported = await controller.operation("plot", { config: exportChartConfig, out: exportOut || null, data_out: exportDataOut || null, force, allow_outside_workspace: allowOutside, precision: 30, display_digits: 12, timeout: 10, save_run: runId.trim() || null });
      setExportResult(exported);
      setExportOpened(false);
    } catch (caught) {
      setError(errorMessage(caught));
    } finally {
      setRunning(false);
    }
  };

  const exportStaticCharts = async () => {
    if (!entryId) return;
    setRunning(true);
    try {
      const exported = await controller.operation("export_static_charts", {
        entry: entryId,
        force: false,
        allow_outside_workspace: false,
        timeout: 10,
      });
      setExportResult(exported);
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
  const staticCharts = result && mode === "chart" && Array.isArray(result.charts)
    ? result.charts as Array<Record<string, unknown>>
    : [];
  const processVariants = result && Array.isArray(result.variants)
    ? result.variants as Array<Record<string, unknown>>
    : [];
  const comparisonRows = result?.operation === "compare" && Array.isArray(result.variants)
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
          <Box><Text className="result-label">文档投影</Text><Text fw={650} fz="sm" mt={4}>{entryId}</Text><Text c="dimmed" fz="xs" mt={3}>从当前源码草稿即时派生；临时试算只改变当前预览。</Text></Box>
          {[entryTargets.length > 0, hasChart, entryAnalyses.length > 0].filter(Boolean).length > 1 && <SegmentedControl fullWidth size="xs" value={mode} onChange={(value) => { modeWasChosen.current = true; setMode(value as "result" | "chart" | "process"); setResult(null); }} data={[...(entryTargets.length ? [{ value: "result", label: "结果" }] : []), ...(hasChart ? [{ value: "chart", label: "图表" }] : []), ...(entryAnalyses.length ? [{ value: "process", label: "过程" }] : [])]} />}
          {mode === "result" && entryTargets.length > 1 && <Select label="查看结果" searchable value={target} onChange={(value) => { setTarget(value); setResult(null); }} data={entryTargets.map((item) => ({ value: item.value, label: `${item.group_label ? `${item.group_label} / ` : ""}${item.label}` }))} />}
          {mode === "process" && entryAnalyses.length > 1 && <Select label="过程分析" searchable value={analysisTarget} onChange={(value) => { setAnalysisTarget(value); setResult(null); }} data={entryAnalyses.map((item) => ({ value: item.value, label: item.label }))} />}
          {mode === "result" && relevantInputs.length > 0 && <Box className="preview-inputs trial-panel">
            <Group justify="space-between" wrap="nowrap"><Box><Text className="result-label">临时试算</Text><Text c="dimmed" fz="xs" mt={3}>只存在于当前会话；不会写入源码。</Text></Box><Badge variant="outline" color="gray">非权威</Badge></Group>
            <div className="trial-input-list">
              {relevantInputs.map((input) => <div className="trial-input-row" key={input.value}>
                <span className="preview-input-identity"><strong>{input.label}</strong><small>{input.value}{input.unit && input.unit !== "dimensionless" ? ` · ${input.unit}` : ""}</small></span>
                <span className="trial-default"><small>源码默认值</small><Code>{String(input.default ?? "—")}</Code></span>
                <TextInput aria-label={`${input.label}临时试算值`} placeholder="保持默认" value={trialValues[input.value] ?? ""} onChange={(event) => {
                  const value = event.currentTarget.value;
                  setTrialValues((values) => ({ ...values, [input.value]: value }));
                }} />
              </div>)}
            </div>
            <Group justify="space-between" mt="sm"><Button variant="subtle" color="gray" size="xs" disabled={!hasTrial} onClick={() => setTrialValues({})}>重置</Button><Group gap={6}><Button variant="default" size="xs" disabled={!hasTrial || document.read_only} onClick={() => setPresetOpened(true)}>生成 preset 草稿</Button><Button variant="default" size="xs" disabled={controller.dirtyCount > 0} onClick={() => setRunOpened(true)}>保存运行记录</Button></Group></Group>
            {controller.dirtyCount > 0 && <Text c="dimmed" fz="xs" mt={6}>保存全部草稿后，才能创建引用持久源码的运行记录。</Text>}
          </Box>}
          {running && !result && <LoadingState label={mode === "chart" ? "正在生成图表…" : mode === "process" ? "正在搜索过程策略…" : "正在计算结果…"} />}
          {error && <Box className="inline-error compact"><Text fw={650}>投影未完成</Text><Text c="dimmed" fz="xs" mt={5}>{error}</Text></Box>}
          {result && mode === "result" && result.operation !== "compare" && <Stack gap="md" className={`document-result-preview${activeSymbolId === target ? " is-source-linked" : ""}`}><Box><Group justify="space-between" wrap="nowrap"><Text className="result-label">{selectedTarget?.label || target}</Text>{selectedTarget?.line && <Button variant="subtle" color="gray" size="compact-xs" leftSection={<Crosshair size={13} />} onClick={() => onNavigateToSource(document.key, selectedTarget.line, selectedTarget.column)}>定位结果源码</Button>}</Group><Text className="document-result-value">{displayedValue(result)}</Text><Group gap={6} mt="xs">{Boolean(result.unit) && <Badge variant="outline" color="gray">{String(result.unit)}</Badge>}<Code>{String(result.exact ?? "—")}</Code></Group></Box><TechnicalResult result={result} /></Stack>}
          {result && mode === "result" && result.operation === "compare" && <Stack gap="md" className={`document-result-preview${activeSymbolId === target ? " is-source-linked" : ""}`}>
            <Group justify="space-between" wrap="nowrap"><Text className="result-label">{selectedTarget?.label || target} · 默认值对照</Text>{selectedTarget?.line && <Button variant="subtle" color="gray" size="compact-xs" leftSection={<Crosshair size={13} />} onClick={() => onNavigateToSource(document.key, selectedTarget.line, selectedTarget.column)}>定位结果源码</Button>}</Group>
            <SimpleGrid cols={{ base: 1, sm: 2 }} spacing="sm">
              {comparisonRows.map((row, index) => {
                const rowResult = row.result && typeof row.result === "object" ? row.result as OperationResult : null;
                const rowError = row.error && typeof row.error === "object" ? row.error as Record<string, unknown> : null;
                return <Box className={`trial-result-card${index === 1 ? " is-current" : ""}`} key={String(row.name)}>
                  <Text c="dimmed" fz="xs">{String(row.name)}</Text>
                  {rowResult ? <><Text className="document-result-value">{displayedValue(rowResult)}</Text><Group gap={6} mt="xs">{Boolean(rowResult.unit) && <Badge variant="outline" color="gray">{String(rowResult.unit)}</Badge>}<Code>{String(rowResult.exact ?? "—")}</Code></Group>{index > 0 && <Group gap={6} mt="sm"><Badge variant="outline" color="gray">差值 {String(row.delta_exact ?? "—")}</Badge>{row.delta_percent !== null && row.delta_percent !== undefined && <Badge variant="outline" color="gray">{String(row.delta_percent)}%</Badge>}</Group>}</> : <Text c="red" fz="xs" mt="sm">{String(rowError?.message ?? "试算未完成")}</Text>}
                </Box>;
              })}
            </SimpleGrid>
            <TechnicalResult result={result} />
          </Stack>}
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
            {processCharts.length > 0 && <Box className="document-chart-preview">
              <Text className="result-label" mb="sm">分析图表 · {processCharts.length}</Text>
              <div className="preview-chart-grid">
                {processCharts.map((chartResult) => <section className="preview-chart-card" key={String(chartResult.id)}>
                  <Group className="preview-chart-card-header" justify="space-between" wrap="nowrap">
                    <Box><Text fw={650} fz="sm">{String(chartResult.label ?? chartResult.id)}</Text><Text c="dimmed" fz="xs">{String(chartResult.id)}</Text></Box>
                    <Group gap={4} wrap="nowrap"><Badge variant="outline" color="gray">{String(chartResult.kind ?? "—")}</Badge>{selectedAnalysis?.line && <Button aria-label="定位分析图表源码" variant="subtle" color="gray" size="compact-xs" leftSection={<Crosshair size={13} />} onClick={navigateToAnalysisSource}>源码</Button>}<Button aria-label="展开预览" variant="subtle" color="gray" size="compact-xs" leftSection={<Maximize2 size={13} />} onClick={() => setExpandedPreview({ kind: "process", chart: chartResult })}>展开</Button></Group>
                  </Group>
                  <DeferredChart label={`${String(chartResult.label ?? chartResult.id)}图表`}><ProcessChartCanvas chart={chartResult} onActivate={selectedAnalysis?.line ? navigateToAnalysisSource : undefined} /></DeferredChart>
                </section>)}
              </div>
            </Box>}
            <TechnicalResult result={result} />
          </Stack>}
          {result && mode === "chart" && <Stack gap="sm" className="document-chart-preview">
            <Group justify="space-between" wrap="nowrap"><Text className="result-label">静态图表 · {staticCharts.length}</Text>{staticCharts.length > 1 && <Button variant="default" size="xs" leftSection={<FileOutput size={13} />} loading={running} onClick={() => { void exportStaticCharts(); }}>导出全部图表</Button>}</Group>
            <div className="preview-chart-grid">
              {staticCharts.map((chartResult) => {
                const config = String(chartResult.config);
                const chartIndex = entryCharts.find((item) => item.value === config);
                return <section className="preview-chart-card" key={config}>
                  <Group className="preview-chart-card-header" justify="space-between" wrap="nowrap">
                    <Box><Text fw={650} fz="sm">{String(chartResult.label ?? config)}</Text><Text c="dimmed" fz="xs">{config}</Text></Box>
                    <Group gap={4} wrap="nowrap">
                      {chartIndex?.line && <Button aria-label="定位图表源码" variant="subtle" color="gray" size="compact-xs" leftSection={<Crosshair size={13} />} onClick={() => onNavigateToSource(document.key, chartIndex.line, chartIndex.column)}>源码</Button>}
                      <Button aria-label="展开预览" variant="subtle" color="gray" size="compact-xs" leftSection={<Maximize2 size={13} />} onClick={() => setExpandedPreview({ kind: "static", chart: chartResult })}>展开</Button>
                      <Button variant="subtle" color="gray" size="compact-xs" leftSection={<FileOutput size={13} />} onClick={() => { setExportChartConfig(config); setExportOpened(true); }}>导出</Button>
                    </Group>
                  </Group>
                  <DeferredChart label={`${String(chartResult.label ?? config)}图表`}><ChartCanvas result={chartResult as OperationResult} onSelectTarget={navigateToTargetSource} /></DeferredChart>
                  <Group className="preview-chart-card-meta" gap={6}><Badge variant="outline" color="gray">静态扫描</Badge><Badge variant="light" color="green">{Array.isArray(chartResult.rows) ? chartResult.rows.length : 0} 个采样点</Badge><Badge variant="outline" color="gray">{String(chartResult.x || "—")}</Badge></Group>
                </section>;
              })}
            </div>
            <TechnicalResult result={result} />
          </Stack>}
          {exportResult && <Box className="export-success"><Save size={16} /><span><strong>图表已导出</strong><small>{String(exportResult.out || "已使用文档声明的输出路径")}</small></span></Box>}
        </Stack>
      </ScrollArea>

      <Modal opened={exportOpened} onClose={() => setExportOpened(false)} title="导出当前图表" centered>
        <Stack><Text c="dimmed" fz="xs">路径留空时使用文档中声明的导出路径。</Text><TextInput label="图像路径" placeholder="使用文档定义" value={exportOut} onChange={(event) => setExportOut(event.currentTarget.value)} /><TextInput label="CSV 路径" placeholder="使用文档定义或不导出数据" value={exportDataOut} onChange={(event) => setExportDataOut(event.currentTarget.value)} /><SimpleGrid cols={2}><Checkbox label="覆盖已有文件" checked={force} onChange={(event) => setForce(event.currentTarget.checked)} /><Checkbox label="允许工作区外路径" checked={allowOutside} onChange={(event) => setAllowOutside(event.currentTarget.checked)} /></SimpleGrid><TextInput label="运行记录 ID" disabled={controller.dirtyCount > 0} description={controller.dirtyCount ? "请先保存全部草稿。" : "可选"} value={runId} onChange={(event) => setRunId(event.currentTarget.value)} /><Group justify="flex-end"><Button variant="default" onClick={() => setExportOpened(false)}>取消</Button><Button loading={running} onClick={() => { void exportChart(); }}>生成文件</Button></Group></Stack>
      </Modal>
      <Modal opened={presetOpened} onClose={() => setPresetOpened(false)} title="生成参数方案草稿" centered>
        <Stack><Text c="dimmed" fz="xs">这会把当前临时输入追加为普通 `.kirin` preset 草稿；不会自动保存。</Text><TextInput label="Preset ID" description="使用稳定的 ASCII 标识" value={presetId} onChange={(event) => setPresetId(event.currentTarget.value)} error={presetId.trim() && !currentPresetIdValid ? "ID 无效或已经存在" : undefined} /><TextInput label="显示名" value={presetLabel} onChange={(event) => setPresetLabel(event.currentTarget.value)} /><Box className="trial-preset-preview"><Code block>{Object.entries(trialOverrides).map(([name, value]) => `${name} = ${value}`).join("\n")}</Code></Box><Group justify="flex-end"><Button variant="default" onClick={() => setPresetOpened(false)}>取消</Button><Button variant="default" disabled={!currentPresetIdValid || !hasTrial} onClick={createPresetDraft}>生成草稿</Button></Group></Stack>
      </Modal>
      <Modal opened={runOpened} onClose={() => setRunOpened(false)} title="保存当前试算记录" centered>
        <Stack><Text c="dimmed" fz="xs">运行记录只引用已经保存的 `.kirin` 权威源码；临时输入会作为请求参数进入记录。</Text><TextInput label="运行记录 ID" description="仅限 ASCII 字母、数字、下划线和连字符" value={trialRunId} onChange={(event) => setTrialRunId(event.currentTarget.value)} error={trialRunId.trim() && !trialRunIdValid ? "运行记录 ID 无效" : undefined} /><Group justify="flex-end"><Button variant="default" onClick={() => setRunOpened(false)}>取消</Button><Button variant="default" loading={savingRun} disabled={!trialRunIdValid || controller.dirtyCount > 0} onClick={() => { void saveTrialRun(); }}>保存记录</Button></Group></Stack>
      </Modal>
      <Modal fullScreen opened={expandedPreview !== null} onClose={() => setExpandedPreview(null)} title={expandedPreview ? String(expandedPreview.chart.label ?? expandedPreview.chart.id ?? expandedPreview.chart.config ?? "展开图表预览") : "展开图表预览"}>
        {expandedPreview && <div className="expanded-chart-preview">{expandedPreview.kind === "static" ? <ChartCanvas result={expandedPreview.chart as OperationResult} onSelectTarget={navigateToTargetSource} /> : <ProcessChartCanvas chart={expandedPreview.chart} onActivate={selectedAnalysis?.line ? navigateToAnalysisSource : undefined} />}</div>}
      </Modal>
    </>
  );
}
