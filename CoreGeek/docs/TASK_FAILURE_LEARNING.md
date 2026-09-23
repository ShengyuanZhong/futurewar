# v0.4.1 失败任务分析与经验修正

基准是用户确认的v0.4（Python包版本0.4.0，逻辑同0.3.10），备份见[基准登记](../../reports/BASELINE-v0.4.md)。本次只调整任务证据、经验归档与提示词，战斗、工人、布局、升级、回防和HTTP调度保持基准。

## 1. 日志证据

分析文件为 `temp/teamA (2).log`，547396字节，SHA256 `0231f7d25d1b0b9573e05f801dfb8ed3dafef7cf772c793661abb21e79bd0726`。本次文件与上次接入时检查的同名文件一致，这次进一步分析失败原因；不把它当作集成后新跑出的比赛记录。仅解析文本，未执行其中命令，原件保持不变。

文件有1213条回合记录、6段任务交互。5段提交答案后积分增加，1段结束前没有答案：

| 任务 | 活跃开始→结束观测 | 证据 |
|---|---|---|
| 北京API查询 | R12→R24 | R23提交答案，随后积分+86 |
| alpha工程修复 | R50→R61 | R59验证通过，R60提交，随后积分+87 |
| 南京API查询 | R141→R151 | 两次解析失败，没有final_answer，积分未增加 |
| beta工程修复 | R177→R185 | R183验证通过，R184提交，随后积分+86 |
| 成都API查询 | R271→R280 | R279提交，随后积分+86 |
| gamma工程修复 | R306→R315 | R313验证通过，R314提交，随后积分+86 |

这份调试日志没有完整的官方errors和角色动作反馈，不能证明每段的准确通过率。南京任务的10轮预算、R151结束且没有提交支持“超时未交卷”的推断；它不是直接读取到的官方错误码1。金钱变化可能来自销售，不作为任务奖励证据。

## 2. 失败链条

1. **错误请求被记成成功步骤。** R18认证失败401、R20缺参数400，curl都以exitCode 0退出。R142生成的SOP把这些请求放在成功命令序列里，还要求“不要调整步骤”。这会鼓励后续任务重复无效请求。
2. **已知结构没有跨任务保留。** R22已经显示记录位于`data.records`，另有`data.pagination`，实际字段包括`protected_level`、`type`。R147却对`data`对象直接计数和遍历，得到的2是对象键数；随后对字符串键调用`.get`，R148抛AttributeError。还猜用了响应中不存在的字段别名。
3. **修复解析时又引入shell引号错误。** R149没有先核对结构，继续写长统计脚本；其中单引号/撇号破坏外层shell引用。R150同时出现AttributeError和shell syntax error。仅修改统计逻辑没有解决根因。
4. **短任务仍重复读旧API文档。** 当前任务书明确同一API，仅查询条件改变，但R145又读相同文档，占用两轮。旧prompt对10轮、剩3轮的任务仍给出固定5–7条命令估计。R151最后一条命令回复已经晚于任务结束；它退回了此前失败的认证方式，但日志不能证明该命令实际被执行。
5. **工程任务也有被掩盖的失败。** R57的`bad interpreter`被`|| true`变成退出码0。虽然随后修复并成功，这一步不应进入可直接复用的成功步骤。

完整回合、行号、命令指纹、诊断和结构摘要见[机器分析](../../reports/task-failure-analysis-v0.4.1.json)。报告不复制认证值、命令正文、答案或token。

## 3. 实现改动

### 结果分类与结构摘要

新增 `app/service/task_evidence.py`：

| 函数/类型 | 参数 | 返回/限制 |
|---|---|---|
| `inspect_result(raw)` | 完整lastCmdResult字符串 | `ResultEvidence(ok, diagnostics, schema)`；先分类再裁剪 |
| `response_schema(value)` | 已解析JSON对象/数组 | JSON结构字符串，保存字段路径、类型、数组样本字段，不保存记录值 |
| `merged_strings(*groups, limit=10)` | 多组字符串和最大数量 | 去重并限制保留量，用于经验合并 |

