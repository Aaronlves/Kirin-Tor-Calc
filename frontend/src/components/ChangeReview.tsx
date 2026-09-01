import { useEffect, useMemo, useState } from "react";
import { Badge, Box, Button, Code, Group, ScrollArea, Select, Stack, Tabs, Text } from "@mantine/core";
import { GitCommitHorizontal, Save } from "lucide-react";

import { errorMessage } from "../api";
import type { WorkbenchController } from "../hooks/useWorkbench";
import type { GitSummary } from "../types";

interface ChangeReviewProps {
  controller: WorkbenchController;
  onNavigate(path: string, line?: number, column?: number): void;
}

export function ChangeReview({ controller, onNavigate }: ChangeReviewProps) {
  const dirtyKeys = useMemo(() => Object.keys(controller.dirtyOverlays), [controller.dirtyOverlays]);
  const [selectedKey, setSelectedKey] = useState<string | null>(dirtyKeys[0] ?? null);
  const [git, setGit] = useState<GitSummary | null>(null);
  const [gitError, setGitError] = useState<string | null>(null);

  useEffect(() => {
    if (!selectedKey || !dirtyKeys.includes(selectedKey)) setSelectedKey(dirtyKeys[0] ?? null);
  }, [dirtyKeys, selectedKey]);

  useEffect(() => {
    let active = true;
    void controller.gitHistory().then((result) => { if (active) setGit(result); }).catch((error) => {
      if (active) setGitError(errorMessage(error));
    });
    return () => { active = false; };
  }, [controller.gitHistory]);

  const selectedDocument = controller.documents.find((item) => item.key === selectedKey);
  return (
    <div className="change-review-tool">
      <Group justify="space-between" align="flex-start">
        <Box>
          <Text fw={680}>保存前审查</Text>
          <Text c="dimmed" fz="xs" mt={3}>左侧是打开或创建时的基线，右侧是当前草稿。这里只审查，不会改写内容。</Text>
        </Box>
        <Button
          leftSection={<Save size={14} />}
          disabled={!dirtyKeys.length}
          loading={controller.asyncState === "saving"}
          onClick={() => { void controller.saveAll(); }}
        >保存全部草稿</Button>
      </Group>
      <Tabs defaultValue="drafts" keepMounted={false} mt="md">
        <Tabs.List>
          <Tabs.Tab value="drafts">草稿 {dirtyKeys.length}</Tabs.Tab>
          <Tabs.Tab value="git">Git 历史</Tabs.Tab>
        </Tabs.List>
        <Tabs.Panel value="drafts" pt="md">
          {dirtyKeys.length ? <Stack gap="sm">
            <Group align="flex-end">
              <Select
                label="选择草稿"
                value={selectedKey}
                onChange={setSelectedKey}
                data={dirtyKeys.map((key) => ({ value: key, label: controller.documents.find((item) => item.key === key)?.path ?? key }))}
                style={{ flex: 1 }}
              />
              {selectedDocument && <Button variant="default" onClick={() => onNavigate(selectedDocument.key, 1, 1)}>回到源码</Button>}
            </Group>
            {selectedKey && <div className="change-comparison" aria-label="保存前草稿比较">
              <section>
                <Text fw={650} fz="sm">基线</Text>
                <ScrollArea h="calc(100vh - 330px)" type="auto"><pre tabIndex={0}>{controller.originals[selectedKey] ?? ""}</pre></ScrollArea>
              </section>
              <section>
                <Text fw={650} fz="sm">当前草稿</Text>
                <ScrollArea h="calc(100vh - 330px)" type="auto"><pre tabIndex={0}>{controller.buffers[selectedKey] ?? ""}</pre></ScrollArea>
              </section>
            </div>}
          </Stack> : <Text c="dimmed" ta="center" py="xl">当前没有未保存草稿。</Text>}
        </Tabs.Panel>
        <Tabs.Panel value="git" pt="md">
          {gitError && <Text c="red">{gitError}</Text>}
          {git && !git.available && <Text c="dimmed">当前工作区不在 Git 仓库内；草稿审查仍可正常使用。</Text>}
          {git?.available && <Stack gap="lg">
            <Box>
              <Group gap="xs"><GitCommitHorizontal size={16} /><Text fw={650}>最近提交</Text><Badge variant="outline" color="gray">{git.commits.length}</Badge></Group>
              <Stack gap={6} mt="sm">{git.commits.map((commit) => <Box key={commit.sha} className="git-history-row"><Code>{commit.sha.slice(0, 8)}</Code><span>{commit.subject}</span><small>{new Date(commit.date).toLocaleString()}</small></Box>)}</Stack>
            </Box>
            <Box>
              <Text fw={650}>磁盘工作树</Text>
              {git.working_tree.length
                ? <Code block mt="sm">{git.working_tree.join("\n")}</Code>
                : <Text c="dimmed" fz="sm" mt="sm">Git 工作树没有磁盘修改。未保存的浏览器草稿不会出现在这里。</Text>}
            </Box>
          </Stack>}
        </Tabs.Panel>
      </Tabs>
    </div>
  );
}
