# 自进化任务模块接入与维护

版本0.3.10，2026-09-23。采用用户新提供的 `temp/task_prompt(1).py` 与 `temp/task_controller.py`，自进化决策与提示词以这两个文件为准。正式源码不读取 `temp/`；原件保留。涉及 R01、R07，官方规则、接口与 demo 原件没有修改。

## 1. 来源与接入范围

- 提示词移植到 `app/service/task_prompt.py`。保留文件定位、API 原始响应、错误修参、CRLF 修复、提交格式自检和最近20条历史等内容。唯一内容补充是实际插入 `skill_hint`，原文件接收该参数但未写进 prompt。
- 控制器移植到 `app/service/task_controller.py`。正式自进化链路调用 `SelfEvolveController`，沿用 JSON/代码块/前后说明文字提取、XML 兼容、命令诊断、SOP/Skill、失败冷却。
- 接任务时的路径选择、白天时间检查、回防和工人策略仍由现有 `Strategy` 调度。接受任务时记录选中的点位、类型与时长；活跃任务交给新控制器。因此不调用外来控制器依赖其原工程 movement 的 `_try_start`。
- 同文件的 `TreasureController` 原样保留供后续迁移；本次实际替换的是自进化任务，新闻和宝藏仍走 `LLMService.apply_news → Strategy.treasure`，未切换为该辅助类的猜测式献祭。
- SHA256、逐函数移植差异以及 `teamA (2).log` 的只读解析记录见 [来源审计](../../reports/task-integration-v0.3.10.json)。未执行日志中的任何命令，未复制其答案、token 或认证信息到策略。

## 2. 模块位置与数据流

| 文件 | 作用 |
|---|---|
| `app/service/task_prompt.py` | 纯文本生成器；由控制器直接调用，不再叠加旧版任务策略提示 |
| `app/service/task_controller.py` | 用户控制器：命令/答案决策，API 诊断，SOP/Skill 归档及复用 |
| `app/service/task_state.py` | `TaskAgentMemory` 持久状态与内部 `TaskAction` 枚举 |
| `app/service/task_service.py` | 将当前项目的 Turn/Memory/ActionPlan 映射到控制器字段，处理任务切换、反馈关联、回防和死亡 |
| `app/service/llm_service.py` | 校验回复属于上一轮及同一任务；任务原始文本交给新解析器，新闻仍独立严格解析 |
| `app/service/memory.py` | 每队、每阵营会话记忆，接任务的轮次及预算；嵌入 `task_agent` |
| `app/service/task_context.py` | 接取轮次估计、旧协议规范化及兼容工具；不再决定新版重试策略 |
| `app/service/turn_service.py` | observe → consume → TaskService.active → Strategy.run → record，最后事务提交 |
| `src/agent/brain.py` | 接取前的路径/日照预算，接受时调用 `task_agent.accept(task)`，冷却期不重接；其它策略沿用基准 |
| `tests/test_task_controller.py` | 同型复用、失败归档、冷却、协议兼容、预算和会话隔离 |
| `tools/audit_task_integration.py` | 离线比较用户源码和正式源码，并检查日志中的 LLM 回复能否解析 |

正常交互：接取 → 收到 `phaseTask` → prompt → 下一轮 `llmResp` → executeCmd → 下一轮 `lastCmdResult` → prompt → 下一轮答案 → submitAnswer → 根据后续 `phaseTask/errors/actionResults` 归档。

`executeCmd` 仅作为响应字符串返回官方沙盒。提示词仅返回官方 LLM；本程序不在选手主机执行命令，也不直接调用模型服务。官方响应仍只有 `roleCommandMap`、`prompt`、`executeCmd`。

## 3. 关键函数及参数

