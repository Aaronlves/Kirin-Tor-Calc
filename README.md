# Kirin Tor

Kirin Tor 是一个游戏中立、文件驱动的结构化数学工作台。它面向希望在同一份源码中保存数据、公式、参数方案和图表，而不想编写程序的攻略与理论计算作者。

公开文档只有一种：保存数据、公式、参数方案以及可选图表配置的 `entry`。角色、技能、天赋、目标衰减、组合公式以及其他游戏机制都由社区用普通条目表达；内核不会把任何游戏、职业或机制写死。Entry 和用户声明的数学语义统一使用 `.kirin` 源文件。社区可以在各自的 GitHub 仓库中发布只含数据的 Package，Kirin Tor 负责校验、锁定、组合和计算，而不取得具体游戏数据的权威。

这不是战斗模拟器：没有事件队列、随机战斗模拟、完整 APL、Boss 时间轴或自动循环优化器。

## 安装

需要 Python 3.9 或更新版本：

当前公开版本是预发布版 [`0.3.0rc1`](https://github.com/Aaronlves/Kirin-Tor-Calc/releases/tag/v0.3.0-rc.1)。从发布页下载通用 wheel 后安装：

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -U pip
python -m pip install ./kirin_tor_cli-0.3.0rc1-py3-none-any.whl
kt version
```

也可以从源码安装当前检出版本：

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -U pip
python -m pip install .
kt version
kt --help
```

开发安装：

```bash
python -m pip install -e '.[dev]'
pytest
```

`pyproject.toml` 安装命令入口 `kt`，因此激活对应虚拟环境后，可以在源码目录之外使用。

## Kirin 源文件与浏览器工作台

`kt new` 创建 `.kirin` 文档。Kirin 源文件使用 `//` 作者注释、`---` 长说明块、固定章节和缩进表达结构，不使用 Markdown：

```text
@kirin 1
@entry fictional_effect

// 虚构效果
// damage 由当前工作区或社区 Package 声明，不是内核内置游戏语义。

---
这段文字只用于说明技能。
---

inputs:
  crit "暴击率": probability = 0.25

fields:
  base_damage: damage = 1000

outputs:
  expected "期望伤害": damage = base_damage * (1 + crit)
```

在工作区内运行 `kt web` 会启动一个只监听本机回环地址的服务，并在默认浏览器打开图形工作台。也可以直接传工作区目录或源文件，不必先 `cd`：

```bash
kt web entries/fictional_effect.kirin
kt web /path/to/workspace
kt web /path/to/workspace --no-open
```

服务只接受带随机会话令牌的本地请求，拒绝外部 Host、跨站 Origin 和非回环监听；它不是需要部署或登录的云服务。关闭命令所在终端即可停止。

- **文档**是主入口。`.kirin` 文本始终是唯一权威；右侧按当前源码显示结果、可选图表、局部关系、诊断和公式。新建时可选内置模板、工作区自定义模板或 Package 随附的只读模板。模板只做一次源码展开，生成后不再继承模板。
- **关系图**从已校验公式生成文档级和成员级依赖网络；点击成员可查看直接公式并返回定义位置。文档右侧使用相同数据显示零层、直接或两层上下游。
- **语法参考**是应用内只读速查，通过左侧“参考”、工作区菜单或命令面板打开。它可以按中英文语法词搜索，覆盖文档、成员、别名、参数方案、查表、有限分布、递推、状态模型、数学语义和图表，并为每个主题提供经过当前校验器检查的完整示例。复制示例只写入剪贴板，不会修改当前文档。
- **全文搜索与替换**同时读取未保存草稿、本地源码和 Package 源码；替换会跳过只读 Package，只生成待审查草稿。**保存前变更审查**并排显示基线与当前草稿，并在 Git 工作区中提供只读提交与磁盘状态摘要。
- **记录**和 **Packages** 是工作区工具，通过顶栏菜单或命令面板打开，不占据常驻顶层导航。记录可重放含定义快照的不可变运行；Package 工具负责安装、更新、移除、恢复、离线验证和作者检查。
- 高级计算、扫描、求解和变换仍由浏览器与 CLI 共用的操作服务提供，但不会在缺少具体作者任务时被拆成永久顶层页面。

日常编辑只在中央 `.kirin` 编辑器中进行。顶部可以切换“仅编辑”“分栏”和“仅预览”，这个选择只改变布局，不改变源码、计算或保存状态。右侧检查器始终是只读投影：结果与公式按当前有效草稿和源码默认值自动派生，图表只在源码声明 `x/range/points/y` 时出现。检查器不提供临时参数、参数方案、超时等填写字段，也不要求点击“计算”或“解释”；要改变默认预览应修改源码中的输入默认值，需反复使用的实验组合应写成命名参数方案，并通过明确的计算流程调用。

浏览器关闭或刷新前会提示尚未保存的修改。计算可以使用完整且有效的未保存草稿；保存运行记录前必须先保存并校验参与计算的文档。长操作以可取消的独立本地作业运行，并继续受服务端超时约束。保存全部采用先校验、再原子替换；若文件在外部被修改，会拒绝覆盖，并在共同基线可验证时提供三方合并草稿。

界面采用现代、简洁、直角的深色工作台风格，操作名称保持为攻略作者熟悉的普通词汇。没有图表动画、参数表单、独立诊断页或窄屏终端兼容层。

工作台的状态、诊断类别和常见错误说明默认使用中文。诊断保留相对文件位置、行列、正式条目/字段以及英文技术详情；如果错误行包含常见全角符号，还会显示对应的半角替换建议。CLI 的稳定错误 code 和 `--json` 结构不受本地化影响。

文档编辑区按 `Ctrl+Space` 打开 Kirin 补全，在候选中用上下方向键移动、`Enter` 插入、`Esc` 关闭。补全会读取全部磁盘文档和内存草稿，可以按正式 ID、中文标签或中文别名检索输入、字段、函数、有限分布、有限递推、有限状态模型、输出、量纲、单位和值域。补全和符号索引允许草稿暂时不完整；只有完整工作区校验成功后，预览、保存和安全重命名才成立。

补全面板还提供中文触发的结构片段，包括“条目文档”“图表配置”“输入”“别名”“字段”“函数”“查表”“有限分布”“有限递推”“有限状态”“输出”“分组”“参数方案”“显示”“约束”“来源”“长说明”“分段”和“条件”。多行片段继承当前行缩进，并把光标放在下一处需要填写的位置。

常用编辑命令：

| 操作 | 快捷键 | 行为边界 |
| --- | --- | --- |
| 保存全部 | `Mod+S` | 完整校验后原子保存全部本地草稿 |
| 查找/替换 | `Mod+F` | 只修改当前内存草稿 |
| 跳到行 | `Mod+G` | 在当前文档定位 |
| 文档符号大纲 | `Mod+Shift+O` | 从当前容错符号索引定位 |
| 安全格式化 | `Mod+Shift+F` | 只规范安全空白，不重建 schema 或删除注释 |
| 转到定义 | `F12` 或 `Mod+单击` | 可跨文档打开定义位置 |
| 查看定义与引用 | `Shift+F12` | 包含直接引用和经局部别名产生的使用 |
| 安全重命名 | `F2` | 更新可写正式成员及引用，完整校验后保留为未保存草稿 |
| 工作区快速打开 | `Mod+K` 或 `Mod+P` | 搜索页面、命令、文档和符号 |

编辑器还提供章节折叠、签名与参数提示、悬浮信息，以及跨文档保留的当前会话撤销历史。全角语法符号仅在作者选择快速修复时替换。未保存内容会进入 `.kirin/workbench-recovery.json` 这一被忽略的有界恢复缓存，成功保存后立即清除；恢复内容只会作为未保存覆盖层重新进入工作区校验，不构成第二套源码权威。

文档菜单可以移动本地文件路径、复制为新的未保存条目草稿，或把文件移入 `.kirin/trash/documents`。移动路径不会修改文档内直接编写的 `@entry` ID、别名或数学语义；删除若会破坏引用或工作区校验，会自动撤销。Package 文档始终只读。

完整语法见 [Kirin source syntax v1](docs/kirin-syntax.md)。

完整的交互、权威和安全边界见 [浏览器工作台规范](docs/web-workbench.md)。针对当前《魔兽世界》式阈值、层数、触发、周期、充能、目标软上限和状态过程的边界结论，见 [游戏机制计算能力审查](docs/game-mechanics-capability-audit.md)。

## 创建游戏中立工作区

新工作区永远是游戏中立的：

```bash
kt init my-math
```

核心不再提供任何内置游戏数据。它只提供数值、布尔值、精确运算、量纲代数、通用表达式，以及 `time`、`second`、`millisecond`、`probability`、`count`、`nonnegative_integer` 和 `positive_integer` 等游戏中立数学词汇。`damage`、`healing`、`attack_power`、资源、职业、技能和版本数据必须由工作区或社区 Package 声明。

## GitHub 社区 Package

任何人都可以用模板创建独立 Package：

```bash
kt package new my-community-package \
  --name community.example \
  --namespace community_example
kt package check my-community-package
```

作者把仓库推送到 GitHub 并发布精确版本 tag 后，用户可以安装：

```bash
cd my-math
kt package add example github:OWNER/REPOSITORY 1.0.0
kt package list
kt package verify
```

本地开发使用：

```bash
kt package add-path example ../my-community-package
```

`kirin.packages.toml` 是用户声明的直接依赖，`kirin.lock` 锁定完整依赖图、Git commit 和内容摘要，`.kirin/packages/` 是可重建的只读缓存。普通工作区加载永不隐式联网；缺失缓存使用 `kt package restore` 显式恢复。Package 文档和静态模板在浏览器工作台中只读，运行记录仍嵌入所用定义，因此移除 Package 后也能重放。

Package 必须使用 manifest 声明的 namespace 前缀导出文档和数学语义，不得引用未声明的 Package 或工作区本地定义。它不能注册 Python、安装脚本、Git hook 或其他可执行能力。完整协议见 [Kirin community package protocol v1](docs/package-system-v1.md)。

社区作者不需要把内容提交进 Kirin Tor 核心仓库：他们在自己的 GitHub 仓库中接受 issue、Pull Request 和共同维护，发布后把安装地址分享给用户即可。Kirin Tor 维护的是“游戏知识如何表达、组合、验证和计算”的公共协议，不裁定“某个游戏具体包含什么”。

## 用户定义基础数学语义

除内核固有的游戏中立数学词汇外，命名量纲、单位和可复用值域均可由任意普通条目声明：

```text
@kirin 1
@entry my_semantics

// 我的数学语义

dimensions:
  power
  effect

units:
  power = power
  effect = effect
  effect_per_power = effect / power

domains:
  level_choice: number[dimensionless] integer one-of [0, 1, 2]
```

`dimensions`、`units` 和 `domains` 可以出现在任何 `entry` 中。重复的同义声明允许存在；同名但数学结构不同的单位或值域会由 `kt check` 报告冲突及两个来源位置。内核不会根据名字猜测或偷偷创建语义。

## 输入具有稳定的限定身份

条目内部仍使用短名：

```text
@kirin 1
@entry character

// 角色属性

inputs:
  attack_power: number[attack_power] = 3000 in 0..*

outputs:
  displayed_attack_power: attack_power = attack_power
```

该输入的稳定身份是 `character.attack_power`。其他条目可以直接引用它，条目内参数方案和 CLI 也可以覆盖它：

```text
@kirin 1
@entry builds

presets:
  stronger "高主属性":
    character.attack_power = 3500
```

```bash
kt eval character.displayed_attack_power --set character.attack_power=3500
```

如果一个短名在当前目标中唯一，`--set attack_power=3500` 仍可使用；若多个条目都声明 `rank` 或 `x`，必须写限定名。这避免不相关条目因为同名输入而被意外合并。

参数优先级为：条目 `default` < 参数方案 < 本次 `--set`。`--keep`、求导/求解变量以及扫描轴不会被默认值或参数方案提前代入。

## 中文局部别名与显示标签

正式 ID 保持 ASCII，公式可以使用仅在当前条目内生效的 Unicode 别名：

```text
aliases:
  技能甲 = skill_a.expected
  技能乙 = skill_b.expected

inputs:
  crit "暴击率": probability = 0.25

outputs:
  total "组合期望伤害": damage = 技能甲(crit) + 2 * 技能乙(crit)
```

别名可以指向输入、字段、输出或函数；其他文件、参数方案、CLI 和运行结果仍使用 `entry.member` 正式身份。双引号标签只负责浏览器工作台、`explain` 和图表呈现，修改标签不会破坏引用。图表 `y` 声明中显式的 `as "标签"` 会覆盖成员的默认标签。

## 作者定义分组、参数方案与显示方式

工具不预先决定玩家应该按什么分类。作者可以把本条目的输出放入任意分组，并把常用输入组合保存为参数方案：

```text
groups:
  single_target "单体":
    expected_damage
    damage_per_cast

presets:
  current "当前配装":
    character.crit = 0.25
  high_crit "高暴击":
    character.crit = 0.40

display:
  expected_damage: integer
  damage_per_cast: coefficient_percent digits 2
```

分组只影响选择器的顺序与检索，不改变数学含义。输出不必属于任何分组，一个输出也不能同时出现在两个分组中。参数方案属于普通 `entry`，引用时使用稳定名称 `entry.preset`；短名仅在工作区内唯一时可用。

版本化离散数据可直接写成查表，并选择精确匹配或线性插值：

```text
tables:
  rating "等级换算": dimensionless -> dimensionless:
    1 = 10
    3 = 30

outputs:
  exact: dimensionless = lookup(rating, level)
  smooth: dimensionless = interpolate(rating, level)
```

## 通用字段、函数、约束与分段表达式

```text
@kirin 1
@entry fictional_effect

// 虚构效果

inputs:
  level: level_choice = 2

constraints:
  level >= 0

fields:
  coefficient: effect_per_power = 1/2

functions:
  value_for(local_level: level_choice) -> dimensionless =
    piecewise(
    local_level == 0, 0,
    local_level == 1, 1/10,
    local_level == 2, 1/5,
    0
    )

outputs:
  result: effect = coefficient * character.attack_power * (1 + value_for(level))
```

`rank`、`talent` 或 `targets` 都不是内核关键字。整数、有限允许值、条件和分段函数是通用能力，变量叫什么以及每个值表示什么由用户决定。

## 常用命令

```text
kt init DIRECTORY
kt package new DIRECTORY --name NAME --namespace NAMESPACE
kt package check [DIRECTORY]
kt package add ALIAS github:OWNER/REPOSITORY VERSION
kt package add-path ALIAS DIRECTORY
kt package remove ALIAS
kt package update ALIAS [VERSION]
kt package restore|verify|list
kt web [WORKSPACE|SOURCE.kirin] [--port PORT] [--no-open]
kt new entry ID [--template blank|data|model|semantics]
kt new plot ID
kt list [--json]
kt show ID [--json]
kt explain TARGET [--json]
kt check [--timeout SECONDS] [--json]
kt eval TARGET [--preset ENTRY.PRESET] [--set ENTRY.INPUT=VALUE] [--save-run ID] [--json]
kt simplify|expand|factor TARGET [--keep ENTRY.INPUT] [--json]
kt diff TARGET --var ENTRY.INPUT [--json]
kt solve TARGET --var ENTRY.INPUT --equals "VALUE [UNIT]" [--range START:END] [--json]
kt solve-system --equation TARGET="VALUE [UNIT]" --var ENTRY.INPUT [...] [--json]
kt scan --x ENTRY.INPUT --range START:END --points N --y TARGET [--y TARGET ...] [--out FILE.csv]
kt grid --x ENTRY.INPUT --x-range START:END --x-points N \
  --y ENTRY.INPUT --y-range START:END --y-points N --result TARGET [--out FILE.csv]
kt plot --x ENTRY.INPUT --range START:END --points N --y TARGET --out FILE.svg
kt plot --config PLOT_ID
kt replay RUN_ID [--regenerate-artifacts] [--json]
```

`kt explain` 展示展开表达式、限定输入、值域、定义域条件、来源、游戏版本和依赖闭包。`kt check` 严格拒绝未知 schema 键，会验证默认值、参数方案、组合约束、引用、循环、版本一致性、单位和绘图配置；可独立发现的错误会一次汇总，并尽量给出文件、行、列、条目和字段。

## 示例工作区

以下验收示例使用虚构数据，不代表真实 WoW 技能：

```bash
cd "examples/虚构技能工作区"
kt check
kt eval combo.total --preset presets.baseline
kt simplify combo.total --keep combo.crit
kt diff combo.total --var combo.crit
kt solve combo.total --var combo.crit --equals "3000 damage" --range "0:1"
kt scan --x combo.crit --range "0:0.6" --points 61 \
  --y combo.total --preset presets.baseline --out results/damage.csv --force
kt plot --config crit_curve --force
```

关键结果：`2750 damage`、`2200*combo.crit + 2200`、导数 `2200 damage`、解 `4/11`，以及扫描端点 `2200` 与 `3520 damage`。

## 扫描与绘图

曲线、双属性网格和绘图使用完全相同的解析、约束、单位和求值路径。无效采样点保留错误，不会伪造为零。CSV 同时保存精确值、近似值、错误、单位、有效参数、精度和依赖 id。

允许用户把不同单位的曲线画在同一纵轴；CLI 会给出非阻断警告，并保留每条曲线的真实单位，不进行隐式换算。

默认情况下：

- 输出必须位于工作区内；确需写到外部时显式使用 `--allow-outside-workspace`。
- 已有 SVG、PNG 或 CSV 不会被覆盖；显式使用 `--force` 才能替换。
- `scan`、`grid`、`plot`、求解、解析、引用展开及所有 SymPy 运算都受 `--timeout` 控制；超时会终止实际工作进程。

保存的 plot 配置还支持 `title`、`x_label`、`y_label` 和 `curve_labels`。

## 运行记录与重放

```bash
kt eval combo.total --preset presets.baseline --save-run before_change
kt replay before_change --json
```

运行记录格式 v2 保存：

- 操作、原始请求和实际生效的限定参数。
- 依赖闭包及所有语义声明条目的完整原始源文本、结构内容和双重哈希；社区定义还带有 Package 来源、版本、提交和内容摘要。
- 定义域条件、假设、单位、精度、依赖版本和内核实现哈希。
- 成功结果或失败状态。
- CSV/SVG/PNG 的内容哈希和大小。

重放只读取记录中的快照，不读取当前 `entries/`。它会比较当前与记录中的依赖版本，并明确报告环境漂移；失败运行也能重放。绘图和网格记录可使用 `--regenerate-artifacts` 在新路径重新生成产物，默认仍不覆盖已有文件。

v1 运行记录与 v2 不兼容，会明确报错，而不会假装能够保证复现。

## 实际数学能力

- 精确整数、有理数、十进制和科学计数法；近似精度与显示位数分离。
- `+ - * / **`、括号和显式函数调用。
- 比较 `== != < <= > >=` 与布尔 `and or not`。
- `abs`、`min`、`max`、`sqrt`、`floor`、`ceil`。
- `if_else`、多分支 `piecewise` 和有明确整数上下界的有限 `sum`、`product`。
- 版本化 `lookup` 精确查表和 `interpolate` 线性插值。
- 显式有限离散分布、映射、作者声明独立的卷积/重复试验、条件化，以及精确的期望、方差和指定结果概率。
- 具有静态有限步数的纯函数递推。
- 有限状态模型的唯一稳态概率、稳态奖励、到达概率和期望步数解析求解。
- 固定数值/布尔字段、派生字段、显式参数函数和输出。
- 用户定义基础量纲、带精确比例的命名单位、整数值域、上下界和有限允许值；例如 `millisecond = 1/1000 * time`。
- 数值求值、化简、展开、因式分解、求导、单变量实数符号求解，以及最多八个变量/方程的有限符号联立反求。
- 一维精确等距扫描、多曲线 CSV/SVG/PNG，以及总计最多 10,000 点的双属性网格和热力图。

除法、根式、负幂、零次幂和变量指数会保留必要的实数定义域条件。例如 `x/x` 化简为 `1` 后，`x != 0` 仍然保留。

## 已知边界

- `solveset` 返回条件集合、无限集合或未完成集合时，命令返回 `incomplete` 和非零退出码；没有一般数值根搜索。
- 联立反求只接受有限符号解；不支持矩阵语言、不等式组、积分、极限或复杂优化。
- 不支持隐式乘法；`^` 不表示乘方。
- 不执行用户代码，不允许导入、下标、lambda、多层属性访问或未注册函数。
- 核心不自动推断分布独立性；独立组合与重复必须由作者显式声明，并受结果数、组合对和重复次数上限约束。
- 有限递推和状态模型不提供可变运行时状态、事件队列、战斗时间线、APL 或随机采样。

完整 schema、安全边界和固定限制见 [docs/schema-and-expressions.md](docs/schema-and-expressions.md)。
`0.3.0rc1` 的破坏性变更、当前预发布能力和迁移摘要见 [CHANGELOG.md](CHANGELOG.md)。

实现所依据的官方接口资料包括：[SymPy 解析安全警告](https://docs.sympy.org/latest/modules/parsing.html)、[SymPy solveset 集合语义](https://docs.sympy.org/latest/modules/solvers/solveset.html)、[Typer 命令](https://typer.tiangolo.com/tutorial/commands/) 和 [Matplotlib savefig](https://matplotlib.org/stable/api/_as_gen/matplotlib.pyplot.savefig.html)。项目测试会读取实际安装版本并把相关版本写入每份运行记录。
