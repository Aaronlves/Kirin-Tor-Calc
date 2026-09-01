# 结构模型、表达式与安全边界

本页说明 Kirin source 解析后形成的结构模型、数学语义和安全边界。表面语法的完整写法见 [Kirin source syntax v1](kirin-syntax.md)。

## 1. 工作区

工作区根目录包含：

```text
kirin.workspace
kirin.packages.toml    # 可选，用户声明的直接 Package 依赖
kirin.lock             # 可选，生成的精确依赖锁
.kirin/packages/       # 可删除、可恢复的内容寻址缓存
entries/
runs/
results/
```

标记文件格式为：

```text
@kirin-workspace 1
```

新工作区没有游戏选择。旧工作区中的 `initial-package` 仍可作为惰性迁移元数据读取，但不再具有运行时权限。`entries/` 递归发现本地 `.kirin` 文件；锁定 Package 的同类源文件通过同一解析器合并加载。文件名、子目录和 `//` 标题注释都不构成引用身份。

文档 id、字段、输入、函数、局部参数、量纲、单位和值域名称遵守 `[A-Za-z_][A-Za-z0-9_]*`，且不得以 `__` 开头。参数方案和绘图轴可以使用 `entry_id.input_name`。

## 2. 单一文档模型

数学内容只有一种文档：

```text
@entry ID
```

角色、技能、天赋、开关、组合模型、语义声明以及可选图表配置都是普通 entry；文件本身直接表达其结构与计算语义。

解析器严格拒绝未知指令、章节、重复成员和不一致缩进。`//` 行完全不进入结构模型；`---` 围栏内容只进入文档说明。

## 3. 数学核心与用户声明的语义

核心内置游戏中立的 `dimensionless`、`time`、`second`、`millisecond`、`probability`、`count`、`nonnegative_integer` 和 `positive_integer`。这些名称只表达数学或物理结构，不表达任何具体游戏机制。

### 3.1 量纲与单位

```text
dimensions:
  damage "伤害"
  time "时间"

units:
  damage = damage
  second = time
  millisecond = 1/1000 * time
  damage_per_time = damage / time
```

量纲是独立数学轴。单位右侧会被解析成精确比例与“基础量纲 → 精确有理指数”的结构映射；只允许正的精确比例、名称、乘法、除法和精确幂。

同名且结构相同的声明可以重复；同名但结构不同会失败并报告两个来源位置。内核不会根据名字猜测或自动创建单位。

输入、常量、查表点、范围、目标值和结果都会按声明比例精确换算。表达式中也可直接写 `500 * millisecond`。

### 3.2 可复用值域

```text
domains:
  probability: number[dimensionless] in 0..1
  three_levels: number[dimensionless] integer one-of [0, 1, 2]
```

值域支持：

- 数值或布尔类型；
- 单位；
- 单侧或双侧界限；
- 整数限制；
- 有限允许值。

输入可以收窄命名值域，但不能放宽它。

### 3.3 社区 Package

核心不再包含游戏初始化包。社区 Package 通过 `kirin.package.toml` 声明精确版本、namespace 和依赖，经 GitHub commit 与内容摘要锁定后，从 `.kirin/packages/` 只读加载。Package 中的文档、量纲、单位和值域必须使用其 namespace 前缀；不同 Package 不能隐式覆盖，也不能引用未声明的依赖或工作区本地定义。完整格式和权威边界见 [Package protocol v1](package-system-v1.md)。

## 4. 输入与稳定参数身份

```text
inputs:
  crit "暴击率": probability = 0.25
  targets: number[dimensionless] = 1 in 1..20 integer
  enabled: boolean = true
```

条目 `combo` 中输入 `crit` 的稳定身份是 `combo.crit`：

- 当前条目内部写 `crit`；
- 其他条目写 `combo.crit`；
- 参数方案、CLI 覆盖、求导、求解和扫描推荐使用限定名；
- 短名只有在当前候选集合中唯一时才能省略前缀。

参数优先级为：

```text
entry default < preset < --set
```

符号保留变量、求导/求解变量和扫描轴不会被默认值或参数方案提前代入。

### 4.1 中文局部别名与显示标签

正式 ID 保持 ASCII；条目可以为限定成员声明只在当前文件生效的 Unicode 别名：

```text
aliases:
  技能甲 = skill_a.expected
  技能乙 = skill_b.expected

outputs:
  total "组合期望伤害": damage = 技能甲(crit) + 2 * 技能乙(crit)
```

别名可以指向输入、字段、函数、有限分布、有限递推、有限状态模型或输出，但不能遮蔽当前条目的正式成员或表达式内置函数。其他文件、参数方案、CLI 参数和运行结果仍使用正式限定身份。数学成员可以增加双引号显示标签；标签只影响 `explain`、浏览器工作台和图表呈现，不参与引用。图表曲线显式的 `as "标签"` 优先于成员默认标签。

## 5. 约束、字段、函数与输出

### 5.1 组合约束

```text
constraints:
  targets >= 1 and targets <= 20
  not enabled or coefficient > 0
```

