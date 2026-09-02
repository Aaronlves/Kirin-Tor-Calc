# Kirin Tor 有界 Process 模型

状态：目标设计；Process/Scenario/Analysis 的类型化 AST、IR、公开 workspace parser/renderer、完整
表达式类型检查与安全求值、lowering、process 内及静态场景批次冲突验证、精确时间执行器与 trace，
以及具名 run/compare/optimize/reach/steady/cycle 分析分派已经实现；旧动态构造迁移与工作台切换尚未
完成。

本文是动态机制重构的语义依据。它规定 Kirin Tor 下一阶段应当提供的通用计算能力，
但不改变当前 `.kirin` 文件的解析或求值行为。在切换完成前，当前行为仍以
[Kirin Tor source syntax v2](kirin-syntax.md)、
[结构模型、表达式与安全边界](schema-and-expressions.md)和测试为准。

本文固定语义；配套纸面模型冻结首批动态词汇，但不冻结参数标点、缩进和不增加语义的简写。
文中的 source 片段都是目标语义示意，不能当作当前可执行语法。

六类机制对这套语义与候选表面语法的纸面验证见
[有界 Process 纸面模型](bounded-process-paper-models.md)。

## 1. 为什么重构

当前语言分别实现普通表达式、有限递推、有限状态解析模型和固定 cycle。固定 cycle 又通过
`cycle_step`、`cycle_profile` 接口为资源、冷却和充能赋予专用语义。继续在这些接口上加入
伤害池、护盾、效果刷新、重置、触发、目标状态和决策，会使每一种新机制都要求新的内核合同。

目标不是把 Kirin Tor 变成通用脚本语言，而是让游戏机制由 `.kirin` source 或 Community
Package 使用少量游戏中立原语组合出来。内核只理解类型、状态、时间、事件、动作、选择、概率、
边界和分析，不理解生命、伤害、法力、醉拳、护盾或任何具体游戏名词。

## 2. 模型分层

目标语言分为三个动态层次：

1. `process` 定义一类可复用组件的参数、私有状态、事件、动作和状态转移；
2. `scenario` 实例化并组合 process，给出初始值、外部事件、运行边界和可选策略；
3. `analysis` 选择运行、比较、优化、可达性、稳态或周期证明，不改变模型定义。

静态声明继续负责精确值与可复用数据：`dimension`、`unit`、`domain`、`input`、`field`、
`function`、`type`、具名对象、`source`、`preset`、`output`、`display` 和 `chart`。

`scenario` 是 process 的组合和运行入口，不拥有另一套状态转移语义。分析器也不能通过隐式规则
补全模型没有声明的事实。

## 3. 形式合同

一个 process 的单次转移可以抽象为：

```text
transition(current_state, event, optional_choice)
  -> finite_distribution(
       next_state,
       scheduled_events,
       observations
     )
```

- `current_state` 是事件所在阶段开始时的只读快照；
- `event` 具有稳定类型、精确时间和封闭的类型化载荷；
- `optional_choice` 只在声明的决策点存在；
- 确定性转移是概率恰为一的单分支有限分布；
- 随机转移必须显式列出有限结果及精确概率；
- `next_state` 同时生效，不按赋值文本的先后顺序逐句修改；
- `scheduled_events` 只能包含类型正确且符合运行边界的事件；
- `observations` 是派生输出，不能反向修改状态。

任何分析都只能观察这个合同。专用分析器可以要求模型满足更窄的条件，但不能为同一个 process
发明另一套执行语义。

## 4. 参数、状态和局部值

### 4.1 参数

参数在一次运行内不可变，使用现有精确数值、布尔、单位、domain、封闭类型和静态成员路径。
Preset 与临时覆盖仍只作用于正式输入；覆盖合并后才构造初始状态和事件。

### 4.2 状态单元

每个状态单元具有稳定 ID、声明类型、初始表达式和唯一 owning process。状态可以是：

- 精确数值或布尔；
- 命名 domain 的值；
- 封闭的类型化对象；
- 具有显式最大容量的同类型序列或按稳定 ID 索引的有限集合。

命名 domain 在目标语义中可以继续约束数值，也可以声明有限个稳定 symbolic value。Symbolic value
使用 canonical ASCII ID，中文等显示名仍然只属于 presentation。

有界集合只提供总函数操作，例如 `size`、`contains`、`get`、`put`、`remove`，以及受容量约束的
`filter`、`sum`、`argmin` 和 `argmax`。插入已满集合、读取不存在的 key、在空集合上求极值或构造
重复 key 都必须由类型、guard 或显式失败分支处理，不能继承宿主语言行为。引擎提供不可伪造、可
重放的 `event.id` 类型，供独立到期层数、挂起效果和其他有限实体作稳定 key。

