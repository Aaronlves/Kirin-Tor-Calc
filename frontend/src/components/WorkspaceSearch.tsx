import { useState } from "react";
import { Badge, Box, Button, Checkbox, Group, ScrollArea, Stack, Text, TextInput } from "@mantine/core";
import { Replace, Search } from "lucide-react";

import { errorMessage } from "../api";
import type { WorkbenchController } from "../hooks/useWorkbench";
import type { WorkspaceSearchMatch } from "../types";

interface WorkspaceSearchProps {
  controller: WorkbenchController;
  onNavigate(path: string, line?: number, column?: number): void;
  onReviewChanges(): void;
}

export function WorkspaceSearch({ controller, onNavigate, onReviewChanges }: WorkspaceSearchProps) {
  const [query, setQuery] = useState("");
  const [replacement, setReplacement] = useState("");
  const [caseSensitive, setCaseSensitive] = useState(false);
  const [matches, setMatches] = useState<WorkspaceSearchMatch[]>([]);
  const [truncated, setTruncated] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [running, setRunning] = useState(false);

  const search = async () => {
    if (!query) return;
    setRunning(true);
    setError(null);
    try {
      const result = await controller.searchWorkspace(query, caseSensitive);
      setMatches(result.matches);
      setTruncated(result.truncated);
    } catch (searchError) {
      setError(errorMessage(searchError));
    } finally {
      setRunning(false);
    }
  };

  const replaceAll = async () => {
    if (!query) return;
    setRunning(true);
    setError(null);
    try {
      const result = await controller.replaceWorkspace(query, replacement, caseSensitive);
      if (result.edits) onReviewChanges();
      else await search();
    } catch (replaceError) {
      setError(errorMessage(replaceError));
    } finally {
      setRunning(false);
    }
  };

  return (
    <div className="workspace-search-tool">
      <Stack gap="md">
        <Box>
          <Text fw={680}>搜索整个工作区</Text>
          <Text c="dimmed" fz="xs" mt={3}>搜索会读取当前未保存草稿与 Package 源码；替换只生成本地文档草稿，不直接写盘。</Text>
        </Box>
        <Group align="flex-end" wrap="nowrap">
          <TextInput
            label="查找"
            aria-label="工作区查找"
            placeholder="输入纯文本"
            leftSection={<Search size={14} />}
            value={query}
            onChange={(event) => { setQuery(event.currentTarget.value); setMatches([]); setTruncated(false); }}
            onKeyDown={(event) => { if (event.key === "Enter") void search(); }}
            style={{ flex: 1 }}
          />
          <Button loading={running} disabled={!query} onClick={() => { void search(); }}>搜索</Button>
        </Group>
        <Group align="flex-end" wrap="nowrap">
          <TextInput
            label="替换为"
            aria-label="工作区替换文本"
            value={replacement}
            onChange={(event) => setReplacement(event.currentTarget.value)}
            style={{ flex: 1 }}
          />
          <Button
            variant="default"
            leftSection={<Replace size={14} />}
            loading={running}
            disabled={!query || !matches.some((item) => !item.read_only)}
            onClick={() => { void replaceAll(); }}
          >
            替换全部可写匹配
          </Button>
        </Group>
        <Checkbox
          label="区分大小写"
          checked={caseSensitive}
          onChange={(event) => { setCaseSensitive(event.currentTarget.checked); setMatches([]); setTruncated(false); }}
        />
        {error && <Text c="red" fz="sm">{error}</Text>}
        <Group justify="space-between">
          <Text className="nav-group-label">{matches.length} 个匹配{truncated ? "（已截断）" : ""}</Text>
          {matches.some((item) => item.read_only) && <Badge variant="light" color="gray">Package 结果只读</Badge>}
        </Group>
      </Stack>
      <ScrollArea className="workspace-search-results" type="auto">
        <div role="list" aria-label="工作区搜索结果">
          {matches.map((match, index) => (
            <button
              type="button"
              role="listitem"
              className="workspace-search-result"
              key={`${match.key}-${match.line}-${match.column}-${index}`}
              onClick={() => onNavigate(match.key, match.line, match.column)}
            >
              <Group justify="space-between" wrap="nowrap">
                <strong>{match.path}:{match.line}:{match.column}</strong>
                {match.read_only && <Badge size="xs" variant="outline" color="gray">只读</Badge>}
              </Group>
              <small>{match.preview}</small>
            </button>
          ))}
          {!matches.length && <Text c="dimmed" fz="sm" ta="center" py="xl">输入文本后搜索当前草稿、磁盘文档与 Package 源码。</Text>}
        </div>
      </ScrollArea>
    </div>
  );
}
