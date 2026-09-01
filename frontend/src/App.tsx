import { lazy, Suspense, useState } from "react";
import { Drawer } from "@mantine/core";

import { LoadingState } from "./components/ui";
import { WorkspaceShell } from "./components/WorkspaceShell";
import { useWorkbench } from "./hooks/useWorkbench";
import type { ViewId, WorkspaceTool } from "./types";

const DocumentsView = lazy(() => import("./views/DocumentsView").then((module) => ({ default: module.DocumentsView })));
const GraphView = lazy(() => import("./views/GraphView").then((module) => ({ default: module.GraphView })));
const RunsView = lazy(() => import("./views/RunsView").then((module) => ({ default: module.RunsView })));
const PackagesView = lazy(() => import("./views/PackagesView").then((module) => ({ default: module.PackagesView })));

export function App() {
  const controller = useWorkbench();
  const [activeView, setActiveView] = useState<ViewId>("documents");
  const [workspaceTool, setWorkspaceTool] = useState<WorkspaceTool | null>(null);

  const navigateToSource = async (path: string, line?: number | null, column?: number | null) => {
    const document = controller.documents.find((item) => path === item.path || path.endsWith(item.path));
    if (!document) return;
    setActiveView("documents");
    await controller.openDocument(document.key);
    window.setTimeout(() => window.dispatchEvent(new CustomEvent("kirin:navigate-source", {
      detail: { key: document.key, line, column },
    })), 50);
  };

  return (
    <>
      <WorkspaceShell activeView={activeView} onViewChange={setActiveView} onOpenTool={setWorkspaceTool} controller={controller}>
        <Suspense fallback={<LoadingState label="正在打开工作区工具…" />}>
          {activeView === "documents" && <DocumentsView controller={controller} />}
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
