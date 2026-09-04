import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Badge, Box, Group, Title } from "@mantine/core";
import { Puzzle, ShieldAlert } from "lucide-react";

import type { WorkbenchController } from "../hooks/useWorkbench";
import type {
  DocumentProjection,
  InputItem,
  PluginSurfaceContribution,
  TargetItem,
  WorkspaceIndex,
} from "../types";
import { EmptyState, LoadingState } from "./ui";

const PROTOCOL = "kirin-workbench-plugin";

type JsonRecord = Record<string, unknown>;

class PluginActionError extends Error {
  code: string;

  constructor(code: string, message: string) {
    super(message);
    this.name = "PluginActionError";
    this.code = code;
  }
}

function isRecord(value: unknown): value is JsonRecord {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

function requiredText(value: unknown, label: string, maximum: number): string {
  if (typeof value !== "string" || !value.trim() || value.length > maximum) {
    throw new PluginActionError("invalid_action", `${label} 必须是长度不超过 ${maximum} 的非空文本。`);
  }
  return value.trim();
}

function optionalText(value: unknown, label: string, maximum: number): string | undefined {
  if (value === undefined || value === null || value === "") return undefined;
  return requiredText(value, label, maximum);
}

function proposedSource(value: unknown, maximum: number): string {
  if (typeof value !== "string" || !value || new TextEncoder().encode(value).length > maximum) {
    throw new PluginActionError(
      "invalid_action",
      `text 必须是非空且不超过 ${maximum} 字节的 Kirin Tor 源码。`,
    );
  }
  return value;
}

function targetFor(index: WorkspaceIndex, value: unknown, maximum: number): TargetItem {
  const id = requiredText(value, "target", maximum);
  const target = index.targets.find((item) => item.value === id);
  if (!target) throw new PluginActionError("invalid_action", "target 不是当前有效工作区中的公开输出。");
  return target;
}

function inputFor(index: WorkspaceIndex, value: unknown, maximum: number, allowed?: Set<string>): InputItem {
  const id = requiredText(value, "input", maximum);
  const input = index.inputs.find((item) => item.value === id);
  if (!input || (allowed && !allowed.has(id))) {
    throw new PluginActionError("invalid_action", "input 不是该数学操作可使用的公开输入。");
  }
  return input;
}

function presetFor(index: WorkspaceIndex, value: unknown, maximum: number): string | undefined {
  const preset = optionalText(value, "preset", maximum);
  if (!preset) return undefined;
  if (!index.presets.some((item) => item.value === preset)) {
    throw new PluginActionError("invalid_action", "preset 不是当前有效工作区中的具名方案。");
  }
  return preset;
}

function operationValue(value: unknown, label: string, maximum: number): string {
  if (typeof value === "boolean") return value ? "true" : "false";
  if (typeof value === "number" && Number.isFinite(value)) return String(value);
  return requiredText(value, label, maximum);
}

function overridesFor(
  index: WorkspaceIndex,
  value: unknown,
  allowed: Set<string>,
  identityMaximum: number,
  expressionMaximum: number,
  reserved: Set<string> = new Set(),
): Record<string, string> {
  if (value === undefined || value === null) return {};
  if (!isRecord(value)) {
    throw new PluginActionError("invalid_action", "overrides 必须是公开输入到数值文本的对象。");
  }
  const entries = Object.entries(value);
  if (entries.length > index.inputs.length) {
    throw new PluginActionError("invalid_action", "overrides 超过当前工作区的输入数量。");
  }
  const result: Record<string, string> = {};
  for (const [name, raw] of entries) {
    inputFor(index, name, identityMaximum, allowed);
    if (reserved.has(name)) {
      throw new PluginActionError("invalid_action", `${name} 已是当前求解或扫描变量，不能同时覆盖。`);
    }
    result[name] = operationValue(raw, `override ${name}`, expressionMaximum);
  }
  return result;
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
  const [ready, setReady] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [selectedProjection, setSelectedProjection] = useState<DocumentProjection | null>(null);
  const effectiveProjection = projection === undefined ? selectedProjection : projection;
  const pluginProtocol = controller.pluginSummary.protocol;
  const limits = pluginProtocol.limits;
  const apiVersion = Number(pluginProtocol.api);

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
          dirty: source !== (controller.originals[document.key] ?? ""),
        };
      }
    }
    if (contribution.permissions.includes("model.read")) {
      value.catalog = controller.validation?.status === "ok"
        ? controller.validation.catalog ?? controller.bootstrapData?.catalog
        : { status: "unavailable", reason: "workspace_invalid" };
    }
    return value;
  }, [
    contribution.permissions,
    controller.bootstrapData?.packages,
    controller.buffers,
    controller.currentDocument,
    controller.documents,
    controller.originals,
    controller.validation?.status,
    controller.validation?.catalog,
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
        reply("action-error", { code: "unsupported_action", message: "插件请求的 action 不受支持。" });
        return;
      }
      if (!contribution.permissions.includes(capability.permission)) {
        reply("action-error", {
          code: "permission_denied",
          message: `${capability.permission} was not granted`,
        });
        return;
      }
      const operationName = (): string => {
        if (capability.handler !== "operation" || !capability.operation) {
          throw new PluginActionError("unsupported_action", "该 action 没有可调用的数学后端操作。");
        }
        return capability.operation;
      };
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
        if (action === "propose-draft") {
          const key = requiredText(payload.key, "key", limits.max_path_chars);
          if (key !== controller.currentDocument?.key) {
            throw new PluginActionError("invalid_action", "插件只能为当前文档提交草稿提案。");
          }
          const result = await controller.proposePluginDraft({
            pluginId: contribution.plugin_id,
            pluginName: contribution.plugin_name,
            pluginVersion: contribution.plugin_version,
            pluginContentSha256: contribution.content_sha256,
            contributionId: contribution.id,
            documentKey: key,
            title: requiredText(payload.title, "title", limits.max_title_chars),
            description: optionalText(payload.description, "description", limits.max_description_chars),
            proposedText: proposedSource(payload.text, limits.max_draft_source_bytes),
          });
          reply("action-result", {
            status: result.status,
            proposal_id: result.proposalId,
            reason: result.reason,
            errors: result.errors,
          });
          return;
        }
        requireValidModel();
        const index = controller.workspaceIndex;
        if (action === "evaluate") {
          const target = targetFor(index, payload.target, limits.max_identity_chars);
          const allowed = new Set(target.inputs ?? []);
          const result = await controller.operation(operationName(), {
            target: target.value,
            preset: presetFor(index, payload.preset, limits.max_identity_chars),
            overrides: overridesFor(
              index,
              payload.overrides,
              allowed,
              limits.max_identity_chars,
              limits.max_expression_chars,
            ),
            precision: 30,
            display_digits: 12,
            timeout: limits.standard_operation_timeout_seconds,
          });
          reply("action-result", result);
          return;
        }
        if (action === "explain") {
          const target = targetFor(index, payload.target, limits.max_identity_chars);
          const result = await controller.operation(operationName(), {
            target: target.value,
            timeout: limits.standard_operation_timeout_seconds,
          });
          reply("action-result", result);
          return;
        }
        if (action === "compare") {
          const target = targetFor(index, payload.target, limits.max_identity_chars);
          if (
            !Array.isArray(payload.variants)
            || payload.variants.length < 1
            || payload.variants.length > limits.max_comparison_variants
          ) {
            throw new PluginActionError(
              "invalid_action",
              `variants 必须包含 1 至 ${limits.max_comparison_variants} 个方案。`,
            );
          }
          const allowed = new Set(target.inputs ?? []);
          const names = new Set<string>();
          const variants = payload.variants.map((raw, variantIndex) => {
            if (!isRecord(raw)) throw new PluginActionError("invalid_action", "每个 variant 必须是对象。");
            const name = requiredText(
              raw.name,
              `variant ${variantIndex + 1} name`,
              limits.max_variant_name_chars,
            );
            if (names.has(name)) throw new PluginActionError("invalid_action", "variant 名称不能重复。");
            names.add(name);
            return {
              name,
              preset: presetFor(index, raw.preset, limits.max_identity_chars),
              overrides: overridesFor(
                index,
                raw.overrides,
                allowed,
                limits.max_identity_chars,
                limits.max_expression_chars,
              ),
            };
          });
          const result = await controller.operation(operationName(), {
            target: target.value,
            variants,
            precision: 30,
            display_digits: 12,
            timeout: limits.standard_operation_timeout_seconds,
          });
          reply("action-result", result);
          return;
        }
        if (action === "scan") {
          if (
            !Array.isArray(payload.targets)
            || payload.targets.length < 1
            || payload.targets.length > limits.max_operation_targets
          ) {
            throw new PluginActionError(
              "invalid_action",
              `targets 必须包含 1 至 ${limits.max_operation_targets} 个公开输出。`,
            );
          }
          const targets = payload.targets.map((item) => targetFor(index, item, limits.max_identity_chars));
          const allowed = new Set(targets.flatMap((item) => item.inputs ?? []));
          const x = inputFor(index, payload.x, limits.max_identity_chars, allowed).value;
          const points = payload.points === undefined ? 41 : payload.points;
          if (!Number.isInteger(points) || Number(points) < 2 || Number(points) > limits.max_scan_points) {
            throw new PluginActionError("invalid_action", `points 必须是 2 至 ${limits.max_scan_points} 的整数。`);
          }
          const result = await controller.operation(operationName(), {
            x,
            range: requiredText(payload.range, "range", limits.max_expression_chars),
            points: Number(points),
            targets: targets.map((item) => item.value),
            preset: presetFor(index, payload.preset, limits.max_identity_chars),
            overrides: overridesFor(
              index,
              payload.overrides,
              allowed,
              limits.max_identity_chars,
              limits.max_expression_chars,
              new Set([x]),
            ),
            precision: 30,
            display_digits: 12,
            timeout: limits.standard_operation_timeout_seconds,
          });
          reply("action-result", result);
          return;
        }
        if (action === "grid") {
          const target = targetFor(index, payload.target, limits.max_identity_chars);
          const allowed = new Set(target.inputs ?? []);
          const x = inputFor(index, payload.x, limits.max_identity_chars, allowed).value;
          const y = inputFor(index, payload.y, limits.max_identity_chars, allowed).value;
          if (x === y) throw new PluginActionError("invalid_action", "二维网格的 x 与 y 必须是不同输入。");
          const xPoints = payload.x_points === undefined ? 21 : payload.x_points;
          const yPoints = payload.y_points === undefined ? 21 : payload.y_points;
          if (
            !Number.isInteger(xPoints)
            || !Number.isInteger(yPoints)
            || Number(xPoints) < 2
            || Number(yPoints) < 2
            || Number(xPoints) * Number(yPoints) > limits.max_scan_points
          ) {
            throw new PluginActionError(
              "invalid_action",
              `网格轴至少各 2 点，且总点数不能超过 ${limits.max_scan_points}。`,
            );
          }
          const result = await controller.operation(operationName(), {
            x,
            x_range: requiredText(payload.x_range, "x_range", limits.max_expression_chars),
            x_points: Number(xPoints),
            y,
            y_range: requiredText(payload.y_range, "y_range", limits.max_expression_chars),
            y_points: Number(yPoints),
            target: target.value,
            preset: presetFor(index, payload.preset, limits.max_identity_chars),
            overrides: overridesFor(
              index,
              payload.overrides,
              allowed,
              limits.max_identity_chars,
              limits.max_expression_chars,
              new Set([x, y]),
            ),
            precision: 30,
            display_digits: 12,
            timeout: limits.standard_operation_timeout_seconds,
          });
          reply("action-result", result);
          return;
        }
        if (action === "solve") {
          const target = targetFor(index, payload.target, limits.max_identity_chars);
          const allowed = new Set(target.inputs ?? []);
          const variable = inputFor(index, payload.variable, limits.max_identity_chars, allowed).value;
          const result = await controller.operation(operationName(), {
            target: target.value,
            variable,
            equals: requiredText(payload.equals, "equals", limits.max_expression_chars),
            range: optionalText(payload.range, "range", limits.max_expression_chars),
            preset: presetFor(index, payload.preset, limits.max_identity_chars),
            overrides: overridesFor(
              index,
              payload.overrides,
              allowed,
              limits.max_identity_chars,
              limits.max_expression_chars,
              new Set([variable]),
            ),
            precision: 30,
            timeout: limits.standard_operation_timeout_seconds,
          });
          reply("action-result", result);
          return;
        }
        if (action === "analyze") {
          const target = requiredText(payload.target, "analysis target", limits.max_identity_chars);
          if (!index.analyses.some((item) => item.value === target)) {
            throw new PluginActionError("invalid_action", "target 不是当前有效工作区中的具名 Process Analysis。");
          }
          const includeTrace = payload.include_trace ?? false;
          if (typeof includeTrace !== "boolean") {
            throw new PluginActionError("invalid_action", "include_trace 必须是布尔值。");
          }
          const result = await controller.operation(operationName(), {
            target,
            include_trace: includeTrace,
            timeout: limits.analysis_timeout_seconds,
          });
          reply("action-result", result);
          return;
        }
        throw new PluginActionError("unsupported_action", "插件请求的 action 不受支持。");
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
          reply("action-error", { code: "invalid_action", message: "invalid source location" });
          return;
        }
        onNavigateToSource(key, line == null ? null : Number(line), column == null ? null : Number(column));
        reply("action-result", { status: "ok" });
        return;
      }
      void perform().catch((caught) => {
        reply("action-error", {
          code: caught instanceof PluginActionError ? caught.code : "operation_failed",
          message: caught instanceof Error ? caught.message : "数学操作未完成。",
        });
      });
    };
    window.addEventListener("message", onMessage);
    return () => window.removeEventListener("message", onMessage);
  }, [activation, apiVersion, contribution, controller, limits, onNavigateToSource, pluginProtocol.actions, post]);

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
        <Badge variant="outline" color="gray" size="xs">{contribution.plugin_name} {contribution.plugin_version}</Badge>
      </Group>
      {!ready && !error && <div className="plugin-surface-state"><LoadingState label="正在启动沙箱插件…" /></div>}
      {error && <div className="plugin-surface-state"><EmptyState icon={<ShieldAlert size={22} />} title="插件未能启动" description={error} /></div>}
      <iframe
        ref={frameRef}
        className={`plugin-frame${ready && !error ? " is-ready" : ""}`}
        src={contribution.entry_url}
        title={`${contribution.title}（由 ${contribution.plugin_name} 提供）`}
        sandbox="allow-scripts"
        referrerPolicy="no-referrer"
      />
    </Box>
  );
}
