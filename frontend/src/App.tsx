import { lazy, Suspense, useEffect, useMemo, useState } from "react";
import { Drawer } from "@mantine/core";
import { Notifications } from "@mantine/notifications";

import { LoadingState, WorkspaceToolFrame } from "./components/ui";
import { PluginSurface } from "./components/PluginSurface";
import { WorkspaceShell } from "./components/WorkspaceShell";
import tokens from "./design/tokens.json";
import { useWorkbench } from "./hooks/useWorkbench";
import type { DocumentFocusMode, PluginCommandContribution, PluginProfileContribution, ViewId, WorkspaceTool } from "./types";
import { builtinDestinationById, builtinToolIds, builtinViewIds, type BuiltinDestinationId } from "./workbenchDestinations";

const DocumentsView = lazy(() => import("./views/DocumentsView").then((module) => ({ default: module.DocumentsView })));
const GraphView = lazy(() => import("./views/GraphView").then((module) => ({ default: module.GraphView })));
const RunsView = lazy(() => import("./views/RunsView").then((module) => ({ default: module.RunsView })));
const PackagesView = lazy(() => import("./views/PackagesView").then((module) => ({ default: module.PackagesView })));
const PluginsView = lazy(() => import("./views/PluginsView").then((module) => ({ default: module.PluginsView })));
const SyntaxReference = lazy(() => import("./components/SyntaxReference").then((module) => ({ default: module.SyntaxReference })));
const WorkspaceSearch = lazy(() => import("./components/WorkspaceSearch").then((module) => ({ default: module.WorkspaceSearch })));
const ChangeReview = lazy(() => import("./components/ChangeReview").then((module) => ({ default: module.ChangeReview })));
const WorkspaceSettings = lazy(() => import("./components/WorkspaceSettings").then((module) => ({ default: module.WorkspaceSettings })));

const notificationDurations = new Set([3000, 4000, 6000, 8000]);

interface WorkbenchProfile {
  id: string;
  title: string;
  description: string;
  views: string[];
  tools: string[];
  default_view: string;
  document_focus_mode: DocumentFocusMode;
  plugin_name?: string;
}

