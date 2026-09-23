# 任务模块优化与回放资料审计

版本0.3.10，2026-09-23。变更类别为任务流程/提示词优化，涉及R01接口、R07任务与官方沙盒。用户已确认0.3.9稳定；修改前保存[0.3.9源码快照](../../reports/baselines/v0.3.9-source.zip)及[SHA256清单](../../reports/baselines/v0.3.9-manifest.json)。`src/agent`战斗、开局、工人、维修与升级代码未修改。

## 1. 实际收到的资料

`replay_crawler/logs/0df417d673710fe4e14f8b43/`包含三个文件，每个1013行，按`half/side/round`对齐：

| 文件 | 内容 |
|---|---|
| `observations.jsonl` | 半场1、challenger，第1–1013轮的观测，包括phaseTask、llmResp、lastCmdResult |
| `responses.jsonl` | 对应回合的roleCommandMap、prompt、executeCmd |
| `diagnostics.jsonl` | 决策目标/工程计划摘要，不能替代任务判题反馈 |

它们是**同一个回放的三个数据流，不是三场独立对局**。任务原文明确写着“快速任务模拟……解题结果由预设能力模型决定，不代表真实解题质量”；8份工具结果带`synthetic: true`，6次提交均为模拟结果。JSON中文本身正常，初次终端显示乱码不代表原文件损坏。没有运行爬虫、访问其中的网址，也没有在主机执行任何回放命令。

六段任务首次活跃→提交回合为14→16、20→27、143→145、166→168、272→274、278→280。第二段在22、24、26轮反复读取同一spec文件，前三次工具返回相同内容，之后才提交。来源指纹与结构统计见[资料审计JSON](../../reports/task-replay-analysis-v0.3.10.json)。

可借鉴的是：优先精确读取当前题目、合并必要资料、再请求模型；工具输出驱动后续动作；答案可用结构化JSON表达。不能借鉴的是固定模拟答案、预设成功率、未经真实工具验证的“已完成”或模拟奖励。正式策略中没有写入这些答案、任务端口、身份或token。由于资料与“三场优秀实战”的描述不一致，已请求核对位置；本版不冒充基于三场实战训练或验证。

## 2. 改了什么

### 明确文件路径时先读资料

新增`app/service/task_bootstrap.py`，纯函数`bootstrap_command(task: str) -> str`生成官方沙盒命令，不在Agent主机执行。

当新任务描述包含**唯一的绝对Markdown路径**时，`TaskService.active`首次直接返回只读`executeCmd`：读取指定任务书最多7000字符、同目录最多2份api/sdk/interface/readme Markdown各1500字符，列出最多40个相邻名称。读取超长内容显式标记`truncated`；读取失败返回`read_error`。不修改任务文件，不运行check，不调用API、不递归扫描系统。

脚本参数使用`shlex.quote`，不把描述里的shell片段拼进命令。出现多个不同路径、相对文件名、`..`路径、超长路径或时间不足时交给模型按证据定位，不默认选第一份。一次任务最多自动探读一次，失败后交给模型修正；任务切换时重置。

| 典型链路 | 第1轮 | 第2轮 | 第3轮 | 第4轮 |
|---|---|---|---|---|
| 旧版 | 请求模型找文件 | 执行读文件命令 | 提供结果并请求模型 | 提交答案或执行下一步 |
| 新版明确路径 | 直接执行只读命令 | 提供结果并请求模型 | 提交答案或执行下一步 | 按反馈继续 |

在这一特定链路中少一次模型调用、少一个游戏回合；不是承诺所有题都只需3轮。只有相对文件名时仍走模型发现流程。沙盒15秒、输出64KB限制未改。

### 重写提示词，统一证据和提交要求

`app/service/task_prompt.py`现在是项目维护的提示词，保留函数签名和`HISTORY_WINDOW=20`。`temp/task_prompt.py`原件保留不变；0.3.5逐字节复制的历史说明不再表示当前副本仍相同。

删除了以下冲突或容易误导的内容：

- 一边要求精确匹配任务文件，一边建议`head -1`任取第一个。
- 把出现TOKEN当作立即认定全部成功的依据，忽略同轮FAIL或业务错误。
- 无论题目schema如何都要求“年份必须字符串”等固定类型规则。
- 已有资料却仍要求重复读完整任务书。

新的顺序是：核对历史与预算 → 确认当前提交schema和缺失证据 → 数据/API任务合并获取、完整分页、计算与输出 → 工程任务合并必要修改与验证 → 按真实结果提交。明确保留失败项、业务错误和截断信息，禁止把示例/模拟结果当答案；脚本每次写明cwd，避免假定上一轮cd持久化。

### 支持结构化JSON答案

