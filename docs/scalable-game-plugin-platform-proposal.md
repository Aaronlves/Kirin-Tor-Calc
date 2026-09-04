# Kirin Tor 可规模化游戏插件平台提案

> 状态：设计提案，尚未成为实现合同  
> 日期：2026-09-04  
> 目标版本：后续 Kirin Tor feature line；版本号须在实施前另行确定  
> 当前合同：Community Package protocol v2、Workbench Extension Plugin protocol v2 描述现行行为

## 1. 提案目标

Kirin Tor 应成为一个游戏中立、来源可审查、计算可重放的数学底座。第三方维护者可以在它之上发布：

1. **游戏数据与算法 Package**：声明某个游戏版本的数据、公式、机制、参数方案和有界决策模型；
2. **游戏视觉 Plugin**：把这些公开模型投影为角色面板、技能页、天赋树、配装比较、策略编辑器或其他游戏化交互；
3. **本地工作区**：保存用户自己的假设、配置、preset、场景和对 Package 的组合引用。

成功不等于“插件能够显示一个 iframe”。成功必须满足：

- 数学核心不内置游戏、职业、技能、装备或版本数据；
- Package 不执行代码，Plugin 不扩展数学语义；
- Plugin 可以完整、分页、稳定地发现自己依赖的模型，而不是依赖截断的启动快照；
- 一组输入只由宿主数学服务计算，结果保留精确值、单位、证明等级和来源；
- Package、Plugin、接口版本和当前工作区 revision 的兼容性可在激活前判断；
- 大型模型、长 Process Analysis 和多输出界面有明确的资源边界、取消和错误合同；
- Plugin 对源码的任何影响都必须先成为可审查候选，再由用户接受为普通未保存草稿；
- 第三方 JavaScript 的展示声明与宿主验证的计算结果在界面上可区分；
- 作者可以使用正式 SDK、脚手架和一致性测试，而不必手写协议细节。

## 2. 规范语言与状态边界

本提案中的“必须”“不得”“应当”“可以”描述目标平台。只有阶段状态明确标为“已完成”的
部分才是当前实现；其余内容不能用于推断现行行为。

实施后仍有三种需要分开的状态：

| 状态 | 含义 |
| --- | --- |
| Implemented | 当前代码存在该行为 |
| Conformance tested | 自动化测试覆盖了声明的公共合同 |
| Human accepted | 用户已确认产品交互、信息结构和术语可用 |

任一自动化检查通过都不能自动获得 Human accepted 状态。第三方 Package 的数据正确性与 Plugin 的游戏解释正确性也不由 Kirin Tor 测试代替。

## 3. 非目标

本提案不把下列能力纳入数学核心或 Plugin 权限：

- 从技能文本、战斗日志或自然语言自动推导正确模型；
- 在核心中加入 damage、healing、talent、class、item 等特权类型；
- 执行 Package 内的脚本、Python、二进制、安装 hook 或更新 hook；
- 允许 Plugin 注册新的表达式函数、求解器、Process reducer 或 backend operation；
- 允许 iframe 直接读取文件、会话令牌、凭据、宿主 DOM 或任意网络；
- 把 UI 状态、搜索索引、catalog、Plugin storage 或草稿提案提升为模型权威；
- 在没有证明时把有限搜索结果称为全局最优；
- 在首个可规模化版本中提供动态实体集合、空间位置、真实网络延迟或完整战斗模拟器；
- 由 Package 或 Plugin 安装流程静默安装另一个可执行组件。

实时游戏数据抓取应属于 Package 发布者的外部维护流水线。Kirin Tor 消费经过版本化、锁定和摘要验证的 Package release，不让运行中的 Plugin 直接同步远程游戏数据。

## 4. 当前基线与已知缺口

当前仓库已经具备最小闭环：

- `.kirin` 提供精确数值、单位、约束、表、有限分布、静态求值和有界 Process；
- Community Package 是不可执行、可锁定、内容寻址、只读加载的数据与模型发布单元；
- Workbench Plugin 通过沙箱 iframe 提供 renderer、view、tool、command 和 profile；
- Plugin 可以按权限查询 revision-bound Catalog，并调用 evaluate、explain、compare、scan、grid、solve 和具名 Process Analysis；
- Plugin 可以提交当前本地文档的候选全文，由工作台校验并进入人工审查；
- 示例插件的 Chromium 与 WebKit 流程覆盖当前 v2 action，包括五个 Catalog action。

当前能力仍不足以支撑大型第三方游戏平台：

1. 每个插件仍手写 `postMessage` 生命周期、请求关联和错误处理；
2. 没有多输出批量求值、Plugin 可见的长任务进度或按任务取消；
3. 没有安全、限额、非权威的 Plugin 偏好存储；
4. 草稿提案只覆盖当前文档的完整替换，不支持从模板新建用户配置或多文档原子候选；
5. iframe 可以显示自算或伪造的数值，因此“能调用核心”不等于“呈现必然来自核心”；
6. 只有示例插件，没有正式 SDK、脚手架、JSON Schema、生成型类型和完整的第三方 conformance kit。

