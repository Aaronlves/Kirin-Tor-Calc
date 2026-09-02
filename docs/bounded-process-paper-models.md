# Kirin Tor 有界 Process 纸面模型

状态：目标语义验证。本文的 Process、scenario 和 analysis 声明已经可解析、完整检查表达式类型、
lower、验证静态批次冲突并无损往返；执行仍未实现，因此完整片段已是合法 `.kirin` source，但尚不
会产生运行结果。

本文使用[有界 Process 模型](bounded-process-model.md)中的同一组游戏中立原语，检验六类差异较大的
游戏机制能否在不增加机制专用内核关键字的情况下完整表达。示例数值都是验证数据，不代表任何真实
游戏版本；其中伤害延迟案例使用本次讨论明确给出的规则。

纸面模型的职责是验证表达能力、可读性、结算顺序和边界。当前自动化验证证明九个 Process 可以进入
带可执行表达式节点的统一 IR，酒仙 Scenario 与 Analysis 也进入组合 IR；它不证明 engine、CLI 或
工作台动态预览已经实现。

## 1. 候选最小表面语法

本轮冻结以下动态词汇作为 AST 与 parser 实现的输入；允许后续调整标点和不改变语义的简写，不能在
实现阶段为单个游戏机制添加新的语义类别。

### 1.1 Process

```text
process ID ["LABEL"]:
  input ID ["LABEL"]: TYPE [= DEFAULT] [in MIN..MAX]
  state ID ["LABEL"]: TYPE = INITIAL [in MIN..MAX]
  require CONDITION
  key ID
  phase ID

  event input ID([ID: TYPE [reduce REDUCER], ...])
  event output ID([ID: TYPE, ...])
  event internal ID([ID: TYPE, ...])
  action ID(PARAMETERS) [when CONDITION]

  flow STATE(current, elapsed) = EXPRESSION

  on EVENT(PARAMETERS) [when CONDITION]:
    let ID: TYPE = EXPRESSION
    next STATE = EXPRESSION
    emit EVENT(ARGUMENTS) [phase PHASE]
    schedule EVENT(ARGUMENTS) after DURATION phase PHASE key KEY
    replace EVENT(ARGUMENTS) after DURATION phase PHASE key KEY
    cancel KEY
    when CONDITION:
      EFFECTS
    branch ID independent|joint:
      probability EXPRESSION:
        EFFECTS

  observe ID ["LABEL"]: TYPE = EXPRESSION
```

事件参数使用与函数参数相同的类型语法，但没有默认值。`event input`、`event output` 和
`event internal` 分别是输入端口、输出端口和组件私有事件。`action` 是带可用条件的公开决策事件。
没有匹配处理器或 handler guard 为假的 input/internal 事件对该 process 是明确的 no-op。Action guard
为假时该 action 不可选；固定策略仍选择它是明确失败，不能解释为 no-op 或 `wait`。

`next`、`emit`、`schedule`、`replace` 和 `cancel` 统称 effect。嵌套 `when` 只选择有限 effect。
概率分支各自包含完整 effect 集；某分支没有 `next` 时状态保持不变。

现有 `domain` 同时增加封闭 symbolic 写法：

```text
domain ID ["LABEL"]:
  - SYMBOL ["LABEL"]
```

Symbol 使用稳定 ASCII ID，显示名不参与相等判断或引用。

目标 `TYPE` 在现有标量、domain 和封闭 object 之外增加 `event_id`、`list[VALUE_TYPE, CAPACITY]` 与
`map[KEY_TYPE, VALUE_TYPE, CAPACITY]`。容量必须是 source 中的正整数常量，不接受运行时表达式。
`key ID` 声明 process 私有的稳定 `event_key`；运行时 `event.id` 也可以用作动态 key。
`phase ID` 声明 process 使用的本地 phase slot；scenario 实例化时必须逐一映射到自己的 phase。

### 1.2 Scenario

```text
scenario ID ["LABEL"]:
  phases:
    - PHASE

  use INSTANCE = PROCESS:
    INPUT = EXPRESSION
    phase PROCESS_PHASE = SCENARIO_PHASE

  connect INSTANCE.OUTPUT -> INSTANCE.INPUT

  at TIME phase PHASE:
    send INSTANCE.EVENT(ARGUMENTS)

  every INTERVAL from START [until END] phase PHASE:
    send INSTANCE.EVENT(ARGUMENTS)

  action ID [when OBSERVATION_CONDITION]:
    send INSTANCE.EVENT_OR_ACTION(ARGUMENTS) phase PHASE

  decide every INTERVAL from START [until END] phase PHASE:
    - ACTION
    - wait

  stop when OBSERVATION_CONDITION
  bounds:
    horizon = DURATION
    maximum_events = INTEGER
    maximum_decisions = INTEGER
    maximum_branches = INTEGER
    maximum_entities = INTEGER
```

