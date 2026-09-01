# Kirin Tor CLI

Kirin Tor CLI 是一个游戏中立、文件驱动的结构化数学工作台。它面向希望保存数据、公式、参数方案和图表，而不想编写程序的理论计算用户。

公开文档只有两类：保存数据、公式和参数方案的 `entry`，以及保存图表配置的 `plot`。角色、技能、天赋、目标衰减、组合公式以及其他游戏机制都由用户用普通条目表达；内核不会把任何游戏、职业或机制写死。两类文档和用户声明的数学语义统一使用 `.kirin` 源文件。可选的 WoW 初始化包也只是遵守同一公开语法的普通数据文件，没有额外执行权限。

这不是战斗模拟器：没有事件队列、随机战斗模拟、完整 APL、Boss 时间轴或自动循环优化器。

## 安装

需要 Python 3.9 或更新版本：

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -U pip
python -m pip install '.[tui]'
kt version
kt --help
```

开发安装：

```bash
python -m pip install -e '.[dev,tui]'
pytest
```

`pyproject.toml` 安装命令入口 `kt`，因此激活对应虚拟环境后，可以在源码目录之外使用。

## Kirin 源文件与 TUI

`kt new` 创建 `.kirin` 文档。Kirin 源文件使用 `//` 作者注释、`---` 长说明块、固定章节和缩进表达结构，不使用 Markdown：

```text
@kirin 1
@entry fictional_effect

// 虚构效果

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

在工作区内运行 `kt tui` 会打开第一个 `.kirin` 文档；也可以直接传工作区目录或源文件，不必先 `cd`：

```bash
kt tui entries/fictional_effect.kirin
kt tui /path/to/workspace
```

TUI 默认进入玩家计算台，并提供五个普通入口：计算、图表、文档、诊断和记录。`Ctrl+1` 至 `Ctrl+5` 切换入口。

- **计算**选择一个正式输出，并添加一个或多个命名方案。输出按作者在条目中声明的分组排序和搜索，工具不预设“伤害/防御”等类别。每个比较方案可以选择条目内参数方案，也可以通过类型化表单或高级文本临时改参数；百分比可直接写作 `25%`。结果使用作者声明的整数、百分比或系数显示，同时保留精确值。除了单输入反求，也可用多个结果联立反求多个输入。
- **图表**可生成单轴曲线、多方案比较曲线和双属性热力图；终端预览与数据表共享同一份计算结果。已保存的 `plot` 会完整恢复所有曲线。单方案曲线可转换为未保存的图表配置草稿；热力图可导出完整 CSV。
- **文档**保留 Kirin 编辑器。`Ctrl+N` 只创建 `entry` 或 `plot` 草稿；entry 可从空白、数据、公式或基础语义模板开始，参数方案写在 entry 的 `presets:` 中。创建时不写盘。`Ctrl+P` 切换文档，`Ctrl+R` 校验所有内存草稿，`Ctrl+S` 验证后保存全部已修改文档，`Ctrl+E` 保存并导出当前图表配置的 SVG/CSV。
- **诊断**聚合多个文件中的独立错误，选择错误后会打开对应文件和行；也可查看输出的展开公式、输入、单位、条件和依赖文档。
- **记录**把已保存文档上的计算比较写成含定义快照的不可变运行记录，并使用同一重放管线检查结果和环境是否一致。

退出或关闭存在未保存修改的文档时，TUI 会要求保存、丢弃或取消。计算可以使用完整且有效的未保存草稿，但会明确标示来源；保存运行记录前必须先保存并校验参与计算的文档。

界面使用 Kirin Tor 的紫、金与法力蓝视觉体系，但操作名称保持为玩家熟悉的普通词汇。图表显现动画只改变已计算数据的显示进度，不重复计算数据；可在图表页选择完整、精简或关闭，自动化测试始终关闭动画。

TUI 的状态、诊断类别和常见错误说明默认使用中文。诊断保留相对文件位置、行列、正式条目/字段以及英文技术详情；如果错误行包含 `：`、`，`、`（`、`）`、中文引号等常见全角符号，还会显示对应的半角替换建议。CLI 的稳定错误 code 和 `--json` 结构不受本地化影响。

文档编辑区提供 Kirin 专用语法高亮；指令、章节、正式成员、中文别名、字符串、数字、布尔值、单位类型、函数调用、注释和 `---` 说明块使用不同样式。按 `Ctrl+Space` 打开补全，在候选中用上下方向键移动、`Enter` 插入、`Esc` 关闭。补全会读取全部磁盘文档和内存草稿，可以按正式 ID、中文标签或中文别名检索输入、字段、函数、输出、量纲、单位和值域；函数补全后光标位于参数括号内。

补全面板还提供中文触发的结构片段，包括“条目文档”“图表文档”“输入”“别名”“字段”“函数”“查表”“输出”“分组”“参数方案”“显示”“约束”“说明字段”“来源”“长说明”“分段”和“条件”。多行片段继承当前行缩进，并把光标放在下一处需要填写的位置。

完整语法见 [Kirin source syntax v1](docs/kirin-syntax.md)。

完整的日常流程和保留边界见 [TUI 玩家视角验收](docs/tui-player-acceptance.md)。针对当前《魔兽世界》式阈值、层数、触发、周期、充能、目标软上限和状态过程的边界结论，见 [游戏机制计算能力审查](docs/game-mechanics-capability-audit.md)。

## 创建工作区与选择数据包

空白、游戏中立的工作区：

```bash
kt init my-math --package none
```

包含 WoW 基础语义的工作区：

```bash
kt init my-wow-math --package wow
```

`wow` 包会复制一个普通的 `entries/wow_semantics.kirin`，其中声明 `time`、`damage`、`attack_power`、`healing`、`armor`、`resource` 等量纲和常用值域。用户可以查看、修改、删除或替换它；包不能注册 Python 代码，也不能绕过安全解析器。

## 用户定义基础数学语义

除内核固有的数值、布尔值和 `dimensionless` 外，命名量纲、单位和可复用值域均可由任意普通条目声明：

```text
@kirin 1
@entry my_semantics
@template semantics

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

