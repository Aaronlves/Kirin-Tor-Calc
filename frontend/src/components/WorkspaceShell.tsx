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
  SegmentedControl,
  Stack,
  Text,
  Tooltip,
} from "@mantine/core";
import { Spotlight, spotlight, type SpotlightActionData } from "@mantine/spotlight";
import {
  Box as PackageIcon,
  BookOpenText,
  Braces,
  Check,
  CircleAlert,
  Columns3,
  Command,
  Eye,
  FileCode2,
  History,
  ListChecks,
  Network,
  PanelLeftClose,
  PanelLeftOpen,
  Save,
  Search,
  Square,
} from "lucide-react";

import type { DocumentFocusMode, ViewId, WorkspaceTool } from "../types";
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
  activeTool: WorkspaceTool | null;
  controller: WorkbenchController;
  documentFocusMode: DocumentFocusMode;
  onDocumentFocusModeChange(mode: DocumentFocusMode): void;
  onViewChange(view: ViewId): void;
  onOpenTool(tool: WorkspaceTool): void;
  onNavigateToSource(key: string, line?: number | null, column?: number | null): void;
  children: ReactNode;
}

function workspaceName(path?: string): string {
  if (!path) return "正在连接";
  const parts = path.split(/[\\/]/).filter(Boolean);
  return parts.at(-1) || path;
}

