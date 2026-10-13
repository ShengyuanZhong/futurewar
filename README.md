# Future War / CoreGeek

以初赛基线为基础，按 `32_docs/` v2.0 文档逐项扩展的参赛 HTTP Agent；规则来源见 `DEVELOPMENT_RULES.md`。保留 CoreGeek 的 `main3.py → src/agent` 基础结构，新增 `CoreGeek/app` 应用层。运行仅依赖 Python 标准库，Python 3.10 及以上。

当前程序版本为 `v1.2.21`，基于用户确认的v0.4基准，版本声明见 [CoreGeek/pyproject.toml](CoreGeek/pyproject.toml)。开局仍为三火箭→采石→17墙蓝图（工人先撤出，随后从外侧完整封闭），随后集中升满一台火箭；第二天起依次强化正中两墙3级、第二台火箭2级、正面其余四墙2→3级、所有火箭3级，最后把其余11块侧后墙升2级；不升级基地。全部目标达成后，两名工人白天继续采矿售矿、批量购包，黄昏回防，夜间双人维修。阈值仍为严格低于30%。详细坐标、镜像、购买规则和关键函数见[建筑维护](CoreGeek/docs/MAINTENANCE.md)。沿用工人独立任务、让行、城墙掩护与动态备货，见[工人协作](CoreGeek/docs/WORKER_COORDINATION.md)。沿用昼夜统一工人经济流程，夜间可继续采购与配送升级券，维修工在实际可达维修区域兼顾升级，详见[昼夜统一调度](CoreGeek/docs/WORKER_SCHEDULE.md)。根据bug_log1/bug_log2进一步拆分通行与施工预约，修复虚拟墙环封路并避免预建位驱离引起的折返；历史问题见[日志定位与修复](CoreGeek/docs/WORKER_PATH_FIX.md)，当前实现见[首日修复](CoreGeek/docs/OPENING_BUG_V1210.md)。v0.4基准已[归档](reports/BASELINE-v0.4.md)。0.4.1根据teamA(2)失败记录修正任务经验：过滤退出码0的业务/脚本失败、保留真实JSON层级及字段、补充解析/引号诊断并压缩短任务步骤；详见[失败任务修正](CoreGeek/docs/TASK_FAILURE_LEARNING.md)。战斗和工人策略沿用基准。0.4.2接入用户提供的任务交互日志格式，见[日志开发文档](CoreGeek/docs/TASK_LOGGING.md)。0.4.3整合新版任务控制器与提示词，包含分类经验、临期预算、占位答案拦截和按奖励增量判定成功；双任务点调度沿用上一版，详见[任务模块接入](CoreGeek/docs/TASK_INTEGRATION.md)。

已进入32强。用户提供的 [32进16需求变更](32_docs/2026云核心网第十届编程大赛-32进16-需求变更.md)、[v2.0任务书](32_docs/任务书.md)、[v2.0接口文档](32_docs/接口文档.md)及[新版报文样例](32_docs/request.txt)是**后续复赛开发**的参照，优先于根目录初赛 v1.0 文档中的冲突条款。v1.0 是变更前封版；当前已接入捣乱鬼move/destroy、召唤坐标和本方机器人move/attack，新增第一夜BOSS策略。小车已解析并用于首日侦察，其它复赛改动继续逐项开发，范围见[复赛规则接入索引](CoreGeek/docs/ROUND_OF_32_RULES.md)，封版证据见[v1.0基准记录](reports/BASELINE-v1.0.md)。

v1.2.23按用户更正保护首日开拓者的任务时间：三次任务尝试全部实际结束且没有活跃任务后，才允许邻格抓捕与近家追捕。任务失败也计一次结束；第三次仅接取、仍在等待题目或提交反馈时均不解锁。工人随时邻格抓捕、采购工用券后回防与其它策略保持，关闭任务配置也不伪造三次尝试。细节见[回防开发文档](CoreGeek/docs/IMP_HOME_DEFENSE_V1222.md)，结果见[首日验证](reports/VALIDATION-v1.2.23.md)。

历史v1.2.22新增[邻格抓捕与首日回防驱离](CoreGeek/docs/IMP_HOME_DEFENSE_V1222.md)：开拓者和工人任何时候发现八邻域内有当前存活敌捣乱鬼，优先catch；三次任务结束后的开拓者与购用券完成后的采购工追捕基地、炮台四格视野范围内的敌捣乱鬼。采购工实际返家一次后继续原补给维护；失视、逃出防区或不可达时结束追逐，不凭旧坐标盲追。抓捕独占本轮动作，活跃任务收到的LLM响应保留到同任务下一轮；不提前计入20金币。细节、函数和诊断见开发文档，结果见[首日验证](reports/VALIDATION-v1.2.22.md)。

历史v1.2.21新增[多BOSS集中破墙与攻基地](CoreGeek/docs/COORDINATED_WALL_ASSAULT_V1221.md)：敌方炮手或最佳操炮位必须拆墙才可攻击时，不再为清炮手耗时，按实际阵型选不同侧的合法召唤位置，让本方BOSS集中攻击同一堵墙，真实破口出现后转攻基地。最佳操炮位已由本方BOSS占住，且全部存活BOSS当前均能清晰攻击基地时，全队忽略敌方角色并持续攻基地。确认炮位缓存只支持几何规划，移动单位仍依真实观测；射程三、45°弹道、同轮不移攻、实际占用与动作反馈保持。偏离浪潮方向是几何和当前风险偏好，不能保证不受浪潮影响；结果见[首日验证报告](reports/VALIDATION-v1.2.21.md)。

历史v1.2.20优化[首日直墙连续施工](CoreGeek/docs/STRAIGHT_WALL_BUILD_V1220.md)：个人施工段按实际首缺墙逐格推进，取消两步距离插入导致的隔格建墙与回扫；直墙正对外侧站位，空闲同轴轨道轴向前进，真实障碍和转角保留八方向绕行。实际到站才建，暂时受阻且仍有个人墙任务时记build_wait，不转收入挖矿；个人最后一墙经下一轮观测确认后立即赴店或侦察，不等整圈完工。购物截止和封闭安全继续保留，根因与结果见[首日验证报告](reports/VALIDATION-v1.2.20.md)。

历史v1.2.19更新[三火箭阵型的 BOSS 攻击与占位](CoreGeek/docs/ROCKET_CONTROL_V1219.md)：敌方已确认三座火箭时，只清理同时能操控三炮的共同位置上的当前可见敌方可控单位，其它炮旁或基地旁角色不引起追击；共同位置无人时，单只或多只 BOSS 均尝试占住可达共同位置并攻击基地。炮位及类型可以使用真实观测后的缓存，人员攻击仍依当前真实视野；混合或不足三炮保留旧策略。射程三、45°弹道、实际占用和同轮不移攻保留，结果见[首日验证报告](reports/VALIDATION-v1.2.19.md)。

v1.2.18更新[开局侦察、炮位记忆与车辆路线](CoreGeek/docs/OPENING_SCOUT_V1218.md)：捣乱鬼第一天先调查敌炮位置，初次确认三炮位置或实际扫描十二格武器圈后才考虑回防，不受购券开关、任务成功数或己方占墙影响。真实观测的炮位和类型保存到 `enemy_weapon_sites`，结合当前全局可见城墙选召唤位置；已知阵型使用 `spawn_ready`，不因失去操炮手当前视野而停止召唤。机器人攻击仍只选当前可见敌单位。侦察工个人施工完毕直接探路，发现实际小车且更快时取车，保持有效取车行程；仅真实 `isDriving` 且白天输出两个连续邻格，夜间恢复步行。范围及结果见[首日验证报告](reports/VALIDATION-v1.2.18.md)。

历史v1.2.17优化[首日分矿与个人交接](CoreGeek/docs/FIRST_DAY_MINING_V1217.md)：从官方 `Zone.remain` 保存真实矿区余量，两名筹石工人联合选择可达石矿，能分矿时优先不同矿并保持有效旧预约；只有单矿时允许不同站位共同采，不让另一人等待。真实三炮及个人施工段完成后，采购工立即赴店，侦察工立即探路，不等待整圈墙齐，也不转去普通挖矿。购券仍在2→1→2三次任务尝试后按成功数冻结0～3张；真实视野、外侧施工、敌占位暂跳和购物截止保持。缺失余量的旧输入仅以10作策略上限，诊断保留未知值。范围及结果见[首日验证报告](reports/VALIDATION-v1.2.17.md)。

历史v1.2.16按真实后续目的安排[首日建墙分工](CoreGeek/docs/WALL_SCHEDULE_V1216.md)：采购工以报文中的商店为目的，另一工以敌基地为目的，将17墙划成稳定的两段，从较远侧向离开侧推进；实际外侧施工路径相对最近墙只增加两步以内时保留施工方向，已有有效途中目标继续完成。相邻施工与远墙选择使用同一下一墙，采石按各自真正剩余墙数分份，初始已有足量石头时按实际背包切分施工段。三炮完成后，外侧工人的首日日间路线保持在外侧，防止穿入未封内圈再被拉回。首日已腾空的历史占点不再抢占远程施工；购物截止、真实撤出、夜间缺口接力和BOSS协作保持。范围及结果见[首日验证报告](reports/VALIDATION-v1.2.16.md)。

历史v1.2.15采用[永久封闭建家与采石协调](CoreGeek/docs/SEALED_HOME_V1215.md)：沿用两张用户图的17墙、三火箭和外侧P位，取消白天临时门、门石预留与自动拆墙；三炮建成后，工人先按真实观测撤出将被封闭的内圈，再从外侧逐块施工。建墙同时检查本轮其它施工目标，不把同轮移动当成已离开。首夜维修改用可达外侧邻墙格，旧观测中已困在内部的角色仍可就地维修。采石按真实缺墙、在家工人库存与稳定配额安排，邻近可施工时先用已有石头建墙，够材后停止额外筹石；同矿可用不同采集站位。首日购物截止、2→1→2三任务及v1.2.14 BOSS协作保持。验证范围见[首日报告](reports/VALIDATION-v1.2.15.md)。

非集中破墙场景沿用v1.2.14的[多BOSS进位与直攻基地](CoreGeek/docs/BOSS_FORMATION_V1214.md)，三火箭人员范围和单 BOSS 占位以[v1.2.19](CoreGeek/docs/ROCKET_CONTROL_V1219.md)为准：混合或不足三炮仍先清真实可见炮手；转攻基地后，多只BOSS中前排优先占住真实可见的共同操炮位，每次移动的落脚格均须仍有清晰基地射线；后排先寻找实际可达的基地直射位置，再考虑拆墙或炮台。仅在同伴已发出移动、通路暂时被其本轮位置占住时短等，最多3轮；不预测同伴已腾空、不合并移动攻击。历史失败只封禁原目标和原站位的射线，不再迫使其它清晰射线一律靠近。首日购物截止、工人分工及任务顺序沿用v1.2.13。

历史v1.2.13更新[首日购物截止与持续工作](CoreGeek/docs/BUYER_DEADLINE_V1213.md)：首日白天两名工人不提前回防，也不预留返程；采购工按实际赴店路径、可能拆入口、腾包、批购一轮、最多三轮用券及两轮让行余量计算出发截止，墙齐或到截止就赴店，购物优先于继续建墙。三次任务未结束仅等店，结算后仍按真实成功数购用0～3张；采购出发批准与真实施工记录分开，侦察不假设墙已完成，召唤仍需当前普通共享视野。开拓者三次任务后回防，夜间和第二天后的维护沿用原逻辑。

历史v1.2.12的[采购工人分工](CoreGeek/docs/WORKER_BOSS_V1212.md)仍保留；固定购手身份、工人背包与反馈账本、真实商店坐标、工人让行和首夜缺口接力继续沿用；旧临时入口以v1.2.15永久墙策略替代。

历史v1.2.8增加[真实布局侦察与阵型召唤](CoreGeek/docs/LAYOUT_SCOUTING.md)：非留守工人在三炮及可建原墙实际完成后立即探路，不再等L2火箭和修包。敌基地/墙全局可见，炮台及普通角色受视野限制，BOSS没有视野。布局通过真实三炮或12格武器圈累计扫描确认；实际用券还需活侦察工人就近、当前普通共享视野覆盖共同操炮位及可见炮手。按实测炮阵选择合法出生点，利用45度缺口、直射或一堵墙突破，并维持第一夜视野。购券仍在两任务结束后按成功数冻结0/1/2张，只有use等待侦察；火箭升级采购等购券尝试之后。缺口留守、任务prompt、普通升级及经济路线保持。首日完整时序见[FIRST_DAY_PLAN](CoreGeek/docs/FIRST_DAY_PLAN.md)。

v1.2.6阶段用户已重新提供`32_docs/任务书.md`，后续以当前v2正文、接口文档及本轮建造区域澄清为参照；保留原件，不将日志或历史策略当作官方规则。

## 阅读导航

沿用[有限追击与双BOSS](CoreGeek/docs/BOSS_EFFICIENCY.md)的战斗与库存反馈框架；旧“财富提前买两张、晚间降为一张、后续收入补第二张”采购条件已由任务结果冻结数量替代。

当前[视野协作](CoreGeek/docs/RAID_SCOUTS.md)以[开局侦察](CoreGeek/docs/OPENING_SCOUT_V1218.md)和[个人任务交接](CoreGeek/docs/FIRST_DAY_MINING_V1217.md)为准：捣乱鬼先完成初次敌炮调查，再考虑缺口后备；侦察工个人施工完成即走，采购工独立赴店。观察从扫描切换到覆盖操炮位，站在敌建造圈外并避让召唤点/射线。已确认炮位失视后仍支持阵型召唤；移动角色攻击要求当前真实观测，不向记忆或推断敌角色格盲目开火。旧“工人必须等防守补给完成、固定后侧观察、固定后方出生”的条件已撤销。

v1.2.2增加[机器人诊断日志](CoreGeek/docs/ROBOT_DIAGNOSTICS.md)，保持v1.2.1策略：robot_observation记录本方机器人列表与出生/移出状态，robot_diagnostic逐回合输出实际位移、前轮反馈、候选/HP/墙/射程/cache、射击格筛选及最终决定原因。默认INFO stderr，enable_robot_diagnostics可关闭；动作合法不代表命中，日志不自行判断击杀。

历史v1.2.1修正[BOSS操控和出生点](CoreGeek/docs/BOSS_RAID.md)：每回合重查三类炮台八邻格内当前存活的工人/开拓者，优先可直接命中、按当前HP尽快清理；有操炮者时不转攻基地，清空后立即尝试基地，重新进入炮旁者再次抢占优先级。按用户新图，敌基地(9,22)首选(6,22)/(6,21)，其它位置平移/镜像；完整6×6建造区固定排除2格，替代旧版过大的5格默认排除。

历史v1.2.0增加[第一天BOSS袭击](CoreGeek/docs/BOSS_RAID.md)：两个任务结束后开拓者赴店，按实价买一张BOSS召唤令并远程指定敌基地后方出生点，再返回操炮位；第一夜独立操控本方BOSS追击敌方操炮者，绕墙找射线，必要时破墙，确认死亡后攻基地。接入summonRobotList归属，己方BOSS不再进入炮台取分和工人危险估值。

