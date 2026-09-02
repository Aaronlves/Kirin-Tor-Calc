import { useEffect, useRef, useState } from "react";
import { Alert, Badge, Box, Button, Code, Group, SimpleGrid, Stack, Text, TextInput } from "@mantine/core";
import { ExternalLink, GitFork, RefreshCw, Search, ShieldAlert, Star } from "lucide-react";

import { errorMessage, request } from "../api";
import type { CommunityDiscoveryCandidate, CommunityDiscoveryResult } from "../types";
import { EmptyState, Surface } from "./ui";

type DiscoveryKind = "plugin" | "package";

function endpointFor(kind: DiscoveryKind): string {
  return kind === "plugin" ? "/api/plugin" : "/api/package";
}

function compatibilityFacts(item: CommunityDiscoveryCandidate): string[] {
  if (item.kind === "plugin") {
    return [item.id ?? "", `Plugin API ${item.api ?? "?"}`].filter(Boolean);
  }
  return [item.namespace ? `namespace ${item.namespace}` : "", item.requires_kirin ? `Kirin Tor ${item.requires_kirin}` : ""].filter(Boolean);
}

function CandidateCard({ item }: { item: CommunityDiscoveryCandidate }) {
  return (
    <Surface>
      <Stack gap="sm" h="100%">
        <Group justify="space-between" align="flex-start" wrap="nowrap">
          <Box>
            <Text fw={700} fz="sm">{item.name}</Text>
            <Text c="dimmed" fz="xs" mt={3}>{item.repository}</Text>
          </Box>
          <Code>{item.version}</Code>
        </Group>
        <Text fz="sm" c="dimmed" lineClamp={3}>{item.description}</Text>
        <Group gap={5}>
          <Badge size="xs" variant="light" color="orange">topic 自声明</Badge>
          <Badge size="xs" variant="light" color="teal">manifest 兼容</Badge>
          <Badge size="xs" variant="outline" color="gray">未审核</Badge>
        </Group>
        <Stack gap={4}>
          {compatibilityFacts(item).map((fact) => <Text key={fact} fz="xs"><Code>{fact}</Code></Text>)}
          {item.game && <Text fz="xs" c="dimmed">游戏：{item.game}{item.game_version ? ` · ${item.game_version}` : ""}</Text>}
          <Text fz="xs" c="dimmed">manifest blob：<Code>{item.manifest_sha.slice(0, 12)}…</Code></Text>
        </Stack>
        <Group gap="md" c="dimmed">
          <Group gap={4}><Star size={13} /><Text fz="xs">{item.stars}</Text></Group>
          <Group gap={4}><GitFork size={13} /><Text fz="xs">{item.forks}</Text></Group>
          {item.updated_at && <Text fz="xs">更新 {new Date(item.updated_at).toLocaleDateString()}</Text>}
        </Group>
        <Button
          component="a"
          href={item.repository_url}
          target="_blank"
          rel="noreferrer"
          variant="default"
          size="xs"
          mt="auto"
          leftSection={<ExternalLink size={13} />}
        >在 GitHub 查看</Button>
      </Stack>
    </Surface>
  );
}

export function CommunityDiscoveryPanel({ kind }: { kind: DiscoveryKind }) {
  const [query, setQuery] = useState("");
  const [activeQuery, setActiveQuery] = useState("");
  const [result, setResult] = useState<CommunityDiscoveryResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [failure, setFailure] = useState<string | null>(null);
  const started = useRef(false);

  const load = async (page: number, selectedQuery: string) => {
    setLoading(true);
    setFailure(null);
    try {
      const response = await request<CommunityDiscoveryResult>(endpointFor(kind), {
        action: "discover",
        payload: { query: selectedQuery, page },
      });
      setResult(response);
      setActiveQuery(selectedQuery);
    } catch (error) {
      setFailure(errorMessage(error));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (started.current) return;
    started.current = true;
    void load(1, "");
  }, []);

  const title = kind === "plugin" ? "社区 Workbench Plugins" : "社区 Packages";

  return (
    <Stack gap="lg">
      <Box>
        <Text fw={700}>{title}</Text>
        <Text c="dimmed" fz="xs" mt={4}>
          GitHub topic 只生成候选；这里只读取并检查 manifest，不会下载、安装、批准或启用任何内容。
        </Text>
      </Box>
      <Group align="flex-end" wrap="nowrap">
        <TextInput
          label="搜索公开仓库"
          description="匹配 GitHub 仓库名称或说明；topic 固定，不能由搜索词替换。"
          placeholder={kind === "plugin" ? "renderer" : "warcraft"}
          value={query}
          onChange={(event) => setQuery(event.currentTarget.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter" && !loading) void load(1, query.trim());
          }}
          style={{ flex: 1 }}
        />
        <Button leftSection={<Search size={14} />} loading={loading} onClick={() => { void load(1, query.trim()); }}>搜索</Button>
      </Group>

      {failure && <Alert color="red" icon={<ShieldAlert size={17} />} title="无法读取社区发现结果">{failure}</Alert>}

      {result && <>
        <Group justify="space-between" align="flex-start">
          <Box>
            <Group gap="xs"><Badge variant="outline">{result.topic}</Badge><Text fz="xs" c="dimmed">第 {result.page} 页</Text></Group>
            <Text fz="xs" c="dimmed" mt={6}>
              本页检查 {result.inspected_repositories} 个 topic 仓库；显示 {result.items.length} 个当前协议兼容项。
              {result.skipped_repositories > 0 ? ` ${result.skipped_repositories} 个缺少、无效或不兼容的 manifest 未显示。` : ""}
            </Text>
          </Box>
          <Button variant="subtle" size="xs" leftSection={<RefreshCw size={13} />} loading={loading} onClick={() => { void load(result.page, activeQuery); }}>刷新本页</Button>
        </Group>

        {result.items.length > 0 ? (
          <SimpleGrid cols={{ base: 1, lg: 2 }}>
            {result.items.map((item) => <CandidateCard key={`${item.source}:${item.manifest_sha}`} item={item} />)}
          </SimpleGrid>
        ) : (
          <EmptyState
            icon={<Search size={22} />}
            title="没有发现兼容项目"
            description="可能还没有仓库使用这个 topic，也可能候选仓库的 manifest 不符合当前协议。"
          />
        )}

        <Group justify="space-between">
          <Button variant="default" size="xs" disabled={!result.has_previous || loading} onClick={() => { void load(result.page - 1, activeQuery); }}>上一页</Button>
          <Text fz="xs" c="dimmed">{result.notice}</Text>
          <Button variant="default" size="xs" disabled={!result.has_next || loading} onClick={() => { void load(result.page + 1, activeQuery); }}>下一页</Button>
        </Group>
      </>}
    </Stack>
  );
}
