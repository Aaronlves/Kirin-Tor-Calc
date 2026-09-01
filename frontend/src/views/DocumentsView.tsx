import { useEffect, useMemo, useRef, useState } from "react";
import {
  ActionIcon,
  Badge,
  Box,
  Button,
  Code,
  Divider,
  Drawer,
  Group,
  Menu,
  Modal,
  Popover,
  ScrollArea,
  Select,
  Stack,
  Tabs,
  Text,
  TextInput,
  Title,
  Tooltip,
} from "@mantine/core";
import { notifications } from "@mantine/notifications";
import {
  ArrowRight,
  BookOpen,
  BookTemplate,
  Box as PackageIcon,
  Braces,
  CircleAlert,
  CircleCheck,
  Copy,
  Crosshair,
  FileCode2,
  FileDown,
  FilePlus2,
  FileText,
  FolderInput,
  GitCompare,
  Eye,
  ListTree,
  MoreHorizontal,
  Network,
  PackageOpen,
  Save,
  Search,
  Trash2,
  WandSparkles,
} from "lucide-react";

import { errorMessage, request } from "../api";
import type { WorkbenchController } from "../hooks/useWorkbench";
import { documentOutline, referencesFor, symbolFor, type AuthoringTarget } from "../authoring";
import type { AuthoringLocation, DiagnosticItem, DocumentFocusMode, DocumentItem, DocumentPayload, OperationResult, TemplateItem, TutorialItem } from "../types";
import { CodeEditor, type CodeEditorHandle, type EditorCursorContext } from "../components/CodeEditor";
import { DocumentPreview } from "../components/DocumentPreview";
import { DocumentRelationshipPreview } from "../components/DocumentRelationshipPreview";
import { EmptyState, LoadingState, TechnicalResult } from "../components/ui";
import { openSyntaxReference, syntaxTopicForDiagnostic } from "../syntaxHelp";

interface DocumentsViewProps {
  controller: WorkbenchController;
  focusMode: DocumentFocusMode;
  onFocusModeChange(mode: DocumentFocusMode): void;
}

function diagnosticPath(item: DiagnosticItem, workspace?: string): string {
  let path = item.location?.path || "工作区";
  if (workspace && path.startsWith(workspace)) path = path.slice(workspace.length).replace(/^[/\\]/, "");
  return path;
}

function templateOrigin(item: TemplateItem): string {
  if (item.origin === "tutorial") return "教程";
  if (item.origin === "workspace") return "工作区";
  if (item.origin === "package") return `${item.package_name}@${item.package_version}`;
  return "内置";
}

function documentIcon(item: DocumentItem) {
  if (item.package) return <PackageIcon size={15} strokeWidth={1.55} />;
  return <FileText size={15} strokeWidth={1.55} />;
}

function sourceEntryId(source: string): string | null {
  return source.match(/^@entry\s+([A-Za-z_][A-Za-z0-9_]*)$/m)?.[1] ?? null;
}

function isSafeDocumentPath(value: string): boolean {
  if (!value.startsWith("entries/") || !value.endsWith(".kirin") || value.includes("\\") || value.includes("\0")) return false;
  const segments = value.split("/");
  return segments.length >= 2 && segments.every((segment) => segment !== "" && segment !== "." && segment !== "..");
}

const fullWidthSyntax: Record<string, string> = { "：": ":", "，": ",", "（": "(", "）": ")", "＝": "=", "％": "%" };