旧v1.1.3–v1.2.5临时绕墙策略已删除，不再执行连续5回合判定、额外建墙或拆临墙；当前处理见[缺口接力](CoreGeek/docs/GAP_DEFENSE.md)。

v1.1.2将己区、敌区火箭选点统一为：中心有活机器人，九宫格内Σ(击杀分/当前剩余HP)最大，使用精确分数求和。三级沿用两发己区、一发敌区，敌区为空时三发防守；详见[火箭半区策略](CoreGeek/docs/ROCKET_SECTORS.md)。上一版v1.1.1的总分选点证据保留在历史报告中。

v1.1.0新增捣乱鬼策略：昼夜寻找并连续破坏对方半区矿石，不逃避机器人，官方观测到复活后立即继续行动。架构、半区公式、关键函数与状态见[捣乱鬼开发说明](CoreGeek/docs/IMP_STRATEGY.md)。

v1.0.2 修正升级完成后的经济停止：两名工人白天继续采矿、售矿和购包，黄昏回防，夜间双人修墙；购包为下一批采矿预留背包空间，详见[完成后的经济循环](CoreGeek/docs/COMPLETED_ECONOMY.md)。

v1.0.1 优化两名工人的行程：有效矿点/墙位保持、采石与施工并行、临近入夜不发起无法完成的施工、让行失败后尝试其它工作、同种升级券只安排一人采购。原因、函数与状态字段见[工人效率修复](CoreGeek/docs/WORKER_EFFICIENCY.md)。v1.0 封版记录保留，复赛新增功能仍按既有适配索引逐项推进。