| 函数 | 输入与返回 | 行为 |
|---|---|---|
| `build_self_evolve_prompt(task_desc, context, steps_used=0, timeout_rounds=0, sop_hint=None, skill_hint=None)` | 当前题目、字符串历史、实际已过轮数、总预算、可选 SOP 与 Skill；返回 str | 历史最近20条，预算≤0默认15，SOP 和 Skill 均进入提示 |
| `TaskService.active(turn, memory, plan, llm, reply, defense_due=False)` | 观测、会话副本、动作计划、LLM 服务、通过轮次匹配的原始回复；返回 `(prompt, executeCmd)` | 先结算旧任务再初始化新任务；保留活跃开拓者；回防或死亡时释放 |
| `controller_reply(reply)` | str 或兼容旧调用方的 dict；返回规范化 v2 JSON 或空字符串 | 优先使用用户解析器；未识别时兼容旧 `executeCmd/taskAnswer`；不执行内容 |
| `SelfEvolveController.decide(role)` | 桥接角色；返回是否接管本轮 | 活跃任务调用 `_continue_agent`；结果写到状态的 response 字段或角色的 task_answer |
| `_record_command_result()` | 经过上一轮命令关联校验的原始结果 | 先保留结果再检查终止条件，避免最后一次失败被漏归档；同轮仅记录一次 |
| `_parse_llm_response(resp)` | 原始 LLM 字符串；返回 `(action, payload)` | 支持 v2 JSON、代码块、对象前后文本、XML；沿用用户实现，以 action 决定分支 |
| `_extract_api_diag(cmd_result)` | 沙盒原始输出；返回提示或 None | 提取缺参名称、认证头格式；按集合去重，不猜新的 API 字段 |
| `_timeout_rounds()` | 已接受坐标及任务表 | 优先使用接受时捕获的点位预算；无法定位时按有效任务最大值兜底，再默认15 |
| `_archive_sop()` / `_archive_experience()` | 当前命令结果轨迹 | 成功与失败分别保存，失败条目不会覆盖成功条目 |
| `_sop_hint()` / `_skill_hint()` | 同局经验库及当前任务类型 | 选择匹配的方法加入 prompt，不自动执行历史命令，也不直接提交旧答案 |
| `TaskAgentMemory.accept(task)` | 实际选中的 `PlayerTask` | 捕获坐标、taskType、timeoutRounds；避免其它点位或刷新后的预算串入 |
| `LLMService.register_task_prompt(turn, memory)` | 当前任务与会话 | 只记录 pending，不修改控制器 prompt、不计普通新闻额度 |

命令上限32KiB、答案128KiB、待解析 LLM 文本256KiB；拒绝空值、NUL、无法编码的字符串。这些是本地资源限制。内部 `TaskAction.NOTHING` 为等待标记，响应不输出非法 nothing 动作。

## 4. 状态、经验库与退出

`GameMemory.task_agent` 保存以下字段。它在当前队伍/阵营、当前进程的一局内复用；日切换保留，重开局或不同会话隔离。没有磁盘恢复。

| 字段 | 含义 |
|---|---|
| `self_evolve_active/steps/context` | 活跃状态、控制器推进次数、完整当前轨迹；prompt 仅取最近20条 |
| `self_evolve_task_desc/first_question/started_round` | 任务描述、当前首问和开始回合；任务切换时重新初始化 |
| `self_evolve_pending_pos/accepted_task` | 接受点位及类型/预算快照，用于精准分库和时限 |
| `self_evolve_sop` | type、任务名或类别索引的经验；包含 steps、answer、ok，失败时还有 fail_steps、diags |
| `self_evolve_skill` | 按 taskType 保存首次成功题目和成功步骤；后续更新解法时保留已存首问 |
| `_self_evolve_diags/_self_evolve_fail_streak` | 当前诊断去重及连续失败命令计数 |
| `self_evolve_abandon_tick` | 重新接取的最早轮次 |
| `execution_round/observed_description/suspended` | 上次发命令轮次、已观察题目、已释放任务标记，防止放弃后下一轮立即重启 |

