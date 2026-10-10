# BOSS逐回合诊断日志

v1.2.3新增[首夜观察者](RAID_SCOUTS.md)及raid_scout日志；下文为v1.2.2建立的BOSS诊断字段，继续保留。

v1.2.2，2026-10-10。本次只增加诊断信息，不改变第一天购买/召唤、第一夜BOSS选敌、走位、破墙和攻击策略；原工人、任务、炮台及施工流程继续保留。策略本身见[BOSS袭击说明](BOSS_RAID.md)，本地检查结果见[v1.2.2验证报告](../../reports/VALIDATION-v1.2.2.md)。本文解释如何使用日志，具体JSON字段与枚举以当前源码输出为准。

## 输出位置与开关

程序默认在INFO级别向stderr输出两类单行JSON日志。日志行仍可能带时间、级别和logger名称；识别下面的标记，再把标记后的JSON对象交给JSON解析器。

- `robot_observation {...}`：出现本方机器人、全局BOSS、召唤状态或消失记录时输出一轮摘要，用于确认本方BOSS是否生成、是否仍在存活列表，以及哪些机器人在本轮消失。
- `robot_diagnostic {...}`：每只机器人一条，串联本轮观测、前轮命令反馈、目标选择依据、走位检查和本轮最终命令。

原有`boss_raid`、`action_rejected`和服务错误日志继续输出。两类新日志用于逐回合定位原因，不替代原有购买状态与异常记录。HTTP返回字段和Postman调用方式没有增加，诊断信息不放进`roleCommandMap`、`prompt`或`executeCmd`。

配置新增`enable_robot_diagnostics`，类型为bool，默认true。关闭示例：

```json
{
  "enable_robot_diagnostics": false
}
```

配置仍由`FUTUREWAR_CONFIG`或既有显式配置路径加载；修改后重启服务。关闭诊断仅停止这两类新日志，不停止BOSS购买、召唤和操控，也不屏蔽原有`boss_raid`和错误日志。

## 一轮摘要：robot_observation

摘要先交代本轮看到什么，避免把“没发指令”直接误认为寻路故障。

| 信息 | 用途与边界 |
|---|---|
| `round/team_id/team_type` | 对齐日志顺序与队伍；游戏日、昼夜见每只机器人的`policy` |
| `owned_ids/owned_count` | 来源是`teamOur.summonRobotList`，这是归属依据 |
| `global_boss_ids/global_boss_count` | 来源是`robot.roles`，仅说明全图观测到BOSS，不能单凭类型认定归属 |
| `summon_status/requested_spawn/summon_round` | 区分尚未用券、用券后等待夜间生成与已经生成；出生位置仍读取真实观测 |
| `removed` | 上轮有、本轮缺失的机器人；记录`expected_dawn_clear`或`removed_from_owned_alive_list`，不直接判定战斗死亡 |

`RobotRole.targetTeam`是攻击目标阵营，不是所属队伍。召唤位置与真实出生位置可能不同，官方允许角色、矿石或机器人占据指定点后旁移生成；日志不能用两者坐标不同直接判定召唤失败。

## 单机器人记录：robot_diagnostic

每条记录以真实机器人ID串联，内容分为下面几组。

| 信息组 | 记录内容 | 排查问题 |
|---|---|---|
| `robot/policy` | 位置、HP、类型、异常状态、攻击力、射程、目标阵营与策略开关、游戏日、昼夜 | 是否已被眩晕、HP是否仍大于0、是否为第一夜策略操控的BOSS |
| `previous`前轮关联 | `round/command/consecutive/command_matched/raw_action_result/legality` | 命令是否真正发出、判题器是否判非法、反馈是否缺失或不能对应当前记录 |
| `previous`位置变化 | `position/displacement/movement/positions/oscillating` | move后是否移动、是否形成往返；不把短位置序列直接认定为无限循环 |
| `previous`自身HP | `robot_hp_before/robot_observed_hp_delta` | 确认机器人自身是否遭到伤害或HP回升，不预判死亡原因 |
| `previous`攻击观测 | `attack_target/target_hp_now/observed_hp_delta/target_observation` | 破墙时检查墙，攻击角色时检查角色；不能拿操炮者HP代替实际被攻击墙的HP |
| `weapons/visible_heroes/operator_count` | 可见三类炮台、各角色HP和位置、角色邻近武器ID与`eligible` | 是否识别全部工人/先锋，是否有角色回血、离开或重新进入炮旁 |
| `candidates`及`events`的`candidate/attack_check` | 候选rank、距离、射程、墙遮挡与失败站位缓存；顶层`selected/selected_rank/failed_cache`补充最终目标与缓存 | 为什么选择这个目标，为什么当前没有直接攻击它；候选另存一份，避免被扫描事件挤出 |
| `route` | 已计算路径的可达格总数、周围八格的地形/占用单位/预留/可达情况 | 周围是否被城墙、单位、矿石或己方下一步占住；未重新计算路径 |
| `events`的`firing_sweep` | `counts/timed_out/best`记录射击格排除原因计数、扫描是否截止与选定post | 哪些射击格因不可达、墙、缓存或其它条件未被采用 |
| 决策结果 | `reason/attempted_command/accepted/final_command/rejections` | 策略准备做什么、最终命令是否进入响应、是否被本地动作门禁拒绝 |

