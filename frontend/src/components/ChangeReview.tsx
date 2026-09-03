import { useEffect, useMemo, useState } from "react";
import { Badge, Box, Button, Code, Group, Modal, ScrollArea, Select, Stack, Tabs, Text } from "@mantine/core";
import { GitCommitHorizontal, RotateCcw, Save, Trash2 } from "lucide-react";

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
  const [discardTarget, setDiscardTarget] = useState<string | "all" | null>(null);
  const [discarding, setDiscarding] = useState(false);

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
  const targetDocument = discardTarget && discardTarget !== "all"
    ? controller.documents.find((item) => item.key === discardTarget)
    : null;
  const targetIsNew = Boolean(targetDocument?.source_sha256 === null);

  const confirmDiscard = async () => {
    if (!discardTarget || discarding) return;
    setDiscarding(true);
    try {
      if (discardTarget === "all") await controller.discardAllDrafts();
      else await controller.discardDraft(discardTarget);
      setDiscardTarget(null);
    } finally {
      setDiscarding(false);
    }
  };

  return (
    <div className="change-review-tool">
      <Group justify="space-between" align="flex-start">
        <Box>
          <Text fw={680}>保存前审查</Text>
          <Text c="dimmed" fz="xs" mt={3}>左侧是打开或创建时的基线，右侧是当前草稿。这里只审查，不会改写内容。</Text>
        </Box>
        <Group gap="xs">
          <Button
            className="danger-outline-button"
            variant="default"
            leftSection={<Trash2 size={14} />}
            disabled={!dirtyKeys.length || controller.asyncState !== "idle"}
            onClick={() => setDiscardTarget("all")}
          >放弃全部草稿</Button>
          <Button
            leftSection={<Save size={14} />}
            disabled={!dirtyKeys.length || controller.asyncState !== "idle"}
            loading={controller.asyncState === "saving"}
            onClick={() => { void controller.saveAll(); }}
          >保存全部草稿</Button>
        </Group>
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
              {selectedDocument && <>
                <Button variant="default" onClick={() => onNavigate(selectedDocument.key, 1, 1)}>回到源码</Button>
                <Button
                  className="danger-outline-button"
                  variant="default"
                  leftSection={<RotateCcw size={14} />}
                  onClick={() => setDiscardTarget(selectedDocument.key)}
                >放弃此草稿</Button>
              </>}
            </Group>
            {selectedKey && <div className="change-comparison" aria-label="保存前草稿比较">
              <section>
                <Text fw={650} fz="sm">基线</Text>
                <ScrollArea h="calc(100vh - var(--kt-sz-330))" type="auto"><pre tabIndex={0}>{controller.originals[selectedKey] ?? ""}</pre></ScrollArea>
              </section>
              <section>
                <Text fw={650} fz="sm">当前草稿</Text>
                <ScrollArea h="calc(100vh - var(--kt-sz-330))" type="auto"><pre tabIndex={0}>{controller.buffers[selectedKey] ?? ""}</pre></ScrollArea>
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
      <Modal
        opened={discardTarget !== null}
        onClose={() => setDiscardTarget(null)}
        title={discardTarget === "all" ? "放弃全部未保存草稿" : targetIsNew ? "放弃新文档草稿" : "恢复磁盘基线"}
        centered
      >
        <Stack gap="md">
          <Text fz="sm">
            {discardTarget === "all"
              ? `将放弃 ${dirtyKeys.length} 个未保存草稿。已有文档恢复到打开时的磁盘基线，新文档草稿从工作台移除。`
              : targetIsNew
                ? `${targetDocument?.path ?? "这个新文档"} 尚未写入磁盘；放弃后会从工作台移除。`
                : `${targetDocument?.path ?? "这个文档"} 将恢复到打开时的磁盘内容。`}
          </Text>
          <Text c="dimmed" fz="xs">此操作不会修改磁盘上的 `.kirin` 文件，但会清除对应浏览器草稿和恢复缓存。</Text>
          <Group justify="flex-end">
            <Button variant="default" onClick={() => setDiscardTarget(null)}>取消</Button>
            <Button className="danger-button" loading={discarding} onClick={() => { void confirmDiscard(); }}>确认放弃</Button>
          </Group>
        </Stack>
      </Modal>
    </div>
  );
}
