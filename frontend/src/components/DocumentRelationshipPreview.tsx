import { useCallback, useEffect, useMemo, useState } from "react";
import { Box, Button, Code, Group, SegmentedControl, Stack, Text } from "@mantine/core";
import { Crosshair, RefreshCw } from "lucide-react";

import { errorMessage } from "../api";
import type { WorkbenchController } from "../hooks/useWorkbench";
import type { RelationshipGraphResult, RelationshipNode } from "../types";
import { RelationshipGraphCanvas } from "./RelationshipGraphCanvas";
import { EmptyState, LoadingState } from "./ui";

interface DocumentRelationshipPreviewProps {
  controller: WorkbenchController;
  documentKey: string;
  source: string;
}

function entryId(source: string): string | null {
  return source.match(/^@entry\s+([A-Za-z_][A-Za-z0-9_]*)$/m)?.[1] ?? null;
}

function normalizedPath(path: string): string {
  return path.replace(/\\/g, "/");
}

function project(graph: RelationshipGraphResult, documentId: string, depth: number) {
  const visible = new Set(graph.nodes.filter((node) => node.document_id === documentId).map((node) => node.id));
  let frontier = new Set(visible);
  for (let index = 0; index < depth; index += 1) {
    const next = new Set<string>();
    for (const edge of graph.edges) {
      if (frontier.has(edge.source) && !visible.has(edge.target)) next.add(edge.target);
      if (frontier.has(edge.target) && !visible.has(edge.source)) next.add(edge.source);
    }
    for (const node of next) visible.add(node);
    frontier = next;
  }
  return {
    nodes: graph.nodes.filter((node) => visible.has(node.id)),
    edges: graph.edges.filter((edge) => visible.has(edge.source) && visible.has(edge.target)),
  };
}

export function DocumentRelationshipPreview({ controller, documentKey, source }: DocumentRelationshipPreviewProps) {
  const documentId = entryId(source);
  const [graph, setGraph] = useState<RelationshipGraphResult | null>(null);
  const [depth, setDepth] = useState("1");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setGraph(await controller.operation("relationship_graph", { timeout: 15 }) as RelationshipGraphResult);
    } catch (caught) {
      setError(errorMessage(caught));
    } finally {
      setLoading(false);
    }
  }, [controller.operation]);

  useEffect(() => { void load(); }, [documentKey, load]);
  const projection = useMemo(
    () => graph && documentId ? project(graph, documentId, Number(depth)) : { nodes: [], edges: [] },
    [depth, documentId, graph],
  );
  const selected: RelationshipNode | null = projection.nodes.find((node) => node.id === selectedId) || null;
  const selectedDocument = selected && graph?.documents.find((item) => item.id === selected.document_id);
  const selectedDocumentKey = selected
    ? controller.documents.find((item) => {
        if (item.read_only !== selected.read_only) return false;
        const selectedPath = normalizedPath(selected.path);
        const documentPath = normalizedPath(item.path);
        if (selectedPath !== documentPath && !selectedPath.endsWith(`/${documentPath}`)) return false;
        if (!selectedDocument?.package) return !item.package;
        return item.package?.name === selectedDocument.package.name
          && item.package.version === selectedDocument.package.version
          && item.package.source === selectedDocument.package.source;
      })?.key ?? (selected.document_id === documentId ? documentKey : null)
    : null;

  useEffect(() => {
    setSelectedId(null);
  }, [documentKey]);

  if (!documentId) return <EmptyState title="文档声明无效" description="修复 @entry 文档头后，局部关系投影会在这里出现。" />;
  if (loading && !graph) return <LoadingState label="正在构建当前文档关系…" />;
  if (error) return <EmptyState title="局部关系无法生成" description={error} action={<Button size="xs" onClick={() => { void load(); }}>重试</Button>} />;
  if (!projection.nodes.length) return <EmptyState title="当前文档没有公式成员" description="声明输入、字段、函数或输出后会生成局部关系。" />;

  return (
    <Stack h="100%" gap={0}>
      <Group className="local-graph-toolbar" justify="space-between" wrap="nowrap">
        <SegmentedControl
          size="xs"
          value={depth}
          onChange={setDepth}
          data={[{ value: "0", label: "仅本文" }, { value: "1", label: "直接" }, { value: "2", label: "两层" }]}
        />
        <Button variant="subtle" color="gray" size="compact-xs" px={7} onClick={() => { void load(); }} loading={loading}><RefreshCw size={13} /></Button>
      </Group>
      <Box className="local-graph-stage">
        <RelationshipGraphCanvas compact nodes={projection.nodes} edges={projection.edges} selectedId={selectedId} onSelect={setSelectedId} />
      </Box>
      {selected && (
        <button
          type="button"
          className="local-graph-selection"
          disabled={!selectedDocumentKey}
          onClick={() => {
            if (!selectedDocumentKey) return;
            window.dispatchEvent(new CustomEvent("kirin:navigate-source", { detail: { key: selectedDocumentKey, line: selected.line, column: selected.column } }));
          }}
        >
          <Crosshair size={14} />
          <span><strong>{selected.label}</strong><small>{selected.id}{selected.line ? ` · 第 ${selected.line} 行` : ""}</small></span>
          {selected.unit && <Code>{selected.unit}</Code>}
        </button>
      )}
      {!selected && <Text className="local-graph-help">箭头从依赖指向使用者。点击图中节点，或展开键盘节点列表。</Text>}
    </Stack>
  );
}
