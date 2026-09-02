# 结构模型、表达式与安全边界

本页说明 Kirin Tor source v2 解析后的结构、求值规则和硬限制。表面写法见
[Kirin Tor source syntax v2](kirin-syntax.md)。

## 1. 权威与加载

工作区的可编辑权威只有 `entries/**/*.kirin`。本地文档与锁定 Package 文档都经同一个
`@kirin 2` 解析器进入内部模型；已有静态声明进入 raw schema，Process 声明则进入独立的类型化 AST
与不可变 IR。关系图、索引、预览、运行记录和导出不能反向修改数学定义。

每个文件只声明一个 `entry`。正式 ID、成员、类型、对象和属性名使用
`[A-Za-z_][A-Za-z0-9_]*`，且不能以 `__` 开头。文件路径、注释和显示标签都不构成引用身份。

解析器拒绝 v1、未知声明、重复成员、未知对象属性、缺少的必填属性、Tab 缩进和不一致的
嵌套。说明围栏中的内容是例外：它作为不透明 UTF-8 文本保存。

## 2. 精确数值、类型和单位

整数、分数、十进制、科学计数法和百分比在进入 SymPy 前都保留为精确值；源 schema
拒绝二进制浮点数。`25%` 是 `1/4`，`3/2 second` 是带单位的精确数量。

核心只内置游戏中立的 `dimensionless`、`time`、`second`、`millisecond`、
`probability`、`count`、`nonnegative_integer` 和 `positive_integer`。其他量纲、单位和值域由普通
entry 声明。相同语义声明必须结构一致；冲突会同时保留来源位置。

Domain 除数值和布尔值外也可以是封闭 symbolic value 集合。Symbol 使用 ASCII canonical ID，显示
标签不参与相等判断；symbolic domain 不带单位、数值范围或整数约束。同名 symbol 的完整身份包含
domain；无法由期望类型消歧时使用 `domain.symbol`。

输入、函数参数、字段、输出、类型属性、查表、求解目标和扫描范围都经过量纲检查。精确零可以
适配声明量纲，非零表达式不能靠名称或上下文猜测单位。

## 3. 输入与参数优先级

条目 `model` 的输入 `haste` 具有稳定身份 `model.haste`。当前条目内可写短名；CLI、参数方案、
运行记录和跨文档引用使用限定名。短名仅在候选集合中唯一时才被外部操作接受。

参数优先级是：

```text
input default < preset < temporary override
```

输入范围、整数条件、允许值、命名值域和 `require` 条件会同时进入求值条件。符号保留变量、求导/
求解变量和扫描轴不会被默认值提前代入。

## 4. 表达式模型

表达式 AST 只允许数值/布尔字面量、声明名称、静态成员路径、算术、比较、布尔运算和白名单函数。
属性访问会被拆成完整路径后静态解析：

```text
entry.output
entry.object.field
entry.object.nested.leaf
```

不存在运行时反射、动态键、下标访问、赋值、导入、任意函数调用、文件访问或网络访问。任何
`__private` 路径段都会被拒绝。

跨文档依赖、Package 权限、版本约束、循环依赖、输入集合和运行快照都沿同一解析后的依赖闭包
传播。类型化对象中的属性表达式也不例外。

## 5. 封闭结构类型

`type` 解析为 `StructureTypeSpec`：稳定类型 ID、字段表、可选/默认信息和语义接口映射。具名对象
解析为 `StructuredObjectSpec`：类型引用和一棵精确值/表达式树。

校验按声明类型递归执行：

- 每层只接受类型中声明的字段；
- 必填字段必须有值或默认值；
- 嵌套值必须对应另一个声明类型；
- 标量叶节点必须符合布尔、单位或值域；
- 最大嵌套深度为 16；
- 每个 entry 最多 256 个类型、2,000 个对象；每个类型最多 256 个字段。

类型引用可以是本地 `TYPE` 或限定 `ENTRY.TYPE`。未限定类型在工作区中有多个候选时会要求作者
写限定名，不会任选一个。

## 6. Process 状态转移

动态状态只通过类型化 Process effect 更新。每个事件批次读取同一 phase 起点快照；`next`
同时提交，一个批次不能重复写同一状态。事件之间的数值变化由作者声明封闭 `flow`，时间保持精确
有理单位。资源、冷却、充能、延迟池等名称没有内核特权，均由普通 state、guard、event、schedule
和 flow 组合。

Scenario 必须声明 horizon 与事件、决策、分支、实体 fuel。同一动态语义由 `run`、`compare`、
`optimize`、`reach`、`steady` 和 `cycle` Analysis 读取；分析器可以要求更窄的可证明前提，
但不能引入另一套状态推进规则。固定 action sequence 是 source Policy，周期结果只在完整精确状态重现
后成立。

## 7. 其他有界结构

- 查表要求严格递增、唯一的精确键；`lookup` 精确匹配，`interpolate` 只做范围内线性插值。
- 有限分布要求结果量纲一致，概率在 `0..1` 且精确归一；独立性只能由作者通过组合函数显式声明。
- Process 重复必须消耗显式 event/decision fuel；耗尽边界会失败而不是返回截断结果。
- `steady` 只接受可枚举的有限 Process 状态空间；非唯一或非精确有理稳态会失败。
- 扫描最多 10,000 个点；联立求解最多八个方程和变量。

