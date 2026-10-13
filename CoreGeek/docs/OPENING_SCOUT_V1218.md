# v1.2.18 开局侦察、炮位记忆与车辆路线

本版在 v1.2.17 首日分矿和个人施工交接基础上调整侦察。捣乱鬼开局先调查敌炮位置，阵型确认后才考虑回家守缺口；已经确认的炮位用于后续召唤选点，失去当前视野不会取消已知阵型。侦察工人完成自己的施工后继续探敌，发现实际可用小车且乘车更快时先取车。

本次是策略与实现修正。规则依据为 [32_docs/任务书.md](../../32_docs/任务书.md) §4.3、§4.5.4、§4.6.4 与 [32_docs/接口文档.md](../../32_docs/接口文档.md) 的局部视野、车辆和 move 字段；召唤机器人没有视野、移动和攻击不能同轮执行，以及炮位确认后的阵型利用，沿用用户提供的比赛澄清。官方原件和用户 temp 原件均保留，正式源码不读取 temp。

## 首日角色流程

捣乱鬼在 `Strategy.run()` 的角色分支首先调用 `RaidScouts.opening_imp(role)`。只要第一天敌基地仍存活且初次侦察没有完成，该分支优先于 `WallGapDefense.imp(role)` 和普通矿石破坏。购券开关、任务成功数、工人是否完成建墙和己方预建墙是否被占，不阻止首次侦察。观察路线仍避开可见敌方角色的邻格和不安全观察位，优先留在敌建造圈外，不占召唤点及预定攻击通道。

首次侦察完成依据是普通己方单位的真实共享视野，满足下列任一条件即可：

- 已经真实确认敌方武器圈内三个炮位，达到同时最多三台武器的上限。
- 武器数量不足三台时，敌基地周围十二格武器圈都累计进入过普通己方单位四格视野。

`opening_scout_complete` 与首次完成回合跨回合保存。未完成时继续调查未见过的武器圈；完成后捣乱鬼恢复既有分支优先级，先考虑缺口接力，再维持袭击所需视野或普通矿石破坏。夜间仍未完成调查时也不会仅因进入黑夜取消首次侦察。敌基地不在当前报文中时，不将镜像估计当成基地存活确认。

两名工人的原有分工保留：采购工完成自己的施工或到实际购物截止后赴店，侦察工完成自己的可建施工段后立即探路，不等待全队墙齐或转去收入采矿。当前敌占格暂跳，三次任务按任务二→任务一→任务二尝试，三次结算后按成功数购买和使用最多三张 BOSS 券。开拓者三次尝试后回防。

## 阵型知识与当前攻击目标

跨回合记忆位于 [app/service/memory.py](../app/service/memory.py)，保存在对应比赛会话的 `GameMemory` 中。

| 状态 | 类型或内容 | 用途及边界 |
|---|---|---|
| `enemy_weapon_sites` | `dict[Pos, str]`，真实炮位到炮类型 | 由实际收到的敌炮观测写入；位置确认后保存，失视或炮被摧毁不会使已确认建造点变成未知 |
| `enemy_structures` | 单位 ID 到真实观测过的建筑 `Unit` | 保存尚未被当前死亡、重建、可见空格等证据否定的建筑；失视时可用于路径和建筑弹道规划 |
| `raid_scouts['surveyed']` | `set[Pos]` | 十二格武器圈中实际进入普通共享视野的格子；全局可见墙和召唤机器人不提供扫描来源 |
| `raid_scouts['opening_scout_complete']` | `bool` | 首次调查已经得到足够阵型信息，允许捣乱鬼恢复缺口防御等后续行为 |
| `opening_scout_completed_round` | 回合号 | 首次达到确认条件的回合，仅记录一次 |
| `weapon_sites/layout_ready` | 已确认位置列表及阵型确认值 | 日志中的阵型知识，不代表该格当前有存活炮或角色 |
| `posts` | 角色 ID 到观察行程 | 观察目标、survey/watch 模式、travelling/holding/collecting_vehicle 状态和预计行程 |
| `avoided_vehicle_sites` | `set[Pos]` | 对持续失败的取车点进行回避，不等待或追逐消失车辆 |

