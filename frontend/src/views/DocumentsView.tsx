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
  ScrollArea,
  Select,
  Stack,
  Tabs,
  Text,
  TextInput,
  Tooltip,
} from "@mantine/core";
import { notifications } from "@mantine/notifications";
import {
  BookTemplate,
  Box as PackageIcon,
  Braces,
  CircleAlert,
  CircleCheck,
  FileCode2,
  FileDown,
  FilePlus2,
  FileText,
  GitCompare,
  Eye,
  MoreHorizontal,
  Network,
  PackageOpen,
  Save,
  Search,
  Trash2,
} from "lucide-react";

import { errorMessage } from "../api";
import type { WorkbenchController } from "../hooks/useWorkbench";
import type { DiagnosticItem, DocumentFocusMode, DocumentItem, OperationResult, TemplateItem } from "../types";
import { CodeEditor, type CodeEditorHandle } from "../components/CodeEditor";
import { DocumentPreview } from "../components/DocumentPreview";
import { DocumentRelationshipPreview } from "../components/DocumentRelationshipPreview";
import { EmptyState, LoadingState, TechnicalResult } from "../components/ui";

interface DocumentsViewProps {
  controller: WorkbenchController;
  focusMode: DocumentFocusMode;
}

function diagnosticPath(item: DiagnosticItem, workspace?: string): string {
  let path = item.location?.path || "工作区";
  if (workspace && path.startsWith(workspace)) path = path.slice(workspace.length).replace(/^[/\\]/, "");
  return path;
}

