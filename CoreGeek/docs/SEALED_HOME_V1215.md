# v1.2.15 永久封闭建家与采石协调

2026-10-13。本轮保留用户两张图中的17块墙、三座火箭及外侧共同操炮位，取消临时出入口。工人建完炮后先离开将被完整墙体封闭的内部，从外侧完成墙体；后续补墙与维修也使用实际可达的邻墙格。采石按真实墙体缺口与工人背包安排，减少拿到一块石头后仍绕行远矿、配额反复变化、两人争夺同一采集站位等无效行程。

这属于团队策略调整。建造圈层、切比雪夫距离、八方向移动、昼夜权限、占用和同时结算约束继续依据 [v2.0任务书](../../32_docs/任务书.md)与[接口文档](../../32_docs/接口文档.md)。官方文档和 `temp/` 原始资料不修改，正式运行不读取 `temp/`。本版本地验证只覆盖第一天，结果、输入范围与源码哈希见[首日验证报告](../../reports/VALIDATION-v1.2.15.md)，不能将其描述为新版官方对局结果。

## 布局与镜像

坐标以2×2基地的左上角 `station.pos` 为原点，x向右、y向上。以下是基地在左上侧的偏移；基地在右侧时按 `dx → 1-dx` 水平镜像，y不变。

| 部位 | 左侧基地偏移 | 右侧基地偏移 |
|---|---|---|
| 三座火箭 | `(-1,1),(-1,0),(-1,-1)` | `(2,1),(2,0),(2,-1)` |
| 共同操炮位P | `(-2,0)` | `(3,0)` |
| 顶部五块墙 | `x=-1..3,y=2` | `x=-2..2,y=2` |
| 底部六块墙 | `x=-2..3,y=-3` | `x=-2..3,y=-3` |
| 迎敌侧四块墙 | `x=3,y=-2..1` | `x=-2,y=-2..1` |
| 后下侧两块墙 | `x=-2,y=-2..-1` | `x=3,y=-2..-1` |

这17格与前版模板坐标相同。本版把曾被 `DayGate` 特别排除的顶部墙 `(-1,2)`，镜像 `(2,2)`，恢复为普通计划墙，白天也完整施工。P位处于封闭内部的外侧，因此先锋完成任务后仍可从外部回到P控制三炮，不需要临时门。

`Settings.build_cells(turn, kind)`仍负责平移和合法圈层过滤。显式 `layouts` 保留原配置含义和优先级，不强制添加默认墙，不自行扩张可建造区域。边界地图以过滤后的实际合法格为准。

## 一天内的实际执行顺序

1. 开局工人按原75金币预算建三座火箭；队友等待剩余炮位时可以并行筹石。
2. 三炮已由观测确认后，处于未来封闭内部的工人先执行 `construction_exit`。移动只能作为本轮指令，下一次观测确认位置后才算撤出。
3. 工人从未来完整阵型的外侧站位施工。相邻墙位可建且有一块石头时优先就地建墙；否则按自己的稳定配额筹石或前往有效施工目标。
4. 采购工人的真实赴店截止优先级继续高于建墙。它到点仍前往实际商店，等待先锋2→1→2三次任务真实结束，按成功数购用0～3张BOSS券，不预留回家时间。
5. 可见对手占住墙位时先完成其余合法墙；原工人肉身顶缺口、捣乱鬼候补和死亡接力保持。原门位现在也按真实缺口处理，对手离开后补建。
6. 首夜维修工使用外侧可达邻墙格，不要求穿过完整墙环回到内部。真正低于30%血量的墙仍优先使用修复包；采购、侦察、BOSS操控和真实共享视野约束保持。

首日不会因为黄昏而提前召回两名工人；本版也没有R70关门或清晨拆门阶段。已有墙不会为了通行被策略自动拆除。

## 施工安全：SealedHome

实现位置：[src/agent/sealed_home.py](../src/agent/sealed_home.py)。`Strategy`在创建 `WallGuard`前创建此对象，并由工人调度、施工协调、维修策略共享同一回合的几何结果。

对象将计划中的全部墙和炮、实际存活建筑、不可通行中立点及任务点作为静态障碍，按八方向洪泛得到完整阵型的 `outside` 和 `inside`。可移动单位不决定这一几何分类，实际移动仍检查当前占用。尚未建造的墙格仍可作为通行路径；限制的是最终施工站位和能否安全补上该墙。

