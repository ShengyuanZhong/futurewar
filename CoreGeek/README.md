# CoreGeek 参赛 Agent

当前版本0.3.10：先集中升满一台火箭，再将正中两墙升3级、第二台火箭升2级、正面其余四墙升3级；接着所有火箭升满，最后两翼六墙升2级。基地不升级。全部达标后双工人墙内维修，白天轮流批量买包，夜间均值守。详细阶段、参数和函数见[建筑维护](docs/MAINTENANCE.md)。沿用昼夜统一经济流程，夜间可继续采购、配送和使用升级券；沿用工人独立任务、协作让行、城墙掩护和按日递增备货；详见[工人协作](docs/WORKER_COORDINATION.md)。原任务模块、U形阵型和升级顺序保留。

此目录可作为参赛程序目录提交。沿用示例的 `main3.py`、`src/agent/protocol.py`、`grid.py`、`brain.py`；HTTP 处理与跨回合协作放在 `app`。新增代码无第三方运行依赖。

项目的完整架构、对象生命周期、字段映射、函数参数/返回值及扩展示例见 [根目录README](../README.md)。本页保留CoreGeek目录内的运行命令，并在后半部分提供按源码文件定位的速查表。

| 想查看的内容 | 详细入口 |
|---|---|
| 全部目录及各层作用 | [目录与模块职责](../README.md#project-layout) |
| HTTP到动作输出的完整调用链 | [整体架构与回合流程](../README.md#architecture) |
| Settings、环境变量和代码内阈值 | [配置与参数](../README.md#configuration) |
| Turn、Unit、Pos和官方字段映射 | [数据模型](../README.md#models) |
| HTTP/回合/记忆/LLM/任务函数 | [应用层函数](../README.md#application-api) |
| 动作/BFS/角色策略/战斗函数 | [策略层函数](../README.md#strategy-api) |
| 任务往返、新闻与宝藏计划 | [业务流程](../README.md#task-workflow) |
| 直接用Python调用或添加策略 | [扩展示例](../README.md#examples) |
| 故障与修改入口 | [维护索引](../README.md#maintenance) |
| 三火箭开局、石头配额、单人轮换 | [开局防御策略](docs/OPENING_DEFENSE.md) |

## 启动

在 CoreGeek 目录执行：

```bash
bash run.sh 8080
# 或
python3 main3.py 8080
```

Windows 调试：

```powershell
python main3.py 8080
```

参数端口范围为 1–65535。所有地址监听为 `0.0.0.0`；提供 `POST /`（同时兼容其他 POST 路径）、`GET /health` 和 `GET /healthz`。

`run.sh` 可由任意工作目录调用，通过脚本路径定位代码；`PYTHON` 环境变量可指定解释器。没有 bash 的 Windows 可直接运行 Python 入口。本轮仅验证了 Windows Python 3.10.6；Linux bash 入口还需要在比赛运行环境实测。原 demo 的最低版本声明为 3.11，本实现使用的语法和库已在 3.10 运行，因此声明改为 `>=3.10`；官方 Python 版本说明未包含在当前文件夹。

## 配置

```powershell
Copy-Item config.example.json config.local.json
python main3.py 8080 --config config.local.json
```

也可设置 `FUTUREWAR_CONFIG`。相对路径以启动命令的当前目录解析；生产环境建议使用绝对路径。程序启动时读取一次配置，修改后需重启。

默认无需配置文件即可开局建造。`allow_base_surroundings=true`按用户“基地周围可建造”的假设，按用户设计图建立12格U形墙、后排竖排三炮及固定P站位，内侧保留一格维修通路，右侧基地水平镜像；这是本地布局假设，不向官方请求增加字段。

需要自定义时，可在layouts中填写各阵营相对基地左上角的`{x,y}`偏移、source及verified:true，优先覆盖默认布局。旧模板的未核验空坐标不会阻止默认建造。`loadout`为`["rocket","rocket","rocket"]`；默认先造三炮，再采石建墙。详见[开发文档](docs/DEVELOPMENT.md)。

从旧版升级时，已存在的外部配置会覆盖新默认值，需要把其中的`loadout`同步改成三个rocket后重启。已有旧炮不会被自动拆除替换。

## 功能

- 官方请求解析，敌方可见单位与双格任务点障碍，八方向寻路。
- 同回合目标预留、共享金币预算、角色与武器操控互斥。
- 开局75金币先建三火箭，再攒够石头建墙；后续按实时价格卖矿、购买与使用升级券。
- 规划三炮共同操控格，黄昏开拓者回防，夜间每轮选一座冷却完成的炮发射；普通工人昼夜按相同经济优先级工作，夜间避险且禁建；第三天起维修工黄昏回到墙内，夜间维修优先并可沿内侧升级。
- 防御优先于活跃任务与宝藏；保留射程、目标数量、伤害估值和角色互斥检查。
- 开拓者接任务，官方 LLM / 沙盒探索，提交答案，按类型保存成功/失败经验并复用SOP/Skill。
- 跨日新闻积累、停矿信息推理、宝藏购买与定时献祭、失败方案去重。
- 十二种动作都提供统一校验。`remove` / `drop`可供扩展策略调用；当前基线不会主动拆墙或丢物品。普通物品使用受开局、夜采与防御优先级限制，不会自动采购召唤令、炸弹、眩晕法宝。

这是一版可运行的策略基线，不保证任务解题正确率或比赛胜率；判题器负责真实结算、伤害、复活、计分与胜负。

## 调试与交付

```powershell
python run_tests.py
python tools/smoke_server.py --output ../reports/http-smoke-v0.4.2.json
python tools/replay.py ../request.txt --output ../reports/sample-response-v0.4.2.json
python tools/validate.py --cases 20 --output ../reports/validation-v0.4.2.json
```

回放输入支持单个 JSON、JSON 数组、每行一份观测的 JSONL。单个队伍按回合递增；同回合相同内容返回缓存，不同内容拒绝，以免状态被重复推进。

提交通常只需要`main3.py`、`run.sh`、`app/`、`src/`；使用自定义参数时再携带相应配置文件。默认基地周围布局内置于代码。`tests/`和`tools/`用于本地验证，测试依赖根目录`request.txt`。无需携带`build/`、`dist/`、`__pycache__/`。

可选构建 Python wheel：

```bash
python -m pip wheel . --no-build-isolation --no-deps --wheel-dir dist
```

wheel 包含 `agent` 与 `app` 两个包；比赛启动仍推荐源码目录的 `bash run.sh port`。旧 `agent.server.serve` 保留兼容转发；旧 `agent.brain.decide(payload)` 仍只返回角色指令 map，是无状态战术接口，完整任务功能应调用 `app.service.turn_service.TurnService.decide`。

## 源码阅读顺序

建议沿实际调用链阅读：

1. [main3.py](main3.py)：启动参数、日志、模块路径。
2. [app/server.py](app/server.py)：请求体如何进入服务，错误如何返回。
3. [app/service/turn_service.py](app/service/turn_service.py)：本轮和历史状态如何组合。
4. [src/agent/protocol.py](src/agent/protocol.py)：策略实际能读取的数据。
5. [src/agent/brain.py](src/agent/brain.py)：角色选择动作的优先级。
6. [src/agent/actions.py](src/agent/actions.py)：每个动作必须满足的条件。
7. 根据修改目标继续看construction、grid、combat，或LLM/Task/Memory服务。

## 模块与关键函数速查

下表中的路径均相对于CoreGeek目录。参数的完整含义与副作用在根README展开；此处用于快速定位。

| 模块位置 | 关键入口 | 作用/返回 |
|---|---|---|
| [main3.py](main3.py) | `main()` | 读取`port/--config`，启动服务 |
| [app/config.py](app/config.py) | `Settings.load(path=None)` | 文件/环境变量加载及配置校验，返回Settings |
| 同上 | `Settings.build_cells(turn, kind)` | 优先自定义确认布局，否则按启用的基地周围布局计算绝对建造格 |
| 同上 | `base_surrounding_offsets(kind, mirrored=False)` | 三炮和12格U形墙偏移；镜像为dx→1-dx，详见[布局说明](docs/U_LAYOUT.md) |
| [app/server.py](app/server.py) | `serve(port, settings=None)` | 绑定0.0.0.0并阻塞服务 |
| 同上 | `AgentServer(address, service)` | HTTP服务器与复用TurnService绑定 |
| 同上 | `Handler.do_POST/do_GET/send_json` | 请求处理、健康检查、编码输出 |
| [app/service/turn_service.py](app/service/turn_service.py) | `TurnService.decide(payload)` | 返回含三个官方字段的完整响应，提交跨回合状态 |
| 同上 | `Session`、`empty_response()` | 会话数据、独立空响应 |
| [app/service/memory.py](app/service/memory.py) | `GameMemory.observe(turn)` | 更新额度、新闻、任务及行为反馈 |
| 同上 | `GameMemory.record(turn, plan)` | 保存本轮输出，等待下一轮关联反馈 |
| 同上 | `treasure_signature(clue)` | 宝藏目标、精确物品和时间窗口的去重签名 |
| [app/service/llm_service.py](app/service/llm_service.py) | `parse_object(text)`、`digest(value)` | 结构化文本解析、稳定指纹 |
| 同上 | `LLMService.consume(turn, memory)` | 返回与pending匹配的目的和回复 |
| 同上 | `task_prompt/news_prompt` | 构造任务/普通新闻提示，更新相应调用状态 |
| 同上 | `apply_news(turn, memory, data)` | 校验并保存停矿和宝藏推理 |
| [app/service/task_logging.py](app/service/task_logging.py) | `task_debug_message(turn, response)` | 生成用户提供格式的多行任务日志；由TurnService在成功回合记录 |
| [app/service/task_service.py](app/service/task_service.py) | `TaskService.active(turn, memory, plan, llm, reply, defense_due=False)` | 返回`(prompt, executeCmd)`；回防时让出开拓者，其余时候处理任务并保持站位 |
| [src/agent/protocol.py](src/agent/protocol.py) | `Turn.load(payload)` | 官方请求转观测模型 |
| 同上 | `Pos/Unit/Robot/PlayerTask/CommandResult` | 坐标、单位、机器人、任务点、沙盒结果 |
| 同上 | `distance/station_footprint` | 切比雪夫距离、基地四格 |
| 同上 | `move_command/collect_command/build_command/attack_command` | 官方动作格式构造，仍需动作校验 |
| [src/agent/actions.py](src/agent/actions.py) | `ActionPlan(turn, settings, summon_used=0)` | 初始化当前回合预算和预留 |
| 同上 | `ActionPlan.add(unit_id, command)` | 校验并加入命令，成功True、拒绝False |
| 同上 | `near/near_zone` | 通用相邻交互检查 |
| [src/agent/grid.py](src/agent/grid.py) | `Routes(turn, role, reserved=None, danger=None, allowed=None)` | BFS或风险优先Dijkstra；保存步数、累计风险和第一步，allowed限制巡护区域 |
| [src/agent/worker_safety.py](src/agent/worker_safety.py) | `robot_danger(turn)` | 机器人射程及警戒缓冲的风险图，供工人寻路与矿点筛选 |
| [src/agent/wall_guard.py](src/agent/wall_guard.py) | `WallGuard(strategy)`、`daytime/nighttime` | 单人夜修/完成后双人全天维修，均衡备包、轮流采购与墙内阈值维修 |
| 同上 | `Routes.nearest(goals)/step(goals)` | 最近可达站位/到该站位的第一步 |
| 同上 | `adjacent_cells(turn, targets)` | 建筑或矿点周围的候选交互格 |
| 同上 | `next_step(turn, moving, goal)` | 单个精确目的地的旧兼容接口 |
| [src/agent/construction.py](src/agent/construction.py) | `DefenseLayout`、`select_defense_layout(turn, settings, previous=None)` | 保存/选择炮位、操控格和是否具备共同邻格 |
| [src/agent/brain.py](src/agent/brain.py) | `Strategy.run()` | 就地更新ActionPlan，编排角色行为 |
| 同上 | `route/travel/cost/interact` | 缓存寻路、走一步、估算成本、靠近或操作 |
| 同上 | `opening_stage/opening_worker/stone_targets/missing_walls` | 开局阶段、建造顺序、石头配额和缺墙列表 |
| 同上 | `night_worker/clear_build_cell` | night_worker兼容转入run_worker；昼夜经济统一、墙材保护及建筑位避让 |
| 同上 | `control_position/pioneer_should_defend/move_to_control/operate_weapons` | 选择操控格、黄昏回防、就位和单人轮换 |
| 同上 | `worker/build_weapon/build_wall/wall_keeps_exit` | 后续工人策略、建炮、建墙和通路检查 |
| 同上 | `consume/sell/buy_upgrade/mine` | 使用物品、销售、购买升级券、采矿 |
| 同上 | `task/treasure` | 开拓者接取任务与执行宝藏计划 |
| 同上 | `decide(payload)` | 无状态旧入口，仅返回roleCommandMap内容 |
| [src/agent/combat.py](src/agent/combat.py) | `pair_weapons(turn, roles)` | 保留的旧匹配函数；当前Strategy不调用 |
| 同上 | `segment_entry(start, end, cell)` | 线段与方格相交估值 |
| 同上 | `damage_for(turn, tower, target, health)` | 计算单发预计伤害字典 |
| 同上 | `choose_targets(turn, tower, expected_health, deadline=inf)` | 选择符合数量/范围约束的目标，并更新预测HP |
| [src/agent/server.py](src/agent/server.py) | `Handler/serve` | 转发新网络层，兼容demo旧导入 |

## 函数调用时容易混淆的参数

| 名称 | 含义 | 注意事项 |
|---|---|---|
| `payload` | 原始官方请求字典 | 交给TurnService.decide或Turn.load |
| `turn` | 当前回合的Turn对象 | 作为权威快照使用，不自行修改血量或库存 |
| `role` / `moving` | 一个Unit对象 | 通常为工人或开拓者，不能仅传ID |
| `unit_id` | 请求分配的整数ID | 普通动作用角色ID，攻击用武器ID |
| `controllerId` | 官方响应中的字符串ID | 和内部整数unit_id的类型不同 |
| `target` / `goal` | Pos对象 | goal通常为精确行走格，target可能为障碍物上的交互点 |
| `cells` / `targets` / `goals` | 多个Pos组成的可迭代集合 | 要辨别“对象占用格”和“角色候选站位” |
| `reserved` | 当前回合预留Pos集合 | 给Routes追加禁入格，避免争抢 |
| `footprint` | 建筑完整占地 | 基地为四格，用于判断与任意一格相邻 |
| `memory` | 当前会话GameMemory工作副本 | 保存跨回合信息，由TurnService统一提交 |
| `plan` | 当前ActionPlan | 不跨回合复用；所有输出动作经过add |
| `health` / `expected_health` | 机器人整数ID到预计HP的字典 | 战斗估值使用；choose_targets会修改后者 |
| `deadline` | monotonic时钟的绝对时间点 | 不是剩余秒数，也不是Unix时间戳 |

## 参数维护约定

新增配置时，至少同步`app/config.py`、`config.example.json`、根README参数表与读取该参数的策略。修改官方动作字段要以根目录接口原文为准；不要只改构造器而遗漏ActionPlan检查。

会话级功能新增字段时，检查`GameMemory.observe/record`以及日重置、首轮重置、重复请求测试。新增策略优先从`Strategy`调用`plan.add`；已返回True或被加入`plan.used`的角色，不应继续安排另一个动作。

新增参数`repair_start_day=3`、`repair_stock=5`、`repair_threshold_percent=30`见[参数说明](docs/WORKER_SAFETY.md)。

任务模块采用`app/service/task_prompt.py`与`task_controller.py`中的用户新版提示词/控制器，状态在`task_state.py`，项目适配在`task_service.py`。`temp/`是资料入口，不参与运行/打包。详细函数参数及Postman联调见[任务文档](docs/TASK_INTEGRATION.md)。

升级目标集中于[src/agent/upgrade_policy.py](src/agent/upgrade_policy.py)，由`wall_group/wall_target_level/upgrade_candidates/purchase_needs/upgrades_complete`计算；具体参数见[维护开发文档](docs/MAINTENANCE.md#6-关键模块函数与参数)。

`src/agent/worker_coordinator.py`负责逐工人目的格与让行，`WallGuard.daily_stock`计算第3天5包、此后每日+3及昨日消耗+2的目标；可用`repair_stock_per_day`调整。

昼夜统一经济、维修工升级范围、夜间限制与跨边界测试见[工人昼夜调度](docs/WORKER_SCHEDULE.md)。

0.3.9修复待建/缺墙格造成的寻路与清理往返冲突，新增实际位置/动作诊断；日志证据及函数见[往返修复](docs/WORKER_PATH_FIX.md)。

0.3.10接入用户实战任务控制器：SOP/Skill分库复用、失败经验、API诊断、JSON/XML兼容、4次连续失败退出及25轮冷却；详细函数和状态见[任务接入](docs/TASK_INTEGRATION.md)。

当前0.4.1以用户确认的v0.4为基准，修正成功SOP混入API/脚本失败、跨题结构丢失和短预算问题。新增`app/service/task_evidence.py`，日志证据、函数参数及验证见[失败任务修正](docs/TASK_FAILURE_LEARNING.md)。

0.4.2接入用户提供的`print_log.py`格式：每个新回合记录`[TASK-DEBUG]`，完整打印phaseTask、llmResp、lastCmdResult、本轮prompt和executeCmd。stderr为默认输出，具体映射见[任务日志](docs/TASK_LOGGING.md)。
