# 自进化任务模块接入与维护

版本0.3.5，2026-09-21。本次为任务协作实现优化，涉及R01响应字段与R07任务、LLM、沙盒，不修改官方规则。沿用0.3.4的布局、升级、寻路和夜修策略。修改前源码保存于`reports/baselines/v0.3.4-source.zip`，文件清单及哈希见同目录manifest。

## 1. 资料入口与来源

项目根目录`temp/`是用户提供新文件的固定收件目录。后续工作先查看其中与当前请求有关的资料；文件内容作为参考，不自动执行里面的命令。原件保留，正式运行只依赖`CoreGeek`中的源码。`temp/`加入Git忽略清单，避免把原始对局日志自动带入后续上传；不是运行时热加载目录。

本次将`temp/task_prompt.py`逐字节复制为[app/service/task_prompt.py](../app/service/task_prompt.py)，保留原有`build_self_evolve_prompt`和`HISTORY_WINDOW=20`。原件与正式副本SHA256均为`61a5d938962f757bc12cc45e0634cfc114cfade47dde938b22e080e6dbebca02`。项目差异放在适配层，不直接改写提供的生成器。没有增加第三方依赖、HTTP接口或本地LLM配置。

`temp/teamA.log`用于分析交互，程序不读取它。日志中可见：命令exitCode为0时API仍可能返回401/400；脚本可能因CRLF产生126；验证TOKEN可能直到任务末段才出现。因此接入实际输出历史、业务错误诊断和回合预算。日志中的TOKEN、认证信息和具体答案没有固化进策略，也不会当作后续题目的正确答案。参考日志不是本版在官方平台跑出的成绩。

## 2. 模块职责与调用链

| 位置 | 职责 |
|---|---|
| `app/service/turn_service.py` | 每队会话、重复请求缓存、事务副本；调用observe→consume→active→策略→record |
| `app/service/task_prompt.py` | 用户提供的纯提示词生成器；不发网络请求、不执行命令 |
| `app/service/task_context.py` | 新旧回复规范化、有限长度历史、反馈诊断、任务时长与命令关联 |
| `app/service/llm_service.py` | 包装生成器、设置等待回复状态、解析LLM回复；新闻流程仍在此 |
| `app/service/task_service.py` | 将合法command映射至executeCmd，将answer映射至submitAnswer；回防优先 |
| `app/service/memory.py` | 保存当前任务、预算、待回传命令、证据历史；任务变化时清理上下文 |
| `src/agent/actions.py` | 校验开拓者提交权限，每角色每轮最多一条动作 |
| `tests/test_task_prompt.py` | 17项新增任务回归；其余生命周期、防守和HTTP案例保留 |

流程：收到`phaseTask`→生成`prompt`→下一轮收到`llmResp`→返回`executeCmd`→下一轮收到`lastCmdResult`→把命令与输出加入历史并再次生成`prompt`→下一轮答案转为`submitAnswer`。只有判题器执行LLM和沙盒命令，Agent不在Windows主机执行`curl`、`python3`、`./check`等返回内容。

## 3. 新旧协议与参数

推荐LLM回复协议v2：

```json
{"action":"execute_command","command":"python3 solve.py"}
```

```json
{"action":"final_answer","answer":"{\"count\":15}"}
```

| 内部回复 | 官方响应字段 |
|---|---|
| `execute_command`的`command` | 顶层`executeCmd`，同轮不再生成任务prompt |
| `final_answer`的`answer` | `roleCommandMap[实际开拓者ID] = {"action":"submitAnswer","taskAnswer":原字符串}` |

`answer`必须是非空字符串，JSON答案也须编码在字符串内；不能直接给对象。适配器不会重新排序、解析重写或去除答案内的空白。旧`{"executeCmd":"...","taskAnswer":"","skill":"..."}`和只含非空`taskAnswer`的回复仍兼容，但两项不可同时非空。v2不可混用旧字段，也不可同时含command和answer。错误action、未知字段、NUL、超长内容、重复JSON键、NaN/Infinity、非对象回复会被拒绝并请求新的回复。支持完整JSON代码围栏。