export function DocumentsView({ controller, focusMode, onFocusModeChange }: DocumentsViewProps) {
  const [filter, setFilter] = useState("");
  const [newDocumentOpened, setNewDocumentOpened] = useState(false);
  const [templateDrawerOpened, setTemplateDrawerOpened] = useState(false);
  const [tutorialDrawerOpened, setTutorialDrawerOpened] = useState(false);
  const [selectedTutorialId, setSelectedTutorialId] = useState<string | null>(null);
  const [tutorialDocumentId, setTutorialDocumentId] = useState("");
  const [copyingTutorial, setCopyingTutorial] = useState(false);
  const [saveTemplateOpened, setSaveTemplateOpened] = useState(false);
  const [deleteTemplate, setDeleteTemplate] = useState<TemplateItem | null>(null);
  const [selectedTemplate, setSelectedTemplate] = useState<string | null>(null);
  const [documentId, setDocumentId] = useState("");
  const [templateId, setTemplateId] = useState("");
  const [creating, setCreating] = useState(false);
  const [inspectorTab, setInspectorTab] = useState<string | null>("preview");
  const [explainTarget, setExplainTarget] = useState<string | null>(null);
  const [explainResult, setExplainResult] = useState<OperationResult | null>(null);
  const [explaining, setExplaining] = useState(false);
  const [pendingLocation, setPendingLocation] = useState<{ line?: number; column?: number } | null>(null);
  const [conflictOpened, setConflictOpened] = useState(false);
  const [outlineOpened, setOutlineOpened] = useState(false);
  const [outlineFilter, setOutlineFilter] = useState("");
  const [referenceTarget, setReferenceTarget] = useState<AuthoringTarget | null>(null);
  const [renameTarget, setRenameTarget] = useState<AuthoringTarget | null>(null);
  const [renameName, setRenameName] = useState("");
  const [renaming, setRenaming] = useState(false);
  const [documentLifecycleAction, setDocumentLifecycleAction] = useState<"move" | "duplicate" | "remove" | null>(null);
  const [documentLifecycleValue, setDocumentLifecycleValue] = useState("");
  const [documentLifecycleRunning, setDocumentLifecycleRunning] = useState(false);
  const [cursorContext, setCursorContext] = useState<EditorCursorContext>({
    symbolId: null,
    containerSymbolId: null,
    callSymbolId: null,
    activeParameter: null,
    line: 1,
    column: 1,
    selectionCharacters: 0,
    selectionLines: 0,
    selectionRanges: 0,
  });
  const editorRef = useRef<CodeEditorHandle>(null);

  const current = controller.currentDocument;
  const currentText = current ? controller.buffers[current.key] ?? "" : "";
  const currentDirty = Boolean(current && controller.dirtyOverlays[current.key] !== undefined);
  const templates = controller.bootstrapData?.templates ?? [];
  const tutorials = controller.bootstrapData?.tutorials ?? [];
  const availableTemplates = templates.filter((item) => !item.error);
  const selectedTutorial = tutorials.find((item) => item.id === selectedTutorialId) ?? null;
  const emptyWorkspace = controller.documents.length === 0;
  const currentEntryId = sourceEntryId(currentText);
  const currentExplainTargets = useMemo(
    () => currentEntryId
      ? controller.workspaceIndex.targets.filter((item) => item.value.startsWith(`${currentEntryId}.`))
      : [],
    [controller.workspaceIndex.targets, currentEntryId],
  );
  const currentExplainTargetSignature = currentExplainTargets.map((item) => item.value).join("\u0000");
  const selectedExplainTarget = currentExplainTargets.find((item) => item.value === explainTarget);
  const validDocumentId = /^[A-Za-z_][A-Za-z0-9_]*$/.test(documentId.trim());
  const validTutorialDocumentId = /^[A-Za-z_][A-Za-z0-9_]*$/.test(tutorialDocumentId.trim());
  const tutorialDocumentPath = `entries/${tutorialDocumentId.trim()}.kirin`;
  const tutorialDocumentExists = controller.documents.some((item) => item.path === tutorialDocumentPath);
  const validMovePath = isSafeDocumentPath(documentLifecycleValue.trim());
  const validDuplicateId = /^[A-Za-z_][A-Za-z0-9_]*$/.test(documentLifecycleValue.trim());
  const currentOutline = useMemo(
    () => current ? documentOutline(controller.authoringIndex, current.key) : [],
    [controller.authoringIndex, current],
  );
  const filteredOutline = useMemo(() => {
    const query = outlineFilter.trim().toLocaleLowerCase();
    return currentOutline.filter((item) => !query || `${item.label} ${item.name} ${item.id} ${item.kind}`.toLocaleLowerCase().includes(query));
  }, [currentOutline, outlineFilter]);
  const activeSymbolId = cursorContext.containerSymbolId ?? cursorContext.symbolId;
  const activeRenameSymbol = symbolFor(controller.authoringIndex, cursorContext.symbolId);
  const callSymbol = symbolFor(controller.authoringIndex, cursorContext.callSymbolId)
    ?? controller.authoringIndex.builtins.find((item) => item.id === cursorContext.callSymbolId)
    ?? null;
  const referenceLocations = referenceTarget ? [
    ...(referenceTarget.symbol ? [{ symbol_id: referenceTarget.id, text: "定义", location: referenceTarget.symbol.definition, via_alias: false }] : []),
    ...referencesFor(controller.authoringIndex, referenceTarget.id),
  ] : [];

  useEffect(() => {
    if (controller.externalConflict) setConflictOpened(true);
  }, [controller.externalConflict]);

  useEffect(() => {
    if (!selectedTemplate && availableTemplates.length) setSelectedTemplate(availableTemplates[0].value);
  }, [availableTemplates, selectedTemplate]);

  useEffect(() => {
    if (!selectedTutorialId && tutorials.length) {
      setSelectedTutorialId(tutorials[0].id);
      setTutorialDocumentId(tutorials[0].document_id);
    }
  }, [selectedTutorialId, tutorials]);

  useEffect(() => {
    setExplainTarget((selected) => (
      selected && currentExplainTargets.some((item) => item.value === selected)
        ? selected
        : currentExplainTargets[0]?.value ?? null
    ));
  }, [current?.key, currentExplainTargetSignature]);

  useEffect(() => {
    setCursorContext({ symbolId: null, containerSymbolId: null, callSymbolId: null, activeParameter: null, line: 1, column: 1, selectionCharacters: 0, selectionLines: 0, selectionRanges: 0 });
    setOutlineFilter("");
    setReferenceTarget(null);
    setRenameTarget(null);
  }, [current?.key]);

  useEffect(() => {
    if (activeSymbolId && currentExplainTargets.some((item) => item.value === activeSymbolId)) {
      setExplainTarget(activeSymbolId);
    }
  }, [activeSymbolId, currentExplainTargetSignature]);

  useEffect(() => {
    if (inspectorTab !== "formula" || !explainTarget || controller.validation?.status !== "ok") {
      setExplaining(false);
      setExplainResult(null);
      return;
    }

    let active = true;
    setExplaining(true);
    setExplainResult(null);
    const timer = window.setTimeout(() => {
      void (async () => {
        try {
          const result = await controller.operation("explain", { target: explainTarget });
          if (active) setExplainResult(result);
        } catch {
          if (active) setExplainResult(null);
        } finally {
          if (active) setExplaining(false);
        }
      })();
    }, 650);

    return () => {
      active = false;
      window.clearTimeout(timer);
    };
  }, [controller.operation, controller.validation?.status, currentText, explainTarget, inspectorTab]);

  useEffect(() => {
    if (!pendingLocation || !current) return;
    const timer = window.setTimeout(() => {
      editorRef.current?.focusAt(pendingLocation.line, pendingLocation.column);
      setPendingLocation(null);
    }, 60);
    return () => window.clearTimeout(timer);
  }, [current, pendingLocation]);

  const filteredDocuments = useMemo(() => {
    const query = filter.trim().toLocaleLowerCase();
    return controller.documents.filter((item) => {
      const packageLabel = item.package ? `${item.package.name} ${item.package.version}` : "";
      return !query || `${item.title} ${item.path} ${packageLabel}`.toLocaleLowerCase().includes(query);
    });
  }, [controller.documents, filter]);

  const groupedDocuments = useMemo(() => ({
    workspace: filteredDocuments.filter((item) => !item.package),
    packages: filteredDocuments.filter((item) => item.package),
  }), [filteredDocuments]);

  useEffect(() => {
    const navigate = (event: Event) => {
      const detail = (event as CustomEvent<{ key?: string; line?: number; column?: number }>).detail;
      if (!detail) return;
      if (detail.key && detail.key !== controller.currentKey) void controller.openDocument(detail.key);
      setPendingLocation({ line: detail.line, column: detail.column });
    };
    window.addEventListener("kirin:navigate-source", navigate);
    return () => window.removeEventListener("kirin:navigate-source", navigate);
  }, [controller.currentKey, controller.openDocument]);

  const currentDiagnostics = useMemo(() => {
    if (!current) return [];
    return controller.validationItems.filter((item) => {
      const path = diagnosticPath(item, controller.bootstrapData?.workspace);
      return path === current.path || path.endsWith(current.path);
    });
  }, [controller.bootstrapData?.workspace, controller.validationItems, current]);

  const navigateToSource = (key: string, line?: number | null, column?: number | null) => {
    onFocusModeChange("split");
    window.dispatchEvent(new CustomEvent("kirin:navigate-source", { detail: { key, line, column } }));
  };

  const openDiagnostic = async (item: DiagnosticItem) => {
    onFocusModeChange("split");
    const path = diagnosticPath(item, controller.bootstrapData?.workspace);
    const match = controller.documents.find((document) => document.path === path || path.endsWith(document.path));
    if (match) await controller.openDocument(match.key);
    setPendingLocation({ line: item.location?.line, column: item.location?.column });
  };

  const navigateToLocation = (location: AuthoringLocation) => {
    navigateToSource(location.key, location.line, location.column);
  };

  const openRename = (target: AuthoringTarget) => {
    if (!target.symbol?.renameable) return;
    setRenameTarget(target);
    setRenameName(target.symbol.name);
  };

  const handleRename = async () => {
    if (!renameTarget?.symbol || !/^[A-Za-z_][A-Za-z0-9_]*$/.test(renameName) || renaming) return;
    setRenaming(true);
    try {
      await controller.renameSymbol(renameTarget.symbol.id, renameName);
      setRenameTarget(null);
    } catch (error) {
      notifications.show({ color: "red", title: "无法重命名", message: errorMessage(error), autoClose: false });
    } finally {
      setRenaming(false);
    }
  };

  const fixDiagnostic = async (item: DiagnosticItem) => {
    const path = diagnosticPath(item, controller.bootstrapData?.workspace);
    const document = controller.documents.find((candidate) => candidate.path === path || path.endsWith(candidate.path));
    if (!document || document.read_only) return;
    const opened = Object.prototype.hasOwnProperty.call(controller.buffers, document.key)
      ? null
      : await request<DocumentPayload>(`/api/document?key=${encodeURIComponent(document.key)}`);
    await controller.openDocument(document.key);
    const source = controller.buffers[document.key] ?? opened?.text ?? "";
    const lines = source.split("\n");
    const lineIndex = Math.max(0, Math.min(lines.length - 1, (item.location?.line ?? 1) - 1));
    const fixed = Array.from(lines[lineIndex]).map((character) => fullWidthSyntax[character] ?? character).join("");
    if (fixed === lines[lineIndex]) return;
    lines[lineIndex] = fixed;
    controller.updateBuffer(document.key, lines.join("\n"));
    await controller.openDocument(document.key);
    setPendingLocation({ line: lineIndex + 1, column: item.location?.column });
  };

  const handleCreateDocument = async () => {
    if (!selectedTemplate || !validDocumentId || creating) return;
    setCreating(true);
    try {
      await controller.createDocument(selectedTemplate, documentId.trim());
      setNewDocumentOpened(false);
      setDocumentId("");
      notifications.show({ color: "orange", title: "草稿已创建", message: "文档尚未写入磁盘；保存全部后才会成为工作区源码。" });
    } catch (error) {
      notifications.show({ color: "red", title: "无法创建文档", message: errorMessage(error) });
    } finally {
      setCreating(false);
    }
  };

  const openTutorial = (tutorial?: TutorialItem) => {
    const selected = tutorial ?? selectedTutorial ?? tutorials[0];
    if (!selected) return;
    setSelectedTutorialId(selected.id);
    setTutorialDocumentId(selected.document_id);
    setTutorialDrawerOpened(true);
  };

  const selectTutorial = (tutorial: TutorialItem) => {
    setSelectedTutorialId(tutorial.id);
    setTutorialDocumentId(tutorial.document_id);
  };

  const handleCopyTutorial = async () => {
    if (!selectedTutorial || !validTutorialDocumentId || tutorialDocumentExists || copyingTutorial) return;
    setCopyingTutorial(true);
    try {
      await controller.createDocument(selectedTutorial.template, tutorialDocumentId.trim());
      setTutorialDrawerOpened(false);
      notifications.show({
        color: "orange",
        title: "教程已复制为草稿",
        message: `${tutorialDocumentPath} 尚未写入磁盘；可以先编辑和预览，再使用“保存全部”。`,
      });
    } catch (error) {
      notifications.show({ color: "red", title: "无法复制教程", message: errorMessage(error), autoClose: false });
    } finally {
      setCopyingTutorial(false);
    }
  };

  const openDocumentLifecycle = (action: "move" | "duplicate" | "remove") => {
    if (!current) return;
    setDocumentLifecycleAction(action);
    setDocumentLifecycleValue(action === "move" ? current.path : "");
  };

  const handleDocumentLifecycle = async () => {
    if (!current || !documentLifecycleAction || documentLifecycleRunning) return;
    setDocumentLifecycleRunning(true);
    try {
      const payload: Record<string, unknown> = {
        key: current.key,
        expected_sha256: controller.hashes[current.key],
      };
      if (documentLifecycleAction === "move") payload.destination = documentLifecycleValue.trim();
      if (documentLifecycleAction === "duplicate") payload.document_id = documentLifecycleValue.trim();
      await controller.documentAction(documentLifecycleAction, payload);
      setDocumentLifecycleAction(null);
      setDocumentLifecycleValue("");
    } catch (error) {
      notifications.show({ color: "red", title: "文档操作未完成", message: errorMessage(error), autoClose: false });
    } finally {
      setDocumentLifecycleRunning(false);
    }
  };

  const handleSaveTemplate = async () => {
    if (!current || !templateId.trim()) return;
    if (currentDirty) {
      notifications.show({ color: "red", message: "请先保存当前文档，再将它保存为创建模板。" });
      return;
    }
    const header = currentText.match(/^@entry\s+([A-Za-z_][A-Za-z0-9_]*)$/m);
    if (!header) {
      notifications.show({ color: "red", message: "当前源码没有有效的 @entry 文档头。" });
      return;
    }
    try {
      await controller.templateAction("save", { document_id: header[1], template_id: templateId.trim() });
      setSaveTemplateOpened(false);
      setTemplateId("");
      notifications.show({ color: "green", message: "创建模板已保存到工作区。" });
    } catch (error) {
      notifications.show({ color: "red", title: "无法保存模板", message: errorMessage(error) });
    }
  };

  const handleDeleteTemplate = async () => {
    if (!deleteTemplate) return;
    try {
      await controller.templateAction("remove", { template: deleteTemplate.value });
      notifications.show({ color: "green", message: "工作区模板已删除；由它生成的现有文档没有改变。" });
      setDeleteTemplate(null);
    } catch (error) {
      notifications.show({ color: "red", title: "无法删除模板", message: errorMessage(error) });
    }
  };

  if (!controller.bootstrapData && controller.asyncState === "connecting") {
    return <LoadingState label="正在读取工作区…" />;
  }

  return (
    <>
      <div className={`documents-workspace is-focus-${focusMode}${emptyWorkspace ? " is-empty" : ""}`} id="documents-layout">
        {!emptyWorkspace && focusMode === "split" && <section className="workspace-panel explorer-panel" aria-label="文档索引">
          <div className="panel-toolbar">
            <Group justify="space-between" wrap="nowrap">
              <Text fw={650} fz="sm">工作区文档</Text>
              <Group gap={4} wrap="nowrap">
                <Tooltip label="教程与示例"><ActionIcon variant="subtle" color="gray" aria-label="教程与示例" onClick={() => openTutorial()}><BookOpen size={14} /></ActionIcon></Tooltip>
                <Tooltip label="管理创建模板"><ActionIcon variant="subtle" color="gray" aria-label="管理创建模板" onClick={() => setTemplateDrawerOpened(true)}><BookTemplate size={14} /></ActionIcon></Tooltip>
                <Tooltip label="新建文档"><ActionIcon aria-label="新建文档" onClick={() => setNewDocumentOpened(true)}><FilePlus2 size={14} /></ActionIcon></Tooltip>
              </Group>
            </Group>
          </div>
          <Box className="explorer-controls">
            <TextInput
              value={filter}
              onChange={(event) => setFilter(event.currentTarget.value)}
              placeholder="搜索文档"
              leftSection={<Search size={14} strokeWidth={1.7} />}
              size="xs"
            />
          </Box>
          <ScrollArea className="document-scroll" type="auto">
            {groupedDocuments.workspace.length > 0 && (
              <Box className="document-group">
                <Text className="document-group-label">本地源码</Text>
                {groupedDocuments.workspace.map((item) => (
                  <button
                    className={`document-list-row${item.key === controller.currentKey ? " is-active" : ""}`}
                    key={item.key}
                    type="button"
                    onClick={() => { void controller.openDocument(item.key); }}
                  >
                    <span className="document-kind-icon">{documentIcon(item)}</span>
                    <span className="document-list-copy">
                      <strong>{item.title}</strong>
                      <small>{item.path}</small>
                    </span>
                    {controller.dirtyOverlays[item.key] !== undefined && <span className="dirty-dot" title="未保存" />}
                  </button>
                ))}
              </Box>
            )}
            {groupedDocuments.packages.length > 0 && (
              <Box className="document-group">
                <Text className="document-group-label">Package 源码</Text>
                {groupedDocuments.packages.map((item) => (
                  <button
                    className={`document-list-row${item.key === controller.currentKey ? " is-active" : ""}`}
                    key={item.key}
                    type="button"
                    onClick={() => { void controller.openDocument(item.key); }}
                  >
                    <span className="document-kind-icon">{documentIcon(item)}</span>
                    <span className="document-list-copy">
                      <strong>{item.title}</strong>
                      <small>{item.package?.name}@{item.package?.version}</small>
                    </span>
                  </button>
                ))}
              </Box>
            )}
            {!filteredDocuments.length && (
              <EmptyState title="没有匹配的文档" description="调整搜索词。" />
            )}
          </ScrollArea>
        </section>}

        <section className="workspace-panel editor-panel" aria-label="源码编辑器">
          {emptyWorkspace ? (
            <div className="workspace-welcome" aria-label="Kirin 入门">
              <section className="workspace-welcome-intro">
                <Text className="page-kicker">GET STARTED</Text>
                <Title order={1}>从一份真正的 Kirin 源码开始</Title>
                <Text c="dimmed" maw={720}>
                  当前工作区仍然为空。内置教程只读展示完整 `.kirin`；只有主动复制后，它才会成为当前工作区中的未保存草稿。
                </Text>
                <Group gap="xs" mt="lg">
                  <Button className="tutorial-primary-action" leftSection={<ArrowRight size={14} />} onClick={() => openTutorial(tutorials[0])}>开始基础教程</Button>
                  <Button variant="default" leftSection={<FilePlus2 size={14} />} onClick={() => setNewDocumentOpened(true)}>新建空白文档</Button>
                  <Button variant="subtle" leftSection={<BookOpen size={14} />} onClick={() => openSyntaxReference("document")}>打开语法参考</Button>
                </Group>
              </section>

              <section className="workspace-tutorials" aria-labelledby="workspace-tutorial-heading">
                <Group justify="space-between" align="end" mb="md">
                  <Box>
                    <Text className="page-kicker">BUILT-IN TUTORIALS</Text>
                    <Title id="workspace-tutorial-heading" order={2}>三个虚构、游戏中立的练习</Title>
                  </Box>
                  <Text c="dimmed" fz="xs">查看源码不会修改工作区</Text>
                </Group>
                <div className="workspace-tutorial-grid">
                  {tutorials.map((tutorial, index) => (
                    <article className="workspace-tutorial-card" key={tutorial.id}>
                      <Group justify="space-between" align="flex-start" wrap="nowrap">
                        <span className="workspace-tutorial-number">0{index + 1}</span>
                        <Badge size="xs" color="gray" variant="light">{tutorial.duration}</Badge>
                      </Group>
                      <Title order={3}>{tutorial.title}</Title>
                      <Text c="dimmed" fz="xs">{tutorial.description}</Text>
                      <ul>
                        {tutorial.learning_points.map((point) => <li key={point}>{point}</li>)}
                      </ul>
                      <Button variant="default" rightSection={<ArrowRight size={13} />} onClick={() => openTutorial(tutorial)}>查看完整源码</Button>
                    </article>
                  ))}
                </div>
              </section>

              <section className="workspace-authority-note">
                <FileCode2 size={18} />
                <Box>
                  <Text fw={650} fz="sm">教程不是工作区数据</Text>
                  <Text c="dimmed" fz="xs" mt={3}>它不会参加校验、计算、搜索或保存；复制后生成的 `.kirin` 草稿才进入这些流程。</Text>
                </Box>
              </section>
            </div>
          ) : current ? (
            <>
              <div className="editor-commandbar">
                <Group justify="space-between" wrap="nowrap">
                  <Group gap="xs" wrap="nowrap" className="editor-file-identity">
                    {current.package ? <PackageOpen size={16} strokeWidth={1.6} /> : <FileCode2 size={16} strokeWidth={1.6} />}
                    <Box>
                      <Group gap={6} wrap="nowrap">
                        <Text fw={650} fz="sm" truncate>{current.title}</Text>
                        {current.read_only && <Badge size="xs" color="gray" variant="light">只读</Badge>}
                        {currentDirty && <Badge size="xs" color="orange" variant="light">已修改</Badge>}
                      </Group>
                      <Text c="dimmed" fz="10px" ff="monospace" truncate>{current.path}</Text>
                    </Box>
                  </Group>
                  <Group gap={4} wrap="nowrap">
                    <Popover opened={outlineOpened} onChange={setOutlineOpened} position="bottom-end" width={330} withinPortal>
                      <Popover.Target>
                        <Tooltip label="文档符号大纲 · ⌘⇧O">
                          <ActionIcon variant="subtle" color="gray" aria-label="文档符号大纲" onClick={() => setOutlineOpened((opened) => !opened)}>
                            <ListTree size={15} />
                          </ActionIcon>
                        </Tooltip>
                      </Popover.Target>
                      <Popover.Dropdown className="outline-popover">
                        <TextInput
                          size="xs"
                          autoFocus
                          value={outlineFilter}
                          onChange={(event) => setOutlineFilter(event.currentTarget.value)}
                          placeholder="搜索当前文档符号"
                          leftSection={<Search size={13} />}
                        />
                        <ScrollArea h={320} mt="xs" type="auto">
                          <div className="outline-list" role="list" aria-label="当前文档符号">
                            {filteredOutline.map((item) => (
                              <div role="listitem" key={item.id}>
                                <button
                                  type="button"
                                  style={{ paddingLeft: 9 + item.outline_level * 14 }}
                                  onClick={() => { setOutlineOpened(false); navigateToLocation(item.definition); }}
                                >
                                  <strong>{item.label}</strong>
                                  <small>{item.kind} · 第 {item.definition.line} 行</small>
                                </button>
                              </div>
                            ))}
                          </div>
                        </ScrollArea>
                      </Popover.Dropdown>
                    </Popover>
                    {controller.externalConflict && (
                      <Tooltip label="比较外部修改">
                        <ActionIcon variant="subtle" color="orange" aria-label="比较外部修改" onClick={() => setConflictOpened(true)}>
                          <GitCompare size={15} />
                        </ActionIcon>
                      </Tooltip>
                    )}
                    <Tooltip label={`保存全部${controller.dirtyCount ? `（${controller.dirtyCount} 个草稿）` : ""} · ⌘S`}>
                      <ActionIcon
                        variant="subtle"
                        color="gray"
                        aria-label="保存全部"
                        onClick={() => { void controller.saveAll(); }}
                        disabled={!controller.dirtyCount}
                      >
                        <Save size={15} />
                      </ActionIcon>
                    </Tooltip>
                    <Menu position="bottom-end" withinPortal>
                      <Menu.Target>
                        <ActionIcon variant="subtle" color="gray" aria-label="文档操作"><MoreHorizontal size={16} /></ActionIcon>
                      </Menu.Target>
                      <Menu.Dropdown>
                        <Menu.Label>文档操作</Menu.Label>
                        <Menu.Item
                          leftSection={<Braces size={14} />}
                          disabled={current.read_only || !activeRenameSymbol?.renameable}
                          onClick={() => {
                            if (activeRenameSymbol) openRename({ id: activeRenameSymbol.id, symbol: activeRenameSymbol, definition: activeRenameSymbol.definition });
                          }}
                        >
                          重命名光标处成员 <span className="menu-shortcut">F2</span>
                        </Menu.Item>
                        <Menu.Item
                          leftSection={<WandSparkles size={14} />}
                          disabled={current.read_only}
                          onClick={() => { void controller.formatDocument(current.key).catch((error) => notifications.show({ color: "red", title: "无法格式化", message: errorMessage(error) })); }}
                        >
                          格式化文档 <span className="menu-shortcut">⌘⇧F</span>
                        </Menu.Item>
                        <Menu.Item
                          leftSection={<BookTemplate size={14} />}
                          disabled={current.read_only || currentDirty}
                          onClick={() => setSaveTemplateOpened(true)}
                        >
                          保存为创建模板
                        </Menu.Item>
                        <Menu.Divider />
                        <Menu.Label>文件管理</Menu.Label>
                        <Menu.Item
                          leftSection={<FolderInput size={14} />}
                          disabled={current.read_only || controller.dirtyCount > 0}
                          onClick={() => openDocumentLifecycle("move")}
                        >
                          移动文件路径
                        </Menu.Item>
                        <Menu.Item
                          leftSection={<Copy size={14} />}
                          disabled={current.read_only || controller.dirtyCount > 0}
                          onClick={() => openDocumentLifecycle("duplicate")}
                        >
                          复制为新文档草稿
                        </Menu.Item>
                        <Menu.Item
                          color="red"
                          leftSection={<Trash2 size={14} />}
                          disabled={current.read_only || controller.dirtyCount > 0}
                          onClick={() => openDocumentLifecycle("remove")}
                        >
                          移到恢复区
                        </Menu.Item>
                        {controller.dirtyCount > 0 && <Menu.Label>先保存或处理全部草稿，才能改变文件结构</Menu.Label>}
                      </Menu.Dropdown>
                    </Menu>
                  </Group>
                </Group>
              </div>
              <div className="editor-stage">
                <CodeEditor
                  key={current.key}
                  ref={editorRef}
                  documentKey={current.key}
                  value={currentText}
                  ariaLabel={`Kirin 源码：${current.title}`}
                  readOnly={current.read_only}
                  diagnostics={currentDiagnostics}
                  authoring={controller.authoringIndex}
                  onChange={(text) => controller.updateBuffer(current.key, text)}
                  onComplete={(prefix) => controller.completions(current.key, prefix)}
                  onSave={() => { void controller.saveAll(); }}
                  onNavigate={navigateToLocation}
                  onShowReferences={setReferenceTarget}
                  onRename={openRename}
                  onCursorContext={setCursorContext}
                  onFormat={() => { if (!current.read_only) void controller.formatDocument(current.key); }}
                  onOpenOutline={() => setOutlineOpened(true)}
                />
              </div>
              <div className="editor-statusbar">
                <span>{currentDiagnostics.length ? `${currentDiagnostics.length} 个当前文档问题` : "当前文档有效"}</span>
                <span className="editor-signature-hint">{callSymbol?.signature ? `${callSymbol.signature}${cursorContext.activeParameter ? ` · 参数 ${cursorContext.activeParameter}` : ""}` : "Kirin 文档"}</span>
                <span
                  className={`editor-cursor-status${cursorContext.selectionCharacters ? " is-selection" : ""}`}
                  aria-live="polite"
                >
                  {cursorContext.selectionCharacters
                    ? `${cursorContext.selectionRanges > 1 ? `${cursorContext.selectionRanges} 处 · ` : ""}已选 ${cursorContext.selectionCharacters} 字符${cursorContext.selectionLines > 1 ? ` / ${cursorContext.selectionLines} 行` : ""}`
                    : `行 ${cursorContext.line}，列 ${cursorContext.column}`}
                </span>
                <span>UTF-8</span>
                {!current.read_only && <span>补全 ⌃Space · 定义 F12 · 引用 ⇧F12 · 改名 F2</span>}
              </div>
            </>
          ) : (
            <EmptyState
              title="选择一个文档开始创作"
              description="左侧列出了工作区源码以及来自已安装 Package 的只读源码。"
              action={<Button size="xs" leftSection={<FilePlus2 size={14} />} onClick={() => setNewDocumentOpened(true)}>新建文档</Button>}
            />
          )}
        </section>

        {!emptyWorkspace && focusMode !== "editor" && <aside className="workspace-panel inspector-panel" aria-label="文档检查器">
          <Tabs value={inspectorTab} onChange={setInspectorTab} className="inspector-tabs" keepMounted={false}>
            <Tabs.List grow>
              <Tabs.Tab value="preview" leftSection={<Eye size={13} />}>预览</Tabs.Tab>
              <Tabs.Tab value="relationships" leftSection={<Network size={13} />}>关系</Tabs.Tab>
              <Tabs.Tab value="diagnostics" leftSection={controller.validationItems.length ? <CircleAlert size={13} /> : <CircleCheck size={13} />}>
                诊断{controller.validationItems.length ? ` ${controller.validationItems.length}` : ""}
              </Tabs.Tab>
              <Tabs.Tab value="formula" leftSection={<Braces size={13} />}>公式</Tabs.Tab>
            </Tabs.List>
            <Tabs.Panel value="preview" className="inspector-content">
              {current ? <DocumentPreview controller={controller} document={current} source={currentText} activeSymbolId={activeSymbolId} onNavigateToSource={(line, column) => navigateToSource(current.key, line, column)} /> : <EmptyState title="选择一个文档" description="结果和图表会从当前文档源码按需出现。" />}
            </Tabs.Panel>
            <Tabs.Panel value="relationships" className="inspector-content">
              {current ? <DocumentRelationshipPreview controller={controller} documentKey={current.key} source={currentText} activeSymbolId={activeSymbolId} onNavigateToSource={navigateToSource} /> : <EmptyState title="选择一个文档" description="这里会显示当前文档的局部依赖投影。" />}
            </Tabs.Panel>
            <Tabs.Panel value="diagnostics" className="inspector-content">
              <ScrollArea h="100%" type="auto">
                {controller.validationItems.length ? (
                  <Stack gap={0}>
                    {controller.validationItems.map((item, index) => {
                      const path = diagnosticPath(item, controller.bootstrapData?.workspace);
                      const diagnosticKey = controller.documents.find((document) => document.path === path || path.endsWith(document.path))?.key ?? "";
                      const diagnosticLine = (controller.buffers[diagnosticKey] ?? "").split("\n")[(item.location?.line ?? 1) - 1] ?? "";
                      const canFix = item.location?.line && Object.keys(fullWidthSyntax).some((character) => diagnosticLine.includes(character));
                      const syntaxTopic = syntaxTopicForDiagnostic(item, diagnosticLine);
                      return (
                        <div className="diagnostic-row-wrap" key={`${path}-${item.location?.line}-${index}`}>
                          <button className="diagnostic-row" type="button" onClick={() => { void openDiagnostic(item); }}>
                            <span className="diagnostic-severity"><CircleAlert size={15} /></span>
                            <span>
                              <strong>{item.author_message || item.message || "校验错误"}</strong>
                              <small>{path}{item.location?.line ? `:${item.location.line}` : ""} · {item.code || "error"}</small>
                            </span>
                          </button>
                          {canFix && <Button variant="subtle" color="gray" size="compact-xs" onClick={() => { void fixDiagnostic(item); }}>修复全角符号</Button>}
                          <Button variant="subtle" color="gray" size="compact-xs" onClick={() => openSyntaxReference(syntaxTopic)}>查看相关语法</Button>
                        </div>
                      );
                    })}
                  </Stack>
                ) : (
                  <EmptyState
                    icon={<CircleCheck size={23} strokeWidth={1.5} />}
                    title="没有发现问题"
                    description={`${controller.validation?.documents ?? controller.documents.filter((item) => !item.package).length} 个本地文档可以参与计算。`}
                  />
                )}
              </ScrollArea>
            </Tabs.Panel>
            <Tabs.Panel value="formula" className="inspector-content">
              <ScrollArea h="100%" type="auto">
                <Stack p="md" gap="md">
                  <Box>
                    <Text fw={650} fz="sm">公式与依赖</Text>
                    <Text c="dimmed" fz="xs" mt={3}>从当前草稿解释一个结果，不会修改源码。</Text>
                  </Box>
                  {currentExplainTargets.length > 1 && <Select
                    label="查看结果"
                    placeholder="选择一个结果"
                    searchable
                    value={explainTarget}
                    onChange={(value) => { setExplainTarget(value); setExplainResult(null); }}
                    data={currentExplainTargets.map((item) => ({
                      value: item.value,
                      label: `${item.group_label || "未分组"} / ${item.label}`,
                    }))}
                  />}
                  {selectedExplainTarget && <Group justify="space-between" wrap="nowrap"><Box><Text className="result-label">当前结果</Text><Code>{selectedExplainTarget.value}</Code></Box>{current && selectedExplainTarget.line && <Button variant="subtle" color="gray" size="compact-xs" leftSection={<Crosshair size={13} />} onClick={() => navigateToSource(current.key, selectedExplainTarget.line, selectedExplainTarget.column)}>定位公式源码</Button>}</Group>}
                  {currentExplainTargets.length === 0 && <EmptyState title="这个文档没有结果输出" description="定义 output 后，表达式和依赖会自动出现在这里。" />}
                  {explaining && <LoadingState label="正在解释公式…" />}
                  {explainResult && (
                    <Stack gap="sm" className="formula-result">
                      {typeof explainResult.expression === "string" && (
                        <Box><Text className="result-label">表达式</Text><Code block>{explainResult.expression}</Code></Box>
                      )}
                      {Array.isArray(explainResult.dependencies) && (
                        <Box>
                          <Text className="result-label">依赖</Text>
                          <Stack gap={4} mt={6}>{explainResult.dependencies.map((dependency) => <Code key={String(dependency)}>{String(dependency)}</Code>)}</Stack>
                        </Box>
                      )}
                      <TechnicalResult result={explainResult} />
                    </Stack>
                  )}
                </Stack>
              </ScrollArea>
            </Tabs.Panel>
          </Tabs>
        </aside>}
      </div>

      <Modal opened={newDocumentOpened} onClose={() => setNewDocumentOpened(false)} title="新建文档" centered>
        <Stack gap="md">
          <Box>
            <Text fz="sm" fw={620}>从一次性模板创建</Text>
            <Text c="dimmed" fz="xs" mt={3}>模板只在创建时展开为完整源码，此后文档独立成为权威。</Text>
          </Box>
          <Select
            label="创建模板"
            searchable
            value={selectedTemplate}
            onChange={setSelectedTemplate}
            data={availableTemplates.map((item) => ({
              value: item.value,
              label: `${templateOrigin(item)} / ${item.label} · ${item.kind}`,
            }))}
          />
          <TextInput
            label="文档 ID"
            description="ASCII 字母、数字和下划线；必须以字母或下划线开头。"
            placeholder="example_model"
            value={documentId}
            onChange={(event) => setDocumentId(event.currentTarget.value)}
            error={documentId && !validDocumentId ? "文档 ID 格式无效" : null}
            onKeyDown={(event) => {
              if (event.key !== "Enter") return;
              event.preventDefault();
              if (selectedTemplate && validDocumentId && !creating) void handleCreateDocument();
            }}
          />
          <Group justify="flex-end">
            <Button variant="default" onClick={() => setNewDocumentOpened(false)}>取消</Button>
            <Button
              loading={creating}
              disabled={!selectedTemplate || !validDocumentId}
              onClick={() => { void handleCreateDocument(); }}
            >
              创建草稿
            </Button>
          </Group>
        </Stack>
      </Modal>

      <Modal
        opened={documentLifecycleAction !== null}
        onClose={() => setDocumentLifecycleAction(null)}
        title={documentLifecycleAction === "move" ? "移动文档文件" : documentLifecycleAction === "duplicate" ? "复制为新文档" : "移到恢复区"}
        centered
      >
        {current && <Stack gap="md">
          <Box>
            <Text fz="sm" fw={650}>{current.path}</Text>
            <Text c="dimmed" fz="xs" mt={4}>
              {documentLifecycleAction === "move" && "只改变 entries/ 下的文件路径，不会修改源码中的 @entry ID、别名或任何数学语义。"}
              {documentLifecycleAction === "duplicate" && "复制会生成新的 @entry ID，并把对原文档自身的正式引用改为新 ID；结果先成为未保存草稿。"}
              {documentLifecycleAction === "remove" && "文件会移入 .kirin/trash/documents；如果删除会破坏工作区引用或校验，操作会自动撤销。"}
            </Text>
          </Box>
          {documentLifecycleAction === "move" && <TextInput
            label="目标文件路径"
            description="必须位于 entries/ 内并以 .kirin 结尾。"
            value={documentLifecycleValue}
            onChange={(event) => setDocumentLifecycleValue(event.currentTarget.value)}
            error={documentLifecycleValue && !validMovePath ? "请输入安全的 entries/.../*.kirin 路径" : null}
          />}
          {documentLifecycleAction === "duplicate" && <TextInput
            label="新文档 ID"
            description="ASCII 字母、数字和下划线；必须以字母或下划线开头。"
            value={documentLifecycleValue}
            onChange={(event) => setDocumentLifecycleValue(event.currentTarget.value)}
            error={documentLifecycleValue && !validDuplicateId ? "文档 ID 格式无效" : null}
          />}
          <Divider />
          <Group justify="flex-end">
            <Button variant="default" onClick={() => setDocumentLifecycleAction(null)}>取消</Button>
            <Button
              className={documentLifecycleAction === "remove" ? "danger-button" : undefined}
              loading={documentLifecycleRunning}
              disabled={documentLifecycleAction === "move" ? !validMovePath : documentLifecycleAction === "duplicate" ? !validDuplicateId : false}
              onClick={() => { void handleDocumentLifecycle(); }}
            >
              {documentLifecycleAction === "move" ? "移动文件" : documentLifecycleAction === "duplicate" ? "创建复制草稿" : "移到恢复区"}
            </Button>
          </Group>
        </Stack>}
      </Modal>

      <Modal
        opened={Boolean(controller.externalConflict) && conflictOpened}
        onClose={() => setConflictOpened(false)}
        title="比较外部修改"
        size="min(1100px, 94vw)"
        centered
      >
        {controller.externalConflict && (
          <Stack gap="md">
            <Text fz="sm">磁盘上的 <strong>{controller.externalConflict.path}</strong> 已被其他程序修改。当前草稿尚未覆盖磁盘。</Text>
            <Text c="dimmed" fz="xs">
              {controller.externalConflict.base == null
                ? "恢复草稿缺少可验证的共同基线，因此不能自动三方合并；仍可下载草稿或重新加载磁盘版本。"
                : "共同基线、当前草稿和磁盘版本会并排显示。三方合并结果先回到编辑器；重叠修改会留下明确冲突标记。"}
            </Text>
            <div className={`conflict-comparison${controller.externalConflict.base != null ? " is-three-way" : ""}`} aria-label="草稿、基线与磁盘版本比较">
              {controller.externalConflict.base != null && <section>
                <Text fw={650} fz="sm">共同基线</Text>
                <pre tabIndex={0}>{controller.externalConflict.base}</pre>
              </section>}
              <section>
                <Text fw={650} fz="sm">当前工作台草稿</Text>
                <pre tabIndex={0}>{controller.externalConflict.draft}</pre>
              </section>
              <section>
                <Text fw={650} fz="sm">当前磁盘版本</Text>
                <pre tabIndex={0}>{controller.externalConflict.disk}</pre>
              </section>
            </div>
            <Group justify="space-between">
              <Button variant="default" onClick={() => setConflictOpened(false)}>继续编辑草稿</Button>
              <Group gap="xs">
                <Button variant="default" leftSection={<FileDown size={14} />} onClick={() => { controller.keepExternalConflictDraft(); }}>保留草稿副本</Button>
                {controller.externalConflict.base != null && <Button variant="default" leftSection={<GitCompare size={14} />} onClick={() => { void controller.mergeExternalConflict().then((merged) => { if (merged) setConflictOpened(false); }); }}>三方合并为草稿</Button>}
                <Button className="danger-button" onClick={() => { void controller.reloadExternalConflict().then((reloaded) => { if (reloaded) setConflictOpened(false); }); }}>重新加载磁盘版本</Button>
              </Group>
            </Group>
          </Stack>
        )}
      </Modal>

      <Drawer
        opened={tutorialDrawerOpened}
        onClose={() => setTutorialDrawerOpened(false)}
        position="right"
        size="min(900px, 94vw)"
        title="教程与示例"
        className="tutorial-drawer"
      >
        <div className="tutorial-library">
          <nav className="tutorial-library-index" aria-label="内置教程">
            <Text className="page-kicker">LEARNING PATH</Text>
            {tutorials.map((tutorial, index) => (
              <button
                type="button"
                key={tutorial.id}
                aria-pressed={tutorial.id === selectedTutorial?.id}
                onClick={() => selectTutorial(tutorial)}
              >
                <span>0{index + 1}</span>
                <strong>{tutorial.title}</strong>
                <small>{tutorial.duration}</small>
              </button>
            ))}
            <Button variant="subtle" leftSection={<BookOpen size={14} />} onClick={() => { setTutorialDrawerOpened(false); openSyntaxReference("document"); }}>完整语法参考</Button>
          </nav>

          <ScrollArea className="tutorial-library-detail" type="auto">
            {selectedTutorial && (
              <article>
                <Text className="page-kicker">READ-ONLY KIRIN SOURCE</Text>
                <Title order={2}>{selectedTutorial.title}</Title>
                <Text c="dimmed" fz="sm" mt="xs">{selectedTutorial.description}</Text>
                <ol className="tutorial-learning-points">
                  {selectedTutorial.learning_points.map((point) => <li key={point}>{point}</li>)}
                </ol>

                <div className="tutorial-source">
                  <Group justify="space-between" className="tutorial-source-toolbar">
                    <Box>
                      <Text fw={650} fz="sm">完整示例源码</Text>
                      <Text c="dimmed" fz="xs">只读 · 尚未进入当前工作区</Text>
                    </Box>
                    <Badge size="sm" color="gray" variant="light">.kirin</Badge>
                  </Group>
                  <pre tabIndex={0}><Code>{selectedTutorial.source}</Code></pre>
                </div>

                <div className="tutorial-copy-panel">
                  <Box>
                    <Text fw={650} fz="sm">复制到当前工作区</Text>
                    <Text c="dimmed" fz="xs" mt={3}>复制只创建内存草稿；保存全部前不会写入磁盘。</Text>
                  </Box>
                  <TextInput
                    label="文档 ID"
                    description="正式 ID 会替换示例中的 @entry 和限定引用。"
                    value={tutorialDocumentId}
                    onChange={(event) => setTutorialDocumentId(event.currentTarget.value)}
                    error={
                      tutorialDocumentId && !validTutorialDocumentId
                        ? "文档 ID 格式无效"
                        : tutorialDocumentExists
                          ? "当前工作区已经有同路径文档"
                          : null
                    }
                    onKeyDown={(event) => {
                      if (event.key !== "Enter") return;
                      event.preventDefault();
                      if (validTutorialDocumentId && !tutorialDocumentExists && !copyingTutorial) void handleCopyTutorial();
                    }}
                  />
                  <Group justify="flex-end">
                    <Button variant="default" onClick={() => setTutorialDrawerOpened(false)}>关闭</Button>
                    <Button
                      className="tutorial-primary-action"
                      leftSection={<Copy size={14} />}
                      loading={copyingTutorial}
                      disabled={!validTutorialDocumentId || tutorialDocumentExists}
                      onClick={() => { void handleCopyTutorial(); }}
                    >
                      复制为未保存草稿
                    </Button>
                  </Group>
                </div>
              </article>
            )}
          </ScrollArea>
        </div>
      </Drawer>

      <Drawer opened={templateDrawerOpened} onClose={() => setTemplateDrawerOpened(false)} position="right" title="创建模板" size="md">
        <Stack gap="lg">
          <Text c="dimmed" fz="xs">模板提供带固定字段的初始源码，也可以预置图表配置。创建完成后，它不会继续影响文档。</Text>
          {templates.map((item) => (
            <Box className="template-card" key={item.value}>
              <Group justify="space-between" align="flex-start" wrap="nowrap">
                <Box>
                  <Group gap={6}>
                    <Text fw={620} fz="sm">{item.label}</Text>
                    <Badge size="xs" color={item.error ? "red" : "gray"} variant="light">{item.kind}</Badge>
                  </Group>
                  <Text c={item.error ? "red.3" : "dimmed"} fz="xs" mt={4}>{item.error || templateOrigin(item)}</Text>
                </Box>
                {item.origin === "workspace" && (
                  <ActionIcon className="danger-action" variant="subtle" onClick={() => setDeleteTemplate(item)} aria-label={`删除模板 ${item.label}`}>
                    <Trash2 size={14} />
                  </ActionIcon>
                )}
              </Group>
            </Box>
          ))}
        </Stack>
      </Drawer>

      <Modal opened={saveTemplateOpened} onClose={() => setSaveTemplateOpened(false)} title="保存为创建模板" centered>
        <Stack>
          <Text c="dimmed" fz="xs">保存的是当前已写入磁盘的源码快照。以后从它创建文档时会替换文档 ID。</Text>
          <TextInput
            label="模板 ID"
            placeholder="damage_model"
            value={templateId}
            onChange={(event) => setTemplateId(event.currentTarget.value)}
            error={templateId && !/^[A-Za-z_][A-Za-z0-9_]*$/.test(templateId) ? "模板 ID 格式无效" : null}
          />
          <Group justify="flex-end">
            <Button variant="default" onClick={() => setSaveTemplateOpened(false)}>取消</Button>
            <Button disabled={!/^[A-Za-z_][A-Za-z0-9_]*$/.test(templateId)} onClick={() => { void handleSaveTemplate(); }}>保存模板</Button>
          </Group>
        </Stack>
      </Modal>

      <Modal opened={Boolean(deleteTemplate)} onClose={() => setDeleteTemplate(null)} title="删除工作区模板" centered>
        <Stack>
          <Text fz="sm">确定删除 <strong>{deleteTemplate?.label}</strong>？</Text>
          <Text c="dimmed" fz="xs">这个操作不会修改已经由模板创建的文档。</Text>
          <Divider />
          <Group justify="flex-end">
            <Button variant="default" onClick={() => setDeleteTemplate(null)}>取消</Button>
            <Button className="danger-button" leftSection={<Trash2 size={14} />} onClick={() => { void handleDeleteTemplate(); }}>删除模板</Button>
          </Group>
        </Stack>
      </Modal>

      <Drawer
        opened={Boolean(referenceTarget)}
        onClose={() => setReferenceTarget(null)}
        position="right"
        size="md"
        title={referenceTarget ? `定义与引用 · ${referenceTarget.id}` : "定义与引用"}
      >
        <Stack gap="sm">
          <Text c="dimmed" fz="xs">引用来自当前内存草稿的只读符号投影；点击位置会返回对应 `.kirin` 源码。</Text>
          <div className="reference-list" role="list" aria-label="符号定义与引用">
            {referenceLocations.map((item, index) => (
              <div role="listitem" key={`${item.location.key}-${item.location.line}-${item.location.column}-${index}`}>
                <button
                  type="button"
                  onClick={() => { setReferenceTarget(null); navigateToLocation(item.location); }}
                >
                  <Crosshair size={14} />
                  <span>
                    <strong>{index === 0 && referenceTarget?.symbol ? "定义" : item.via_alias ? `别名引用 · ${item.text}` : `引用 · ${item.text}`}</strong>
                    <small>{item.location.path}:{item.location.line}:{item.location.column}{item.location.read_only ? " · 只读" : ""}</small>
                  </span>
                </button>
              </div>
            ))}
          </div>
          {!referenceLocations.length && <EmptyState title="没有引用位置" description="内置函数和未解析名称没有工作区定义位置。" />}
        </Stack>
      </Drawer>

      <Modal opened={Boolean(renameTarget)} onClose={() => setRenameTarget(null)} title="安全重命名符号" centered>
        <Stack gap="md">
          <Box>
            <Text fw={650} fz="sm">{renameTarget?.symbol?.id}</Text>
            <Text c="dimmed" fz="xs" mt={3}>定义、同文档短名称和跨文档正式引用会一起更新；中文别名保持不变。所有变化先进入内存草稿，并在应用前执行完整工作区校验。</Text>
          </Box>
          <TextInput
            label="新的正式名称"
            value={renameName}
            onChange={(event) => setRenameName(event.currentTarget.value)}
            error={renameName && !/^[A-Za-z_][A-Za-z0-9_]*$/.test(renameName) ? "必须是 ASCII 标识符" : null}
            onKeyDown={(event) => {
              if (event.key === "Enter") { event.preventDefault(); void handleRename(); }
            }}
          />
          <Group justify="flex-end">
            <Button variant="default" onClick={() => setRenameTarget(null)}>取消</Button>
            <Button loading={renaming} disabled={!/^[A-Za-z_][A-Za-z0-9_]*$/.test(renameName)} onClick={() => { void handleRename(); }}>重命名草稿</Button>
          </Group>
        </Stack>
      </Modal>
    </>
  );
}
