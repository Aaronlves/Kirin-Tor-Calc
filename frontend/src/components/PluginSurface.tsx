import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Badge, Box, Button, Code, Group, Stack, Text, Title } from "@mantine/core";
import { CheckCircle2, Crosshair, Puzzle, ShieldAlert, X } from "lucide-react";

import { ApiError } from "../api";
import type { WorkbenchController } from "../hooks/useWorkbench";
import type {
  DocumentProjection,
  OperationResult,
  PluginProposalRequestChange,
  PluginSurfaceContribution,
} from "../types";
import { EmptyState, LoadingState } from "./ui";

const PROTOCOL = "kirin-workbench-plugin";

class PluginActionError extends Error {
  code: string;

  constructor(code: string, message: string) {
    super(message);
    this.name = "PluginActionError";
    this.code = code;
  }
}

function requiredText(value: unknown, label: string, maximum: number): string {
  if (typeof value !== "string" || !value.trim() || value.length > maximum) {
    throw new PluginActionError("invalid_request", `${label} 必须是长度不超过 ${maximum} 的非空文本。`);
  }
  return value.trim();
}

function optionalText(value: unknown, label: string, maximum: number): string | undefined {
  if (value === undefined || value === null || value === "") return undefined;
  return requiredText(value, label, maximum);
}