别名可以指向输入、字段、输出或函数；其他文件、参数方案、CLI 和运行结果仍使用 `entry.member` 正式身份。双引号标签只负责 TUI、`explain` 和图表呈现，修改标签不会破坏引用。plot 中显式的 `as "标签"` 会覆盖成员的默认标签。

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

info:
  note = "这只是说明文字"

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
kt init DIRECTORY [--package none|wow]
kt tui [WORKSPACE|SOURCE.kirin]
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

[`examples/酒仙系数表复现`](examples/%E9%85%92%E4%BB%99%E7%B3%BB%E6%95%B0%E8%A1%A8%E5%A4%8D%E7%8E%B0/README.md) 使用 Kirin 语法复现一份酒仙玩家工作簿的第 1、3、6 张表，覆盖单体伤害、防御/治疗和 1–20 目标 AOE 比较。它保留原表的版本边界，不把表内数值声明成当前官方数据。

### 虚构验收示例

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
- 依赖闭包及所有语义声明条目的完整原始源文本、结构内容和双重哈希。
- 定义域条件、假设、单位、精度、依赖版本和内核实现哈希。
- 成功结果或失败状态。
- CSV/SVG/PNG 的内容哈希和大小。

重放只读取记录中的快照，不读取当前 `entries/` 或 `plots/`。它会比较当前与记录中的依赖版本，并明确报告环境漂移；失败运行也能重放。绘图和网格记录可使用 `--regenerate-artifacts` 在新路径重新生成产物，默认仍不覆盖已有文件。

v1 运行记录与 v2 不兼容，会明确报错，而不会假装能够保证复现。

## 实际数学能力

- 精确整数、有理数、十进制和科学计数法；近似精度与显示位数分离。
- `+ - * / **`、括号和显式函数调用。
- 比较 `== != < <= > >=` 与布尔 `and or not`。
- `abs`、`min`、`max`、`sqrt`、`floor`、`ceil`。
- `if_else`、多分支 `piecewise` 和有明确整数上下界的有限 `sum`、`product`。
- 版本化 `lookup` 精确查表和 `interpolate` 线性插值。
- 固定数值/布尔字段、派生字段、说明字段、显式参数函数和输出。
- 用户定义基础量纲、带精确比例的命名单位、整数值域、上下界和有限允许值；例如 `millisecond = 1/1000 * time`。
- 数值求值、化简、展开、因式分解、求导、单变量实数符号求解，以及最多八个变量/方程的有限符号联立反求。
- 一维精确等距扫描、多曲线 CSV/SVG/PNG，以及总计最多 10,000 点的双属性网格和热力图。

除法、根式、负幂、零次幂和变量指数会保留必要的实数定义域条件。例如 `x/x` 化简为 `1` 后，`x != 0` 仍然保留。

## 已知边界

- `solveset` 返回条件集合、无限集合或未完成集合时，命令返回 `incomplete` 和非零退出码；没有一般数值根搜索。
- 联立反求只接受有限符号解；不支持矩阵语言、不等式组、积分、极限或复杂优化。
- 不支持隐式乘法；`^` 不表示乘方。
- 不执行用户代码，不允许导入、下标、lambda、多层属性访问或未注册函数。

完整 schema、安全边界和固定限制见 [docs/schema-and-expressions.md](docs/schema-and-expressions.md)。
0.2 的破坏性变更与迁移摘要见 [CHANGELOG.md](CHANGELOG.md)。

实现所依据的官方接口资料包括：[SymPy 解析安全警告](https://docs.sympy.org/latest/modules/parsing.html)、[SymPy solveset 集合语义](https://docs.sympy.org/latest/modules/solvers/solveset.html)、[Typer 命令](https://typer.tiangolo.com/tutorial/commands/) 和 [Matplotlib savefig](https://matplotlib.org/stable/api/_as_gen/matplotlib.pyplot.savefig.html)。项目测试会读取实际安装版本并把相关版本写入每份运行记录。
