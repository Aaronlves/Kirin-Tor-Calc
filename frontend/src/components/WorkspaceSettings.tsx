import { useState } from "react";
import {
  Badge,
  Box,
  Button,
  Code,
  CopyButton,
  Group,
  SegmentedControl,
  Select,
  SimpleGrid,
  Stack,
  Table,
  Text,
  TextInput,
} from "@mantine/core";
import { notifications } from "@mantine/notifications";
import { ArrowRightLeft, Box as PackageIcon, Check, Copy, Plug, Settings2 } from "lucide-react";

import { errorMessage } from "../api";
import type { WorkbenchController } from "../hooks/useWorkbench";
import { isApplePlatform, primaryShortcut } from "../platform";
import type { DocumentFocusMode, WorkspaceTool } from "../types";
import { ToolSubview } from "./ui";

interface WorkbenchProfileInfo {
  id: string;
  title: string;
  description: string;
}

interface WorkspaceSettingsProps {
  controller: WorkbenchController;
  compactNavigation: boolean;
  onCompactNavigationChange(compact: boolean): void;
  documentFocusMode: DocumentFocusMode;
  onDocumentFocusModeChange(mode: DocumentFocusMode): void;
  notificationDuration: number;
  onNotificationDurationChange(duration: number): void;
  activeProfileId: string;
  profiles: WorkbenchProfileInfo[];
  onProfileChange(profileId: string): void;
  onOpenTool(tool: WorkspaceTool): void;
}

const notificationOptions = [
  { value: "3000", label: "3 秒" },
  { value: "4000", label: "4 秒（推荐）" },
  { value: "6000", label: "6 秒" },
  { value: "8000", label: "8 秒" },
];

