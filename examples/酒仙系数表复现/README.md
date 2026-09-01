# 酒仙系数表复现

这个工作区用 Kirin v1 语法复现《酒仙技能攻强系数表 v2.1.xlsx》的三个计算入口：

- `damage_table`：第 1 张表“伤害表”的当前输入、技能攻强系数和预测伤害。
- `defense_table`：第 3 张表“防御表”的醉拳、减伤、躲闪、治疗和吸收计算。
- `aoe_table`：第 6 张表“技能aoe总值表”的 1–20 目标 AOE 总系数、DPC、爆发期 DPC 和 DPE。

默认值对应工作簿当前黄色输入区。游戏版本标记沿用表内的 `12.0.1.65617`；它表达的是这份工作簿的适用范围，不表示这些数值是当前官方数据。

第 3 张表的“期望躲闪率”实际引用第 4 张表 `H2`，因此 `defense_table.expected_dodge` 把它建模成带来源说明的输入。工作簿中的实测伤害、翻译和文字备注不是公式权威，也没有作为计算定义抄入。这里进行的是期望值和等效值计算，不是战斗模拟。

可以直接运行：

```bash
kt check
kt eval damage_table.tiger_palm_damage
kt eval defense_table.expected_physical_reduction
kt scan --x aoe_table.targets --range 1:20 --points 20 \
  --y aoe_table.blackout_kick_dpc --y aoe_table.tiger_palm_dpc
kt plot --config aoe_dpc_curves --force
```

`plots/aoe_dpc_curves.kirin` 是第 6 张表的玩家向曲线入口。`results/aoe-dpc.svg` 和 `results/aoe-dpc.csv` 是用真实 Kirin 扫描与导出路径生成的结果。
