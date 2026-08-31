# Schema v1、表达式与安全边界

## 1. 工作区

工作区根目录包含严格校验的 `.kirin-tor.yaml`（`schema_version: 1`、`kind: kirin_tor_workspace`），以及：

```text
entries/    普通数学条目和语义声明
scenarios/  参数方案
plots/      可保存的绘图配置
runs/       不可覆盖的运行记录
results/    推荐的输出位置
```

前三个目录递归发现 `.yaml` 和 `.yml`。文件名、子目录和显示名称可以变化；引用只依赖稳定 `id`。

所有文档必须包含：

```yaml
schema_version: 1
id: ascii_identifier
name: 任意 Unicode 显示名称
type: entry | scenario | plot
```

文档 id、字段、输入、函数、局部参数、量纲、单位和值域名称遵守 `[A-Za-z_][A-Za-z0-9_]*`，且不得以 `__` 开头。scenario 参数和绘图横轴还可以使用 `entry_id.input_name`。中文可用于名称、说明、来源文字和路径。

schema 是严格的：未知键和重复 YAML 映射键都会报错，以免把 `default` 写成 `defualt`，或让后一个同名字段静默覆盖前一个。

## 2. 统一 entry

角色、技能、天赋、开关、组合公式和语义声明都使用：

```yaml
type: entry
```

可选 `template` 只是普通标识文本，不参与内核分派。内核没有 Skill、Talent、Character 或 WoW 专用核心类型。

entry 可包含：

```yaml
description: 可选说明
game_version: 可选版本文本
validation_status: 可选状态文本
sources: []
semantics: {}
inputs: {}
constraints: []
fields: {}
functions: {}
outputs: {}
```

## 3. 用户声明的基础数学语义

### 3.1 基础量纲与单位

```yaml
semantics:
  dimensions:
    damage:
      name: 伤害
    time: {}
  units:
    damage:
      dimensions: {damage: 1}
    time:
      dimensions: {time: 1}
    damage_per_time:
      dimensions: {damage: 1, time: -1}
```

`dimensions` 声明独立的基础量纲。`units.NAME.dimensions` 是基础量纲到精确有理指数的结构化映射，不使用另一套单位表达式语言。

任意普通 entry 都可以包含 `semantics`。位置和文件组织没有特权：

- 重复声明相同基础量纲名称是同一数学身份，显示说明不参与冲突判断。
- 重复声明同名且结构相同的单位允许存在。
- 同名单位对应不同量纲结构时失败，并显示两个声明位置。
- 未声明单位失败；内核不会按名字猜测。

当前版本只处理量纲，不进行秒/毫秒之类的比例换算。

### 3.2 可复用值域

```yaml
semantics:
  domains:
    probability:
      value_type: number
      unit: dimensionless
      min: "0"
      max: "1"
    three_levels:
      value_type: number
      unit: dimensionless
      integer: true
      allowed_values: [0, 1, 2]
```

值域是通用数学约束，不含 `rank` 或 `talent` 等业务关键字。支持：

- `value_type: number | boolean`
- `unit`
- `min`、`max`
- `integer: true | false`
- `allowed_values`

输入可以进一步收窄值域，但不能放宽它。例如，引用 `[0,1]` 值域的输入不能把最大值改为 `2`。

### 3.3 初始化包

`kt init --package wow` 复制一个普通的 `wow_semantics.yaml`。它与用户条目使用相同 schema、安全边界和冲突规则，没有运行时钩子或额外权限。`--package none` 只保留内核固有的 `dimensionless`、数值和布尔语义。

## 4. inputs 与稳定参数身份

直接声明：

```yaml
inputs:
  x:
    value_type: number
    unit: dimensionless
    default: "0.1"
    min: "0"
    max: "1"
    integer: false
    allowed_values: ["0.1", "0.2", "0.3"]
    description: 可选说明
```

引用值域：

```yaml
inputs:
  crit:
    domain: probability
    default: "0.25"
```

兼容简写 `unit: probability`：如果该名称是值域而不是单位，会按 `domain: probability` 解释。新文件推荐显式使用 `domain`。

布尔输入：

```yaml
inputs:
  enabled:
    value_type: boolean
    default: true
```

布尔值在 YAML 中使用 `true`/`false`，CLI 中使用 `--set entry.enabled=true`。

条目 `combo` 内的输入 `crit` 的稳定身份是 `combo.crit`：

- 条目自己的公式内部写 `crit`。
- 其他条目可以写 `combo.crit`。
- scenario、`--set`、`--keep`、`--var` 和 `--x` 推荐写 `combo.crit`。
- 短名在当前候选集合中唯一时可以省略前缀；有歧义时必须限定。