所有操作都受表达式深度、节点数、展开大小、依赖数、数值长度、精度和进程级超时限制。限制值以
`src/kirin_tor/limits.py` 为准；触发限制不会返回伪造的近似结果。

## 8. 有界 Process 的接入边界

Process source 不进入静态声明 raw dictionary。Source parser 生成保留位置的 `ProcessAst`，workspace 加载
时再解析单位、domain、集合容量和成员引用，生成不可变 `ProcessIR`。`Entry.process_asts` 保留可往返
的 source 结构，`Entry.processes` 保存已降低的语义结构；canonical renderer 必须接收这个类型化文档
容器，不能从 raw schema 猜测或重建 Process。

当前加载阶段还完成表达式结果类型推导并生成不可变求值节点，验证声明命名空间、类型存在性、有界
list/map 容量、状态所有权、事件参数、reducer 类型族、handler 参数、事件方向、phase 与 schedule key
引用，以及单次转移内的写入冲突。每个 entry 最多 256 个 Process；每个 Process 最多 1,024 个声明和
4,096 个 effect，effect 最多嵌套 16 层，集合静态容量最多 10,000。

`ScenarioAst`/`ScenarioIR` 与 `AnalysisAst`/`AnalysisIR` 同样位于 raw schema 之外。Workspace 在所有
Process 都已加载后解析跨 entry 实例引用，强制完整 phase 映射和五项 fuel bound，并预检可枚举的
同时间同 phase 批次冲突、外部事件数量和决策数量。确定性 runtime 在每次调度、发射、路由和决策时
继续执行动态 fuel 检查，按 phase 起点快照同时提交 `next`，并记录 flow、reducer 来源、状态、调度、
取消、动作和 stop trace。随机分支由精确有限分支分析器展开，`run`、`compare`、`reach`、`steady` 和
`cycle` 都必须先满足各自前提；任何路径都不会暗中抽样或把 fuel 截断结果标成完整结果。

每次运行还保留有序的公开 observation 快照和公开 output event。Scenario 的类型化 Measure 只从这两类
数据和 `elapsed`/`horizon` 等引擎观察值求值，支持终值、极值、事件求和/计数、条件持续时间、带显式
默认值的首次发生、停止时间、最大回撤、总变化量和时间加权方差；派生 Measure 可以引用其他 Measure
组成普通安全表达式。具名 Objective 仅引用数值 Measure，支持任意有限层字典序目标和布尔约束。有限
策略空间被完整枚举时结果标记为 `exact_global`，并返回最优策略的全部 Measure。

决策来源可以是作者选择的固定周期、公开事件结算后、条件从假到真，或有限个有界连续动作时点。
连续条件只对已证明的仿射非严格比较求精确有理根；其他事件间变化会报 `unsupported`。一般自由时点
搜索必须在 Analysis 中声明 `adaptive_dyadic`、`time_tolerance` 和 `maximum_evaluations`，结果记录为
`best_found` 并回写全部三项设置及预算是否耗尽；它不会暗中转换成一秒或十分之一秒网格。

具名 Scenario variant 是一组经过原 Process input 类型与值域检查的常量覆盖。`optimize` 可列出多个
variant；执行器分别初始化实例、分别搜索并输出 variant × objective 结果，包含生效的覆盖值和每个
最优策略的完整 trace。Variant 不提供私有 state 写入口。

Process Analysis 可以携带最多 64 张图，且不受普通静态 entry “一张 chart”历史结构的限制。
`trajectory` 读取最优 trace 的 observation samples 和公开 marker；`decision_surface` 读取至少两次决策
的候选；`pareto` 用作者声明的两个方向标记非支配点；`variant_comparison` 读取各最优解的同量纲
Measure。结构化 chart rows 随 Analysis 结果生成，SVG/CSV 仅在显式导出请求下写入。

有限随机 Analysis 的 outcome 同时携带路径概率、完整 run 和该路径全部 Measure；数值 Measure 的
`measure_expectations` 在所有路径 Measure 求值完成后才以精确分数聚合。结果字段
`random_semantics` 区分 `strict_finite_output_expectation` 与 `deterministic_scenario`，因此平均输入场景
不会被误标成严格输出期望，也不会自动降级为 Monte Carlo。

## 9. 运行记录与重放

保存运行记录时，Kirin Tor 写入请求、结果、依赖文档原始 source、规范化内容摘要、实现摘要、Python/
依赖版本和产物摘要。`process_analysis` 与旧 `cycle`、`eval`、扫描、求解等操作走同一记录路径。

重放先校验嵌入 source 与结构内容一致，再在隔离的快照工作区执行相同操作。软件环境变化会被报告，
不会被解释成源码变化。

## 10. Package 与安全

社区 Package 只包含数据。manifest、精确依赖版本、Git commit、namespace 和内容摘要经锁文件固定，
然后从内容寻址缓存只读加载。Package 不能运行 Python、安装脚本、Git hook 或其他代码，也不能引用
未声明依赖或工作区本地权威。

浏览器工作台只监听本机回环地址，并使用随机会话令牌、Host/Origin 检查和隔离的长操作进程。前端
高亮、补全和预览不会扩大语言或数学引擎的权限。
