import { useEffect, useMemo, type ReactNode } from "react";
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
  ChevronDown,
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
  Plug,
  Puzzle,
  Save,
  Search,
  Settings,
  Square,
  Wrench,
  type LucideIcon,
} from "lucide-react";

import type { DocumentFocusMode, PluginCommandContribution, PluginSurfaceContribution, ViewId, WorkspaceTool } from "../types";
import type { WorkbenchController } from "../hooks/useWorkbench";
import { primaryShortcut } from "../platform";
import { openSyntaxReference } from "../syntaxHelp";
import tokens from "../design/tokens.json";
import { builtinDestinationById, builtinDestinations, type BuiltinDestinationId, type DestinationIcon } from "../workbenchDestinations";

const destinationIcons: Record<DestinationIcon, LucideIcon> = {
  book: BookOpenText,
  changes: ListChecks,
  documents: FileCode2,
  graph: Network,
  history: History,
  package: PackageIcon,
  plugin: Plug,
  search: Search,
  settings: Settings,
};

interface WorkbenchProfileInfo {
  id: string;
  title: string;
  description: string;
  views: string[];
  tools: string[];
  default_view: string;
  document_focus_mode: DocumentFocusMode;
  plugin_name?: string;
}

interface WorkspaceShellProps {
  activeView: ViewId;
  activeTool: WorkspaceTool | null;
  controller: WorkbenchController;
  compactNavigation: boolean;
  onCompactNavigationChange(compact: boolean): void;
  documentFocusMode: DocumentFocusMode;
  onDocumentFocusModeChange(mode: DocumentFocusMode): void;
  onViewChange(view: ViewId): void;
  onOpenTool(tool: WorkspaceTool): void;
  onNavigateToSource(key: string, line?: number | null, column?: number | null): void;
  activeProfile: WorkbenchProfileInfo;
  pluginViews: PluginSurfaceContribution[];
  pluginCommands: PluginCommandContribution[];
  onPluginCommand(command: PluginCommandContribution): void;
  children: ReactNode;
}

function workspaceName(path?: string): string {
  if (!path) return "正在连接";
  const parts = path.split(/[\\/]/).filter(Boolean);
  return parts.at(-1) || path;
}

