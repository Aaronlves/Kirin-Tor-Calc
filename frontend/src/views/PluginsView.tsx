import { useState } from "react";
import { Alert, Badge, Box, Button, Code, Group, SimpleGrid, Stack, Text, TextInput, Title } from "@mantine/core";
import { notifications } from "@mantine/notifications";
import { CircleAlert, Compass, Plug, RefreshCw, ShieldCheck, ShieldOff, Trash2 } from "lucide-react";

import { errorMessage } from "../api";
import { CommunityDiscoveryPanel } from "../components/CommunityDiscoveryPanel";
import type { WorkbenchController } from "../hooks/useWorkbench";
import type { InstalledPlugin } from "../types";
import { ToolSubview } from "../components/ui";

function statusColor(plugin: InstalledPlugin): string {
  if (plugin.status === "active") return "green";
  if (plugin.status === "disabled" || plugin.status === "safe-mode") return "gray";
  if (plugin.status === "unapproved") return "yellow";
  return "red";
}

function statusLabel(plugin: InstalledPlugin): string {
  return {
    active: "已启用",
    disabled: "已停用",
    "safe-mode": "安全模式停用",
    unapproved: "尚未批准",
    incompatible: "接口不兼容",
    invalid: "内容无效",
    "missing-lock": "缺少锁定快照",
  }[plugin.status] ?? plugin.status;
}