Scenario 的组合 action 是一次选择，可以向多个实例发送事件；这些事件在指定 phase 作为同一批次
发生，并在该 phase 的转移开始前一次性构造；它们不是 handler 运行中产生的同 phase 事件。各实例
仍只更新自己拥有的状态。Process 的私有状态不能直接出现在 scenario 条件中，必须先导出为
observation。

`at`、`every`、`decide` 都只在 horizon 内展开。最终 grammar 可以为固定序列提供更短写法，但简写
必须降低为这里的普通调度和选择，不能获得额外执行语义。

### 1.3 Analysis

```text
analysis ID ["LABEL"]:
  using = SCENARIO
  operation = run|compare|optimize|reach|steady|cycle
  [policy = POLICY]
  [objective maximize|minimize OBSERVATION]
  [then maximize|minimize OBSERVATION]
```

`policy` 只用于需要固定策略的操作，`objective` 与 `then` 只用于需要目标和并列判定的操作。分析声明
不改变 scenario 或 process；同一个 scenario 可以有多个独立分析。分析器只能读取公开 observation
和引擎提供的 `elapsed`、事件计数等运行 observation。

## 2. 多资源、冷却与顺序充能

这个模型同时验证连续回复、动作开始/结束、动作局部冷却、顺序恢复的充能和零回复资源。`mana` 与
`rage` 是 source 声明的普通单位，不是内核资源类型。

```text
dimension mana
dimension rage
unit mana = mana
unit rage = rage
unit mana_per_time = mana / time

process combat_resources "资源与就绪状态":
  input maximum_mana: mana
  input mana_regeneration: mana_per_time
  input maximum_rage: rage
  input blast_cooldown: time
  input orb_recharge: time
  input maximum_orb_charges: positive_integer in 1..64

  state mana: mana = maximum_mana in 0..maximum_mana
  state rage: rage = 0 in 0..maximum_rage
  state blast_ready: boolean = true
  state orb_charges: count = maximum_orb_charges in 0..maximum_orb_charges

  event internal blast_finished()
  event internal blast_ready_again()
  event internal orb_charge_ready()

  key blast_cooldown
  key orb_recharge
  phase finish
  phase readiness

  action arcane_blast() when mana >= 30 mana and blast_ready
  action arcane_orb() when orb_charges >= 1
  action arcane_barrage() when rage >= 20 rage

  flow mana(current, elapsed) = min(maximum_mana, current + mana_regeneration * elapsed)

  on arcane_blast():
    next mana = mana - 30 mana
    next blast_ready = false
    schedule blast_finished() after 3/2 second phase finish key event.id
    replace blast_ready_again() after blast_cooldown phase readiness key blast_cooldown

  on blast_finished():
    next rage = min(maximum_rage, rage + 10 rage)

  on blast_ready_again():
    next blast_ready = true

  on arcane_orb():
    next orb_charges = orb_charges - 1
    when orb_charges == maximum_orb_charges:
      schedule orb_charge_ready() after orb_recharge phase readiness key orb_recharge

  on orb_charge_ready():
    next orb_charges = orb_charges + 1
    when orb_charges + 1 < maximum_orb_charges:
      schedule orb_charge_ready() after orb_recharge phase readiness key orb_recharge

  on arcane_barrage():
    next rage = rage - 20 rage

  observe current_mana: mana = mana
  observe current_rage: rage = rage
  observe available_orbs: count = orb_charges
```

当第一枚充能在恢复时再次消耗充能，不会再创建第二个恢复事件；只有从满层首次消耗时才启动 keyed
恢复链。每次 `orb_charge_ready` 最多恢复一枚，并在仍不满时安排下一枚，因此没有“并行恢复”的
隐藏假设。冷却缩减或重置只需 `replace`/`cancel` 同一个 `blast_cooldown` key，不需要新内核能力。

## 3. 伤害延迟池、清除与治疗决策

验证规则如下：最大生命归一化为输入；80% 来袭伤害进入延迟池，余下部分立即承受；每 0.5 秒按
作者给出的 `pool / 20` 规则结算；活血酒清除当前总池的 50%，并恢复清除量的 25%；有两枚顺序恢复
充能，每枚恢复时间八秒。这些都是本纸面案例的输入规则，不声称对应任何正式游戏版本。