Phase 0 已消除此前存在的 compare 8/64 分叉：backend 发布一份 Plugin capability
descriptor，Workbench 用它取得 action 权限、backend operation 映射与所有桥接 limits；compare
当前统一为底层已经验证的 8 个 variant。该注册表和内置 conformance matrix 是后续生成
Schema、SDK 与 Operation Service 2 的基线，不代表后续阶段已经实现。

## 5. 不可破坏的架构

目标依赖方向是：

```text
                    local entries/**/*.kirin
                              │
                              ▼
Game data/model Package ──► Workspace + Model Catalog
          │                         │
          │ immutable inputs        ├──► Core Operation Service
          │                         │          │
          ▼                         │          ▼
Package provenance                  │    exact bounded results
                                    │          │
                                    ▼          ▼
                              Plugin Host ──► visual Plugin
                                    │
                                    ▼
                         reviewed draft proposal
                                    │ user accepts
                                    ▼
                         ordinary unsaved local draft
```

### 5.1 权威分层

| 层 | 可以定义 | 不得定义 | 权威角色 |
| --- | --- | --- | --- |
| Core | 游戏中立数学、类型检查、单位、Process 语义、操作与边界 | 游戏事实或命名语义 | 唯一计算语义实现 |
| Package | 游戏数据、公式、类型、对象、场景、算法、来源说明 | 可执行代码或宿主权限 | 版本化模型权威 |
| Workspace | 用户假设、preset、组合场景和本地扩展 | 覆盖锁定 Package 内容 | 用户可编辑模型权威 |
| Catalog | 已验证模型的查询投影 | 独立可写定义 | 可重建读取模型 |
| Operation result | 某 revision 下的计算、证明和来源 | 新公式或参数默认值 | 派生证据 |
| Plugin | 交互、布局、选择、说明与视觉编码 | backend 数学扩展、直接源码写入 | 非权威呈现与工作流 |
| Host-verified view | 宿主对操作结果的标准化呈现 | Plugin 自定义计算 | 可核对的派生呈现 |
| Proposal | 一组经验证的候选源码变更 | 自动保存 | 待人工接受的临时状态 |
| Plugin preference | 折叠、布局、最近选择等 UI 偏好 | build、数值假设或模型定义 | 用户本地非权威状态 |

### 5.2 单向规则

- Package 只能依赖 Package；不得依赖 Plugin。
- Plugin 可以要求模型接口存在，但不得使 Package 安装隐式安装 Plugin。
- Plugin 不得向 Core 注册语义。
- Catalog 与 Operation result 必须携带产生它们的 workspace revision。
- 只有 `.kirin` source 参与计算定义；Plugin storage 不进入求值。
- Plugin 对模型的任何修改必须经过 Proposal → Review → Unsaved draft → Save All。

## 6. 稳定身份与模型接口

### 6.1 为什么需要模型接口

绑定某个 Package 名称不足以形成可规模化合同。Package 可以更新数据而不改变 Plugin 需要的结构，也可以在同一名称下做破坏性结构变化。Plugin 应依赖“模型接口”，而不是猜测文档标题、文件名或字段标签。

模型接口是由 Package 声明、由 Kirin Tor 只做身份与版本校验的游戏中立字符串合同。Core 不解释接口代表天赋、技能还是装备。

### 6.2 Package 提供接口

建议在下一版 Package manifest 中加入：

以下版本号与 ID 仅用于说明目标合同，不预先决定实际 release 编号。

```toml
schema = 2
name = "community.fictional-models"
version = "3.4.1"
namespace = "fictional"
requires_kirin = "0.5"

[interfaces."fictional.theorycraft-model"]
revision = 2
documents = ["fictional_semantics", "fictional_character"]
document_prefixes = ["fictional_action_"]

[interfaces."fictional.character-build"]
revision = 1
documents = ["fictional_builds"]
document_prefixes = []
```

规则：

- interface ID 必须是全局稳定的 dotted lower-case ID；
- `revision` 是正整数且精确匹配，不使用隐式版本范围；
- 同一个锁定 Package 图中，一个 interface ID + revision 只能有一个 provider；
- `documents` 与 `document_prefixes` 至少提供一种，限定该接口可公开的 Package-owned canonical Entry；
- 保持结构向后兼容时 Package 可以更新 release version 而不改变 interface revision；
- 删除、重命名或改变必需成员类型时必须提升 interface revision；
- Kirin Tor 校验身份、唯一性与 prefix，不理解接口的游戏含义。

Package release 仍以 source、release version、resolved commit 和 content SHA-256 锁定。Interface revision 不代替 release identity。

### 6.3 Plugin 要求接口

建议下一代 Plugin manifest 使用严格 schema 2 / API 2：

```json
{
  "schema": 2,
  "id": "community.fictional-ui",
  "version": "2.0.0",
  "api": "2",
  "requires": {
    "kirin_feature": "0.5",
    "interfaces": [
      {"id": "fictional.theorycraft-model", "revision": 2},
      {"id": "fictional.character-build", "revision": 1}
    ]
  }
}
```