export function WorkspaceSettings({
  controller,
  compactNavigation,
  onCompactNavigationChange,
  documentFocusMode,
  onDocumentFocusModeChange,
  notificationDuration,
  onNotificationDurationChange,
  activeProfileId,
  profiles,
  onProfileChange,
  onOpenTool,
}: WorkspaceSettingsProps) {
  const workspace = controller.bootstrapData?.workspace ?? "正在连接";
  const [workspacePath, setWorkspacePath] = useState("");
  const [confirmSwitchOpened, setConfirmSwitchOpened] = useState(false);
  const [switching, setSwitching] = useState(false);
  const platform = isApplePlatform() ? "macOS" : "Windows / Linux";
  const shortcuts = [
    ["保存全部", primaryShortcut("S")],
    ["快速打开", `${primaryShortcut("K")} / ${primaryShortcut("P")}`],
    ["查找 / 替换", primaryShortcut("F")],
    ["跳到行", primaryShortcut("G")],
    ["文档大纲", primaryShortcut("O", true)],
    ["安全格式化", primaryShortcut("F", true)],
    ["成员重命名", "F2（编辑器）"],
    ["文件重命名 / 移动", "F2（文档列表）"],
  ];
  const targetWorkspace = workspacePath.trim();
  const workspaceBusy = controller.asyncState !== "idle" || controller.operationJobs.length > 0;
  const canSwitch = Boolean(targetWorkspace) && targetWorkspace !== workspace && !workspaceBusy && !switching;

  const performSwitch = async () => {
    if (!canSwitch) return;
    setSwitching(true);
    try {
      await controller.switchWorkspace(targetWorkspace);
    } catch (error) {
      setSwitching(false);
      setConfirmSwitchOpened(false);
      notifications.show({
        color: "red",
        title: "无法切换工作区",
        message: errorMessage(error),
        autoClose: false,
      });
    }
  };

  const requestSwitch = () => {
    if (!canSwitch) return;
    if (controller.dirtyCount) {
      setConfirmSwitchOpened(true);
      return;
    }
    void performSwitch();
  };

  if (confirmSwitchOpened) {
    return <ToolSubview
      title="保留草稿并切换工作区"
      description="确认后先把草稿写入当前工作区的恢复缓存，再打开目标工作区。"
      onBack={() => setConfirmSwitchOpened(false)}
      backDisabled={switching}
    >
      <Stack gap="md" maw={620}>
        <Text fz="sm">当前有 {controller.dirtyCount} 个未保存草稿。</Text>
        <Text c="dimmed" fz="xs">这些草稿不会写入权威 `.kirin` 源码；下次返回当前工作区时会自动恢复。</Text>
        <Code block>{targetWorkspace}</Code>
        <Group justify="flex-end">
          <Button variant="default" disabled={switching} onClick={() => setConfirmSwitchOpened(false)}>取消</Button>
          <Button disabled={!canSwitch} loading={switching} onClick={() => { void performSwitch(); }}>保留草稿并切换</Button>
        </Group>
      </Stack>
    </ToolSubview>;
  }

  return (
    <div className="workspace-settings-tool">
      <Stack gap="xl">
        <Box>
          <Group gap="xs">
            <Settings2 size={18} />
            <Text className="page-kicker">工作台偏好</Text>
          </Group>
          <Text c="dimmed" fz="xs" mt={4}>界面偏好只保存在当前浏览器；工作区选择记录在用户本地，不会写入 `.kirin`、锁文件或运行记录。</Text>
        </Box>

        <section className="settings-section" aria-labelledby="workspace-settings-identity">
          <Group justify="space-between" align="flex-start" wrap="nowrap">
            <Box>
              <Text component="h3" id="workspace-settings-identity" fw={650}>当前工作区</Text>
              <Text c="dimmed" fz="xs" mt={3}>所有保存操作都写入这个本地工作区。</Text>
            </Box>
            <Badge color={controller.validationItems.length ? "red" : controller.dirtyCount ? "orange" : "green"} variant="light">
              {controller.validationItems.length ? `${controller.validationItems.length} 个问题` : controller.dirtyCount ? `${controller.dirtyCount} 个草稿` : "有效"}
            </Badge>
          </Group>
          <Group mt="md" gap="xs" wrap="nowrap">
            <Code block className="workspace-path-code">{workspace}</Code>
            <CopyButton value={workspace}>
              {({ copied, copy }) => <Button variant="default" leftSection={copied ? <Check size={14} /> : <Copy size={14} />} onClick={copy}>{copied ? "已复制" : "复制路径"}</Button>}
            </CopyButton>
          </Group>
          <Text c="dimmed" fz="xs" mt="xs">Kirin Tor {controller.bootstrapData?.version ?? "—"}</Text>
          <Box mt="lg">
            <Text component="h4" fw={620} fz="sm">打开另一个工作区</Text>
            <Text c="dimmed" fz="xs" mt={3}>填写已有 Kirin Tor 工作区或其子目录；切换成功后会成为下次启动的默认工作区。</Text>
            <Group mt="sm" align="flex-end" wrap="nowrap">
              <TextInput
                label="工作区目录"
                placeholder="/path/to/workspace"
                value={workspacePath}
                onChange={(event) => setWorkspacePath(event.currentTarget.value)}
                onKeyDown={(event) => { if (event.key === "Enter") requestSwitch(); }}
                style={{ flex: 1 }}
              />
              <Button
                variant="default"
                leftSection={<ArrowRightLeft size={14} />}
                loading={switching}
                disabled={!canSwitch}
                onClick={requestSwitch}
              >
                切换工作区
              </Button>
            </Group>
            {workspaceBusy && <Text c="orange" fz="xs" mt="xs">请先等待当前操作结束，或取消正在运行的计算。</Text>}
          </Box>
        </section>

        <SimpleGrid cols={{ base: 1, sm: 2 }} spacing="md">
          <section className="settings-section" aria-labelledby="workspace-settings-interface">
            <Text component="h3" id="workspace-settings-interface" fw={650}>界面布局</Text>
            <Stack gap="md" mt="md">
              <Select
                label="界面 Profile"
                value={activeProfileId}
                onChange={(value) => { if (value) onProfileChange(value); }}
                data={profiles.map((profile) => ({ value: profile.id, label: profile.title, description: profile.description }))}
              />
              <Box>
                <Text className="settings-control-label">主导航</Text>
                <SegmentedControl
                  fullWidth
                  value={compactNavigation ? "compact" : "expanded"}
                  onChange={(value) => onCompactNavigationChange(value === "compact")}
                  data={[{ value: "expanded", label: "展开" }, { value: "compact", label: "紧凑" }]}
                />
              </Box>
              <Box>
                <Text className="settings-control-label">文档默认布局</Text>
                <SegmentedControl
                  fullWidth
                  value={documentFocusMode}
                  onChange={(value) => onDocumentFocusModeChange(value as DocumentFocusMode)}
                  data={[{ value: "editor", label: "仅编辑" }, { value: "split", label: "分栏" }, { value: "preview", label: "仅预览" }]}
                />
              </Box>
            </Stack>
          </section>

          <section className="settings-section" aria-labelledby="workspace-settings-feedback">
            <Text component="h3" id="workspace-settings-feedback" fw={650}>反馈与通知</Text>
            <Select
              mt="md"
              label="普通通知停留时间"
              value={String(notificationDuration)}
              onChange={(value) => { if (value) onNotificationDurationChange(Number(value)); }}
              data={notificationOptions}
            />
            <Text c="dimmed" fz="xs" mt="sm">成功、提示和可自行修正的警告会自动退出；保存失败、外部冲突与需要处理的严重错误始终常驻。</Text>
          </section>
        </SimpleGrid>

        <section className="settings-section" aria-labelledby="workspace-settings-extensions">
          <Text component="h3" id="workspace-settings-extensions" fw={650}>依赖与扩展</Text>
          <Text c="dimmed" fz="xs" mt={3}>Package 提供只读模型数据，Workbench Plugin 提供受沙箱约束的界面扩展。</Text>
          <Group mt="md">
            <Button variant="default" leftSection={<PackageIcon size={14} />} onClick={() => onOpenTool("packages")}>Package 管理</Button>
            <Button variant="default" leftSection={<Plug size={14} />} onClick={() => onOpenTool("plugins")}>Workbench Plugins</Button>
          </Group>
        </section>

        <section className="settings-section" aria-labelledby="workspace-settings-shortcuts">
          <Group justify="space-between">
            <Text component="h3" id="workspace-settings-shortcuts" fw={650}>快捷键</Text>
            <Badge variant="outline" color="gray">{platform}</Badge>
          </Group>
          <Table mt="sm" striped withRowBorders>
            <Table.Tbody>
              {shortcuts.map(([action, shortcut]) => <Table.Tr key={action}><Table.Td>{action}</Table.Td><Table.Td><Code>{shortcut}</Code></Table.Td></Table.Tr>)}
            </Table.Tbody>
          </Table>
        </section>
      </Stack>
    </div>
  );
}
