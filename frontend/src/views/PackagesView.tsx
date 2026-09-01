import { useState } from "react";
import {
  ActionIcon,
  Badge,
  Box,
  Button,
  Code,
  Divider,
  Drawer,
  Group,
  Modal,
  ScrollArea,
  SimpleGrid,
  Stack,
  Tabs,
  Text,
  TextInput,
  Title,
} from "@mantine/core";
import { notifications } from "@mantine/notifications";
import {
  ArchiveRestore,
  Box as PackageIcon,
  Check,
  Download,
  FolderInput,
  PackageCheck,
  Plus,
  RefreshCw,
  ShieldCheck,
  Trash2,
  Wrench,
} from "lucide-react";

import { errorMessage, request } from "../api";
import type { WorkbenchController } from "../hooks/useWorkbench";
import type { InstalledPackage, OperationResult } from "../types";
import { EmptyState, Surface, TechnicalResult } from "../components/ui";

type InstallMode = "github" | "local";

export function PackagesView({ controller }: { controller: WorkbenchController }) {
  const [installOpened, setInstallOpened] = useState(false);
  const [installMode, setInstallMode] = useState<InstallMode>("github");
  const [alias, setAlias] = useState("");
  const [source, setSource] = useState("");
  const [version, setVersion] = useState("");
  const [path, setPath] = useState("");
  const [working, setWorking] = useState(false);
  const [result, setResult] = useState<OperationResult | null>(null);
  const [updatePackage, setUpdatePackage] = useState<InstalledPackage | null>(null);
  const [updateVersion, setUpdateVersion] = useState("");
  const [removePackage, setRemovePackage] = useState<InstalledPackage | null>(null);
  const [authorToolsOpened, setAuthorToolsOpened] = useState(false);
  const [authorTab, setAuthorTab] = useState<string | null>("new-package");
  const [packageDirectory, setPackageDirectory] = useState("");
  const [packageName, setPackageName] = useState("");
  const [packageNamespace, setPackageNamespace] = useState("");
  const [packageVersion, setPackageVersion] = useState("1.0.0");
  const [checkDirectory, setCheckDirectory] = useState("");
  const [workspacePath, setWorkspacePath] = useState("");

  const packages = controller.bootstrapData?.packages ?? [];

  const act = async (action: string, payload: Record<string, unknown> = {}, success?: string) => {
    setWorking(true);
    try {
      const response = await controller.packageAction(action, payload);
      setResult(response);
      if (success) notifications.show({ color: "green", title: success, message: "依赖锁定与缓存状态已经刷新。" });
      return response;
    } catch (error) {
      notifications.show({ color: "red", title: "Package 操作失败", message: errorMessage(error), autoClose: false });
      return null;
    } finally {
      setWorking(false);
    }
  };

  const install = async () => {
    const response = installMode === "github"
      ? await act("add", { alias, source, version }, "Package 已安装")
      : await act("add_path", { alias, path }, "本地快照已添加");
    if (response) {
      setInstallOpened(false);
      setAlias("");
      setSource("");
      setVersion("");
      setPath("");
    }
  };

  const update = async () => {
    if (!updatePackage?.alias) return;
    const response = await act("update", { alias: updatePackage.alias, version: updateVersion || null }, "Package 已更新");
    if (response) {
      setUpdatePackage(null);
      setUpdateVersion("");
    }
  };

  const remove = async () => {
    if (!removePackage?.alias) return;
    const response = await act("remove", { alias: removePackage.alias }, "Package 已移除");
    if (response) setRemovePackage(null);
  };

  const initializeWorkspace = async () => {
    setWorking(true);
    try {
      const response = await request<OperationResult>("/api/workspace/init", { path: workspacePath });
      setResult(response);
      notifications.show({ color: "green", title: "工作区已初始化", message: String(response.path || workspacePath) });
    } catch (error) {
      notifications.show({ color: "red", title: "无法初始化工作区", message: errorMessage(error) });
    } finally {
      setWorking(false);
    }
  };

  return (
    <div className="content-page packages-page">
      <div className="page-intro compact">
        <Box>
          <Text className="page-kicker">PACKAGE ECOSYSTEM</Text>
          <Title order={1}>可复现的社区预设</Title>
          <Text c="dimmed" fz="sm" mt={5}>每个 Package 都以精确版本和内容哈希锁定；模板只在创建文档时展开。</Text>
        </Box>
        <Group gap="xs">
          <Button variant="default" size="xs" leftSection={<Wrench size={14} />} onClick={() => setAuthorToolsOpened(true)}>作者工具</Button>
          <Button size="xs" leftSection={<Plus size={14} />} onClick={() => setInstallOpened(true)}>安装 Package</Button>
        </Group>
      </div>

      <ScrollArea h="calc(100vh - 158px)" type="auto">
        <Stack gap="lg" pb="xl">
          <Surface className="package-toolbar-surface">
            <Group justify="space-between" wrap="nowrap">
              <Box><Text fw={650} fz="sm">依赖健康</Text><Text c="dimmed" fz="xs" mt={3}>{packages.length ? `${packages.filter((item) => item.direct).length} 个直接依赖，${packages.filter((item) => !item.direct).length} 个传递依赖` : "当前工作区没有社区依赖"}</Text></Box>
              <Group gap="xs">
                <Button variant="default" size="xs" leftSection={<ArchiveRestore size={14} />} loading={working} onClick={() => { void act("restore", {}, "Package 缓存已恢复"); }}>恢复缓存</Button>
                <Button variant="default" size="xs" leftSection={<ShieldCheck size={14} />} loading={working} onClick={() => { void act("verify", {}, "离线验证通过"); }}>离线验证</Button>
                <Button variant="subtle" color="gray" size="xs" leftSection={<RefreshCw size={14} />} onClick={() => { void controller.refresh(true); }}>刷新</Button>
              </Group>
            </Group>
          </Surface>

          {packages.length ? (
            <div className="package-card-grid">
              {packages.map((item) => (
                <Surface className="package-card-modern" key={`${item.source}-${item.content_sha256}`}>
                  <Stack gap="md" h="100%">
                    <Group justify="space-between" align="flex-start" wrap="nowrap">
                      <div className="package-icon"><PackageIcon size={19} strokeWidth={1.6} /></div>
                      <Badge size="xs" variant="light" color={item.direct ? "orange" : "gray"}>{item.direct ? item.alias : "传递依赖"}</Badge>
                    </Group>
                    <Box>
                      <Group gap={6} wrap="nowrap"><Text fw={680} fz="sm" truncate>{item.name}</Text><Code>{item.version}</Code></Group>
                      <Text c="dimmed" fz="xs" mt={7} lineClamp={3}>{item.description || "这个 Package 没有提供说明。"}</Text>
                    </Box>
                    <Stack gap={5} className="package-facts">
                      <span><small>namespace</small><Code>{item.namespace}</Code></span>
                      <span><small>resolved</small><Text fz="xs" truncate>{item.resolved}</Text></span>
                      <span><small>content</small><Code>{item.content_sha256.slice(0, 12)}…</Code></span>
                    </Stack>
                    <Group mt="auto" gap="xs">
                      {item.direct ? (
                        <>
                          <Button variant="default" size="xs" flex={1} leftSection={<Download size={14} />} onClick={() => { setUpdatePackage(item); setUpdateVersion(""); }}>更新</Button>
                          <ActionIcon className="danger-action" variant="subtle" onClick={() => setRemovePackage(item)} aria-label={`移除 ${item.alias}`}><Trash2 size={14} /></ActionIcon>
                        </>
                      ) : <Text c="dimmed" fz="xs">由直接依赖自动引入</Text>}
                    </Group>
                  </Stack>
                </Surface>
              ))}
            </div>
          ) : (
            <Surface><EmptyState icon={<PackageCheck size={24} />} title="尚未安装社区 Package" description="可以从 GitHub 安装精确版本，也可以将本地 Package 目录冻结为不可变快照。" action={<Button size="xs" leftSection={<Plus size={14} />} onClick={() => setInstallOpened(true)}>安装第一个 Package</Button>} /></Surface>
          )}

          {result && <Surface className="package-result-surface"><Group mb="md" gap="xs"><Check size={16} color="var(--kt-success)" /><Text fw={650} fz="sm">最近一次 Package 操作已完成</Text></Group><TechnicalResult result={result} /></Surface>}
        </Stack>
      </ScrollArea>

      <Modal opened={installOpened} onClose={() => setInstallOpened(false)} title="安装 Package" centered size="lg">
        <Stack gap="lg">
          <Tabs value={installMode} onChange={(value) => setInstallMode(value as InstallMode)}>
            <Tabs.List grow><Tabs.Tab value="github" leftSection={<Download size={14} />}>GitHub 精确版本</Tabs.Tab><Tabs.Tab value="local" leftSection={<FolderInput size={14} />}>本地不可变快照</Tabs.Tab></Tabs.List>
          </Tabs>
          <TextInput label="工作区别名" description="在当前工作区内引用这个 Package 的稳定名称。" placeholder="example" value={alias} onChange={(event) => setAlias(event.currentTarget.value)} />
          {installMode === "github" ? (
            <>
              <TextInput label="来源" placeholder="github:OWNER/REPOSITORY" value={source} onChange={(event) => setSource(event.currentTarget.value)} />
              <TextInput label="精确版本" description="必须指定可解析的精确版本。" placeholder="1.0.0" value={version} onChange={(event) => setVersion(event.currentTarget.value)} />
            </>
          ) : (
            <TextInput label="Package 目录" description="目录内容会复制到内容寻址缓存，而不是保持活动链接。" placeholder="/path/to/package" value={path} onChange={(event) => setPath(event.currentTarget.value)} />
          )}
          <Divider />
          <Group justify="flex-end"><Button variant="default" onClick={() => setInstallOpened(false)}>取消</Button><Button loading={working} disabled={!alias || installMode === "github" ? !alias || !source || !version : !alias || !path} onClick={() => { void install(); }}>安装并锁定</Button></Group>
        </Stack>
      </Modal>

      <Modal opened={Boolean(updatePackage)} onClose={() => setUpdatePackage(null)} title={`更新 ${updatePackage?.alias || "Package"}`} centered>
        <Stack>
          <Text c="dimmed" fz="xs">留空版本会重新解析当前约束；填写版本则更新到新的精确版本。</Text>
          <TextInput label="精确版本" placeholder={updatePackage?.version || "1.0.0"} value={updateVersion} onChange={(event) => setUpdateVersion(event.currentTarget.value)} />
          <Group justify="flex-end"><Button variant="default" onClick={() => setUpdatePackage(null)}>取消</Button><Button loading={working} onClick={() => { void update(); }}>更新并重新锁定</Button></Group>
        </Stack>
      </Modal>

      <Modal opened={Boolean(removePackage)} onClose={() => setRemovePackage(null)} title="移除直接依赖" centered>
        <Stack>
          <Text fz="sm">移除 <strong>{removePackage?.alias}</strong>？</Text>
          <Text c="dimmed" fz="xs">不再可达的传递依赖也会从锁文件中移除；内容缓存仍可由其他工作区复用。</Text>
          <Group justify="flex-end"><Button variant="default" onClick={() => setRemovePackage(null)}>取消</Button><Button className="danger-button" leftSection={<Trash2 size={14} />} loading={working} onClick={() => { void remove(); }}>移除依赖</Button></Group>
        </Stack>
      </Modal>

      <Drawer opened={authorToolsOpened} onClose={() => setAuthorToolsOpened(false)} position="right" size="lg" title="Package 与工作区作者工具">
        <Tabs value={authorTab} onChange={setAuthorTab} orientation="vertical" className="author-tools-tabs">
          <Tabs.List>
            <Tabs.Tab value="new-package">新建 Package</Tabs.Tab>
            <Tabs.Tab value="check-package">检查 Package</Tabs.Tab>
            <Tabs.Tab value="new-workspace">初始化工作区</Tabs.Tab>
          </Tabs.List>
          <Tabs.Panel value="new-package" pl="lg">
            <Stack>
              <Box><Text fw={650}>创建 Package 骨架</Text><Text c="dimmed" fz="xs" mt={3}>生成 manifest、entries 和消费者模板示例。</Text></Box>
              <TextInput label="目录" value={packageDirectory} onChange={(event) => setPackageDirectory(event.currentTarget.value)} />
              <TextInput label="名称" placeholder="community.example" value={packageName} onChange={(event) => setPackageName(event.currentTarget.value)} />
              <TextInput label="namespace" placeholder="community_example" value={packageNamespace} onChange={(event) => setPackageNamespace(event.currentTarget.value)} />
              <TextInput label="版本" value={packageVersion} onChange={(event) => setPackageVersion(event.currentTarget.value)} />
              <Button loading={working} disabled={!packageDirectory || !packageName || !packageNamespace || !packageVersion} onClick={() => { void act("new", { directory: packageDirectory, name: packageName, namespace: packageNamespace, version: packageVersion }, "Package 骨架已创建"); }}>创建 Package</Button>
            </Stack>
          </Tabs.Panel>
          <Tabs.Panel value="check-package" pl="lg">
            <Stack>
              <Box><Text fw={650}>完整检查 Package</Text><Text c="dimmed" fz="xs" mt={3}>验证 manifest、源码、依赖和模板。</Text></Box>
              <TextInput label="Package 目录" value={checkDirectory} onChange={(event) => setCheckDirectory(event.currentTarget.value)} />
              <Button loading={working} disabled={!checkDirectory} onClick={() => { void act("check", { directory: checkDirectory }, "Package 检查完成"); }}>开始检查</Button>
            </Stack>
          </Tabs.Panel>
          <Tabs.Panel value="new-workspace" pl="lg">
            <Stack>
              <Box><Text fw={650}>初始化新工作区</Text><Text c="dimmed" fz="xs" mt={3}>在指定目录创建 Kirin 工作区结构。</Text></Box>
              <TextInput label="目标目录" value={workspacePath} onChange={(event) => setWorkspacePath(event.currentTarget.value)} />
              <Button loading={working} disabled={!workspacePath} onClick={() => { void initializeWorkspace(); }}>初始化工作区</Button>
            </Stack>
          </Tabs.Panel>
        </Tabs>
      </Drawer>
    </div>
  );
}