export function WorkspaceShell({ activeView, activeTool, controller, compactNavigation, onCompactNavigationChange, documentFocusMode, onDocumentFocusModeChange, onViewChange, onOpenTool, onNavigateToSource, activeProfile, pluginViews, pluginCommands, onPluginCommand, children }: WorkspaceShellProps) {
  const selectedPluginView = pluginViews.find((item) => item.id === activeView);
  const builtinMetadata = builtinDestinationById.get(activeView as BuiltinDestinationId);
  const metadata = builtinMetadata ?? {
    title: selectedPluginView?.title ?? "插件页面",
    eyebrow: "扩展",
    description: selectedPluginView?.description ?? `由 ${selectedPluginView?.plugin_name ?? "Workbench Plugin"} 提供的沙箱页面。`,
  };
  const navigationGroups = useMemo(() => {
    const builtinGroups = builtinDestinations
      .filter((item) => item.placement === "sidebar")
      .filter((item) => item.kind === "view" ? activeProfile.views.includes(item.id) : activeProfile.tools.includes(item.id))
      .reduce<Array<{ label: string; items: Array<{ id: string; label: string; icon: LucideIcon; kind: "view" | "tool" }> }>>((groups, item) => {
        let group = groups.find((candidate) => candidate.label === item.group);
        if (!group) {
          group = { label: item.group, items: [] };
          groups.push(group);
        }
        group.items.push({ id: item.id, label: item.id === "syntax" ? "语法参考" : item.title, icon: destinationIcons[item.icon], kind: item.kind });
        return groups;
      }, []);
    const plugins = activeProfile.views
      .map((id) => pluginViews.find((item) => item.id === id))
      .filter((item): item is PluginSurfaceContribution => Boolean(item))
      .map((item) => ({ id: item.id, label: item.title, icon: Puzzle, kind: "view" as const }));
    return [
      ...builtinGroups,
      ...(plugins.length ? [{ label: "插件", items: plugins }] : []),
    ];
  }, [activeProfile.tools, activeProfile.views, pluginViews]);
  const toolMenuGroups = useMemo(() => builtinDestinations
    .filter((item) => item.placement === "tool-menu" && activeProfile.tools.includes(item.id))
    .reduce<Array<{ label: string; items: typeof builtinDestinations }>>((groups, item) => {
      let group = groups.find((candidate) => candidate.label === item.group);
      if (!group) {
        group = { label: item.group, items: [] };
        groups.push(group);
      }
      group.items.push(item);
      return groups;
    }, []), [activeProfile.tools]);
  const hasErrors = controller.validationItems.length > 0;
  const isBusy = controller.asyncState !== "idle";
  const workspacePath = controller.bootstrapData?.workspace;
  const currentWorkspaceName = workspaceName(workspacePath);
  const saveBlockedReason = !controller.dirtyCount
    ? "当前没有未保存草稿"
    : controller.asyncState === "running"
      ? "请等待当前计算结束或先取消计算"
      : isBusy
        ? "请等待当前工作区操作结束"
        : `保存 ${controller.dirtyCount} 个草稿 · ${primaryShortcut("S")}`;
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
    const handleShortcut = (event: KeyboardEvent) => {
      if (!event.metaKey && !event.ctrlKey) return;
      const key = event.key.toLowerCase();
      if (key === "s") {
        event.preventDefault();
        void controller.saveAll();
        return;
      }
      if (key === "k" || key === "p") {
        event.preventDefault();
        spotlight.open();
      }
    };
    window.addEventListener("keydown", handleShortcut);
    return () => window.removeEventListener("keydown", handleShortcut);
  }, [controller]);

  const spotlightActions = useMemo<SpotlightActionData[]>(() => [
    ...builtinDestinations
      .filter((item) => item.placement === "sidebar")
      .filter((item) => item.kind === "view" ? activeProfile.views.includes(item.id) : activeProfile.tools.includes(item.id))
      .map((item) => {
      const Icon = destinationIcons[item.icon];
      return {
        id: `${item.kind}-${item.id}`,
        label: item.commandLabel,
        description: item.description,
        leftSection: <Icon size={17} strokeWidth={1.7} />,
        onClick: () => item.kind === "view" ? onViewChange(item.id) : onOpenTool(item.id),
        keywords: [item.group, item.title, ...item.keywords],
      };
    }),
    ...pluginViews
      .filter((item) => activeProfile.views.includes(item.id))
      .map((item) => ({
        id: `view-${item.id}`,
        label: `前往${item.title}`,
        description: item.description,
        leftSection: <Puzzle size={17} strokeWidth={1.7} />,
        onClick: () => onViewChange(item.id),
        keywords: ["插件", item.title, item.plugin_name],
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
    ...builtinDestinations
      .filter((item) => item.placement !== "sidebar")
      .filter((item) => item.kind === "view" ? activeProfile.views.includes(item.id) : activeProfile.tools.includes(item.id))
      .map((item) => {
        const Icon = destinationIcons[item.icon];
        return {
          id: `${item.kind}-${item.id}`,
          label: item.commandLabel,
          description: item.description,
          leftSection: <Icon size={17} strokeWidth={1.7} />,
          onClick: () => item.kind === "view" ? onViewChange(item.id) : onOpenTool(item.id),
          keywords: [item.group, item.title, ...item.keywords],
        };
      }),
    {
      id: "open-external-authoring-help",
      label: "查看 Agent 与外部编辑器协作",
      description: "了解直接写入 .kirin、自动同步、草稿保护和冲突边界",
      leftSection: <BookOpenText size={17} strokeWidth={1.7} />,
      onClick: () => openSyntaxReference("external-authoring"),
      keywords: ["Agent 协作", "Agent", "external editor", "sync", "conflict", "外部编辑器", "协作", "同步", "冲突"],
    },
    ...pluginCommands.map((command) => ({
      id: `plugin-command-${command.id}`,
      label: command.title,
      description: `${command.description} · ${command.plugin_name}`,
      leftSection: <Puzzle size={17} strokeWidth={1.7} />,
      onClick: () => onPluginCommand(command),
      keywords: [command.id, command.plugin_name, "plugin", "插件"],
    })),
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
  ], [activeProfile.tools, activeProfile.views, controller, onDocumentFocusModeChange, onNavigateToSource, onOpenTool, onPluginCommand, onViewChange, pluginCommands, pluginViews]);

  return (
    <>
      <Spotlight
        actions={spotlightActions}
        zIndex={Number(tokens.layer.spotlight)}
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
                  onClick={() => onCompactNavigationChange(!compactNavigation)}
                >
                  {compactNavigation
                    ? <PanelLeftOpen size={17} strokeWidth={1.65} />
                    : <PanelLeftClose size={17} strokeWidth={1.65} />}
                </ActionIcon>
              </Tooltip>
              <Box className="page-identity-copy">
                <Group gap="xs" wrap="nowrap">
                  <Text id="workbench-page-title" component="h1" aria-label={metadata.title} className="page-title">{metadata.title}</Text>
                  <Text className="page-context">
                    <Tooltip label={workspacePath ?? "正在连接工作区"} position="bottom-start">
                      <span className="workspace-context" aria-label={`当前工作区：${workspacePath ?? "正在连接"}`}>{currentWorkspaceName}</span>
                    </Tooltip>
                    <span aria-hidden="true"> · </span>{metadata.eyebrow}
                  </Text>
                </Group>
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
                rightSection={<Kbd>{primaryShortcut("K")}</Kbd>}
                onClick={() => spotlight.open()}
              >
                命令
              </Button>
              <Menu position="bottom-end" withinPortal>
                <Menu.Target>
                  <Button
                    variant="default"
                    size="xs"
                    aria-label="工作区工具"
                    leftSection={<Wrench size={14} strokeWidth={1.7} />}
                    rightSection={<ChevronDown size={12} strokeWidth={1.7} />}
                  >
                    工具
                  </Button>
                </Menu.Target>
                <Menu.Dropdown>
                  {toolMenuGroups.map((group, groupIndex) => <Box key={group.label}>
                    {groupIndex > 0 && <Menu.Divider />}
                    <Menu.Label>{group.label}</Menu.Label>
                    {group.items.map((item) => {
                      const Icon = destinationIcons[item.icon];
                      return <Tooltip key={item.id} label={item.description} position="left" withArrow>
                        <Menu.Item leftSection={<Icon size={16} />} onClick={() => onOpenTool(item.id)}>{item.menuLabel ?? item.title}</Menu.Item>
                      </Tooltip>;
                    })}
                  </Box>)}
                  {controller.pluginSummary.contributions.tools.filter((tool) => activeProfile.tools.includes(tool.id)).length > 0 && <>
                    <Menu.Divider />
                    <Menu.Label>插件工具</Menu.Label>
                    {controller.pluginSummary.contributions.tools.filter((tool) => activeProfile.tools.includes(tool.id)).map((tool) => (
                      <Tooltip key={tool.id} label={tool.description} position="left" withArrow>
                        <Menu.Item leftSection={<Puzzle size={16} />} onClick={() => onOpenTool(tool.id)}>{tool.title}</Menu.Item>
                      </Tooltip>
                    ))}
                  </>}
                </Menu.Dropdown>
              </Menu>
              <Tooltip label="工作台设置">
                <ActionIcon variant="default" size="lg" aria-label="设置" onClick={() => onOpenTool("settings")}>
                  <Settings size={15} strokeWidth={1.7} />
                </ActionIcon>
              </Tooltip>
              <Tooltip label={controller.lastCheckedAt ? `最近检查：${controller.lastCheckedAt.toLocaleTimeString()}` : "尚未完成检查"}>
                <Badge
                  className={`workspace-status-badge${hasErrors ? " is-error" : controller.dirtyCount ? " is-dirty" : isBusy ? " is-busy" : " is-valid"}`}
                  color={hasErrors ? "red" : controller.dirtyCount || isBusy ? "orange" : "gray"}
                  variant="light"
                  leftSection={hasErrors ? <CircleAlert size={12} /> : <Check size={12} />}
                  aria-label={`工作区状态：${workspaceStatus}`}
                >
                  {workspaceStatus === "工作区有效" ? "有效" : workspaceStatus}
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
              <Tooltip label={saveBlockedReason}>
                <span className="disabled-control-wrapper">
                  <Button
                    size="xs"
                    leftSection={<Save size={14} strokeWidth={1.8} />}
                    onClick={() => { void controller.saveAll(); }}
                    loading={controller.asyncState === "saving"}
                    disabled={!controller.dirtyCount || isBusy}
                  >
                    保存全部
                  </Button>
                </span>
              </Tooltip>
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
                  <Text c="dimmed" fz="var(--kt-t-s-caption)">结构化计算工作台</Text>
                </Box>
              )}
            </Box>
            <ScrollArea flex={1} type="never" px={compactNavigation ? 6 : 10} py="sm">
              <Stack gap={2}>
                {navigationGroups.flatMap((group) => group.items).map((item) => {
                  const Icon = item.icon;
                  return (
                    <Tooltip key={item.id} label={item.label} position="right" disabled={!compactNavigation}>
                      <NavLink
                        component="button"
                        active={item.kind === "view" ? activeView === item.id : activeTool === item.id}
                        aria-label={item.label}
                        label={item.label}
                        leftSection={<Icon size={17} strokeWidth={1.65} />}
                        onClick={() => item.kind === "view" ? onViewChange(item.id) : onOpenTool(item.id)}
                      />
                    </Tooltip>
                  );
                })}
              </Stack>
            </ScrollArea>
            <Tooltip label={workspacePath ?? "正在连接工作区"} position="right">
              <button
                className="workspace-meta"
                type="button"
                onClick={() => onOpenTool("settings")}
                aria-label={`当前工作区：${workspacePath ?? "正在连接"}；打开设置`}
              >
                <span className={`connection-dot${hasErrors ? " is-error" : ""}`} />
                {!compactNavigation && (
                  <Box className="workspace-meta-copy">
                    <Text fz="xs" fw={600} truncate>{currentWorkspaceName}</Text>
                    <Text fz="var(--kt-t-s-caption)" c="dimmed" truncate>Kirin Tor {controller.bootstrapData?.version ?? "—"}</Text>
                  </Box>
                )}
              </button>
            </Tooltip>
          </Stack>
        </nav>

        <main className="workbench-main" aria-labelledby="workbench-page-title">
          {children}
        </main>
      </div>
    </>
  );
}