激活前，宿主必须把每项要求解析为：

- `satisfied`：存在唯一兼容 provider；
- `missing`：未安装；
- `revision-mismatch`：接口存在但 revision 不同；
- `ambiguous`：锁定图中出现多个 provider；
- `invalid-provider`：Package 未通过普通加载或接口范围校验；
- `kirin-incompatible`：当前 feature line 不匹配。

不满足要求的 Plugin 保留在管理界面，但不得挂载可执行 surface。宿主应展示具体 provider、锁定版本和摘要，不应自动安装或更新 Package。

### 6.4 清洁版本边界

可规模化协议已经在仓库内以 Package manifest schema 2、Plugin manifest schema 2 / API 2
清洁切换，没有保留双语义运行时。正式发布前仍必须检查是否已经存在外部 v1 Plugin：

- 若没有外部使用者，直接迁移仓库示例并删除 v1 执行路径；
- 若已有外部使用者，保留最后一个支持 v1 的 Kirin Tor release，并提供 manifest/SDK 迁移说明；
- 不通过“遇到未知字段就忽略”或自动猜测旧 payload 来兼容。

## 7. Model Catalog 2

### 7.1 启动上下文

Plugin 激活时不再接收可能很大的完整 index。宿主只发送：

```json
{
  "catalog": {
    "revision": "opaque-workspace-revision",
    "counts": {"entry": 1200, "output": 8400, "input": 3100},
    "interfaces": [
      {
        "id": "fictional.theorycraft-model",
        "revision": 2,
        "provider": {
          "package": "community.fictional-models",
          "version": "3.4.1",
          "content_sha256": "..."
        }
      }
    ]
  }
}
```

此 summary 必须有固定大小上限；大型条目通过查询获得。

### 7.2 查询动作

API 2 至少提供：

- `model.query`：分页列举 descriptor；
- `model.get`：按 canonical ID 获取一个 descriptor；
- `model.dependencies`：读取直接或有限深度依赖；
- `model.document`：获取一个已验证文档的结构化投影，不包含原始源码；
- `model.capabilities`：读取宿主当前操作、limits 与 descriptor kinds。

`model.query` 请求：

```json
{
  "revision": "opaque-workspace-revision",
  "kind": ["object", "output"],
  "interface": "fictional.theorycraft-model",
  "owner": "fictional_actions",
  "prefix": "fictional_actions.",
  "cursor": null,
  "limit": 100
}
```

规则：

- `limit` 默认 50，最大 100；
- 顺序必须按 canonical ID 稳定；
- cursor 绑定 query 参数与 workspace revision，Plugin 不解释其内容；
- revision 改变时返回 `stale_revision`，不得混合两个模型 revision 的分页结果；
- 所有 filter 都在宿主白名单中，不接受任意表达式或正则；
- 每个响应继续受统一消息大小限制；
- `model.read` 的“截断但不可继续”行为由分页查询替代。

### 7.3 公共 descriptor

所有 descriptor 必须共享：

```json
{
  "id": "fictional_actions.arcane_blast",
  "kind": "object",
  "owner_id": "fictional_actions",
  "label": "Arcane Blast",
  "contract": {"type": "fictional_semantics.ability"},
  "dependencies": ["fictional_character.spell_power"],
  "origin": {
    "scope": "package",
    "package": "community.fictional-models",
    "version": "3.4.1",
    "source": "github:community/fictional-models",
    "resolved": "commit-sha",
    "content_sha256": "..."
  },
  "source_location": {
    "document": "fictional_actions",
    "line": 42,
    "column": 1
  },
  "payload": {}
}
```

`payload` 按 kind 使用严格 schema。首个完整版本应覆盖：

- entry；
- dimension、unit、domain；
- type 与 type field；
- object 与嵌套 object field；
- input、field、function、output、group、preset；
- table、distribution；
- Process、Process input/state/event/action/observe；
- Scenario、instance、variant、policy、decision、measure、objective；
- Analysis 与 Analysis chart；
- static chart；
- source/evidence block。

Catalog 暴露已解析结构与普通来源坐标，不暴露 Python 对象、SymPy 实例、任意 AST 执行能力或 Package 原始文件路径。

### 7.4 来源与事实证据必须分开

Descriptor 的 `origin` 只证明“这个声明来自哪一个锁定 Package release”，不证明“这个系数与游戏官方数据一致”。平台必须保留这一区分：

- Package source、version、resolved commit 和 content digest 属于发布来源；
- `.kirin` `source` block、citation、location、verified_at 和 game version 属于事实证据；
- Plugin 的说明或颜色编码不构成事实证据；
- Catalog 应当完整列出接口范围内的 source/evidence blocks；
- 具体游戏接口应说明哪些对象字段或声明对应哪些 evidence ID；
- 不得根据文件邻近、命名相似或同一 Package 自动推断某条 evidence 支持某个数值。