推荐协议仍为v2：

```json
{"action":"execute_command","command":"python3 solve.py"}
```

```json
{"action":"final_answer","answer":{"count":3,"label":"actual"}}
```

`normalize_reply`新增支持v2的dict/list答案，只用`json.dumps(..., ensure_ascii=False, allow_nan=False)`转成官方`taskAnswer`字符串；数字、布尔、null、嵌套结构保持，不推测或填补字段。原本字符串答案逐字保留，不重新编码内容。纯数字、bool等顶层值仍不接收；题目要求这种纯文本时应给字符串。未知字段、command/answer混用、NaN/Infinity、NUL、无效Unicode和长度限制仍检查。旧协议`taskAnswer`继续要求字符串。

这是一种序列化便利，不是正确性判题；schema和答案是否正确仍由官方反馈决定。

### 阻止无进展重复，允许修复后复查

原已确认失败命令禁止原样立即重试的机制保留。新增记录上一条命令、真实结果SHA256和连续相同次数：同一命令连续两次返回相同结果时，第三次同样请求被替换为提示，要求利用已有证据推进。

中间执行了不同的修复命令后，可以再次运行相同`./check`；同一轮询命令若实际返回内容变化，也不会计作无进展。只比较成功关联到当前任务、当前执行的下一轮反馈，任务切换清空记录。此限制不是模拟判题，也不会自动提交历史答案。

### 预算包括回防时间

`TurnService`沿用原本开拓者操控位置、实际路径与`return_margin`计算任务最晚可用截止：

```text
有武器时：回防截止轮 = 当前轮 + max(0, daylight_left - 到操控格路径成本 - return_margin)
实际可用回合 = min(任务剩余回合, 回防截止轮 - 当前轮)
没有武器时：仅使用任务剩余回合
```

该预算写入提示词；剩余≤2轮拒绝新命令并请求基于已有证据提交。既有`defense_due`仍优先释放开拓者去控炮，未修改战斗策略。预算每轮重新计算，避免把上轮或上一局的路线当成固定截止。

## 3. 模块、参数与记忆

| 文件/函数 | 参数、返回与用途 |
|---|---|
| `task_bootstrap.bootstrap_command(task)` | 当前描述→官方沙盒命令或空字符串；路径不明确则退回模型 |
| `task_bootstrap.READ_SCRIPT` | 本项目只读脚本文本，随executeCmd发送；不在服务内执行 |
| `task_service.TaskService.active(...)` | 新任务只读准备、回复映射、失败/重复限制、预算与回防 |
| `task_prompt.build_self_evolve_prompt(task_desc, context, steps_used=0, timeout_rounds=0, sop_hint=None)` | 生成提示词；可选hint是待核对方法，不能冒充成功SOP |
| `task_context.normalize_reply(reply)` | v2/旧协议→(kind, string)，新增v2对象/数组序列化 |
| `task_context.observe_task(turn,memory)` | 只关联当前任务的实际执行反馈，更新命令重复计数并清理任务切换状态 |
| `task_context.remaining_rounds(turn,memory)` | 超时和回防两项预算取更小值 |
| `llm_service.LLMService.task_prompt(turn,memory)` | 原协议等待标记与适配约束，附加实际可用回合 |
| `turn_service.TurnService.decide(payload)` | 计算任务回防截止；其余事务、HTTP和策略流程保留 |

`GameMemory`新增`task_bootstrap_done`、`task_last_result_hash`、`task_command_repeats`、`task_defense_deadline`。前三项任务切换时清空，截止每轮由服务更新。所有状态仍按队伍会话隔离，不落盘复用旧题答案；服务重启时可能重新读取当前题目，但不会使用上一进程的未知证据。

没有新增配置、HTTP路由、主机命令执行能力、外部网络依赖或运行时日志依赖。`POST`仍接原官方报文，读取下一轮`lastCmdResult/llmResp`继续任务。新的确定性只读步骤仍需要官方沙盒执行，Postman本地调试不会凭空获得文件内容。

## 4. 验证与后续资料

新增12项任务效率测试，覆盖明确路径先读、歧义不猜、脚本参数引用/有界只读、读取失败与任务切换、结构化答案类型/错误、重复输出阻断、修复后复查、变化中的轮询、失败与TOKEN并存、回防预算。只在临时测试文件上执行本项目自己的纯读取函数，没有执行其他战队日志中的命令。

完整本地结果见[0.3.10验证报告](../../reports/VALIDATION-v0.3.10.md)。未调用真实LLM或官方沙盒，不声明完成率提升。要比较真实任务质量，需要实际任务书、执行结果、提交答案及官方判题反馈组成的完整回合链；现有模拟得分只能用于流程观察。
