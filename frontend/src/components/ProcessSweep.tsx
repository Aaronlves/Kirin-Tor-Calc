import { useEffect, useRef, useState } from "react";
import { Badge, Box, Button, Checkbox, Code, Group, Pagination, ScrollArea, Select, Stack, Table, Text, TextInput } from "@mantine/core";
import type { OperationResult } from "../types";
import type { WorkbenchController } from "../hooks/useWorkbench";
import { errorMessage } from "../api";
import { ProcessChartCanvas } from "./ProcessChartCanvas";

type Axis = { input: string; line: number; start: string; end: string; step: string };
type Family = { id: string; policy: string; enabled: boolean; line: number; axes: Axis[] };
export type SweepDefinition = { case_count: number; maximum_cases: string; maximum_cases_line: number; families: Family[]; policies: string[] };
type Value = { exact: unknown; formatted: string; approximate?: number };
type Case = { id: string; policy: string; rank: number | null; inputs: Record<string, string>; measures: Record<string, Value>; deltas: Record<string, Value>; error: { message: string } | null };

export function SweepControls({ definition, source, readOnly, onChange }: {
  definition: SweepDefinition; source: string; readOnly: boolean; onChange(source: string): void;
}) {
  const [draft, setDraft] = useState(definition);
  const definitionSignature = JSON.stringify(definition);
  // Background index refreshes recreate the projection without changing source.
  // Preserve pending edits unless the declaration itself actually changes.
  useEffect(() => setDraft(definition), [definitionSignature]);
  const update = (index: number, values: Partial<Family>) => setDraft((old) => ({ ...old, families: old.families.map((f, i) => i === index ? { ...f, ...values } : f) }));
  const apply = () => {
    const lines = source.split("\n");
    const changes: { start: number; end: number; text: string[] }[] = [];
    const replaceLine = (index: number, text: string) => {
      const comment = lines[index].match(/\s+\/\/.*$/)?.[0] ?? "";
      changes.push({ start: index, end: index + 1, text: [text + comment] });
    };
    draft.families.forEach((family, familyIndex) => {
      const original = definition.families[familyIndex];
      const start = family.line - 1;
      let end = start + 1;
      while (end < lines.length && (!lines[end].trim() || /^ {3,}\S/.test(lines[end]))) end += 1;
      if (family.enabled !== original.enabled) {
        const existing = lines.findIndex((line, i) => i > start && i < end && /^\s+enabled\s*=/.test(line));
        if (existing >= 0) replaceLine(existing, `    enabled = ${family.enabled}`);
        else changes.push({ start: start + 1, end: start + 1, text: [`    enabled = ${family.enabled}`] });
      }
      if (family.policy !== original.policy) {
        const existing = lines.findIndex((line, i) => i > start && i < end && /^\s+policy\s*=/.test(line));
        if (existing >= 0) replaceLine(existing, `    policy = ${family.policy}`);
      }
      family.axes.forEach((axis, axisIndex) => {
        if (JSON.stringify(axis) !== JSON.stringify(original.axes[axisIndex])) replaceLine(axis.line - 1,
          `    vary ${axis.input} from ${axis.start.trim()} to ${axis.end.trim()} step ${axis.step.trim()}`);
      });
    });
    if (draft.maximum_cases !== definition.maximum_cases) replaceLine(draft.maximum_cases_line - 1, `  maximum_cases = ${draft.maximum_cases.trim()}`);
    changes.sort((a, b) => b.start - a.start || b.end - a.end).forEach((change) => lines.splice(change.start, change.end - change.start, ...change.text));
    onChange(lines.join("\n"));
  };
  return <details><summary>调整策略与扫描范围 · 当前 {definition.case_count} 个候选</summary><Stack gap="sm" mt="sm">
    <Text c="dimmed" fz="xs">应用后修改源码草稿；保存全部后可创建运行记录。排序指标在分析声明中设置。</Text>
    <TextInput label="最多计算候选数" value={draft.maximum_cases} disabled={readOnly} onChange={(e) => setDraft({ ...draft, maximum_cases: e.currentTarget.value })} />
    {draft.families.map((family, index) => <Box key={family.id} className="preview-inputs">
      <Group justify="space-between"><Checkbox label={family.id} checked={family.enabled} disabled={readOnly} onChange={(e) => update(index, { enabled: e.currentTarget.checked })} /><Select aria-label={`${family.id}策略`} data={definition.policies} value={family.policy} disabled={readOnly} onChange={(value) => value && update(index, { policy: value })} /></Group>
      {family.axes.map((axis, axisIndex) => <Box key={axis.input} mt="sm"><Text fz="xs">{axis.input}</Text><Group grow align="end">
        {(["start", "end", "step"] as const).map((field) => <TextInput key={field} label={{ start: "起点", end: "终点", step: "步长" }[field]} aria-label={`${family.id} ${axis.input} ${field}`} value={axis[field]} disabled={readOnly} onChange={(e) => {
          const value = e.currentTarget.value;
          update(index, { axes: family.axes.map((a, i) => i === axisIndex ? { ...a, [field]: value } : a) });
        }} />)}
      </Group></Box>)}
    </Box>)}
    <Button variant="default" disabled={readOnly || JSON.stringify(draft) === JSON.stringify(definition)} onClick={apply}>应用到源码草稿</Button>
  </Stack></details>;
}