两个不相关条目可以分别声明不同约束和默认值的 `x`，不会冲突或自动共享。需要共享时，应显式引用同一个状态条目的输入或输出。

参数优先级：

```text
entry default < scenario < --set
```

符号保留变量、求导/求解变量和扫描横轴不会被前面的默认值或 scenario 提前替换。

## 5. constraints

```yaml
constraints:
  - targets >= 1 and targets <= 20
  - not enabled or coefficient > 0
```

约束必须是布尔表达式。它可以引用当前条目的输入、字段和普通跨条目成员。循环仍会报错。`kt check` 会：

- 编译约束。
- 检查默认值的单项值域。
- 在约束所需参数都具备默认值时验证组合约束。
- 对每个 scenario 叠加默认值后验证可确定的组合约束。

## 6. fields

固定数值：

```yaml
fields:
  base:
    kind: value
    value: "1000"
    unit: damage
```

固定布尔值：

```yaml
fields:
  enabled_by_default:
    kind: value
    value_type: boolean
    value: true
```

派生字段：

```yaml
fields:
  scaled:
    kind: expression
    expression: base * multiplier
    unit: damage
```

说明字段：

```yaml
fields:
  note:
    kind: info
    value: 任意 JSON 兼容的安全 YAML 内容
```

说明字段不能进入数学表达式。为保证运行记录可恢复，值只能由文本、整数、布尔、null、列表和文本键映射组成；十进制和日期应加引号保存为原始文本。固定值和表达式不能同时出现。

## 7. functions 与 outputs

```yaml
functions:
  expected:
    parameters:
      c:
        domain: probability
    expression: base_damage * (1 + c)
    unit: damage
outputs:
  total:
    expression: skill_a.expected(crit) + 2 * skill_b.expected(crit)
    unit: damage
```

函数参数是显式局部变量，不能声明默认值；数量、类型、单位和通用值域约束都会检查。entry 输入、函数局部参数、scenario 和 CLI 覆盖在实现中属于不同层级。

输出和派生字段声明的单位必须与表达式推导量纲一致。

## 8. scenario

```yaml
schema_version: 1
id: baseline
name: 基线
type: scenario
values:
  combo.crit: "0.25"
  talent_selection.enabled: true
```

scenario 只能提供已经声明的外部输入。裸浮点 YAML 会被拒绝；十进制应加引号。scenario 可以包含多个目标会用到的全局配置，单次计算只代入当前依赖闭包需要的部分。

## 9. plot

```yaml
schema_version: 1
id: curve
name: 曲线
type: plot
x: combo.crit
range: ["0", "0.6"]
points: 61
y: [combo.total, alternative.total]
scenario: baseline
out: results/damage.svg
data_out: results/damage.csv
title: 对比
x_label: 暴击率
y_label: 数值
curve_labels:
  combo.total: 组合 A
  alternative.total: 组合 B
```

所有曲线必须共享同一个稳定横轴输入。纵轴单位可以不同；此时工具保留每条曲线单位并警告，但不阻止绘图或进行隐式换算。

## 10. 受限表达式

允许：

- 数值和布尔字面量。
- 已声明局部名与 `entry.member`。
- `+ - * / **` 和括号。
- `== != < <= > >=`。
- `and or not`。
- 白名单函数和已声明条目函数。

不允许：

- 赋值、列表、字典和下标。
- lambda、推导式和隐式乘法。
- 多层对象属性。
- 导入、文件、网络或任意代码执行。
- 未声明变量或函数。
- `^` 乘方；必须写 `**`。

