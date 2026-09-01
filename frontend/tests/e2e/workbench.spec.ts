import { expect, test, type Page } from "@playwright/test";
import { readFile, writeFile } from "node:fs/promises";
import { resolve } from "node:path";

const sessionUrl = "/?token=kirin-e2e-token";
const comboButtonName = "双技能组合（虚构） entries/组合模型.kirin";

async function openWorkbench(page: Page) {
  await page.goto(sessionUrl);
  await expect(page.getByRole("button", { name: comboButtonName, exact: true })).toBeVisible();
}

async function openCombo(page: Page) {
  await page.getByRole("button", { name: comboButtonName, exact: true }).click();
  await expect(page.getByRole("textbox", { name: "Kirin 源码：双技能组合（虚构）" })).toBeVisible();
}

test.describe.serial("Kirin 浏览器工作台交互", () => {
  test("三种文档专注模式切换并记住选择", async ({ page }) => {
    await page.setViewportSize({ width: 1120, height: 800 });
    await openWorkbench(page);
    await expect(page.getByRole("button", { name: "展开导航" })).toBeVisible();
    await expect(page.locator('[aria-label^="工作区状态："]')).toBeVisible();
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

  test("文档切换与新建文档 Enter 使用同一校验", async ({ page }) => {
    await openWorkbench(page);
    await page.getByRole("button", { name: "技能 A（虚构） entries/技能甲.kirin", exact: true }).click();
    await expect(page.getByRole("textbox", { name: "Kirin 源码：技能 A（虚构）" })).toContainText("@entry skill_a");
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
    const fallback = page.locator(".graph-surface .canvas-data-fallback");
    await fallback.locator("summary").click();
    const firstNode = fallback.locator(".relationship-node-list button").first();
    await firstNode.focus();
    await page.keyboard.press("Enter");
    await expect(page.locator(".graph-inspector")).toContainText("所属文档");
  });

  test("补全片段替换前缀并把光标放进参数", async ({ page }) => {
    await openWorkbench(page);
    await openCombo(page);
    const editor = page.getByRole("textbox", { name: "Kirin 源码：双技能组合（虚构）" });
    await page.locator(".cm-line").last().click();
    await editor.press("End");
    await editor.type("  平方根");
    await editor.press("Control+Space");
    const sqrtCompletion = page.getByRole("option", { name: "平方根内置函数 · sqrt", exact: true });
    await expect(sqrtCompletion).toBeVisible();
    await sqrtCompletion.click();
    await editor.type("1");
    await expect(page.locator(".cm-line").filter({ hasText: "sqrt(1)" }).first()).toContainText("sqrt(1)");
  });

  test("检查器自动派生结果、图表与公式且不提供参数填写", async ({ page }) => {
    await openWorkbench(page);
    await openCombo(page);
    await page.getByRole("tab", { name: "预览", exact: true }).click();
    await expect(page.getByRole("textbox", { name: "临时参数" })).toHaveCount(0);
    await expect(page.getByRole("combobox", { name: "参数方案" })).toHaveCount(0);
    await expect(page.getByRole("button", { name: "计算结果" })).toHaveCount(0);
    await expect(page.locator(".document-result-preview")).toContainText("2,420");

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
    await expect(activeLine).toContainText("x: combo.crit");

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
    const editor = page.getByRole("textbox", { name: "Kirin 源码：双技能组合（虚构）" });
    await page.locator(".cm-line").last().click();
    await editor.press("End");
    await editor.type("unknown:");
    await expect(page.getByRole("tab", { name: /诊断 1/ })).toBeVisible();
    await page.getByRole("tab", { name: /诊断 1/ }).click();
    await page.locator(".diagnostic-row").first().click();
    await expect(page.locator(".cm-activeLine")).toContainText("unknown:");
  });

  test("外部修改冲突可比较、保留草稿副本并重新加载", async ({ page }) => {
    await openWorkbench(page);
    await openCombo(page);
    const editor = page.getByRole("textbox", { name: "Kirin 源码：双技能组合（虚构）" });
    await page.locator(".cm-line").last().click();
    await editor.press("End");
    await editor.type("// local workbench draft");

    const sourcePath = resolve(".e2e-workspace", "entries", "组合模型.kirin");
    const diskSource = await readFile(sourcePath, "utf8");
    await writeFile(sourcePath, `${diskSource}\n// external edit\n`, "utf8");
    await page.getByRole("button", { name: "保存全部" }).first().click();

    const conflictDialog = page.getByRole("dialog", { name: "比较外部修改" });
    await expect(conflictDialog).toContainText("// local workbench draft");
    await expect(conflictDialog).toContainText("// external edit");
    const downloadPromise = page.waitForEvent("download");
    await conflictDialog.getByRole("button", { name: "保留草稿副本" }).click();
    expect((await downloadPromise).suggestedFilename()).toBe("组合模型.workbench-draft.kirin");

    await conflictDialog.getByRole("button", { name: "重新加载磁盘版本" }).click();
    await expect(conflictDialog).toBeHidden();
    await expect(editor).toContainText("// external edit");
    await expect(editor).not.toContainText("// local workbench draft");
    await expect(page.getByRole("button", { name: "保存全部" }).first()).toBeDisabled();
  });
});