export function PluginsView({ controller }: { controller: WorkbenchController }) {
  const [alias, setAlias] = useState("");
  const [path, setPath] = useState("");
  const [running, setRunning] = useState<string | null>(null);
  const [discoverOpened, setDiscoverOpened] = useState(false);
  const summary = controller.pluginSummary;

  const act = async (action: string, payload: Record<string, unknown>, success: string) => {
    setRunning(`${action}:${String(payload.alias ?? "")}`);
    try {
      await controller.pluginAction(action, payload);
      notifications.show({ color: "green", message: success });
      if (action === "add_path") {
        setAlias("");
        setPath("");
      }
    } catch (caught) {
      notifications.show({ color: "red", title: "插件操作失败", message: errorMessage(caught), autoClose: false });
    } finally {
      setRunning(null);
    }
  };

  const contributions = summary.contributions;
  const counts = {
    renderers: contributions.renderers.length,
    views: contributions.views.length,
    tools: contributions.tools.length,
    commands: contributions.commands.length,
    profiles: contributions.profiles.length,
  };

  if (discoverOpened) {
    return <ToolSubview title="发现社区 Workbench Plugins" description="候选项目保持只读；安装和批准仍需返回插件管理后明确执行。" onBack={() => setDiscoverOpened(false)}>
      <CommunityDiscoveryPanel kind="plugin" />
    </ToolSubview>;
  }

  return (
    <Stack className="plugin-manager-tool" gap="lg" p="lg">
      <Group justify="space-between" align="flex-start">
        <Box>
          <Group gap="sm"><Plug size={20} /><Title order={3}>本地插件与激活贡献</Title></Group>
          <Text c="dimmed" fz="sm" mt={5}>安装经过内容摘要锁定的本地 UI 插件；插件在无同源权限的沙箱 iframe 中运行。</Text>
        </Box>
        <Button variant="default" size="xs" leftSection={<Compass size={14} />} onClick={() => setDiscoverOpened(true)}>发现社区插件</Button>
      </Group>

      {summary.safe_mode && <Alert color="orange" icon={<ShieldOff size={17} />} title="工作台处于安全模式">
        插件配置仍可检查和修改，但本次服务不会激活贡献或提供插件资源。退出后使用普通 <Code>kt web</Code> 重新启动。
      </Alert>}
      {summary.error && <Alert color="red" icon={<CircleAlert size={17} />} title="插件配置无法读取">
        {summary.error}。核心工作台仍可使用；请通过安全模式或 CLI 修复插件要求与锁文件。
      </Alert>}

      <Box className="plugin-manager-install">
        <Text component="h4" fw={650} fz="sm">安装本地插件快照</Text>
        <Text c="dimmed" fz="xs" mt={3}>此操作会读取并批准当前目录内容。以后源目录发生变化时，必须显式“接受更新”。</Text>
        <SimpleGrid cols={{ base: 1, md: 2 }} mt="md">
          <TextInput label="别名" placeholder="talents" value={alias} onChange={(event) => setAlias(event.currentTarget.value)} />
          <TextInput label="插件目录" placeholder="/absolute/path/to/plugin" value={path} onChange={(event) => setPath(event.currentTarget.value)} />
        </SimpleGrid>
        <Group justify="flex-end" mt="md">
          <Button
            leftSection={<ShieldCheck size={15} />}
            loading={running === `add_path:${alias}`}
            disabled={!/^[a-z][a-z0-9_]*$/.test(alias) || !path.trim() || summary.safe_mode}
            onClick={() => { void act("add_path", { alias, path }, `已安装并批准插件 ${alias}`); }}
          >安装并启用</Button>
        </Group>
      </Box>

      <Group justify="space-between">
        <Text component="h4" fw={650} fz="sm">已请求插件</Text>
        <Button
          variant="default"
          size="xs"
          leftSection={<RefreshCw size={13} />}
          loading={running === "verify:"}
          onClick={() => { void act("verify", {}, "插件锁与缓存验证通过"); }}
        >离线验证</Button>
      </Group>

      {summary.plugins.length ? <Stack gap="sm">
        {summary.plugins.map((plugin) => (
          <Box className="plugin-manager-card" key={plugin.alias}>
            <Group justify="space-between" align="flex-start" wrap="nowrap">
              <Box>
                <Group gap={7}>
                  <Text component="h5" fw={700}>{plugin.name || plugin.id || plugin.alias}</Text>
                  <Badge color={statusColor(plugin)} variant="light">{statusLabel(plugin)}</Badge>
                </Group>
                <Text c="dimmed" fz="xs" mt={4}>{plugin.id || "身份不可用"}@{plugin.version || plugin.requested_version} · 别名 {plugin.alias}</Text>
                {plugin.description && <Text fz="sm" mt="sm">{plugin.description}</Text>}
                {plugin.error && <Text c="red.3" fz="xs" mt="sm"><CircleAlert size={12} /> {plugin.error}</Text>}
                {plugin.compatibility && !plugin.compatibility.compatible && <Box mt="sm" aria-label="插件兼容性详情">
                  {plugin.compatibility.kirin_feature.status !== "satisfied" && <Text c="red.3" fz="xs">
                    需要 Kirin feature {plugin.compatibility.kirin_feature.required}，当前为 {plugin.compatibility.kirin_feature.current}。
                  </Text>}
                  {plugin.compatibility.interfaces.filter((item) => item.status !== "satisfied").map((item) => (
                    <Text c="red.3" fz="xs" key={`${item.id}@${item.revision}`}>
                      {item.id}@{item.revision}：{item.status}
                      {item.providers.length ? `；已安装 provider ${item.providers.map((provider) => `${String(provider.package)}@${String(provider.version)}`).join("、")}` : ""}
                    </Text>
                  ))}
                </Box>}
                <Code block mt="sm">{plugin.content_sha256 || "没有锁定内容摘要"}</Code>
              </Box>
              <Group gap={6} justify="flex-end">
                <Button
                  variant="default"
                  size="xs"
                  loading={running === `update_path:${plugin.alias}`}
                  disabled={summary.safe_mode}
                  onClick={() => { void act("update_path", { alias: plugin.alias }, `已接受 ${plugin.alias} 的新内容快照`); }}
                >接受更新</Button>
                <Button
                  variant="default"
                  size="xs"
                  loading={running === `${plugin.enabled ? "disable" : "enable"}:${plugin.alias}`}
                  disabled={summary.safe_mode && !plugin.enabled}
                  onClick={() => { void act(plugin.enabled ? "disable" : "enable", { alias: plugin.alias }, `${plugin.alias} 已${plugin.enabled ? "停用" : "启用"}`); }}
                >{plugin.enabled ? "停用" : "启用"}</Button>
                <Button
                  variant="subtle"
                  color="red"
                  size="xs"
                  leftSection={<Trash2 size={13} />}
                  loading={running === `remove:${plugin.alias}`}
                  onClick={() => { void act("remove", { alias: plugin.alias }, `已移除 ${plugin.alias}`); }}
                >移除</Button>
              </Group>
            </Group>
          </Box>
        ))}
      </Stack> : <Text c="dimmed" fz="sm">尚未安装 Workbench Plugin。</Text>}

      <Box>
        <Text component="h4" fw={650} fz="sm">当前激活贡献</Text>
        <Group gap={6} mt="sm">
          <Badge variant="outline">{counts.renderers} 个呈现器</Badge>
          <Badge variant="outline">{counts.views} 个页面</Badge>
          <Badge variant="outline">{counts.tools} 个工具</Badge>
          <Badge variant="outline">{counts.commands} 个命令</Badge>
          <Badge variant="outline">{counts.profiles} 个 Profile</Badge>
        </Group>
      </Box>
    </Stack>
  );
}