退出码0之外还检查API的4xx/5xx、status:error/failed、success:false、`[FAIL]`、Python Traceback、JSONDecodeError、shell语法错误和明确的bad interpreter。无法穷尽任意业务协议，未知文本仍交给模型阅读；不会声称能验证所有API成功。

JSON结构仅从当前完整、非截断、未识别为失败的JSON输出提取。path数组表示逐层字段名；数组记录`item_types`和`sample_fields`。最多12个对象/数组节点、深度4、每层20个字段、每数组前3项、字段名80字符，SOP最多保存4个不同结构。采样不是完整字段清单，不可据此假定其它字段不存在。

### 经验归档

`TaskAgentMemory.self_evolve_command_trace`记录经过上一轮关联校验的命令、完整输出分类结果和结构摘要。TaskService的轮次/任务校验不变，命令仍只返回官方沙盒。

`_record_command_result`在裁剪前分类并写入结构化轨迹；原`cmd_result`继续按头1600、尾800字符显示，结构另用`api_schema:`保留。`_extract_experience/_extract_trace`优先使用结构化轨迹，避免裁剪后漏掉业务错误。

成功SOP现在包含`steps`、`fail_steps`、`diags`、`schemas`、`answer`、`ok`。只有未观察到失败的命令进入steps及Skill；错误认证、缺参和被掩盖的脚本错误进入fail_steps。后一题失败时，可向已有成功SOP补充失败命令和诊断，保留原成功步骤/答案/ok，不用失败流程覆盖它。

`_sop_hint`提供成功方法、真实结构与失败教训，取消“不要调整步骤”的强制复刻。先确认本题目标，只在当前题目明确同服务时复用接口知识；城市、文件、工作区、配置值和最终答案须重新核对。历史错误命令属于避坑证据，不会自动执行。

### 提示词和恢复流程

保留用户新版prompt中的文件定位、工程check/CRLF修复、TOKEN提交与输出格式。补充：

- 同型同服务任务先读本题要求，复用已验证认证、参数和结构，减少重读相同旧文档。
- 统计前确认对象/数组层级及元素类型，字段名来自真实响应；AttributeError不作为重新试认证的依据。
- 响应短且完整时直接据此作答；长数据先保存到沙盒临时JSON文件，修复解析时读取缓存。
- 多行Python使用带引号的heredoc或脚本文件。heredoc和管道输入不可争用stdin；不要将curl数据管道接到同时从stdin读取脚本的Python。
- 后续命令预算为`max(0, (剩余回合-2)//2)`，是预留答案与提交余量的保守提示。剩余≤3时强调有证据就优先提交，不编造缺失数据。

没有增加自动预读命令，没有自动生成任务答案，也没有恢复旧适配器的硬重试/末段命令拦截。原上限30步、连续失败4次、冷却25轮保持；连续失败现在也包含退出码0的已识别业务/脚本失败。

## 4. 复现与验证

```powershell
python CoreGeek/tools/analyze_task_log.py 'temp/teamA (2).log' --output reports/task-failure-analysis-v0.4.1.json
python CoreGeek/run_tests.py
python CoreGeek/tools/validate.py --cases 20 --output reports/validation-v0.4.1.json
```

`analyze_task_log.py`需要显式输入日志路径；正式程序和单元测试不依赖temp。分析工具按调试日志的回合及字段标记拆分交互，不是通用日志格式解析器。

新增`tests/test_task_failure_learning.py`覆盖污染的SOP、跨题结构保留、纯失败经验合并、字段解析/引号错误、裁剪前分类、被掩盖的check失败、业务失败冷却、动态预算、结构大小上限及工程成功路径。最初8项针对性用例在基准上7失败/1错误，缺陷随后修复，并补足3项边界检查。

本地验证报告见[0.4.1报告](../../reports/VALIDATION-v0.4.1.md)。当前没有新的官方模型/沙盒实战回放，不能据本地测试宣称南京任务已经在比赛中成功。
