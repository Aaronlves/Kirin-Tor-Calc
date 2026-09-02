# Kirin Tor

Kirin Tor 是一个游戏中立、文件驱动的结构化数学工作台，面向需要长期维护数据、公式、参数方案和图表的攻略与理论计算作者。

工作区只有一种可编辑权威：`entries/**/*.kirin`。结果、图表、公式展开、诊断、关系图、索引、恢复缓存和导出文件都是源码的投影或产物，不会形成第二套计算定义。具体游戏的量纲、公式和数据由工作区或独立社区 Package 提供；Kirin Tor 核心不内置游戏、职业、技能或版本数据。

Kirin Tor 不是脚本式战斗模拟器。内核只执行 source 明确声明且受 horizon、事件、决策、分支、实体和
集合容量约束的 Process 事件场景；它不会补全完整 APL、Boss 时间轴或未声明规则，也不做隐式抽样。
Process Analysis 已接入 CLI、浏览器工作台实时投影、多图导出和可重放运行记录。

## 安装

需要 Python 3.9 或更新版本。预发布构建可从 [GitHub Releases](https://github.com/Aaronlves/Kirin-Tor-Calc/releases) 下载：

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -U pip
python -m pip install /path/to/kirin_tor_cli-VERSION-py3-none-any.whl
kt version
```

也可以安装当前源码：

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -U pip
python -m pip install .
kt --help
```

开发安装：

```bash
python -m pip install -e '.[dev]'
pytest
```

## 快速开始

创建并打开一个空的游戏中立工作区：

```bash
kt init my-math
cd my-math
kt web
```

浏览器工作台会显示三份只读教程：基础公式、参数方案与比较、扫描与图表。教程不是工作区文档；只有主动复制后，才会以普通未保存草稿进入校验和保存流程。

也可以从命令行创建文档：

```bash
kt new entry basic_model --template model
```

一份最小而完整的 Kirin Tor source 如下：

```text
@kirin 2
@entry basic_model "基础公式"

input unit_price "单价": number[dimensionless] = 12 in 0..*
input quantity "数量": number[dimensionless] = 5 in 0..100 integer
input discount "折扣": probability = 10%

field subtotal "小计": dimensionless = unit_price * quantity

output total "折后总价": dimensionless = subtotal * (1 - discount)
display total = number digits 2
```

保存为 `entries/basic_model.kirin` 后可以校验和计算：

```bash
kt check
kt eval basic_model.total
```

结果为精确值 `54`。十进制先转换为精确有理数，不经过二进制浮点近似。

## 浏览器工作台

`kt web [WORKSPACE|SOURCE.kirin]` 启动只监听本机回环地址的浏览器工作台。服务使用随机会话令牌，不接受外部 Host、跨站 Origin 或远程监听；停止终端进程即可关闭，不存在后台守护程序或云端账户状态。

工作台的主要能力包括：

- 在中央 CodeMirror 编辑器中完成全部源码编辑；`Ctrl+Space` 提供 Kirin Tor 补全和中文结构片段。
- 同时保留多个未保存草稿，按完整工作区校验，并通过 Save All 原子写入。
- 自动派生只读结果、静态图表、Process Analysis 多图、公式、诊断和局部关系；检查器不提供临时计算参数或参数方案填写字段。
- 提供定义跳转、引用查找、符号大纲、签名提示、安全重命名、查找替换和安全空白格式化。
- 提供工作区全文搜索、草稿式批量替换、保存前变更审查、只读 Git 摘要和外部冲突三方合并。
- 支持文档路径移动、复制为新草稿，以及依赖安全的可恢复删除；这些文件操作不会改写源码中的 `@entry` ID 或数学语义。
- 从已校验引用生成文档与成员关系图，并为图表和画布提供键盘可读的数据列表。
- 通过独立本地进程执行长操作，显示真实阶段并允许取消；数学超时仍是另一层独立限制。

右侧检查器的结果使用源码默认值。需要改变默认预览时应编辑 `.kirin` 输入默认值；需要重复使用的组合应写成命名 `presets`。变换、求导、求解、扫描和网格目前使用相应 CLI 命令；多方案比较保留在共享计算服务层。这些高级操作没有在浏览器中复制成一组通用参数表单。

常用编辑快捷键：

| 操作 | 快捷键 |
| --- | --- |
| 保存全部 | `Mod+S` |
| 补全 | `Ctrl+Space` |
| 查找/替换 | `Mod+F` |
| 跳到行 | `Mod+G` |
| 文档符号大纲 | `Mod+Shift+O` |
| 安全格式化 | `Mod+Shift+F` |
| 转到定义 | `F12` 或 `Mod+单击` |
| 查看定义与引用 | `Shift+F12` |
| 安全重命名 | `F2` |
| 工作区快速打开 | `Mod+K` 或 `Mod+P` |

完整交互与权威边界见[浏览器工作台规范](docs/web-workbench.md)。

## 语言和数学能力

Kirin Tor source v2 使用一个 `entry` 文档模型和一致的逐项声明语法。正式 ID 保持 ASCII；中文别名只在声明它的条目中参与公式，显示标签只影响界面、解释和图表。跨文档引用、CLI 参数、运行记录和 Package 导出继续使用稳定的正式身份。

当前内核支持：

- 精确整数、有理数、十进制和科学计数法；
- 数值与布尔输入、范围、整数限制、有限允许值和组合约束；
- 用户声明的量纲、精确比例单位和可复用值域；
- 字段、函数、输出、分组、参数方案、显示格式和版本化查表；
- 封闭的可复用类型、具名对象和静态多层属性访问；
- 有界 Process 状态、精确时间、事件 phase、连续 flow、动作 guard、冷却/充能等作者定义组件与固定策略；
- 条件、分段、有限求和与连乘；
- 有限离散分布、显式独立组合、条件化和有限重复；
- Process 事件链形式的有界迭代，以及有限随机转移的 `reach` / `steady` / `cycle` 分析；
- 化简、展开、因式分解、求导、单变量求解和最多八个变量的有限符号联立求解；
- 一维扫描、双输入网格、SVG/PNG/CSV 图表以及可重放运行记录。

完整语法写法见 [Kirin Tor source syntax v2](docs/kirin-syntax.md)；数学语义、安全边界和固定限制见[结构模型、表达式与安全边界](docs/schema-and-expressions.md)。

## 社区 Package

社区 Package 是独立维护、只含数据的 GitHub 仓库或本地开发目录。Kirin Tor 不执行其中的 Python、安装脚本、Git hook 或其他代码。

公开仓库可添加 GitHub topic `kirin-tor-package`，从工作台的只读发现抽屉中被找到。Topic 只是社区自声明；发现不会安装内容，安装仍需用户明确指定来源与精确版本。

创建并检查 Package：

```bash
kt package new my-community-package \
  --name community.example \
  --namespace community_example
kt package check my-community-package
```

安装精确 GitHub 版本或本地不可变快照：

```bash
cd my-math
kt package add example github:OWNER/REPOSITORY 1.0.0
kt package add-path local_example ../my-community-package
kt package list
kt package verify
```

`kirin.packages.toml` 记录用户请求的直接依赖，`kirin.lock` 锁定完整依赖图、Git commit 和内容摘要，`.kirin/packages/` 是可删除并显式恢复的只读缓存。普通工作区加载不会隐式联网。

完整协议见 [Kirin Tor community package protocol v1](docs/package-system-v1.md)。

## Workbench Extension Plugins

Workbench Plugin 可以为验证后的文档增加游戏化呈现器，也可以注册顶层页面、工作区工具、声明式命令和布局 Profile。插件不会改变 Kirin Tor 语法或数学结果；`.kirin`、验证器、Save All、Package 解析和运行记录仍由官方工作台控制。

公开仓库可添加 GitHub topic `kirin-tor-plugin`，从工作台的只读发现抽屉中被找到。只有当前协议可解析的 manifest 会显示；发现不会下载、安装、批准、启用或执行插件。

协议 v1 只安装作者明确选择的本地目录快照：

```bash
cd my-math
kt plugin add-path talents /path/to/talent-plugin
kt plugin list
kt plugin verify
kt web
```

插件清单、JavaScript、CSS、图片和其他静态文件全部进入内容摘要；安装时复制到 `.kirin/plugins/<SHA-256>/`，不会从可变源目录直接执行。`kirin.plugins.toml` 记录请求和启用状态，`kirin.plugins.lock` 锁定身份、版本与摘要，而可执行批准单独保存在工作区外的本机用户状态中。仅提交工作区配置不能批准陌生代码。

插件页面运行在没有同源权限的沙箱 iframe 中，只能接收清单权限允许的 JSON 投影。v1 可代理定位源码以及对既有合法 target 的有界求值；插件无法读取会话令牌、宿主 DOM、文件系统、环境变量或网络，也不能调用 Save All 和 Package 变更。出现问题时可停用插件，或使用：

```bash
kt web --safe-mode
```

源码仓库提供了不含真实游戏数据的 `examples/plugins/fictional-talent-tree`，展示文档呈现器、页面、工具、命令与 Profile。完整清单、权限、frame 消息协议和限制见 [Workbench Extension Plugin protocol v1](docs/workbench-plugin-system-v1.md)。

## 命令概览

```text
kt init DIRECTORY
kt web [WORKSPACE|SOURCE.kirin] [--safe-mode]
kt new entry ID [--template blank|data|model|semantics]
kt list
kt show ID
kt explain TARGET
kt check
kt eval TARGET [--preset ENTRY.PRESET] [--set ENTRY.INPUT=VALUE]
kt analyze ENTRY.ANALYSIS [--save-run ID] [--export-charts]
kt simplify TARGET
kt expand TARGET
kt factor TARGET
kt diff TARGET --var ENTRY.INPUT
kt solve TARGET --var ENTRY.INPUT --equals VALUE
kt solve-system --equation TARGET=VALUE --var ENTRY.INPUT
kt scan --x ENTRY.INPUT --range START:END --points N --y TARGET
kt grid --x ENTRY.INPUT --x-range START:END --x-points N \
  --y ENTRY.INPUT --y-range START:END --y-points N --result TARGET
kt plot [--config ENTRY_ID]
kt replay RUN_ID
kt package --help
kt plugin --help
```

各命令的完整参数以 `kt COMMAND --help` 为准。输出文件默认限制在工作区内且不覆盖已有文件；扩大路径权限或覆盖文件必须显式请求。保存运行记录前，参与计算的源码必须已经保存。

## 仓库示例

`examples/虚构技能工作区` 只存在于源码仓库，不进入 wheel 或 source distribution。其数据完全虚构，只用于验证常见游戏公式形状：

```bash
cd "examples/虚构技能工作区"
kt check
kt eval combo.total --preset presets.baseline
kt simplify combo.total --keep combo.crit
kt diff combo.total --var combo.crit
kt solve combo.total --var combo.crit --equals "3000 damage" --range "0:1"
kt plot --config combo --force
kt analyze rotation.replay_rotation
kt analyze rotation.prove_rotation
```

关键结果包括 `2750 damage`、`2200*combo.crit + 2200`、导数 `2200 damage`、解 `4/11`，以及固定 Process 策略的精确轨迹与边界周期证明。这些都是测试数据，不代表任何真实游戏技能。

## 能力边界

Kirin Tor 可以直接处理作者给出的有限公式、有限分布，以及有明确 phase 和 fuel 的有界 Process 场景。Process Analysis 已支持精确有限随机路径、作者声明的条件或固定序列策略，以及 `run`、`compare`、确定性有界 `optimize`、`reach`、有限状态 `steady` 和 `cycle`。它不会从技能说明自动推导完整战斗循环。当前没有：

- 优先级 APL、完整战斗时间线或随机采样；
- 一般连续时间搜索的全局证明或带误差界全局求解；
- 面向动态目标集合的公开建模承诺，或通用向量/矩阵语言；
- 无界连续或离散全局优化器；
- 积分、极限和完整通用数值根搜索。

常见理论计算的适用范围和不可直接表达的问题见[游戏机制计算能力边界](docs/game-mechanics-capability-audit.md)。

## 文档索引

| 文档 | 职责 |
| --- | --- |
| [Kirin Tor source syntax v2](docs/kirin-syntax.md) | 表面语法、类型化属性、多层访问与 Process 写法 |
| [结构模型、表达式与安全边界](docs/schema-and-expressions.md) | 解析后的数学语义、求值、安全和固定限制 |
| [有界 Process 模型](docs/bounded-process-model.md) | 动态机制统一语义、fuel、分析器与证明边界 |
| [有界 Process 纸面模型](docs/bounded-process-paper-models.md) | 六类机制的目标验证、Policy/Analysis 声明与当前可执行边界 |
| [浏览器工作台规范](docs/web-workbench.md) | 界面、编辑状态、保存、冲突与权威边界 |
| [Kirin Tor community package protocol v1](docs/package-system-v1.md) | Package manifest、解析、锁定、缓存和来源 |
| [Workbench Extension Plugin protocol v1](docs/workbench-plugin-system-v1.md) | 沙箱 UI 插件、贡献点、权限、批准、锁定和安全模式 |
| [游戏机制计算能力边界](docs/game-mechanics-capability-audit.md) | 已证明能力、需要外部等效模型的情况和明确非目标 |
| [Changelog](CHANGELOG.md) | 版本历史、破坏性变更和未发布修改 |

发生冲突时，以当前实现和测试为行为证据；表面语法以语法文档为准，数学与安全契约以结构模型文档为准，界面行为以工作台规范为准，Package 行为以 Package 协议为准。Changelog 只记录历史，不替代当前规范。