export function WorkspaceShell({ activeView, activeTool, controller, documentFocusMode, onDocumentFocusModeChange, onViewChange, onOpenTool, onNavigateToSource, children }: WorkspaceShellProps) {
  const [compactNavigation, setCompactNavigation] = useState(() => {
    const stored = localStorage.getItem("kirin:compact-navigation");
    return stored === null ? window.matchMedia("(max-width: 1320px)").matches : stored === "true";
  });
  const metadata = viewMetadata[activeView];
  const hasErrors = controller.validationItems.length > 0;
  const isBusy = controller.asyncState !== "idle";
  const workspaceStatus = controller.asyncState === "connecting"
    ? "连接中"
    : controller.asyncState === "validating"
      ? "正在检查"
      : controller.asyncState === "running"
        ? `${controller.operationJobs.length || 1} 项操作执行中`
      : hasErrors
        ? `${controller.validationItems.length} 个问题`
        : controller.dirtyCount
          ? `${controller.dirtyCount} 个草稿`
          : "工作区有效";

  useEffect(() => {
    localStorage.setItem("kirin:compact-navigation", String(compactNavigation));
  }, [compactNavigation]);

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
      id: "document-focus-editor",
      label: "文档：仅编辑",
      description: "隐藏文档索引和检查器，将空间完整交给源码编辑器",
      leftSection: <FileCode2 size={17} strokeWidth={1.7} />,
      onClick: () => { onViewChange("documents"); onDocumentFocusModeChange("editor"); },
      keywords: ["focus", "editor", "专注", "编辑"],
    },
    {
      id: "document-focus-split",
      label: "文档：分栏",
      description: "同时显示文档索引、源码编辑器和检查器",
      leftSection: <Columns3 size={17} strokeWidth={1.7} />,
      onClick: () => { onViewChange("documents"); onDocumentFocusModeChange("split"); },
      keywords: ["focus", "split", "分栏"],
    },
    {
      id: "document-focus-preview",
      label: "文档：仅预览",
      description: "隐藏文档索引和源码编辑器，将空间完整交给检查器",
      leftSection: <Eye size={17} strokeWidth={1.7} />,
      onClick: () => { onViewChange("documents"); onDocumentFocusModeChange("preview"); },
      keywords: ["focus", "preview", "专注", "预览"],
    },
    {
      id: "open-syntax-reference",
      label: "打开 Kirin 语法参考",
      description: "搜索写作规则并查看可复制的完整示例",
      leftSection: <BookOpenText size={17} strokeWidth={1.7} />,
      onClick: () => onOpenTool("syntax"),
      keywords: ["syntax", "reference", "docs", "help", "语法", "参考", "文档", "帮助", "示例"],
    },
    {
      id: "open-workspace-search",
      label: "搜索与替换整个工作区",
      description: "搜索当前草稿和 Package 源码；替换只生成可审查草稿",
      leftSection: <Search size={17} strokeWidth={1.7} />,
      onClick: () => onOpenTool("search"),
      keywords: ["search", "replace", "全文", "搜索", "替换"],
    },
    {
      id: "open-change-review",
      label: "审查未保存变更",
      description: controller.dirtyCount ? `${controller.dirtyCount} 个草稿等待审查` : "当前没有未保存修改",
      leftSection: <ListChecks size={17} strokeWidth={1.7} />,
      onClick: () => onOpenTool("changes"),
      keywords: ["diff", "changes", "review", "变更", "审查", "差异"],
    },
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
    ...controller.documents.map((document) => ({
      id: `document-${document.key}`,
      label: `打开文档：${document.title}`,
      description: document.package ? `${document.path} · ${document.package.name}@${document.package.version} · 只读` : document.path,
      leftSection: document.package ? <PackageIcon size={17} strokeWidth={1.7} /> : <FileCode2 size={17} strokeWidth={1.7} />,
      onClick: () => onNavigateToSource(document.key, 1, 1),
      keywords: [document.title, document.path, document.package?.name ?? "", "文档", "quick open"],
    })),
    ...controller.authoringIndex.symbols
      .filter((symbol) => symbol.outline && symbol.kind !== "section" && symbol.kind !== "entry")
      .map((symbol) => ({
        id: `symbol-${symbol.id}-${symbol.definition.key}-${symbol.definition.line}`,
        label: `符号：${symbol.label}`,
        description: `${symbol.detail} · ${symbol.definition.path}:${symbol.definition.line}`,
        leftSection: <Braces size={17} strokeWidth={1.7} />,
        onClick: () => onNavigateToSource(symbol.definition.key, symbol.definition.line, symbol.definition.column),
        keywords: [symbol.id, symbol.name, symbol.label, symbol.kind, "symbol", "符号"],
      })),
  ], [controller, onDocumentFocusModeChange, onNavigateToSource, onOpenTool, onViewChange]);

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
              {activeView === "documents" && <SegmentedControl
                className="document-focus-switch"
                size="xs"
                aria-label="文档专注模式"
                value={documentFocusMode}
                onChange={(value) => onDocumentFocusModeChange(value as DocumentFocusMode)}
                data={[
                  { value: "editor", label: "仅编辑" },
                  { value: "split", label: "分栏" },
                  { value: "preview", label: "仅预览" },
                ]}
              />}
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
                  <Menu.Item leftSection={<Search size={14} />} onClick={() => onOpenTool("search")}>全文搜索与替换</Menu.Item>
                  <Menu.Item leftSection={<ListChecks size={14} />} onClick={() => onOpenTool("changes")}>保存前变更审查</Menu.Item>
                  <Menu.Item leftSection={<History size={14} />} onClick={() => onOpenTool("runs")}>运行记录</Menu.Item>
                  <Menu.Item leftSection={<PackageIcon size={14} />} onClick={() => onOpenTool("packages")}>Package 管理</Menu.Item>
                  <Menu.Divider />
                  <Menu.Label>参考</Menu.Label>
                  <Menu.Item leftSection={<BookOpenText size={14} />} onClick={() => onOpenTool("syntax")}>Kirin 语法参考</Menu.Item>
                </Menu.Dropdown>
              </Menu>
              <Tooltip label={controller.lastCheckedAt ? `最近检查：${controller.lastCheckedAt.toLocaleTimeString()}` : "尚未完成检查"}>
                <Badge
                  className={`workspace-status-badge${hasErrors ? " is-error" : controller.dirtyCount ? " is-dirty" : ""}`}
                  color={hasErrors ? "red" : controller.dirtyCount ? "orange" : "green"}
                  variant="light"
                  leftSection={hasErrors ? <CircleAlert size={12} /> : <Check size={12} />}
                  aria-label={`工作区状态：${workspaceStatus}`}
                >
                  {workspaceStatus}
                </Badge>
              </Tooltip>
              {controller.operationJobs.length > 0 && <Tooltip label={`${controller.operationJobs.map((job) => `${job.operation} · ${job.stage === "executing" ? "执行中" : job.stage}`).join("；")}。取消会终止对应计算进程。`}>
                <Button
                  variant="default"
                  color="orange"
                  size="xs"
                  leftSection={<Square size={11} fill="currentColor" />}
                  onClick={() => { void controller.cancelOperations(); }}
                >
                  取消 {controller.operationJobs.length} 项操作
                </Button>
              </Tooltip>}
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
                            component="button"
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
                <Stack gap={2}>
                  {!compactNavigation && <Text className="nav-group-label">参考</Text>}
                  <Tooltip label="语法参考" position="right" disabled={!compactNavigation}>
                    <NavLink
                      component="button"
                      active={activeTool === "syntax"}
                      aria-label="语法参考"
                      label={compactNavigation ? undefined : "语法参考"}
                      leftSection={<BookOpenText size={17} strokeWidth={1.65} />}
                      onClick={() => onOpenTool("syntax")}
                    />
                  </Tooltip>
                </Stack>
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
