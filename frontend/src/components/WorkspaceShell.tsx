import { useEffect, useMemo, useState, type ReactNode } from "react";
import {
  ActionIcon,
  Badge,
  Box,
  Button,
  Group,
  Kbd,
  Menu,
  NavLink,
  ScrollArea,
  Stack,
  Text,
  Tooltip,
} from "@mantine/core";
import { Spotlight, spotlight, type SpotlightActionData } from "@mantine/spotlight";
import {
  Box as PackageIcon,
  Check,
  CircleAlert,
  Command,
  FileCode2,
  History,
  Network,
  PanelLeftClose,
  PanelLeftOpen,
  Save,
  Search,
} from "lucide-react";

import type { ViewId, WorkspaceTool } from "../types";
import type { WorkbenchController } from "../hooks/useWorkbench";

const viewMetadata: Record<ViewId, { title: string; eyebrow: string; description: string }> = {
  documents: {
    title: "文档",
    eyebrow: "创作",
    description: "编辑 Kirin 权威源码，并从当前草稿派生诊断与公式。",
  },
  graph: {
    title: "关系图",
    eyebrow: "理解",
    description: "浏览由公式与跨文档引用生成的工作区关系网络。",
  },
};

const navigationGroups: Array<{
  label: string;
  items: Array<{ id: ViewId; label: string; icon: typeof FileCode2 }>;
}> = [
  {
    label: "创作",
    items: [
      { id: "documents", label: "文档", icon: FileCode2 },
      { id: "graph", label: "关系图", icon: Network },
    ],
  },
];

interface WorkspaceShellProps {
  activeView: ViewId;
  controller: WorkbenchController;
  onViewChange(view: ViewId): void;
  onOpenTool(tool: WorkspaceTool): void;
  children: ReactNode;
}

function workspaceName(path?: string): string {
  if (!path) return "正在连接";
  const parts = path.split(/[\\/]/).filter(Boolean);
  return parts.at(-1) || path;
}

