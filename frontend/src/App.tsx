import { lazy, Suspense, useEffect, useState } from "react";
import { Drawer } from "@mantine/core";

import { LoadingState } from "./components/ui";
import { WorkspaceShell } from "./components/WorkspaceShell";
import { useWorkbench } from "./hooks/useWorkbench";
import type { DocumentFocusMode, ViewId, WorkspaceTool } from "./types";

const DocumentsView = lazy(() => import("./views/DocumentsView").then((module) => ({ default: module.DocumentsView })));
const GraphView = lazy(() => import("./views/GraphView").then((module) => ({ default: module.GraphView })));
const RunsView = lazy(() => import("./views/RunsView").then((module) => ({ default: module.RunsView })));
const PackagesView = lazy(() => import("./views/PackagesView").then((module) => ({ default: module.PackagesView })));

export function App() {
  const controller = useWorkbench();
  const [activeView, setActiveView] = useState<ViewId>("documents");
  const [workspaceTool, setWorkspaceTool] = useState<WorkspaceTool | null>(null);
  const [documentFocusMode, setDocumentFocusMode] = useState<DocumentFocusMode>(() => {
    const stored = localStorage.getItem("kirin:document-focus-mode");
    return stored === "editor" || stored === "preview" ? stored : "split";
  });

  useEffect(() => {
    localStorage.setItem("kirin:document-focus-mode", documentFocusMode);
  }, [documentFocusMode]);

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

  return (
    <>
      <WorkspaceShell
        activeView={activeView}
        documentFocusMode={documentFocusMode}
        onDocumentFocusModeChange={setDocumentFocusMode}
        onViewChange={setActiveView}
        onOpenTool={setWorkspaceTool}
        onNavigateToSource={(key, line, column) => { void navigateToSource(key, line, column); }}
        controller={controller}
      >
        <Suspense fallback={<LoadingState label="正在打开工作区工具…" />}>
          {activeView === "documents" && <DocumentsView controller={controller} focusMode={documentFocusMode} onFocusModeChange={setDocumentFocusMode} />}
          {activeView === "graph" && <GraphView controller={controller} onNavigate={(path, line, column) => { void navigateToSource(path, line, column); }} />}
        </Suspense>
      </WorkspaceShell>
      <Drawer
        opened={workspaceTool !== null}
        onClose={() => setWorkspaceTool(null)}
        position="right"
        size="92%"
        title={workspaceTool === "runs" ? "运行记录" : "Package 管理"}
        className="workspace-tool-drawer"
      >
        <Suspense fallback={<LoadingState label="正在打开工作区工具…" />}>
          {workspaceTool === "runs" && <RunsView controller={controller} />}
          {workspaceTool === "packages" && <PackagesView controller={controller} />}
        </Suspense>
      </Drawer>
    </>
  );
}