| 函数 | 参数与返回 | 作用 |
|---|---|---|
| `SealedHome(strategy)` | 当前 `Strategy` | 计算本轮完整计划的静态障碍、外部与内部分类，引用 `GameMemory.sealed_home` |
| `builder_posts(goals)` | 候选 `set[Pos]` → `set[Pos]` | 已启用布局时仅保留完整阵型外侧格；无布局时兼容原候选 |
| `safe_wall(target)` | 待建墙 `Pos` → `bool` | 将当前目标与 `ActionPlan.build_targets`一并检查，确保真实工人仍有外出通路、先锋原本可达的操炮位不被切断 |
| `evacuate(role)` | 工人 `Unit` → `bool` | 白天且三炮已存在时，安排内部工人离开；已在外、无布局或无法退出时不生成拆墙命令 |
| `repair_cells(role=None)` | 可选角色 → `set[Pos]` | 外侧合法邻墙格；传入已有内部角色且实际没有出路时，返回其内部区域用于就地维修 |
| `needs_operator(worker)` | 工人 `Unit` → `bool` | 判断是否白天、工人实际带当前升级券且距P不超过2，目标炮唯一外侧交互格恰为P |
| `pioneer_yield(role)` | 先锋 `Unit` → `bool` | 首日三任务结束后，满足实际送券需求才从P让开；夜间始终不让炮手退出 |
| `wait_for_operator(role)` | 工人 `Unit` → `bool` | 先锋刚发出离开P指令时工人等待一轮，不提前进入本轮仍被占用的P |
| `diagnostic()` | 无 → `dict` | 本轮施工、困人、操炮位协调的本地诊断字段 |

`Strategy.wall_keeps_exit(role,target)`委托 `safe_wall`；`WorkerCoordinator.move_to()`对 `build:wall`目标站位调用 `builder_posts`；`Strategy.build_wall(role,local_only=False)`拒绝从未来内部施工。`local_only=True`只尝试工人当前相邻的墙，不启动一次去远墙的行程。远处工人不会抢占已有携石工人当前能就地建造的墙位。

同时施工的安全检查使用 `ActionPlan.build_targets`，包括前一工人本轮已经提交的建造。工人自己的移动目的地预约可以从路线障碍中移除，但路线起点仍是观测到的真实当前位置，不能把“本轮将离开”当作“已经在外部”。不同工人争抢同格、互换位置以及建筑占用仍由原动作校验处理。

如果读到已经完整封闭、工人实际在内部的旧状态，记录 `trapped_preexisting`；允许就地维修、使用已经持有的物品，不能凭空经过墙体。程序不自动拆墙恢复出路，新施工会尽力避免制造此状态。

## 外侧维修与操炮位送券

[wall_guard.py](../src/agent/wall_guard.py)的 `inner_cells()`仍表示原物理内部通道，不将其重定义为外侧。新增 `duty_cells(role=None)`读取 `SealedHome.repair_cells(role)`；`home/daytime/final_daytime/on_site_upgrade/nighttime`使用实际维修区域，双工分墙、修复包库存、真正血量阈值及避险逻辑继续沿用。

[first_night_defense.py](../src/agent/first_night_defense.py)的 `home_cells(role=None)`及旅行、送券按当前角色取得维修区；[gap_defense.py](../src/agent/gap_defense.py)的 `posts(gap=None,role=None)`从该区域中选择距真实缺口一格的待命格。夜里实际空缺口仍允许工人或候补捣乱鬼进入，不依据预计死亡或预计移动提前接位。

完整阵型会使最低火箭的唯一外侧交互格成为P。为保留三炮升级能力，白天采用短暂让位：

1. 工人实际持有当前阶段需要的券并接近P；先锋首日任务尚未完成时不让位。
2. 先锋发出合法移动；工人本轮以 `weapon_access`等待真实让位，不折返挖矿。
3. 下一观测确认P空闲，工人才进入并使用券；提交 `use`不会提前修改炮等级或背包。
4. 下一观测确认使用结果，工人离开操炮位，先锋回P。夜间不执行这次让位。

## 采石配额：StonePlanner

实现位置：[src/agent/stone_planner.py](../src/agent/stone_planner.py)。它只规划建墙材料，不替代普通铁/铜/收入采矿、售矿、升级或修包采购。