function record(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

interface VerifiedResultSlot {
  handle: string;
  title: string;
  order: number;
  envelope: OperationResult;
}

function resultRows(envelope: OperationResult): OperationResult[] {
  const result = record(envelope.result) ? envelope.result : {};
  if (Array.isArray(result.results)) {
    return result.results.filter(record).slice(0, 12);
  }
  if (Array.isArray(result.variants)) {
    return result.variants
      .map((item) => record(item) && record(item.result) ? item.result : null)
      .filter(record)
      .slice(0, 12);
  }
  return [result];
}

function displayedValue(result: OperationResult): string {
  for (const key of ["formatted", "approximate", "exact"]) {
    const value = result[key];
    if (value !== undefined && value !== null && value !== "") return String(value);
  }
  return "已生成结构化结果";
}

interface PluginSurfaceProps {
  controller: WorkbenchController;
  contribution: PluginSurfaceContribution;
  projection?: DocumentProjection | null;
  onNavigateToSource(key: string, line?: number | null, column?: number | null): void;
  compact?: boolean;
  headingOrder?: 2 | 3 | 4;
}

function safeMessage(value: unknown, maximum: number): value is Record<string, unknown> {
  if (!value || typeof value !== "object" || Array.isArray(value)) return false;
  try {
    return JSON.stringify(value).length <= maximum;
  } catch {
    return false;
  }
}

export function PluginSurface({
  controller,
  contribution,
  projection,
  onNavigateToSource,
  compact = false,
  headingOrder,
}: PluginSurfaceProps) {
  const frameRef = useRef<HTMLIFrameElement>(null);
  const readyRef = useRef(false);
  const loadedEntryRef = useRef<string | null>(null);
  const frameSessionRef = useRef(0);
  const ownedJobsRef = useRef(new Set<string>());
  const liveJobsRef = useRef(new Set<string>());
  const pluginJobRef = useRef(controller.pluginJob);
  const [ready, setReady] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [liveJobIds, setLiveJobIds] = useState<string[]>([]);
  const verifiedResultsRef = useRef(new Map<string, OperationResult>());
  const [verifiedSlots, setVerifiedSlots] = useState<VerifiedResultSlot[]>([]);
  const [selectedProjection, setSelectedProjection] = useState<DocumentProjection | null>(null);
  const effectiveProjection = projection === undefined ? selectedProjection : projection;
  const pluginProtocol = controller.pluginSummary.protocol;
  const limits = pluginProtocol.limits;
  const apiVersion = pluginProtocol.api;
  const jobOwner = `${contribution.content_sha256}:${contribution.id}`;
  const pluginIdentity = useMemo(() => ({
    plugin_id: contribution.plugin_id,
    content_sha256: contribution.content_sha256,
    contribution_id: contribution.id,
  }), [contribution.content_sha256, contribution.id, contribution.plugin_id]);
  pluginJobRef.current = controller.pluginJob;
  const cancelLiveJobs = useCallback(() => {
    for (const jobId of liveJobsRef.current) {
      void pluginJobRef.current("cancel", jobOwner, { jobId }).catch(() => undefined);
    }
    liveJobsRef.current.clear();
    ownedJobsRef.current.clear();
    setLiveJobIds([]);
  }, [jobOwner]);
  const rememberVerifiedResult = useCallback((value: unknown) => {
    if (!record(value) || typeof value.operation_id !== "string") return;
    verifiedResultsRef.current.set(value.operation_id, value);
  }, []);

  useEffect(() => {
    verifiedResultsRef.current.clear();
    setVerifiedSlots([]);
  }, [jobOwner]);

  useEffect(() => {
    if (
      projection !== undefined
      || !contribution.permissions.includes("document.read")
      || !controller.currentDocument
      || controller.validation?.status !== "ok"
    ) {
      if (projection === undefined) setSelectedProjection(null);
      return;
    }
    let active = true;
    void controller.documentProjection(controller.currentDocument.key).then(
      (result) => { if (active) setSelectedProjection(result); },
      () => { if (active) setSelectedProjection(null); },
    );
    return () => { active = false; };
  }, [
    contribution.permissions,
    controller.currentDocument,
    controller.documentProjection,
    controller.validation?.status,
    projection,
  ]);

  const context = useMemo(() => {
    const value: Record<string, unknown> = {};
    if (contribution.permissions.includes("workspace.summary")) {
      value.workspace = effectiveProjection?.workspace ?? {
        documents: controller.documents.map((item) => ({
          key: item.key,
          title: item.title,
          kind: item.kind,
          read_only: item.read_only,
          package: item.package ? {
            name: item.package.name,
            version: item.package.version,
            content_sha256: item.package.content_sha256,
          } : null,
        })),
        packages: (controller.bootstrapData?.packages ?? []).map((item) => ({
          alias: item.alias,
          direct: item.direct,
          name: item.name,
          version: item.version,
          namespace: item.namespace,
          game: item.game,
          game_version: item.game_version,
          content_sha256: item.content_sha256,
        })),
      };
    }
    if (contribution.permissions.includes("document.read") && effectiveProjection) {
      value.document = effectiveProjection.document;
      value.members = effectiveProjection.members;
      value.relationships = effectiveProjection.relationships;
    }
    if (contribution.permissions.includes("draft.read")) {
      const document = controller.currentDocument;
      const source = document ? controller.buffers[document.key] : undefined;
      if (!document) {
        value.draft = { status: "unavailable", reason: "no_current_document" };
      } else if (document.read_only) {
        value.draft = { status: "unavailable", reason: "package_document_read_only" };
      } else if (typeof source !== "string") {
        value.draft = { status: "unavailable", reason: "document_not_loaded" };
      } else if (new TextEncoder().encode(source).length > limits.max_draft_source_bytes) {
        value.draft = { status: "unavailable", reason: "source_too_large" };
      } else {
        value.draft = {
          status: "ok",
          document: {
            key: document.key,
            path: document.path,
            title: document.title,
            kind: document.kind,
          },
          text: source,
          content_sha256: controller.validation?.source_sha256?.[document.key] ?? null,
          dirty: source !== (controller.originals[document.key] ?? ""),
        };
      }
    }
    if (contribution.permissions.includes("model.read")) {
      value.catalog = controller.validation?.status === "ok"
        ? controller.validation.catalog ?? controller.bootstrapData?.catalog
        : { status: "unavailable", reason: "workspace_invalid" };
    }
    if (contribution.permissions.includes("template.read")) {
      value.templates = (controller.bootstrapData?.templates ?? []).map((item) => ({
        value: item.value,
        id: item.id,
        label: item.label,
        kind: item.kind,
        origin: item.origin,
        package_name: item.package_name ?? null,
        package_version: item.package_version ?? null,
        bindings: item.bindings ?? [],
        error: item.error ?? null,
      }));
    }
    return value;
  }, [
    contribution.permissions,
    controller.bootstrapData?.packages,
    controller.bootstrapData?.templates,
    controller.buffers,
    controller.currentDocument,
    controller.documents,
    controller.originals,
    controller.validation?.status,
    controller.validation?.catalog,
    controller.validation?.source_sha256,
    controller.workspaceIndex,
    effectiveProjection,
    limits,
  ]);

  const post = useCallback((payload: Record<string, unknown>) => {
    if (!safeMessage(payload, limits.max_message_chars)) {
      setError("插件消息超过工作台限制。");
      return;
    }
    frameRef.current?.contentWindow?.postMessage(payload, "*");
  }, [limits.max_message_chars]);

  const activation = useCallback((type: "activate" | "context") => {
    post({
      protocol: PROTOCOL,
      api: apiVersion,
      type,
      contribution: {
        id: contribution.id,
        kind: contribution.kind,
        title: contribution.title,
        plugin_id: contribution.plugin_id,
        plugin_name: contribution.plugin_name,
        plugin_version: contribution.plugin_version,
        permissions: contribution.permissions,
        required_interfaces: contribution.required_interfaces,
        storage_schema: contribution.storage_schema,
      },
      capabilities: pluginProtocol,
      context,
    });
  }, [apiVersion, context, contribution, pluginProtocol, post]);

  useEffect(() => {
    readyRef.current = false;
    setReady(false);
    setError(null);
    const timeout = window.setTimeout(() => {
      if (!readyRef.current) setError("插件没有在限定时间内完成初始化。");
    }, 6000);
    return () => window.clearTimeout(timeout);
  }, [contribution.id, contribution.entry_url]);

  useEffect(() => {
    if (readyRef.current) activation("context");
  }, [activation]);

  useEffect(() => {
    if (!liveJobIds.length) return;
    let active = true;
    const poll = async () => {
      const completed: string[] = [];
      await Promise.all(liveJobIds.map(async (jobId) => {
        try {
          const job = await controller.pluginJob("status", jobOwner, { jobId });
          if (!active) return;
          if (job.state === "completed") rememberVerifiedResult(job.result);
          post({ type: "job-update", job });
          if (!["queued", "running"].includes(job.state)) completed.push(jobId);
        } catch (caught) {
          if (!active) return;
          completed.push(jobId);
          post({
            type: "job-update",
            job: {
              job_id: jobId,
              operation: "analyze",
              state: "failed",
              stage: "failed",
              cancellable: false,
              error: {
                code: caught instanceof ApiError && typeof caught.payload.code === "string"
                  ? caught.payload.code
                  : "operation_failed",
                message: caught instanceof Error ? caught.message : "任务状态不可用。",
              },
            },
          });
        }
      }));
      if (completed.length) {
        completed.forEach((jobId) => liveJobsRef.current.delete(jobId));
        setLiveJobIds([...liveJobsRef.current]);
      }
    };
    void poll();
    const timer = window.setInterval(() => { void poll(); }, 300);
    return () => {
      active = false;
      window.clearInterval(timer);
    };
  }, [controller.pluginJob, jobOwner, liveJobIds, post, rememberVerifiedResult]);

  useEffect(() => () => {
    frameSessionRef.current += 1;
    cancelLiveJobs();
  }, [cancelLiveJobs]);

  useEffect(() => {
    const onMessage = (event: MessageEvent) => {
      if (event.source !== frameRef.current?.contentWindow || !safeMessage(event.data, limits.max_message_chars)) return;
      const message = event.data;
      if (message.protocol !== PROTOCOL || message.api !== apiVersion || typeof message.type !== "string") return;
      if (message.type === "ready") {
        readyRef.current = true;
        setReady(true);
        setError(null);
        activation("activate");
        return;
      }
      if (
        message.type !== "action"
        || typeof message.id !== "string"
        || message.id.length > limits.max_action_id_chars
      ) return;
      const action = typeof message.action === "string" ? message.action : "";
      const payload = safeMessage(message.payload, limits.max_message_chars) ? message.payload : {};
      const reply = (type: "action-result" | "action-error", result: unknown) => {
        const response = {
          protocol: PROTOCOL,
          api: apiVersion,
          type,
          id: message.id,
          ...(type === "action-result" ? { result } : { error: result }),
        };
        if (safeMessage(response, limits.max_message_chars)) {
          post(response);
        } else {
          post({
            protocol: PROTOCOL,
            api: apiVersion,
            type: "action-error",
            id: message.id,
            error: { code: "result_too_large", message: "数学操作结果超过插件消息大小限制。" },
          });
        }
      };
      const capability = pluginProtocol.actions[action];
      if (!capability) {
        reply("action-error", { code: "unsupported_capability", message: "插件请求的 action 不受支持。" });
        return;
      }
      if (!contribution.permissions.includes(capability.permission)) {
        reply("action-error", {
          code: "permission_denied",
          message: `${capability.permission} was not granted`,
        });
        return;
      }
      const requireValidModel = () => {
        if (controller.validation?.status !== "ok") {
          throw new PluginActionError("workspace_invalid", "当前工作区无效，不能执行插件数学操作。");
        }
      };
      const perform = async () => {
        if (capability.handler === "catalog") {
          const result = await controller.modelCatalog(action, payload);
          reply("action-result", result);
          return;
        }
        if (capability.handler === "proposal") {
          const result = await controller.proposePluginTransaction({
            pluginId: contribution.plugin_id,
            pluginName: contribution.plugin_name,
            pluginVersion: contribution.plugin_version,
            pluginContentSha256: contribution.content_sha256,
            contributionId: contribution.id,
            revision: requiredText(payload.revision, "revision", limits.max_identity_chars),
            title: requiredText(payload.title, "title", limits.max_title_chars),
            description: optionalText(payload.description, "description", limits.max_description_chars),
            changes: Array.isArray(payload.changes)
              ? payload.changes as PluginProposalRequestChange[]
              : [],
          });
          reply("action-result", {
            status: result.status,
            proposal_id: result.proposalId,
            reason: result.reason,
            errors: result.errors,
          });
          return;
        }
        if (capability.handler === "result") {
          const handle = requiredText(payload.handle, "handle", limits.max_identity_chars);
          const envelope = verifiedResultsRef.current.get(handle);
          if (!envelope) {
            throw new PluginActionError("unknown_identity", "结果 handle 不属于当前 Plugin contribution。");
          }
          const order = payload.order === undefined ? 0 : Number(payload.order);
          if (!Number.isInteger(order) || order < -100 || order > 100) {
            throw new PluginActionError("invalid_request", "结果排序必须是 -100 到 100 的整数。");
          }
          const title = optionalText(payload.title, "title", limits.max_title_chars)
            ?? String(envelope.operation ?? "核心计算结果");
          setVerifiedSlots((current) => [
            ...current.filter((item) => item.handle !== handle),
            { handle, title, order, envelope },
          ].sort((left, right) => left.order - right.order || left.handle.localeCompare(right.handle)));
          reply("action-result", { status: "ok", handle });
          return;
        }
        if (capability.handler === "storage") {
          const storageAction = action.split(".")[1];
          if (!(["get", "set", "delete"] as string[]).includes(storageAction)) {
            throw new PluginActionError("unsupported_capability", "偏好操作不受支持。");
          }
          const result = await controller.pluginStorage(
            storageAction as "get" | "set" | "delete",
            pluginIdentity,
            payload,
          );
          reply("action-result", result);
          return;
        }
        if (capability.handler === "job") {
          const jobId = requiredText(payload.job_id, "job_id", limits.max_identity_chars);
          if (!ownedJobsRef.current.has(jobId)) {
            throw new PluginActionError("unknown_identity", "这个任务不属于当前 Plugin contribution。");
          }
          const job = await controller.pluginJob(
            action === "job.cancel" ? "cancel" : "status",
            jobOwner,
            { jobId },
          );
          if (!["queued", "running"].includes(job.state)) {
            liveJobsRef.current.delete(job.job_id);
            setLiveJobIds([...liveJobsRef.current]);
          }
          if (job.state === "completed") rememberVerifiedResult(job.result);
          reply("action-result", job);
          return;
        }
        if (capability.handler === "operation") {
          requireValidModel();
          if (capability.execution === "job") {
            const frameSession = frameSessionRef.current;
            const job = await controller.pluginJob("start", jobOwner, {
              action,
              payload,
            });
            ownedJobsRef.current.add(job.job_id);
            if (frameSession !== frameSessionRef.current) {
              await controller.pluginJob("cancel", jobOwner, { jobId: job.job_id });
              ownedJobsRef.current.delete(job.job_id);
              return;
            }
            liveJobsRef.current.add(job.job_id);
            setLiveJobIds([...liveJobsRef.current]);
            reply("action-result", job);
            return;
          }
          const result = await controller.pluginOperation(action, payload);
          rememberVerifiedResult(result);
          reply("action-result", result);
          return;
        }
        throw new PluginActionError("unsupported_capability", "插件请求的 action 不受支持。");
      };
      if (action === "navigate-source") {
        const key = payload.key;
        const line = payload.line;
        const column = payload.column;
        if (
          typeof key !== "string"
          || !controller.documents.some((item) => item.key === key)
          || (line !== undefined && line !== null && (!Number.isInteger(line) || Number(line) < 1))
          || (column !== undefined && column !== null && (!Number.isInteger(column) || Number(column) < 1))
        ) {
          reply("action-error", { code: "invalid_request", message: "invalid source location" });
          return;
        }
        onNavigateToSource(key, line == null ? null : Number(line), column == null ? null : Number(column));
        reply("action-result", { status: "ok" });
        return;
      }
      void perform().catch((caught) => {
        const candidateCode = caught instanceof PluginActionError
          ? caught.code
          : caught instanceof ApiError && typeof caught.payload.code === "string"
            ? caught.payload.code
            : "operation_failed";
        reply("action-error", {
          code: Object.prototype.hasOwnProperty.call(pluginProtocol.errors, candidateCode)
            ? candidateCode
            : "operation_failed",
          message: caught instanceof Error ? caught.message : "数学操作未完成。",
        });
      });
    };
    window.addEventListener("message", onMessage);
    return () => window.removeEventListener("message", onMessage);
  }, [activation, apiVersion, contribution, controller, limits, onNavigateToSource, pluginIdentity, pluginProtocol.actions, post, rememberVerifiedResult]);

  if (!contribution.entry_url.startsWith("/plugins/")) {
    return <EmptyState
      icon={<ShieldAlert size={22} />}
      title="插件入口被拒绝"
      description="插件入口不属于已验证的不可变内容存储。"
      headingOrder={headingOrder ?? (compact ? 3 : 2)}
    />;
  }

  return (
    <Box className={`plugin-surface${compact ? " is-compact" : ""}`}>
      <Group className="plugin-surface-header" justify="space-between" wrap="nowrap">
        <Group gap={7} wrap="nowrap">
          <Puzzle size={14} />
          <Title className="plugin-surface-title" order={headingOrder ?? (compact ? 3 : 2)}>{contribution.title}</Title>
        </Group>
        <Group gap={5} wrap="nowrap">
          <Badge variant="outline" color="gray" size="xs">第三方 Plugin 呈现</Badge>
          <Badge variant="outline" color="gray" size="xs">{contribution.plugin_name} {contribution.plugin_version}</Badge>
        </Group>
      </Group>
      <div className={`plugin-surface-body${verifiedSlots.length ? " has-verified-results" : ""}`}>
        {!ready && !error && <div className="plugin-surface-state"><LoadingState label="正在启动沙箱插件…" /></div>}
        {error && <div className="plugin-surface-state"><EmptyState icon={<ShieldAlert size={22} />} title="插件未能启动" description={error} /></div>}
        <iframe
          ref={frameRef}
          className={`plugin-frame${ready && !error ? " is-ready" : ""}`}
          src={contribution.entry_url}
          title={`${contribution.title}（由 ${contribution.plugin_name} 提供）`}
          sandbox="allow-scripts"
          referrerPolicy="no-referrer"
          onLoad={() => {
            if (loadedEntryRef.current !== contribution.entry_url) {
              loadedEntryRef.current = contribution.entry_url;
              return;
            }
            frameSessionRef.current += 1;
            cancelLiveJobs();
            readyRef.current = false;
            setReady(false);
          }}
        />
        {verifiedSlots.length > 0 && <aside className="plugin-verified-results" aria-label="Kirin Tor 核心计算结果">
          {verifiedSlots.map((slot) => {
            const stale = slot.envelope.revision !== controller.validation?.catalog?.revision;
            const provenance = record(slot.envelope.provenance) ? slot.envelope.provenance : {};
            const targets = Array.isArray(provenance.targets) ? provenance.targets.filter(record) : [];
            const rows = resultRows(slot.envelope);
            const source = targets.map((item) => record(item.source_location) ? item.source_location : null).find(record);
            const sourceDocument = source
              ? controller.documents.find((item) => item.id === source.document)
              : undefined;
            return <Box className={`plugin-verified-result${stale ? " is-stale" : ""}`} key={slot.handle}>
              <Group justify="space-between" align="flex-start" wrap="nowrap">
                <Box>
                  <Group gap={5}>
                    <CheckCircle2 size={14} />
                    <Badge color={stale ? "orange" : "green"} variant="light">
                      {stale ? "模型已变化" : "Kirin Tor 核心计算"}
                    </Badge>
                  </Group>
                  <Text fw={680} fz="sm" mt={6}>{slot.title}</Text>
                </Box>
                <Button
                  variant="subtle"
                  color="gray"
                  size="compact-xs"
                  aria-label={`移除核心结果 ${slot.title}`}
                  onClick={() => setVerifiedSlots((current) => current.filter((item) => item.handle !== slot.handle))}
                ><X size={13} /></Button>
              </Group>
              <Stack gap={7} mt="sm">
                {rows.map((row, index) => <Box className="plugin-verified-value" key={`${slot.handle}-${index}`}>
                  <Text c="dimmed" fz="xs">{String(row.target ?? targets[index]?.id ?? slot.envelope.operation ?? "结果")}</Text>
                  <Text fw={720}>{displayedValue(row)}</Text>
                  <Group gap={5} mt={3}>
                    {row.unit !== undefined && <Badge variant="outline" color="gray">{String(row.unit)}</Badge>}
                    {row.exact !== undefined && <Code>{String(row.exact)}</Code>}
                  </Group>
                </Box>)}
              </Stack>
              <Group justify="space-between" mt="sm" wrap="nowrap">
                <Text c="dimmed" fz="xs">revision {String(slot.envelope.revision ?? "").slice(0, 12)}</Text>
                {source && sourceDocument && <Button
                  variant="subtle"
                  color="gray"
                  size="compact-xs"
                  leftSection={<Crosshair size={12} />}
                  onClick={() => onNavigateToSource(
                    sourceDocument.key,
                    typeof source.line === "number" ? source.line : null,
                    typeof source.column === "number" ? source.column : null,
                  )}
                >来源</Button>}
              </Group>
              {Array.isArray(slot.envelope.warnings) && slot.envelope.warnings.length > 0 && <Text c="orange" fz="xs" mt={6}>
                {slot.envelope.warnings.map(String).join("；")}
              </Text>}
            </Box>;
          })}
        </aside>}
      </div>
    </Box>
  );
}