function templateOrigin(item: TemplateItem): string {
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

export function DocumentsView({ controller, focusMode }: DocumentsViewProps) {
  const [filter, setFilter] = useState("");
  const [newDocumentOpened, setNewDocumentOpened] = useState(false);
  const [templateDrawerOpened, setTemplateDrawerOpened] = useState(false);
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
  const editorRef = useRef<CodeEditorHandle>(null);

  const current = controller.currentDocument;
  const currentText = current ? controller.buffers[current.key] ?? "" : "";
  const currentDirty = Boolean(current && controller.dirtyOverlays[current.key] !== undefined);
  const templates = controller.bootstrapData?.templates ?? [];
  const availableTemplates = templates.filter((item) => !item.error);
  const currentEntryId = sourceEntryId(currentText);
  const currentExplainTargets = useMemo(
    () => currentEntryId
      ? controller.workspaceIndex.targets.filter((item) => item.value.startsWith(`${currentEntryId}.`))
      : [],
    [controller.workspaceIndex.targets, currentEntryId],
  );
  const currentExplainTargetSignature = currentExplainTargets.map((item) => item.value).join("\u0000");
  const validDocumentId = /^[A-Za-z_][A-Za-z0-9_]*$/.test(documentId.trim());

  useEffect(() => {
    if (controller.externalConflict) setConflictOpened(true);
  }, [controller.externalConflict]);

  useEffect(() => {
    if (!selectedTemplate && availableTemplates.length) setSelectedTemplate(availableTemplates[0].value);
  }, [availableTemplates, selectedTemplate]);

  useEffect(() => {
    setExplainTarget((selected) => (
      selected && currentExplainTargets.some((item) => item.value === selected)
        ? selected
        : currentExplainTargets[0]?.value ?? null
    ));
  }, [current?.key, currentExplainTargetSignature]);

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

  const openDiagnostic = async (item: DiagnosticItem) => {
    const path = diagnosticPath(item, controller.bootstrapData?.workspace);
    const match = controller.documents.find((document) => document.path === path || path.endsWith(document.path));
    if (match) await controller.openDocument(match.key);
    setPendingLocation({ line: item.location?.line, column: item.location?.column });
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
      <div className={`documents-workspace is-focus-${focusMode}`} id="documents-layout">
        {focusMode === "split" && <section className="workspace-panel explorer-panel" aria-label="文档索引">
          <div className="panel-toolbar">
            <Group justify="space-between" wrap="nowrap">
              <Text fw={650} fz="sm">工作区文档</Text>
              <Group gap={4} wrap="nowrap">
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
          {current ? (
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
                          leftSection={<BookTemplate size={14} />}
                          disabled={current.read_only || currentDirty}
                          onClick={() => setSaveTemplateOpened(true)}
                        >
                          保存为创建模板
                        </Menu.Item>
                      </Menu.Dropdown>
                    </Menu>
                  </Group>
                </Group>
              </div>
              <div className="editor-stage">
                <CodeEditor
                  key={current.key}
                  ref={editorRef}
                  value={currentText}
                  ariaLabel={`Kirin 源码：${current.title}`}
                  readOnly={current.read_only}
                  diagnostics={currentDiagnostics}
                  onChange={(text) => controller.updateBuffer(current.key, text)}
                  onComplete={(prefix) => controller.completions(current.key, prefix)}
                  onSave={() => { void controller.saveAll(); }}
                />
              </div>
              <div className="editor-statusbar">
                <span>{currentDiagnostics.length ? `${currentDiagnostics.length} 个当前文档问题` : "当前文档有效"}</span>
                <span>Kirin 文档</span>
                <span>UTF-8</span>
                {!current.read_only && <span>补全 ⌃Space</span>}
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

        {focusMode !== "editor" && <aside className="workspace-panel inspector-panel" aria-label="文档检查器">
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
              {current ? <DocumentPreview controller={controller} document={current} source={currentText} /> : <EmptyState title="选择一个文档" description="结果和图表会从当前文档源码按需出现。" />}
            </Tabs.Panel>
            <Tabs.Panel value="relationships" className="inspector-content">
              {current ? <DocumentRelationshipPreview controller={controller} documentKey={current.key} source={currentText} /> : <EmptyState title="选择一个文档" description="这里会显示当前文档的局部依赖投影。" />}
            </Tabs.Panel>
            <Tabs.Panel value="diagnostics" className="inspector-content">
              <ScrollArea h="100%" type="auto">
                {controller.validationItems.length ? (
                  <Stack gap={0}>
                    {controller.validationItems.map((item, index) => {
                      const path = diagnosticPath(item, controller.bootstrapData?.workspace);
                      return (
                        <button className="diagnostic-row" type="button" key={`${path}-${item.location?.line}-${index}`} onClick={() => { void openDiagnostic(item); }}>
                          <span className="diagnostic-severity"><CircleAlert size={15} /></span>
                          <span>
                            <strong>{item.author_message || item.message || "校验错误"}</strong>
                            <small>{path}{item.location?.line ? `:${item.location.line}` : ""} · {item.code || "error"}</small>
                          </span>
                        </button>
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
                  {currentExplainTargets.length === 1 && <Box><Text className="result-label">当前结果</Text><Code>{currentExplainTargets[0].value}</Code></Box>}
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
            <Text fz="sm" fw={620}>从固定字段模板创建</Text>
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
            placeholder="arcane_missiles"
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
        opened={Boolean(controller.externalConflict) && conflictOpened}
        onClose={() => setConflictOpened(false)}
        title="比较外部修改"
        size="min(1100px, 94vw)"
        centered
      >
        {controller.externalConflict && (
          <Stack gap="md">
            <Text fz="sm">磁盘上的 <strong>{controller.externalConflict.path}</strong> 已被其他程序修改。当前草稿尚未覆盖磁盘。</Text>
            <Text c="dimmed" fz="xs">先比较两个版本。重新加载会用右侧磁盘内容替换当前缓冲区；保留草稿副本会下载左侧内容，但不会改变任何工作区源码。</Text>
            <div className="conflict-comparison" aria-label="草稿与磁盘版本比较">
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
                <Button className="danger-button" onClick={() => { void controller.reloadExternalConflict().then((reloaded) => { if (reloaded) setConflictOpened(false); }); }}>重新加载磁盘版本</Button>
              </Group>
            </Group>
          </Stack>
        )}
      </Modal>

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
    </>
  );
}