敌方基地和城墙持续来自当前全局可见报文，墙被拆除或重建后会更新选点。炮位记忆来自实际炮观测，不根据墙形、镜像模板或推测的操炮手站位写入。`layout_weapon_sites()` 合并有效炮观测和当前敌基地武器圈内的已确认位置，返回 `tuple[Pos, ...]`，不制造单位 ID、HP 或活炮对象。

`layout_operator_positions()` 根据这些位置计算能够操控最多炮台的空格，帮助召唤选点和视野覆盖；其返回值仍是位置假设。机器人真正攻击时从当前 `Turn.enemies` 查询存活目标，并经过 `clear_attack()` 的射程和墙遮挡校验。旧工人位置、推测炮手格和永久炮位缓存均不能单独产生攻击指令。即使已经知道阵型，第一夜仍需要工人在附近保持普通视野以清理敌方移动角色。

## 召唤就绪与视野就绪

`RaidScouts.spawn_ready()` 用于判断是否能利用已知阵型召唤。条件包含第一天袭击流程有效、敌基地当前存活、阵型已经确认；它不要求此刻有侦察角色看见操炮手。采购工持有券且满足既有日间、任务结果、库存与合法出生点约束时，`BossRaid._deploy()` 使用这个条件继续召唤。

`RaidScouts.summon_ready()` 保留为实时普通共享视野诊断：是否有活观察者、是否已经就近、共同操炮格及当前可见炮手是否在普通视野中。它可以在 `spawn_ready=True` 时为 False。这种组合表示已知炮位足以选出生位置，当前不能据此声称可以看到或攻击敌方英雄。日志中的 `readiness_reason` 与 `uncovered_operators` 用于检查这一差别。

`scouted_spawn_position()` 使用炮位、当前墙体、潜在操炮格和合法出生区域选择召唤位置，并考虑先前召唤位置、失败位置、实际占用以及 45°攻击通道。历史后方模板仍只用于购买可行性估计，实际用券使用已确认的阵型几何。

## 侦察工人取车与驾驶

任务二至少完成一次后可能奖励己方小车。取车决策只读取当前报文中的己方车辆格，不因为任务成功就假定车已刷新；任务在夜间或白天最后一轮结束时车辆顺延，已有小车也不会再次刷新。

`travel_budget(role, goal, route)` 比较直接步行和经过实际停放车辆的路线：步行到车位所需轮数加上后续驾驶轮数。任何确实更快的可行车路线都可采用，取消此前至少节省两轮的门槛。已经开始的有效取车任务在代价持平时保持，避免观察目标变化后折返。车辆被占、消失、被预约或通路不可达时继续可行的步行路线，不等待车辆。

登车是正常的一格移动，进入己方车位后必须由下一轮真实 `isDriving` 确认已经驾驶。已经驾驶且仍是白天时，`vehicle.move_targets()` 从同一避碰路线取两个相邻步骤，输出：

```json
{"action":"move","targetPos":[{"x":20,"y":17},{"x":21,"y":18}]}
```

两个目标按实际行驶顺序提供；每一步与前一格的切比雪夫距离为一，不能直接只传两格远的终点。路线只剩一步时发送一个坐标，按规则步行下车；采矿、建造或交易不自动让车消失。夜晚第一轮车辆消失，路线估计只对剩余白天计算两步速度，之后按步行计算，夜间动作也只传一格。

取车后的路线预测把本工人的路径起点放在车位，并通过 `ignore_workers` 显式忽略该工人原位置的占用；其他真实单位、建筑、车辆禁入格和当轮预约保留。这样不会把工人自己即将腾出的原格错误当成障碍，导致本来更快的车路线被拒绝。该预测只用于比较行程，实际动作仍依据当轮观测和 `ActionPlan` 校验。

## 关键源码接口

