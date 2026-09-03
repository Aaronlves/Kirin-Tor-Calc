import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { notifications } from "@mantine/notifications";

import { ApiError, cancelOperationJob, errorMessage, initialDocument, request, runOperation } from "../api";
import type {
  AuthoringChange,
  AsyncState,
  BootstrapPayload,
  CompletionItem,
  CompletionRequest,
  DocumentItem,
  DocumentPayload,
  DocumentProjection,
  ExternalChangeConflict,
  GitSummary,
  OperationResult,
  OperationJobStatus,
  RecoveryDraft,
  ValidationResult,
  WorkspaceStatePayload,
  WorkspaceSearchMatch,
} from "../types";
import { emptyAuthoringIndex } from "../authoring";

function recordsEqual(left: Record<string, string>, right: Record<string, string>): boolean {
  const keys = Object.keys(left);
  return keys.length === Object.keys(right).length && keys.every((key) => left[key] === right[key]);
}

function externalConflictPath(error: ApiError): string | null {
  if (error.payload.code !== "workspace_error") return null;
  const location = error.payload.location;
  if (!location || typeof location !== "object") return null;
  const path = (location as Record<string, unknown>).path;
  return typeof path === "string" ? path : null;
}

function rememberedDocumentKey(workspace: string): string {
  return `kirin:current-document:${workspace}`;
}

function recoveryPayload(
  overlays: Record<string, string>,
  documents: DocumentItem[],
  hashes: Record<string, string | null>,
): Record<string, RecoveryDraft> {
  return Object.fromEntries(Object.entries(overlays).map(([key, text]) => {
    const document = documents.find((item) => item.key === key);
    return [key, {
      text,
      base_sha256: hashes[key] ?? null,
      document: document ?? {
        key,
        path: key,
        title: key.split("/").at(-1)?.replace(/\.kirin$/i, "") || key,
        kind: "entry",
        read_only: false,
        source_sha256: null,
      },
    }];
  }));
}

