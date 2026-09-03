import { useMemo, useState } from "react";
import {
  Badge,
  Box,
  Button,
  Checkbox,
  Code,
  Group,
  ScrollArea,
  Stack,
  Text,
  TextInput,
  Title,
} from "@mantine/core";
import { Check, History, Play, RefreshCw, RotateCcw, Search, X } from "lucide-react";

import { errorMessage } from "../api";
import type { WorkbenchController } from "../hooks/useWorkbench";
import type { OperationResult } from "../types";
import { Disclosure, EmptyState, PageIntro, Surface, TechnicalResult } from "../components/ui";

export function RunsView({ controller }: { controller: WorkbenchController }) {
  const [filter, setFilter] = useState("");
  const [selectedId, setSelectedId] = useState<string | null>(controller.bootstrapData?.runs[0]?.id ?? null);
  const [regenerate, setRegenerate] = useState(false);
  const [out, setOut] = useState("");
  const [dataOut, setDataOut] = useState("");
  const [force, setForce] = useState(false);
  const [allowOutside, setAllowOutside] = useState(false);
  const [optionsOpened, setOptionsOpened] = useState(false);
  const [replaying, setReplaying] = useState(false);
  const [result, setResult] = useState<OperationResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  const runs = controller.bootstrapData?.runs ?? [];
  const filteredRuns = useMemo(() => {
    const query = filter.trim().toLocaleLowerCase();
    return runs.filter((run) => !query || `${run.id} ${run.operation} ${run.status}`.toLocaleLowerCase().includes(query));
  }, [filter, runs]);
  const selected = runs.find((run) => run.id === selectedId);

  const replay = async () => {
    if (!selectedId) return;
    setReplaying(true);
    setError(null);
    try {
      setResult(await controller.operation("replay", {
        run_id: selectedId,
        regenerate_artifacts: regenerate,
        out: out || null,
        data_out: dataOut || null,
        force,
        allow_outside_workspace: allowOutside,
      }));
    } catch (caught) {
      setError(errorMessage(caught));
    } finally {
      setReplaying(false);
    }
  };

  return (
    <div className="content-page runs-page">
      <PageIntro
        kicker="运行与证据"
        title="记录与重放"
        description="记录保存请求、结果与定义快照；重放会明确报告是否与原结果一致。"
        headingOrder={3}
        actions={<Button variant="default" size="xs" leftSection={<RefreshCw size={14} />} loading={controller.asyncState === "connecting"} onClick={() => { void controller.refresh(true); }}>刷新</Button>}
      />
      <div className="runs-layout-modern">
        <Surface component="section" ariaLabel="运行记录列表" className="runs-list-surface">
          <Box p="sm" className="surface-toolbar"><TextInput size="xs" placeholder="搜索记录" leftSection={<Search size={14} />} value={filter} onChange={(event) => setFilter(event.currentTarget.value)} /></Box>
          <ScrollArea h="calc(100vh - var(--kt-sz-236))" type="auto">
            {filteredRuns.map((run) => (
              <button
                className={`run-row${selectedId === run.id ? " is-active" : ""}`}
                key={run.id}
                type="button"
                onClick={() => { setSelectedId(run.id); setResult(null); setError(null); }}
              >
                <span className="run-icon"><History size={15} /></span>
                <span><strong>{run.id}</strong><small>{run.operation || "未知操作"} · {run.created_at ? new Date(run.created_at).toLocaleString() : "时间未知"}</small></span>
                <Badge size="xs" variant="light" color={run.status === "error" ? "red" : "gray"}>{run.status || "—"}</Badge>
              </button>
            ))}
            {!filteredRuns.length && <EmptyState title="没有运行记录" description={filter ? "没有匹配当前搜索词的记录。" : "在计算、图表或数学操作中填写运行记录 ID 后，会在这里出现。"} />}
          </ScrollArea>
        </Surface>

        <Surface component="section" ariaLabel="运行记录详情" className="run-detail-surface">
          {selected ? (
            <ScrollArea h="calc(100vh - var(--kt-sz-178))" type="auto">
              <Stack p="xl" gap="xl">
                <Group justify="space-between" align="flex-start">
                  <Box><Text className="result-label">RUN RECORD</Text><Title order={4}>{selected.id}</Title><Group gap={6} mt={8}><Badge variant="outline" color="gray">{selected.operation || "未知操作"}</Badge><Badge variant="light" color={selected.status === "error" ? "red" : "green"}>{selected.status || "—"}</Badge></Group></Box>
                  <Button leftSection={<Play size={14} />} loading={replaying} onClick={() => { void replay(); }}>重放</Button>
                </Group>
                <Box className="run-metadata"><span><small>创建时间</small><strong>{selected.created_at ? new Date(selected.created_at).toLocaleString() : "—"}</strong></span><span><small>记录 ID</small><Code>{selected.id}</Code></span></Box>
                <Disclosure label="重新生成文件与输出路径" opened={optionsOpened} onToggle={() => setOptionsOpened((value) => !value)}>
                  <Stack gap="sm">
                    <Checkbox checked={regenerate} onChange={(event) => setRegenerate(event.currentTarget.checked)} label="重新生成图表或网格文件" />
                    <TextInput label="图像/主输出路径" placeholder="可选" value={out} onChange={(event) => setOut(event.currentTarget.value)} />
                    <TextInput label="数据输出路径" placeholder="可选" value={dataOut} onChange={(event) => setDataOut(event.currentTarget.value)} />
                    <Group><Checkbox checked={force} onChange={(event) => setForce(event.currentTarget.checked)} label="覆盖已有文件" /><Checkbox checked={allowOutside} onChange={(event) => setAllowOutside(event.currentTarget.checked)} label="允许工作区外路径" /></Group>
                  </Stack>
                </Disclosure>
                {error && <Box className="inline-error"><Text fw={650}>重放未完成</Text><Text c="dimmed" fz="sm" mt={6}>{error}</Text></Box>}
                {result && (
                  <Stack gap="lg">
                    <Box className={`replay-verdict${result.matches_recorded_result === false ? " is-mismatch" : ""}`}>
                      {result.matches_recorded_result === false ? <X size={21} /> : <Check size={21} />}
                      <span><strong>{result.matches_recorded_result === false ? "结果与记录不一致" : "结果与记录一致"}</strong><small>{result.matches_recorded_result === false ? "请检查依赖、源码或计算环境变化。" : "当前环境成功复现了这次运行。"}</small></span>
                    </Box>
                    <TechnicalResult result={result} />
                  </Stack>
                )}
              </Stack>
            </ScrollArea>
          ) : (
            <EmptyState icon={<RotateCcw size={24} />} title="选择一条记录" description="选择左侧运行记录，检查元数据并执行重放。" />
          )}
        </Surface>
      </div>
    </div>
  );
}
