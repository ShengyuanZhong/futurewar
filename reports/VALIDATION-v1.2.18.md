# v1.2.18 开局侦察、炮位缓存与车辆验证

2026-10-13。基于 `125027d` 的v1.2.17。只验证第一天，本地请求、任务反馈及敌方行为均是隔离输入，没有进行新版官方比赛。实现和关键函数见[开发文档](../CoreGeek/docs/OPENING_SCOUT_V1218.md)，源码与规则哈希见[回归JSON](validation-v1.2.18.json)。

## 修复内容

- `Strategy.run()`先调用 `RaidScouts.opening_imp()`：初次调查未完成时，捣乱鬼先探敌炮，购券禁用、零任务成功、己方墙未完或被占不抢占该任务。真实确认三炮位置或十二格炮圈累计进入普通视野后，再考虑缺口回防。禁用购券的流程也保留未完成的扫描行程。
- 复用 `GameMemory.enemy_weapon_sites`保存真实炮位和类型。`layout_weapon_sites()`返回纯坐标，结合当前全局基地/墙体进行操炮位假设、路径与召唤射线规划，不生成伪造单位、HP或英雄攻击目标。
- `spawn_ready()`判断已确认阵型能否召唤；`summon_ready()`保留当前共享视野诊断。采购仍在三次任务尝试后按确认成功数批买，实际券库存和逐轮反馈、合法区域及落点去重保持；已知阵型不会因失去角色视野而停止用券。BOSS攻击英雄仍查询当前真实敌单位。
- 实际己方车只要更快就取；有效取车预约代价持平时继续，避免途中改道。车后预测仅忽略本人旧格，修复窄路假阻塞；其它占用不放宽。真实 `isDriving`才发送两个连续邻格坐标；ETA只计白天双步，夜间恢复步行。正式侦察不因不能在日落前抵达就停步。

## 检查结果

| 验证 | 结果 | 主要覆盖 |
|---|---|---|
| [首日回归](validation-v1.2.18.json) | 379项通过，0失败、0错误 | 新9项初次侦察、9项缓存召唤，车辆20项，完整17项阵型扫描及原首日施工/采购/BOSS |
| [HTTP 失视后缓存召唤](http-cached-summon-flow-v1.2.18.json) | 142次POST，全部200 | 两基地方向，普通侦察者先真实看过三炮，R7死亡；用券时无敌英雄/武器观测，仍R37买3张、R38～40用3张 |
| [HTTP 小车流程](http-vehicle-flow-v1.2.18.json) | 84次POST，全部200 | R1～71任务二产车；独立R59～71晚取车/夜间边界 |
| [HTTP 原购券流程](http-worker-buyer-flow-v1.2.18.json) | 142次POST，全部200 | 两方向，三次任务后R37批购，R38～40用券，开拓者R37开始回防 |
| [HTTP 未全封个人派遣/截止](http-unfinished-worker-flow-v1.2.18.json) | 142次POST，全部200 | 左上R47个人施工完成出发、R58买/R59～61用；右下R53截止出发、R65买/R66～68用 |
| [HTTP 双矿封墙](http-sealed-home-flow-v1.2.18.json) | 284次POST，全部200 | 两方向、内外初始工人；每人施工采一个不同10石矿，共17石/17墙，不困工人 |
| [HTTP BOSS协作](http-boss-formation-flow-v1.2.18.json) | 32次POST，全部200 | 首夜R78～85四组阵型/镜像，进位、直攻、返来炮手优先 |

合计826次POST，不计健康检查。全部启动正式本地HTTP服务，使用公开观测及响应驱动下一轮位置、背包、建筑和反馈；没有注入服务私有记忆，没有执行 `executeCmd`。

失视场景使用与原购券场景相同的两基地方向及固定商店，初始三炮/17墙已建、侦察工已到敌基地是隔离前提。先通过普通四格视野提供敌方三炮和操炮者，R7把侦察者死亡作为真实输入。后续每次 `use`都独立断言当前敌列表仅含全局建筑、没有英雄或武器，普通己方单位也不覆盖操炮者；每局仍购用三张且出生位置各不相同。没有把BOSS的位置作为视野来源。

车辆场景在本地任务二成功反馈之后R4加入实际己方车位；工人R6步行登车，R7起由下一轮 `isDriving`驱动双步，R19末端单步下车。晚取车场景R60登车，R61～70双步，R71车辆和驾驶标志移除，只走一格。每个坐标与前一格距离均为1；车辆移动与单步离车按官方正文驱动，未假设碰撞结果。

原“已确认阵型但死侦察者必须持券等待”的测试预期按本次用户策略改为合法召唤；未知阵型仍等待、缓存不能盲打、最后一墙必须下一观测确认等断言保持。新增窄路验证仅让上车预测忽略本人原格，实际两步依旧通过原占用和预约校验。

## 复现与边界

项目根目录运行：

```powershell
python CoreGeek/tools/validate_first_day.py --output reports/validation-v1.2.18.json
python CoreGeek/tools/smoke_worker_buyer_flow.py --lost-sight --output reports/http-cached-summon-flow-v1.2.18.json
python CoreGeek/tools/smoke_vehicle_flow.py --output reports/http-vehicle-flow-v1.2.18.json
python CoreGeek/tools/smoke_worker_buyer_flow.py --output reports/http-worker-buyer-flow-v1.2.18.json
python CoreGeek/tools/smoke_worker_buyer_flow.py --unfinished --output reports/http-unfinished-worker-flow-v1.2.18.json
python CoreGeek/tools/smoke_sealed_home_flow.py --output reports/http-sealed-home-flow-v1.2.18.json
python CoreGeek/tools/smoke_boss_formation_flow.py --output reports/http-boss-formation-flow-v1.2.18.json
```

官方文件和temp原件没有修改，正式程序与测试不依赖temp。车位、刷新时点、任务答案/奖励、对手死亡与静止布局是明确本地输入；没有复现官方随机矿点、移动对手抓捕、车辆碰撞或完整比赛胜率。部分HTTP场景从房屋已建或三炮已建开始，不能证明官方完整开局耗时。本轮验证源码，未重建历史wheel，未运行第二天及以后的模拟。