若要让宿主对单个字段显示“有来源支持”，必须另立一个游戏中立的 declaration-to-evidence 引用语法 RFC，并让 parser、renderer、Catalog 与 validation 共同实现。该语法不应在本平台提案中被暗中假定为已经存在。

### 7.5 游戏语义如何保留在 Package

Core 不提供 `ability`、`talent` 或 `item` kind。Package 使用普通 `type` 与 `object` 建模这些概念，并通过模型接口约定 canonical type ID。Plugin 查询接口范围内、指定 type contract 的 object。

例如，`fictional.theorycraft-model@2` 可以约定：

- `fictional_semantics.ability` 是技能对象类型；
- `fictional_semantics.talent` 是天赋对象类型；
- `fictional_builds.default` 是推荐的用户 build 模板。

这些约定属于该接口的 Package 文档，不成为 Kirin Tor 内置词汇。

## 8. Operation Service 2

### 8.1 单一操作注册表

每个公开操作必须由一个 backend capability descriptor 定义：

- action name；
- required permission；
- request schema；
- result schema；
- hard limits；
- timeout class；
- sync 或 job 执行方式；
- 是否允许 unsaved overlay；
- 是否允许 durable run record 或 artifact。

Plugin host、CLI adapter、Web adapter、SDK types、文档和测试应从同一注册表或同一生成源取得操作名与 limits。不得再次出现前端 64、backend 8 的分叉。

### 8.2 初始操作集合

| Action | 目标 | 建议边界 |
| --- | --- | --- |
| `evaluate` | 一个公开 output | 同当前精确求值 |
| `evaluate-many` | 同一 preset/override 下多个 outputs | 最多 64 个，单次共享 workspace/parameter preparation |
| `explain` | 一个公开 output | 返回公式、条件、依赖、单位与来源 |
| `compare` | 一个 output 的多个方案 | 初始沿用 backend 已证明的 8 个上限，除非基准与实现同时提升 |
| `scan` | 一个输入轴、多个 outputs | 总点数与曲线数均受注册表约束 |
| `grid` | 两个输入轴、一个 output | 总点数不超过 core limit |
| `solve` | 单 output 单变量 | 只允许其声明依赖输入 |
| `analyze` | 一个具名 Process Analysis | 长任务 job；保留 proof 与 trace 语义 |

不提供 `operation.execute(name, payload)` 之类任意转发入口。

### 8.3 统一请求与结果 envelope

请求必须带 Plugin 已知的 workspace revision：

```json
{
  "id": "plugin-request-id",
  "action": "evaluate-many",
  "revision": "opaque-workspace-revision",
  "payload": {
    "targets": ["fictional_damage.total", "fictional_damage.per_target"],
    "preset": "user_builds.current",
    "overrides": {"fictional_character.crit": "25%"}
  }
}
```

成功结果至少保留：

- workspace revision；
- operation ID 和 canonical targets；
- exact、approximate、unit、display contract；
- 实际应用的 preset 与临时 overrides；
- dependency IDs 与 Package origins；
- warnings；
- 对优化结果的 proof level、solver controls、bounds 与是否耗尽预算。

Plugin 不得选择 backend precision、进程 timeout、资源 limits、artifact path 或 run-record ID。

### 8.4 Job、进度与取消

预计超过普通交互时限的操作必须返回 job handle：

```json
{
  "status": "accepted",
  "job_id": "opaque-job-id",
  "operation": "analyze",
  "stage": "queued"
}
```

Plugin API 提供：

- `job.status`：只查询由该 contribution 创建的 job；
- `job.cancel`：请求宿主终止对应 job；
- 宿主推送 `job-update`：queued、running、completed、failed、cancelled；
- 稳定 stage 名称，不伪造百分比；
- frame 卸载时由宿主策略决定继续或取消，但行为必须写入 capability descriptor。

全局 Workbench 仍显示并可取消所有当前 job。Plugin 不能查看其他 Plugin 的请求内容。

## 9. 呈现可信度

### 9.1 两类 surface

目标平台应明确区分：

1. **Executable surface**：当前 sandbox iframe 的后继；可提供完全自定义游戏视觉，但其文字和数值是第三方呈现；
2. **Host-verified surface**：Plugin 提交声明式布局与 canonical binding，由 Kirin Tor 宿主直接渲染值、单位、proof 和 provenance。

Executable surface 可以调用 Core，但宿主不能证明它没有忽略或篡改结果。因此不得仅凭“插件已批准”给 iframe 中的数字加“由 Kirin Tor 验证”标签。

### 9.2 Host-verified result slot

首个可信呈现能力不必立即发明完整 UI DSL。可以先提供 host-owned result slot：

- Plugin 发起操作后得到不可伪造的 host result handle；
- Plugin 请求把该 handle 呈现在 iframe 邻接的宿主区域；
- 宿主负责数字、单位、精确/近似状态、警告、proof 与来源入口；
- Plugin 只能提供短标题和排序建议，不能替换值；
- workspace revision 变化后 slot 明确标记 stale 或清除。

