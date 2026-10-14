# 首日结束后恢复 v1.1.2 运营（v1.2.25）

本轮依据用户最新说明，将近期的侦察、任务2→1→2、工人购券召唤、BOSS集火、占墙肉身补位和追捕限定在第一天。第二天起恢复 v1.1.2（Git提交 `6946877`）的经济、升级和维修策略。沿用 `32_docs/` v2.0 接口与规则，未修改官方文档。

## 时间与布局

第一天为 R1～R130，首夜从 R71 开始；第二天从 R131 开始。**首夜不会拆墙**。第一天继续使用当前已验证的17墙封闭布局和三火箭，工人外侧施工与任务分工保持。

第二天起，默认墙目标切换成旧版12墙U形。以基地左上角 `(6,7)` 为例：保留 `(6..9,9)`、`(6..9,4)`、`(9,5..8)`；拆除新增的 `(5,9)`、`(5,4)`、`(4,4)`、`(4,5)`、`(4,6)`。右侧基地按 `dx→1-dx` 镜像。三炮位置和共同操炮位保持，后排开放，内侧一格宽维修通道重新可达。

`OperatingHome` 从第二天的白天开始派一名可达工人移除这些新增墙；优先继续原拆墙工，死亡或无路时重选，另一名工人继续正常工作。只拆默认蓝图的新增墙，不拆旧U形墙、不移动武器、不自动更改用户提供的 verified 自定义布局。拆除无材料返还，不伪造石头。

提交 `remove` 后不会假定墙已经消失；下一轮观测仍有墙就继续处理，失败不跳过，也不让其它角色穿过本轮尚在的墙。原来的12墙缺失仍会补建，新增5墙不进入第二天的补墙、升级或修复包需求。若工人在远处，恢复需真实返程及逐墙操作，不承诺黎明单回合完成。

## 后续运营

升级顺序与 v1.1.2 相同，按真实建筑等级推进：

1. 一台火箭升满3级。
2. 正面中央两墙升满3级。
3. 第二台火箭升2级。
4. 正面其余四墙先全部2级，再全部3级。
5. 全部火箭补满3级。
6. 上下两翼剩余六墙升2级。

**不升级基地**，这是 v1.1.2 已确认策略；已有更高基地等级保留。批量购券、同一次到店准备集中升炮所需两种券、升级恢复满血、白天毁墙补建均保持。第二天起不受首日购BOSS券的预算和任务进度限制。

工人昼夜沿用同一经济顺序，夜间增加安全与维修值班约束，仍可采购和配送可用升级券。第三天起安排一名维修工：严格低于30%时用包，另一名继续经济。全部目标达成后，两名工人白天继续挖矿、售矿和批量买包，黄昏按正常返程预算回内侧，夜间双人分区维修。每日备货按天数增长，并结合上一日实际消耗；完成升级不会停止挖矿。缺墙后白天筹石补建、重新升级，夜间仍值守。

开拓者第二天起恢复原任务准入与回防操炮：重新考虑任务往返、时限和日照，夜间优先防守；不会继续首日强制第三次任务。捣乱鬼恢复敌半区毁矿，不再持续首日侦察、绕行或肉身堵缺口。首日主动追捕及近身抓捕不抢占后续经济/任务/维修回合。敌炮位置记忆与任务经验仍保留，但不再给侦察工预留路线、站位或阻挡其它工人让行。

## 模块与接口

| 位置 | 关键函数或字段 | 作用 |
|---|---|---|
| `app/config.py` | `operating_wall_offsets(mirrored=False)` | 旧版12墙相对坐标；默认只在day>1使用 |
| 同上 | `Settings.build_cells(turn, kind)` | 首日17墙/后续12墙，武器三格保持；仍过滤官方相应圈层 |
| 同上 | `opening_only_wall_cells(turn)` | 返回默认首日新增5墙；verified布局返回空集合 |
| `src/agent/operating_home.py` | `OperatingHome.worker(role)` | 白天由固定可达工人拆新增封口墙，返回是否安排本轮动作 |
| 同上 | `retained_walls()` / `diagnostic()` | 运营保留墙与当前恢复进度，真实观测驱动 |
| `app/service/memory.py` | `GameMemory.operating_home` | 跨轮保存拆墙工、target、pending、status；不存虚拟拆墙结果 |
| `src/agent/worker_coordinator.py` | `__init__` | 释放首日采购/侦察/补位等遗留工单；普通采矿配送行程继续 |
| `src/agent/sealed_home.py` | `enabled` | 只在day==1强制外侧施工/维修/撤出 |
| `src/agent/wall_guard.py` | `duty_cells` | day>1恢复旧内侧维修区，正常黄昏返程预算 |
| `src/agent/stone_planner.py` | `targets()` | 后续按缺墙数量与真实石头分摊补墙材料，不沿用首日大批筹石份额 |
| `src/agent/upgrade_policy.py` | `retained_walls/pending_walls/upgrades_complete` | 新增封口墙不消耗运营升级预算，不阻塞完成状态 |
| `src/agent/boss_raid.py` | `__init__/worker_mission_active/budget_reserve` | 仅首日观察采购账本、分派采购工和预留召唤预算 |
| `src/agent/gap_defense.py` / `imp_defense.py` | 日界检查 | 首日补位/抓捕退出；后续用原补墙、维修与挖矿逻辑 |
| `app/service/turn_service.py` | `operating_home`日志 | 第二天起输出恢复状态，与现有worker_motion、opening、full_time_repair组合查看 |

日志 `pending` 是本轮实际观测到的多余墙位，`target` 是拆除目标，`worker_id` 是执行者；`approaching_closure` 表示途中，`awaiting_wall_observation` 表示已发拆墙指令待平台确认，`operating` 表示已无新增封口墙。无人或没有可达路线时不伪造恢复成功。

参数继续沿用：`repair_start_day=3`、`repair_stock=5`、`repair_stock_per_day=3`、`repair_threshold_percent=30`、`sell_batch=12`、`return_margin=4`。实际价格读取报文，v2.0修复包15金币；旧测试中的10金币属于传入商店价格的合成场景，非修改官方价格。

## 本地验证

`tests/test_operating_home.py` 覆盖两个镜像、两阵营、R130→R131、真实拆墙失败重试、死亡换人、自定义布局保护、后续补墙、升级、采矿售矿、批量买包、黄昏返程、双工人内侧修墙与 `TurnService` 日志状态。既有后续维护用例改用独立写出的12墙坐标；第一天的17墙夹具保持。

```powershell
python CoreGeek/tools/validate_first_day.py --output reports/validation-v1.2.25-first-day.json
python CoreGeek/tools/validate_operations.py --output reports/validation-v1.2.25-operations.json
```

前者保护当前首日策略，后者验证过渡与运营，并保存源码/官方资料哈希。测试使用本地输入及明确动作反馈，不是新官方对局，也不是完整双队十天比赛模拟。结果见根目录 `reports/VALIDATION-v1.2.25.md`。
