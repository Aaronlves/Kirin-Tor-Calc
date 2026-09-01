import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Badge, Box, Group, Text } from "@mantine/core";
import { Puzzle, ShieldAlert } from "lucide-react";

import type { WorkbenchController } from "../hooks/useWorkbench";
import type { DocumentProjection, PluginSurfaceContribution } from "../types";
import { EmptyState, LoadingState } from "./ui";

const PROTOCOL = "kirin-workbench-plugin";
const MAX_MESSAGE_CHARS = 1_000_000;

interface PluginSurfaceProps {
  controller: WorkbenchController;
  contribution: PluginSurfaceContribution;
  projection?: DocumentProjection | null;
  onNavigateToSource(key: string, line?: number | null, column?: number | null): void;
  compact?: boolean;
}

function safeMessage(value: unknown): value is Record<string, unknown> {
  if (!value || typeof value !== "object" || Array.isArray(value)) return false;
  try {
    return JSON.stringify(value).length <= MAX_MESSAGE_CHARS;
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
}: PluginSurfaceProps) {
  const frameRef = useRef<HTMLIFrameElement>(null);
  const readyRef = useRef(false);
  const [ready, setReady] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [selectedProjection, setSelectedProjection] = useState<DocumentProjection | null>(null);
  const effectiveProjection = projection === undefined ? selectedProjection : projection;

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
    return value;
  }, [contribution.permissions, controller.bootstrapData?.packages, controller.documents, effectiveProjection]);

  const post = useCallback((payload: Record<string, unknown>) => {
    if (!safeMessage(payload)) {
      setError("插件消息超过工作台限制。");
      return;
    }
    frameRef.current?.contentWindow?.postMessage(payload, "*");
  }, []);

  const activation = useCallback((type: "activate" | "context") => {
    post({
      protocol: PROTOCOL,
      api: 1,
      type,
      contribution: {
        id: contribution.id,
        kind: contribution.kind,
        title: contribution.title,
        plugin_id: contribution.plugin_id,
        plugin_name: contribution.plugin_name,
        plugin_version: contribution.plugin_version,
        permissions: contribution.permissions,
      },
      context,
    });
  }, [context, contribution, post]);

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
      if (event.source !== frameRef.current?.contentWindow || !safeMessage(event.data)) return;
      const message = event.data;
      if (message.protocol !== PROTOCOL || message.api !== 1 || typeof message.type !== "string") return;
      if (message.type === "ready") {
        readyRef.current = true;
        setReady(true);
        setError(null);
        activation("activate");
        return;
      }
      if (message.type !== "action" || typeof message.id !== "string" || message.id.length > 80) return;
      const action = message.action;
      const payload = safeMessage(message.payload) ? message.payload : {};
      const reply = (type: "action-result" | "action-error", result: unknown) => post({
        protocol: PROTOCOL,
        api: 1,
        type,
        id: message.id,
        ...(type === "action-result" ? { result } : { error: result }),
      });
      if (action === "navigate-source") {
        if (!contribution.permissions.includes("source.navigate")) {
          reply("action-error", { code: "permission_denied", message: "source.navigate was not granted" });
          return;
        }
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
      if (action === "evaluate") {
        if (!contribution.permissions.includes("operation.evaluate")) {
          reply("action-error", { code: "permission_denied", message: "operation.evaluate was not granted" });
          return;
        }
        const target = payload.target;
        if (typeof target !== "string" || !controller.workspaceIndex.targets.some((item) => item.value === target)) {
          reply("action-error", { code: "invalid_action", message: "target is not a validated workspace output" });
          return;
        }
        void controller.operation("eval", {
          target,
          precision: 30,
          display_digits: 12,
          timeout: 10,
        }).then(
          (result) => reply("action-result", result),
          (caught) => reply("action-error", {
            code: "operation_failed",
            message: caught instanceof Error ? caught.message : "evaluation failed",
          }),
        );
        return;
      }
      reply("action-error", { code: "unsupported_action", message: "plugin action is not supported" });
    };
    window.addEventListener("message", onMessage);
    return () => window.removeEventListener("message", onMessage);
  }, [activation, contribution.permissions, controller, onNavigateToSource, post]);

  if (!contribution.entry_url.startsWith("/plugins/")) {
    return <EmptyState icon={<ShieldAlert size={22} />} title="插件入口被拒绝" description="插件入口不属于已验证的不可变内容存储。" />;
  }

  return (
    <Box className={`plugin-surface${compact ? " is-compact" : ""}`}>
      <Group className="plugin-surface-header" justify="space-between" wrap="nowrap">
        <Group gap={7} wrap="nowrap">
          <Puzzle size={14} />
          <Text fz="xs" fw={650}>{contribution.title}</Text>
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