用户提供的常量保持：`MAX_STEPS=30`，`MAX_CONSECUTIVE_FAIL_CMD=4`，`ABANDON_COOLDOWN=25`。推进次数用于防卡死，提示词的已用轮数使用 `roundNo - started_round`，含跳轮，不能用提示调用次数代替真实时间。命令结果保留头1600、尾800字符。

SOP 主要按 `type::<taskType>` 分库，其次按 ws/task 名称、`cat::<类别>` 匹配，优先选择成功条目。失败记录包含已执行成功步骤、失败步骤、诊断和错误答案；即使只有失败命令也保留。Skill 的首问、答案、步骤仅用于当前任务的解法参考。

官方 `lastRoundRoleActionResults=true` 只表示动作合法。本项目因此要求：上一轮确为提交、动作合法、当前任务已结束或更换、且无官方错误，才归档成功。任务仍在继续时不会提前宣布成功；超时或判错保存失败经验。缺少反馈只按未确认结束处理。这仍不是对100%通过率或官方得分的测量。

四次非零退出码/超时/判题器命令异常、推进上限、判错或额度错误触发退出；当前相同题目保持 suspended，避免反复抢回开拓者。重新接取仍受25轮冷却约束。回防或死亡也释放任务并保留已有探索；官方决定离开范围/死亡后的结束状态。

为遵循用户控制器，当前不再由旧适配器硬拦截重复命令或预算末尾命令；是否重试、如何合并步骤由提供的 prompt 与控制器决定。超时最终以官方反馈为准。

## 5. Postman 本地联调

启动 `python CoreGeek/main3.py 8080`。

- 健康检查：`GET http://127.0.0.1:8080/health`。
- 回合调用：`POST http://127.0.0.1:8080/`，`Content-Type: application/json`，Body → raw → JSON，发送完整官方观测。`/decision` 等其它 POST 路径也由同一处理器接收。
- 连续回合保持同一 teamId/type，每次增加 roundNo；同回合相同报文返回缓存，同回合改内容会被拒绝。

下面仅列每轮需要修改的字段，其它地图和角色字段仍须保留：

| 轮次 | 请求变化 | 预期响应 |
|---|---|---|
| N | `phaseTask="Read task_demo.md"`，LLM/命令结果为空 | 返回用户新版 prompt |
| N+1 | `llmResp` 填字符串 `{"action":"execute_command","command":"printf fixture"}` | 顶层 executeCmd；本机不执行 |
| N+2 | 清空 llmResp，`lastCmdResult="[exitCode:0]\nfixture"` | 含 `cmd:`/`cmd_result:` 的下一份 prompt |
| N+3 | 清空 lastCmdResult，llmResp 填 `{"action":"final_answer","answer":"fixture"}` | 开拓者 submitAnswer，taskAnswer 为字符串 |
| N+4 | 清空 phaseTask/llmResp；上一轮开拓者结果 true、errors 空 | 归档经验；当前地图策略继续运行 |

LLM 回复与命令结果都需要你手动填写或由官方平台产生。本地 HTTP 只验证流转，示例 fixture 不是任务答案。回防场景需要先满足防守策略，否则系统会正常释放任务。

## 6. 修改与验证

调整任务提示：改 task_prompt.py；调整解析/经验选择：改 task_controller.py；调整回合、反馈或回防边界：改 task_service.py；新增持久字段：改 task_state.py 并检查会话隔离。不要把原始 temp 文件作为运行依赖。

运行 `python CoreGeek/run_tests.py`。来源/日志解析可重现：

```powershell
python CoreGeek/tools/audit_task_integration.py --prompt 'temp/task_prompt(1).py' --controller temp/task_controller.py --log 'temp/teamA (2).log' --output reports/task-integration-v0.3.10.json
```

正式源码回归、HTTP 与验证范围见 [本版验证报告](../../reports/VALIDATION-v0.3.10.md)。参考日志中28条非空LLM回复全部可解析（23命令、5答案），不代表本版本已经完成对应官方对局。