export function App() {
  const controller = useWorkbench();
  const [activeView, setActiveView] = useState<ViewId>(() => localStorage.getItem("kirin:active-view") || "documents");
  const [workspaceTool, setWorkspaceTool] = useState<WorkspaceTool | null>(null);
  const [workspaceToolParent, setWorkspaceToolParent] = useState<WorkspaceTool | null>(null);
  const [syntaxTopic, setSyntaxTopic] = useState<string | null>(null);
  const [compactNavigation, setCompactNavigation] = useState(() => {
    const stored = localStorage.getItem("kirin:compact-navigation");
    return stored === null ? window.matchMedia(`(max-width: ${tokens.size.scale["1320"]})`).matches : stored === "true";
  });
  const [notificationDuration, setNotificationDuration] = useState(() => {
    const stored = Number(localStorage.getItem("kirin:notification-duration"));
    return notificationDurations.has(stored) ? stored : 4000;
  });
  const [documentFocusMode, setDocumentFocusMode] = useState<DocumentFocusMode>(() => {
    const stored = localStorage.getItem("kirin:document-focus-mode");
    return stored === "editor" || stored === "preview" ? stored : "split";
  });
  const [activeProfileId, setActiveProfileId] = useState(() => localStorage.getItem("kirin:workbench-profile") || "default");
  const pluginContributions = controller.pluginSummary.contributions;
  const defaultProfile = useMemo<WorkbenchProfile>(() => ({
    id: "default",
    title: "Kirin Tor 默认",
    description: "显示官方工作台以及所有已启用插件贡献。",
    views: [...builtinViewIds, ...pluginContributions.views.map((item) => item.id)],
    tools: [...builtinToolIds, ...pluginContributions.tools.map((item) => item.id)],
    default_view: "documents",
    document_focus_mode: "split",
  }), [pluginContributions.tools, pluginContributions.views]);
  const profiles = useMemo<WorkbenchProfile[]>(
    () => [
      defaultProfile,
      ...pluginContributions.profiles.map((item: PluginProfileContribution) => ({
        ...item,
        plugin_name: item.plugin_name,
      })),
    ],
    [defaultProfile, pluginContributions.profiles],
  );
  const activeProfile = profiles.find((item) => item.id === activeProfileId) ?? defaultProfile;

  useEffect(() => {
    localStorage.setItem("kirin:document-focus-mode", documentFocusMode);
  }, [documentFocusMode]);

  useEffect(() => {
    localStorage.setItem("kirin:compact-navigation", String(compactNavigation));
  }, [compactNavigation]);

  useEffect(() => {
    localStorage.setItem("kirin:notification-duration", String(notificationDuration));
  }, [notificationDuration]);

  useEffect(() => {
    localStorage.setItem("kirin:active-view", activeView);
  }, [activeView]);

  useEffect(() => {
    if (profiles.some((item) => item.id === activeProfileId)) return;
    setActiveProfileId("default");
  }, [activeProfileId, profiles]);

  useEffect(() => {
    if (!controller.bootstrapData) return;
    if (activeProfile.views.includes(activeView)) return;
    setActiveView(activeProfile.default_view);
  }, [activeProfile, activeView, controller.bootstrapData]);

  useEffect(() => {
    if (
      workspaceTool
      && !builtinToolIds.includes(workspaceTool as BuiltinDestinationId)
      && !pluginContributions.tools.some((item) => item.id === workspaceTool)
    ) {
      setWorkspaceTool(null);
      setWorkspaceToolParent(null);
    }
  }, [pluginContributions.tools, workspaceTool]);

  useEffect(() => {
    const openSyntaxReference = (event: Event) => {
      const detail = (event as CustomEvent<{ topic?: string }>).detail;
      setSyntaxTopic(detail?.topic ?? null);
      setWorkspaceToolParent(null);
      setWorkspaceTool("syntax");
    };
    window.addEventListener("kirin:open-syntax-reference", openSyntaxReference);
    return () => window.removeEventListener("kirin:open-syntax-reference", openSyntaxReference);
  }, []);

  const navigateToSource = async (path: string, line?: number | null, column?: number | null) => {
    const document = controller.documents.find((item) => item.key === path || path === item.path || path.endsWith(item.path));
    if (!document) return;
    setActiveView("documents");
    setDocumentFocusMode("split");
    await controller.openDocument(document.key);
    window.setTimeout(() => window.dispatchEvent(new CustomEvent("kirin:navigate-source", {
      detail: { key: document.key, line, column },
    })), 50);
  };

  const activateProfile = (profileId: string, keepToolOpen = false) => {
    const profile = profiles.find((item) => item.id === profileId) ?? defaultProfile;
    setActiveProfileId(profile.id);
    localStorage.setItem("kirin:workbench-profile", profile.id);
    setDocumentFocusMode(profile.document_focus_mode);
    setActiveView(profile.default_view);
    if (!keepToolOpen) {
      setWorkspaceTool(null);
      setWorkspaceToolParent(null);
    }
  };

  const changeView = (viewId: string) => {
    if (!activeProfile.views.includes(viewId)) {
      setActiveProfileId("default");
      localStorage.setItem("kirin:workbench-profile", "default");
    }
    setActiveView(viewId);
    setWorkspaceTool(null);
    setWorkspaceToolParent(null);
  };

  const openWorkspaceTool = (tool: WorkspaceTool, parent: WorkspaceTool | null = null) => {
    if (tool === "syntax") setSyntaxTopic(null);
    setWorkspaceToolParent(parent);
    setWorkspaceTool(tool);
  };
  const toolCloseBlocked = workspaceTool === "settings" && controller.asyncState === "connecting";

  const closeWorkspaceTool = () => {
    setWorkspaceTool(null);
    setWorkspaceToolParent(null);
  };

  useEffect(() => {
    if (!workspaceTool) return;
    const handleEscape = (event: KeyboardEvent) => {
      if (event.key !== "Escape" || toolCloseBlocked) return;
      closeWorkspaceTool();
    };
    window.addEventListener("keydown", handleEscape);
    return () => window.removeEventListener("keydown", handleEscape);
  }, [toolCloseBlocked, workspaceTool]);

  const runPluginCommand = (command: PluginCommandContribution) => {
    if (command.action === "open-view") {
      changeView(command.target);
    } else if (command.action === "open-tool") {
      openWorkspaceTool(command.target);
    } else {
      activateProfile(command.target);
    }
  };

  const pluginView = pluginContributions.views.find((item) => item.id === activeView);
  const pluginTool = pluginContributions.tools.find((item) => item.id === workspaceTool);
  const toolMetadata = workspaceTool ? builtinDestinationById.get(workspaceTool as BuiltinDestinationId) : undefined;
  const toolTitle = workspaceTool
    ? toolMetadata?.title ?? pluginTool?.title ?? "工作区工具"
    : "工作区工具";
  const toolParentTitle = workspaceToolParent
    ? builtinDestinationById.get(workspaceToolParent as BuiltinDestinationId)?.title ?? "上一层工具"
    : undefined;

  return (
    <>
      <Notifications position="top-right" autoClose={notificationDuration} limit={3} zIndex={Number(tokens.layer.notification)} />
      <WorkspaceShell
        activeView={activeView}
        activeTool={workspaceTool}
        compactNavigation={compactNavigation}
        onCompactNavigationChange={setCompactNavigation}
        documentFocusMode={documentFocusMode}
        onDocumentFocusModeChange={setDocumentFocusMode}
        onViewChange={changeView}
        onOpenTool={(tool) => openWorkspaceTool(tool)}
        onNavigateToSource={(key, line, column) => { void navigateToSource(key, line, column); }}
        activeProfile={activeProfile}
        pluginViews={pluginContributions.views}
        pluginCommands={pluginContributions.commands}
        onPluginCommand={runPluginCommand}
        controller={controller}
      >
        <Suspense fallback={<LoadingState label="正在打开工作区工具…" />}>
          {activeView === "documents" && <DocumentsView controller={controller} focusMode={documentFocusMode} onFocusModeChange={setDocumentFocusMode} />}
          {activeView === "graph" && <GraphView controller={controller} onNavigate={(path, line, column) => { void navigateToSource(path, line, column); }} />}
          {pluginView && <PluginSurface
            controller={controller}
            contribution={pluginView}
            onNavigateToSource={(key, line, column) => { void navigateToSource(key, line, column); }}
          />}
        </Suspense>
      </WorkspaceShell>
      <Drawer
        opened={workspaceTool !== null}
        onClose={() => { if (!toolCloseBlocked) closeWorkspaceTool(); }}
        position="right"
        size={toolMetadata?.drawerSize ?? "92%"}
        title={<span className="workspace-tool-title">{toolTitle}</span>}
        closeButtonProps={{ "aria-label": "关闭工作区工具", disabled: toolCloseBlocked }}
        closeOnClickOutside={!toolCloseBlocked}
        closeOnEscape={false}
        className="workspace-tool-drawer"
      >
        <WorkspaceToolFrame
          returnLabel={toolParentTitle}
          onReturn={workspaceToolParent ? () => openWorkspaceTool(workspaceToolParent) : undefined}
        >
          <Suspense fallback={<LoadingState label="正在打开工作区工具…" />}>
            {workspaceTool === "runs" && <RunsView controller={controller} />}
            {workspaceTool === "packages" && <PackagesView controller={controller} />}
            {workspaceTool === "plugins" && <PluginsView controller={controller} />}
            {workspaceTool === "syntax" && <SyntaxReference initialTopic={syntaxTopic} />}
            {workspaceTool === "search" && <WorkspaceSearch controller={controller} onNavigate={(path, line, column) => { void navigateToSource(path, line, column); }} onReviewChanges={() => openWorkspaceTool("changes", "search")} />}
            {workspaceTool === "changes" && <ChangeReview controller={controller} onNavigate={(path, line, column) => { void navigateToSource(path, line, column); }} />}
            {workspaceTool === "settings" && <WorkspaceSettings
              controller={controller}
              compactNavigation={compactNavigation}
              onCompactNavigationChange={setCompactNavigation}
              documentFocusMode={documentFocusMode}
              onDocumentFocusModeChange={setDocumentFocusMode}
              notificationDuration={notificationDuration}
              onNotificationDurationChange={setNotificationDuration}
              activeProfileId={activeProfile.id}
              profiles={profiles}
              onProfileChange={(profileId) => activateProfile(profileId, true)}
              onOpenTool={(tool) => openWorkspaceTool(tool, "settings")}
            />}
            {pluginTool && <PluginSurface
              controller={controller}
              contribution={pluginTool}
              headingOrder={3}
              onNavigateToSource={(key, line, column) => { void navigateToSource(key, line, column); }}
            />}
          </Suspense>
        </WorkspaceToolFrame>
      </Drawer>
    </>
  );
}