| 位置与函数 | 参数与返回 | 修改入口 |
|---|---|---|
| [brain.py](../src/agent/brain.py) `Strategy.run()` | 当前 `Turn/ActionPlan/GameMemory` → 本轮角色动作 | 捣乱鬼先初次侦察，再缺口、持续观察和矿石破坏；每角色每轮仍至多一条指令 |
| [raid_scouts.py](../src/agent/raid_scouts.py) `opening_imp(role)` | 捣乱鬼 `Unit` → `bool` | 最高首日初次侦察分支；True 表示角色已安排移动或观察待命 |
| 同上 `update_survey()` | 无参数 → 更新状态 | 真实四格扫描、炮位确认及初次完成标记 |
| 同上 `spawn_ready()` / `summon_ready()` | 无参数 → `bool` | 分别判断已知阵型召唤条件和当前普通共享视野条件 |
| 同上 `travel_budget(role, goal, route)` | 当前角色、观察位 `Pos`、真实路线 → `(rounds, car_pos_or_none)` | 取车收益、保持有效取车和昼夜速度估计 |
| 同上 `scout_route(role, ignore_workers=frozenset())` / `observe_from(role)` | 当前或预测角色、仅供路线预测忽略的工人 ID 集合 → `Routes` / `bool` | 可达观察位、安全避捕、射线避让、取车和维持视野；车后预测仅忽略本工人旧占用 |
| [summoning.py](../src/agent/summoning.py) `layout_weapon_sites(turn, remembered=(), confirmed_sites=())` | 当前观测、真实建筑记忆、已确认炮位 → `tuple[Pos, ...]` | 仅生成位置几何，不生成当前攻击目标 |
| 同上 `layout_operator_positions(turn, remembered=(), confirmed_sites=())` | 同上 → `tuple[Pos, ...]` | 从炮位推断可同时控制最多武器的空格 |
| 同上 `scouted_spawn_position(turn, settings, remembered=(), pending=(), failed=(), surveyed=(), confirmed_sites=())` | 当前观测、配置、记忆及限制集合 → `Pos` 或 None | 利用失视后保留的炮位及当前全局墙体选出生位置 |
| [boss_raid.py](../src/agent/boss_raid.py) `BossRaid._deploy(role)` | 当前采购工人 → `bool` | 持券后使用 `spawn_ready()`，不再用实时视野诊断阻止已知阵型召唤 |
| [robot_raider.py](../src/agent/robot_raider.py) `observe_structures()` / `decide(robot)` | 当前观测 / 当前己方机器人 | 记录实际炮位，更新建筑记忆；攻击目标仍来自当前可见敌方单位 |
| [vehicle.py](../src/agent/vehicle.py) `move_targets(turn, role, route, goals)` | 当前观测、角色、路线及目标集合 → 有序 `tuple[Pos, ...]` | 仅真实白天驾驶时输出两段，其余输出一段 |

## 排查与本地验证

检查 `raid_scout` 的 `opening_scout_complete/opening_scout_completed_round`、`surveyed_count/weapon_cells`、`weapon_sites`、`layout_ready`、`spawn_ready/summon_ready`、`readiness_reason` 与 `posts`。车辆问题同时看 `vehicle/is_driving/steps/travel_rounds`、`worker_jobs` 中的 `raid_scout_vehicle` 和下一轮动作反馈。BOSS攻击问题看当前 `robot_diagnostic` 目标查询与墙、建筑遮挡，不能只看旧炮位缓存。

新增首日回归位于 [test_imp_opening_scout.py](../tests/test_imp_opening_scout.py)，覆盖敌占墙、购券禁用、零任务成功、三炮与十二格扫描、扫描完成后的缺口接力，以及已知阵型失视后召唤和禁止盲打。[test_cached_layout_summon.py](../tests/test_cached_layout_summon.py)另验证纯炮位缓存、当前全局墙体变化、镜像、无实时视野的三张券反馈和不产生虚假攻击目标。车辆相关验证在 [test_scout_vehicle.py](../tests/test_scout_vehicle.py)，协议与逐步路径验证在 [test_vehicle_protocol.py](../tests/test_vehicle_protocol.py)；阵型缓存、侦察安全和召唤合法性沿用相应回归。

本轮只验证第一天。实际检查数量、连续 HTTP 场景、运行环境、源码哈希及未覆盖范围由 [VALIDATION-v1.2.18](../../reports/VALIDATION-v1.2.18.md) 记录；这些是本地证据，不是新版官方对局结果。后续修改要分别维护阵型知识、当前视野和实际库存反馈，不把取车预测或旧单位观测改成官方当前报文。