- [快速开始](#快速开始)：启动服务、检查入口。
- [目录与模块职责](#project-layout)：完整文件树、各层边界。
- [整体架构与回合流程](#architecture)：请求如何变成三个响应字段。
- [配置、命令行与关键参数](#configuration)：参数含义、默认值、读取位置和修改影响。
- [数据模型与坐标约定](#models)：`Turn`、`Unit`、`Pos` 等对象及字段映射。
- [应用层关键函数](#application-api)：网络、会话、记忆、LLM、任务服务。
- [策略层关键函数](#strategy-api)：动作校验、寻路、角色策略、战斗估值。
- [任务、新闻与宝藏流程](#task-workflow)：跨回合数据如何传递。
- [代码调用与扩展示例](#examples)：如何调用服务，如何添加新策略。
- [测试、回放与报告](#verification)：工具参数、测试分工、结果解释。
- [修改定位与常见问题](#maintenance)：按实际问题找到代码入口。
- [当前限制与后续工作](#limitations)：已实现功能与待确认部分。

首次阅读建议先看目录和架构，再看 `TurnService.decide → Strategy.run → ActionPlan.add` 三个函数。只调整采矿、武器组合等策略时，优先阅读配置和策略层章节。

## 快速开始

在本目录执行：

```powershell
python CoreGeek/main3.py 8080
```

比赛 Linux 环境入口：

```bash
bash run.sh 8080
```

监听 `0.0.0.0`，任意路径接收 POST JSON；`GET /health` 可用于检查进程状态。启动前无需安装第三方运行依赖。进程日志写入 stderr。

**默认即可执行“三座火箭 → 采石 → 建围墙”，无需另建配置文件。** 基地2×2外第一圈是武器区，第二圈是墙区；默认在合法圈层内采用用户新图的17墙与后排三火箭，左右镜像；工人从外侧施工并封齐全部计划墙，详见[永久封闭与采石](CoreGeek/docs/SEALED_HOME_V1215.md)。显式layouts也不能越过圈层约束。

## 文档入口

| 文档 | 用途 |
|---|---|
| [CoreGeek 使用说明](CoreGeek/README.md) | 启动、配置、回放、测试、部署 |
| [开发与维护文档](CoreGeek/docs/DEVELOPMENT.md) | 分层架构、调用链、状态管理、修改方式 |
| [接口与 LLM 协作](CoreGeek/docs/PROTOCOL.md) | 官方收发结构、动作约束、异步任务交互 |
| [规则覆盖与差异登记](CoreGeek/docs/RULE_COVERAGE.md) | R01–R08、D01–D08、仍待确认的行为 |
| [开局防御策略](CoreGeek/docs/OPENING_DEFENSE.md) | 三火箭布局、攒石建墙、单人轮换、测试与升级步骤 |
| [实现现状](DEMO.md) | 本轮完成范围与未完成的外部验证 |
| [任务交互日志](CoreGeek/docs/TASK_LOGGING.md) | 完整任务字段、日志格式、位置与回合边界 |
| [失败任务修正](CoreGeek/docs/TASK_FAILURE_LEARNING.md) | 日志证据、SOP污染、JSON结构、短预算与函数参数 |
| [任务流程优化](CoreGeek/docs/TASK_OPTIMIZATION.md) | 新版控制器来源、接入范围及验证入口 |
| [任务模块接入](CoreGeek/docs/TASK_INTEGRATION.md) | 新版控制器、SOP/Skill、状态与函数参数、预算和Postman逐轮调试 |
| [复赛规则接入索引](CoreGeek/docs/ROUND_OF_32_RULES.md) | `32_docs/` 的来源优先级、关键变更、受影响模块与未实现范围 |
| [捣乱鬼开发说明](CoreGeek/docs/IMP_STRATEGY.md) | 半区、独立寻路、连续destroy、死亡/复活、日志与函数 |
| [火箭半区策略](CoreGeek/docs/ROCKET_SECTORS.md) | 所有火箭占用中心、Σ(分/当前HP)、精确计算、三级2+1、预测血量 |
| [缺口接力](CoreGeek/docs/GAP_DEFENSE.md) | 合法建造范围、工人占缺口、捣乱鬼接替与BOSS采购预算 |
| [第一天BOSS袭击](CoreGeek/docs/BOSS_RAID.md) | 买券/召唤/返岗、归属解析、夜间追击/绕墙/破墙及原生机器人指令 |
| [机器人诊断日志](CoreGeek/docs/ROBOT_DIAGNOSTICS.md) | 乱走/不攻击的原因、反馈/HP事实、结构化字段和实战资料保留 |
| [布局侦察与阵型召唤](CoreGeek/docs/LAYOUT_SCOUTING.md) | 真实武器圈扫描、持续操炮区视野、四种阵型/镜像、单墙突破及函数参数 |
| [首夜视野协作](CoreGeek/docs/RAID_SCOUTS.md) | 当前规则入口及v1.2.3–v1.2.7历史观察策略 |
| [有限追击与双BOSS](CoreGeek/docs/BOSS_EFFICIENCY.md) | 绕路/无效追位预算、基地回退、双券交易反馈与部署账本 |
| [v1.2.4验证报告](reports/VALIDATION-v1.2.4.md) | 独立效率审计、双购买/部署、共享视野与完整回归检查 |
| [v1.2.21集中破墙与基地集火](CoreGeek/docs/COORDINATED_WALL_ASSAULT_V1221.md) / [验证](reports/VALIDATION-v1.2.21.md) | 保护炮手识别、不同侧合法召唤、同墙突破与全队直攻基地优先 |
| [v1.2.20直墙连续施工](CoreGeek/docs/STRAIGHT_WALL_BUILD_V1220.md) / [验证](reports/VALIDATION-v1.2.20.md) | 个人首缺墙逐格建、外侧轴向轨道、受阻等待与实际完工交接 |
| [v1.2.19三火箭 BOSS](CoreGeek/docs/ROCKET_CONTROL_V1219.md) / [验证](reports/VALIDATION-v1.2.19.md) | 共同三炮位限定人员攻击、单只/多只安全占位与基地攻击、混合阵型兼容 |
| [v1.2.18开局侦察](CoreGeek/docs/OPENING_SCOUT_V1218.md) / [验证](reports/VALIDATION-v1.2.18.md) | 捣乱鬼先探敌、真实炮位永久记忆、已知阵型失视可召唤及侦察车辆路线 |
| [v1.2.17首日分矿](CoreGeek/docs/FIRST_DAY_MINING_V1217.md) / [验证](reports/VALIDATION-v1.2.17.md) | 官方remain观测、两矿联合分配、有效预约与单矿回退、个人施工完工即采购或侦察 |
| [v1.2.16建墙调度](CoreGeek/docs/WALL_SCHEDULE_V1216.md) / [验证](reports/VALIDATION-v1.2.16.md) | 真实目的坐标、稳定两段施工、外侧站位成本、按段筹石及历史缺口取消远程抢单 |
| [v1.2.15永久封闭与采石](CoreGeek/docs/SEALED_HOME_V1215.md) / [验证](reports/VALIDATION-v1.2.15.md) | 工人先撤出、全部17墙永久施工、外侧维修、稳定采石与炮手让位 |
| [v1.2.14多BOSS进位](CoreGeek/docs/BOSS_FORMATION_V1214.md) / [验证](reports/VALIDATION-v1.2.14.md) | 前排占共同操炮位、后排寻找基地直射位置及按射线记录失败 |
| [v1.2.13购物截止](CoreGeek/docs/BUYER_DEADLINE_V1213.md) / [验证](reports/VALIDATION-v1.2.13.md) | 首日工人不提前回防、实际赴店预算、购物优先于墙齐及真实施工记录 |
| [v1.2.12采购工人](CoreGeek/docs/WORKER_BOSS_V1212.md) / [验证](reports/VALIDATION-v1.2.12.md) | 真实商店、固定双工分工、工人背包反馈、先锋三次后回防 |
| [v1.2.11首日与车辆](CoreGeek/docs/TASK2_VEHICLE_V1211.md) / [验证](reports/VALIDATION-v1.2.11.md) | 2→1→2、三任务优先、驾驶两步及侦查取车 |
| [v1.2.10首日修复](CoreGeek/docs/OPENING_BUG_V1210.md) / [验证](reports/VALIDATION-v1.2.10.md) | bug_log1/2根因、施工预约、任务行程关闭、IMP侦查及关键字段 |
| [v1.2.9验证报告](reports/VALIDATION-v1.2.9.md) | 历史三次任务、三券、17墙入口、武器清障与HTTP/回归 |
| [v1.2.8验证报告](reports/VALIDATION-v1.2.8.md) | 真实视野门、阵型召唤、单墙突破和HTTP/回归结果 |
| [v1.2.7历史报告](reports/VALIDATION-v1.2.7.md) | 两任务后固定购券、升级采购顺序、45度攻击及跨回合HTTP |
| [v1.2.6验证报告](reports/VALIDATION-v1.2.6.md) | 删除绕墙、缺口接力、BOSS采购/使用及跨回合HTTP验证 |
| [v1.2.3验证报告](reports/VALIDATION-v1.2.3.md) | 视野协作、占点留守、夜间稳定及回归/HTTP检查 |
| [v1.2.2验证报告](reports/VALIDATION-v1.2.2.md) | 日志开关策略一致性、诊断回归及HTTP/压力检查 |
| [v1.2.1历史报告](reports/VALIDATION-v1.2.1.md) | 逐回合操炮者优先、新图召唤几何及压力检查 |
| [v1.2.0历史报告](reports/VALIDATION-v1.2.0.md) | 原BOSS流程、归属/攻击回归及压力检查 |
| [v1.1.3历史报告](reports/VALIDATION-v1.1.3.md) | 占点防御的回归及原策略压力检查 |
| [v1.1.2历史报告](reports/VALIDATION-v1.1.2.md) | 比值选点的回归及独立压力检查 |
| [v1.1.1历史报告](reports/VALIDATION-v1.1.1.md) | 上一版半区分配与总分选点证据 |
| [v1.1.0验证报告](reports/VALIDATION-v1.1.0.md) | 本次捣乱鬼接入的完整回归、压力和新版报文回放 |
| [工人效率修复](CoreGeek/docs/WORKER_EFFICIENCY.md) | v1.0.1 的目标保持、施工/采矿分工、日照截止和单人采购 |
| [完成后的经济循环](CoreGeek/docs/COMPLETED_ECONOMY.md) | 全部升级后白天采矿售矿购包、黄昏返岗及背包容量 |
| [v1.0.2验证报告](reports/VALIDATION-v1.0.2.md) | 当前工人策略的回归、合成观测和HTTP证据 |
| [v1.0.1历史报告](reports/VALIDATION-v1.0.1.md) | 工人行程和施工效率修复证据 |
| [v1.0基准记录](reports/BASELINE-v1.0.md) | 32强阶段封版源码、测试与复赛兼容边界 |
| [实战日志往返修复](CoreGeek/docs/WORKER_PATH_FIX.md) | log1/log2证据、统一路径预留、重建场景与诊断字段 |
| [昼夜统一调度](CoreGeek/docs/WORKER_SCHEDULE.md) | 跨昼夜任务连续、夜间升级/采购、维修岗位限制与函数参数 |
| [工人协作与备货](CoreGeek/docs/WORKER_COORDINATION.md) | 单人任务、让行、墙掩护、值守分区及按日备货参数 |
| [v0.4.3验证报告](reports/VALIDATION-v0.4.3.md) | 封版前任务模块测试证据；旧报告独立保留 |
| [开发规则](DEVELOPMENT_RULES.md) | 本地开发约束、初赛历史规则索引和复赛来源顺序 |
| [初赛任务书](任务书.md) / [初赛接口文档](接口文档.md) | 初赛 v1.0 原件，供追溯，复赛冲突处以 `32_docs/` 为准 |

## 本地验证

```powershell
python CoreGeek/run_tests.py
python CoreGeek/tools/smoke_server.py --output reports/http-smoke-v1.2.8.json
python CoreGeek/tools/replay.py request.txt --output reports/sample-response-v1.2.8.json
python CoreGeek/tools/validate.py --cases 20 --output reports/validation-v1.2.8.json
```

`replay.py` 只计算响应，不执行响应中的沙盒命令或 LLM 请求。验证脚本生成的压力结果是合成观测检查，不是比赛模拟、官方难度或胜率。

<a id="project-layout"></a>

## 目录与模块职责

```text
futurewar/
├── README.md                         # 项目总览、架构、关键函数与参数（本文）
├── DEVELOPMENT_RULES.md              # 团队开发约束，含R01–R08和D01–D08索引
├── 32_docs/                         # 32进16复赛 v2.0 任务书、接口、变更说明和报文样例
├── 任务书.md                         # 官方游戏规则原文
├── 接口文档.md                       # 官方HTTP/JSON接口原文
├── request.txt                       # 官方请求样例，测试和离线回放的输入来源
├── response.txt                      # 官方动作目录样例，不能当有效JSON直接读取
├── DEMO.md                           # 当前实现范围和外部验证缺口
├── run.sh                            # 仓库级入口，转交CoreGeek/run.sh
├── .gitignore                        # 忽略缓存、构建中间文件和本地配置
├── reports/
│   ├── VALIDATION.md                 # 人类可读的历史验证报告
│   ├── BASELINE-v1.0.md              # 当前程序封版与复赛适配边界
│   ├── validation-v1.2.4.json          # 封版测试、压力、环境与源码哈希
│   ├── http-smoke-v1.2.4.json          # 封版真实进程HTTP验证
│   ├── sample-response-v1.2.4.json     # 封版对初赛样例的响应
│   ├── validation.json               # 测试/压力结果、环境、源码和规则文件SHA256
│   ├── http-smoke.json               # 实际启动进程后的HTTP检查结果
│   └── sample-response.json          # 原请求样例生成的离线响应
└── CoreGeek/
    ├── README.md                     # 子项目运行指南、模块/函数速查
    ├── main3.py                      # Python启动入口，处理端口、配置、日志和模块路径
    ├── run.sh                        # 比赛启动脚本，最终exec Python进程
    ├── pyproject.toml                # 包名、版本、Python要求、setuptools打包规则
    ├── config.example.json           # 配置模板，不包含已核验建造区域
    ├── config.local.json             # 可自行复制模板创建，不随代码提交
    ├── run_tests.py                  # unittest发现与执行入口
    ├── app/
    │   ├── __init__.py               # app包声明
    │   ├── config.py                 # Settings配置模型、配置校验、建造位置换算
    │   ├── server.py                 # HTTP网络适配、响应序列化、错误处理
    │   └── service/
    │       ├── __init__.py           # 服务包声明
    │       ├── turn_service.py       # 整个回合的编排、缓存、锁和事务式状态提交
    │       ├── memory.py             # 额度、新闻、任务、失败反馈和开局布局记忆
    │       ├── llm_service.py        # 构造prompt、消费LLM回复、校验新闻推理结果
    │       ├── task_prompt.py        # 用户提供的自进化prompt生成器
    │       ├── task_controller.py    # 用户控制器：任务推进、SOP/Skill和失败冷却
    │       ├── task_state.py         # 同局任务状态、点位快照和经验库
    │       ├── task_evidence.py      # 命令业务结果分类、JSON结构与错误诊断
    │       ├── task_logging.py       # 任务交互日志格式
    │       ├── task_context.py       # 任务开始轮、旧协议兼容及辅助工具
    │       └── task_service.py       # 活跃任务期间的答案/沙盒命令处理
    ├── src/
    │   └── agent/
    │       ├── __init__.py           # agent包声明
    │       ├── protocol.py          # 观测数据模型、规则常量、坐标与命令构造器
    │       ├── vehicle.py           # 白天已驾驶角色两段真实安全路径
    │       ├── grid.py              # BFS/风险优先Dijkstra、目标邻域和巡护区域
    │       ├── worker_coordinator.py # 独立任务、目的格预留、堵路让行
    │       ├── worker_safety.py     # 机器人风险图
    │       ├── upgrade_policy.py    # 集中升炮、墙分组/目标等级与完成判断
    │       ├── wall_guard.py        # 维修工分配、备货、回岗和夜间修墙
    │       ├── imp_policy.py        # 捣乱鬼半区、目标保持、连续破坏和复活恢复
    │       ├── imp_defense.py       # 邻格catch、首日先锋/采购工反侦察回防
    │       ├── map_regions.py       # 捣乱鬼/炮台共用的对角线半区与基地侧判断
    │       ├── actions.py           # 十四动作校验、共享金币和目标格预留
    │       ├── construction.py      # 在当前建造格内选三炮位置与共同操控格
    │       ├── combat.py            # 弹道相交、选敌伤害估值、旧匹配函数
    │       ├── gap_defense.py      # 被占墙位的合法施工、工人占缺口和捣乱鬼接力
    │       ├── day_gate.py          # 已退休的兼容入口，不产生拆墙/门石/封门动作
    │       ├── sealed_home.py       # 完整墙体外部分类、工人撤出、封闭安全和外侧维修
    │       ├── wall_schedule.py     # 首日施工两段、逐墙外侧直轨、个人完工与交接
    │       ├── stone_planner.py     # 墙材配额、真实矿余量与首日两工联合分矿
    │       ├── first_day_tasks.py   # Task2→Task1→Task2独立尝试与幂等结束/成功账本
    │       ├── boss_raid.py         # 第一天三次任务后按成功数买0～3张BOSS券、侦察后逐张召唤
    │       ├── robot_raider.py      # 基地集火优先、同墙突破、三火箭共同位筛选与清障
    │       ├── wall_assault.py      # 保护炮手几何判定、不同侧集中破墙与召唤点规划
    │       ├── boss_formation.py    # 单只/多只BOSS占共同三炮位、进位和通路短等
    │       ├── robot_combat.py      # 机器人射程/可见目标/城墙遮挡检查
    │       ├── raid_diagnostics.py  # BOSS逐回合候选/移动/攻击事实与原因日志
    │       ├── raid_scouts.py       # 捣乱鬼先探敌、炮阵扫描、工人取车、召唤/视野分离
    │       ├── first_night_defense.py # 先保留BOSS费用后的首日补给、回防与维修
    │       ├── summoning.py         # 实际/镜像敌基地、后排出生点与召唤区域约束
    │       ├── brain.py             # 昼夜策略、经济、建造、回防、接任务、宝藏行动
    │       └── server.py            # 旧agent.server入口的兼容转发
    ├── tests/
    │   ├── __init__.py              # 测试包声明
    │   ├── fixtures.py              # 合成单位、请求和测试专用布局
    │   ├── test_protocol.py         # 坐标、输入、昼夜、障碍、命令结果解析
    │   ├── test_actions.py          # 十二动作、角色权限、资源与冲突约束
    │   ├── test_combat_strategy.py  # 弹道/伤害估值、回防、经济和宝藏策略
    │   ├── test_opening_defense.py  # 三火箭开局、攒石建墙、单人轮换和夜采
    │   ├── test_default_opening.py  # 无配置默认开局、基地边界、通道及配置优先级
    │   ├── test_u_layout.py         # 图样、左右镜像、维修通路及两侧完整开局
    │   ├── test_maintenance.py      # 升级券顺序、回血与毁墙补建回归
    │   ├── test_worker_safety.py    # 避险、批量采购、专人夜修与反馈
    │   ├── test_services.py         # 多轮任务、LLM额度、幂等与状态隔离
    │   └── test_http_config.py      # HTTP响应、错误处理、配置校验
    ├── tools/
    │   ├── replay.py                # 从JSON/JSONL观测生成离线响应
    │   ├── smoke_server.py          # 启动真实CLI进程，检查健康接口并POST原样例
    │   └── validate.py              # 执行测试、合成观测压力检查、生成哈希报告
    ├── docs/
    │   ├── DEVELOPMENT.md           # 维护流程与设计说明
    │   ├── PROTOCOL.md              # 官方协议接入和内部LLM协作格式
    │   ├── OPENING_DEFENSE.md        # 开局阶段、共同站位、冷却与回归案例
    │   ├── U_LAYOUT.md              # U形模板坐标、左右示意图、函数参数及验证
    │   ├── MAINTENANCE.md           # 升级阶段、购券/用券、前后顺序与缺口补建
    │   ├── WORKER_SAFETY.md         # 避险算法、批量计算、维修工参数/接口
    │   ├── assets/u-layout-reference.png # 用户原始设计图
    │   └── RULE_COVERAGE.md          # 覆盖矩阵、实现选择、未确认差异
    └── dist/
        ├── coregeek_futurewar-0.2.0-py3-none-any.whl  # 历史构建产物
        ├── coregeek_futurewar-0.3.0-py3-none-any.whl  # 历史三火箭策略包
        ├── coregeek_futurewar-0.3.1-py3-none-any.whl  # 历史默认建造版本
        ├── coregeek_futurewar-0.3.2-py3-none-any.whl  # 用户认可的基准版本
        ├── coregeek_futurewar-0.3.3-py3-none-any.whl  # 历史维护策略版本
        └── coregeek_futurewar-0.3.10-py3-none-any.whl  # 当前可选构建产物
```

`config.local.json` 是可选文件，初始不会自动创建。`dist/` 由打包生成；`__pycache__/`、`build/`、`*.egg-info/` 是运行或构建缓存，不属于业务架构。

| 层次 | 主要位置 | 输入与输出 | 职责边界 |
|---|---|---|---|
| 启动层 | `main3.py`、两级`run.sh` | 端口、配置路径 → 服务进程 | 不做游戏决策 |
| 网络层 | `app/server.py` | HTTP字节 → JSON请求；响应字典 → HTTP字节 | 不直接决定角色动作 |
| 应用服务层 | `app/service/` | 当前观测、历史记忆 → 完整回合响应 | 管理跨回合状态、任务和LLM协作 |
| 领域模型层 | `src/agent/protocol.py` | 官方字典 → `Turn/Unit/Pos` | 提供规则相关数据与查询方法 |
| 策略计算层 | `brain.py`、`construction.py`、`grid.py`、`combat.py` | 观测、配置、记忆 → 候选动作 | 决定建造布局、角色分工、行走和攻击目标 |
| 动作约束层 | `src/agent/actions.py` | 候选动作 → 接受或拒绝 | 统一检查权限、预算、数量、互斥与位置 |
| 验证与工具层 | `tests/`、`tools/`、`reports/` | 夹具或历史观测 → 断言、响应、报告 | 不参与比赛主循环 |

程序没有数据库、Web前端和本地LLM客户端。HTTP流量是判题器主动请求本程序；`prompt` 与 `executeCmd` 随响应交回判题器，再由官方执行。

<a id="architecture"></a>

## 整体架构与回合流程

### 组件关系

```mermaid
flowchart TD
    Launch[main3.py / run.sh] --> Config[Settings.load]
    Config --> Server[app.server / AgentServer]
    Judge[官方判题器] -->|POST 当前观测| Server
    Server --> Service[TurnService.decide]
    Service --> Turn[Turn.load / 观测模型]
    Service --> Session[Session / GameMemory]
    Service --> LLM[LLMService / TaskService]
    Service --> Strategy[Strategy.run]
    Strategy --> Grid[Routes / BFS]
    Strategy --> Layout[construction / 三炮与共同站位]
    Strategy --> Combat[单人选炮 / 选敌估值]
    Strategy --> Raid[第一天买券召唤 / 第一夜BOSS独立操控]
    Strategy --> Plan[ActionPlan.add]
    LLM --> Plan
    Plan --> Result[roleCommandMap]
    LLM --> Fields[prompt / executeCmd]
    Result --> Commit[提交会话记忆和响应缓存]
    Fields --> Commit
    Commit --> Server
    Server -->|JSON 响应| Judge
```

图中箭头表示调用或数据使用关系。实现保留两个Python包：`app` 位于CoreGeek根目录，`agent` 位于CoreGeek/src。入口脚本会把`src`加入模块搜索路径；工具脚本会同时加入CoreGeek与CoreGeek/src。旧`agent.brain.decide`包装器为兼容用途，会延迟导入应用默认配置。

### 一次请求的执行顺序

1. `Handler.do_POST()`读取`Content-Length`，检查体积、编码与JSON对象形状，再调用`TurnService.decide(payload)`。
2. `Turn.load(payload)`解析观测；检查41×32地图、回合范围、阵营、全局ID重复和传入存活单位坐标等。
3. `digest(payload)`产生请求指纹。服务以`(team_id, team_type)`定位`Session`，对重复、冲突、乱序请求做处理。
4. 拷贝原`GameMemory`，调用`observe(turn)`处理换日、任务原文变化、宝藏结果与失败采集反馈。
5. `LLMService.consume()`取出与上次发起调用匹配的下一轮回复。新闻结果交给`apply_news()`；任务回复交给`TaskService.active()`。
6. 创建本轮`ActionPlan`及`Strategy`，先运行`ImpDefense.catch_available()`检查工人以及首日三次任务已结束的开拓者，为合法邻格抓捕保留动作，再调用任务服务。抓捕延迟的LLM响应只在同一任务后续回合恢复；其它回防条件继续由`defense_due`传入，首日三次任务不预留回家时间预算。
7. 运行`Strategy`，先安排开拓者，再安排工人。白天工人执行开局阶段或后续经济，维修工备货和黄昏回岗；普通工人昼夜执行相同经济流程，夜间受避敌与禁建约束；维修工在实际可达邻墙区域维修及升级。全部升级达标后，两工人白天夜晚都由WallGuard接管，白天轮流买包。动作全部进入`ActionPlan.add()`，只将通过校验的命令写入计划。
8. 任务外按配置与普通额度决定是否调用`news_prompt()`。它仅构造返回字符串，不在进程内等待LLM。
9. `GameMemory.record()`记录本轮计划，再统一提交新会话、响应深拷贝及最近回合号。内部异常不会提交中间记忆。
10. `Handler.send_json()`将响应编码为UTF-8，写入HTTP状态、字节长度和JSON内容。

响应固定为以下三个字段；没有动作时也不增加`idle`等非官方动作：

```json
{
  "roleCommandMap": {},
  "prompt": "",
  "executeCmd": ""
}
```

### 对象的生命周期

| 对象 | 生命周期 | 为什么这样设计 |
|---|---|---|
| `Settings` | 启动时创建，整个服务复用 | 策略参数不在每次请求重新加载 |
| `TurnService` | 整个HTTP服务进程 | 跨回合保存会话和额度 |
| `Session`、`GameMemory` | 每个队伍/阵营会话 | 隔离新闻、任务、请求缓存与日计数 |
| `Turn` | 单次观测 | 权威输入快照，不自行更新血量、金币或背包 |
| `ActionPlan` | 当前回合 | 聚合动作和共享预算，不跨回合保留占位 |
| `Strategy`、`Routes` | 当前策略执行 | 路线缓存随当前角色和预留格变化 |
| `expected_health` | 本轮选敌计算 | 只辅助分配火力，不写回真实机器人状态 |

`Turn`等模型使用冻结dataclass，但其中的字典不是深度不可变对象；调用方仍应把观测视为只读。未来收到的金币、库存和HP以判题器新观测为准，不能把本地预计收益当作真实状态。

<a id="configuration"></a>

## 配置、命令行与关键参数

### 启动参数和环境变量

默认以下命令均在仓库根目录执行：

```powershell
python CoreGeek/main3.py 8080
Copy-Item CoreGeek/config.example.json CoreGeek/config.local.json
python CoreGeek/main3.py 8080 --config CoreGeek/config.local.json
```

Linux可从仓库根目录运行，也可直接指定CoreGeek脚本：

```bash
bash run.sh 8080 --config CoreGeek/config.local.json
bash CoreGeek/run.sh 8080
PYTHON=/usr/bin/python3 bash CoreGeek/run.sh 8080
```

| 参数/变量 | 类型/默认值 | 读取位置 | 含义 |
|---|---|---|---|
| `port` | 必填整数，1–65535 | `main3.main()` | 监听端口，比赛由系统传入 |
| `--config` | 可选文件路径 | `main3.main()` → `Settings.load()` | 使用指定JSON配置 |
| `FUTUREWAR_CONFIG` | 可选环境变量 | `Settings.load()` | 未传配置路径时使用的配置文件 |
| `PYTHON` | shell环境变量，默认`python3` | `CoreGeek/run.sh` | Bash入口调用的解释器路径 |
| 监听地址 | 固定`0.0.0.0` | `app.server.serve()` | 对齐官方启动约定，不是JSON配置项 |

配置选择顺序：显式`--config`路径 → `FUTUREWAR_CONFIG` → `Settings`默认值。`config.local.json`不会仅因存在就自动读取，必须传参或设置环境变量。配置文件支持UTF-8及UTF-8 BOM；相对路径按**启动命令当前工作目录**解析，脚本不会切换当前目录。

修改配置后需重启服务。程序重启会丢失本局内存记忆，不应为了中途调参随意重启正式对局。

### Settings 字段

定义和读取位置：[CoreGeek/app/config.py](CoreGeek/app/config.py)。

| 字段 | 类型 | 默认值 | 具体作用与主要使用者 |
|---|---|---|---|
| `layouts` | `dict` | `{}` | 按阵营提供已确认的建造偏移；`Settings.build_cells`和`ActionPlan`使用 |
| `allow_base_surroundings` | `bool` | `true` | 生成合法圈层内的三炮/U墙；false只用确认layouts，各配置均受圈层约束 |
| `loadout` | 长度为3的元组；JSON中为数组 | `rocket, rocket, rocket` | `Strategy.build_weapon`根据现存炮型和本轮已计划建造补齐缺口；旧配置显式填写的组合仍会覆盖默认值 |
| `sell_batch` | 正整数 | `12` | 远离小贩且背包未满时，携带的可出售矿石达到该值才主动运往小贩 |
| `return_margin` | 正整数，单位为回合 | `4` | 后续天数的回防、接任务和普通出行余量；首日三任务与工人出行不计回防余量，采购截止另计两轮让行 |
| `repair_start_day` | 整数1–10 | `3` | 升级完成前从该天安排单维修工；全部达标立即双维修 |
| `repair_stock` | 整数1–100 | `5` | 起始日基础库存，后续按天数与昨日确认消耗增加 |
| `repair_stock_per_day` | 整数0–100 | `3` | 每天增加的目标数量，0关闭按日增长，仍按容量封顶 |
| `repair_threshold_percent` | 整数1–100 | `30` | 墙血量严格低于该百分比时夜间维修 |
| `enable_tasks` | `bool` | `true` | 控制是否主动接新任务；已处于`phaseTask`的任务继续处理 |
| `enable_news` | `bool` | `true` | 控制是否生成普通新闻分析prompt；不控制任务内的LLM调用 |
| `enable_boss_raid` | `bool` | `true` | 首日按三次任务成功数和经济部署0～3只BOSS，已知阵型召唤及首夜操控；不取消捣乱鬼的初次侦察 |
| `enable_robot_diagnostics` | `bool` | `true` | INFO输出两类机器人JSON日志；不改变策略，关闭时不更新诊断位置历史 |
| `enable_first_night_defense` | `bool` | `true` | 首日L2/修包供应与夜间维护；白天不提前回防，先保留BOSS费用，不控制独立缺口接力 |
| `first_night_repair_stock` | 整数1–100 | `5` | 首日指定留守工人最低维修包目标，按容量封顶；第2天后沿用原策略 |
| `boss_controller_max_walk` | `int` | `4` | 炮手射击位及累计追位预算，0–30；0仅处理直接可攻击炮手，长路转攻基地 |
| `summon_build_margin` | `int`，0–10 | `2` | 新图6×6建造区以footprint距离≤2固定排除；0/1不能缩小，大于2额外保守扩区 |
| `max_body_bytes` | 正整数，单位为字节 | `2097152` | HTTP请求体上限，即2MiB；过大返回413 |

注意：`Settings.load(path)`会校验文件结构和参数；直接在Python里调用`Settings(...)`是dataclass构造，不会自动执行同一套文件校验。正式配置建议经过`load`。

一个与当前默认行为一致的配置如下，可直接作为模板：

```json
{
  "layouts": {},
  "allow_base_surroundings": true,
  "loadout": ["rocket", "rocket", "rocket"],
  "sell_batch": 12,
  "return_margin": 4,
  "repair_start_day": 3,
  "repair_stock": 5,
  "repair_stock_per_day": 3,
  "repair_threshold_percent": 30,
  "enable_tasks": true,
  "enable_news": true,
  "enable_boss_raid": true,
  "enable_robot_diagnostics": true,
  "enable_first_night_defense": true,
  "first_night_repair_stock": 5,
  "boss_controller_max_walk": 4,
  "summon_build_margin": 2,
  "max_body_bytes": 2097152
}
```

### layouts 子字段与坐标

无需填写`layouts`即可使用默认开局。`Settings.build_cells(turn, kind)`优先读取该阵营`verified:true`的自定义布局；否则在`allow_base_surroundings=true`时调用`base_surrounding_offsets(kind, mirrored)`。旧模板中的空、未核验布局同样使用默认区域。

`base_surrounding_offsets(kind, mirrored=False) -> tuple[Pos, ...]`返回相对2×2基地左上角的固定模板：三炮`(-1,1),(-1,0),(-1,-1)`，P为`(-2,0)`；墙上沿`(-1..3,2)`、下沿`(-2..3,-3)`、迎敌侧`(3,-2..1)`、后侧`(-2,-2..-1)`，共17格。右侧基地按`dx -> 1-dx`水平镜像，y不变。平移后过滤越界、基地及非空地中立点；实际建造再检查单位占用、材料、昼夜和预算。完整17墙、镜像和防锁工人流程见[当前布局说明](CoreGeek/docs/SEALED_HOME_V1215.md)。

| 字段 | 要求 | 用途 |
|---|---|---|
| 阵营key | `challenger`或`defender` | 两个阵营分别登记，不自动镜像 |
| `verified` | 布尔值 | 为true时优先使用此自定义布局；false时允许使用基地周围默认布局 |
| `source` | 字符串，确认后不能为空白 | 记录官方图示、坐标说明及版本来源 |
| `weapons` | `{x:整数,y:整数}`数组 | 允许造武器的相对基地左上角偏移 |
| `walls` | 同上 | 允许造围墙的相对偏移；配置应留出通道 |

实际坐标公式为`Pos(base.x + offset.x, base.y + offset.y)`。例如基地左上角是`(10,24)`，偏移`(-1,0)`计算得到`(9,24)`；这只是数学示例，**不说明该位置已被确认属于官方武器区**。

文件校验拒绝重复坐标、两区重叠、未知字段、非法炮型和超出地图尺度的偏移。`build_cells`在使用时过滤越界、基地格和非空地中立区域；单位占用和本轮预留仍由动作层继续检查。`verified`记录维护者的确认，不是软件自动证明区域来源。

### 代码内的关键参数

以下不是`config.local.json`字段。修改前先区分官方规则和工程选择，不能通过加JSON字段让它们生效。

| 参数/约定 | 当前值 | 位置 | 分类与影响 |
|---|---|---|---|
| `DAY_ROUNDS` / `NIGHT_ROUNDS` | 70 / 60 | `protocol.py` | 官方规则，不作为策略调参 |
| `ROUNDS_PER_DAY` | 130 | `protocol.py` | 日计数与额度重置 |
| 武器造价 / 总数量上限 | 25金币 / 3座 | `protocol.py`常量、`actions.py`校验、`brain.py`预算 | 官方规则；造价在部分实现处仍以字面值使用，修改单个常量不会同步所有位置 |
| `TOWER_RANGE_BY_LEVEL` | 加特林3/5/7；电磁6/8/10；火箭10/15/全图 | `protocol.py` | 以规则表为上限；全图用`10**9`表示 |
| 普通LLM / 召唤令日上限 | 3次 / 10次 | `llm_service.py`、`actions.py` | 官方额度；程序按尝试保守计数 |
| 决策软截止时间 | 开始后3.5秒 | `turn_service.py`、`brain.py`、`combat.py` | 工程保护，检查角色循环与选敌候选；不是可中断所有代码的硬超时 |
| 锁等待时间 | 0.1秒 | `TurnService.decide` | 繁忙时返回空动作并记录日志 |
| 连接读写超时 | 4.0秒 | `Handler.setup` | socket操作超时，不等于官方完整请求时限 |
| 会话缓存上限 | 16个 | `TurnService.decide` | 成功处理后按使用顺序淘汰旧会话 |
| 待解析LLM回复 | 256KiB | `parse_object` | 过长视为无有效结构化回复 |
| 沙盒命令 / 提交答案大小 | 32KiB / 128KiB | `task_service.controller_reply` | 本地接受上限，按UTF-8编码字节计 |
| 方法提示 | 最近8条，每条4000字符 | `TaskService.active` | 控制跨任务提示体积；仍属待验证经验 |
| 任务历史窗口 | `observe`时保留最近12条 | `GameMemory.observe` | 本轮提交还可能在窗口之后追加一条 |
| 失败矿点退避 | 3轮 | `GameMemory.observe` | 暂避对应坐标，不断言该矿种永久停产 |
| 缺失任务时长 | 15轮 | `Strategy.task` | 首日仅作任务信息，不作准入预算；其它天仍使用，不是官方固定超时 |
| 不可达路径代价 | `10000` | `Strategy.cost`、`pair_weapons` | 哨兵值，用于拒绝不可达目标 |

<a id="models"></a>

## 数据模型与坐标约定

模型统一定义在 [CoreGeek/src/agent/protocol.py](CoreGeek/src/agent/protocol.py)。官方字段名在输入输出中保持不变；Python模型内部使用下划线命名便于访问。

### 核心类型

| 类型 | 关键字段 | 表达的对象 |
|---|---|---|
| `Pos` | `x: int`、`y: int` | 一个地图格；可排序、可哈希，可用作字典key |
| `Unit` | `unit_id`、`pos`、`kind`、`health`、`level`、`cooldown`、`attack_range`、`capacity`、`backpack`、`is_driving` | 己方或可见敌方角色/建筑 |
| `Robot` | `robot_id`、`pos`、`health`、`kind`、`target_team`、`abnormal_state` | 全图可见机器人，包含目标阵营和眩晕状态 |
| `Turn.summon_robots` / `hostile_robots()` | 本方可控列表 / 排除本方ID的全场机器人 | 本方ID只来自summonRobotList；占用合并、炮台/工人估值分离 |
| `PlayerTask` | `kind`、`pos`、`cooldown`、`valid`、`timeout`、`score`、`gold` | 官方任务点及可接取状态 |
| `CommandResult` | `raw`、`status`、`exit_code`、`output`、`truncated` | 官方沙盒上一轮执行结果 |
| `Turn` | 地图、队伍、机器人、任务、新闻、商店、反馈 | 一轮完整可用观测 |

### Turn 字段对应关系

| 官方输入字段 | Python字段 | 主要用途 |
|---|---|---|
| `roundNo` | `round_no`；派生`day/is_day/daylight_left` | 昼夜策略、任务时间、额度重置 |
| `mapInfo.width/height/zones` | `width/height/zones` | 地图边界、中立点与矿点；zones转换为`Pos → 类型`字典 |
| 矿区元素 `remain` | `Turn.mine_remaining: dict[Pos,int]` | 本轮真实剩余采集次数；缺失不伪造观测，首日分矿详见[开发文档](CoreGeek/docs/FIRST_DAY_MINING_V1217.md) |
| `teamOur.goldNum/type/teamId` | `gold/team_type/team_id` | 预算和会话隔离 |
| `teamOur.roles` | `ours` | 存活角色、建筑、背包和武器 |
| 角色`isDriving` / `mapInfo.zones`中的`*Vehicle` | `Unit.is_driving` / `Turn.vehicle_cells(own=True)` | 已驾驶状态、己车或敌车的位置，不由本地计划推测 |
| `teamOur.playerTasks` | `tasks` | 接取条件、任务位置、奖励与时长 |
| `teamEnemy.roles` | `enemies` | 仅使用判题器提供的可见敌方单位 |
| `robot.roles` | `robots` | 寻路障碍与选敌 |
| `phaseTask` | `phase_task` | 当前活跃任务原文 |
| `llmResp` | `llm_response` | 上轮LLM返回内容 |
| `lastCmdResult` | `command_result` | 沙盒结果及状态解析 |
| `worldNews.officialNews/folkLegends` | `official_news/folk_legends` | 新闻和宝藏线索积累 |
| `vendorShopList/weaponShopList` | `vendor_prices/shop_prices` | 商品名称到当前价格的映射 |
| `lastRoundRoleActionResults` | `action_results` | 以字符串角色ID索引的执行反馈 |
| `lastSummonTreasureResult` | `treasure_result` | 宝藏成功、失败或已空状态 |
| `errors` | `errors` | 官方任务、LLM及指令等错误反馈 |

`teamName`、`totalScore`、单位`attackPower`等输入字段当前没有映射为策略字段。若后续要做比分驱动策略，应在模型中明确增加读取，而不是误以为当前模型已自动保留所有原始字段。

### 常用模型函数

| 函数/属性 | 参数 | 返回值与行为 |
|---|---|---|
| `integer(raw, name)` | 待解析值、字段名 | 返回严格的`int`；`True/False`不当作整数接受；错误抛`ValueError` |
| `Pos.load(raw)` / `Pos.dump()` | `{x,y}`字典 / 无 | 字典与`Pos`互转 |
| `Pos.neighbours()` | 无 | 返回8个邻格；自身不在列表，边界另行检查 |
| `distance(first, second)` | 两个`Pos` | 切比雪夫距离`max(abs(dx),abs(dy))` |
| `station_footprint(pos)` | 基地左上角 | 返回`(x,y),(x+1,y),(x,y-1),(x+1,y-1)`四格 |
| `Unit.load(raw)` | 单个官方单位字典 | 构造`Unit`，对部分样例缺失字段给默认值 |
| `Unit.backpack_full` | 属性，无括号 | `len(backpack) >= capacity` |
| `Unit.range_of_attack()` | 无 | 非武器为0；输入正射程和官方表值取较小值，否则用表值 |
| `Robot.load(raw)` / `PlayerTask.load(raw)` | 对应官方字典 | 转换机器人/任务点模型 |
| `CommandResult.load(raw)` | 官方结果字符串 | 原样保留`raw`，解析退出、超时、判题错误与截断状态 |
| `Turn.load(payload)` | 完整请求字典 | 返回`Turn`；必要结构错误不吞掉，交上层处理 |
| `Turn.alive(kinds)` | 类型字符串组成的元组 | 己方HP大于0且类型匹配的单位，按ID排序 |
| `controllable()` / `workers()` / `weapons()` / `walls()` | 无 | 分别返回存活可控角色、工人、全部炮型、墙 |
| `station()` | 无 | 存活基地`Unit`；没有则`None` |
| `footprint(unit)` | 一个单位 | 基地四格，其他单位一格 |
| `task_cells(task)` | `PlayerTask` | 按本队阵营和任务类型取观测中的完整任务点格；没有对应zone时退回`task.pos` |
| `in_bounds(pos)` | 坐标 | 是否处于地图范围 |
| `land(pos)` | 坐标 | 地图内的空地；不检查角色或建筑占用，车格不是land |
| `walkable(pos)` / `vehicle_cells(own=True)` | 坐标 / 是否己车 | 白天己车格可通行；车辆坐标集合，False查询敌车 |
| `occupied_cells()` | 无 | 己方与可见敌方存活单位占用格；不含矿点和机器人 |
| `blocked(moving)` | 当前移动单位 | 中立区、任务格、双方存活单位、机器人组成的障碍集，再去除自身起点 |

第1天第1轮为白天起点。`daylight_left`在第1轮为70、第70轮为1、第71轮为0，包含当前白天回合。正式模式不通过改变地图尺寸来做泛化实验。

`CommandResult.status`可能为`empty/exited/timeout/judger_error/unknown`。`exited`只表示进程结束，还必须检查`exit_code`是否为0；末尾`[TRUNCATED]`不覆盖退出状态。

<a id="application-api"></a>

## 应用层关键函数

### 启动与网络：main3.py / app/server.py

| 函数/类 | 参数与返回 | 作用 |
|---|---|---|
| `main3.main()` | 读CLI参数；返回`None` | 校验端口、添加`src`模块路径、配置stderr日志，加载配置并启动服务 |
| `serve(port, settings=None)` | 端口、可选`Settings`；阻塞运行 | 绑定`0.0.0.0`；无配置对象时调用`Settings.load()`；Ctrl+C关闭服务 |
| `AgentServer(address, service)` | `(host, port)`、`TurnService` | 绑定HTTP服务器和复用服务实例；测试可传`127.0.0.1`和端口0 |
| `Handler.setup()` | HTTP框架调用 | 建立输入输出流并设置4秒socket超时 |
| `Handler.do_GET()` | HTTP框架调用 | `/health`和`/healthz`返回200，其余GET返回404 |
| `Handler.do_POST()` | HTTP框架调用 | 任意POST路径接收完整请求，调用服务并分类处理异常；不支持分块传输 |
| `Handler.send_json(status, payload)` | HTTP状态码、字典 | UTF-8序列化，禁止NaN，写入字节级Content-Length并关闭连接 |
| `Handler.log_message(format, *args)` | 框架访问日志参数 | 关闭默认HTTP访问日志，由业务日志记录关键事件 |

有效POST返回200。无效JSON/字段/回合序列返回400；超过体积上限返回413；读取超时返回408。意外内部异常会记录`decision_failed`并返回200空动作，保证响应结构可用；200本身不代表策略没有降级。格式错误发生在配置文件加载时则启动失败，不进入比赛请求处理。

### 配置：Settings

```text
Settings.load(path: str | None = None) -> Settings
Settings.build_cells(turn, kind: str) -> tuple[Pos, ...]
```

`load`优先读取显式路径，再读取环境变量；都不存在时返回默认对象。`build_cells`的`turn`提供阵营、基地位置和地图，`kind`传`wall`时查墙区，传官方武器名时查武器区。优先采用已确认的自定义布局，否则按allow_base_surroundings使用基地周围默认区域。没有存活基地，或显式关闭默认区域且未提供确认布局时返回空元组。它只产生候选格，不生成建造指令。

### 回合服务：TurnService / Session

位置：[CoreGeek/app/service/turn_service.py](CoreGeek/app/service/turn_service.py)。

```text
TurnService(settings: Settings | None = None)
TurnService.decide(payload: dict) -> dict
empty_response() -> dict
```

- `settings`省略时使用`Settings()`默认对象，**不会像`Settings.load()`一样主动读取环境配置**。嵌入使用时应显式传`Settings.load(...)`。
- `payload`是完整官方请求。返回值包含`roleCommandMap/prompt/executeCmd`，可直接JSON序列化。
- 直接调用`decide`时，协议错误或策略异常会抛给调用者；HTTP层负责把这些异常变成HTTP响应。
- `empty_response`每次生成新的空响应字典，避免多个请求共享可变对象。

`Session`字段：`memory`保存游戏记忆，`round_no`保存最后成功处理的回合，`fingerprint`保存该请求SHA256，`response`保存可重放的响应副本。

| 输入序列 | 服务行为 |
|---|---|
| 相同队伍/阵营、相同回合、相同指纹 | 返回响应深拷贝，不重复推进内存额度或任务记录 |
| 相同回合，但请求内容不同 | 抛`ValueError`，避免一次回合提交两套状态 |
| 回合倒退，且不是第1轮 | 抛`ValueError` |
| 已处理较大回合后回到第1轮 | 重置该队伍/阵营的会话 |
| teamId或阵营改变 | 使用独立会话 |
| 锁在0.1秒内无法获得 | 返回空响应，保留原状态 |
| 中间决策失败 | 丢弃工作副本，不提交部分记忆 |

缓存仅针对最近一个回合，不支持随意返回很久以前的请求。协议没有matchId，完全相同的两个首轮无法区分新局和重试，正式运行应保持每场新进程。

### 跨回合记忆：GameMemory

位置：[CoreGeek/app/service/memory.py](CoreGeek/app/service/memory.py)。

| 字段组 | 字段 | 作用 |
|---|---|---|
| 日计数 | `day`、`ordinary_llm_calls`、`summon_attempts` | 换日重置普通LLM和召唤尝试预算 |
| 等待回复 | `pending` | 保存目的`task/news`、发出回合及任务原文或所属日 |
| 新闻 | `news`、`analysed_news` | 去重后的历史新闻及已分析内容指纹 |
| 宝藏 | `treasure`、`treasure_done`、`treasure_attempt_round`、`failed_treasures` | 当前计划、结束标记、最近尝试回合、失败方案签名 |
| 矿区 | `mine_closures`、`failed_mines` | 新闻推理的停矿窗口、单个失败矿点的短期退避 |
| 首日分矿 | `stone_mining` | 联合矿点预约、实际个人缺石量和必须共享矿点的回退；真实remain保存在当轮Turn中 |
| 开局防线 | `defense_layout`、`opening_complete` | 复用选定炮位/共同站位；观测确认三炮及配置墙已建好后标记完成，换日保留、新局重置 |
| 任务控制器 | `task_agent` | TaskAgentMemory：任务状态、接受点快照、SOP/Skill、失败冷却、挂起状态 |
| 工人独立任务 | `worker_tasks` | 按实际工人ID保存任务、目标、目的格、停滞、让路等待及最多4个实际位置的往返诊断 |
| 机器人诊断 | `robot_motion` | 前轮实际位置/HP/攻击目标及最近4个连续位置，仅用于日志，不参与策略 |
| 首夜观察协作 | `raid_scouts` | 首次扫描完成、固定观察ID、真实武器圈扫描、已知阵型召唤与当前视野诊断、车辆行程和终止标记 |
| 敌方建筑知识 | `enemy_weapon_sites`、`enemy_structures` | 实际确认的炮位/类型永久记忆与可被死亡/重建/可见空格否定的建筑观测；前者不生成实时攻击目标 |
| BOSS交易与追击 | `boss_raid`、`robot_raids` | 首日0～3张购买/使用账本、各机器人追位消耗、按目标与站位限定的失败射线、编队目标与短等次数 |
| 捣乱鬼 | `imp_home_side`、`imp_tasks` | 基地所在半区与各imp的目标、站位、前轮位置/回合；死亡、跳轮或复活位移后重新规划 |
| 维修消耗与阶段 | `repair_usage_today`、`repair_usage_previous`、`dual_repair_active` | 记录确认成功的用包量和曾进入双维修阶段的状态 |
| 维修与采购工 | `repair_worker_id`、`repair_supplier_id` | 主维修工、完成阶段唯一采购工；采购往返期间保持身份，死亡/消失时接替 |
| 任务 | `task_description`、`task_started`、`task_history`、`skills` | 活跃任务、开始轮估计、元信息、待验证方法 |
| 任务轨迹 | `task_agent.self_evolve_context/self_evolve_command_trace`、`execution_round` | 文本/结构化轨迹与上一轮命令关联；task_context保留当前轨迹镜像，旧命令诊断字段仅作兼容 |
| 任务预算 | `task_accept_round`、`task_accept_timeout`、`task_timeout_rounds` | 接任务时捕获的轮次、时长及当前预算 |
| 双点任务记录 | `last_task_point`、`task_points_attempted` | 上次接取点坐标与 `(日,x,y)` 已尝试集合；仅正式接取反馈后记入，防止当天重复同点并允许转往另一点 |
| 有奖励的任务提交 | `task_points_succeeded` | 连续提交合法反馈、奖励证据和控制器完成判定对应的不同任务点；不单凭任务消失或接取记成功，不证明100%通过 |
| 上轮动作 | `last_commands`、`last_round` | 把下一轮反馈与本轮输出关联起来 |

| 函数 | 参数 | 返回与副作用 |
|---|---|---|
| `observe(turn)` | 最新`Turn` | 返回`None`；处理换日、新闻去重、任务变化和上一轮反馈；不生成角色指令 |
| `record(turn, plan)` | 当前观测和已完成动作计划 | 返回`None`；写入上轮命令、召唤尝试数、宝藏尝试回合 |
| `treasure_signature(clue)` | 已具备坐标、items、时间窗口的宝藏字典 | 返回可哈希元组；物品排序后保留重复数量，用于失败方案去重 |

`task_started`在接任务后紧接下一轮出现题目时使用本服务发出acceptTask的轮次，否则使用首次观测轮次估计。时长从接取点timeoutRounds捕获，缺失按15轮估计，不能替代官方计分/超时结算。旧`skills`字段仅作兼容，不再注入提示词；当前经验分别在`task_agent.self_evolve_sop/self_evolve_skill`，依据提交反馈归档。`task_points_finished`单独记录任务尝试结束，与接取集合及成功集合分开。所有记忆保存在进程内，没有数据库或磁盘自动恢复；首日购券调试需在同一服务实例按序回放任务。

### LLM协作：LLMService

位置：[CoreGeek/app/service/llm_service.py](CoreGeek/app/service/llm_service.py)。

| 函数 | 参数 | 返回值 | 状态变化/使用说明 |
|---|---|---|---|
| `parse_object(text)` | LLM文本字符串 | JSON字典；无效为`{}` | 支持完整代码围栏；只解析数据，不执行内容 |
| `digest(value)` | 可JSON序列化对象 | SHA256十六进制字符串 | 排序字典key后计算，用于请求和新闻去重 |
| `consume(turn, memory)` | 当前观测与记忆 | `(purpose, reply)` | 清空旧pending；仅接收发送后的紧接下一轮，任务还须匹配原文及开始轮；task返回原始文本，news返回字典 |
| `register_task_prompt(turn, memory)` | 当前任务、记忆 | None | 只设置task pending；提示词由用户控制器生成，不增加普通LLM额度 |
| `news_prompt(turn, memory)` | 历史新闻、当前价格、记忆 | prompt或空字符串 | 无新内容或额度用完时不调用；有调用则增加普通计数并记录news pending |
| `apply_news(turn, memory, data)` | 结构化新闻回复 | `None` | 校验停矿信息与宝藏计划，将接受的结果写入记忆 |

`purpose`为`task`或`news`，无可用pending时为空字符串。过期回复不会被补用到更晚的回合。新闻prompt的3次额度按尝试发出计数；网络失败不会假定返还额度。

`apply_news`只校验结构和当前可执行信息，不证明LLM推理正确。宝藏必须提供高置信标记、依据、有效时间窗口、地图内坐标，以及当前商店存在且不属于已知普通消耗品的物品名；相同失败签名不会重新写入。

### 活跃任务：TaskService.active

位置：[CoreGeek/app/service/task_service.py](CoreGeek/app/service/task_service.py)。

```text
TaskService.active(turn, memory, plan, llm, reply: str | dict, defense_due: bool = False) -> tuple[str, str]
```

| 参数 | 需要提供的对象 | 作用 |
|---|---|---|
| `turn` | `Turn` | 判断是否有任务和存活开拓者，读取题目及反馈 |
| `memory` | 工作副本`GameMemory` | 保存TaskAgentMemory中的上下文、成功/失败经验和冷却 |
| `plan` | 当前`ActionPlan` | 加入submitAnswer，或保留开拓者本轮动作 |
| `llm` | `LLMService` | 登记用户控制器生成的prompt所对应的pending |
| `reply` | 已通过轮次匹配的任务回复原始文本，兼容dict调用 | 用户解析器支持JSON/代码块/说明文字/XML，未识别时兼容旧taskAnswer/executeCmd |
| `defense_due` | 是否需要开拓者回防，默认False | True时不提交答案、不发任务prompt/命令、不占用开拓者；由Strategy接管防御 |

返回顺序为`(prompt, executeCmd)`。先结算上次提交再清理旧任务；无需回防且角色存活时由用户控制器接管。命令只返回官方沙盒，答案通过`ActionPlan.add`。回防、死亡或主动退出后释放开拓者，不自行修改官方phaseTask。重复命令和末段是否执行由新版控制器与提示词决定，旧适配器不再硬拦截。

### 用户任务控制器及经验状态

| 位置/函数 | 参数与作用 |
|---|---|
| `task_prompt.build_self_evolve_prompt(task_desc, context, steps_used=0, timeout_rounds=0, sop_hint=None, skill_hint=None, category=None)` | 题目、轨迹、已用轮数、总预算、SOP、Skill与任务类别；返回prompt，保留最近20条历史；经验优先级为Skill→SOP→内置类别 |
| `task_controller.SelfEvolveController.decide(role)` | 桥接角色；推进任务，返回是否接管本轮 |
| `task_controller._parse_llm_response(resp)` | 原始LLM文本；提取v2 JSON或旧XML中的command/answer |
| `SelfEvolveController._archive_sop/_archive_experience` | 按type、任务名、任务类别保存成功/失败经验；失败教训可追加，但不替换已有成功步骤 |
| `SelfEvolveController._sop_hint/_skill_hint` | 为当前题型选择历史方法，加入prompt，不自动执行或复制旧答案 |
| `task_state.TaskAgentMemory.accept(task)` | 保存实际接受点位、taskType、timeoutRounds快照 |
| `task_evidence.inspect_result(raw)` | 完整lastCmdResult；裁剪前判断进程/业务错误、提取JSON层级和字段，返回ResultEvidence |
| `task_service.controller_reply(reply)` | 优先采用用户解析器，兼容旧协议并检查大小/NUL/编码 |

失败结果不会再仅凭exitCode 0进入成功经验；新的SOP保存失败命令、纠错信息和JSON结构（不保存记录值）。同服务任务读取本题后复用已验证接口，按真实响应确认数组和字段。新版提示词按剩余回合估算可执行命令数；仅余约1回合时控制器阻止普通新命令，但上一结果失败可作最后修复尝试。`submitAnswer`动作合法不等于答对，控制器以提交后金币或总分增长固化成功经验；否则保存失败经验。

三个防卡死参数保留用户值：最多推进30步、连续失败命令4次、退出后冷却25轮。提示词已用轮数按实际roundNo差计算。输出裁剪保留头1600/尾800字符；自动提取缺失参数或认证头格式。Skill首问按类型保存，并已接入提示词。

`TaskAgentMemory`还记录`execution_round`以避免错配沙盒结果，`suspended`避免放弃后下一轮立即重启。同局SOP/Skill跨日保留，换队、换阵营或新局隔离。官方动作合法不等于答题通过：只有上一轮提交合法、任务已结束且无错误才保存成功记录；没有据此推算通过率。

完整持久字段、接入差异、源码位置和Postman逐轮调用见[任务接入与维护](CoreGeek/docs/TASK_INTEGRATION.md)。参考文件中的宝藏辅助类保留，当前宝藏仍由既有新闻策略调度。

<a id="strategy-api"></a>

## 策略层关键函数

### 动作计划与校验：ActionPlan

位置：[CoreGeek/src/agent/actions.py](CoreGeek/src/agent/actions.py)。

```text
ActionPlan(turn: Turn, settings, summon_used: int = 0, summon_positions=())
ActionPlan.add(unit_id: int, command: dict) -> bool
```

`turn`提供当前权限、位置和资源；`settings`提供建造区域与召唤排除余量；`summon_used`是本日召唤预算，`summon_positions`是已待生成的位置。`add`使用实际整数ID：英雄动作以英雄ID、武器攻击以武器ID、原生机器人move/attack以本方机器人ID；机器人attack不带controllerId。

成功返回`True`，并更新动作map、角色占用、金币及相关预留。可识别的校验失败返回`False`并把原因写进`rejections`，不会写入该指令。内部`_add`实施约束，策略应使用有错误处理的`add`入口。

| 成员 | 类型/内容 | 作用 |
|---|---|---|
| `commands` | 字符串ID → 命令字典 | 最终`roleCommandMap` |
| `used` | 整数ID集合 | 已行动或被任务/宝藏等待逻辑保留的角色；攻击同时占用武器与操作者 |
| `reserved` | `Pos`集合 | 本轮已预留的移动和建造目的格 |
| `gold` | 剩余预算 | 在观测金币基础上扣已计划购买/造炮费用，不增加同轮预期卖矿收入 |
| `tower_count` | 当前炮数加本轮计划的新炮数 | 三炮总上限；合法覆盖不增加数量 |
| `summon_used` | 当前日已使用的本地尝试预算 | 不超过10次 |
| `build_targets` | 建造格集合 | 记录本轮接受的建造目标 |
| `upgrade_targets` | 建筑ID集合 | 避免同轮重复升级/维修同一建筑 |
| `catch_targets` | 本轮敌方imp ID集合 | 避免两个角色重复抓同一目标；不提前更新目标HP或抓捕金币 |
| `units` | 整数ID → 存活己方单位 | 校验角色和操控者 |
| `robots` / `summon_positions` | 本方存活机器人字典 / 待生成Pos集合 | 机器人独立权限及召唤位置去重 |
| `rejections` | 原因字符串列表 | 日志和测试检查本地策略错误 |

`near(role, cells)`判断角色是否在任一目标格切比雪夫距离1以内；`near_zone(role, kind)`在`turn.zones`中查指定类型中立点后做相同判断。

#### 十四种指令的字段

| action | 本地调用时的主要字段 | 附加检查/当前选择行为 |
|---|---|---|
| `move` | `targetPos: [pos]`；白天已驾驶可`[p1,p2]` | 两段均为相邻格，逐格检查与预约；仅一步时离车，机器人仍一步 |
| `attack` | 武器需`controllerId: str`和`targetPos`；原生机器人只传一个`targetPos` | 武器保留射程/冷却/数量/角度；本方机器人夜间、未眩晕、射程3、可见敌目标且无中间墙 |
| `sell` | `name`、`num`默认1 | 小贩相邻、矿物、库存、当前收购清单 |
| `buy` | `name`、`num`默认1 | 商店相邻、当前价格、共同预算和背包空间 |
| `build` | `name`、`targetPos: [pos]` | 白天工人、当前配置或默认区域、材料、25金币或石头、总炮数 |
| `remove` | `targetPos: [pos]` | 工人、相邻己方墙；当前策略不自动拆墙 |
| `acceptTask` | 无额外字段 | 开拓者、己方任务点有效、冷却为0、无活跃任务 |
| `submitAnswer` | `taskAnswer: str` | 活跃任务、非空字符串答案 |
| `summonTreasure` | `targetPos: [pos]`、`item: list[str]` | 开拓者、范围、任务用品、多重数量检查 |
| `use` | `name`；部分物品需`targetPos` | 库存、升级等级、建筑类型、范围、召唤令预算 |
| `drop` | `name` | 已持有物品；当前策略不主动使用 |
| `collect` | `targetPos: [pos]` | 工人、相邻矿点、背包未满 |
| `destroy` | `targetPos: [pos]` | 仅捣乱鬼、八邻域矿点、每轮单动作；昼夜均可；策略固定敌半区矿连续破坏 |
| `catch` | `targetPos: [pos]` | 可控角色、当前存活敌方imp、八邻域距离恰好1；昼夜均可，本轮目标去重；不增加弹道条件 |

`ACTION_FIELDS`定义各动作允许出现的字段，必填和语义检查由`_add`完成。`UPGRADES`映射券名称到“建筑类型集合、适用原等级”，`SUMMON_ITEMS`列出四种召唤令。法宝/炸弹和召唤令均需要一个目标坐标；Medicine不带坐标。召唤仍不得进入任一基地建造区/NPC或重复待生成位置，动态占用可由官方旁移。

`protocol.py`另提供`move_command(pos)`、`collect_command(pos)`、`destroy_command(pos)`、`build_command(pos, name)`、`attack_command(controller_id, targets)`五个构造器。构造器只拼装格式，不校验合法性；生成后仍必须经过`plan.add`。`attack_command`接受单个`Pos`或`list[Pos]`，统一输出坐标数组和字符串控制者ID。

### 寻路：Routes与邻域函数

位置：[CoreGeek/src/agent/grid.py](CoreGeek/src/agent/grid.py)。

```text
Routes(turn: Turn, role: Unit, reserved=None, danger=None, allowed=None)
Routes.nearest(goals) -> Pos | None
Routes.step(goals) -> Pos | None
adjacent_cells(turn: Turn, targets) -> set[Pos]
next_step(turn: Turn, moving: Unit, goal: Pos) -> Pos | None
```

| 接口 | 参数含义 | 返回与细节 |
|---|---|---|
| `Routes(...)` | 地图观测、移动角色、本轮额外禁入格 | 无风险时八方向BFS；有danger时按累计风险/步数Dijkstra；allowed限制巡护区域；生成cost/exposure/first |
| `cost`成员 | `Pos → int` | 所选路线的实际步数；风险优先的路线可能更长；起点0，不可达不在字典中 |
| `exposure`成员 | `Pos → int` | 所选路线累计风险，起点0，无风险时全为0 |
| `first`成员 | `Pos → Pos` | 去对应目标路径上的第一步，不是整条路线 |
| `nearest(goals)` | 候选站位的可迭代集合 | 先比累计风险，再比步数，最后按坐标排序；无目标为`None` |
| `step(goals)` | 同上 | 返回到最近候选格的第一步；已在目标格或全部不可达均为`None` |
| `adjacent_cells(turn, targets)` | 要交互的建筑/矿点/任务点格集合 | 得到目标周围的空地区域，排除目标本身；单位占用由Routes过滤 |
| `next_step(turn, moving, goal)` | 单个精确目的格 | 兼容旧接口，每次创建Routes；不含额外预留参数 |

从当前位置访问矿点等障碍时，不要直接让角色走到矿点坐标，应使用`adjacent_cells`求交互站位。两个障碍形成的角落不会额外禁止斜向移动。当前策略保守避开所有角色当前占用格，不尝试推演“前一个角色走开后再跟入”的同时移动。

工人避险、维修工和批量购券的完整参数见[工人策略开发文档](CoreGeek/docs/WORKER_SAFETY.md)。`robot_danger`结合存活墙掩护提供风险图；WorkerCoordinator为每个工人保留任务并协调侧移让路；`WallGuard`负责单人夜修及升级完成后的双人夜间维修、白天经济补货。日志包含`repair_worker`、`worker_danger_cells`、`full_time_repair`、`repair_supplier`、`worker_jobs`和`worker_motion`。后者区分实际位置、目标、下一步动作与平台反馈，不能把goal当作实际位置。

### 建造布局：DefenseLayout与select_defense_layout

位置：[CoreGeek/src/agent/construction.py](CoreGeek/src/agent/construction.py)。

`select_defense_layout(turn, settings, previous=None) -> DefenseLayout`读取当前观测、当前建造区域和上轮布局，返回本轮规划。`previous`可为空；仍然有效的完整布局会复用，减少炮位反复变动。出现静态障碍或可用位置数量改变时重新选择。

| 字段 | 类型 | 含义 |
|---|---|---|
| `tower_sites` | `tuple[Pos, ...]` | 最多三座已有/待建武器的位置；新增位置来自Settings提供的当前建造格 |
| `operator_pos` | `Pos`或None | 优先与三炮均相邻的操控格；排除建筑和预定墙格 |
| `shared_control` | `bool` | 规划操控格是否覆盖所有选定炮位；不是每轮实际可达的保证 |

默认模板可用且已有炮与模板兼容时，直接固定后排三炮及图中P，不随工人距离重排。`Settings.mirrored_layout(turn)`按基地中心决定左右，`Settings.default_operator_position(turn)`提供默认P；自定义已确认布局不自动镜像。兼容规划的选择顺序仍是尽量补足三炮、提高共同站位覆盖数、缩短工人建造距离，再考虑开拓者距离。若区域没有三炮共同邻格，保留合法炮位，夜间由开拓者在可达炮位间移动。不会为凑共同站位越界建造或自动拆掉旧炮。详细阶段和边界见[开局防御策略](CoreGeek/docs/OPENING_DEFENSE.md)。

### 策略编排：Strategy

位置：[CoreGeek/src/agent/brain.py](CoreGeek/src/agent/brain.py)。

```text
Strategy(turn: Turn, plan: ActionPlan, memory)
Strategy.run() -> None
```

构造函数选择布局并更新工作记忆中的`defense_layout`，不直接产生响应。`run()`就地更新`plan`，由服务层读取`plan.commands`；它不会直接发送HTTP，也不创建新会话。`deadline`是`time.monotonic()`时间基准上的绝对截止点，默认无限；应用层每轮将其设为开始时间加3.5秒。

执行时先安排开拓者，再安排捣乱鬼和工人。捣乱鬼首日先经 `opening_imp` 调查敌炮，实际完成初次侦察后才恢复缺口后备等分支。工人的邻格catch先于普通动作；首日开拓者三次尝试结束且无活跃任务后才可catch，不占用前期任务动作。其它已被占用角色跳过。首日三任务完成后的先锋与购用券结束后的采购工先追捕近家当前imp，目标失视、跑远或不可达时恢复原回防，采购工实际回家一次后恢复补给。低血量且没有邻格抓捕时可用Medicine。开拓者需要回防时选择可发射炮或移动就位；其余时间可接任务，开局完成后再允许宝藏采购。白天工人通常按“三炮 → 攒石 → 建墙 → 常规经济”推进；首日两工联合分矿并按个人施工段筹石，各自完工后立即转采购或侦察，不等同伴墙齐或改去收入采矿；采购工到实际购物出发截止时优先离开未完成的施工，所有工人首日白天不预留返程，采购工完成购用券后参与回防；普通工人昼夜按相同经济流程升级、交易及采矿，夜间需安全路线且不能建造；第三天起其中一人由WallGuard负责可达邻墙区域维修及升级；所有建筑达到目标后两人都转为邻墙值守，白天轮流补货，不分配操炮任务。

| 方法 | 参数 | 返回值和实际作用 |
|---|---|---|
| `route(role)` | 当前角色`Unit` | 返回Routes；禁入本轮动作/具体施工预约及规划炮位，未建墙可通行，工人额外避让操控格；按角色与禁入格快照缓存；临时忽略工人的路线仅供诊断堵路，实际动作仍禁止进入占用格 |
| `movement_reserved(role=None)` | 可选Unit，省略按工人 | set[Pos]；炮位、P位、实际动作与施工预约；未建墙可穿行 |
| `run_worker(role)` | 当前工人Unit | 昼夜统一的单工人入口，按自己的任务/岗位执行与让路 |
| `ImpDefense.catch_available/catch_near/defend` | 无参数 / 当前Unit | 优先邻格抓捕、三任务后先锋及购用券结束后的采购工近家追捕；参数和返程状态见[开发文档](CoreGeek/docs/IMP_HOME_DEFENSE_V1222.md) |
| `travel(role, cells, job="travel")` | 角色、交互对象的占用格集合 | `bool`；尝试朝相邻站位移动一步，已到达或不可达时为False |
| `cost(role, cells)` | 同上 | 到最近合法交互站位的步数，不可达为10000 |
| `interact(role, target, command, footprint=None)` | 角色、目标坐标、候选命令、可选完整占地 | 已相邻则提交命令，否则移动；基地交互可传四格footprint |
| `opening_stage()` | 无 | 返回`towers/stockpile/walls/complete/unconfigured`；只根据观测确认建筑完成 |
| `missing_walls()` | 无 | 当前自定义/默认墙位中尚未存在存活己方墙的位置列表 |
| `stone_targets()` | 无 | 工人ID→实际背包目标石头数；统计真实缺墙、排除已采购出发工人的石头，首日先按个人施工剩余墙数分份，再兼顾库存、容量与有效采石配额 |
| `opening_worker(role)` | 工人 | `bool`；已有石头且当前计划下一墙相邻、合法时就地建墙，否则按个人施工段筹石施工；首日石矿联合分配，个人完工由采购/侦察分支接手；没有这些使命的工人保留收入采矿回退 |
| `night_worker(role)` | 工人 | 返回None；兼容入口，仅调用run_worker，不再提供独立夜间采矿流程 |
| `clear_build_cell(role)` | 当前角色 | `bool`；角色占用规划建筑格，或工人占用操控格时，尝试移开一格 |
| `control_position(role)` | 开拓者 | 返回可达且覆盖最多现有炮的Pos，优先既有共同站位；无可达站位为None |
| `pioneer_should_defend(role)` | 开拓者 | 首日三次任务未结束/仍活跃时False；三次结束直接回防，由另工采购；其它天沿用原预算 |
| `move_to_control(role)` | 开拓者 | `bool`；朝选定操控格移动一步，已就位或不可达时False |
| `operate_weapons(role)` | 开拓者 | `bool`；夜间从相邻、冷却0、有目标的炮中选一座发射；否则移动或等待 |
| `consume(role, allow_travel=True, allowed=None)` | 角色、是否允许为使用建筑物品而行走、可选巡护范围 | 依次考虑药剂、夜间法宝/炸弹、召唤令，再按统一阶段用券；按中央/外围/两翼阶段，组内前列与残血优先，升级优先于已有修复包 |
| `worker(role)` | 工人 | 返回None；昼夜统一经济流程（建造仅白天）：补缺墙/筹石 → 商店旁补齐当前券 → 用券 → 补炮 → 卖矿（保护墙材）→ 买券 → 采矿 |
| `build_wall(role, local_only=False)` | 工人、是否仅就地施工 | `bool`；白天从完整蓝图外侧按个人段逐墙施工，实际到选定法线/角点站位才建；local_only与行程使用同一首缺墙、站位和安全条件。路径加建造一轮超过日照时不启动；夜间False |
| `WallSchedule.targets(role, candidates, local_only=False)` | 工人、合法候选墙、是否仅就地施工 | `list[Pos]`；首日按个人弧顺序完成真实缺墙，当前占位/不可达可暂跳；旧途中目标与距离插入不越过首缺墙，不借仍在筹石同伴的墙段，见[直墙施工](CoreGeek/docs/STRAIGHT_WALL_BUILD_V1220.md) |
| `WallSchedule.posts(role, target)` / `straight_steps(role, goal)` | 工人、目标墙或已选站位 | 外侧法线/角点站位与空闲轴向步；步行最多一格、真实白天驾驶最多两格，遇障保留普通八向路线 |
| `WallSchedule.remaining(role)` | 当前工人 | `int`；个人段的真实未完成墙数，已离开或死亡同伴的墙可接手；待执行建造仍需观测确认 |
| `wall_keeps_exit(role, target)` | 工人、待建墙坐标 | `bool`；委托SealedHome检查真实工人外出通路、本轮全部建造预约与开拓者操炮格可达性，不能依据同轮预测移动封住工人 |
| `build_weapon(role)` | 工人 | `bool`；白天在规划炮位与当前建造区域的交集按loadout缺口建造或靠近；夜间False |
| `sell(role, keep_stone=False)` | 角色、是否保留石头 | `bool`；按持有量×收购价选矿种；keep_stone=True时不出售石头，适用于开局墙材保护 |
| `upgrade_candidates()` / `upgrades_complete()` | 无 | 委托upgrade_policy返回当前阶段/完成状态，详见[维护文档](CoreGeek/docs/MAINTENANCE.md) |
| `buy_upgrade(role)` | 角色 | `bool`；按purchase_needs批量购券，可预购当前火箭的2→3券；扣全队库存/本轮买用，受金币/容量和维修预算限制 |
| `mine(role, need_stone=False, return_cells=None)` | 工人、是否仅考虑石矿、可选返岗格集合 | `bool`；need_stone委托StonePlanner，以真实缺口和remain联合分配首日矿点，保持有效预约；普通采矿保留收益/避险排序，返岗格使用实际维修区域；首日白天不留返程预算 |
| `task(role)` | 开拓者 | 首日2→1→2，无购物/回防/完整时限准入预算，合法领取或前往等待；其它天保留原准入逻辑 |
| `BossRaid.departure_budget(role)` | 当前采购工人Unit | 返回travel/opening/drop/buy/use/slack/total/latest_departure/post/route_mode字典或None；实际赴店和购用成本，不含返程 |
| `BossRaid.departure_due(role)` | 当前采购工人Unit | bool；剩余日照不够预算时离开施工，无可估计路线则立即进入购物路线诊断 |
| `BossRaid.worker(role)` | 当前工人Unit | 固定购手在墙齐或购物截止后赴店；三次真实任务结算前只等待，结束按实际成功数购用 |
| `treasure(role)` | 开拓者 | `bool`；按计划采购、移动、等待或献祭；等待时可仅加入used而不输出动作 |

策略中`True`通常表示已安排当前角色，但不总等同于已经提交交互动作：例如`interact`可能只是移动一步，`treasure`可能是原地等候。后续新策略不要在返回True后继续给同一角色发第二条指令。

几个便于调参和排查的计算细节：

- 筹石时已经相邻的有效石矿优先，避免为旧远矿放弃一次可用采集；否则保持原有效矿点，按实际距离选新矿。两工可共享矿点但使用不同站位，达到稳定石头配额后停止筹石。普通收入采矿仍按有效目标及`value / (cost + 2)`排序，value读取收购清单。
- 不在小贩旁时，出售通常要求满背包或可售矿石达到`sell_batch`；已在小贩旁可直接出售少量库存。
- 有可用武器区时，买券前预留`(3 - tower_count) × 25`金币；同轮卖矿不会增加该预算。
- 开局75金币优先保留给三座火箭。两个工人每人每轮只能造一座，初始至多同时造两座；第三座随后补齐，距离会增加移动轮数。
- `stockpile`阶段按缺失墙数筹石，每墙一石；各工人完成自己的配额后可以独立施工。同种待购物品由一名采购工人保持行程。只要模板仍缺墙就保护墙材，不按普通卖矿阈值售出。
- 首日白天两名工人不提前回防，DayGate/缺口准备/首夜维护/WallGuard均不以返程预算抢占工作；采购工的实际赴店购用截止优先于继续建墙。不再保留R70封门分支；所有计划墙按普通施工处理，封闭前确认真实工人可退出。其它天回防目标采用实际可达维修区域。
- 首日三任务优先：任务timeout只控制解题超时，不因剩余日照、购物或回防预算拒绝领取；入夜尚未三次时继续任务。其它天仍沿用路径、完整时限和回防准入预算。
- 每轮只由开拓者操控一座炮；直接读取`cooldown==0`。按发射后3轮空窗，理想共同站位下为A→B→C→空→A；无目标或移动会额外消耗轮次。
- Medicine在角色血量不超过初始上限一半时优先考虑。`consume`支持Bomb/DizzyWeapon，工人夜间同样进入consume分支；开拓者第一日三次任务结束后恢复夜间控炮。第一天由采购工人按Task2→Task1→Task2三次真实结束后的成功次数购买0～3张BOSS券，先锋直接回防，逐张用券等待真实确认阵型，炮位已知后不以缺少当前角色视野阻止召唤；其它召唤令、炸弹和眩晕法宝不自动采购。

旧`agent.brain.decide(payload) -> dict`仅返回动作map，每次使用新默认配置和新记忆，没有完整LLM协作。它保留兼容，不应替代比赛主入口中的`TurnService.decide`。

升级、维修和补建的函数参数、前后排序、库存统计以及基准快照见[建筑维护开发文档](CoreGeek/docs/MAINTENANCE.md)。新入口为`upgrade_candidates()`、`upgrade_name(building)`、`wall_depth(building)`、`building_max_health(building)`、`rebuild_wall(role)`；它们集中在`brain.py`，没有新增网络协议字段。

### 战斗计算：combat.py

位置：[CoreGeek/src/agent/combat.py](CoreGeek/src/agent/combat.py)。

| 函数 | 参数 | 返回与副作用 |
|---|---|---|
| `pair_weapons(turn, roles)` | 当前观测、可用角色元组 | 返回`((角色, 武器), ...)`；优先减少不可达匹配，再最小化总路径成本，ID用于稳定打破平局 |
| `segment_entry(start, end, cell)` | 起点、终点、待检查格中心 | 线段第一次进入闭区间方格的归一化参数；不相交为None |
| `damage_for(turn, tower, target, health)` | 炮台、落点、预测剩余HP字典 | 返回`机器人ID → 本发预计伤害`，不修改真实HP；适用于单发伤害估值 |
| `choose_targets(turn, tower, expected_health, deadline=inf)` | 当前观测、炮台、全队本轮预测HP、绝对软截止时间 | 所有火箭占用中心按九宫格Σ(分/当前HP)最大；三级2+1或全防守；完整方案后才更新expected_health |
| `protected_layout(turn, settings, remembered=(), confirmed_sites=())` | 当前Turn、Settings、真实建筑记忆与炮位缓存 | 判定炮手或最佳操炮位是否需破墙才能攻击；不创建移动单位，详见[集中破墙](CoreGeek/docs/COORDINATED_WALL_ASSAULT_V1221.md) |
| `plan_assault(turn, settings, count, remembered=(), confirmed_sites=(), pending=(), failed=(), preferred_wall=None)` | 当前布局、追加召唤数量、炮位知识、已预约/失败位置与可选旧墙目标 | 统一墙目标、进攻侧与合法召唤点；签名及字段见[集中破墙](CoreGeek/docs/COORDINATED_WALL_ASSAULT_V1221.md) |
| `RobotRaider.group_base_ready()` | 无→bool | 最佳位已被本方BOSS占住且每只存活BOSS当前均有合法基地射线时启用全队基地攻击优先 |
| `RobotRaider.wall_assault(robot, route)` | 当前BOSS、真实Routes→bool | 按共享计划拆同一堵墙，实际破口后攻击基地；不预测当轮墙已死亡 |
| `RobotRaider.rocket_control_posts()` | 无→tuple[Pos,...]或None | 三火箭共同位；None为旧策略，空元组仍保持三火箭人员限制，见[开发文档](CoreGeek/docs/ROCKET_CONTROL_V1219.md) |
| `BossFormation.occupy_rocket_post(robot,base,route,posts)` | 当前BOSS、敌基地、真实路线与共同位→bool | 单只/多只安全进位；本轮只移动，后续按真实位置攻击 |
| `RaidScouts.opening_imp(role)` | 捣乱鬼Unit→bool | 首日初次扫描最高优先，三炮位置或十二格实际扫描确认后才考虑缺口返防 |
| `RaidScouts.spawn_ready()` / `summon_ready()` | 无→bool | 已知阵型召唤条件 / 实时普通共享视野诊断，两者独立；见[开发文档](CoreGeek/docs/OPENING_SCOUT_V1218.md) |
| `RaidScouts.travel_budget(role,goal,route)` | 角色、目标Pos、Routes→(轮数,车位或None) | 真实车位更快则取车；有效旧取车代价持平保持，车后预测只忽略自身旧占位，夜间车消失 |
| `layout_weapon_sites(turn,remembered=(),confirmed_sites=())` | 真实观测、建筑记忆、炮位缓存→tuple[Pos,...] | 仅给出确认炮位几何，不创建活敌单位 |
| `WallGapDefense.worker(role)` / `imp(role)` | 当前真实Unit→bool | 合法原墙施工、工人守缺口、imp初次侦察后真实死亡接替和次日让位补墙 |
| `construction_walls()` | 当前原墙缺口→list[Pos] | 仅合法原墙，没有临时绕建需求 |

`pair_weapons`保留为兼容/扩展函数，当前`Strategy`不调用它。该函数可以为最多三名角色和三炮求路径匹配；本版使用`operate_weapons`只让开拓者操炮，工人不参与匹配。

火箭候选仅包含观测存活机器人格，在合法射程内按九宫格Σ(击杀分/当前HP)最大选点；所有等级使用同一公式，三级额外限定半区配额。同次攻击使用固定的观测HP分值，可重复落点；预测伤害按中心20、周围10依次叠加。加特林优先沿路径最近目标，并要求所选任意两个方向点积不小于0。电磁炮仍以`10 × level`估值，非火箭的复赛伤害变更待后续单独接入。

非火箭单炮选敌按预计有效伤害及威胁权重评分；明确攻击己方阵营的机器人增加权重，距基地越近也越优先。火箭使用上述积分/当前HP公式。`operate_weapons`分别复制机器人HP评估候选炮，再选择预计总有效伤害最大的一座，同分按武器ID。预测HP用于伤害估值，不改变同轮火箭分值、真实障碍或机器人状态。

闭区间格边界、并列命中顺序和回合末统一结算仍有待官方回放确认，因此这里提供的是策略估值，不能当作官方伤害模拟器。

<a id="task-workflow"></a>

## 任务、新闻与宝藏流程

任务模块的目录、关键参数、证据上限、时限计算及Postman逐轮示例见[任务接入与维护](CoreGeek/docs/TASK_INTEGRATION.md)。`temp/`是后续用户资料入口，正式运行不依赖该目录。

### 自进化任务

```mermaid
sequenceDiagram
    participant A as Agent服务
    participant J as 官方判题器
    participant L as 官方LLM
    participant S as 官方沙盒
    A->>J: roleCommandMap: acceptTask
    J->>A: 下一轮phaseTask
    A->>J: prompt（任务原文与上下文）
    J->>L: 执行LLM调用
    J->>A: 下一轮llmResp
    A->>J: executeCmd
    J->>S: 执行命令（最多15秒）
    J->>A: 下一轮lastCmdResult
    A->>J: prompt（结果与错误反馈）
    J->>A: 下一轮llmResp（答案）
    A->>J: roleCommandMap: submitAnswer
    J->>A: errors / phaseTask / 最新队伍状态
```

内部约定的LLM回复示例：

```json
{"action": "execute_command", "command": "python3 inspect_task.py"}
```

或者：

```json
{"action": "final_answer", "answer": "{\"answer\":42}"}
```

这是用户模块的v2回复约定，兼容旧executeCmd/taskAnswer格式，未向官方请求增加字段。command映射顶层executeCmd，answer映射角色submitAnswer.taskAnswer。`taskAnswer`仍是字符串，即使任务答案本身是JSON，也要放成字符串。Agent收到命令时先返回命令，等待下一轮结果后再组织新的prompt，不会凭空预测沙盒输出。

任务完成/超时/死亡的真实奖励与最高通过率由判题器维护；程序按用户控制器保存成功或失败经验，判错会退出并冷却，后续任务可复用经验。需要回防时停止任务输出，允许开拓者离开；离开范围可能结束任务，下一轮以`phaseTask`为准。没有防守责任时继续保持任务站位。题目结束后迟到的LLM命令不会再进入executeCmd。

### 新闻和宝藏

新闻按“游戏日+内容”去重保存。任务外且有可分析更新时，LLM收到历史新闻、当前矿价和商品清单，可返回：

```json
{
  "treasure": null,
  "mineClosures": [
    {"name": "iron", "startDay": 2, "endDay": 3, "evidence": "新闻给出的停工依据"}
  ]
}
```

有完整线索时，treasure应包含`targetPos`、`items`、`startRound`、`endRound`、`confidence: "high"`、`evidence`。具体字段格式见[协议协作文档](CoreGeek/docs/PROTOCOL.md#4-普通新闻与宝藏)。用品按当前清单精确匹配，不能自行修正`AcientTablet`等官方拼写。

通过本地校验后，`Strategy.treasure`只在接近时间窗口时开始行动：检查完整采购预算与容量，逐种购买缺少的物品，移到目标邻域，等待或提交精确item数组。背包里额外的其他物品不会自动加入献祭。本版在开局完成或区域未配置时才考虑宝藏；有炮且需要回防时，防御优先于宝藏，包括夜间窗口。

若官方返回成功或已空（1/4），停止继续尝试；合法失败（2/3）会清理计划并记住失败签名。非法尝试返回0不会被当作已消耗物品，库存仍以观测为准。LLM的高置信不等于答案正确，完整线索的推理质量仍需真实平台验证。

<a id="examples"></a>

## 代码调用与扩展示例

### 离线调用完整服务

以下脚本按仓库根目录为工作目录运行，不开启网络端口：

```python
from pathlib import Path
import json
import sys

project = Path.cwd()
sys.path[:0] = [str(project / "CoreGeek"), str(project / "CoreGeek" / "src")]

from app.config import Settings
from app.service.turn_service import TurnService

settings = Settings.load(str(project / "CoreGeek" / "config.example.json"))
service = TurnService(settings)  # 整个观测序列只创建一次
payload = json.loads((project / "request.txt").read_text(encoding="utf-8"))
response = service.decide(payload)
print(json.dumps(response, ensure_ascii=False, indent=2))
```

处理多轮时复用`service`，按回合顺序传入官方观测。重新创建服务会丢失额度、线索与任务方法，离线计算也不会替你执行响应中的命令。

### 在Strategy内添加一个规则受控动作

例如为工人增加“收到策略要求时拆除邻近己方墙”的方法。以下只是扩展示例，当前代码不会自动调用它；接入`worker`时还需要明确调用条件与优先级。

```python
def remove_adjacent_wall(self, role, wall) -> bool:
    command = {"action": "remove", "targetPos": [wall.pos.dump()]}
    return self.plan.add(role.unit_id, command)
```

这里的`self`是`Strategy`，`role`和`wall`来自当前`Turn`；ActionPlan会继续检查工人身份、距离、墙归属和角色是否已被占用。不要跳过校验层直接向`commands`塞字典，也不要在策略里直接修改权威观测。

### 查找某个交互对象的第一步

```python
from agent.grid import Routes, adjacent_cells
from agent.protocol import move_command

routes = Routes(turn, worker, plan.reserved)
stands = adjacent_cells(turn, [mine_pos])
step = routes.step(stands)
if step is not None:
    accepted = plan.add(worker.unit_id, move_command(step))
```

示例假定`turn/worker/plan/mine_pos`已经来自当前回合。若`step is None`，可能已经在合法交互格，也可能所有目标都不可达；需要结合`routes.nearest(stands)`判断，不能直接当成路径错误。

<a id="verification"></a>

## 测试、回放与报告

### 工具参数

| 入口 | 参数 | 输入与输出 |
|---|---|---|
| `CoreGeek/run_tests.py` | 无自定义参数 | 自动发现tests目录，打印unittest结果；失败时非零退出 |
| `CoreGeek/tools/replay.py` | `input`必填；`--output`必填；`--config`可选 | 读取单JSON、JSON数组或JSONL；一条响应输出对象，多条输出数组 |
| `CoreGeek/tools/smoke_server.py` | `--output`默认reports/http-smoke.json | 使用临时本地端口启动main3.py，检查/health并POST原样例；写入指定报告，结束自建进程 |
| `CoreGeek/tools/validate.py` | `--cases`默认80；`--output`默认reports/validation.json | 先跑测试，再做两种子×两阵营的合成观测检查，最后记录源码和基线哈希 |

`validate.py --cases N`的总观测数为`4 × N`，不是N局比赛。`--cases 20`生成80份，省略参数则默认320份。建议传正整数。两个种子固定为17和20260917。

```powershell
python CoreGeek/run_tests.py
python CoreGeek/tools/replay.py request.txt --output reports/sample-response-v1.2.4.json
python CoreGeek/tools/replay.py observations.jsonl --output reports/replayed-responses.json --config CoreGeek/config.local.json
python CoreGeek/tools/smoke_server.py --output reports/http-smoke-v1.2.4.json
python CoreGeek/tools/validate.py --cases 20 --output reports/validation-v1.2.4.json
```

上述JSONL命令需要先准备`observations.jsonl`。工具会覆盖指定的同名输出；新版本应另取报告文件名，保留历史证据。`validate.py`不会自动重写人工说明，修改代码后需另存对应版本的说明。本版压力观测同时覆盖三火箭和混合旧炮，增加“仅开拓者攻击”和输入冷却为0的断言。

### 测试文件负责什么

| 文件 | 重点内容 | 哪类变更应重点检查 |
|---|---|---|
| `test_protocol.py` | 坐标、地图边界、昼夜、角色ID、障碍、命令结果 | 观测解析、数据模型、坐标计算 |
| `test_actions.py` | 十二动作、共享金币、三炮上限、操控者、角度、容量、物品 | 新动作逻辑或官方规则修复 |
| `test_combat_strategy.py` | 可手算伤害、炮台匹配、回防、交易、升级、宝藏时机 | 选敌或经济/角色策略调整 |
| `test_opening_defense.py` | 75金币先造三火箭、多轮攒石建墙、轮换冷却、工人夜采、任务让出防御 | 开局阶段、规划位置、角色分工与石头保留 |
| `test_default_opening.py` | 无配置完成三炮→采石→建墙，覆盖两阵营、地图边界、默认通道和自定义布局优先级 | 默认可运行性和建造区域来源 |
| `test_services.py` | LLM日计数、任务往返、跨日、重复请求、事务与会话隔离 | 任何跨回合状态变更 |
| `test_http_config.py` | HTTP响应/错误、请求上限、配置文件检查 | 启动入口、网络层、配置变化 |
| `test_robot_diagnostics.py` | 实际位移/HP、反馈关联、墙遮挡/站位、截止原因、日志开关一致性 | 机器人诊断与日志修改 |
| `test_imp_opening_scout.py` | 开局敌占墙、购券禁用/零成功仍先探敌，三炮/十二格确认、完成后缺口接力、失视召唤与禁止盲打 | 首日IMP优先级和炮位知识 |
| `test_raid_scouts.py` | 真实施工派出、固定身份、观察覆盖、昼夜保持及第二天恢复 | 首夜BOSS视野协作 |
| `test_stone_mines.py` | remain解析、两10石矿联合分配、旧预约、零余量与不可达、单矿共享回退 | 首日日间筹石与矿点选择 |
| `test_personal_construction.py` | 个人完工独立赴店/侦察、敌占位暂跳、真实建筑确认及唯一存活工人接手 | 施工到采购/侦察的交接 |
| `test_raid_efficiency.py`、`test_raid_audit.py`、`test_dual_boss.py` | 手算绕路/破墙与基地回退、独立审计正反例、两券库存/反馈/预算 | BOSS效率或首日部署数量修改 |
| `fixtures.py` | 统一合成数据构造，布局专供测试 | 不能当官方地图坐标或规则来源 |

历史v1.2.8通过569项回归、320份合成压力及四种布局520次跨帧HTTP检查；证据见[v1.2.8历史验证报告](reports/VALIDATION-v1.2.8.md)。历史v1.2.7记录529个测试通过、80份合成观测检查通过（20份含本方BOSS，其中12份同时两只、共32只受控BOSS），另有四组任务结果、缺口接力及45度攻击的真实HTTP验证，见[v1.2.7历史验证报告](reports/VALIDATION-v1.2.7.md)。[v1.2.4历史报告](reports/VALIDATION-v1.2.4.md)保留原435项检查及双券/追击效率审计。[v1.2.3历史报告](reports/VALIDATION-v1.2.3.md)保留373项证据，[v1.2.2历史报告](reports/VALIDATION-v1.2.2.md)保留356项证据。v1.0封版回归见[基准报告](reports/BASELINE-v1.0.md)。这些本地检查不代表所有复赛规则已适配或官方比赛胜率。

`validate.independent_contract(raw, response)`是压力工具中的附加结构断言，检查角色互斥、移动占用和攻击时机等。它不是完整判题器，不能代替官方平台对动作执行结果和比分的裁定。

<a id="maintenance"></a>

## 修改定位与常见问题

### 想改某种行为，应从哪里开始

| 目标 | 首先修改/查看 | 同时需要关注 |
|---|---|---|
| 调整三炮组合 | `config.local.json: loadout` | `Strategy.build_weapon`、三炮总上限、建造区确认 |
| 调整开局顺序与城墙数量 | `opening_stage/opening_worker/stone_targets`、配置walls | 先三炮再攒石建墙；完成标记只读取观测 |
| 调整直墙施工顺序与站位 | `WallSchedule.targets/posts/straight_steps`、`Strategy.build_wall/opening_worker` | 真实首缺墙、法线/角点站位、外侧预约、build_wait、封闭安全与采购截止 |
| 调整首日分矿与个人交接 | `StonePlanner.assignments/options/targets`、`WallSchedule.construction_ready/release/reclaim` | 当前remain、有效预约、单矿回退、实际施工确认与RaidScouts.refresh_dispatch |
| 调整采矿偏好或运矿批量 | `Strategy.mine/sell/run_worker/worker`、`sell_batch` | 实时价格、停矿信息、容量与墙材预留 |
| 调整回防时间 | `return_margin`、`pioneer_should_defend` | 首日三任务和工人出行排除返程预算；其它天沿用开拓者与维修工回防 |
| 调整升级优先级 | `Strategy.buy_upgrade/consume` | 已有券库存、共享金币、建筑等级与重复目标 |
| 改寻路或拥挤处理 | `grid.Routes`、`Turn.blocked`、`plan.reserved` | 官方八方向及同时结算约束 |
| 改三炮站位与轮换 | `select_defense_layout`、`control_position/operate_weapons` | 共同邻格、冷却0、每轮一炮、工人不操炮 |
| 改选敌和火力分配 | `choose_targets/damage_for` | 射程、目标数量、90°、预测HP与真实HP分离 |
| 改任务解题提示 | `task_prompt.build_self_evolve_prompt`、`SelfEvolveController._dispatch_prompt` | reply结构、命令结果语义、不能在本机执行 |
| 改任务动作流程 | `TaskService.active`、`Strategy.task` | 回防优先、离开任务点的代价、过期回复和免费额度 |
| 改新闻/宝藏推理 | `news_prompt/apply_news`、`Strategy.treasure` | 长期线索、精确物品、时间窗口、失败去重 |
| 新增跨回合字段 | `GameMemory` | observe/record、深拷贝、换日与新局重置 |
| 新增可配置策略阈值 | `Settings`及`Settings.load` | 模板、文档、实际读取处都要同步 |
| 修复HTTP/编码错误 | `app.server.Handler` | Content-Length按字节，错误类型与业务降级分开 |
| 对齐新官方字段 | `protocol.py`及对应服务 | 保留旧基线，单独登记版本差异 |

### 常见现象

| 现象 | 可能原因 | 排查方法 |
|---|---|---|
| 工人一直不造炮 | 显式关闭默认区域且无自定义布局，或已三炮、缺金币、无可达空位 | 默认无需配置；检查allow_base_surroundings、已加载布局、Settings.build_cells与build_weapon |
| 仍然造出混合炮 | 外部旧配置显式覆盖默认loadout | 将实际加载配置改成三个rocket后重启；已有炮不自动覆盖 |
| 三炮没有每轮连续发射 | 发射后3轮空窗、无目标、无法共享站位或需要移动 | 查看输入cooldown和日志shared_control，每轮仅开拓者一炮 |
| 工人攒石后没立即建墙 | 个人施工目标、天黑、真实占用、墙位不可达或会封闭通路 | 查看wall_schedule、stone_targets和wall_keeps_exit；首日不要求同伴采齐或整圈完工才进入个人下一使命 |
| 两人一起追同一个石矿 | 只有一个可达矿点、旧预约失效或观察数据缺失 | 查看stone_mining的assignments、remaining和shared_fallback，结合真实站位和反馈确认；能形成不同矿配对时优先分矿 |
| 部分角色没返回动作 | 冷却、已经就位、任务保留、宝藏等待、无可行目标 | 空动作允许；检查`plan.used`和对应策略分支 |
| 无法到达肉眼看似空的格子 | 隐含基地四格、双格任务点、当前单位占用或本轮预留 | 区分`land`、`occupied_cells`、`blocked`，检查Routes.cost |
| 下一轮不继续任务命令 | 到回防时间、pending轮次/原文不匹配、开拓者死亡、phaseTask为空 | 查看`pioneer_should_defend`与`TaskService.active`，不手工复用过期回复 |
| LLM不再分析新闻 | 无新内容、额度已满、处于任务中、enable_news关闭 | 检查`analysed_news`与`ordinary_llm_calls` |
| 改了config.local.json不生效 | 未通过--config/环境变量加载，或进程未重启 | 先检查实际启动命令和配置绝对路径 |
| `ModuleNotFoundError: agent/app` | 脱离入口直接运行内部模块，搜索路径不全 | 用main3.py/工具入口，或按离线示例添加两个路径 |
| HTTP200但没有动作 | 合法等待，或内部异常/繁忙降级 | 必须结合日志中的`decision_failed/decision_busy`判断 |
| 收到400 | JSON/必要字段错误、非法尺寸、重复ID、同轮冲突或乱序 | 查`protocol_error`，核对原始请求，不修改官方样例掩盖问题 |

### 日志与错误的区分

`main3.py`配置日志写stderr。正常`decision`日志含回合、阵营、动作数、本地拒绝数、耗时、官方反馈失败数量、错误码，以及`opening`阶段和`shared_control`布局标记。`[TASK-DEBUG]`按用户提供的格式打印完整题目、模型回复、沙盒结果、本轮prompt和executeCmd；详见[日志文档](CoreGeek/docs/TASK_LOGGING.md)。`shared_control=True`表示规划具备共同邻格，仍须确认开拓者实际到位。

| 日志事件 | 含义 |
|---|---|
| `construction_mode=base_surroundings` | 已启用用户指定的基地周围默认布局 |
| `D01` | 已显式关闭默认布局且没有确认坐标，无法建造 |
| `decision` | 本轮决策完成 |
| `[TASK-DEBUG R...]` | 本轮任务输入、LLM/沙盒反馈与实际返回的prompt/executeCmd |
| `robot_observation` | 本方机器人归属列表、召唤状态及移出记录，JSON单行 |
| `robot_diagnostic` | 单机器人实际位移/HP、候选与遮挡、前轮反馈及最终指令原因，详见[字段说明](CoreGeek/docs/ROBOT_DIAGNOSTICS.md) |
| `raid_scout` | 初次侦察完成、永久炮位、固定观察者，个人完工独立派出；spawn_ready与summon_ready、观察站位和驾驶/取车行程 |
| `wall_schedule` | 稳定arcs、当前首缺墙frontier、真实remaining与released交接；结合worker_motion中的实际位置、外侧goal、command和下一轮反馈检查连续施工，见[直墙施工](CoreGeek/docs/STRAIGHT_WALL_BUILD_V1220.md) |
| `stone_mining` | 两工矿点分配、缺石数、真实余量与单矿共享回退，详见[首日分矿](CoreGeek/docs/FIRST_DAY_MINING_V1217.md) |
| `first_day_policy.buyer / last_buyer_decision` | 采购工人ID、位置、HP、持券和指令，真实金币/价格/等待原因；旧last_pioneer_decision为解析兼容别名 |
| `raid_survey` | 实际武器圈已扫进度、真炮阵、操炮位覆盖、召唤就绪及拒绝原因；详见[布局侦察](CoreGeek/docs/LAYOUT_SCOUTING.md) |
| `action_rejected` | 本地候选动作没有通过统一校验 |
| `protocol_error` | 请求结构、数据或回合序列错误 |
| `decision_failed` | 非预期内部错误，记录traceback并返回空动作 |
| `decision_busy` | 会话锁繁忙，短等待后降级 |
| `request_read_timeout` | 读取请求超时 |
| `response_connection_closed` | 写响应时连接已关闭或超时 |

官方`errors`、`lastRoundRoleActionResults=false`、本地校验拒绝和HTTP错误是不同层次，不能合计为官方队伍异常次数。官方停调度、结算和胜负不由此Agent代算。

<a id="limitations"></a>

## 当前限制与后续工作

1. **建造严格限定在合法圈层。** 第一圈武器、第二圈墙依据用户本轮澄清；U形蓝图是团队策略，布局配置不能授权越圈建造。
2. 已接入选手侧任务、LLM、沙盒与宝藏往返，但真实题目解题正确率、实际LLM质量和官方沙盒尚未验证。
3. 直线弹道格边界、样例射程与任务书冲突、复活/轮号等疑点仍登记在[规则覆盖清单](CoreGeek/docs/RULE_COVERAGE.md)，不以本地估值代替官方裁定。
4. 移动采用保守占用检查，可能牺牲拥挤场景效率；隐藏敌人和机器人下一步移动仍可能导致合法动作执行失败。
5. 当前没有完整比赛模拟器、网页面板、数据库和磁盘断点恢复；压力工具不评估双队胜负。
6. 十三动作均有校验入口，但基线不主动`remove/drop`，不主动采购所有消耗品；后续可在策略层按明确目标扩展。
7. 本机已验证Windows Python入口。Linux `bash run.sh port`仍需在目标比赛环境实际验证。

后续开发按`DEVELOPMENT_RULES.md`标注变更类别与R编号，保留官方原文；规则修复先保留独立失败案例。每次新增状态或策略能力时同步更新本文的目录、函数表和参数说明。

v1.2.23按用户要求只验证第一天；范围、结果和源码哈希见[首日验证报告](reports/VALIDATION-v1.2.23.md)。v1.2.20使用的原始build_bug3日志保留在temp中；本版依据用户两张阵型图，运行时和测试均不依赖temp存在。v1.2.9的625项回归、320份合成压力与1105次HTTP为[历史证据](reports/VALIDATION-v1.2.9.md)，不作为当前官方对局结果。