export function useWorkbench() {
  const [bootstrapData, setBootstrapData] = useState<BootstrapPayload | null>(null);
  const [documents, setDocuments] = useState<DocumentItem[]>([]);
  const [currentKey, setCurrentKey] = useState<string | null>(null);
  const [buffers, setBuffers] = useState<Record<string, string>>({});
  const [originals, setOriginals] = useState<Record<string, string>>({});
  const [hashes, setHashes] = useState<Record<string, string | null>>({});
  const [validation, setValidation] = useState<ValidationResult | null>(null);
  const [asyncState, setAsyncState] = useState<AsyncState>("connecting");
  const [lastCheckedAt, setLastCheckedAt] = useState<Date | null>(null);
  const [externalConflict, setExternalConflict] = useState<ExternalChangeConflict | null>(null);
  const [recoveryReady, setRecoveryReady] = useState(false);
  const [operationJobs, setOperationJobs] = useState<OperationJobStatus[]>([]);
  const started = useRef(false);
  const recoveryHydrated = useRef(false);
  const recoveryDrafts = useRef<Record<string, RecoveryDraft>>({});
  const validationSequence = useRef(0);
  const validationPending = useRef(false);
  const operationJobsRef = useRef(new Map<string, OperationJobStatus>());
  const recoveryWriteChain = useRef<Promise<void>>(Promise.resolve());
  const switchingWorkspaceRef = useRef(false);
  const workspaceReloadRef = useRef(false);
  const workspaceRevision = useRef<string | null>(null);
  const externalSyncRunning = useRef(false);
  const asyncStateRef = useRef(asyncState);
  asyncStateRef.current = asyncState;
  const workspaceData = useMemo(
    () => ({ buffers, originals, hashes, documents, currentKey }),
    [buffers, currentKey, documents, hashes, originals],
  );
  const workspaceDataRef = useRef(workspaceData);
  workspaceDataRef.current = workspaceData;

  const persistRecovery = useCallback((drafts: Record<string, RecoveryDraft>): Promise<void> => {
    const pending = recoveryWriteChain.current
      .catch(() => undefined)
      .then(() => request("/api/recovery", { drafts }))
      .then(() => undefined);
    recoveryWriteChain.current = pending;
    return pending;
  }, []);

  const currentDocument = useMemo(
    () => documents.find((document) => document.key === currentKey) ?? null,
    [currentKey, documents],
  );

  const dirtyOverlays = useMemo(() => {
    const result: Record<string, string> = {};
    for (const [path, text] of Object.entries(buffers)) {
      if (text !== (originals[path] ?? "")) result[path] = text;
    }
    return result;
  }, [buffers, originals]);

  const dirtyCount = Object.keys(dirtyOverlays).length;
  const bootstrapReady = bootstrapData !== null;
  const validationItems = validation?.status === "error"
    ? validation.errors ?? [{
        code: validation.code,
        message: validation.message,
        author_message: validation.author_message,
      }]
    : [];

  const openDocument = useCallback(async (key: string) => {
    setCurrentKey(key);
    if (Object.prototype.hasOwnProperty.call(buffers, key)) return;
    const recovered = recoveryDrafts.current[key];
    if (recovered?.base_sha256 === null && recovered.document.source_sha256 === null) {
      setBuffers((current) => ({ ...current, [key]: recovered.text }));
      setOriginals((current) => ({ ...current, [key]: "" }));
      setHashes((current) => ({ ...current, [key]: null }));
      return;
    }
    try {
      const result = await request<DocumentPayload>(`/api/document?key=${encodeURIComponent(key)}`);
      setBuffers((current) => Object.prototype.hasOwnProperty.call(current, key)
        ? current
        : { ...current, [key]: recovered?.text ?? result.text });
      setOriginals((current) => ({ ...current, [key]: result.text }));
      const recoveredConflict = recovered && recovered.base_sha256 !== result.source_sha256;
      setHashes((current) => ({
        ...current,
        [key]: recoveredConflict ? recovered.base_sha256 ?? "recovery-base-missing" : result.source_sha256,
      }));
      if (recoveredConflict) {
        setExternalConflict({ key, path: result.path, base: null, draft: recovered.text, disk: result.text, disk_sha256: result.source_sha256 });
      }
    } catch (error) {
      notifications.show({ color: "red", title: "无法打开文档", message: errorMessage(error), autoClose: false });
    }
  }, [buffers]);

  const refresh = useCallback(async (preserveCurrent = true) => {
    setAsyncState("connecting");
    try {
      const data = await request<BootstrapPayload>("/api/bootstrap");
      setBootstrapData(data);
      setValidation(data.validation);
      setLastCheckedAt(new Date());
      const firstRecovery = !recoveryHydrated.current;
      recoveryHydrated.current = true;
      recoveryDrafts.current = data.recovery?.drafts ?? {};
      const recoveredEntries = Object.values(recoveryDrafts.current);
      const recoveredNewDocuments = recoveredEntries
        .filter((item) => !data.documents.some((document) => document.key === item.document.key))
        .map((item) => item.document);
      setDocuments((existing) => {
        const unsavedDrafts = existing.filter(
          (item) => !data.documents.some((serverItem) => serverItem.key === item.key) && originals[item.key] === "",
        );
        const extras = [...unsavedDrafts, ...recoveredNewDocuments].filter(
          (item, index, items) => items.findIndex((candidate) => candidate.key === item.key) === index,
        );
        return [...data.documents, ...extras];
      });
      const restoredBuffers: Record<string, string> = {};
      if (firstRecovery && recoveredEntries.length) {
        const restoredOriginals: Record<string, string> = {};
        const restoredHashes: Record<string, string | null> = {};
        let conflict: ExternalChangeConflict | null = null;
        for (const recovered of recoveredEntries) {
          const key = recovered.document.key;
          const serverDocument = data.documents.find((item) => item.key === key);
          if (!serverDocument) {
            restoredBuffers[key] = recovered.text;
            restoredOriginals[key] = "";
            restoredHashes[key] = null;
            continue;
          }
          const disk = await request<DocumentPayload>(`/api/document?key=${encodeURIComponent(key)}`);
          restoredBuffers[key] = recovered.text;
          restoredOriginals[key] = disk.text;
          const mismatched = recovered.base_sha256 !== disk.source_sha256;
          restoredHashes[key] = mismatched ? recovered.base_sha256 ?? "recovery-base-missing" : disk.source_sha256;
          if (!conflict && mismatched) {
            conflict = { key, path: disk.path, base: null, draft: recovered.text, disk: disk.text, disk_sha256: disk.source_sha256 };
          }
        }
        setBuffers((current) => ({ ...current, ...restoredBuffers }));
        setOriginals((current) => ({ ...current, ...restoredOriginals }));
        setHashes((current) => ({ ...current, ...restoredHashes }));
        if (conflict) setExternalConflict(conflict);
        notifications.show({
          color: conflict ? "orange" : "green",
          title: `已恢复 ${recoveredEntries.length} 个草稿`,
          message: conflict ? "其中一个文档的磁盘版本已变化，请先比较。" : "草稿仍未写入权威源码；保存全部后才会落盘。",
          ...(conflict ? { autoClose: false } : {}),
        });
      }
      setRecoveryReady(true);
      const availableDocuments = [...data.documents, ...recoveredNewDocuments];
      const rememberedDocument = localStorage.getItem(rememberedDocumentKey(data.workspace));
      const desired = preserveCurrent && currentKey
        ? currentKey
        : initialDocument && availableDocuments.some((item) => item.key === initialDocument)
          ? initialDocument
          : rememberedDocument && availableDocuments.some((item) => item.key === rememberedDocument)
            ? rememberedDocument
            : availableDocuments[0]?.key;
      if (desired) {
        setCurrentKey(desired);
        if (!Object.prototype.hasOwnProperty.call(buffers, desired) && !Object.prototype.hasOwnProperty.call(restoredBuffers, desired)) {
          const recovered = recoveryDrafts.current[desired];
          if (recovered && !data.documents.some((item) => item.key === desired)) {
            setBuffers((current) => ({ ...current, [desired]: recovered.text }));
            setOriginals((current) => ({ ...current, [desired]: "" }));
            setHashes((current) => ({ ...current, [desired]: null }));
            return;
          }
          const opened = await request<DocumentPayload>(`/api/document?key=${encodeURIComponent(desired)}`);
          setBuffers((current) => ({ ...current, [desired]: opened.text }));
          setOriginals((current) => ({ ...current, [desired]: opened.text }));
          setHashes((current) => ({ ...current, [desired]: opened.source_sha256 }));
        }
      }
    } catch (error) {
      notifications.show({ color: "red", title: "无法连接工作台", message: errorMessage(error), autoClose: false });
    } finally {
      setAsyncState("idle");
    }
  }, [buffers, currentKey, originals]);

  useEffect(() => {
    if (started.current) return;
    started.current = true;
    void refresh(false);
  }, [refresh]);

  const validate = useCallback(async (showSuccess = false) => {
    const sequence = ++validationSequence.current;
    setAsyncState("validating");
    try {
      const result = await request<ValidationResult>(
        "/api/validate",
        { overlays: dirtyOverlays },
        { allowErrorResult: true },
      );
      if (sequence !== validationSequence.current) return result;
      setValidation(result);
      setLastCheckedAt(new Date());
      if (result.status === "ok" && result.index) {
        setBootstrapData((current) => current ? { ...current, index: result.index! } : current);
      }
      if (showSuccess && result.status === "ok") {
        notifications.show({ color: "green", title: "工作区有效", message: "全部文档已通过语法和计算校验。" });
      }
      return result;
    } catch (error) {
      if (sequence === validationSequence.current) {
        notifications.show({ color: "red", title: "校验失败", message: errorMessage(error), autoClose: false });
      }
      return null;
    } finally {
      if (sequence === validationSequence.current) setAsyncState("idle");
    }
  }, [dirtyOverlays]);

  const syncExternalDocuments = useCallback(async () => {
    if (switchingWorkspaceRef.current || externalSyncRunning.current || asyncState !== "idle" || document.visibilityState === "hidden") return;
    externalSyncRunning.current = true;
    const snapshot = workspaceDataRef.current;
    try {
      const state = await request<WorkspaceStatePayload>("/api/workspace/state");
      if (switchingWorkspaceRef.current) return;
      if (workspaceRevision.current === state.revision) return;

      const diskDocuments = new Map(state.documents.map((item) => [item.key, item]));
      const nextBuffers = { ...snapshot.buffers };
      const nextOriginals = { ...snapshot.originals };
      const nextHashes = { ...snapshot.hashes };
      const retainedDocuments: DocumentItem[] = snapshot.documents.filter((item) => item.read_only);
      let conflict: ExternalChangeConflict | null = null;
      let removedDrafts = 0;

      for (const item of state.documents) {
        if (!Object.prototype.hasOwnProperty.call(nextBuffers, item.key)) continue;
        if (item.source_sha256 === nextHashes[item.key]) continue;
        const opened = await request<DocumentPayload>(`/api/document?key=${encodeURIComponent(item.key)}`);
        if (nextBuffers[item.key] === (nextOriginals[item.key] ?? "")) {
          nextBuffers[item.key] = opened.text;
          nextOriginals[item.key] = opened.text;
          nextHashes[item.key] = opened.source_sha256;
        } else if (!conflict) {
          conflict = {
            key: item.key,
            path: opened.path,
            base: nextOriginals[item.key] ?? null,
            draft: nextBuffers[item.key],
            disk: opened.text,
            disk_sha256: opened.source_sha256,
          };
        }
      }

      for (const item of snapshot.documents) {
        if (item.read_only || diskDocuments.has(item.key)) continue;
        if (!Object.prototype.hasOwnProperty.call(nextBuffers, item.key)) continue;
        if (nextBuffers[item.key] !== (nextOriginals[item.key] ?? "")) {
          retainedDocuments.push({ ...item, source_sha256: null });
          if (nextHashes[item.key] !== null) removedDrafts += 1;
          nextOriginals[item.key] = "";
          nextHashes[item.key] = null;
        } else {
          delete nextBuffers[item.key];
          delete nextOriginals[item.key];
          delete nextHashes[item.key];
        }
      }

      const mergedDocuments = [...new Map(
        [...state.documents, ...retainedDocuments].map((item) => [item.key, item]),
      ).values()];
      let nextCurrentKey = snapshot.currentKey;
      if (nextCurrentKey && !mergedDocuments.some((item) => item.key === nextCurrentKey)) {
        nextCurrentKey = mergedDocuments[0]?.key ?? null;
        if (nextCurrentKey && !Object.prototype.hasOwnProperty.call(nextBuffers, nextCurrentKey)) {
          const opened = await request<DocumentPayload>(`/api/document?key=${encodeURIComponent(nextCurrentKey)}`);
          nextBuffers[nextCurrentKey] = opened.text;
          nextOriginals[nextCurrentKey] = opened.text;
          nextHashes[nextCurrentKey] = opened.source_sha256;
        }
      }

      // A document may have been opened, edited, created, or discarded while
      // the network requests above were in flight. Never replace that newer
      // local state with this stale snapshot; the next polling cycle will
      // reconcile the same disk revision against the latest local state.
      if (switchingWorkspaceRef.current || workspaceDataRef.current !== snapshot) return;

      setDocuments(mergedDocuments);
      setBootstrapData((current) => current ? { ...current, documents: mergedDocuments } : current);
      setBuffers(nextBuffers);
      setOriginals(nextOriginals);
      setHashes(nextHashes);
      if (nextCurrentKey !== snapshot.currentKey) setCurrentKey(nextCurrentKey);
      if (conflict) setExternalConflict(conflict);
      if (removedDrafts) {
        notifications.show({
          color: "orange",
          title: "磁盘文档已移除",
          message: `${removedDrafts} 个未保存草稿仍保留在工作台；保存全部会重新创建对应文档。`,
          autoClose: false,
        });
      }
      workspaceRevision.current = state.revision;
      await validate(false);
    } catch {
      // External synchronization is opportunistic; ordinary workbench actions
      // retain their existing visible error handling and retry on the next poll.
    } finally {
      externalSyncRunning.current = false;
    }
  }, [asyncState, validate]);

  useEffect(() => {
    if (!bootstrapReady) return;
    const check = () => { void syncExternalDocuments(); };
    check();
    const timer = window.setInterval(check, 1200);
    return () => window.clearInterval(timer);
  }, [bootstrapReady, syncExternalDocuments]);

  const dirtySignature = useMemo(() => JSON.stringify(dirtyOverlays), [dirtyOverlays]);
  useEffect(() => {
    if (!bootstrapReady) return;
    const timer = window.setTimeout(() => {
      if (asyncStateRef.current === "idle") {
        validationPending.current = false;
        void validate(false);
      } else {
        validationPending.current = true;
      }
    }, 450);
    return () => window.clearTimeout(timer);
  }, [bootstrapReady, dirtySignature, validate]);

  useEffect(() => {
    if (!bootstrapReady || asyncState !== "idle" || !validationPending.current) return;
    validationPending.current = false;
    void validate(false);
  }, [asyncState, bootstrapReady, validate]);

  const updateBuffer = useCallback((key: string, text: string) => {
    setBuffers((current) => current[key] === text ? current : { ...current, [key]: text });
    setExternalConflict((current) => current?.key === key ? { ...current, draft: text } : current);
  }, []);

  const inspectExternalConflict = useCallback(async (key: string) => {
    const disk = await request<DocumentPayload>(`/api/document?key=${encodeURIComponent(key)}`);
    setExternalConflict({
      key,
      path: disk.path,
      base: originals[key] ?? null,
      draft: buffers[key] ?? originals[key] ?? disk.text,
      disk: disk.text,
      disk_sha256: disk.source_sha256,
    });
  }, [buffers, originals]);

  const saveAll = useCallback(async () => {
    if (!Object.keys(dirtyOverlays).length) {
      notifications.show({ color: "gray", message: "没有需要保存的草稿。" });
      return false;
    }
    if (asyncState !== "idle") {
      notifications.show({
        color: "orange",
        title: "当前暂不能保存",
        message: asyncState === "running" ? "请等待当前计算结束或先取消计算。" : "请等待当前工作区操作结束。",
      });
      return false;
    }
    setAsyncState("saving");
    try {
      const expected = Object.fromEntries(Object.keys(dirtyOverlays).map((path) => [path, hashes[path] ?? null]));
      const result = await request<{ saved: Array<{ path: string; source_sha256: string }> }>("/api/save", {
        overlays: dirtyOverlays,
        expected,
      });
      const nextOriginals = { ...originals };
      const nextHashes = { ...hashes };
      for (const item of result.saved) {
        nextOriginals[item.path] = buffers[item.path];
        nextHashes[item.path] = item.source_sha256;
      }
      setOriginals(nextOriginals);
      setHashes(nextHashes);
      let recoveryCleared = true;
      try {
        await persistRecovery({});
        recoveryDrafts.current = {};
      } catch (error) {
        recoveryCleared = false;
        notifications.show({
          color: "red",
          title: "文档已保存，但恢复缓存未清除",
          message: errorMessage(error),
          autoClose: false,
        });
      }
      if (recoveryCleared) {
        notifications.show({ color: "green", title: "已保存", message: `${result.saved.length} 个文档已写入工作区。` });
      }
      await refresh(true);
      return true;
    } catch (error) {
      if (error instanceof ApiError) {
        const path = externalConflictPath(error);
        if (path && Object.prototype.hasOwnProperty.call(dirtyOverlays, path)) {
          try {
            await inspectExternalConflict(path);
            notifications.show({
              color: "orange",
              title: "检测到外部修改",
              message: "草稿未被覆盖。请比较磁盘版本，再选择重新加载或保留草稿副本。",
              autoClose: false,
            });
            return false;
          } catch (inspectError) {
            notifications.show({ color: "red", title: "无法读取磁盘版本", message: errorMessage(inspectError), autoClose: false });
          }
        }
      }
      notifications.show({ color: "red", title: "无法保存", message: errorMessage(error), autoClose: false });
      return false;
    } finally {
      setAsyncState("idle");
    }
  }, [asyncState, buffers, dirtyOverlays, hashes, inspectExternalConflict, originals, persistRecovery, refresh]);

  const discardDraft = useCallback(async (key: string) => {
    if (!Object.prototype.hasOwnProperty.call(dirtyOverlays, key)) return false;
    const document = documents.find((item) => item.key === key);
    const isUnsavedDocument = document?.source_sha256 === null && hashes[key] === null;
    const remainingOverlays = { ...dirtyOverlays };
    delete remainingOverlays[key];
    delete recoveryDrafts.current[key];
    setExternalConflict((conflict) => conflict?.key === key ? null : conflict);

    if (isUnsavedDocument) {
      const remaining = documents.filter((item) => item.key !== key);
      setDocuments(remaining);
      setBuffers((current) => {
        const next = { ...current };
        delete next[key];
        return next;
      });
      setOriginals((current) => {
        const next = { ...current };
        delete next[key];
        return next;
      });
      setHashes((current) => {
        const next = { ...current };
        delete next[key];
        return next;
      });
      if (currentKey === key) {
        const nextDocument = remaining.find((item) => Object.prototype.hasOwnProperty.call(buffers, item.key)) ?? remaining[0];
        if (nextDocument) await openDocument(nextDocument.key);
        else setCurrentKey(null);
      }
      try {
        await persistRecovery(recoveryPayload(remainingOverlays, remaining, hashes));
      } catch (error) {
        notifications.show({ color: "red", title: "草稿已放弃，但恢复缓存未清除", message: errorMessage(error), autoClose: false });
        return true;
      }
      notifications.show({ color: "green", title: "已放弃新文档草稿", message: `${document?.path ?? key} 从工作台中移除，磁盘没有发生变化。` });
      return true;
    }

    setBuffers((current) => ({ ...current, [key]: originals[key] ?? "" }));
    try {
      await persistRecovery(recoveryPayload(remainingOverlays, documents, hashes));
    } catch (error) {
      notifications.show({ color: "red", title: "草稿已放弃，但恢复缓存未清除", message: errorMessage(error), autoClose: false });
      return true;
    }
    notifications.show({ color: "green", title: "已恢复磁盘基线", message: `${document?.path ?? key} 的未保存修改已放弃。` });
    return true;
  }, [buffers, currentKey, dirtyOverlays, documents, hashes, openDocument, originals, persistRecovery]);

  const discardAllDrafts = useCallback(async () => {
    const keys = Object.keys(dirtyOverlays);
    if (!keys.length) return false;
    const dirtyKeys = new Set(keys);
    const newKeys = new Set(documents
      .filter((item) => dirtyKeys.has(item.key) && item.source_sha256 === null && hashes[item.key] === null)
      .map((item) => item.key));
    const remaining = documents.filter((item) => !newKeys.has(item.key));
    for (const key of keys) delete recoveryDrafts.current[key];
    setDocuments(remaining);
    setBuffers((current) => {
      const next = { ...current };
      for (const key of keys) {
        if (newKeys.has(key)) delete next[key];
        else next[key] = originals[key] ?? "";
      }
      return next;
    });
    setOriginals((current) => {
      const next = { ...current };
      for (const key of newKeys) delete next[key];
      return next;
    });
    setHashes((current) => {
      const next = { ...current };
      for (const key of newKeys) delete next[key];
      return next;
    });
    setExternalConflict(null);
    if (currentKey && newKeys.has(currentKey)) {
      const nextDocument = remaining.find((item) => Object.prototype.hasOwnProperty.call(buffers, item.key)) ?? remaining[0];
      if (nextDocument) await openDocument(nextDocument.key);
      else setCurrentKey(null);
    }
    try {
      await persistRecovery({});
    } catch (error) {
      notifications.show({ color: "red", title: "草稿已放弃，但恢复缓存未清除", message: errorMessage(error), autoClose: false });
      return true;
    }
    notifications.show({ color: "green", title: "已放弃全部草稿", message: `${keys.length} 个未保存草稿已恢复到磁盘基线；新文档草稿已移除。` });
    return true;
  }, [buffers, currentKey, dirtyOverlays, documents, hashes, openDocument, originals, persistRecovery]);

  const reloadExternalConflict = useCallback(async () => {
    if (!externalConflict) return false;
    const conflict = externalConflict;
    try {
      const latest = await request<DocumentPayload>(`/api/document?key=${encodeURIComponent(conflict.key)}`);
      setBuffers((current) => ({ ...current, [conflict.key]: latest.text }));
      setOriginals((current) => ({ ...current, [conflict.key]: latest.text }));
      setHashes((current) => ({ ...current, [conflict.key]: latest.source_sha256 }));
      setDocuments((current) => current.map((item) => item.key === conflict.key
        ? { ...item, source_sha256: latest.source_sha256 }
        : item));
      setExternalConflict(null);
      notifications.show({ color: "green", title: "已重新加载", message: `${conflict.path} 已更新为最新磁盘版本。` });
      return true;
    } catch (error) {
      notifications.show({ color: "red", title: "无法重新加载", message: errorMessage(error), autoClose: false });
      return false;
    }
  }, [externalConflict]);

  const keepExternalConflictDraft = useCallback(() => {
    if (!externalConflict) return false;
    const blob = new Blob([externalConflict.draft], { type: "text/plain;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    const filename = externalConflict.path.split(/[\\/]/).at(-1) || "document.kirin";
    link.href = url;
    link.download = filename.replace(/\.kirin$/i, "") + ".workbench-draft.kirin";
    link.click();
    URL.revokeObjectURL(url);
    notifications.show({ color: "green", message: "草稿副本已下载；当前编辑缓冲区保持不变。" });
    return true;
  }, [externalConflict]);

  const mergeExternalConflict = useCallback(async () => {
    if (!externalConflict || externalConflict.base == null || !externalConflict.disk_sha256) return false;
    const conflict = externalConflict;
    try {
      const result = await request<{ text: string; clean: boolean; conflicts: number }>("/api/authoring", {
        action: "merge",
        payload: { base: conflict.base, draft: conflict.draft, disk: conflict.disk },
        overlays: {},
      });
      setBuffers((current) => ({ ...current, [conflict.key]: result.text }));
      setOriginals((current) => ({ ...current, [conflict.key]: conflict.disk }));
      setHashes((current) => ({ ...current, [conflict.key]: conflict.disk_sha256 ?? null }));
      setDocuments((current) => current.map((item) => item.key === conflict.key
        ? { ...item, source_sha256: conflict.disk_sha256 ?? null }
        : item));
      setExternalConflict(null);
      notifications.show({
        color: result.clean ? "green" : "yellow",
        title: result.clean ? "已自动合并" : "需要处理合并标记",
        message: result.clean
          ? "磁盘变更与当前草稿已合并，结果仍是未保存草稿。"
          : `检测到 ${result.conflicts} 处冲突；编辑器中已加入冲突标记。`,
        ...(result.clean ? {} : { autoClose: false }),
      });
      return true;
    } catch (error) {
      notifications.show({ color: "red", title: "无法合并", message: errorMessage(error), autoClose: false });
      return false;
    }
  }, [externalConflict]);

  const createDocument = useCallback(async (template: string, documentId: string) => {
    const result = await request<{ path: string; kind: string; id: string; title?: string; text: string }>("/api/document/create", {
      template,
      document_id: documentId,
    });
    const item: DocumentItem = {
      key: result.path,
      path: result.path,
      title: result.title ?? result.id,
      kind: result.kind,
      read_only: false,
      source_sha256: null,
    };
    setDocuments((current) => [...current.filter((document) => document.key !== item.key), item]);
    setBuffers((current) => ({ ...current, [item.key]: result.text }));
    setOriginals((current) => ({ ...current, [item.key]: "" }));
    setHashes((current) => ({ ...current, [item.key]: null }));
    setCurrentKey(item.key);
    return item;
  }, []);

  const createSourceDraft = useCallback((item: DocumentItem, text: string) => {
    setDocuments((current) => [...current.filter((document) => document.key !== item.key), item]);
    setBuffers((current) => ({ ...current, [item.key]: text }));
    setOriginals((current) => ({ ...current, [item.key]: "" }));
    setHashes((current) => ({ ...current, [item.key]: null }));
    setCurrentKey(item.key);
  }, []);

  const documentAction = useCallback(async (
    action: "move" | "duplicate" | "remove",
    payload: Record<string, unknown>,
  ) => {
    const result = await request<Record<string, unknown>>("/api/document/action", {
      action,
      payload,
      overlays: dirtyOverlays,
    });
    if (action === "duplicate") {
      const path = String(result.path);
      createSourceDraft({
        key: path,
        path,
        title: String(result.id),
        kind: String(result.kind ?? "entry"),
        read_only: false,
        source_sha256: null,
      }, String(result.text));
      notifications.show({ color: "green", message: `${path} 已作为未保存草稿创建。` });
      return result;
    }
    const sourceKey = String(payload.key);
    if (action === "move") {
      const path = String(result.path);
      setDocuments((current) => current.map((item) => item.key === sourceKey
        ? { ...item, key: path, path, source_sha256: String(result.source_sha256) }
        : item));
      setBuffers((current) => {
        if (!Object.prototype.hasOwnProperty.call(current, sourceKey)) return current;
        const next = { ...current, [path]: current[sourceKey] };
        delete next[sourceKey];
        return next;
      });
      setOriginals((current) => {
        if (!Object.prototype.hasOwnProperty.call(current, sourceKey)) return current;
        const next = { ...current, [path]: current[sourceKey] };
        delete next[sourceKey];
        return next;
      });
      setHashes((current) => {
        const next = { ...current, [path]: String(result.source_sha256) };
        delete next[sourceKey];
        return next;
      });
      setCurrentKey((current) => current === sourceKey ? path : current);
      notifications.show({ color: "green", message: `文档已移动到 ${path}；源内 @entry 标识保持不变。` });
      return result;
    }
    setDocuments((current) => current.filter((item) => item.key !== sourceKey));
    setBuffers((current) => {
      const next = { ...current };
      delete next[sourceKey];
      return next;
    });
    setOriginals((current) => {
      const next = { ...current };
      delete next[sourceKey];
      return next;
    });
    setHashes((current) => {
      const next = { ...current };
      delete next[sourceKey];
      return next;
    });
    setCurrentKey((current) => current === sourceKey ? null : current);
    await refresh(false);
    notifications.show({ color: "green", message: `文档已移入可恢复的 ${String(result.trash_path)}。` });
    return result;
  }, [createSourceDraft, dirtyOverlays, refresh]);

  const completions = useCallback(async (key: string, completion: CompletionRequest, signal?: AbortSignal) => {
    const result = await request<{ items: CompletionItem[] }>("/api/completions", {
      key,
      ...completion,
      overlays: dirtyOverlays,
    }, { signal });
    return result.items;
  }, [dirtyOverlays]);

  const applyAuthoringChanges = useCallback((changes: AuthoringChange[]) => {
    if (!changes.length) return;
    setBuffers((current) => {
      const next = { ...current };
      for (const change of changes) next[change.key] = change.text;
      return next;
    });
    setOriginals((current) => {
      const next = { ...current };
      for (const change of changes) {
        if (!Object.prototype.hasOwnProperty.call(next, change.key)) next[change.key] = change.before;
      }
      return next;
    });
    setHashes((current) => {
      const next = { ...current };
      for (const change of changes) {
        if (!Object.prototype.hasOwnProperty.call(next, change.key)) {
          next[change.key] = documents.find((item) => item.key === change.key)?.source_sha256 ?? null;
        }
      }
      return next;
    });
  }, [documents]);

  const searchWorkspace = useCallback(async (query: string, caseSensitive = false) => {
    return request<{ matches: WorkspaceSearchMatch[]; truncated: boolean }>("/api/authoring", {
      action: "search",
      payload: { query, case_sensitive: caseSensitive },
      overlays: dirtyOverlays,
    });
  }, [dirtyOverlays]);

  const replaceWorkspace = useCallback(async (
    query: string,
    replacement: string,
    caseSensitive = false,
  ) => {
    const result = await request<{ changes: AuthoringChange[]; edits: number }>("/api/authoring", {
      action: "replace",
      payload: { query, replacement, case_sensitive: caseSensitive },
      overlays: dirtyOverlays,
    });
    applyAuthoringChanges(result.changes);
    notifications.show({
      color: "green",
      title: "替换已生成草稿",
      message: result.edits ? `${result.edits} 处修改尚未保存，可先到“变更审查”检查。` : "没有可写匹配项。",
    });
    return result;
  }, [applyAuthoringChanges, dirtyOverlays]);

  const gitHistory = useCallback(async () => request<GitSummary>("/api/authoring", {
    action: "git_history",
    payload: {},
    overlays: {},
  }), []);

  const renameSymbol = useCallback(async (symbol: string, newName: string) => {
    const result = await request<{ changes: AuthoringChange[]; edits: number; renamed_to: string }>("/api/authoring", {
      action: "rename",
      payload: { symbol, new_name: newName },
      overlays: dirtyOverlays,
    });
    applyAuthoringChanges(result.changes);
    notifications.show({ color: "green", title: "符号已重命名", message: `${result.edits} 处草稿引用已更新为 ${result.renamed_to}。` });
    return result;
  }, [applyAuthoringChanges, dirtyOverlays]);

  const formatDocument = useCallback(async (key: string) => {
    const result = await request<{ changes: AuthoringChange[] }>("/api/authoring", {
      action: "format",
      payload: { key },
      overlays: dirtyOverlays,
    });
    applyAuthoringChanges(result.changes);
    notifications.show({ color: "green", message: result.changes.length ? "文档格式已整理，尚未保存。" : "文档格式已经整洁。" });
    return result.changes.length > 0;
  }, [applyAuthoringChanges, dirtyOverlays]);

  const operation = useCallback(async (
    name: string,
    payload: Record<string, unknown>,
  ): Promise<OperationResult> => {
    if (switchingWorkspaceRef.current) {
      throw new ApiError(
        { code: "workspace_switching", message: "工作区切换已经开始，不能再启动新的计算。" },
        "工作区正在切换",
      );
    }
    asyncStateRef.current = "running";
    setAsyncState("running");
    try {
      const result = await runOperation(name, payload, dirtyOverlays, (job) => {
        if (job.state === "queued" || job.state === "running") operationJobsRef.current.set(job.job_id, job);
        else operationJobsRef.current.delete(job.job_id);
        setOperationJobs([...operationJobsRef.current.values()]);
      });
      if (payload.save_run) await refresh(true);
      return result;
    } catch (error) {
      if (error instanceof ApiError && error.payload.code === "operation_cancelled") {
        notifications.show({ color: "gray", message: "操作已取消。" });
      } else {
        notifications.show({ color: "red", title: "操作失败", message: errorMessage(error), autoClose: false });
      }
      throw error;
    } finally {
      if (!operationJobsRef.current.size) {
        asyncStateRef.current = "idle";
        setAsyncState("idle");
      }
    }
  }, [dirtyOverlays, refresh]);

  const cancelOperations = useCallback(async () => {
    const jobs = operationJobs.filter((job) => job.cancellable);
    await Promise.all(jobs.map((job) => cancelOperationJob(job.job_id).catch(() => null)));
    operationJobsRef.current.clear();
    setOperationJobs([]);
    setAsyncState("idle");
  }, [operationJobs]);

  const packageAction = useCallback(async (action: string, payload: Record<string, unknown> = {}) => {
    setAsyncState("running");
    try {
      const result = await request<OperationResult>("/api/package", { action, payload });
      await refresh(true);
      return result;
    } finally {
      setAsyncState("idle");
    }
  }, [refresh]);

  const pluginAction = useCallback(async (action: string, payload: Record<string, unknown> = {}) => {
    setAsyncState("running");
    try {
      const result = await request<OperationResult>("/api/plugin", { action, payload });
      await refresh(true);
      return result;
    } finally {
      setAsyncState("idle");
    }
  }, [refresh]);

  const documentProjection = useCallback(async (key: string): Promise<DocumentProjection> => request<DocumentProjection>(
    "/api/document/projection",
    { key, overlays: dirtyOverlays },
  ), [dirtyOverlays]);

  const templateAction = useCallback(async (action: string, payload: Record<string, unknown> = {}) => {
    const result = await request<OperationResult>("/api/template", { action, payload });
    await refresh(true);
    return result;
  }, [refresh]);

  const switchWorkspace = useCallback(async (path: string): Promise<void> => {
    if (asyncStateRef.current !== "idle" || operationJobsRef.current.size) {
      throw new ApiError(
        { code: "workspace_busy", message: "请先等待当前工作区操作结束或取消正在运行的计算。" },
        "工作区正忙",
      );
    }
    switchingWorkspaceRef.current = true;
    asyncStateRef.current = "connecting";
    setAsyncState("connecting");
    try {
      if (Object.keys(dirtyOverlays).length) {
        await persistRecovery(recoveryPayload(dirtyOverlays, documents, hashes));
      } else {
        await recoveryWriteChain.current.catch(() => undefined);
      }
      await request<OperationResult>("/api/workspace/open", { path });
      workspaceReloadRef.current = true;
      window.location.reload();
    } catch (error) {
      switchingWorkspaceRef.current = false;
      workspaceReloadRef.current = false;
      asyncStateRef.current = "idle";
      setAsyncState("idle");
      throw error;
    }
  }, [dirtyOverlays, documents, hashes, persistRecovery]);

  useEffect(() => {
    if (!bootstrapReady || !recoveryReady) return;
    const drafts = recoveryPayload(dirtyOverlays, documents, hashes);
    const timer = window.setTimeout(() => {
      if (switchingWorkspaceRef.current) return;
      void persistRecovery(drafts).catch(() => undefined);
    }, 800);
    return () => window.clearTimeout(timer);
  }, [bootstrapReady, dirtySignature, documents, hashes, persistRecovery, recoveryReady]);

  useEffect(() => {
    if (!bootstrapData?.workspace || !currentKey) return;
    localStorage.setItem(rememberedDocumentKey(bootstrapData.workspace), currentKey);
  }, [bootstrapData?.workspace, currentKey]);

  useEffect(() => {
    const preventLoss = (event: BeforeUnloadEvent) => {
      if (workspaceReloadRef.current) return;
      if (!Object.keys(dirtyOverlays).length) return;
      event.preventDefault();
      event.returnValue = "";
    };
    window.addEventListener("beforeunload", preventLoss);
    return () => window.removeEventListener("beforeunload", preventLoss);
  }, [dirtyOverlays]);

  return {
    asyncState,
    bootstrapData,
    buffers,
    authoringIndex: validation?.authoring ?? bootstrapData?.authoring ?? emptyAuthoringIndex,
    completions,
    cancelOperations,
    createDocument,
    createSourceDraft,
    documentAction,
    documentProjection,
    currentDocument,
    currentKey,
    dirtyCount,
    dirtyOverlays,
    discardAllDrafts,
    discardDraft,
    externalConflict,
    formatDocument,
    documents,
    hashes,
    originals,
    lastCheckedAt,
    openDocument,
    operation,
    operationJobs,
    packageAction,
    pluginAction,
    pluginSummary: bootstrapData?.plugins ?? {
      safe_mode: false,
      error: null,
      plugins: [],
      contributions: { renderers: [], views: [], tools: [], commands: [], profiles: [] },
    },
    refresh,
    inspectExternalConflict,
    keepExternalConflictDraft,
    mergeExternalConflict,
    reloadExternalConflict,
    renameSymbol,
    replaceWorkspace,
    saveAll,
    searchWorkspace,
    switchWorkspace,
    gitHistory,
    templateAction,
    updateBuffer,
    validate,
    validation,
    validationItems,
    workspaceIndex: bootstrapData?.index ?? { targets: [], inputs: [], presets: [], charts: [], analyses: [] },
  };
}

export type WorkbenchController = ReturnType<typeof useWorkbench>;