```text
dimension vitality
unit health = vitality
unit damage = vitality

process delayed_damage "伤害延迟池":
  input maximum_health: health
  input maximum_pool: damage
  input conversion: probability = 80%
  input clear_ratio: probability = 50%
  input healing_ratio: probability = 25%

  state health: health = maximum_health in 0..maximum_health
  state pool: damage = 0 in 0..maximum_pool

  event input incoming_damage(amount: damage reduce sum)
  event input stagger_tick()
  event input purify()

  on incoming_damage(amount):
    let delayed: damage = amount * conversion
    next health = max(0 health, health - (amount - delayed))
    next pool = pool + delayed

  on stagger_tick():
    let tick_damage: damage = pool / 20
    next health = max(0 health, health - tick_damage)
    next pool = pool - tick_damage

  on purify():
    let cleared: damage = pool * clear_ratio
    let restored: health = cleared * healing_ratio
    next pool = pool - cleared
    next health = min(maximum_health, health + restored)

  observe alive: boolean = health > 0 health
  observe remaining_health: health = health
  observe stagger_remaining: damage = pool

process sequential_charges "顺序恢复充能":
  input maximum_charges: positive_integer in 1..64
  input recharge: time
  require recharge > 0 second

  state available: count = maximum_charges in 0..maximum_charges

  event input consume()
  event internal charge_ready()

  key recharge_chain
  phase readiness

  on consume() when available >= 1:
    next available = available - 1
    when available == maximum_charges:
      schedule charge_ready() after recharge phase readiness key recharge_chain

  on charge_ready():
    next available = available + 1
    when available + 1 < maximum_charges:
      schedule charge_ready() after recharge phase readiness key recharge_chain

  observe ready: boolean = available >= 1
  observe count: count = available

scenario brewmaster_survival "活血时机":
  phases:
    - periodic_tick
    - incoming
    - readiness
    - decision

  use actor = delayed_damage:
    maximum_health = 100 health
    maximum_pool = 30000 damage

  use brew = sequential_charges:
    maximum_charges = 2
    recharge = 8 second
    phase readiness = readiness

  action purifying_brew when actor.alive and brew.ready:
    send actor.purify() phase decision
    send brew.consume() phase decision

  every 1/2 second from 1/2 second phase periodic_tick:
    send actor.stagger_tick()

  every 1/2 second from 1/2 second phase incoming:
    send actor.incoming_damage(amount = 50 health)

  every 3 second from 3 second phase incoming:
    send actor.incoming_damage(amount = 200 health)

  decide every 1/2 second from 0 second phase decision:
    - purifying_brew
    - wait

  stop when not actor.alive
  bounds:
    horizon = 60 second
    maximum_events = 1000
    maximum_decisions = 121
    maximum_branches = 10000
    maximum_entities = 2

analysis latest_death "最晚死亡":
  using = brewmaster_survival
  operation = optimize
  objective maximize elapsed
  then maximize brew.count
```

同一时间先结算旧的周期伤害，再加入两种来袭伤害，恢复充能，最后作决策。两个 incoming 事件通过
参数上显式声明的 `sum` reducer 合成一次处理。组合 action 同时向伤害池和充能组件发送事件；两个
组件各自只更新自己的状态。若作者需要另一种游戏规则，只改变 phase 顺序，不依赖文件或事件插入
顺序。`maximum_pool` 是分析边界，超过时运行失败；它不会通过截断改变机制结果。这个案例不需要
`stagger`、`health`、`heal` 或 `charge` 内核关键字。

## 4. 可刷新、快照或动态取值的 DoT

`mode` 决定 tick 使用施加时保存的强度，还是每次 tick 读取当前强度。重施效果会替换同 key 的下一
次 tick 并重置剩余次数。事件载荷与 process 状态足以区分快照和动态更新。

