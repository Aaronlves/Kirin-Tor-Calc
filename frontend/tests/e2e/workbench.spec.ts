import { expect, test, type Page } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";
import { access, mkdir, readFile, rename, rm, writeFile } from "node:fs/promises";
import { resolve } from "node:path";

const sessionUrl = "/?token=kirin-e2e-token";
const comboButtonName = /^双技能组合（虚构） entries\/组合模型\.kirin/;
const rotationButtonName = /^过程周期证明（虚构） entries\/循环分析\.kirin/;
const modKey = process.platform === "darwin" ? "Meta" : "Control";

async function openWorkbench(page: Page) {
  await page.goto(sessionUrl);
  await expect(page.getByRole("button", { name: comboButtonName })).toBeVisible();
}

async function openCombo(page: Page) {
  await page.getByRole("button", { name: comboButtonName }).click();
  await expect(page.getByRole("textbox", { name: "Kirin Tor 源码：双技能组合（虚构）" })).toBeVisible();
}

test.describe.serial("Kirin Tor 浏览器工作台交互", () => {
  test.afterEach(async ({ request }) => {
    await request.post("/api/recovery", {
      headers: { "X-Kirin-Token": "kirin-e2e-token" },
      data: { drafts: {} },
    });
  });

  test("沙箱插件注册文档呈现器、页面、工具、命令与 Profile", async ({ page, request }) => {
    const enabled = await request.post("/api/plugin", {
      headers: { "X-Kirin-Token": "kirin-e2e-token" },
      data: { action: "enable", payload: { alias: "talents" } },
    });
    expect(enabled.ok()).toBeTruthy();
    await openWorkbench(page);
    await openCombo(page);

    const talentFrame = page.frameLocator('iframe[title^="天赋树"]');
    await expect(talentFrame.getByRole("heading", { name: /天赋页/ })).toBeVisible();
    await expect(talentFrame.getByRole("region", { name: "虚构天赋节点" })).toBeVisible();
    await talentFrame.getByRole("button", { name: /暴击率/ }).click();
    await expect(page.locator(".cm-activeLine")).toContainText('crit "暴击率"');
    await talentFrame.getByRole("button", { name: "计算 combo.total" }).click();
    await expect(talentFrame.getByText(/验证后结果：2,420/)).toBeVisible();

    await page.locator(".plugin-document-switch .mantine-SegmentedControl-label").filter({ hasText: "通用" }).click();
    await expect(page.getByText("文档投影", { exact: true })).toBeVisible();

    await page.getByRole("button", { name: "Build 大厅", exact: true }).click();
    const buildsFrame = page.frameLocator('iframe[title^="Build 大厅"]');
    await expect(buildsFrame.getByRole("heading", { name: "虚构 Build 大厅" })).toBeVisible();
    await expect(buildsFrame.getByText("双技能组合（虚构）", { exact: true })).toBeVisible();

    await page.getByRole("button", { name: /命令/ }).click();
    await page.getByPlaceholder("搜索页面或命令…").fill("切换到天赋创作");
    await page.getByText("切换到天赋创作 Profile", { exact: true }).click();
    await expect(page.getByRole("button", { name: "关系图" })).toHaveCount(0);
    await expect(page.getByRole("button", { name: "Build 大厅", exact: true })).toBeVisible();

    await page.getByRole("button", { name: "设置", exact: true }).click();
    await page.getByText("Kirin Tor 默认", { exact: true }).click();
    await expect(page.getByRole("button", { name: "关系图" })).toBeVisible();

    await page.getByRole("button", { name: /命令/ }).click();
    await page.getByPlaceholder("搜索页面或命令…").fill("检查虚构天赋插件");
    await page.getByText("检查虚构天赋插件", { exact: true }).click();
    const auditFrame = page.frameLocator('iframe[title^="天赋插件信息"]');
    await expect(auditFrame.getByRole("heading", { name: "天赋插件信息" })).toBeVisible();

    const disabled = await request.post("/api/plugin", {
      headers: { "X-Kirin-Token": "kirin-e2e-token" },
      data: { action: "disable", payload: { alias: "talents" } },
    });
    expect(disabled.ok()).toBeTruthy();
  });

  test("topic 发现只展示兼容 manifest 与仓库链接", async ({ page }) => {
    const discovery = (kind: "plugin" | "package") => ({
      status: "ok",
      kind,
      topic: kind === "plugin" ? "kirin-tor-plugin" : "kirin-tor-package",
      query: "",
      page: 1,
      per_page: 12,
      total_repositories: 1,
      inspected_repositories: 1,
      skipped_repositories: 0,
      has_previous: false,
      has_next: false,
      checked_at: "2026-09-02T00:00:00Z",
      notice: "Topic 与兼容 manifest 仅用于发现；结果未经审核，也不会安装、批准或启用内容。",
      items: [{
        kind,
        topic: kind === "plugin" ? "kirin-tor-plugin" : "kirin-tor-package",
        repository: `community/${kind}-example`,
        source: `github:community/${kind}-example`,
        repository_url: `https://github.com/community/${kind}-example`,
        repository_description: "Fixture repository",
        default_branch: "main",
        manifest_sha: "a".repeat(40),
        updated_at: "2026-09-01T00:00:00Z",
        stars: 3,
        forks: 1,
        name: kind === "plugin" ? "Community Browser" : "community.example",
        version: "1.0.0",
        description: "A read-only discovery fixture.",
        license: "MIT",
        ...(kind === "plugin"
          ? { id: "community.example-browser", api: "1" }
          : { namespace: "community_example", requires_kirin: "0.3" }),
      }],
    });
    for (const kind of ["plugin", "package"] as const) {
      await page.route(`**/api/${kind}`, async (route) => {
        const request = route.request();
        const body = request.method() === "POST" ? request.postDataJSON() : null;
        if (body?.action === "discover") {
          await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(discovery(kind)) });
        } else {
          await route.continue();
        }
      });
    }

    await openWorkbench(page);
    await page.getByRole("button", { name: /命令/ }).click();
    await page.getByPlaceholder("搜索页面或命令…").fill("Workbench Plugins");
    await page.getByText("打开 Workbench Plugins", { exact: true }).click();
    await page.getByRole("button", { name: "发现社区插件" }).click();
    let drawer = page.getByRole("dialog", { name: "发现社区 Workbench Plugins" });
    await expect(drawer.getByText("Community Browser", { exact: true })).toBeVisible();
    await expect(drawer.getByText("kirin-tor-plugin", { exact: true })).toBeVisible();
    await expect(drawer.getByText("未审核", { exact: true })).toBeVisible();
    await expect(drawer.getByRole("link", { name: "在 GitHub 查看" })).toHaveAttribute("href", "https://github.com/community/plugin-example");
    await expect(drawer.getByRole("button", { name: /安装/ })).toHaveCount(0);
    await drawer.locator(".mantine-Drawer-close").click();
    await expect(drawer).toBeHidden();
    const pluginManager = page.getByRole("dialog", { name: "Workbench Plugins" });
    await pluginManager.locator(".mantine-Drawer-close").click();
    await expect(pluginManager).toBeHidden();

    await page.getByRole("button", { name: /命令/ }).click();
    await page.getByPlaceholder("搜索页面或命令…").fill("Package 管理");
    await page.getByText("打开 Package 管理", { exact: true }).click();
    await page.getByRole("button", { name: "发现 Package" }).click();
    drawer = page.getByRole("dialog", { name: "发现社区 Packages" });
    await expect(drawer.getByText("community.example", { exact: true })).toBeVisible();
    await expect(drawer.getByText("kirin-tor-package", { exact: true })).toBeVisible();
    await expect(drawer.getByText("namespace community_example", { exact: true })).toBeVisible();
    await expect(drawer.getByRole("link", { name: "在 GitHub 查看" })).toHaveAttribute("href", "https://github.com/community/package-example");
  });

  test("三种文档专注模式切换并记住选择", async ({ page }) => {
    await page.setViewportSize({ width: 1120, height: 800 });
    await openWorkbench(page);
    await expect(page.getByRole("button", { name: "展开导航" })).toBeVisible();
    await expect(page.locator(".workbench-navbar .mantine-NavLink-label")).toHaveText(["文档", "关系图", "语法参考"]);
    await expect(page.locator('[aria-label^="工作区状态："]')).toBeVisible();
    await expect(page.getByRole("button", { name: "展开检查器" })).toBeVisible();
    await openCombo(page);
    const splitEditorWidth = (await page.getByRole("region", { name: "源码编辑器" }).boundingBox())?.width || 0;
    await page.getByRole("button", { name: "收起检查器" }).click();
    await expect(page.getByRole("button", { name: "展开检查器" })).toBeVisible();
    expect((await page.getByRole("region", { name: "源码编辑器" }).boundingBox())?.width).toBeGreaterThan(splitEditorWidth + 200);
    await page.getByRole("button", { name: "展开检查器" }).click();
    await expect(page.getByRole("tab", { name: "预览", exact: true })).toBeVisible();
    const focusModes = page.getByRole("radiogroup", { name: "文档专注模式" });
    await expect(focusModes.getByRole("radio", { name: "分栏" })).toBeChecked();
    const focusChoice = (label: string) => page.locator(".document-focus-switch .mantine-SegmentedControl-label").filter({ hasText: label });

    const editorPanel = page.getByRole("region", { name: "源码编辑器" });
    await focusChoice("仅编辑").click();
    await expect(page.getByRole("region", { name: "文档索引" })).toHaveCount(0);
    await expect(page.getByRole("complementary", { name: "文档检查器" })).toHaveCount(0);
    expect((await editorPanel.boundingBox())?.width).toBeGreaterThan(950);

    await focusChoice("仅预览").click();
    await expect(editorPanel).toBeHidden();
    const inspector = page.getByRole("complementary", { name: "文档检查器" });
    await expect(inspector).toBeVisible();
    expect((await inspector.boundingBox())?.width).toBeGreaterThan(950);

    await page.reload();
    await expect(page.getByRole("radio", { name: "仅预览" })).toBeChecked();
    await expect(page.getByRole("complementary", { name: "文档检查器" })).toBeVisible();

    await page.getByRole("button", { name: /命令/ }).click();
    await page.getByText("文档：分栏", { exact: true }).click();
    await expect(page.getByRole("radio", { name: "分栏" })).toBeChecked();
    await expect(page.getByRole("region", { name: "文档索引" })).toBeVisible();
  });

  test("语法参考可搜索、复制示例并从命令面板打开", async ({ page }) => {
    await openWorkbench(page);
    await page.getByLabel("语法参考", { exact: true }).click();

    let reference = page.getByRole("dialog", { name: "Kirin Tor 语法参考" });
    await expect(reference).toBeVisible();
    await expect(reference.getByText("11 个匹配主题", { exact: true })).toBeVisible();
    await reference.getByRole("textbox", { name: "搜索语法参考" }).fill("Agent");
    await expect(reference.getByText("1 个匹配主题", { exact: true })).toBeVisible();
    await expect(reference.getByRole("heading", { name: "Agent 与外部编辑器" })).toBeVisible();
    await expect(reference).toContainText("不显示 Agent 提示词、活动记录、终端或文件操作过程");
    await reference.getByRole("textbox", { name: "搜索语法参考" }).fill("minimum_where");
    await expect(reference.getByText("1 个匹配主题", { exact: true })).toBeVisible();
    await expect(reference.getByRole("heading", { name: "有界 Process、场景与策略分析" })).toBeVisible();
    await expect(reference).toContainText("last_before");
    await reference.getByRole("textbox", { name: "搜索语法参考" }).fill("有限分布");
    await expect(reference.getByText("1 个匹配主题", { exact: true })).toBeVisible();
    await expect(reference.getByRole("heading", { name: "有限离散分布" })).toBeVisible();
    await expect(reference.getByText("distribution proc", { exact: false })).toBeVisible();

    const copy = reference.getByRole("button", { name: "复制示例：有限离散分布" });
    await copy.click();
    await expect(copy).toContainText("已复制");

    await reference.locator(".mantine-Drawer-close").click();
    await page.getByRole("button", { name: /命令/ }).click();
    await page.getByPlaceholder("搜索页面或命令…").fill("Agent 协作");
    await page.getByText("查看 Agent 与外部编辑器协作", { exact: true }).click();
    reference = page.getByRole("dialog", { name: "Kirin Tor 语法参考" });
    await expect(reference).toBeVisible();
    await expect(reference.getByRole("heading", { name: "Agent 与外部编辑器" })).toBeVisible();
  });

  test("主工作台与语法抽屉通过自动无障碍检查", async ({ page }) => {
    await openWorkbench(page);
    await openCombo(page);
    let results = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa"]).analyze();
    expect(results.violations).toEqual([]);

    await page.getByLabel("语法参考", { exact: true }).click();
    const reference = page.getByRole("dialog", { name: "Kirin Tor 语法参考" });
    await expect(reference).toBeVisible();
    await expect(page.locator(".syntax-example pre > code")).toHaveAttribute("tabindex", "0");
    await page.waitForTimeout(350);
    results = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa"]).analyze();
    expect(results.violations).toEqual([]);

    await reference.getByRole("button", { name: "关闭工作区工具" }).click();
    await page.getByRole("button", { name: "新建文档" }).click();
    const createDialog = page.getByRole("dialog", { name: "新建文档" });
    await expect(createDialog.getByRole("button", { name: "关闭对话框" })).toBeVisible();
    await page.waitForTimeout(350);
    results = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa"]).analyze();
    expect(results.violations).toEqual([]);
  });

  test("刷新后恢复当前页面与工作区文档", async ({ page }) => {
    await openWorkbench(page);
    await openCombo(page);
    await page.getByLabel("关系图", { exact: true }).click();
    await expect(page.getByRole("heading", { name: "关系图" })).toBeVisible();

    await page.reload();
    await expect(page.getByRole("heading", { name: "关系图" })).toBeVisible();
    await page.getByLabel("文档", { exact: true }).click();
    await expect(page.getByRole("textbox", { name: "Kirin Tor 源码：双技能组合（虚构）" })).toBeVisible();
  });

  test("通知自动收起，Windows 快捷键与真实文件改名入口可用", async ({ page }) => {
    await openWorkbench(page);

    await page.keyboard.press("Control+k");
    await expect(page.getByPlaceholder("搜索页面或命令…")).toBeVisible();
    await page.keyboard.press("Escape");

    const documentButton = page.getByRole("button", { name: comboButtonName });
    await documentButton.focus();
    await page.keyboard.press("F2");
    const moveDialog = page.getByRole("dialog", { name: "重命名或移动真实文件" });
    const pathInput = moveDialog.getByRole("textbox", { name: "新的真实文件路径" });
    await expect(pathInput).toHaveValue("entries/组合模型.kirin");
    await expect(moveDialog.getByRole("button", { name: "应用文件路径" })).toBeDisabled();
    await pathInput.fill("entries/renamed-combo.kirin");
    await moveDialog.getByRole("button", { name: "应用文件路径" }).click();
    await expect(access(resolve(".e2e-workspace", "entries", "renamed-combo.kirin"))).resolves.toBeUndefined();

    const renamedButton = page.getByRole("button", { name: /^双技能组合（虚构） entries\/renamed-combo\.kirin/ });
    await renamedButton.focus();
    await page.keyboard.press("F2");
    await moveDialog.getByRole("textbox", { name: "新的真实文件路径" }).fill("entries/组合模型.kirin");
    await moveDialog.getByRole("button", { name: "应用文件路径" }).click();
    await expect(documentButton).toBeVisible();

    await page.getByRole("button", { name: "设置", exact: true }).click();
    await expect(page.getByText("Package 管理", { exact: true })).toBeVisible();
    await expect(page.getByText("Workbench Plugins", { exact: true })).toBeVisible();
    await page.keyboard.press("Escape");
    await page.getByRole("button", { name: "工作区工具", exact: true }).click();
    await expect(page.getByText("全文搜索与替换", { exact: true })).toBeVisible();
    await expect(page.getByText("保存前变更审查", { exact: true })).toBeVisible();
    await page.keyboard.press("Escape");

    await page.mouse.move(180, 700);
    await page.keyboard.press("Control+s");
    await expect(page.getByText("没有需要保存的草稿。", { exact: true })).toBeVisible();
    await expect(page.getByText("没有需要保存的草稿。", { exact: true })).toBeHidden({ timeout: 6000 });
  });

  test("核心工作台布局保持视觉基线", async ({ page, browserName }) => {
    test.skip(browserName === "firefox", "Firefox 由完整功能套件覆盖；像素基线保留 Chromium 与 WebKit 两种渲染路径。");
    await openWorkbench(page);
    await openCombo(page);
    await expect(page.locator('[aria-label="工作区状态：工作区有效"]')).toBeVisible();
    await expect(page.locator(".document-result-preview")).toContainText("2,420");
    await expect(page.locator(".workbench-shell")).toHaveScreenshot("workbench-shell.png", {
      animations: "disabled",
      maxDiffPixelRatio: 0.08,
      stylePath: resolve("tests/e2e/screenshot.css"),
    });
  });

  test("工作区搜索生成可审查草稿，相关语法可从诊断直达", async ({ page }) => {
    await openWorkbench(page);
    await page.getByRole("button", { name: "工作区工具" }).click();
    await page.getByText("全文搜索与替换", { exact: true }).click();
    const searchDrawer = page.getByRole("dialog", { name: "工作区搜索与替换" });
    await searchDrawer.getByRole("textbox", { name: "工作区查找" }).fill("组合期望伤害");
    await searchDrawer.getByRole("button", { name: "搜索", exact: true }).click();
    await expect(searchDrawer.getByRole("list", { name: "工作区搜索结果" }).getByRole("listitem").first()).toBeVisible();
    await searchDrawer.getByRole("textbox", { name: "工作区替换文本" }).fill("伤害合计");
    await searchDrawer.getByRole("button", { name: "替换全部可写匹配" }).click();
    const review = page.getByRole("dialog", { name: "保存前变更审查" });
    await expect(review.getByText("当前草稿", { exact: true })).toBeVisible();
    await expect(review).toContainText("伤害合计");
    await review.locator(".mantine-Drawer-close").click();

    await openCombo(page);
    const editor = page.getByRole("textbox", { name: "Kirin Tor 源码：双技能组合（虚构）" });
    await page.locator(".cm-line").last().click();
    await editor.press("End");
    await editor.type("unknown：");
    await page.getByRole("tab", { name: /诊断 1/ }).click();
    await page.getByRole("button", { name: "查看相关语法" }).click();
    await expect(page.getByRole("dialog", { name: "Kirin Tor 语法参考" }).getByRole("heading", { name: "文档、注释与说明" })).toBeVisible();
  });

  test("文档复制明确生成未保存源码草稿", async ({ page }) => {
    await openWorkbench(page);
    await openCombo(page);
    await page.getByRole("button", { name: "文档操作" }).click();
    await page.getByText("复制为新文档草稿", { exact: true }).click();
    const duplicate = page.getByRole("dialog", { name: "复制为新文档" });
    await duplicate.getByRole("textbox", { name: "新文档 ID" }).fill("combo_copy");
    await duplicate.getByRole("button", { name: "创建复制草稿" }).click();
    await expect(page.getByRole("textbox", { name: "Kirin Tor 源码：combo_copy" })).toContainText("@entry combo_copy");
    await expect(page.getByRole("textbox", { name: "Kirin Tor 源码：combo_copy" })).toContainText("combo_copy.total");
    await expect(page.getByText("已修改", { exact: true })).toBeVisible();
  });

  test("文档切换与新建文档 Enter 使用同一校验", async ({ page }) => {
    await openWorkbench(page);
    await page.getByRole("button", { name: "技能 A（虚构） entries/技能甲.kirin", exact: true }).click();
    await expect(page.getByRole("textbox", { name: "Kirin Tor 源码：技能 A（虚构）" })).toContainText("@entry skill_a");
    await openCombo(page);

    await page.getByRole("button", { name: "新建文档" }).click();
    const createDialog = page.getByRole("dialog", { name: "新建文档" });
    await createDialog.getByRole("textbox", { name: "文档 ID" }).fill("bad-id");
    await createDialog.getByRole("textbox", { name: "文档 ID" }).press("Enter");
    await expect(createDialog).toBeVisible();
    await expect(createDialog.getByText("文档 ID 格式无效")).toBeVisible();
    await createDialog.getByRole("button", { name: "取消" }).click();
  });

  test("关系图提供可用键盘选择的节点列表", async ({ page }) => {
    await openWorkbench(page);
    await page.getByLabel("关系图", { exact: true }).click();
    const inspector = page.locator(".graph-inspector");
    await expect(inspector).toContainText("直接依赖");
    const fallback = page.locator(".graph-surface .canvas-data-fallback");
    await fallback.locator("summary").click();
    await fallback.getByRole("button").filter({ hasText: "双技能组合（虚构）" }).click();
    await expect(inspector.locator(".graph-neighbor-list").first()).toContainText("技能 A（虚构）");
    await expect(inspector.locator(".graph-neighbor-list").first()).toContainText("技能 B（虚构）");
    const firstNode = fallback.locator(".relationship-node-list button").first();
    await firstNode.focus();
    await page.keyboard.press("Enter");
    await expect(page.locator(".graph-inspector")).toContainText("所属文档");
  });

  test("补全片段替换前缀并把光标放进参数", async ({ page }) => {
    await openWorkbench(page);
    await openCombo(page);
    const editor = page.getByRole("textbox", { name: "Kirin Tor 源码：双技能组合（虚构）" });
    await page.locator(".cm-line").last().click();
    await editor.press("End");
    await editor.type("  平方根");
    await editor.press("Control+Space");
    const sqrtCompletion = page.getByRole("option", { name: "平方根内置函数 · sqrt", exact: true });
    await expect(sqrtCompletion).toBeVisible();
    await sqrtCompletion.click();
    await editor.type("1");
    await expect(page.locator(".cm-line").filter({ hasText: "sqrt(1)" }).first()).toContainText("sqrt(1)");

    await editor.press("Enter");
    await editor.type("条件筛选最小值");
    await editor.press("Control+Space");
    await expect(page.getByRole("option", { name: "条件筛选最小值轨迹 Measure · minimum_where", exact: true })).toBeVisible();
    await editor.press("Escape");

    await editor.press("Enter");
    await editor.type("真");
    await editor.press("Control+Space");
    const trueCompletion = page.getByRole("option", { name: "布尔真关键字 · true", exact: true });
    await expect(trueCompletion).toBeVisible();
    await trueCompletion.hover();
    const completionInfo = page.locator(".kirin-completion-info");
    await completionInfo.getByRole("button", { name: "查看相关语法" }).click();
    await expect(page.getByRole("dialog", { name: "Kirin Tor 语法参考" }).getByRole("heading", { name: "量纲、单位与值域" })).toBeVisible();
  });

  test("当前 Process 词汇、高亮与上下文帮助保持一致", async ({ page }) => {
    await openWorkbench(page);
    await page.getByRole("button", { name: rotationButtonName }).click();
    const editor = page.getByRole("textbox", { name: "Kirin Tor 源码：过程周期证明（虚构）" });
    await expect(editor).toBeVisible();

    const stateLine = page.locator(".cm-line").filter({ hasText: "state mana:" });
    await expect(stateLine.locator("span").filter({ hasText: /^state$/ })).toHaveCSS("color", "rgb(217, 119, 87)");
    const inputLine = page.locator(".cm-line").filter({ hasText: "input regeneration:" });
    await expect(inputLine.locator("span").filter({ hasText: /^regeneration$/ })).toHaveCSS("color", "rgb(201, 196, 185)");
    const measureLine = page.locator(".cm-line").filter({ hasText: "measure ending_mana:" });
    await expect(measureLine.locator("span").filter({ hasText: /^final$/ })).toHaveCSS("color", "rgb(232, 184, 109)");
    const boundsLine = page.locator(".cm-line").filter({ hasText: /^\s*bounds:/ });
    await expect(boundsLine.locator("span").first()).toHaveCSS("color", "rgb(232, 184, 109)");
    const proseLine = page.locator(".cm-line").filter({ hasText: "完全虚构的固定策略" });
    await expect(proseLine.locator("span").first()).toHaveCSS("font-style", "italic");

    await editor.press(`${modKey}+End`);
    await editor.type("\nstate misplaced: count = 0");
    await expect(page.getByRole("tab", { name: /诊断 1/ })).toBeVisible();
    await page.getByRole("tab", { name: /诊断 1/ }).click();
    await page.getByRole("button", { name: "查看相关语法" }).click();
    await expect(page.getByRole("dialog", { name: "Kirin Tor 语法参考" }).getByRole("heading", { name: "有界 Process、场景与策略分析" })).toBeVisible();
  });

  test("光标、活动行和文本选择具有可见且可读的交互状态", async ({ page }) => {
    await openWorkbench(page);
    await openCombo(page);
    const editor = page.getByRole("textbox", { name: "Kirin Tor 源码：双技能组合（虚构）" });
    await editor.press(`${modKey}+f`);
    await page.locator('.cm-search input[name="search"]').fill("combo.total");
    await page.locator('.cm-search button[name="next"]').click();
    await page.keyboard.press("Escape");
    await editor.focus();

    const cursorStatus = page.locator(".editor-cursor-status");
    await expect(cursorStatus).toHaveText("已选 11 字符");
    const selection = page.locator(".cm-selectionBackground").first();
    await expect(selection).toBeVisible();
    await expect(selection).toHaveCSS("background-color", "rgba(207, 116, 85, 0.42)");
    await expect(page.locator(".cm-activeLine")).toHaveCSS("box-shadow", /rgb\(143, 84, 63\)/);

    await page.getByRole("button", { name: "工作区工具" }).click();
    await expect(selection).toBeVisible();
    await expect(selection).toHaveCSS("background-color", "rgba(207, 116, 85, 0.24)");
    await page.keyboard.press("Escape");

    await editor.focus();
    await editor.press("ArrowRight");
    await expect(cursorStatus).toHaveText(/行 \d+，列 \d+/);
    const cursor = page.locator(".cm-cursor-primary");
    await expect(cursor).toBeAttached();
    await expect(cursor).toHaveCSS("border-left-color", "rgb(240, 139, 102)");
    await expect(cursor).toHaveCSS("border-left-width", "2px");
  });

  test("编辑器提供查找、大纲、源码联动、引用与安全重命名", async ({ page }) => {
    await openWorkbench(page);
    await openCombo(page);
    const editor = page.getByRole("textbox", { name: "Kirin Tor 源码：双技能组合（虚构）" });

    await editor.press(`${modKey}+f`);
    const searchPanel = page.locator(".cm-search");
    await expect(searchPanel).toBeVisible();
    await searchPanel.locator('input[name="search"]').fill("0.10");
    await searchPanel.locator('input[name="replace"]').fill("0.11");
    await searchPanel.locator('button[name="next"]').click();
    await searchPanel.locator('button[name="replace"]').click();
    await expect(page.locator(".cm-line").filter({ hasText: "0.11" })).toBeVisible();
    await page.keyboard.press("Escape");
    await editor.press(`${modKey}+z`);
    await expect(page.locator(".cm-line").filter({ hasText: "0.10" })).toBeVisible();

    await page.getByRole("button", { name: "文档符号大纲" }).click();
    const totalSymbol = page.locator(".outline-list button").filter({ hasText: "组合期望伤害" });
    await expect(totalSymbol).toBeVisible();
    await totalSymbol.click();
    await expect(page.locator(".cm-activeLine")).toContainText('total "组合期望伤害"');
    await expect(page.locator(".document-result-preview.is-source-linked")).toBeVisible();

    await editor.press("Shift+F12");
    const references = page.getByRole("dialog", { name: /定义与引用 · combo.total/ });
    await expect(references).toContainText("entries/组合模型.kirin:20");
    await expect(references).toContainText("entries/组合模型.kirin:27");
    await references.locator(".mantine-Drawer-close").click();

    await page.getByRole("button", { name: "文档符号大纲" }).click();
    await page.locator(".outline-list button").filter({ hasText: "组合期望伤害" }).click();
    await expect(page.locator(".cm-activeLine")).toContainText('total "组合期望伤害"');
    await page.getByRole("button", { name: "文档操作" }).click();
    await page.getByText("重命名光标处成员", { exact: false }).click();
    const rename = page.getByRole("dialog", { name: "安全重命名符号" });
    await rename.getByRole("textbox", { name: "新的正式名称" }).fill("combined_total");
    await rename.getByRole("button", { name: "重命名草稿" }).click();
    await expect(rename).toBeHidden();
    await expect(editor).toContainText('combined_total "组合期望伤害"');
    await expect(editor).toContainText("combo.combined_total");
  });

  test("快速切换、转到定义与函数参数提示共享符号索引", async ({ page }) => {
    await openWorkbench(page);
    await page.getByRole("button", { name: /命令/ }).click();
    const paletteSearch = page.getByPlaceholder("搜索页面或命令…");
    await paletteSearch.fill("技能 A");
    await page.getByText("打开文档：技能 A（虚构）", { exact: true }).click();
    await expect(page.getByRole("textbox", { name: "Kirin Tor 源码：技能 A（虚构）" })).toBeVisible();

    await openCombo(page);
    const editor = page.getByRole("textbox", { name: "Kirin Tor 源码：双技能组合（虚构）" });
    await editor.press(`${modKey}+f`);
    const definitionSearch = page.locator('.cm-search input[name="search"]');
    await definitionSearch.fill("skill_a.expected");
    await page.locator('.cm-search button[name="next"]').click();
    await page.keyboard.press("Escape");
    await expect(page.locator(".cm-activeLine")).toContainText("skill_a.expected");
    await editor.press("F12");
    await expect(page.getByRole("textbox", { name: "Kirin Tor 源码：技能 A（虚构）" })).toBeVisible();
    await expect(page.locator(".cm-activeLine")).toContainText("expected(c: probability)");

    await openCombo(page);
    await editor.press(`${modKey}+f`);
    const functionSearch = page.locator('.cm-search input[name="search"]');
    await functionSearch.fill("技能甲");
    await page.locator('.cm-search button[name="next"]').click();
    await page.keyboard.press("Escape");
    await editor.press("ArrowRight");
    await editor.press("ArrowRight");
    await expect(page.locator(".editor-signature-hint")).toContainText("function expected(c: probability): damage · 参数 1");
    await expect(page.locator(".cm-foldGutter")).toBeVisible();
  });

  test("撤销历史跨文档保留且未保存草稿可在重载后恢复", async ({ page, request }) => {
    await openWorkbench(page);
    await openCombo(page);
    let editor = page.getByRole("textbox", { name: "Kirin Tor 源码：双技能组合（虚构）" });
    await page.locator(".cm-line").last().click();
    await editor.press("End");
    await editor.type("// undo across documents");
    await page.getByRole("button", { name: "技能 A（虚构） entries/技能甲.kirin", exact: true }).click();
    await openCombo(page);
    editor = page.getByRole("textbox", { name: "Kirin Tor 源码：双技能组合（虚构）" });
    await editor.press(`${modKey}+z`);
    await expect(editor).not.toContainText("// undo across documents");

    await page.locator(".cm-line").last().click();
    await editor.press("End");
    await editor.type("// recovered after reload");
    await expect.poll(async () => {
      const response = await request.get("/api/bootstrap", { headers: { "X-Kirin-Token": "kirin-e2e-token" } });
      const data = await response.json();
      return Object.values(data.recovery.drafts as Record<string, { text: string }>).some((draft) => draft.text.includes("recovered after reload"));
    }).toBe(true);
    await page.reload();
    await expect(page.getByText("已恢复 1 个草稿", { exact: true })).toBeVisible();
    await openCombo(page);
    const recoveredEditor = page.getByRole("textbox", { name: "Kirin Tor 源码：双技能组合（虚构）" });
    await recoveredEditor.press(`${modKey}+f`);
    await page.locator('.cm-search input[name="search"]').fill("recovered after reload");
    await page.locator('.cm-search button[name="next"]').click();
    await expect(page.locator(".cm-activeLine")).toContainText("// recovered after reload");
  });

  test("检查器自动派生结果、图表与公式且不提供参数填写", async ({ page }) => {
    await openWorkbench(page);
    await openCombo(page);
    await page.getByRole("tab", { name: "预览", exact: true }).click();
    await expect(page.getByRole("textbox", { name: "临时参数" })).toHaveCount(0);
    await expect(page.getByRole("combobox", { name: "参数方案" })).toHaveCount(0);
    await expect(page.getByRole("button", { name: "计算结果" })).toHaveCount(0);
    await expect(page.locator(".document-result-preview")).toContainText("2,420");
    await expect(page.locator(".preview-input-identity strong")).toHaveText("暴击率");
    await expect(page.locator(".preview-input-identity small")).toHaveText("combo.crit");

    await page.locator(".mantine-SegmentedControl-label").filter({ hasText: "图表" }).click();
    await expect(page.getByRole("button", { name: "生成图表" })).toHaveCount(0);
    await expect(page.getByRole("button", { name: "展开预览" })).toBeVisible();
    await expect(page.locator(".document-chart-preview .canvas-data-fallback summary")).toContainText("使用键盘查看");
    await page.getByRole("button", { name: "展开预览" }).click();
    await expect(page.getByRole("dialog", { name: "展开图表预览" })).toBeVisible();
    await page.locator(".mantine-Modal-close").click();

    await page.getByRole("tab", { name: "公式", exact: true }).click();
    await expect(page.getByRole("spinbutton", { name: "超时" })).toHaveCount(0);
    await expect(page.getByRole("button", { name: "解释公式" })).toHaveCount(0);
    await expect(page.locator(".formula-result")).toContainText("2200*combo.crit + 2200");
  });

  test("固定策略由 Process 重放并证明边界周期", async ({ page }) => {
    await openWorkbench(page);
    await page.getByRole("button", { name: "过程周期证明（虚构） entries/循环分析.kirin", exact: true }).click();
    await page.getByRole("tab", { name: "预览", exact: true }).click();

    const preview = page.locator(".document-result-preview");
    await expect(preview).toContainText("证明边界周期");
    await expect(preview).toContainText("2 次迭代");
    await expect(preview).toContainText("cycle");
    await preview.locator(".technical-result summary").click();
    await expect(preview.locator(".technical-result")).toContainText('"preperiod": 1');
    await expect(preview.locator(".technical-result")).toContainText('"period": 1');

    await page.getByRole("button", { name: "定位分析源码" }).click();
    await expect(page.locator(".cm-activeLine")).toContainText('analysis prove_rotation "证明边界周期"');

    await page.getByRole("combobox", { name: "过程分析" }).click();
    await page.getByRole("option", { name: "重放固定策略" }).click();
    await expect(preview).toContainText("重放固定策略");
    await expect(preview).toContainText("1 条路径");
    await expect(preview).toContainText("run");
  });

  test("结果、图表、公式与局部关系都能返回源码位置", async ({ page }) => {
    await openWorkbench(page);
    await openCombo(page);
    const focusChoice = (label: string) => page.locator(".document-focus-switch .mantine-SegmentedControl-label").filter({ hasText: label });
    const activeLine = page.locator(".cm-activeLine");

    await page.getByRole("tab", { name: "预览", exact: true }).click();
    await expect(page.getByRole("button", { name: "定位结果源码" })).toBeVisible();
    await focusChoice("仅预览").click();
    await page.getByRole("button", { name: "定位结果源码" }).click();
    await expect(page.getByRole("radio", { name: "分栏" })).toBeChecked();
    await expect(activeLine).toContainText('total "组合期望伤害"');

    await focusChoice("仅预览").click();
    await page.locator(".mantine-SegmentedControl-label").filter({ hasText: "图表" }).click();
    await expect(page.getByRole("button", { name: "定位图表源码" })).toBeVisible();
    await page.getByRole("button", { name: "定位图表源码" }).click();
    await expect(activeLine).toContainText('chart preview "combo"');

    await focusChoice("仅预览").click();
    await page.getByRole("tab", { name: "公式", exact: true }).click();
    await expect(page.getByRole("button", { name: "定位公式源码" })).toBeVisible();
    await page.getByRole("button", { name: "定位公式源码" }).click();
    await expect(activeLine).toContainText('total "组合期望伤害"');

    await focusChoice("仅预览").click();
    await page.getByRole("tab", { name: "关系", exact: true }).click();
    const localGraph = page.locator(".local-graph-stage .canvas-data-fallback");
    const directionChoice = (label: string) => page.locator(".local-graph-toolbar .mantine-SegmentedControl-label").filter({ hasText: label });
    await expect(page.getByRole("radio", { name: "全部" })).toBeChecked();
    await localGraph.locator("summary").click();
    await expect(localGraph.getByRole("button").filter({ hasText: "combo.total" })).toContainText("当前文档");
    await directionChoice("使用者").click();
    await expect(localGraph.getByRole("button").filter({ hasText: "skill_a.expected" })).toHaveCount(0);
    await directionChoice("依赖").click();
    await expect(localGraph.getByRole("button").filter({ hasText: "skill_a.expected" })).toBeVisible();
    await localGraph.getByRole("button").filter({ hasText: "combo.total" }).click();
    await expect(page.locator(".local-graph-selection")).toContainText("3 个依赖 · 0 个使用者");
    await page.locator(".local-graph-selection").click();
    await expect(page.getByRole("radio", { name: "分栏" })).toBeChecked();
    await expect(activeLine).toContainText('total "组合期望伤害"');
  });

  test("诊断项跳转到编辑器中的错误位置", async ({ page }) => {
    await openWorkbench(page);
    await openCombo(page);
    const editor = page.getByRole("textbox", { name: "Kirin Tor 源码：双技能组合（虚构）" });
    await page.locator(".cm-line").last().click();
    await editor.press("End");
    await editor.type("unknown：");
    await expect(page.getByRole("tab", { name: /诊断 1/ })).toBeVisible();
    await page.getByRole("tab", { name: /诊断 1/ }).click();
    await page.getByRole("button", { name: "修复全角符号" }).click();
    await expect(page.locator(".cm-activeLine")).toContainText("unknown:");
  });

  test("外部写入自动重载干净文档并发现新文档", async ({ page }) => {
    await openWorkbench(page);
    await openCombo(page);
    const editor = page.getByRole("textbox", { name: "Kirin Tor 源码：双技能组合（虚构）" });
    const sourcePath = resolve(".e2e-workspace", "entries", "组合模型.kirin");
    const createdPath = resolve(".e2e-workspace", "entries", "agent_model.kirin");
    const diskSource = await readFile(sourcePath, "utf8");
    try {
      await writeFile(sourcePath, `${diskSource}\n// agent external edit\n`, "utf8");
      await expect(editor).toContainText("// agent external edit", { timeout: 8_000 });

      await writeFile(
        createdPath,
        '@kirin 2\n@entry agent_model "Agent model"\n\noutput value: dimensionless = 1\n',
        "utf8",
      );
      await expect(page.getByRole("button", { name: /^Agent model entries\/agent_model\.kirin/ })).toBeVisible({ timeout: 8_000 });
    } finally {
      await writeFile(sourcePath, diskSource, "utf8");
      await rm(createdPath, { force: true });
    }
    await expect(editor).not.toContainText("// agent external edit", { timeout: 8_000 });
  });

  test("外部修改自动触发冲突比较、保留草稿副本并可重新加载", async ({ page }) => {
    await openWorkbench(page);
    await openCombo(page);
    const editor = page.getByRole("textbox", { name: "Kirin Tor 源码：双技能组合（虚构）" });
    await page.locator(".cm-line").last().click();
    await editor.press("End");
    await editor.type("// local workbench draft");

    const sourcePath = resolve(".e2e-workspace", "entries", "组合模型.kirin");
    const diskSource = await readFile(sourcePath, "utf8");
    await writeFile(sourcePath, `${diskSource}\n// external edit\n`, "utf8");

    const conflictDialog = page.getByRole("dialog", { name: "比较外部修改" });
    await expect(conflictDialog).toContainText("// local workbench draft", { timeout: 8_000 });
    await expect(conflictDialog).toContainText("Agent 或其他外部编辑器");
    await expect(conflictDialog).toContainText("// external edit");
    await conflictDialog.getByRole("button", { name: "查看协作边界" }).click();
    await expect(conflictDialog).toBeHidden();
    let reference = page.getByRole("dialog", { name: "Kirin Tor 语法参考" });
    await expect(reference.getByRole("heading", { name: "Agent 与外部编辑器" })).toBeVisible();
    await expect(reference).toContainText("Agent 不是 Kirin Tor 关键字");
    await reference.locator(".mantine-Drawer-close").click();
    await page.getByLabel("比较外部修改").click();
    await expect(conflictDialog).toBeVisible();
    const downloadPromise = page.waitForEvent("download");
    await conflictDialog.getByRole("button", { name: "保留草稿副本" }).click();
    expect((await downloadPromise).suggestedFilename()).toBe("组合模型.workbench-draft.kirin");

    await conflictDialog.getByRole("button", { name: "重新加载磁盘版本" }).click();
    await expect(conflictDialog).toBeHidden();
    await expect(editor).toContainText("// external edit");
    await expect(editor).not.toContainText("// local workbench draft");
    await expect(page.getByRole("button", { name: "保存全部" }).first()).toBeDisabled();
  });

  test("空工作区展示只读教程并只复制为未保存草稿", async ({ page, browserName }) => {
    const entries = resolve(".e2e-workspace", "entries");
    const backup = resolve(".e2e-workspace", "entries-tutorial-backup");
    await rename(entries, backup);
    await mkdir(entries);
    try {
      await page.goto(sessionUrl);
      await expect(page.getByLabel("Kirin Tor 入门")).toBeVisible();
      await expect(page.getByRole("heading", { name: "从一份真正的 Kirin Tor 源码开始" })).toBeVisible();
      await expect(page.getByText(/让本地 Agent 直接创建/)).toBeVisible();
      await expect(page.getByText("真正的 `.kirin` 才是工作区数据", { exact: true })).toBeVisible();
      await expect(page.getByRole("heading", { name: "三个虚构、游戏中立的练习" })).toBeVisible();
      expect((await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa"]).analyze()).violations).toEqual([]);
      if (browserName !== "firefox") {
        await expect(page.locator(".workspace-welcome")).toHaveScreenshot("empty-workspace-welcome.png", {
          animations: "disabled",
          maxDiffPixelRatio: 0.08,
          stylePath: resolve("tests/e2e/screenshot.css"),
        });
      }

      await page.getByRole("button", { name: "了解 Agent 协作" }).click();
      const reference = page.getByRole("dialog", { name: "Kirin Tor 语法参考" });
      await expect(reference.getByRole("heading", { name: "Agent 与外部编辑器" })).toBeVisible();
      await reference.locator(".mantine-Drawer-close").click();

      await page.getByRole("button", { name: "开始基础教程" }).click();
      const tutorial = page.getByRole("dialog", { name: "教程与示例" });
      await expect(tutorial.getByRole("heading", { name: "基础公式" })).toBeVisible();
      await expect(tutorial.getByRole("button", { name: "关闭抽屉" })).toBeVisible();
      await expect(tutorial.locator(".tutorial-source pre")).toContainText("@entry tutorial_basic");
      await expect(tutorial).toContainText("只读 · 尚未进入当前工作区");
      expect((await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa"]).analyze()).violations).toEqual([]);

      await tutorial.getByRole("textbox", { name: "文档 ID" }).fill("my_first_model");
      await tutorial.getByRole("button", { name: "复制为未保存草稿" }).click();
      const editor = page.getByRole("textbox", { name: "Kirin Tor 源码：教程 1：基础公式" });
      await expect(editor).toContainText("@entry my_first_model");
      await expect(page.getByText("已修改", { exact: true })).toBeVisible();
      await expect(access(resolve(entries, "my_first_model.kirin"))).rejects.toThrow();
    } finally {
      await rm(entries, { recursive: true, force: true });
      await rename(backup, entries);
    }
  });
});