只有 host-owned slot 使用“核心计算”标识。iframe 内部仍标为“第三方 Plugin 呈现”。

### 9.3 后续声明式视图

若 reference Plugin 证明 result slot 不足，再单独设计受限的 declarative renderer：表格、表单、选择器、树、卡片、绑定列表和 host result，不接受任意表达式、脚本或 CSS。它不应阻塞 Model Catalog、SDK 和 operation contract 的先行实施。

## 10. Plugin 状态模型

### 10.1 Ephemeral session state

iframe 自身内存用于当前挂载期间的 hover、展开、临时输入和未提交选择。卸载即可丢失，不是工作区状态。

### 10.2 User-local preferences

新增可选 `storage.preferences` 权限，提供按本地用户、workspace、Plugin ID 隔离的键值存储：

- 每个 Plugin 最多 64 KiB；
- 只接受 JSON-safe 值和有界 key；
- 不随 Package、workspace source、run record 或 artifact 传播；
- 不得保存凭据、源码全文或计算模型；
- Plugin 更新后保留还是清除必须由 manifest storage schema revision 决定；
- 设置界面提供单 Plugin 清除入口；
- Safe Mode 不读取或注入 Plugin preference。

颜色模式、locale、reduced motion、可用尺寸等只读 host context 不需要持久化权限。

### 10.3 Model state

任何影响计算的 build、装备选择、天赋、输入默认值或场景设置必须成为：

- 一次 operation 的显式 temporary override；或
- 工作区中的 `.kirin` preset/object/scenario 草稿。

它们不得只存在 Plugin preference 中。

## 11. Authoring Proposal 2

现有单文档全文提案证明了 review 边界。可规模化版本应扩展为有界 proposal transaction：

```json
{
  "revision": "opaque-workspace-revision",
  "title": "保存当前角色 Build",
  "description": "从界面选择生成一个本地 preset 文档。",
  "changes": [
    {
      "kind": "create-from-template",
      "template": "community.fictional-models:build",
      "document_id": "my_arcane_build",
      "bindings": {"crit": "25%"}
    },
    {
      "kind": "replace-document",
      "key": "entries/my_notes.kirin",
      "base_sha256": "...",
      "text": "..."
    }
  ]
}
```

首版规则：

- 最多 16 个待审 proposal；
- 每个 proposal 最多 16 个文档变化，总 UTF-8 字节数有统一上限；
- 只允许本地 `entries/**/*.kirin`；
- 不得编辑 Package source；
- create 必须来自已安装 Package 或内置模板，或提交完整合法新文档；
- replace 必须匹配当前 buffer revision；
- 首版不支持删除与移动；
- 宿主在入队和接受时分别验证完整候选 workspace；
- review 展示每个文件的 base/candidate、Plugin identity/version/digest 和校验结果；
- 用户只能整体接受或整体拒绝，避免半套模型；
- 接受仅生成普通 dirty buffers；Save All 继续承担磁盘哈希检查和原子写入；
- proposal 本身不进入 recovery，接受后的 dirty buffers 才进入普通 recovery。

应优先提供“从 Package 模板创建本地 build/preset”而不是让 Plugin 拼接 Kirin 语法字符串。结构化模板 binding 由宿主渲染成 source，可减少 Plugin 对语法版本的耦合。

## 12. Plugin SDK 与作者工具

### 12.1 官方 SDK

仓库应提供一个小型、无运行时依赖的 TypeScript SDK，并发布编译后的静态 ESM 文件供 Plugin vendoring：

```ts
const kirin = createKirinPlugin({ api: 2 });

const activation = await kirin.ready();
const abilities = await kirin.model.query({
  interface: "fictional.theorycraft-model",
  kind: ["object"],
  limit: 100,
});
const result = await kirin.operations.evaluateMany({
  targets: ["fictional_damage.total", "fictional_damage.per_target"],
  overrides: { "fictional_character.crit": "25%" },
});
```

SDK 必须负责：

- protocol/api 握手；
- request ID 与 Promise 关联；
- runtime payload validation；
- context revision 更新；
- stable error class/code；
- job update、取消和 frame disposal；
- 分页迭代器；
- capability/permission 检查；
- 消息大小的预检查。

SDK 不得实现数学、Package resolution 或源码写入。

### 12.2 Schema artifacts

每个 release 应生成并版本化：

- Plugin manifest JSON Schema；
- activation/context/action/result JSON Schema；
- Catalog descriptor schemas；
- Operation capability descriptors；
- TypeScript types；
- error-code catalog；
- limits catalog。

这些产物必须来自同一协议定义源，避免文档、前端和 backend 手工漂移。

### 12.3 CLI

建议增加：

```text
kt plugin new DIRECTORY --id ID
kt plugin check [DIRECTORY]
kt plugin test [DIRECTORY] --workspace WORKSPACE
kt plugin bundle [DIRECTORY]
```