YAML `|` 块中的换行作为安全空白连接。表达式内部没有赋值语句；命名中间量使用派生字段或辅助函数。

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
```

有限和上下界必须是常整数。分段函数所有分支必须同为数值或同为布尔，并且数值分支量纲兼容。未选择分支的定义域条件不会错误约束已选择分支。

用户文本先经过受限 Python AST 白名单，再直接构造 SymPy 对象。代码不使用 Python `eval`/`exec`、SymPy `parse_expr` 或字符串 `sympify`。

## 11. 精确数值与定义域

整数、有理数、十进制和科学计数法先解析为精确有理数，不经过 Python float。数值近似精度和显示位数是两个选项。取整只由 `floor` 或 `ceil` 显式表达。

量纲规则：

- 加减、比较、方程两侧、`min`、`max` 和分段数值分支必须兼容。
- 乘除合成量纲指数。
- 指数必须无量纲。
- 带量纲底数只允许常有理指数。

精确零是加法恒等元，可适配相邻或声明的量纲。因此 `damage >= 0`、`damage + 0` 和 `if_else(enabled, damage, 0)` 合法；非零无量纲数不能与伤害、时间等量纲相加或比较。

定义域条件包括：

- 除数不为零。
- `sqrt` 与非整数有理幂的底数非负。
- 负幂底数不为零。
- 零次幂保留底数不为零。
- 变量指数要求底数严格为正，以保证当前实数语义。
- 输入上下界、整数性、有限允许值、函数参数约束和 entry 约束。

因此 `x/x` 化简成 `1` 后仍拒绝 `x=0`。非实数、无穷、NaN、未赋值数值输入和无法判定的封闭定义域条件都会失败。

## 12. 求解状态

单变量实数求解使用 SymPy `solveset`，可限制闭区间。目标值和区间端点可以显式带用户声明单位，例如：

```bash
kt solve model.output --var model.time --equals "100 damage" --range "0 time:10 time"
```

结果状态：

- `exact`：完整有限精确解集。
- `numeric_approximate`：求解器确实返回浮点有限解时使用。
- `no_solution_proven`：符号求解器确认空集，或完整有限候选全部违反显式定义域。
- `incomplete`：条件集合、无限集合或未完成集合；CLI 返回非零。
- `timeout`：工作进程被实际终止。

当前没有一般数值根搜索，因此“没有搜索到根”不会被报告成无解。

## 13. 扫描、绘图和输出安全

扫描会对每一点：

1. 检查横轴值域。
2. 代入与检查定义域。
3. 计算精确值和受控近似值。
4. 对预期的定义域/参数错误记录原因和空值。
5. 对非预期内部错误终止操作，而不是伪装成普通断点。

若整条曲线没有有效点，结果包含警告。CSV 每行同时保存单位、有效参数、依赖 id 和精度元数据。

文件写入使用临时文件和原子落位：

- 默认只允许工作区内路径。
- 默认拒绝覆盖。
- `--allow-outside-workspace` 和 `--force` 必须显式提供。
- run 记录永远不允许覆盖。

## 14. 运行记录 v2

记录嵌入实际依赖条目和所有使用的语义声明条目。每个快照保存原始 UTF-8 YAML、结构内容、源哈希和规范内容哈希。重放从快照构造隔离工作区，不发现当前定义目录。

记录同时保存软件版本、Kirin Tor 实现文件哈希和产物哈希。即使开发者忘记提升版本号，代码内容变化也会被视为环境漂移。重放会报告 `environment_match`、`version_drift` 和实际结果比较；版本漂移时不会声称环境完全一致。成功与失败运行都可重放。绘图可选择在新路径重新生成 SVG/PNG/CSV。

## 15. 固定限制

| 对象 | schema v1 限制 |
|---|---:|
| 工作区 YAML 文档 | 5,000 |
| 工作区 YAML 总量 | 50,000,000 bytes |
| 单 YAML 文件 | 1,000,000 bytes |
| 单运行记录 | 200,000,000 bytes |
| YAML 结构 | 20,000 nodes，40 层；禁用 aliases |
| 单公式 | 2,000 字符 |
| 公式 AST | 200 nodes，30 层 |
| 单公式直接依赖 | 50 |
| 单条目输入／单函数参数 | 100 |
| 依赖展开深度 | 100 |
| 依赖闭包条目 | 500 |
| 展开数学树 | 10,000 nodes |
| 数值文本 | 200 字符 |
| 十进制数量级 | 绝对值不超过 1,000 |
| 常数指数绝对值 | 100 |
| 量纲指数绝对值 | 100 |
| 单个有限允许值集合 | 1,000 项 |
| 数值精度 | 2–100 位 |
| 有限和 | 10,000 项 |
| 扫描/绘图 | 10,000 点 |
| 默认计算超时 | 10 秒 |
| 可请求的最大超时 | 300 秒 |

公共计算操作把表达式解析、引用展开、SymPy 运算和逐点扫描放入独立工作进程。超时或用户中断会 terminate；进程仍存活时会 kill 并 join。Windows 使用 `spawn`，POSIX 使用 `fork`，两者采用相同的终止协议。

## 16. 错误与 JSON

计算和检查命令支持 `--json`。JSON 只写 stdout；诊断和非阻断警告写 stderr；失败返回非零状态。

schema 和表达式错误尽量包含：

- 文件路径、行、列。
- 条目 id。
- schema 字段或公式位置。
- 稳定错误代码和可理解原因。

`kt check` 会汇总可独立发现的多个错误。循环依赖和函数递归会显示闭合路径。