候选rank是现有策略的排序依据，不是额外的攻击规则。可直接攻击的操炮者优先，之后按当前HP所需命中数/HP、可行走位成本等排序；旧目标仅用于稳定并列选择。可见炮旁还有活工人或先锋时，不转攻基地。没有当前可见候选时尝试基地，不把这一状态记成“所有操炮者已被击杀”。

`firing_sweep`记录当轮策略实际进行的检查。直接攻击或提前退出时可能没有完整射击格扫描，缺失扫描结果不表示全图所有位置都不可达。路径成本和射线判断是本地决策信息，实际移动、遮挡和伤害仍由判题器结算。

`route.adjacent.land`仅表示地形是空地；空地仍可能被单位占用或本轮计划预留。`reachable`来自本轮既有路径结果，结合`occupants/reserved`读取，不能只凭`land=true`判断可以移动。

## reason与指令的对应关系

| reason类别 | 含义 |
|---|---|
| `direct_attack` | 当前目标满足本地直射条件，策略尝试发出attack |
| `reposition` | 当前不直接开火，向选定射击post移动 |
| `breach_attack/breach_reposition` | 攻击观察到的敌墙，或移动到打墙位置；目标类型通过`breach_wall`核对 |
| `no_reachable_firing_position_or_wall` | 当前检查没有得到可执行的直射、走位或破墙方案；不是对未来回合的永久无路结论 |
| `no_step_to_breach_post` | 已选定破墙站位，但没有得到本轮可执行的移动一步 |
| `command_rejected` | 本地动作门禁拒绝候选命令，查看`rejections` |
| `deadline_during_candidates/deadline_during_breach/deadline_in_firing_search` | 当轮候选、破墙或射击格检查到达软截止，未继续搜索 |
| `no_visible_operator_or_live_base` | 本轮没有当前可见操炮者，也没有存活敌基地候选 |
| `not_reached_robot_loop` | 该机器人未进入决策循环；结合服务耗时和截止检查，不能直接判成寻路失败 |
| `skip_*` | 因策略时段、开关、机器人类型、HP或眩晕等条件跳过；具体原因以JSON枚举值为准 |

`reason`解释决策分支，`final_command`才表示进入本轮响应的指令。若本地`ActionPlan`拒绝，查看相应rejections与`action_rejected`，不能把“尝试attack”当成“已发送attack”。一只机器人每轮仍只执行一条原生命令。`previous.legality`取`legal/illegal/missing/unmatched`；`target_observation`取`not_applicable/not_visible_or_absent/observed_dead/decreased/increased/unchanged`，二者分别描述动作合法性与目标观测，不能混读。

## 反馈与战果的事实边界

官方[v2.0接口文档](../../32_docs/接口文档.md)明确，`lastRoundRoleActionResults`记录的是**上一回合动作是否合法**，key也可以是可控机器人ID。

- true只能说明判题器判为合法，不能直接写成命中、造成40伤害或击杀成功。
- false表示判题器判为非法；这与本轮命令被本地`ActionPlan`拒绝不同。
- 没有该ID的反馈表示缺失，不能默认为true或false。
- 只有前次记录恰好属于当前回合的前一回合，且对应ID当时确实发出相应命令，才能关联本轮“上回合”反馈。跳回合、进程重启或缺少旧命令时，不把反馈挂到更早的一次攻击上。

同一个目标连续两次可见时可以比较HP，但只能报告观测差值。HP下降可能受到其它单位的伤害影响，不能全部归因于己方BOSS；HP持平或回升也不能直接证明没有命中或确定使用了回血物品。角色移动、回血及同轮其它伤害都可能影响看到的结果。即使发出攻击时估算一击可杀，也必须等待下一轮实际观测，不能预先宣布死亡。

敌方角色显式HP≤0可以记录观测死亡，但不能直接宣称击杀归属。角色从`teamEnemy.roles`消失时，受视野限制，记录“当前不可见/缺失”，不能认定死亡。基地与城墙全局可见，但实体缺失和显式HP为0仍应分别记录。BOSS从本方存活列表消失记录该事实；次日白天首回合官方统一清除机器人，不作为战斗死亡统计。