```text
domain dot_mode:
  - snapshot
  - dynamic

process periodic_damage "可刷新周期伤害":
  input interval: time
  input tick_count: positive_integer in 1..1000
  input coefficient: dimensionless

  state target_health: health = 1000 health in 0..1000 health
  state current_power: damage = 100 damage in 0..10000 damage
  state saved_power: damage = 0 damage in 0..10000 damage
  state remaining_ticks: count = 0 in 0..tick_count
  state mode: dot_mode = snapshot

  event input apply_dot(selected_mode: dot_mode)
  event input change_power(new_power: damage)
  event internal dot_tick()

  key active_dot
  phase periodic_tick

  on apply_dot(selected_mode):
    next mode = selected_mode
    next saved_power = current_power
    next remaining_ticks = tick_count
    replace dot_tick() after interval phase periodic_tick key active_dot

  on change_power(new_power):
    next current_power = new_power

  on dot_tick() when remaining_ticks > 0:
    let power: damage = if_else(mode == snapshot, saved_power, current_power)
    let tick_damage: damage = power * coefficient
    next target_health = max(0 health, target_health - tick_damage)
    next remaining_ticks = remaining_ticks - 1
    when remaining_ticks > 1:
      schedule dot_tick() after interval phase periodic_tick key active_dot

  observe health_remaining: health = target_health
  observe ticks_remaining: count = remaining_ticks
```

若实际规则是每次重施只延长持续时间、不重置下一 tick，只需保留既有 keyed tick，另外替换到期事件。
规则差异在 source 中可见，不需要内核猜测“刷新”的含义。HoT 使用相同模型，只把输出事件连接到
治疗处理器。

## 5. 有序或并行吸收盾

两个模型共享同一种 `incoming_damage` 事件。优先吸收规则显式计算第一层的消耗，再把余量交给第二
层；并行规则显式按当前容量比例分摊。核心不内置护盾顺序。

```text
process priority_shields "有序吸收":
  state outer: damage = 300 damage in 0..300 damage
  state inner: damage = 500 damage in 0..500 damage
  state health: health = 1000 health in 0..1000 health

  event input incoming_damage(amount: damage)

  on incoming_damage(amount):
    let outer_used: damage = min(outer, amount)
    let after_outer: damage = amount - outer_used
    let inner_used: damage = min(inner, after_outer)
    let remainder: damage = after_outer - inner_used
    next outer = outer - outer_used
    next inner = inner - inner_used
    next health = max(0 health, health - remainder)

  observe remaining_health: health = health
  observe total_absorb: damage = outer + inner

process proportional_shields "并行吸收":
  state first: damage = 300 damage in 0..300 damage
  state second: damage = 500 damage in 0..500 damage
  state health: health = 1000 health in 0..1000 health

  event input incoming_damage(amount: damage)

  on incoming_damage(amount):
    let capacity: damage = first + second
    let absorbed: damage = min(capacity, amount)
    let first_used: damage = if_else(capacity > 0 damage, absorbed * first / capacity, 0 damage)
    let second_used: damage = absorbed - first_used
    next first = first - first_used
    next second = second - second_used
    next health = max(0 health, health - (amount - absorbed))

  observe remaining_health: health = health
  observe total_absorb: damage = first + second
```

若护盾属于不同组件，scenario 可以把一次攻击转换成 successive phase，或用一个显式 reducer 组件
生成分配后的类型化事件。多个组件不能竞争写同一个生命状态。

## 6. 独立到期与整体刷新的 Buff 层数

独立到期需要为每一层保存稳定 ID 和到期事件；整体刷新只需要一个计数和一个 keyed 到期事件。
有界 map 与 `event.id` 使二者都不需要特殊 Buff 语义。

```text
process independent_stacks "独立到期层数":
  input duration: time
  input maximum_stacks: positive_integer in 1..100

  state expiries: map[event_id, time, 100] = empty

  event input add_stack()
  event internal expire_stack(stack: event_id)

  phase expiration

  on add_stack() when size(expiries) < maximum_stacks:
    next expiries = put(expiries, event.id, event.time + duration)
    schedule expire_stack(stack = event.id) after duration phase expiration key event.id

  on expire_stack(stack) when contains(expiries, stack):
    next expiries = remove(expiries, stack)

  observe stacks: count = size(expiries)

process refreshing_stacks "整体刷新层数":
  input duration: time
  input maximum_stacks: positive_integer in 1..100

  state stacks: count = 0 in 0..maximum_stacks

  event input add_stack()
  event internal expire_all()

  key buff_expiration
  phase expiration

  on add_stack():
    next stacks = min(maximum_stacks, stacks + 1)
    replace expire_all() after duration phase expiration key buff_expiration

  on expire_all():
    next stacks = 0

  observe current_stacks: count = stacks
```

`map[event_id, time, 100]` 的容量是计算上限；`maximum_stacks` 是机制参数且不能超过容量。满层时新增
独立层没有匹配处理器，因此明确保持原状态。若规则要求替换最早层，应由 source 在非空 guard 下
使用有界 map 的 `argmin` 找到最早到期 key，再显式 `remove` 和 `replace`。

