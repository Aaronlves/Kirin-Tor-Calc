import { createKirinPlugin } from "./kirin-plugin-sdk.mjs";

const kirin = createKirinPlugin({ api: 2 });
const app = document.querySelector("#app");
let contribution = null;
let context = {};
let capabilities = kirin.descriptor;

function text(value) {
  return value == null ? "—" : String(value);
}

function clear() {
  app.replaceChildren();
}

function resultBlock() {
  const result = document.createElement("div");
  result.className = "result";
  result.hidden = true;
  return result;
}

function header(eyebrow, title, description) {
  const label = document.createElement("div");
  label.className = "eyebrow";
  label.textContent = eyebrow;
  const heading = document.createElement("h1");
  heading.textContent = title;
  const detail = document.createElement("div");
  detail.className = "muted";
  detail.textContent = description;
  app.append(label, heading, detail);
}

function renderTree() {
  const documentProjection = context.document;
  if (!documentProjection) {
    header("Sandboxed renderer", "等待有效文档", "Kirin Tor 尚未发送 document.read 投影。");
    return;
  }
  header(
    "Fictional talent tree",
    `${text(documentProjection.name)} 天赋页`,
    `由 ${text(documentProjection.id)} 的验证后结构生成；这不是实际游戏数据。`,
  );
  const members = Array.isArray(context.members) ? context.members : [];
  const relatedIds = new Set();
  for (const edge of Array.isArray(context.relationships) ? context.relationships : []) {
    relatedIds.add(edge.source);
    relatedIds.add(edge.target);
  }
  const known = new Map(members.map((member) => [member.id, member]));
  const nodes = [...new Set([...relatedIds, ...known.keys()])].sort();
  const tree = document.createElement("section");
  tree.className = "tree";
  tree.setAttribute("aria-label", "虚构天赋节点");
  for (const id of nodes) {
    const member = known.get(id);
    const button = document.createElement("button");
    button.type = "button";
    button.className = "node";
    const title = document.createElement("strong");
    title.textContent = member?.label || id.split(".").at(-1) || id;
    const canonical = document.createElement("small");
    canonical.textContent = id;
    const kind = document.createElement("span");
    kind.className = "node-kind";
    kind.textContent = member?.kind || "依赖";
    button.append(title, canonical, kind);
    if (member?.line) {
      button.addEventListener("click", () => {
        void kirin.request("navigate-source", {
          key: documentProjection.key,
          line: member.line,
          column: member.column || 1,
        });
      });
    }
    tree.append(button);
  }
  app.append(tree);
  const outputs = Object.keys(documentProjection.content?.outputs || {});
  if (outputs.length) {
    const targetId = `${documentProjection.id}.${outputs[0]}`;
    const calculate = document.createElement("button");
    calculate.type = "button";
    calculate.className = "action";
    calculate.textContent = `计算 ${targetId}`;
    const result = resultBlock();
    calculate.addEventListener("click", async () => {
      calculate.disabled = true;
      try {
        const envelope = await kirin.operations.evaluate({ target: targetId });
        const value = envelope.result;
        await kirin.results.present(envelope.operation_id, { title: "当前技能结果" });
        result.textContent = `验证后结果：${text(value.formatted || value.approximate || value.exact)}`;
        result.hidden = false;
      } catch (error) {
        result.textContent = `计算未完成：${text(error?.message || error)}`;
        result.hidden = false;
      } finally {
        calculate.disabled = false;
      }
    });
    app.append(calculate, result);

    const critInputId = Object.keys(documentProjection.content?.inputs || {})
      .map((item) => `${documentProjection.id}.${item}`)
      .find((item) => item.endsWith(".crit"));
    if (critInputId) {
      const controls = document.createElement("section");
      controls.className = "controls";
      controls.setAttribute("aria-label", "数学操作桥接示例");
      const label = document.createElement("label");
      label.htmlFor = "temporary-crit";
      label.textContent = "临时暴击率";
      const input = document.createElement("input");
      input.id = "temporary-crit";
      input.value = "0.5";
      const evaluateOverride = document.createElement("button");
      evaluateOverride.type = "button";
      evaluateOverride.className = "action";
      evaluateOverride.textContent = "使用临时暴击率计算";
      const overrideResult = resultBlock();
      evaluateOverride.addEventListener("click", async () => {
        evaluateOverride.disabled = true;
        try {
          const envelope = await kirin.operations.evaluate({
            target: targetId,
            overrides: { [critInputId]: input.value },
          });
          const value = envelope.result;
          await kirin.results.present(envelope.operation_id, { title: "临时参数结果", order: 10 });
          overrideResult.textContent = `临时结果：${text(value.formatted || value.approximate || value.exact)}`;
          overrideResult.hidden = false;
        } catch (error) {
          overrideResult.textContent = `计算未完成：${text(error?.message || error)}`;
          overrideResult.hidden = false;
        } finally {
          evaluateOverride.disabled = false;
        }
      });
      const scan = document.createElement("button");
      scan.type = "button";
      scan.className = "action";
      scan.textContent = "扫描暴击率";
      const scanResult = resultBlock();
      scan.addEventListener("click", async () => {
        scan.disabled = true;
        try {
          const envelope = await kirin.operations.scan({
            x: critInputId,
            range: "0:0.5",
            points: 3,
            targets: [targetId],
          });
          const value = envelope.result;
          scanResult.textContent = `扫描结果：${Array.isArray(value.rows) ? value.rows.length : 0} 个点`;
          scanResult.hidden = false;
        } catch (error) {
          scanResult.textContent = `扫描未完成：${text(error?.message || error)}`;
          scanResult.hidden = false;
        } finally {
          scan.disabled = false;
        }
      });
      const checkProtocol = document.createElement("button");
      checkProtocol.type = "button";
      checkProtocol.className = "action";
      checkProtocol.textContent = "检查全部数学动作";
      const protocolResult = resultBlock();
      checkProtocol.addEventListener("click", async () => {
        checkProtocol.disabled = true;
        try {
          if (!context.catalog?.revision) throw new Error("宿主没有提供模型 revision");
          await kirin.model.capabilities();
          const queried = await kirin.model.query({
            kind: ["output"],
            prefix: "aoe_pattern.",
            limit: capabilities?.limits?.max_model_query_limit || 100,
          });
          const aoeTarget = (queried.items || []).find((item) => item.id === "aoe_pattern.total");
          if (!aoeTarget) throw new Error("没有找到二维网格示例输出");
          await kirin.model.get({ id: targetId, kind: "output" });
          await kirin.model.dependencies({
            id: targetId,
            kind: "output",
            depth: 2,
          });
          await kirin.model.document({ id: documentProjection.id });
          await kirin.operations.evaluateMany({ targets: [targetId, aoeTarget.id] });
          await kirin.operations.explain({ target: targetId });
          await kirin.operations.compare({
            target: targetId,
            variants: [
              { name: "默认" },
              { name: "高暴击", overrides: { [critInputId]: "0.5" } },
            ],
          });
          await kirin.operations.grid({
            target: aoeTarget.id,
            x: "aoe_pattern.bonus",
            x_range: "0:1",
            x_points: 2,
            y: "aoe_pattern.targets",
            y_range: "1:3",
            y_points: 3,
          });
          await kirin.operations.solve({
            target: targetId,
            variable: critInputId,
            equals: "2750",
            range: "0:1",
          });
          const analysisPage = await kirin.model.query({ kind: ["analysis"], limit: 1 });
          if (analysisPage.items?.[0]) {
            const disposableJob = await kirin.operations.analyze({
              target: analysisPage.items[0].id,
              include_trace: false,
            });
            await kirin.jobs.status(disposableJob.job_id);
            await kirin.jobs.cancel(disposableJob.job_id);
          }
          await kirin.storage.get("ui.protocol-audit");
          await kirin.storage.set("ui.protocol-audit", true);
          await kirin.storage.delete("ui.protocol-audit");
          protocolResult.textContent = [
            "Catalog、数学动作与偏好协议检查通过",
            `compare 上限 ${text(capabilities?.limits?.max_comparison_variants)}`,
          ].join("；");
          protocolResult.hidden = false;
        } catch (error) {
          protocolResult.textContent = `数学动作检查未完成：${text(error?.message || error)}`;
          protocolResult.hidden = false;
        } finally {
          checkProtocol.disabled = false;
        }
      });
      const propose = document.createElement("button");
      propose.type = "button";
      propose.className = "action";
      propose.textContent = "提交 Build 模板提案";
      const proposalResult = resultBlock();
      propose.addEventListener("click", async () => {
        propose.disabled = true;
        try {
          const template = (context.templates || []).find((item) => (
            item.origin === "package"
            && item.package_name === "community.fictional-models"
            && item.bindings?.includes("coefficient")
          ));
          if (!template) throw new Error("没有找到 Package 提供的 Build 模板");
          const value = await kirin.proposals.submit({
            title: "保存当前虚构 Build",
            description: "由 Package 模板和结构化绑定生成本地 Build 文档。",
            changes: [{
              kind: "create-from-template",
              template: template.value,
              document_id: "fictional_saved_build",
              bindings: { coefficient: input.value },
            }],
          });
          proposalResult.textContent = value.status === "queued"
            ? "提案已进入 Kirin Tor 保存前变更审查；源码尚未改变。"
            : `提案未进入队列：${text(value.reason)}`;
          proposalResult.hidden = false;
        } catch (error) {
          proposalResult.textContent = `提案未完成：${text(error?.message || error)}`;
          proposalResult.hidden = false;
        } finally {
          propose.disabled = false;
        }
      });
      const density = document.createElement("button");
      density.type = "button";
      density.className = "action";
      density.textContent = "界面密度：读取中";
      let compact = false;
      const updateDensity = () => {
        density.textContent = `界面密度：${compact ? "紧凑" : "舒展"}`;
      };
      void kirin.storage.get("ui.compact").then((stored) => {
        compact = stored.found && stored.value === true;
        updateDensity();
      });
      density.addEventListener("click", async () => {
        density.disabled = true;
        try {
          compact = !compact;
          await kirin.storage.set("ui.compact", compact);
          updateDensity();
        } finally {
          density.disabled = false;
        }
      });
      label.append(input);
      controls.append(
        label,
        evaluateOverride,
        overrideResult,
        scan,
        scanResult,
        checkProtocol,
        protocolResult,
        density,
        propose,
        proposalResult,
      );
      app.append(controls);
    }
  }
}