## 读取一次卡住或攻击异常

1. 先按同一队伍、机器人ID和回合排列连续日志，确认摘要中机器人存在。全局BOSS存在但本方列表没有对应ID时，先检查归属，不将其它BOSS当作本方召唤单位。
2. 查看机器人HP、异常状态、昼夜和`skip_*`。已眩晕或策略时段不适用时，没有命令是预期分支。
3. 对比`previous`中的前轮命令、合法性与连续性。反馈缺失、非连续回合和本地拒绝分别处理；只有可关联的false才证明那次动作非法。
4. 查看实际位移和最近4个位置。移动命令后原地不动与A→B→A式往返分开观察，再结合墙、单位占用、post选择和失败缓存解释；`oscillating`是短序列提示，不自动更改行为。
5. 检查武器邻域与操炮者候选，核对目标仍然活着、是否回血或换位。再看rank、距离、射程、遮挡和`firing_sweep`，确认没有直射时为何选择走位或破墙。
6. 以最终command对齐下一轮实际位置/HP和合法性反馈。当前可见操炮者清空后是否尝试基地、重新出现后是否优先清理，都用连续日志确认。

日志中的JSON部分可独立解析；保留标记和回合信息，以便两类记录互相关联。不要只截一条attack或一帧HP就判断战斗流程，也不要将打印出的坐标或命令作为需要在主机执行的脚本。

本地HTTP检查可同时导出实际服务生成的JSONL：

```powershell
python CoreGeek/tools/smoke_server.py --request reports/boss-raid-observation-v1.2.1.json --robot-id 34009 --robot-log-output reports/robot-diagnostics-v1.2.2.jsonl --output reports/http-boss-v1.2.2.json
```

该文件每行包含`log_type`与`data`，便于查看；示例输入是按截图构造的合成观测，只证明服务输出链路，并非官方实战日志。

## 体积与运行成本

单只机器人的事件最多保留12条；实体列表最多16项，失败缓存最多16项，超限记录省略计数。最近位置仅保留4次。列表被截断时，未显示某个实体不代表真实观测里没有它，应同时查看总数与省略数。

诊断使用既有观测、旧命令快照与策略当轮产生的检查结果，在策略完成后写日志，不额外计算路径或再跑一遍选敌。关闭开关不应改变响应；相同报文的缓存重放不重复推进诊断历史。

两类日志不输出整张地图、任务内容、LLM提示词、任务脚本或敏感配置。其它原有日志保持原样，其内容范围不由此开关调整。

## 模块与函数位置

| 位置 | 作用 |
|---|---|
| `src/agent/raid_diagnostics.py` `RaidDiagnostics(strategy)` | 读取Strategy，保存决策前旧机器人任务/位置记录；为本方机器人准备前轮命令、位置和HP关联 |
| 同上 `set(robot, **fields)` | 补充当前机器人的决策字段，关闭诊断时不保存 |
| 同上 `event(robot, kind, **fields)` | 记录一次候选或扫描事件，超出12条只累计省略数量 |
| 同上 `finish()` | 在策略结束后完成最终命令、拒绝与消失摘要，返回摘要/机器人记录，并保存下一轮诊断用的`robot_motion` |
| 同上 `entity(unit)` / `plain(value)` | 输出实体的ID/类型/位置/HP，把Pos等项目对象转换为JSON可表示的数据 |
| `src/agent/robot_raider.py` | 在既有候选、直射、射击格扫描和破墙分支采样；不为日志额外寻路 |
| `src/agent/robot_combat.py` `clear_attack(...)` | 将既有射程、目标与墙遮挡检查写入可选诊断容器，不改变攻击校验规则 |
| `app/service/turn_service.py` `TurnService.decide(payload)` | 策略完成后收集并输出两类JSON；相同报文缓存重放不重复推进历史 |
| `app/config.py` `Settings.enable_robot_diagnostics` | bool诊断开关，与`enable_boss_raid`策略开关分别控制 |
| `app/service/memory.py` `GameMemory.robot_motion` | 保存上一轮诊断位置序列与实际攻击目标，不能作为战术输入 |

## 后续实战资料

后续出现问题时，从任一`robot_observation`开始，连续保留10–20回合的两类JSON行，并保留同一时段的原`boss_raid`、`action_rejected`与错误日志，放入根目录`temp/`。不要只截异常末尾或删去前轮反馈；连续片段才能确认出生、目标切换、攻击合法性和实际位移之间的关系。

本地验证只证明日志结构、反馈关联、截断及开关等实现行为；官方对局中的伤害、击杀和移动结果应依据完整实战观测核对。具体执行结果见[v1.2.2验证报告](../../reports/VALIDATION-v1.2.2.md)。
