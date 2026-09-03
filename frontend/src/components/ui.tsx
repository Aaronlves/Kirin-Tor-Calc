import { useEffect, useId, type ReactNode } from "react";
import {
  ActionIcon,
  Box,
  Button,
  Center,
  Code,
  Collapse,
  Group,
  Loader,
  Paper,
  Stack,
  Text,
  Title,
  Tooltip,
} from "@mantine/core";
import { ArrowLeft, ChevronRight, FileQuestion, RotateCcw } from "lucide-react";

import type { OperationResult } from "../types";

export function Surface({
  children,
  className = "",
  component = "div",
  ariaLabel,
  ariaLabelledby,
}: {
  children: ReactNode;
  className?: string;
  component?: "article" | "div" | "section";
  ariaLabel?: string;
  ariaLabelledby?: string;
}) {
  return <Paper component={component} aria-label={ariaLabel} aria-labelledby={ariaLabelledby} className={`surface ${className}`.trim()}>{children}</Paper>;
}

export function PageIntro({
  kicker,
  title,
  description,
  actions,
  headingOrder = 2,
  compact = true,
}: {
  kicker: string;
  title: string;
  description: string;
  actions?: ReactNode;
  headingOrder?: 2 | 3;
  compact?: boolean;
}) {
  return (
    <div className={`page-intro${compact ? " compact" : ""}`}>
      <Box>
        <Text className="page-kicker">{kicker}</Text>
        <Title order={headingOrder}>{title}</Title>
        <Text c="dimmed" fz="sm" mt={5}>{description}</Text>
      </Box>
      {actions}
    </div>
  );
}

export function ToolSubview({
  title,
  description,
  backLabel = "返回",
  backDisabled = false,
  onBack,
  children,
}: {
  title: string;
  description?: string;
  backLabel?: string;
  backDisabled?: boolean;
  onBack(): void;
  children: ReactNode;
}) {
  const titleId = useId();
  useEffect(() => {
    const handleEscape = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      event.preventDefault();
      event.stopPropagation();
      if (!backDisabled) onBack();
    };
    document.addEventListener("keydown", handleEscape, true);
    return () => document.removeEventListener("keydown", handleEscape, true);
  }, [backDisabled, onBack]);
  return (
    <section className="tool-subview" aria-labelledby={titleId}>
      <header className="tool-subview-header">
        <Button variant="subtle" color="gray" leftSection={<ArrowLeft size={14} />} disabled={backDisabled} onClick={onBack}>{backLabel}</Button>
        <Box>
          <Title id={titleId} order={3}>{title}</Title>
          {description && <Text c="dimmed" fz="xs" mt={3}>{description}</Text>}
        </Box>
      </header>
      <div className="tool-subview-body">{children}</div>
    </section>
  );
}

export function WorkspaceToolFrame({
  returnLabel,
  onReturn,
  children,
}: {
  returnLabel?: string;
  onReturn?(): void;
  children: ReactNode;
}) {
  return (
    <div className={`workspace-tool-frame${returnLabel && onReturn ? " has-parent" : ""}`}>
      {returnLabel && onReturn && (
        <div className="workspace-tool-parent-bar">
          <Button variant="subtle" color="gray" size="xs" leftSection={<ArrowLeft size={13} />} onClick={onReturn}>返回{returnLabel}</Button>
        </div>
      )}
      <div className="workspace-tool-frame-content">{children}</div>
    </div>
  );
}

export function SectionHeading({
  title,
  description,
  actions,
}: {
  title: string;
  description?: string;
  actions?: ReactNode;
}) {
  return (
    <Group className="section-heading" justify="space-between" align="center" wrap="nowrap">
      <Box>
        <Title order={2}>{title}</Title>
        {description && <Text c="dimmed" fz="xs" mt={2}>{description}</Text>}
      </Box>
      {actions && <Group gap="xs" wrap="nowrap">{actions}</Group>}
    </Group>
  );
}

export function EmptyState({
  title,
  description,
  action,
  icon = <FileQuestion size={22} strokeWidth={1.5} />,
  headingOrder = 3,
}: {
  title: string;
  description: string;
  action?: ReactNode;
  icon?: ReactNode;
  headingOrder?: 2 | 3 | 4 | 5 | 6;
}) {
  return (
    <Center className="empty-state">
      <Stack align="center" gap="xs">
        <div className="empty-state-icon">{icon}</div>
        <Title order={headingOrder} className="empty-state-title">{title}</Title>
        <Text c="dimmed" fz="xs" ta="center" maw={380}>{description}</Text>
        {action}
      </Stack>
    </Center>
  );
}

export function LoadingState({ label = "正在加载…" }: { label?: string }) {
  return (
    <Center className="loading-state">
      <Stack align="center" gap="sm">
        <Loader size="sm" color="orange" />
        <Text c="dimmed" fz="xs">{label}</Text>
      </Stack>
    </Center>
  );
}

export function Disclosure({
  label,
  opened,
  onToggle,
  children,
}: {
  label: string;
  opened: boolean;
  onToggle(): void;
  children: ReactNode;
}) {
  return (
    <Box className="disclosure">
      <button className="disclosure-trigger" type="button" onClick={onToggle} aria-expanded={opened}>
        <ChevronRight className="disclosure-chevron" size={15} />
        <span>{label}</span>
      </button>
      <Collapse expanded={opened}><Box className="disclosure-body">{children}</Box></Collapse>
    </Box>
  );
}

export function TechnicalResult({ result }: { result: OperationResult | null }) {
  if (!result) return null;
  return (
    <details className="technical-result">
      <summary>技术详情</summary>
      <pre>{JSON.stringify(result, null, 2)}</pre>
    </details>
  );
}

export function ErrorPanel({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <Surface className="error-panel">
      <Stack gap="sm">
        <Box>
          <Text fw={620} c="red.3">操作未完成</Text>
          <Text c="dimmed" fz="sm" mt={4}>{message}</Text>
        </Box>
        {onRetry && (
          <Button variant="default" size="xs" leftSection={<RotateCcw size={14} />} onClick={onRetry}>
            重试
          </Button>
        )}
      </Stack>
    </Surface>
  );
}

export function KeyHint({ children }: { children: ReactNode }) {
  return <Code className="key-hint">{children}</Code>;
}

export function IconButton({ label, children, onClick }: { label: string; children: ReactNode; onClick(): void }) {
  return <Tooltip label={label}><ActionIcon variant="subtle" color="gray" aria-label={label} onClick={onClick}>{children}</ActionIcon></Tooltip>;
}