状态单元的值必须始终满足其类型、单位和值域。集合不能在运行中突破声明容量。游戏意义上的
“没有上限”不能绕过计算边界；作者应声明本次 scenario 的分析上限，并明确它是分析边界而非
游戏规则。

### 4.3 局部值与下一状态

事件处理器可以声明不可变局部值，并为自己拥有的状态单元定义 `next`：

```text
let cleared = pool * clear_ratio
next pool = pool - cleared
emit healing(amount = cleared * healing_ratio)
```

`let` 只命名当前转移中的表达式。`next` 是从同一个当前快照到下一快照的定义，不是通用可变赋值。
一个转移中同一状态单元只能定义一次 `next`；未定义时保持原值。

Process 不能直接写入另一个 process 的私有状态。组件协作必须发送类型化事件；这使状态所有权、
依赖关系和运行记录保持明确。

## 5. 时间和事件

### 5.1 精确时间

事件时间使用现有精确 `time` 量纲。场景时间从零开始，调度时间不得早于当前时间。周期声明只是在
horizon 内生成有限事件的简写，不产生无界后台任务。

每个事件具有 `event.id`、`event.time`、类型化载荷和方向：`input` 事件可由 scenario 或连接发送给
process，`output` 事件供连接或观察使用，`internal` 事件只由 owning process 调度。方向不授予读取或
写入其他组件状态的权限。

### 5.2 阶段与同时发生

Scenario 必须声明同一时间点的有序 phase，例如：

```text
phases:
  - periodic_tick
  - incoming
  - decision
  - aftermath
```

Process 中引用的 phase 是本地 phase slot。实例化时，scenario 必须把每个被引用的 slot 映射到自己
声明的全局 phase；不能依靠相同拼写自动连接。这样两个 Package 可以各自使用 `tick`、`finish` 等
局部名称，而不会暗中共享结算顺序。

同一时间、同一 phase 的事件构成一个批次，全部读取 phase 开始时的状态。批次内若两个处理器试图
写入同一状态单元，验证失败；需要顺序差异的规则必须放入不同 phase。Source 文本顺序、文件顺序、
对象 ID 的字典序和运行时容器顺序都不能成为隐藏的结算顺序。

同一目标、同一类型的多个 input 事件可以在事件参数上声明显式 reducer，例如对伤害量使用 `sum`。
Reducer 在处理器运行前把整个批次合成一个事件；未声明 reducer 时不能自动相加、覆盖或取最后值。
合成事件的 ID 由目标、事件类型、时间、phase 和全部来源事件 ID 的规范化集合确定，因此不依赖到达
顺序并可以重放。

首批 reducer 只接受按参数类型定义且满足结合律、交换律的内建 `sum`、`min`、`max`、`all` 和
`any`。同一事件的未归约参数必须全部相等，否则批次验证失败。Reducer 必须保持参数类型与单位，
不能调用作者函数或依赖容器迭代顺序；因此引擎可以在不改变结果的情况下规范化来源事件顺序。

在当前时间调度的新事件只能进入更晚的 phase；否则必须调度到未来时间。这条规则阻止零时间事件环。

### 5.3 调度、刷新和取消

处理器可以：

- `emit` 一个立即进入允许的更晚 phase 的事件；
- `schedule` 一个未来事件；
- 使用稳定 key `replace` 尚未发生的事件；
- 使用稳定 key `cancel` 尚未发生的事件。

刷新持续效果等价于替换同 key 的到期或 tick 计划；重置冷却等价于取消或替换恢复事件。事件 key、
原事件、替换和取消都进入 trace 与运行记录。

静态 key 必须在 owning process 中声明；每个 `event.id` 也可以直接作为动态 key。`schedule` 要求该 key
当前没有挂起事件，否则明确失败；`replace` 无论旧事件是否存在都会留下且只留下一个新事件；
`cancel` 在 key 不存在时是可重放的 no-op。Key 只标识调度槽，不携带游戏含义。

### 5.4 时间推进

Process 可以为自己拥有的数值状态声明事件之间的 `flow(current, elapsed)`。Flow 是作者提供的
封闭表达式，不由内核求解微分方程。所有 flow 在时间跳转时读取同一个时间段起点快照并同时生效。

线性资源回复可以写成 `min(maximum, current + rate * elapsed)`。不能提供封闭推进表达式的连续模型
需要外部推导、显式离散化，或未来单独授权的数值分析器；内核不能静默近似。

## 6. 事件、动作和策略

普通事件描述世界发生的事情；`action` 描述在满足 guard 时可以选择发生的事件。核心不内置技能、
目标或资源概念。

一个决策点包含有限个可用 action。Scenario 可以：