- `new` 生成最小无框架示例、manifest、README、license placeholder 和测试；
- `check` 离线校验 manifest、静态资产、权限、接口要求和内容摘要；
- `test` 使用无凭据 disposable workspace 运行协议 fixtures，不批准或安装到真实工作区；
- `bundle` 生成确定性静态归档和 canonical digest，不发布；
- 任何命令都不得执行 Plugin build script。作者若使用 npm/Vite，应在调用 Kirin CLI 前自行构建静态资产。

## 13. 安装、发现与发布

### 13.1 首个稳定平台仍以本地安装为准

API 2 的正确顺序是先完成协议与 conformance，再增加远程安装。社区 discovery 可以继续只读展示仓库。首个稳定里程碑不应同时承担签名基础设施和 marketplace 治理。

### 13.2 后续远程安装的必要条件

若增加远程 Plugin 安装，必须至少具备：

- exact release tag/commit resolution；
- canonical content digest；
- 静态 bundle 结构与媒体类型检查；
- 权限与所需接口的安装前展示；
- 按 digest 的本地用户批准；
- 更新后重新批准变化的 digest 或权限；
- 离线 verify 与 restore；
- Safe Mode 在损坏控制文件下仍能启动；
- 不执行仓库 build、postinstall、Git hook 或 release script。

GitHub topic 仍只是自我声明，不是安全或质量认证。

## 14. 安全与资源边界

以下限制是目标平台的最低要求：

- iframe 保持 `sandbox="allow-scripts"`，不加入 `allow-same-origin`；
- Plugin response 保持 `connect-src 'none'`、禁表单、禁 popup、禁宿主导航；
- Plugin 不持有 Workbench session token；
- 所有 action 必须验证 event source、API version、permission、payload schema、revision 与 canonical identity；
- 所有列表分页，所有字符串、数组、图、点数、任务和消息有硬上限；
- catalog cursor、result handle、job ID 都是不可解释、会话范围的 opaque token；
- Plugin 只能访问自己创建的 job、result slot 和 storage namespace；
- Package 文档始终只读；
- draft/proposal 不得绕过完整 workspace validation；
- Safe Mode 不挂载 frame、不服务 Plugin asset、不注入 Plugin context；
- 宿主必须始终保留关闭、禁用和恢复到默认 Profile 的路径；
- 资源耗尽、超时和取消返回稳定失败，不伪造部分完成结果。

浏览器 iframe 仍不是完整的 CPU/内存进程隔离。稳定平台必须继续明确这一限制，不能把 CSP 描述为对恶意 Plugin 的完全沙箱。

## 15. 错误合同

API 2 使用稳定 code，文字仅用于显示。最低错误集合：

| Code | 含义 |
| --- | --- |
| `permission_denied` | contribution 未声明所需权限 |
| `unsupported_capability` | 当前宿主没有该能力 |
| `invalid_request` | payload 不符合 schema |
| `unknown_identity` | canonical ID 不存在 |
| `interface_unavailable` | required model interface 不可用 |
| `stale_revision` | catalog 或 operation 使用了旧 workspace revision |
| `limit_exceeded` | 命中声明的硬上限 |
| `result_too_large` |结果无法进入消息 envelope |
| `workspace_invalid` |当前 overlay 不能执行目标操作 |
| `proposal_invalid` |候选 workspace 校验失败 |
| `proposal_stale` | proposal baseline 已改变 |
| `job_cancelled` | operation 被明确取消 |
| `operation_failed` |核心返回已结构化的计算失败 |
| `plugin_disabled` | frame 所属 Plugin 已停用或不再批准 |

错误可以携带有界 diagnostics、source location 和 retry guidance，但不得泄露宿主路径、凭据、其他 Plugin 请求或未授权源码。

## 16. Reference stack

在声称平台可用前，仓库必须拥有一个完全虚构、但结构完整的参考栈：

```text
examples/platform/
  fictional-model-package/
    kirin.package.toml
    entries/
      semantics.kirin
      data.kirin
      calculations.kirin
      process.kirin
      presets.kirin
    templates/entries/build.kirin
  fictional-game-plugin/
    kirin.plugin.json
    web/
    tests/
  consumer-workspace/
    kirin.workspace
    kirin.packages.toml
    kirin.lock
    kirin.plugins.toml
    kirin.plugins.lock
    entries/user_build.kirin
```

Reference Plugin 必须只通过公开 SDK、Catalog 与 Operation Service 工作，不导入 Kirin Tor 内部模块，不复制 Package 公式。它至少展示：

- 接口兼容性状态；
- 分页技能/对象目录；
- 来源与版本；
- 多输出角色结果；
- 参数比较与扫描；
- 一个具名 Process Analysis job；
- host-verified result slot；
- 从 Package template 生成本地 build proposal；
- proposal 审查、接受和 Save All 边界；
- missing/mismatched interface 的恢复体验；
- Safe Mode。

真实游戏 Package 或 Plugin 不应承担首个协议验收 fixture 的角色。

## 17. Conformance 与验证矩阵