约束必须产生布尔值，可以引用当前条目的输入、数学字段和普通跨条目成员。`kt check` 会验证可确定的默认值及参数方案组合。

### 5.2 字段

```text
fields:
  base "基础伤害": damage = 1000
  enabled_by_default: boolean = true
  scaled: damage = base * multiplier
```

字段统一使用 `=`。右侧为数值或布尔字面量时是固定值，其余内容按表达式计算。说明文字放在注释、描述块或 `sources:` 中。

### 5.3 函数与输出

```text
functions:
  expected "期望伤害函数"(c: probability) -> damage = base * (1 + c)

outputs:
  total "组合期望伤害": damage = skill_a.expected(crit) + 2 * skill_b.expected(crit)
```

函数参数是显式局部变量，不能声明默认值。函数和输出声明的单位必须与表达式推导的量纲一致。

## 6. 分组、参数方案、查表与显示

```text
groups:
  damage "伤害收益":
    total

presets:
  baseline "当前配装":
    combo.crit = 0.25
    selection.enabled = true

tables:
  rating "等级换算": dimensionless -> dimensionless:
    1 = 10
    3 = 30

display:
  total: integer
```

分组完全由作者命名，只影响浏览器工作台中的顺序和搜索；内核不预设游戏类别。参数方案只能提供已声明的输入，稳定引用为 `entry.preset`。十进制直接作为精确文本处理，不经过二进制浮点数。`lookup` 要求精确键，`interpolate` 只在表范围内做线性插值。

### 6.1 有限离散概率分布

```text
distributions:
  proc_result "触发结果": damage:
    0 @ 1 - proc_chance
    proc_damage @ proc_chance

outputs:
  expected_damage: damage = expectation(proc_result)
  damage_variance: damage_squared = variance(proc_result)
  proc_probability: dimensionless = probability(proc_result, proc_damage)
```

分布是 entry 中可复用、但不能直接充当标量的数学成员。结果和值均使用普通受限表达式，因此可以引用输入、字段、函数与其他 entry；跨 entry 分布引用写作 `entry.distribution`，并进入既有依赖、Package 权限、版本检查、运行快照与重放路径。

每个结果必须是数值并符合分布声明量纲；概率必须无量纲、处于 `0..1`，且有效参数代入后总和精确等于 `1`。校验器不会静默归一化。`expectation` 返回原量纲，`variance` 返回原量纲的平方，`probability` 返回指定结果的总概率。

`map(distribution, value, expression)` 映射结果；`independent_sum(left, right)` 由作者明确声明两个分布独立并执行卷积；`repeat_sum(distribution, count)` 明确声明有限次独立重复，次数可以是常量或一个具有有限整数值域的直接输入；`condition(distribution, value, predicate)` 生成条件分布，条件事件概率为零时失败。等价结果会合并，但核心绝不从名称或依赖关系推断独立性，也不进行随机采样。

### 6.2 有限递推

```text
recurrences:
  protected_chance: dimensionless:
    initial = base_chance
    steps = failures
    next(current, index) = min(current + increase, cap)
```

递推是普通数值成员。初始值与每一步结果必须符合声明量纲；步数必须是非负整数常量，或直接来自一个可静态证明为有限整数值域的输入。内核将纯函数更新展开为标量表达式或有限 `Piecewise`，最多 1,000 步；不存在可变状态、无限递归或事件时钟。

### 6.3 有限状态解析模型

```text
state_models:
  proc_cycle:
    states:
      ready
      cooldown
    transitions:
      ready -> ready @ 1 - proc_chance
      ready -> cooldown @ proc_chance
      cooldown -> ready @ 1
    rewards:
      damage_reward: damage:
        ready = hit
        cooldown = 0
```

每个状态必须有出边，每一行转移概率必须精确归一化。`steady_probability` 与 `steady_reward` 解析求解唯一稳态；`hitting_probability` 与 `expected_steps` 求给定起点到目标状态的到达概率和期望步数。线性系统不唯一、目标系统奇异或参数落在奇异边界时明确失败，不选择任意解。

状态模型只是有限转移矩阵及奖励函数的声明式语法：没有动作、角色、APL、事件队列、战斗时间线或随机采样。

## 7. 可选图表配置

```text
x: combo.crit
range: 0..0.6
points: 61

y:
  combo.total as "组合 A"
  alternative.total as "组合 B"

preset: builds.baseline
title: "对比"
x-label: "暴击率"
y-label: "数值"
export-svg: "results/damage.svg"
export-csv: "results/damage.csv"
```

这些字段直接附加在定义相关公式的 entry 中；缺少 `x/y` 时不产生图表。所有曲线共享一个稳定横轴输入。不同量纲的纵轴可以同时绘制；工具保留每条曲线单位并产生警告。相同量纲的不同单位会按声明比例精确换算。

浏览器工作台使用同一份 scan 数据生成 SVG 预览、热力图和数据表。SVG、PNG 和 CSV 导出仍通过同一数学求值结果产生。

## 8. 受限表达式

允许：

