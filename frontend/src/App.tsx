import { lazy, Suspense, useEffect, useMemo, useState } from "react";
import { Drawer } from "@mantine/core";

import { LoadingState } from "./components/ui";
import { PluginSurface } from "./components/PluginSurface";
import { WorkspaceShell } from "./components/WorkspaceShell";
import { useWorkbench } from "./hooks/useWorkbench";
import type { DocumentFocusMode, PluginCommandContribution, PluginProfileContribution, ViewId, WorkspaceTool } from "./types";

const DocumentsView = lazy(() => import("./views/DocumentsView").then((module) => ({ default: module.DocumentsView })));
const GraphView = lazy(() => import("./views/GraphView").then((module) => ({ default: module.GraphView })));
const RunsView = lazy(() => import("./views/RunsView").then((module) => ({ default: module.RunsView })));
const PackagesView = lazy(() => import("./views/PackagesView").then((module) => ({ default: module.PackagesView })));
const PluginsView = lazy(() => import("./views/PluginsView").then((module) => ({ default: module.PluginsView })));
const SyntaxReference = lazy(() => import("./components/SyntaxReference").then((module) => ({ default: module.SyntaxReference })));
const WorkspaceSearch = lazy(() => import("./components/WorkspaceSearch").then((module) => ({ default: module.WorkspaceSearch })));
const ChangeReview = lazy(() => import("./components/ChangeReview").then((module) => ({ default: module.ChangeReview })));

const builtinToolTitles: Record<string, string> = {
  runs: "运行记录",
  packages: "Package 管理",
  syntax: "Kirin Tor 语法参考",
  search: "工作区搜索与替换",
  changes: "保存前变更审查",
  plugins: "Workbench Plugins",
};

const builtinTools = ["runs", "packages", "plugins", "syntax", "search", "changes"];

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
  const [activeView, setActiveView] = useState<ViewId>("documents");
  const [workspaceTool, setWorkspaceTool] = useState<WorkspaceTool | null>(null);
  const [syntaxTopic, setSyntaxTopic] = useState<string | null>(null);
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
    views: ["documents", "graph", ...pluginContributions.views.map((item) => item.id)],
    tools: [...builtinTools, ...pluginContributions.tools.map((item) => item.id)],
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
    if (profiles.some((item) => item.id === activeProfileId)) return;
    setActiveProfileId("default");
  }, [activeProfileId, profiles]);

  useEffect(() => {
    if (activeProfile.views.includes(activeView)) return;
    setActiveView(activeProfile.default_view);
  }, [activeProfile, activeView]);

  useEffect(() => {
    if (
      workspaceTool
      && !builtinTools.includes(workspaceTool)
      && !pluginContributions.tools.some((item) => item.id === workspaceTool)
    ) {
      setWorkspaceTool(null);
    }
  }, [pluginContributions.tools, workspaceTool]);

  useEffect(() => {
    const openSyntaxReference = (event: Event) => {
      const detail = (event as CustomEvent<{ topic?: string }>).detail;
      setSyntaxTopic(detail?.topic ?? null);
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

  const activateProfile = (profileId: string) => {
    const profile = profiles.find((item) => item.id === profileId) ?? defaultProfile;
    setActiveProfileId(profile.id);
    localStorage.setItem("kirin:workbench-profile", profile.id);
    setDocumentFocusMode(profile.document_focus_mode);
    setActiveView(profile.default_view);
    setWorkspaceTool(null);
  };

  const changeView = (viewId: string) => {
    if (!activeProfile.views.includes(viewId)) {
      setActiveProfileId("default");
      localStorage.setItem("kirin:workbench-profile", "default");
    }
    setActiveView(viewId);
    setWorkspaceTool(null);
  };

  const runPluginCommand = (command: PluginCommandContribution) => {
    if (command.action === "open-view") {
      changeView(command.target);
    } else if (command.action === "open-tool") {
      setWorkspaceTool(command.target);
    } else {
      activateProfile(command.target);
    }
  };

  const pluginView = pluginContributions.views.find((item) => item.id === activeView);
  const pluginTool = pluginContributions.tools.find((item) => item.id === workspaceTool);
  const toolTitle = workspaceTool
    ? builtinToolTitles[workspaceTool] ?? pluginTool?.title ?? "工作区工具"
    : "工作区工具";

  return (
    <>
      <WorkspaceShell
        activeView={activeView}
        activeTool={workspaceTool}
        documentFocusMode={documentFocusMode}
        onDocumentFocusModeChange={setDocumentFocusMode}
        onViewChange={changeView}
        onOpenTool={(tool) => { if (tool === "syntax") setSyntaxTopic(null); setWorkspaceTool(tool); }}
        onNavigateToSource={(key, line, column) => { void navigateToSource(key, line, column); }}
        activeProfile={activeProfile}
        profiles={profiles}
        pluginViews={pluginContributions.views}
        pluginCommands={pluginContributions.commands}
        onProfileChange={activateProfile}
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
        onClose={() => setWorkspaceTool(null)}
        position="right"
        size={workspaceTool === "syntax" ? 820 : "92%"}
        title={<span style={{ color: "#eeeae1", fontWeight: 650 }}>{toolTitle}</span>}
        closeButtonProps={{ "aria-label": "关闭工作区工具" }}
        className="workspace-tool-drawer"
      >
        <Suspense fallback={<LoadingState label="正在打开工作区工具…" />}>
          {workspaceTool === "runs" && <RunsView controller={controller} />}
          {workspaceTool === "packages" && <PackagesView controller={controller} />}
          {workspaceTool === "plugins" && <PluginsView controller={controller} />}
          {workspaceTool === "syntax" && <SyntaxReference initialTopic={syntaxTopic} />}
          {workspaceTool === "search" && <WorkspaceSearch controller={controller} onNavigate={(path, line, column) => { void navigateToSource(path, line, column); }} onReviewChanges={() => setWorkspaceTool("changes")} />}
          {workspaceTool === "changes" && <ChangeReview controller={controller} onNavigate={(path, line, column) => { void navigateToSource(path, line, column); }} />}
          {pluginTool && <PluginSurface
            controller={controller}
            contribution={pluginTool}
            onNavigateToSource={(key, line, column) => { void navigateToSource(key, line, column); }}
          />}
        </Suspense>
      </Drawer>
    </>
  );
}