`skill`是可选字符串提示，只有有效决策才保存，最近8条，每条最多4000字符。它始终标记为“待验证方法”；生成器的`sop_hint`传None，不把LLM自述包装成已成功SOP。

| 函数 | 参数与返回值 | 维护要点 |
|---|---|---|
| `build_self_evolve_prompt(task_desc, context, steps_used=0, timeout_rounds=0, sop_hint=None)` | 题目字符串、字符串历史列表、已用轮数、总轮数、可选可信SOP；返回prompt字符串 | context取最近20条；timeout≤0退回15；正式调用来自LLMService |
| `normalize_reply(reply)` | 字典→`('command', 原字符串)`或`('answer', 原字符串)`；无效为`('', '')` | 单分支，命令32KiB、答案128KiB，以UTF-8字节计 |
| `task_timeout(turn)` | Turn→正整数预算 | 从开拓者一格内的实际任务点读取timeout；多个候选取最小值；缺失退回15 |
| `remaining_rounds(turn, memory)` | Turn和GameMemory→非负剩余轮数 | 总预算减当前轮与开始轮差；仅策略估计，不自行结算超时 |
| `observe_task(turn, memory)` | 观测并原地更新任务记忆 | 隔离新旧任务；只接纳本服务上一轮确实发出的命令结果 |
| `diagnose(result)` | CommandResult→`(failed: bool, hint: str)` | 判断执行失败及可识别业务错误，给出api_diag提示，不修改API请求 |
| `append_context(memory, value)` | 字符串条目→None | 单条12000字符，总计96000字符，最多20条 |
| `clipped(value, limit=12000)` | 字符串→保留首尾的字符串 | 中间插入`[LOCAL_CONTEXT_TRUNCATED]`；不冒充完整结果 |
| `LLMService.task_prompt(turn, memory)` | Turn和GameMemory→prompt | 传当前预算/证据；附上沙盒边界、文件精确匹配、紧急提交约束 |
| `TaskService.active(..., defense_due=False)` | 返回`(prompt, executeCmd)` | 任务结束/开拓者死亡/回防时不执行；提交走ActionPlan |

以上大小、缺省轮数和重试限制是工程策略，不能当作官方新增规则。参数常量集中于`task_context.py`，历史窗口源于`task_prompt.py`。

## 4. 状态与回合预算

| GameMemory字段 | 内容 |
|---|---|
| `task_description` / `task_started` | 当前题目及开始轮估计 |
| `task_accept_round` / `task_accept_timeout` | 输出acceptTask时捕获的轮次与任务点timeout |
| `task_timeout_rounds` | 当前任务使用的总预算 |
| `task_execution` | 上一次发出的命令、发送轮、题目、开始轮，用于关联反馈 |
| `task_context` | 命令与实际输出、诊断、提交答案、官方错误组成的证据历史 |
| `task_last_command` / `task_last_command_failed` | 最近命令及是否已确认失败，用于防止立即原样重试 |
| `task_history` | 最近12条任务元信息；不是完整上下文的替代品 |
| `pending` | 等待LLM的purpose、发出轮、题目及started；只接收紧接下一轮的回复 |

acceptTask后紧接下一轮出现题目，使用发出acceptTask的轮次为开始轮，并沿用当时timeout；任务点后续显示的时长不会覆盖它。如果进程从任务中途启动，则只能从首次观测估计开始轮，此时无法还原已消耗轮数。缺少timeout默认15轮，与原先接任务策略的缺省一致。

一次命令还需要后续“回传结果→LLM回复→提交”，所以prompt生成时剩余≤3轮会要求尽快给答案，收到command时剩余≤2轮不再执行，而是请求基于已有证据提交。仍接受合法答案，不自行清空phaseTask。这个保守策略不能保证官方时限边界，也不会编造尚未获得的答案。