export function SweepResults({ result, target, controller }: { result: OperationResult; target: string; controller: WorkbenchController }) {
  const rows = result.cases as Case[];
  const ranking = result.ranking as { measure: string; label: string; direction: string }[];
  const [page, setPage] = useState(1);
  const [selected, setSelected] = useState<Case | null>(null);
  const [trace, setTrace] = useState<OperationResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const request = useRef(0);
  useEffect(() => () => { request.current += 1; }, []);
  const inspect = async (row: Case) => {
    const sequence = ++request.current;
    setSelected(row); setTrace(null); setError(null); setLoading(true);
    try {
      const next = await controller.operation("process_analysis", { target, case_id: row.id, include_trace: false, timeout: 3600 });
      if (sequence === request.current) setTrace(next);
    } catch (caught) {
      if (sequence === request.current) setError(errorMessage(caught));
    } finally {
      if (sequence === request.current) setLoading(false);
    }
  };
  return <Stack gap="sm">
    <Text fw={650}>指定策略与网格范围内的比较</Text>
    <Text c="dimmed" fz="xs">完成 {String(result.completed_cases)}/{String(result.planned_cases)}；失败 {String(result.failed_cases)}。布尔指标按全部路径成立判断，数值按精确期望排序。排名不是任意策略的全局最优证明。</Text>
    <Text c="dimmed" fz="xs">显示值相同不代表精确相等；极小差值也不代表显著策略优势。可展开候选查看精确值。</Text>
    {!result.ranking_complete && <Text c="red" fz="sm">有案例失败，当前排名仅覆盖成功项。</Text>}
    <ScrollArea type="auto"><Table striped highlightOnHover><Table.Thead><Table.Tr>
      <Table.Th>排名</Table.Th><Table.Th>候选 / 参数</Table.Th>{ranking.map((term) => <Table.Th key={term.measure}>{term.label} · {term.direction === "maximize" ? "高优先" : "低优先"}</Table.Th>)}<Table.Th>轨迹</Table.Th>
    </Table.Tr></Table.Thead><Table.Tbody>{rows.slice((page - 1) * 20, page * 20).map((row) => <Table.Tr key={row.id}>
      <Table.Td>{row.rank ?? "失败"}</Table.Td><Table.Td><Text fz="sm">{row.id} · {row.policy}</Text><Text c="dimmed" fz="xs">{Object.entries(row.inputs).map(([name, value]) => `${name}=${value}`).join("；")}</Text>{row.error && <Text c="red" fz="xs">{row.error.message}</Text>}</Table.Td>
      {ranking.map((term) => <Table.Td key={term.measure}><Text fz="sm">{row.measures[term.measure]?.formatted ?? "—"}</Text>{row.deltas[term.measure] && <Text c="dimmed" fz="xs">相对首项 {row.deltas[term.measure].formatted}</Text>}</Table.Td>)}
      <Table.Td><Button size="compact-xs" variant="subtle" disabled={Boolean(row.error)} onClick={() => { void inspect(row); }}>查看 {row.id}</Button></Table.Td>
    </Table.Tr>)}</Table.Tbody></Table></ScrollArea>
    <Pagination total={Math.max(1, Math.ceil(rows.length / 20))} value={page} onChange={setPage} size="sm" />
    {selected && <Stack gap="sm"><Group><Text fw={650}>候选 {selected.id}</Text><Badge variant="outline">单独重放</Badge></Group>
      <details><summary>查看精确指标与差值</summary>{ranking.map((term) => <Box key={term.measure}><Text fz="xs">{term.label}</Text><Code block>{String(selected.measures[term.measure]?.exact ?? "—")}</Code><Text fz="xs">相对首项精确差值</Text><Code block>{String(selected.deltas[term.measure]?.exact ?? "—")}</Code></Box>)}</details>
      {loading && <Text c="dimmed">正在重放此候选…</Text>}{error && <Text c="red">{error}</Text>}
      {trace && (Array.isArray(trace.charts) ? trace.charts as Record<string, unknown>[] : []).map((chart) => <Box key={String(chart.id)}><Text fw={650}>{String(chart.label ?? chart.id)}</Text><ProcessChartCanvas chart={chart} /></Box>)}
      {trace && !Array.isArray(trace.charts) && <Text c="dimmed">在此 Analysis 中声明 trajectory 图表即可查看轨迹。</Text>}
    </Stack>}
  </Stack>;
}
