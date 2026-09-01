const PROTOCOL = "kirin-workbench-plugin";
const app = document.querySelector("#app");
let contribution = null;
let context = {};
let nextAction = 0;
const pending = new Map();

function post(message) {
  parent.postMessage({ protocol: PROTOCOL, api: 1, ...message }, "*");
}

function action(name, payload) {
  const id = `example-${++nextAction}`;
  post({ type: "action", id, action: name, payload });
  return new Promise((resolve, reject) => pending.set(id, { resolve, reject }));
}

function text(value) {
  return value == null ? "—" : String(value);
}

function clear() {
  app.replaceChildren();
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
    header("Sandboxed renderer", "等待有效文档", "Kirin 尚未发送 document.read 投影。");
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
        void action("navigate-source", {
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
    const calculate = document.createElement("button");
    calculate.type = "button";
    calculate.className = "action";
    calculate.textContent = `计算 ${documentProjection.id}.${outputs[0]}`;
    const result = document.createElement("div");
    result.className = "result";
    result.hidden = true;
    calculate.addEventListener("click", async () => {
      calculate.disabled = true;
      try {
        const value = await action("evaluate", { target: `${documentProjection.id}.${outputs[0]}` });
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
}

function render() {
  clear();
  if (!contribution) {
    header("Kirin Plugin", "正在等待激活", "宿主尚未发送受限上下文。");
  } else if (contribution.kind === "renderer") {
    renderTree();
  } else {
    renderWorkspace(contribution.kind);
  }
}

addEventListener("message", (event) => {
  const message = event.data;
  if (!message || message.protocol !== PROTOCOL || message.api !== 1) return;
  if (message.type === "activate" || message.type === "context") {
    contribution = message.contribution;
    context = message.context || {};
    render();
  } else if (message.type === "action-result" || message.type === "action-error") {
    const request = pending.get(message.id);
    if (!request) return;
    pending.delete(message.id);
    if (message.type === "action-result") request.resolve(message.result);
    else request.reject(message.error);
  }
});

post({ type: "ready" });
