import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { notifications } from "@mantine/notifications";

import { errorMessage, initialDocument, request, runOperation } from "../api";
import type {
  AsyncState,
  BootstrapPayload,
  CompletionItem,
  DocumentItem,
  DocumentPayload,
  OperationResult,
  ValidationResult,
} from "../types";

function recordsEqual(left: Record<string, string>, right: Record<string, string>): boolean {
  const keys = Object.keys(left);
  return keys.length === Object.keys(right).length && keys.every((key) => left[key] === right[key]);
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
  const started = useRef(false);
  const validationSequence = useRef(0);

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
    try {
      const result = await request<DocumentPayload>(`/api/document?key=${encodeURIComponent(key)}`);
      setBuffers((current) => ({ ...current, [key]: result.text }));
      setOriginals((current) => ({ ...current, [key]: result.text }));
      setHashes((current) => ({ ...current, [key]: result.source_sha256 }));
    } catch (error) {
      notifications.show({ color: "red", title: "无法打开文档", message: errorMessage(error) });
    }
  }, [buffers]);

  const refresh = useCallback(async (preserveCurrent = true) => {
    setAsyncState("connecting");
    try {
      const data = await request<BootstrapPayload>("/api/bootstrap");
      setBootstrapData(data);
      setValidation(data.validation);
      setLastCheckedAt(new Date());
      setDocuments((existing) => {
        const unsavedDrafts = existing.filter(
          (item) => !data.documents.some((serverItem) => serverItem.key === item.key) && originals[item.key] === "",
        );
        return [...data.documents, ...unsavedDrafts];
      });
      const desired = preserveCurrent && currentKey
        ? currentKey
        : initialDocument && data.documents.some((item) => item.key === initialDocument)
          ? initialDocument
          : data.documents[0]?.key;
      if (desired) {
        setCurrentKey(desired);
        if (!Object.prototype.hasOwnProperty.call(buffers, desired)) {
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
        notifications.show({ color: "red", title: "校验失败", message: errorMessage(error) });
      }
      return null;
    } finally {
      if (sequence === validationSequence.current) setAsyncState("idle");
    }
  }, [dirtyOverlays]);

  const dirtySignature = useMemo(() => JSON.stringify(dirtyOverlays), [dirtyOverlays]);
  useEffect(() => {
    if (!bootstrapData) return;
    const timer = window.setTimeout(() => { void validate(false); }, 450);
    return () => window.clearTimeout(timer);
  }, [bootstrapData, dirtySignature, validate]);

  const updateBuffer = useCallback((key: string, text: string) => {
    setBuffers((current) => current[key] === text ? current : { ...current, [key]: text });
  }, []);

  const saveAll = useCallback(async () => {
    if (!Object.keys(dirtyOverlays).length) {
      notifications.show({ color: "gray", message: "没有需要保存的草稿。" });
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
      notifications.show({ color: "green", title: "已保存", message: `${result.saved.length} 个文档已写入工作区。` });
      await refresh(true);
      return true;
    } catch (error) {
      notifications.show({ color: "red", title: "无法保存", message: errorMessage(error), autoClose: false });
      return false;
    } finally {
      setAsyncState("idle");
    }
  }, [buffers, dirtyOverlays, hashes, originals, refresh]);

  const createDocument = useCallback(async (template: string, documentId: string) => {
    const result = await request<{ path: string; kind: string; id: string; text: string }>("/api/document/create", {
      template,
      document_id: documentId,
    });
    const item: DocumentItem = {
      key: result.path,
      path: result.path,
      title: result.id,
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

  const completions = useCallback(async (key: string, prefix: string) => {
    const result = await request<{ items: CompletionItem[] }>("/api/completions", {
      key,
      prefix,
      overlays: dirtyOverlays,
    });
    return result.items;
  }, [dirtyOverlays]);

  const operation = useCallback(async (
    name: string,
    payload: Record<string, unknown>,
  ): Promise<OperationResult> => {
    setAsyncState("running");
    try {
      const result = await runOperation(name, payload, dirtyOverlays);
      if (payload.save_run) await refresh(true);
      return result;
    } catch (error) {
      notifications.show({ color: "red", title: "操作失败", message: errorMessage(error), autoClose: false });
      throw error;
    } finally {
      setAsyncState("idle");
    }
  }, [dirtyOverlays, refresh]);

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

  const templateAction = useCallback(async (action: string, payload: Record<string, unknown> = {}) => {
    const result = await request<OperationResult>("/api/template", { action, payload });
    await refresh(true);
    return result;
  }, [refresh]);

  useEffect(() => {
    const preventLoss = (event: BeforeUnloadEvent) => {
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
    completions,
    createDocument,
    createSourceDraft,
    currentDocument,
    currentKey,
    dirtyCount,
    dirtyOverlays,
    documents,
    hashes,
    lastCheckedAt,
    openDocument,
    operation,
    packageAction,
    refresh,
    saveAll,
    templateAction,
    updateBuffer,
    validate,
    validation,
    validationItems,
    workspaceIndex: bootstrapData?.index ?? { targets: [], inputs: [], presets: [], charts: [] },
  };
}

export type WorkbenchController = ReturnType<typeof useWorkbench>;
