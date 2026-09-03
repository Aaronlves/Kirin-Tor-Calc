import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Badge,
  Box,
  Button,
  Code,
  Group,
  ScrollArea,
  SegmentedControl,
  Stack,
  Text,
  TextInput,
  Title,
} from "@mantine/core";
import { ExternalLink, Focus, Network, RefreshCw, Search } from "lucide-react";

import { errorMessage } from "../api";
import { RelationshipGraphCanvas } from "../components/RelationshipGraphCanvas";
import { EmptyState, LoadingState, PageIntro, Surface } from "../components/ui";
import type { WorkbenchController } from "../hooks/useWorkbench";
import type {
  RelationshipEdge,
  RelationshipGraphResult,
  RelationshipNode,
} from "../types";

type Granularity = "documents" | "members";

interface GraphViewProps {
  controller: WorkbenchController;
  onNavigate(path: string, line?: number | null, column?: number | null): void;
}

const kindLabels: Record<string, string> = {
  document: "文档",
  input: "输入",
  field: "字段",
  function: "函数",
  table: "查表",
  distribution: "有限分布",
  output: "输出",
  object: "类型化对象",
  process: "过程",
  scenario: "场景",
  analysis: "分析",
};

function documentNodes(graph: RelationshipGraphResult): RelationshipNode[] {
  return graph.documents.map((document) => ({
    id: document.id,
    label: document.label,
    kind: "document",
    document_id: document.id,
    path: document.path,
    read_only: document.read_only,
  }));
}

function filteredProjection(nodes: RelationshipNode[], edges: RelationshipEdge[], query: string) {
  const normalized = query.trim().toLocaleLowerCase();
  if (!normalized) return { nodes, edges };
  const matched = new Set(
    nodes
      .filter((node) => `${node.label} ${node.id} ${node.kind}`.toLocaleLowerCase().includes(normalized))
      .map((node) => node.id),
  );
  const visible = new Set(matched);
  for (const edge of edges) {
    if (matched.has(edge.source) || matched.has(edge.target)) {
      visible.add(edge.source);
      visible.add(edge.target);
    }
  }
  return {
    nodes: nodes.filter((node) => visible.has(node.id)),
    edges: edges.filter((edge) => visible.has(edge.source) && visible.has(edge.target)),
  };
}

function relatedNodes(
  selectedId: string,
  edges: RelationshipEdge[],
  nodes: RelationshipNode[],
  relation: "dependencies" | "users",
): RelationshipNode[] {
  const relatedIds = new Set(edges.flatMap((edge) => {
    if (relation === "dependencies" && edge.target === selectedId) return [edge.source];
    if (relation === "users" && edge.source === selectedId) return [edge.target];
    return [];
  }));
  return nodes.filter((node) => relatedIds.has(node.id));
}