| 函数 | 参数与返回 | 作用 |
|---|---|---|
| `targets()` | 无 → `dict[int,int]` | 当前工人ID到实际背包石头目标数；统计真正缺失的计划墙和能参与施工的工人已持石头 |
| `needs_material(role)` | 工人 `Unit` → `bool` | 实际石头数量是否低于该工人目标 |
| `can_build_now(role)` | 工人 `Unit` → `bool` | 白天有石头、相邻墙空闲、预算预约和封闭检查允许时，可优先直接施工 |
| `mine(role,return_cells=None)` | 工人及可选返岗格 → `bool` | 只收集未完成的材料份额，选择可用石矿和分别预约的采集站位 |

每块墙只需要一块石头，材料缺口按“当前缺墙数−可参与工人的实际持石”计算。处于BOSS采购使命的工人不再提供在家工人的墙材预算，不能把远在商店的石头重复算给施工工人。

配额分配先保留已持石头，再保留仍有效的 `collect:stone`任务中未完成份额，最后将真实剩余缺口按容量平衡给工人。保存值是 `GameMemory.worker_tasks[worker_id]['stone_quota']`，代表目标背包量，不能再当作额外需求累加。建筑、背包和材料只由下一轮观测确认；建造/采集命令本身不减少墙缺口、不增加库存。

石矿选择先利用当前已相邻、合法且安全的石矿；否则保持原有效远矿目标，减少途中折返。两个工人可采同一个矿，但 `claimed_goals`、本轮预约和实际占用要求他们使用不同采集格。矿消失、矿点失败冷却、新闻停矿或路线失效会重新选矿。筹墙材料已足时，普通采矿也不再为未完成的墙追加石头；全部墙实际完工后仍可按原经济策略挖矿售卖，包括采石赚金币。

## 临时门兼容与采购预算

[day_gate.py](../src/agent/day_gate.py)保留旧导入和方法名，`enabled=False`、`worker_id=None`、`pos=None`。初始化清除旧门状态，`worker/closing/can_seal/prepare_coupon`不再执行动作，`reserve_stone()`恒为0。`other_ready/day_ready/dispatch_ready`只提供真实墙完成状态的兼容查询，不授权拆墙。

`remove`仍是协议支持的官方动作，`ActionPlan`保留权限校验；当前策略没有自动拆墙分支。BOSS购物预算仍包含真实去程、腾包、购买、逐张使用与让行余量，不含返程或拆门。原 `departure_budget`输出中的 `opening=0`保留作兼容字段，不能被解释为仍计划拆墙。

原[首日购物截止](BUYER_DEADLINE_V1213.md)、[采购工人分工](WORKER_BOSS_V1212.md)与[多BOSS进位](BOSS_FORMATION_V1214.md)继续提供对应机制的历史细节；涉及临时入口、门石及要求工人返回封闭内部的段落，以本页为准。

## 日志定位与修改入口

`app/service/turn_service.py`在首日输出INFO级别 `home_construction <JSON>`，程序日志写入stderr。字段来自 `SealedHome.diagnostic()`，是本地诊断，不是新增官方请求/响应字段。

| 字段 | 含义 |
|---|---|
| `round/enabled/missing` | 当前回合、布局是否启用、真实未完成墙数 |
| `permanent_walls/physical_closed` | 计划墙数及这些墙是否全部由真实观测确认存在 |
| `inside_workers` | 实际处于未来内部几何的存活工人ID |
| `outside_repair_cells` | 外侧邻墙维修格数量 |
| `reason` | 最近施工/撤出决策原因，如 `evacuating_worker`、`worker_still_inside`、`pioneer_control_route`、`trapped_preexisting` |
| `blocked_worker/deferred_wall/exit_goal` | 对应工人、暂缓墙位或撤出目的格；只在相关决策发生时存在 |
| `operator_status` | 实际送券协调状态，如先锋让位、工人等待观测、先锋等配送 |

`worker_tasks.stone_quota`保存在每工任务记忆中，`worker_motion`也直接输出这一施工配额，和 `kind/target/goal`一起定位路线。查看冗余筹石时首先核对真实缺墙数和两工背包，再判断当前矿点及站位是否继续有效；查看返防不动时区分“墙已完整封闭”和“可达外侧维修格被单位临时占住”。

修改布局从 `Settings.base_surrounding_offsets/build_cells`开始；修改防锁工人从 `SealedHome.safe_wall/evacuate`开始；修改采石效率从 `StonePlanner.targets/mine`开始；修改修墙位置从 `WallGuard.duty_cells/nighttime`开始。测试与实际HTTP首日链路以[本版验证报告](../../reports/VALIDATION-v1.2.15.md)为准，旧报告不作为本轮验证数量。