export function WorkspaceShell({ activeView, controller, onViewChange, onOpenTool, children }: WorkspaceShellProps) {
  const [compactNavigation, setCompactNavigation] = useState(false);
  const metadata = viewMetadata[activeView];
  const hasErrors = controller.validationItems.length > 0;
  const isBusy = controller.asyncState !== "idle";

  useEffect(() => {
    const handleShortcut = (event: KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "s") {
        event.preventDefault();
        void controller.saveAll();
      }
    };
    window.addEventListener("keydown", handleShortcut);
    return () => window.removeEventListener("keydown", handleShortcut);
  }, [controller]);

  const spotlightActions = useMemo<SpotlightActionData[]>(() => [
    ...navigationGroups.flatMap((group) => group.items.map((item) => {
      const Icon = item.icon;
      return {
        id: `view-${item.id}`,
        label: `前往${item.label}`,
        description: viewMetadata[item.id].description,
        leftSection: <Icon size={17} strokeWidth={1.7} />,
        onClick: () => onViewChange(item.id),
        keywords: [group.label, item.label],
      };
    })),
    {
      id: "open-runs",
      label: "打开运行记录",
      description: "检查并重放带定义快照的不可变计算记录",
      leftSection: <History size={17} strokeWidth={1.7} />,
      onClick: () => onOpenTool("runs"),
      keywords: ["runs", "history", "运行记录"],
    },
    {
      id: "open-packages",
      label: "打开 Package 管理",
      description: "安装、锁定、验证并开发社区数据包",
      leftSection: <PackageIcon size={17} strokeWidth={1.7} />,
      onClick: () => onOpenTool("packages"),
      keywords: ["package", "依赖", "安装"],
    },
    {
      id: "check-workspace",
      label: "检查工作区",
      description: "从当前未保存草稿重新执行完整校验",
      leftSection: <Check size={17} strokeWidth={1.7} />,
      onClick: () => { void controller.validate(true); },
      keywords: ["check", "validate", "校验"],
    },
    {
      id: "save-workspace",
      label: "保存全部草稿",
      description: controller.dirtyCount ? `${controller.dirtyCount} 个文档等待保存` : "当前没有未保存修改",
      leftSection: <Save size={17} strokeWidth={1.7} />,
      onClick: () => { void controller.saveAll(); },
      keywords: ["save", "保存"],
    },
  ], [controller, onOpenTool, onViewChange]);

  return (
    <>
      <Spotlight
        actions={spotlightActions}
        shortcut={["mod + K", "mod + P"]}
        searchProps={{
          leftSection: <Search size={17} strokeWidth={1.7} />,
          placeholder: "搜索页面或命令…",
        }}
        nothingFound="没有匹配的命令"
        highlightQuery
        limit={9}
      />
      <div className={`workbench-shell${compactNavigation ? " is-compact" : ""}`}>
        <header className="workbench-header">
          <Group h="100%" justify="space-between" wrap="nowrap" px="md">
            <Group gap="sm" wrap="nowrap" className="page-identity">
              <Tooltip label={compactNavigation ? "展开导航" : "收起导航"} position="bottom">
                <ActionIcon
                  variant="subtle"
                  color="gray"
                  aria-label={compactNavigation ? "展开导航" : "收起导航"}
                  onClick={() => setCompactNavigation((value) => !value)}
                >
                  {compactNavigation
                    ? <PanelLeftOpen size={17} strokeWidth={1.65} />
                    : <PanelLeftClose size={17} strokeWidth={1.65} />}
                </ActionIcon>
              </Tooltip>
              <Box>
                <Text className="page-eyebrow">{metadata.eyebrow} / {metadata.title}</Text>
                <Text className="page-description">{metadata.description}</Text>
              </Box>
            </Group>
            <Group gap="xs" wrap="nowrap" className="header-actions">
              <Button
                variant="default"
                size="xs"
                leftSection={<Command size={14} strokeWidth={1.7} />}
                rightSection={<Kbd>⌘ K</Kbd>}
                onClick={() => spotlight.open()}
              >
                命令
              </Button>
              <Menu position="bottom-end" withinPortal>
                <Menu.Target><Button variant="default" size="xs">工作区</Button></Menu.Target>
                <Menu.Dropdown>
                  <Menu.Label>工作区工具</Menu.Label>
                  <Menu.Item leftSection={<History size={14} />} onClick={() => onOpenTool("runs")}>运行记录</Menu.Item>
                  <Menu.Item leftSection={<PackageIcon size={14} />} onClick={() => onOpenTool("packages")}>Package 管理</Menu.Item>
                </Menu.Dropdown>
              </Menu>
              <Tooltip label={controller.lastCheckedAt ? `最近检查：${controller.lastCheckedAt.toLocaleTimeString()}` : "尚未完成检查"}>
                <Badge
                  className={`workspace-status-badge${hasErrors ? " is-error" : controller.dirtyCount ? " is-dirty" : ""}`}
                  color={hasErrors ? "red" : controller.dirtyCount ? "orange" : "green"}
                  variant="light"
                  leftSection={hasErrors ? <CircleAlert size={12} /> : <Check size={12} />}
                >
                  {controller.asyncState === "connecting"
                    ? "连接中"
                    : controller.asyncState === "validating"
                      ? "正在检查"
                      : hasErrors
                        ? `${controller.validationItems.length} 个问题`
                        : controller.dirtyCount
                          ? `${controller.dirtyCount} 个草稿`
                          : "工作区有效"}
                </Badge>
              </Tooltip>
              <Button
                size="xs"
                leftSection={<Save size={14} strokeWidth={1.8} />}
                onClick={() => { void controller.saveAll(); }}
                loading={controller.asyncState === "saving"}
                disabled={!controller.dirtyCount || isBusy && controller.asyncState !== "saving"}
              >
                保存全部
              </Button>
            </Group>
          </Group>
        </header>

        <nav className="workbench-navbar" aria-label="主导航">
          <Stack gap={0} h="100%">
            <Box className="brand-block">
              <div className="brand-mark">KT</div>
              {!compactNavigation && (
                <Box className="brand-copy">
                  <Text className="brand-wordmark">KIRIN TOR</Text>
                  <Text c="dimmed" fz="10px">结构化计算工作台</Text>
                </Box>
              )}
            </Box>
            <ScrollArea flex={1} type="never" px={compactNavigation ? 6 : 10} py="sm">
              <Stack gap="md">
                {navigationGroups.map((group) => (
                  <Stack key={group.label} gap={2}>
                    {!compactNavigation && <Text className="nav-group-label">{group.label}</Text>}
                    {group.items.map((item) => {
                      const Icon = item.icon;
                      return (
                        <Tooltip
                          key={item.id}
                          label={item.label}
                          position="right"
                          disabled={!compactNavigation}
                        >
                          <NavLink
                            active={activeView === item.id}
                            aria-label={item.label}
                            label={compactNavigation ? undefined : item.label}
                            leftSection={<Icon size={17} strokeWidth={1.65} />}
                            onClick={() => onViewChange(item.id)}
                          />
                        </Tooltip>
                      );
                    })}
                  </Stack>
                ))}
              </Stack>
            </ScrollArea>
            <Box className="workspace-meta">
              <span className={`connection-dot${hasErrors ? " is-error" : ""}`} />
              {!compactNavigation && (
                <Box className="workspace-meta-copy">
                  <Text fz="xs" fw={600} truncate>{workspaceName(controller.bootstrapData?.workspace)}</Text>
                  <Text fz="10px" c="dimmed" truncate>Kirin {controller.bootstrapData?.version ?? "—"}</Text>
                </Box>
              )}
            </Box>
          </Stack>
        </nav>

        <main className="workbench-main">
          {children}
        </main>
      </div>
    </>
  );
}