### 17.1 静态协议

- manifest schema 接受全部合法字段并拒绝未知字段；
- API、feature line、interface revision 和 Package provider 状态逐项测试；
- JSON Schema、TypeScript types、Python validators 和文档示例来自同一生成源；
- 权限缺失必须返回 `permission_denied`；
- 不存在通用 operation forward、source.write、filesystem 或 network 权限；
- bundle digest 覆盖全部静态资产。

### 17.2 Catalog

- 超过 240 项的 fixture 可以完整分页读取，无遗漏、重复或顺序漂移；
- cursor 与 revision 绑定；
- workspace 改变后旧 cursor 返回 `stale_revision`；
- 每种 descriptor kind 有成功与失败 fixture；
- local 与 Package origin、source location、interface scope 正确；
- Package 原始本地缓存路径不进入响应；
- 大响应被分页或返回 `result_too_large`，不截断成看似完整的数据。

### 17.3 Operations

- 每个 Plugin action 直接覆盖 backend service limit；
- 前端、SDK、文档和 backend 的限制值一致；
- `evaluate-many` 与逐个 evaluate 数学等价，并共享同一 revision/overrides；
- 非法 target/input/preset/variable 被宿主拒绝；
- exact、unit、proof、provenance 不因 Plugin adapter 丢失；
- 长 Analysis 可以报告 stage、取消并终止进程树；
- 取消、超时和资源耗尽不留下 run record 或 artifact。

### 17.4 Proposal

- Plugin 不能直接改变 buffer 或磁盘；
- invalid、stale、oversized、read-only 和 queue-overflow proposal 被拒绝；
- 多文档候选只整体接受；
- 接受后只是 dirty buffers；
- Save All 继续检测外部磁盘冲突并原子写入；
- proposal 不进入 recovery，接受后的草稿进入；
- Plugin 禁用、reload 与 Safe Mode 的 queue 行为明确测试。

### 17.5 浏览器与安全

- Chromium 与 WebKit 覆盖 reference stack 的主要流程；
- CSP、sandbox、session-token、Host/Origin 和 asset digest 回归；
- iframe 不能访问 host DOM、API token、网络、local Package path 或其他 Plugin storage；
- 错误或崩溃的 Plugin 不移除 generic projection、Plugin manager 或 Safe Mode；
- 键盘、screen-reader name、focus、reduced motion 和最小支持宽度通过宿主 surface 检查；
- iframe 自有内容的可访问性责任与宿主控制分别报告。

### 17.6 性能

实施前为 100、1,000 和最大允许文档规模建立可重复 benchmark。稳定门槛不先凭空指定毫秒数，但必须满足：

- 启动消息不随完整 catalog 线性膨胀；
- catalog 查询受 limit 与消息大小约束；
- `evaluate-many` 不重复加载同一 workspace；
- 长任务不阻塞主 UI 线程；
- benchmark 相对已记录 baseline 的退化需要显式审查；
- 触发硬限制时快速失败，不继续无界分配。

## 18. 实施阶段与退出条件

### Phase 0：收敛当前 v1

工作：

- 修正 compare 8/64 不一致；
- 为现有 action 建立一张 backend-to-protocol conformance matrix；
- 明确现有模型索引的截断与 provenance 缺失；
- 冻结本提案实施前的行为 baseline。

退出条件：现行文档、前端检查和 backend limits 完全一致；没有未测试的公开 action。

当前状态：已完成。最初的 v1 backend capability registry 是权限、operation 映射和 limits 的单一
运行时真源；bootstrap 与 frame activation 都发布这份 descriptor；Workbench adapter 不再复制
桥接上限；compare 统一为 8；Python conformance 测试逐项核对 registry 与 adapter 分支，参考
Plugin 的 Chromium/WebKit 验收路径执行当时全部九个公开 action。该基线随后通过 Phase 1
清洁迁移到 API 2；旧的 240 项启动快照没有作为兼容层保留。

### Phase 1：Package interface 与 Catalog 2

工作：

- 实现 Package interface provider 合同；
- 实现 Plugin required-interface 激活检查；
- 实现 revision-bound `model.query/get/document/dependencies/capabilities`；
- 补齐所有 descriptor kinds 与 origin envelope。

退出条件：reference Plugin 可以在超过 240 项的 Package 中完整发现模型，且不读取 raw source。

当前状态：已完成。Package 可以声明 namespace-scoped interface ID、精确 revision 与文档范围，
重复 provider 会使解析图失败；Plugin 在激活前取得 `satisfied`、`missing`、
`revision-mismatch`、`ambiguous`、`invalid-provider` 或 `kirin-incompatible` 结果。Catalog
summary 固定有界，`model.query/get/document/dependencies/capabilities` 全部绑定 workspace
revision；公共 descriptor 覆盖本阶段列出的种类并统一携带 origin、source location、contract、
dependencies、interface membership 与 payload。275 Entry 的 Package fixture 已通过三页查询
完整枚举，没有遗漏、重复、本地 Package 路径或 raw `.kirin` source 泄露。