## 7. 独立与相关触发、条件动作

独立触发每次攻击重新作一次有限选择。相关触发在一次 joint 分支中产生两个结果，不能由内核把两个
边际概率相乘。条件 action 只在至少有一层 proc 时可用。

```text
process proc_combat "触发与消费":
  input proc_chance: probability
  input proc_damage: damage
  input consume_damage: damage
  input both_probability: probability
  input first_only_probability: probability
  input second_only_probability: probability
  input neither_probability: probability

  require both_probability
        + first_only_probability
        + second_only_probability
        + neither_probability == 1

  state proc_stacks: count = 0 in 0..2
  state total_damage: damage = 0 damage in 0..1000000 damage

  event input independent_attack()
  event input paired_attack()
  event output proc_missed()
  action consume_proc() when proc_stacks >= 1

  phase aftermath

  on independent_attack():
    branch proc_roll independent:
      probability proc_chance:
        next proc_stacks = min(2, proc_stacks + 1)
        next total_damage = total_damage + proc_damage
      probability 1 - proc_chance:
        emit proc_missed() phase aftermath

  on paired_attack():
    branch pair_roll joint:
      probability both_probability:
        next proc_stacks = min(2, proc_stacks + 2)
        next total_damage = total_damage + 2 * proc_damage
      probability first_only_probability:
        next proc_stacks = min(2, proc_stacks + 1)
        next total_damage = total_damage + proc_damage
      probability second_only_probability:
        next proc_stacks = min(2, proc_stacks + 1)
        next total_damage = total_damage + proc_damage
      probability neither_probability:
        emit proc_missed() phase aftermath

  on consume_proc():
    next proc_stacks = proc_stacks - 1
    next total_damage = total_damage + consume_damage

  observe available_proc_stacks: count = proc_stacks
  observe damage_done: damage = total_damage
```

两个 `probability` 恰好相同的单触发分支也不会因此被推断为独立；只有 `independent` 声明允许按调用
次数组合。`joint` 的四个输入值是作者给出的联合分布，验证器只检查范围与精确归一。

## 8. 能力审计结果

| 案例 | 使用的通用能力 | 是否需要机制专用内核语义 |
| --- | --- | --- |
| 多资源、冷却、充能 | 状态、flow、action、keyed schedule | 否 |
| 伤害延迟与治疗决策 | 状态、phase、周期事件、action、analysis objective | 否 |
| 快照/动态 DoT | 事件载荷、状态、replace、周期调度 | 否 |
| 有序/并行护盾 | 局部值、同时 next、显式公式或 reducer | 否 |
| 两类 Buff 层数 | 有界 map、event.id、schedule/replace | 否 |
| 独立/相关触发 | 有限 branch、显式 independence/joint、guard | 否 |

纸面审计发现并补入基础规范的通用缺口是：

1. `input/output/internal` 三种事件方向；
2. 可重放的稳定 `event.id`；
3. 数值 domain 之外的封闭 symbolic domain；
4. `size/contains/get/put/remove/filter/sum/argmin/argmax` 有界集合总函数；
5. 同批同类事件的显式参数 reducer；
6. handler 内有限 `when` effect；
7. process 导出 observation，scenario 只能通过 observation 制定策略和目标；
8. process 本地 phase slot 到 scenario 全局 phase 的显式映射；
9. scenario 组合 action，用一次决策协调多个私有状态组件。

加入这些能力后，六类案例都不需要 `resource`、`cooldown`、`charge`、`stagger`、`shield`、`dot`、
`buff` 或 `proc` 内核关键字。它们可以作为普通 `.kirin` process 在 Community Package 中定义。

## 9. 冻结边界与下一步

冻结的是语义类别和上面的最小词汇，不是最终排版。下一步建立类型化 AST 与 process IR 时，不得：

- 为六个案例增加专用 AST 节点；
- 让分析器绕过统一 transition 合同直接修改状态；
- 用 source 顺序补足未声明的 phase；
- 让集合操作继承 Python/JavaScript 的异常、迭代或键顺序；
- 因实现方便而把私有状态暴露给 scenario；
- 把 fuel 耗尽后的部分结果标记为完整结果。

仍可在实现前调整的只有：参数标点、label 位置，以及固定序列等不增加语义的简写。若 AST 实现需要
新增语义原语，必须先回到这六个案例证明它是跨机制能力。
