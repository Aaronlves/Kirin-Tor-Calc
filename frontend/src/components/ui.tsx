import type { ReactNode } from "react";
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
} from "@mantine/core";
import { ChevronDown, ChevronRight, FileQuestion, RotateCcw } from "lucide-react";

import type { OperationResult } from "../types";

export function Surface({ children, className = "" }: { children: ReactNode; className?: string }) {
  return <Paper className={`surface ${className}`.trim()}>{children}</Paper>;
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
}: {
  title: string;
  description: string;
  action?: ReactNode;
  icon?: ReactNode;
}) {
  return (
    <Center className="empty-state">
      <Stack align="center" gap="xs">
        <div className="empty-state-icon">{icon}</div>
        <Text fw={620} fz="sm">{title}</Text>
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
        {opened ? <ChevronDown size={15} /> : <ChevronRight size={15} />}
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
  return <ActionIcon variant="subtle" color="gray" aria-label={label} title={label} onClick={onClick}>{children}</ActionIcon>;
}