- 指定一个固定 action 序列；
- 提供一个由纯表达式构成的确定策略；
- 将选择留给 `optimize` 分析器；
- 明确选择 `wait`，但不能依赖未声明的隐式等待。

Guard 只判断动作是否可用，不能改变状态。若多个动作同时可用，模型不能假定优先级；固定策略或
分析请求必须明确选择规则。

Optimizer 只把 guard 为真的 action 放入候选集合。固定策略选择不可用 action 时必须返回带 action、
guard 和源位置的明确失败，不能把它静默解释为 no-op 或 `wait`。普通 input/internal 事件没有匹配
处理器时才是 no-op。

处理器可以用有限嵌套的 `when` 选择 effect；它不能形成回跳或循环。Scenario 可以声明组合 action，
在一次选择中向多个 process 实例发送事件。组合 action 的 guard 只能读取这些实例公开的
observation，发送的事件在指定 phase 作为一个批次处理，因此协调消耗充能和施放效果时也不需要
跨组件写状态。这里的发送集合由决策器在该 phase 的转移开始前一次性构造，是 action 本身的展开；
它不是某个 handler 在运行中向当前 phase 新增事件。Handler 内的 `emit` 仍只能进入更晚的 phase。

## 7. 随机性

随机转移使用有限、精确归一的分布。内核不推断两个事件、两个目标或两个触发相互独立。独立重复
必须由作者或复用组件显式声明；相关结果应作为一个联合事件或联合分布给出。

候选表面语法使用 `branch NAME independent:` 或 `branch NAME joint:`。每个概率分支包含与确定处理器
相同的有限转移效果；`independent` 表示每次处理器调用进行新的独立选择，`joint` 表示一次选择的结果
通过同一事件载荷共享。两者都必须引用或声明一个精确归一的有限分布。

随机分析可以返回精确分布、期望、达到概率或有界分位信息。若状态或分支规模超过预算，操作明确
失败；除非作者选择并记录近似方法，否则不能自动改用抽样。

## 8. 组合规则

Process 通过有方向的类型化事件端口、导出 observation 和动作接口组合。Scenario 用 `connect`
将一个实例的 output 事件连接到另一个实例类型兼容的 input 事件；未连接的 output 仍可进入 trace，
但不会隐式修改任何状态。

- 每个状态单元只有一个 owner；
- 组件只能观察已声明订阅的事件载荷和显式导入的静态参数；
- 组件不能反射或遍历其他组件的内部结构；
- 同一事件可以有多个只读观察者；
- Scenario 的 stop、策略和目标只能读取 process 明确导出的 observation；
- 多个事件对一个量的合并必须使用显式 reducer，例如 `sum`、`min`、`max` 或有序 phase；
- 实例具有稳定 canonical ID，同一 process 可以被多次实例化而不共享私有状态。

这些规则使冷却、充能、伤害池、护盾、持续效果和目标成为可发布的普通组件，而不是新的内核关键字。

## 9. 终止与统一 Fuel

“非图灵完备”不是独立产品目标；强制有界、可预算的权威计算才是目标。所有普通运行必须声明或从
输入上界静态得到：

- `horizon`：最大模型时间；
- `maximum_events`：最多处理的事件；
- `maximum_decisions`：最多决策点；
- `maximum_branches`：最多保留的随机或策略分支；
- `maximum_entities`：最多实例或动态实体；
- 每个集合的 `maximum_size`；
- 表达式、依赖和数值的现有固定限制。

受运行时条件控制的重复必须带静态最大次数。事件链可以继续调度事件，但每次调度都会消耗同一运行
的 event fuel。达到边界时返回带边界名称、消耗量和源位置的失败，不返回截断后冒充完整的结果。

禁止任意导入、文件或网络访问、宿主函数调用、运行时反射、无界递归、无界集合和无 fuel 的事件
自我生成。Community Package 仍然只含数据和 `.kirin` 定义，不获得可执行宿主权限。

## 10. 分析器

首批目标分析器及其职责是：

- `run`：执行一个确定策略，返回最终状态和可选 trace；
- `compare`：对有限个明确策略运行同一场景；
- `optimize`：在有限 action 分支中按声明目标搜索，并记录剪枝与并列规则；
- `reach`：计算终止状态或目标条件的有限可达性；
- `steady`：只接受可证明为有限离散马尔可夫模型的 process；
- `cycle`：只接受满足其单调性和周期证明前提的确定 process。

目标可以是最大化或最小化一个观察值，并提供有序的并列判定。例如“最大化死亡时间，其次最大化
剩余充能”。优化器不能把未声明的偏好当作并列规则。

每个分析器都必须先验证适用前提。无法证明符合时明确拒绝，不能把有界运行结果误报为永久周期、
把抽样误报为精确概率，或把一个找到的策略误报为全局最优。

