import{F as e,J as t,Mt as n,a as r,c as i,i as a,kt as o,n as s,p as c,r as l}from"./createLucideIcon-fs27rAxj.js";import{t as u}from"./Code-B0qtSTIf.js";import{t as d}from"./TextInput-DfkY1-5d.js";import{t as f}from"./copy-m46mNftu.js";import{m as p,x as m}from"./index-CnOVB2tH.js";var h=n(o(),1),g=[{id:`document`,title:`文档、注释与说明`,summary:`每个 .kirin 文件只声明一个 entry。正式 ID 使用 ASCII；作者注释和长说明可以使用中文。`,keywords:[`entry`,`header`,`comment`,`prose`,`文档`,`注释`,`说明`],rules:[`文件以 @kirin 1 和 @entry ID 开始。`,`// 行是作者注释，不参与 schema。`,`成对的三个或更多连字符包围长说明文本。`],exampleTitle:`最小可计算文档`,code:`@kirin 1
@entry quick_start

// 最小可计算条目

---
这里可以解释来源、假设和适用范围。
---

inputs:
  x "输入": number[dimensionless] = 0.25 in 0..1

outputs:
  result "结果": dimensionless = 1 + x
`},{id:`members`,title:`输入、字段、函数与输出`,summary:`输入保存可变参数，字段保存常量或派生值，函数声明显式参数，输出定义作者希望公开计算的结果。`,keywords:[`inputs`,`fields`,`functions`,`outputs`,`constraints`,`if_else`,`输入`,`字段`,`函数`,`输出`,`约束`],rules:[`输入可以声明默认值、范围、整数要求或有限允许值。`,`字段、函数和输出必须声明单位或值域。`,`约束和函数体使用受限表达式，不执行用户代码。`],exampleTitle:`带约束和函数的条目`,code:`@kirin 1
@entry members_demo

inputs:
  x "比例": probability = 0.25
  enabled "启用": boolean = true

constraints:
  x >= 0
  x <= 1

fields:
  base "基础值": dimensionless = 2

functions:
  scale(n: number[dimensionless]) -> dimensionless =
    base * n

outputs:
  result "结果": dimensionless =
    if_else(enabled, scale(1 + x), 0)
`},{id:`aliases`,title:`中文别名与显示标签`,summary:`正式身份保持稳定的 ASCII ID；局部中文别名方便写公式，双引号标签只改变呈现。`,keywords:[`aliases`,`label`,`unicode`,`canonical`,`别名`,`标签`,`正式 ID`],rules:[`别名只在当前 entry 的公式中生效。`,`跨文档、CLI、参数方案和运行记录继续使用 entry.member。`,`修改显示标签不会改变依赖关系。`],exampleTitle:`局部中文公式名`,code:`@kirin 1
@entry aliases_demo

aliases:
  基础值 = aliases_demo.base

fields:
  base "基础值": dimensionless = 2

outputs:
  total "合计": dimensionless = 基础值 * 2
`},{id:`presets`,title:`分组、参数方案与显示`,summary:`作者可以组织输出、保存常用输入组合并指定显示格式；这些声明仍属于普通源码。`,keywords:[`groups`,`presets`,`display`,`percent`,`分组`,`参数方案`,`显示`,`百分比`],rules:[`分组只组织当前 entry 的输出，不改变数学含义。`,`参数方案写入正式限定输入名。`,`显示规则影响呈现，不改变精确计算值。`],exampleTitle:`保存一个基线方案`,code:`@kirin 1
@entry presets_demo

inputs:
  chance "触发率": probability = 0.25

outputs:
  expected "期望比例": dimensionless = chance

groups:
  summary "摘要":
    expected

presets:
  baseline "基线":
    presets_demo.chance = 0.5

display:
  expected: percent digits 1
`},{id:`tables`,title:`查表与插值`,summary:`有版本边界的离散系数可以直接写成有序查表，并选择精确匹配或区间内线性插值。`,keywords:[`tables`,`lookup`,`interpolate`,`查表`,`插值`,`系数`],rules:[`表必须声明输入和输出单位。`,`lookup 要求精确键；interpolate 在表的范围内线性插值。`,`十进制在 Kirin 中保持精确，不需要加引号。`],exampleTitle:`等级系数表`,code:`@kirin 1
@entry table_demo

inputs:
  level "等级": number[dimensionless] = 2 in 1..3

tables:
  rating "等级换算": dimensionless -> dimensionless:
    1 = 10
    3 = 30

outputs:
  smooth "插值结果": dimensionless = interpolate(rating, level)
`},{id:`distributions`,title:`有限离散分布`,summary:`用精确结果与概率声明有限分布，再显式求期望、方差或某一结果的概率；Kirin 不做随机采样。`,keywords:[`distributions`,`expectation`,`variance`,`probability`,`分布`,`期望`,`方差`,`概率`],rules:[`所有概率必须位于 0..1，并精确归一化为 1。`,`独立组合与重复必须由作者显式声明。`,`分布不能被当作普通标量直接使用。`],exampleTitle:`一次有限触发`,code:`@kirin 1
@entry distribution_demo

inputs:
  chance "触发率": probability = 0.25

distributions:
  proc "触发结果": dimensionless:
    0 @ 1 - chance
    1 @ chance

outputs:
  mean "期望": dimensionless = expectation(proc)
  spread "方差": dimensionless = variance(proc)
  triggered "触发概率": dimensionless = probability(proc, 1)
`},{id:`recurrences`,title:`有限递推`,summary:`递推从初始值出发执行静态有界的纯函数步骤，不创建可变运行时状态或事件时间线。`,keywords:[`recurrences`,`initial`,`steps`,`next`,`递推`,`步数`,`失败保护`],rules:[`步数必须是常量或具有静态有限范围的整数输入。`,`current 和 index 只在 next 表达式中生效。`,`最多展开 1,000 步。`],exampleTitle:`有限增长递推`,code:`@kirin 1
@entry recurrence_demo

inputs:
  step_count "步数": count = 3 in 0..10

recurrences:
  growth "累计值": dimensionless:
    initial = 1
    steps = step_count
    next(current, index) = current + 1

outputs:
  result "递推结果": dimensionless = growth
`},{id:`state-models`,title:`有限状态解析模型`,summary:`有限状态模型精确求稳态、奖励、到达概率和期望步数；它不是战斗事件模拟器。`,keywords:[`state_models`,`steady_probability`,`steady_reward`,`hitting_probability`,`expected_steps`,`状态`,`稳态`,`奖励`],rules:[`每个状态都必须具有出边，且每一行概率精确归一化。`,`奖励可选，但声明后必须覆盖每个状态并保持单位一致。`,`非唯一稳态或奇异线性系统会明确失败。`],exampleTitle:`两状态触发循环`,code:`@kirin 1
@entry state_demo

state_models:
  cycle "触发循环":
    states:
      ready
      cooldown
    transitions:
      ready -> ready @ 3/4
      ready -> cooldown @ 1/4
      cooldown -> ready @ 1
    rewards:
      value "状态奖励": dimensionless:
        ready = 1
        cooldown = 0

outputs:
  ready_share "可用占比": dimensionless =
    steady_probability(cycle, ready)
  long_run_value "长期奖励": dimensionless =
    steady_reward(cycle, value)
`},{id:`semantics`,title:`量纲、单位与值域`,summary:`游戏词汇由普通 entry 声明；内核只提供游戏中立的数学基础，不根据名字猜测单位。`,keywords:[`dimensions`,`units`,`domains`,`dimensionless`,`量纲`,`单位`,`值域`,`语义`],rules:[`同名语义必须具有相同数学结构。`,`单位比例使用精确数值和量纲代数。`,`值域可以组合范围、整数要求和有限允许值。`],exampleTitle:`自定义强度语义`,code:`@kirin 1
@entry semantics_demo

dimensions:
  power "强度"

units:
  power = power

domains:
  rank: number[dimensionless] in 1..3 integer

inputs:
  base "基础强度": power = 10
  level "等级": rank = 2

outputs:
  result "最终强度": power = base * level
`},{id:`charts`,title:`图表投影与导出`,summary:`图表配置和公式保存在同一个 entry 中；预览自动出现，导出仍需要作者明确选择路径。`,keywords:[`chart`,`x`,`range`,`points`,`y`,`export`,`图表`,`曲线`,`导出`],rules:[`出现任一图表键时，x、range、points 和至少一个 y 必须一起完整声明。`,`as 后的标签只影响曲线显示。`,`导出路径默认必须位于工作区内，已有文件不会被静默覆盖。`],exampleTitle:`一条自动预览曲线`,code:`@kirin 1
@entry chart_demo

inputs:
  x_value "横轴": number[dimensionless] = 0 in 0..1

outputs:
  result "平方": dimensionless = x_value ** 2

x: chart_demo.x_value
range: 0..1
points: 21

y:
  chart_demo.result as "平方曲线"

title: "示例曲线"
x-label: "输入"
y-label: "结果"
`}],_=t(),v=g;function y(e){let t=document.createElement(`textarea`);t.value=e,t.readOnly=!0,t.style.position=`fixed`,t.style.opacity=`0`,document.body.append(t),t.select();let n=document.execCommand(`copy`);return t.remove(),n}function b(e,t){return!t||[e.title,e.summary,e.exampleTitle,...e.keywords,...e.rules,e.code].join(`
`).toLocaleLowerCase().includes(t.toLocaleLowerCase())}function x({initialTopic:t=null}){let[n,o]=(0,h.useState)(``),[g,x]=(0,h.useState)(v[0]?.id??``),[S,C]=(0,h.useState)(null),[w,T]=(0,h.useState)(!1),E=(0,h.useMemo)(()=>v.filter(e=>b(e,n.trim())),[n]),D=E.find(e=>e.id===g)??E[0]??null;(0,h.useEffect)(()=>{!t||!v.some(e=>e.id===t)||(o(``),x(t))},[t]);let O=async e=>{T(!1);try{if(navigator.clipboard?.writeText)await navigator.clipboard.writeText(e.code);else if(!y(e.code))throw Error(`clipboard unavailable`);C(e.id)}catch{y(e.code)?C(e.id):(C(null),T(!0))}};return(0,_.jsxs)(`div`,{className:`syntax-reference`,"aria-label":`Kirin 语法参考内容`,children:[(0,_.jsxs)(`header`,{className:`syntax-reference-header`,children:[(0,_.jsxs)(e,{children:[(0,_.jsx)(r,{className:`page-kicker`,children:`AUTHORING REFERENCE`}),(0,_.jsx)(r,{fw:680,fz:`lg`,children:`在源码旁快速确认写法`}),(0,_.jsx)(r,{c:`dimmed`,fz:`xs`,mt:4,children:`这是随应用发布的只读速查。严格语义和边界仍由当前版本校验器决定。`})]}),(0,_.jsx)(d,{"aria-label":`搜索语法参考`,leftSection:(0,_.jsx)(p,{size:14}),placeholder:`搜索输入、参数方案、分布、图表…`,value:n,onChange:e=>o(e.currentTarget.value)})]}),(0,_.jsxs)(`div`,{className:`syntax-reference-layout`,children:[(0,_.jsx)(c,{className:`syntax-reference-index`,type:`auto`,children:(0,_.jsxs)(`nav`,{"aria-label":`语法主题`,children:[(0,_.jsxs)(r,{className:`nav-group-label`,children:[E.length,` 个匹配主题`]}),E.map(e=>(0,_.jsxs)(`button`,{type:`button`,className:`syntax-reference-link`,"aria-pressed":D?.id===e.id,onClick:()=>{x(e.id),C(null),T(!1)},children:[(0,_.jsx)(`strong`,{children:e.title}),(0,_.jsx)(`small`,{children:e.keywords.slice(0,3).join(` · `)})]},e.id))]})}),(0,_.jsx)(c,{className:`syntax-reference-detail`,type:`auto`,children:D?(0,_.jsx)(`article`,{"aria-labelledby":`syntax-reference-${D.id}`,children:(0,_.jsxs)(s,{gap:`lg`,children:[(0,_.jsxs)(e,{children:[(0,_.jsxs)(i,{gap:`xs`,mb:`xs`,children:[(0,_.jsx)(a,{variant:`outline`,color:`gray`,children:`Kirin v1`}),(0,_.jsx)(a,{variant:`light`,color:`orange`,children:`只读参考`})]}),(0,_.jsx)(r,{id:`syntax-reference-${D.id}`,component:`h2`,fw:700,fz:`xl`,children:D.title}),(0,_.jsx)(r,{c:`dimmed`,fz:`sm`,mt:`xs`,lh:1.65,children:D.summary})]}),(0,_.jsxs)(`section`,{"aria-label":`${D.title}规则`,children:[(0,_.jsx)(r,{className:`page-kicker`,mb:`xs`,children:`规则`}),(0,_.jsx)(`ul`,{className:`syntax-reference-rules`,children:D.rules.map(e=>(0,_.jsx)(`li`,{children:e},e))})]}),(0,_.jsxs)(`section`,{className:`syntax-example`,"aria-label":`${D.title}示例`,children:[(0,_.jsxs)(i,{justify:`space-between`,wrap:`nowrap`,className:`syntax-example-toolbar`,children:[(0,_.jsxs)(e,{children:[(0,_.jsx)(r,{className:`page-kicker`,children:`可校验示例`}),(0,_.jsx)(r,{fw:650,fz:`sm`,mt:3,children:D.exampleTitle})]}),(0,_.jsx)(l,{variant:`default`,size:`xs`,leftSection:S===D.id?(0,_.jsx)(m,{size:13}):(0,_.jsx)(f,{size:13}),"aria-label":`复制示例：${D.title}`,onClick:()=>{O(D)},children:S===D.id?`已复制`:`复制示例`})]}),(0,_.jsx)(`pre`,{children:(0,_.jsx)(u,{component:`code`,children:D.code})}),(0,_.jsx)(r,{c:w?`red`:`dimmed`,fz:`xs`,className:`syntax-example-note`,children:w?`浏览器拒绝了剪贴板访问；可以直接选择上方源码复制。`:`复制只写入剪贴板，不会修改当前文档。粘贴后仍需按所在工作区的语义执行完整校验。`})]})]})}):(0,_.jsxs)(s,{className:`syntax-reference-empty`,align:`center`,justify:`center`,gap:`xs`,children:[(0,_.jsx)(p,{size:26}),(0,_.jsx)(r,{fw:650,children:`没有匹配的语法主题`}),(0,_.jsx)(r,{c:`dimmed`,fz:`xs`,children:`换一个关键词，例如“输入”“分布”或“图表”。`})]})})]})]})}export{x as SyntaxReference};