function renderWorkspace(kind) {
  header(
    kind === "tool" ? "Sandboxed tool" : "Plugin view",
    kind === "tool" ? "天赋插件信息" : "虚构 Build 大厅",
    "这里只收到经过权限裁剪的工作区摘要，没有源码、会话令牌或文件系统权限。",
  );
  const cards = document.createElement("section");
  cards.className = "cards";
  for (const item of context.workspace?.documents || []) {
    const card = document.createElement("article");
    card.className = "card";
    const title = document.createElement("strong");
    title.textContent = item.title;
    const detail = document.createElement("small");
    detail.textContent = `${item.kind} · ${item.read_only ? "只读 Package" : "本地权威源码"}`;
    card.append(title, detail);
    cards.append(card);
  }
  app.append(cards);
  if (context.catalog?.status === "ok") {
    const summary = document.createElement("div");
    summary.className = "result";
    summary.textContent = `模型目录：${text(context.catalog.counts?.output)} 个输出，${text(context.catalog.counts?.analysis)} 个过程分析`;
    app.append(summary);
  }
  if (kind === "view" && context.catalog?.revision) {
    const run = document.createElement("button");
    run.type = "button";
    run.className = "action";
    run.textContent = "查询并运行第一个分析";
    const result = resultBlock();
    run.addEventListener("click", async () => {
      run.disabled = true;
      try {
        const queried = await kirin.model.query({
          kind: ["analysis"],
          limit: 1,
        });
        const analysis = queried.items?.[0];
        if (!analysis) throw new Error("当前目录没有具名 Process Analysis");
        const job = await kirin.operations.analyze({ target: analysis.id, include_trace: false });
        const value = await kirin.jobs.wait(job);
        await kirin.results.present(value.operation_id, { title: "Build 分析结果" });
        result.textContent = `分析完成：${text(value.operation)}`;
        result.hidden = false;
      } catch (error) {
        result.textContent = `分析未完成：${text(error?.message || error)}`;
        result.hidden = false;
      } finally {
        run.disabled = false;
      }
    });
    app.append(run, result);
  }
}

function render() {
  clear();
  if (!contribution) {
    header("Kirin Tor Plugin", "正在等待激活", "宿主尚未发送受限上下文。");
  } else if (contribution.kind === "renderer") {
    renderTree();
  } else {
    renderWorkspace(contribution.kind);
  }
}

kirin.onContext((nextContext, nextContribution) => {
  contribution = nextContribution;
  context = nextContext;
  render();
});

const activation = await kirin.ready();
capabilities = activation.capabilities;
contribution = activation.contribution;
context = activation.context;
render();