### Phase 2：Operation Service 2 与 SDK

工作：

- 将 v2 capability registry 扩展为 Operation Service 2 的完整 registry；
- 加入 `evaluate-many`；
- 实现 job status/update/cancel；
- 生成 schemas、types、limits 和 TypeScript SDK；
- 增加 `kt plugin new/check/test/bundle`。

退出条件：reference Plugin 不包含手写协议代码或复制的数学公式；所有 action 通过 conformance matrix。

### Phase 3：可信呈现、storage 与 Proposal 2

工作：

- 实现 host-owned result slot；
- 实现有额度的 user-local preferences；
- 实现 create-from-template 与多文档 proposal transaction；
- 完善审查、stale、recovery 与 Save All 交互。

退出条件：用户可以完全在游戏视觉层选择一个 build、得到宿主计算结果、保存为可审查 `.kirin` 草稿，并能区分 host-verified 与第三方呈现。

### Phase 4：发布与发现

工作：

- 完成 reference stack 文档；
- 根据真实需求决定是否提供远程 exact-release 安装；
- 补齐更新批准、离线 restore/verify 和社区质量提示；
- 进行真实第三方作者试用。

退出条件：至少一个不依赖内部知识的外部作者可以仅凭公开文档和 SDK 完成 Package + Plugin 集成；这项结果必须作为人类验收记录，而不是由测试数量替代。

## 19. 完成定义

只有同时满足下列条件，Kirin Tor 才能声称拥有“完整、稳定、可规模化的游戏插件平台”：

1. Core 发布物中没有游戏专用数据、类型或分支；
2. Package interface 能稳定描述 Plugin 消费的模型合同；
3. 大型 catalog 可完整分页查询并绑定 revision；
4. Plugin 可以批量求值、扫描、求解和运行有界 Analysis，而不复制数学；
5. 所有结果保留 exact/unit/proof/provenance；
6. 长任务可观察、可取消且资源有界；
7. Plugin 与 Package 的不兼容在挂载 frame 前被解释；
8. SDK、schema、limits、实现和文档由同一合同保持一致；
9. 可执行呈现与 host-verified 呈现明确区分；
10. 用户模型状态只能通过 temporary override 或 `.kirin` 草稿表达；
11. Proposal 不能绕过 review、validation、recovery 与 Save All；
12. Safe Mode、批准、digest 与 iframe 隔离在完整浏览器流程中通过；
13. reference stack 覆盖大型查询、计算、Analysis、提案和恢复；
14. 外部 Plugin 作者完成一次不依赖仓库内部知识的人类验收。

## 20. 建议立即接受的决策

本提案建议先接受以下方向，再开始实现：

1. **继续维持三层结构**：Core / Package / Plugin，不新增第四种游戏逻辑载体；
2. **以模型接口而不是 Package 名称形成 Plugin 数据合同**；
3. **以分页 Catalog 取代完整 index 注入**；
4. **建立单一 operation capability registry**；
5. **新增 `evaluate-many`，但不开放任意 backend operation**；
6. **并行保留 executable iframe 与 host-verified result slot**；
7. **把可持久计算状态写入 `.kirin`，Plugin storage 只存 UI 偏好**；
8. **优先结构化 template proposal，不鼓励 Plugin 拼接源码**；
9. **先完成 API 2 与 reference stack，再讨论远程 Plugin 安装**；
10. **若没有外部 v1 使用者，采用清洁切换而不是长期兼容层**。

这些决策一旦接受，应拆成独立的实施规范和里程碑。本文本身不授权修改 Package schema、Plugin API 或 `.kirin` 语言。

## 21. 接受后的规范拆分

本提案不应直接膨胀成唯一的永久规范。方向获得接受后，按下列权威边界拆分：

| 后续规范 | 负责内容 | 不负责内容 |
| --- | --- | --- |
| `package-system-v2.md` | interface provider、manifest、锁定图和兼容状态 | Plugin 消息与 UI |
| `model-catalog-v2.md` | revision、descriptor、分页、query/get/dependencies | 数学求值语义 |
| `operation-capabilities-v2.md` | action registry、limits、result envelope、job | 游戏模型含义 |
| `workbench-plugin-system-v2.md` | manifest、权限、激活、sandbox、surface、storage | Package 数据正确性 |
| `plugin-sdk.md` | TypeScript API、生命周期、错误和作者用法 | backend 实现 |
| `plugin-conformance.md` | fixture、测试矩阵、浏览器与安全验收 | 人工可用性结论 |
| `host-verified-presentation.md` | result handle、宿主呈现与信任标签 | 任意游戏视觉设计 |
| `authoring-proposal-v2.md` | template、候选事务、review、recovery 与 Save All | 直接源码写权限 |

每份规范必须引用同一个 machine-readable protocol source，而不是复制 action、permission、error code 或 limit 列表。只有相应规范、实现和 conformance fixture 同时完成后，README 才能把该能力从“提案”改为“已实现”。