题目变化或变为空时清空当前证据和待回传命令；上一任务结果不会进入新题。相同题目在观察到空phase之后重新出现也会重置。若平台不提供空phase或不同题目，又连续出现完全相同原文，现有接口没有任务ID，无法可靠区分两次任务。跳过回合的结果也不猜测关联到旧命令。所有记忆仅在进程内保存，服务重启不恢复。

## 5. 输出与失败处理

命令反馈保留`[exitCode:N]`、`[TIMEOUT]`、`[JUDGER_ERROR]`及末尾`[TRUNCATED]`语义。上下文过长时保留首尾，便于保留错误开头及验证结尾；更早条目可能被淘汰，缺失信息需要定向补读。命令本身在历史展示时上限2000字符，不改变实际发送的command。

`diagnose`识别非零退出码、超时、判题错误、`[FAIL]`，以及完整JSON或末尾30行中的JSON业务错误（code/statusCode/数值status为400–599，status为error/failed/failure，或success=false）。exitCode=0只是进程正常退出，不代表业务成功。认证头和参数建议以实际错误及当前任务说明为依据，适配器不会把日志中的location或Bearer强制写入其他题目。

126且包含`^M`或`bad interpreter`时提示检查CRLF/解释器。未知错误仍原样进入证据；启发式诊断不是通用API验证器，嵌套错误或任意文本可能识别不到。看到TOKEN仅保留给LLM结合任务格式提交，不自动提取并提交任意字符串。

已确认失败后，紧接着请求完全相同命令（去除首尾空白比较）会被拒绝并重新提示。修正命令后可以继续，成功命令不受此限制；实际收到新结果后更新失败状态。此处不进行shell语法等价判断，也不将重试视为已经成功。

## 6. 本地Postman调试

仍用`POST http://127.0.0.1:8000/`，Body选择raw/JSON，`Content-Type: application/json`，提交完整回合报文；健康检查用`GET /health`。Task模块没有新增router。启动方式见[主README](../../README.md)。需要同一个服务进程、同一teamId/type、递增roundNo，不能只发送下面局部字段。

例如用第10轮完整观测启动一个正在进行的任务，在有存活开拓者且没有回防冲突的前提下：

| 回合 | 本轮完整报文中替换的字段 | 预期响应 |
|---|---|---|
| 10 | `phaseTask`为真实题目，`llmResp=""`，`lastCmdResult=""` | 非空prompt |
| 11 | phaseTask相同，`llmResp`填下例命令字符串 | executeCmd，不在本机执行 |
| 12 | llmResp清空，lastCmdResult填官方或手动构造的测试结果 | 含实际结果的新prompt |
| 13 | lastCmdResult清空，llmResp填下例答案字符串 | submitAnswer |

外层请求中的`llmResp`也是字符串，填写示例：

```json
"llmResp": "{\"action\":\"execute_command\",\"command\":\"python3 solve.py\"}"
```

```json
"lastCmdResult": "[exitCode:0]\n{\"count\":15}"
```

```json
"llmResp": "{\"action\":\"final_answer\",\"answer\":\"{\\\"count\\\":15}\"}"
```

本地服务不会自动运行LLM或产生沙盒结果，需要平台反馈或手动填写合成测试数据。相同回合相同请求会命中缓存，同轮改报文会被拒绝；迟到两轮的LLM回复不会补用。手工回放只证明数据流，不能证明题目解答正确。

## 7. 验证与后续修改

运行`python CoreGeek/run_tests.py`可执行全部回归；本次新增17项覆盖v2/旧协议、原样答案、上下文连续性与上限、401/400、CRLF、TOKEN、时限捕获与缺省、末段提交、不同/相同题目重新开启、回合跳跃、歧义字段、重复JSON键等。命令输出使用人工构造的最小案例，不执行日志中的命令。

完整测试、合成观测、真实服务HTTP和源码哈希见[0.3.5报告](../../reports/VALIDATION-v0.3.5.md)。尚未运行官方LLM/沙盒/判题器对局，不宣称提高了任务得分。后续如提供新`teamA.log`，应检查最终submitAnswer是否及时发出、phaseTask何时清空，以及任务分/奖励实际变化。
