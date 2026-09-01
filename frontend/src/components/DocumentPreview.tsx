import { useEffect, useMemo, useRef, useState } from "react";
import { Badge, Box, Button, Checkbox, Code, Group, Modal, ScrollArea, SegmentedControl, Select, SimpleGrid, Stack, Text, Textarea, TextInput } from "@mantine/core";
import { FileOutput, Maximize2, Play, Save } from "lucide-react";

import { errorMessage } from "../api";
import type { WorkbenchController } from "../hooks/useWorkbench";
import type { DocumentItem, OperationResult } from "../types";
import { ChartCanvas } from "./ChartCanvas";
import { EmptyState, TechnicalResult } from "./ui";

function documentId(source: string): string | null {
  return source.match(/^@entry\s+([A-Za-z_][A-Za-z0-9_]*)$/m)?.[1] ?? null;
}

function displayedValue(result: OperationResult): string {
  for (const key of ["formatted", "approximate", "exact"]) {
    const value = result[key];
    if (value !== null && value !== undefined && value !== "") return String(value);
  }
  return "—";
}

export function DocumentPreview({ controller, document, source }: { controller: WorkbenchController; document: DocumentItem; source: string }) {
  const entryId = documentId(source);
  const entryTargets = useMemo(() => entryId ? controller.workspaceIndex.targets.filter((target) => target.value.startsWith(`${entryId}.`)) : [], [controller.workspaceIndex.targets, entryId]);
  const entryTargetSignature = entryTargets.map((item) => item.value).join("\u0000");
  const hasChart = Boolean(entryId && controller.workspaceIndex.charts.some((item) => item.value === entryId));
  const [mode, setMode] = useState<"result" | "chart">("result");
  const [target, setTarget] = useState<string | null>(entryTargets[0]?.value ?? null);
  const [preset, setPreset] = useState<string | null>(null);
  const [overrides, setOverrides] = useState("");
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
    setMode(entryTargets.length ? "result" : "chart");
    setPreset(null);
    setOverrides("");
    setResult(null);
    setError(null);
    setExportResult(null);
    setExpandedPreviewOpened(false);
  }, [document.key]);

  useEffect(() => {
    setTarget((selected) => entryTargets.some((item) => item.value === selected) ? selected : entryTargets[0]?.value ?? null);
    setMode((selected) => {
      if (!modeWasChosen.current) {
        if (entryTargets.length) return "result";
        if (hasChart) return "chart";
      }
      if (selected === "chart" && !hasChart && entryTargets.length) return "result";
      if (selected === "result" && !entryTargets.length && hasChart) return "chart";
      return selected;
    });
  }, [entryTargetSignature, hasChart]);

  useEffect(() => {
    setResult(null);
    setError(null);
    setExportResult(null);
  }, [source]);

  const selectedTarget = entryTargets.find((item) => item.value === target);
  const relevantInputs = controller.workspaceIndex.inputs.filter((input) => selectedTarget?.inputs?.includes(input.value));
  const presetOptions = controller.workspaceIndex.presets.map((item) => ({ value: item.value, label: item.label }));

  const preview = async () => {
    if (!entryId) return;
    setRunning(true);
    setError(null);
    try {
      setResult(mode === "chart"
        ? await controller.operation("preview_plot", { config: entryId, preset: preset || null, overrides, precision: 30, display_digits: 12, timeout: 10 })
        : await controller.operation("eval", { target, preset: preset || null, overrides, precision: 30, display_digits: 12, timeout: 10 }));
    } catch (caught) {
      setError(errorMessage(caught));
      setResult(null);
    } finally {
      setRunning(false);
    }
  };

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

  if (!entryId) return <EmptyState title="文档声明无效" description="修复 @entry 文档头后，结果和图表投影会在这里出现。" />;
  if (!entryTargets.length && !hasChart) return <EmptyState title="这个文档没有可预览投影" description="定义 outputs 可显示结果；再定义 x/range/points/y 即可显示图表。" />;

  return (
    <>
      <ScrollArea h="100%" type="auto">
        <Stack p="md" gap="md">
          <Box><Text className="result-label">DOCUMENT PROJECTION</Text><Text fw={650} fz="sm" mt={4}>{entryId}</Text><Text c="dimmed" fz="xs" mt={3}>从当前源码草稿即时派生，不会写回临时参数。</Text></Box>
          {entryTargets.length > 0 && hasChart && <SegmentedControl fullWidth size="xs" value={mode} onChange={(value) => { modeWasChosen.current = true; setMode(value as "result" | "chart"); setResult(null); }} data={[{ value: "result", label: "结果" }, { value: "chart", label: "图表" }]} />}
          {mode === "result" && entryTargets.length > 0 && <Select label="结果输出" searchable value={target} onChange={(value) => { setTarget(value); setResult(null); }} data={entryTargets.map((item) => ({ value: item.value, label: `${item.group_label ? `${item.group_label} / ` : ""}${item.label}` }))} />}
          <Select label="参数方案" clearable searchable placeholder="源码默认值" value={preset} onChange={(value) => { setPreset(value); setResult(null); setError(null); }} data={presetOptions} />
          <Textarea label="临时参数" description="只覆盖本次投影，不构成文档权威。" placeholder={"暴击率=25%\n天赋=true"} autosize minRows={3} maxRows={7} value={overrides} onChange={(event) => { setOverrides(event.currentTarget.value); setResult(null); setError(null); }} />
          {mode === "result" && relevantInputs.length > 0 && <Box className="preview-inputs"><Text className="result-label">相关输入</Text>{relevantInputs.map((input) => <Group key={input.value} justify="space-between" wrap="nowrap" mt={7}><span><strong>{input.label}</strong><small>{input.value}</small></span><Code>{String(input.default ?? "—")}</Code></Group>)}</Box>}
          <Group grow><Button leftSection={<Play size={14} />} loading={running} disabled={mode === "result" && !target} onClick={() => { void preview(); }}>{mode === "chart" ? "生成图表" : "计算结果"}</Button>{mode === "chart" && <Button variant="default" leftSection={<FileOutput size={14} />} onClick={() => setExportOpened(true)}>导出</Button>}</Group>
          {error && <Box className="inline-error compact"><Text fw={650}>投影未完成</Text><Text c="dimmed" fz="xs" mt={5}>{error}</Text></Box>}
          {result && mode === "result" && <Stack gap="md" className="document-result-preview"><Box><Text className="result-label">{selectedTarget?.label || target}</Text><Text className="document-result-value">{displayedValue(result)}</Text><Group gap={6} mt="xs">{Boolean(result.unit) && <Badge variant="outline" color="gray">{String(result.unit)}</Badge>}<Code>{String(result.exact ?? "—")}</Code></Group></Box><TechnicalResult result={result} /></Stack>}
          {result && mode === "chart" && <Stack gap="sm" className="document-chart-preview"><Group justify="space-between"><Text className="result-label">图表预览</Text><Button variant="default" size="xs" leftSection={<Maximize2 size={13} />} onClick={() => setExpandedPreviewOpened(true)}>展开预览</Button></Group><ChartCanvas result={result} /><Group gap={6}><Badge variant="light" color="green">{Array.isArray(result.rows) ? result.rows.length : 0} 个采样点</Badge><Badge variant="outline" color="gray">{String(result.x || "—")}</Badge></Group><TechnicalResult result={result} /></Stack>}
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
