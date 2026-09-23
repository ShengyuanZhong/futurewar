# 任务交互日志（v0.4.2）

用户提供的 `temp/print_log.py` 是原项目中的日志调用片段，使用 `state.game_logger.log_info` 和 `state.tick_in_day`。当前项目的回合模型是 `Turn`，日志入口是 `TurnService` 的 Python `logging`。已将片段中的字段和格式接入正式回合日志，参考原件保留在 `temp/`，运行时不依赖它。

## 输出位置与内容

`CoreGeek/main3.py` 将 INFO 日志写到标准错误流（stderr）。每个成功处理的新回合产生一条多行 `[TASK-DEBUG ...]` 记录，包含收到的 `phaseTask`、`llmResp`、`lastCmdResult`，以及本轮最终响应里的 `prompt` 和 `executeCmd`。空值显示为空字符串。随后仍有原来的 `decision` 和 `worker_motion` 摘要。相同报文的同回合重试直接返回缓存，不重复打印任务记录。

首行格式：`[TASK-DEBUG R<round> day<day> tick<tick> DAY|NIGHT]`。`day` 取自 `Turn.day`，`tick=(roundNo-1)%130`，昼夜标识取自 `Turn.is_day`。第1天第70轮是 `tick69 DAY`，第71轮是 `tick70 NIGHT`；第2天第1轮是全局R131、`tick0 DAY`。

日志打印的是完整交互文本，含模型回复、沙盒结果、最终 prompt 与命令。它不是 JSON 响应的一部分，HTTP 请求和角色动作结构没有新增字段。日志源自实际已解析的回合与已生成的响应，不从 `temp` 读取或推断输出。

## 代码位置

| 函数/调用点 | 参数 | 作用 |
|---|---|---|
| `app/service/task_logging.py:task_debug_message(turn, response)` | `Turn` 和完整响应字典 | 按用户片段生成一条多行字符串，不修改输入 |
| `app/service/turn_service.py:TurnService.decide(payload)` | 官方请求字典 | 响应确定并写入会话缓存后调用 `LOGGER.info`，每个新回合只记录一次 |

调试时先按 `[TASK-DEBUG R...]` 找回合，再按 `phaseTask → llmResp → executeCmd → lastCmdResult → prompt` 追踪任务交互。`executeCmd` 只是提交给官方隔离沙盒的字符串；本机日志不会执行它。原来的 `decision_failed`、`protocol_error` 继续用于识别服务错误。

回归位置：`tests/test_task_logging.py` 覆盖提示词、命令、反馈字段，昼夜边界，重复请求只记录一次，以及日志对响应的零影响。当前本地验证见 [v0.4.2 报告](../../reports/VALIDATION-v0.4.2.md)。