- 精确数值与布尔字面量；
- 已声明局部名和 `entry.member`；
- `+ - * / **` 和括号；
- `== != < <= > >=`；
- `and or not`；
- 白名单函数和已声明条目函数。

白名单函数：

```text
abs(x)
min(x, ...)
max(x, ...)
sqrt(x)
floor(x)
ceil(x)
if_else(condition, when_true, when_false)
piecewise(condition1, value1, ..., default_value)
sum(expression, index, inclusive_lower_integer, inclusive_upper_integer)
product(expression, index, inclusive_lower_integer, inclusive_upper_integer)
lookup(table, key)
interpolate(table, key)
expectation(distribution)
variance(distribution)
probability(distribution, value)
map(distribution, variable, expression)
independent_sum(left_distribution, right_distribution)
repeat_sum(distribution, bounded_count)
condition(distribution, variable, predicate)
steady_probability(model, state)
steady_reward(model, reward)
hitting_probability(model, start_state, target_state)
expected_steps(model, start_state, target_state)
```

不允许：

- 赋值、列表、字典和下标；
- lambda、推导式和隐式乘法；
- 多层对象属性；
- 导入、文件、网络或任意代码执行；
- 未声明变量或函数；
- 用 `^` 表示乘方。

用户表达式先经过受限 Python AST 白名单，再直接构造 SymPy 对象；代码不调用 Python `eval`/`exec`、SymPy `parse_expr` 或字符串 `sympify`。

## 9. 精确数值与定义域

整数、有理数、十进制和科学计数法首先转换为精确有理数。近似计算精度与显示位数分别控制。

内核传播除数非零、偶次根非负、函数参数值域、输入界限、有限允许值和显式 constraints。不能满足的条件返回结构化定义域错误，不会产生伪造数值。

## 10. 求解、扫描与绘图

单变量实数求解区分：

- 精确解；
- 数值近似解；
- 已证明无解；
- 条件集合或未完成集合。

未完成集合不会被截断成几个样本冒充完整答案。

`solve-system` 可对最多八个输入联立最多八个等式；只接受满足每个输入值域和全部定义域条件的有限符号解，参数化结果会明确标为 `incomplete`。

一维扫描和双属性网格都使用精确等距轴。无效采样点保留错误原因并形成曲线断点或热力图空格。二维网格总点数与一维扫描共享 10,000 点上限。所有解析、引用展开、SymPy 操作、求解、扫描与绘图均受进程级超时约束。

## 11. 运行记录与重放

运行记录格式 v2 保存：

- 原始请求和实际生效参数；
- 依赖条目及语义声明条目的完整 Kirin source；
- 源哈希与规范结构哈希；
- 定义域条件、单位、精度和实现环境；
- 成功结果或失败状态；
- 导出文件的哈希与大小。

重放只从嵌入的结构快照构建隔离工作区，不读取当前 `entries/`。

## 12. 固定限制

| 项目 | 上限 |
| --- | ---: |
| 工作区文档 | 5,000 |
| 工作区源文本总量 | 50,000,000 bytes |
| 单个 Kirin source | 1,000,000 bytes |
| 单个运行记录 | 200,000,000 bytes |
| 单表达式字符 | 2,000 |
| 表达式 AST | 200 nodes，30 层 |
| 单 entry 输入 | 100 |
| 单值域允许值 | 1,000 |
| 单次扫描点 | 10,000 |
| 有限求和或连乘项 | 10,000 |
| 单个有限分布结果 | 1,000 |
| 单次分布组合结果对 | 10,000 |
| 独立重复次数 | 1,000 |
| 有限递推步数 | 1,000 |
| 单个状态模型状态 | 16 |
| 单个状态模型转移 | 256 |
| 单个状态模型奖励 | 64 |
| 联立方程或变量 | 8 |
| 默认操作超时 | 10 秒 |
| 最大可请求超时 | 300 秒 |

## 13. 错误与机器输出

错误具有稳定 code，并尽量包含源文件、行、列、条目和字段位置。`--json` 只向 stdout 写 JSON，诊断写 stderr；失败返回非零状态。`kt check` 会汇总彼此独立的加载和数学错误。

浏览器工作台在这些稳定错误之上增加中文呈现层：显示中文错误类别和常见原因、工作区相对路径、行列、正式条目/字段以及原始英文技术详情。错误行中的全角符号会产生明确替换建议，但工具不会静默修改作者源。CLI 文本、错误 code、JSON 字段和运行记录仍保持原有机器契约。

文档选择器将首条非空 `//` 注释作为中文显示标题，并始终同时显示相对路径。标题不进入 schema，也不改变文档 ID、引用或运行记录。

浏览器编辑器提供 `Ctrl+Space` Kirin 补全，从磁盘文档和所有内存草稿建立容错索引，可按正式 ID、中文标签或中文别名查找输入、字段、函数、有限分布、递推、状态模型和输出，也包含量纲、单位、值域、内置函数和结构关键字。候选只帮助插入源文本，不创建新的身份或绕过后续完整校验。中文语法片段同样只展开为普通 Kirin source；插入后立即进入既有工作区校验路径。