## 11. Source authority、Package 与重放

Process、scenario 和普通静态声明都属于 `.kirin` source authority。索引、关系图、编辑器投影、trace、
优化搜索树和运行记录不是可反向编辑的模型定义。

Community Package 可以发布游戏通用或游戏专用 process，但不能发布 Python 求值器或替换核心执行
语义。Workbench Plugin 仍只能提供沙箱化视图和声明式操作请求，不能修改 process 结果。

运行记录至少包含：参与的 source 快照和摘要、Package 身份、参数与覆盖、初始状态、外部事件、固定
策略或优化目标、所有 fuel 边界、phase 顺序、分析器和实现摘要。相同记录的重放必须得到相同精确
结果，或明确报告软件环境差异。

## 12. 现有构造的迁移

动态重构不得改变现有静态数值、单位、类型、对象、来源和输入覆盖的含义。

- `process`、`scenario` 和 `analysis` 是目标公开动态语义；
- `recurrence` 可以保留为单一 step 事件 process 的作者简写，但 parser 必须立即降低到同一个 AST/IR，
  不能保留独立 schema 或求值器；
- `state_model` 的有限概率转移迁移为 process，由 `steady`、`reach` 等分析器解释；目标表面名称不再
  使用容易与通用状态混淆的 `state_model`；
- `cycle` 可以保留为固定 action sequence 与 `cycle` analysis 的作者简写，但不能保留专用状态语义；
- `cycle_step`、`cycle_profile`、内建资源、冷却和充能合同不进入目标 IR；它们的能力改由普通
  process 组件表达；
- 现有 `continuous`、`waiting`、`blocked` 结果只能在新模型满足相同证明条件时保持；
- 迁移必须保留 canonical ID、跨 entry 依赖、Package 权限检查和运行记录闭包。

由于尚未投入正式使用，目标是直接完成单一 v2 cutover，不维护两套公开动态语法。实现期间可以有
内部迁移适配器，但不能让旧、新两套 source 同时成为长期权威。

## 13. 纸面能力验收

第一轮纸面验收已经完成，完整模型和发现的通用缺口见
[有界 Process 纸面模型](bounded-process-paper-models.md)。验收覆盖：

1. 多资源消耗、回复、动作冷却和逐枚恢复充能；
2. 伤害延迟池、周期结算、按当前池比例清除和按清除量治疗；
3. 可刷新且可选择快照或动态取值的 DoT/HoT；
4. 多个有优先级或并行规则的吸收盾；
5. 有上限层数、独立到期或整体刷新的 Buff；
6. 显式独立与相关两种随机触发，并包含条件动作选择。

验收不仅检查“理论上能编码”，还要检查 source 是否对攻略作者可读、事件顺序是否明确、每个数值的
来源是否可追踪、错误是否能定位到声明，以及模型是否能在同一个编辑框中完成。若案例需要新的游戏
专用内核关键字，应先修正通用原语，而不是直接为案例加例外。

## 14. 实现顺序与完成条件

1. **已完成：**完成六类纸面模型并冻结最小表面语法；
2. **已完成：**建立独立于当前 raw dictionary 的类型化 AST 和 process IR；
3. **已完成内部链路：**独立 Process parser、AST 到 IR lowering，以及声明命名空间、类型解析、
   所有权引用、事件参数、reducer、phase 和调度 key 的结构验证；九个纸面 Process 均可降低；
4. **已完成：**改造类型化文档容器与 renderer，并在保证 source 往返不丢失后接入公开 workspace
   parser；
5. **已完成静态部分：**表达式结果类型、安全求值、单个 process 转移及可枚举场景批次的写入/调度
   key 冲突、phase 映射与外部事件/决策 fuel 已验证；动态事件链 fuel 由执行器继续落实；
6. **已完成内核：**实现确定性 `run` 与完整 trace；具名 Analysis/CLI 分派在步骤 10 接入；
7. 将现有 recurrence 与 cycle 行为迁移到新 IR，并执行等价回归；
8. **已完成：**实现有限随机分支、source Policy、策略比较和有界优化；
9. **分析器已完成：**实现精确可达、有限离散稳态和确定性周期证明；旧 `state_model` 动态路径仍待
   步骤 7/9 的统一迁移后移除；
10. 同步诊断、补全、高亮、浏览器预览、CLI、Package 校验、运行记录和公开能力文档后，才宣布
    cutover 完成。

完成意味着当前受支持模型的行为等价、新的六类机制无需游戏专用内核扩展、所有执行边界可见且可
重放，并且旧动态语义实现已经删除。仅有目标文档、局部测试或可运行原型都不构成完成。