export function GraphView({ controller, onNavigate }: GraphViewProps) {
  const [graph, setGraph] = useState<RelationshipGraphResult | null>(null);
  const [granularity, setGranularity] = useState<Granularity>("documents");
  const [query, setQuery] = useState("");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const result = await controller.operation("relationship_graph", { timeout: 15 }) as RelationshipGraphResult;
      setGraph(result);
    } catch (caught) {
      setError(errorMessage(caught));
    } finally {
      setLoading(false);
    }
  }, [controller.operation]);

  useEffect(() => { void load(); }, [load]);

  const baseNodes = useMemo(
    () => !graph ? [] : granularity === "documents" ? documentNodes(graph) : graph.nodes,
    [granularity, graph],
  );
  const baseEdges = useMemo(
    () => !graph ? [] : granularity === "documents" ? graph.document_edges : graph.edges,
    [granularity, graph],
  );
  const projection = useMemo(
    () => filteredProjection(baseNodes, baseEdges, query),
    [baseEdges, baseNodes, query],
  );
  const selected = projection.nodes.find((node) => node.id === selectedId) || null;
  const selectedDependencies = selected ? relatedNodes(selected.id, projection.edges, projection.nodes, "dependencies") : [];
  const selectedUsers = selected ? relatedNodes(selected.id, projection.edges, projection.nodes, "users") : [];

  useEffect(() => {
    if (!projection.nodes.length) {
      if (selectedId !== null) setSelectedId(null);
      return;
    }
    if (selectedId && projection.nodes.some((node) => node.id === selectedId)) return;
    const degree = new Map(projection.nodes.map((node) => [node.id, 0]));
    for (const edge of projection.edges) {
      degree.set(edge.source, (degree.get(edge.source) || 0) + 1);
      degree.set(edge.target, (degree.get(edge.target) || 0) + 1);
    }
    const next = [...projection.nodes].sort((left, right) => (
      (degree.get(right.id) || 0) - (degree.get(left.id) || 0)
      || left.label.localeCompare(right.label)
    ))[0];
    setSelectedId(next.id);
  }, [projection.edges, projection.nodes, selectedId]);

  if (loading && !graph) return <LoadingState label="正在从公式构建关系图…" />;

  return (
    <div className="content-page graph-page">
      <PageIntro
        kicker="SEMANTIC RELATIONSHIPS"
        title="关系图"
        description="边由已校验的表达式引用与 Process 组合生成；包含静态成员、过程、场景与分析。"
        actions={<Group gap="xs">
          <Badge variant="outline" color="gray">{graph?.documents.length || 0} 文档</Badge>
          <Badge variant="outline" color="gray">{graph?.nodes.length || 0} 成员</Badge>
          <Button variant="default" size="xs" leftSection={<RefreshCw size={14} />} loading={loading} onClick={() => { void load(); }}>刷新投影</Button>
        </Group>}
      />

      <div className="graph-layout">
        <Surface component="section" ariaLabel="关系图画布" className="graph-surface">
          <div className="graph-toolbar">
            <SegmentedControl
              size="xs"
              value={granularity}
              onChange={(value) => { setGranularity(value as Granularity); setSelectedId(null); }}
              data={[{ value: "documents", label: "文档关系" }, { value: "members", label: "公式成员" }]}
            />
            <TextInput
              size="xs"
              placeholder="搜索并聚焦邻接节点"
              leftSection={<Search size={14} />}
              value={query}
              onChange={(event) => setQuery(event.currentTarget.value)}
            />
          </div>
          {error ? (
            <EmptyState icon={<Network size={24} />} title="关系图无法生成" description={error} action={<Button size="xs" onClick={() => { void load(); }}>重试</Button>} />
          ) : projection.nodes.length ? (
            <RelationshipGraphCanvas
              nodes={projection.nodes}
              edges={projection.edges}
              layout={granularity === "documents" ? "circular" : "force"}
              selectedId={selectedId}
              onSelect={setSelectedId}
            />
          ) : (
            <EmptyState title="没有匹配的关系" description="清除搜索词，或先在文档中定义输入、公式和跨文档引用。" />
          )}
          <div className="graph-hint"><Focus size={13} />文档使用稳定环形布局；成员可拖动。也可展开键盘节点列表。</div>
        </Surface>

        <Surface component="section" ariaLabel="所选关系节点" className="graph-inspector">
          {selected ? (
            <ScrollArea h="100%" type="auto">
              <Stack p="lg" gap="lg">
                <Box>
                  <Text className="result-label">{kindLabels[selected.kind] || selected.kind}</Text>
                  <Title order={3} mt={4}>{selected.label}</Title>
                  <Code mt="xs" block>{selected.id}</Code>
                </Box>
                <Stack gap={8} className="graph-node-facts">
                  <span><small>所属文档</small><strong>{selected.document_id}</strong></span>
                  {selected.unit && <span><small>单位</small><strong>{selected.unit}</strong></span>}
                  {selected.line && <span><small>定义位置</small><strong>{selected.line}:{selected.column || 1}</strong></span>}
                </Stack>
                {selected.expression && (
                  <Box>
                    <Text className="result-label">直接公式</Text>
                    <Code block mt={7}>{selected.expression}</Code>
                  </Box>
                )}
                <Box>
                  <Text className="result-label">连接</Text>
                  <Text fz="xs" c="dimmed" mt={6}>
                    {selectedDependencies.length} 个直接依赖 · {selectedUsers.length} 个直接使用者
                  </Text>
                </Box>
                <Stack gap="md" className="graph-neighbor-groups">
                  <Box>
                    <Text className="result-label">直接依赖</Text>
                    <div className="graph-neighbor-list">
                      {selectedDependencies.map((node) => <button key={node.id} type="button" onClick={() => setSelectedId(node.id)}><strong>{node.label}</strong><small>{node.id}</small></button>)}
                      {!selectedDependencies.length && <Text c="dimmed" fz="xs">无</Text>}
                    </div>
                  </Box>
                  <Box>
                    <Text className="result-label">直接使用者</Text>
                    <div className="graph-neighbor-list">
                      {selectedUsers.map((node) => <button key={node.id} type="button" onClick={() => setSelectedId(node.id)}><strong>{node.label}</strong><small>{node.id}</small></button>)}
                      {!selectedUsers.length && <Text c="dimmed" fz="xs">无</Text>}
                    </div>
                  </Box>
                </Stack>
                <Button leftSection={<ExternalLink size={14} />} onClick={() => onNavigate(selected.path, selected.line, selected.column)}>在文档中打开</Button>
              </Stack>
            </ScrollArea>
          ) : (
            <EmptyState icon={<Network size={24} />} title="选择一个节点" description="节点详情会显示直接公式、定义位置和上下游连接。" />
          )}
        </Surface>
      </div>
    </div>
  );
}
