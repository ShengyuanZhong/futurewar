> 当前版本0.4.1：用户已将下述实现提升为v0.4基准，后续改动见[失败任务修正](TASK_FAILURE_LEARNING.md)。下文保留0.3.10接入来源。

# 0.3.10 任务模块更新

当前版本以用户最新提供的 `temp/task_prompt(1).py` 与 `temp/task_controller.py` 为准。详细架构、函数、字段、阈值及 Postman 回合示例见 [任务接入文档](TASK_INTEGRATION.md)。

本次实际改动是接入用户的自进化控制器与提示词：按 taskType 复用 SOP/Skill、保存失败经验、自动提取 API 缺参/认证要求、兼容带说明文字的 JSON 与 XML，连续失败退出并冷却。补齐 Skill 注入，准确关联已接受任务的点位、预算、命令和提交反馈。命令仍只返回官方沙盒。

0.3.9稳定战斗与工人策略沿用；接任务仅增加点位快照与任务冷却检查。已保存基准于 `reports/baselines/v0.3.9-source.zip`。最新参考原件和移植差异见 [来源审计](../../reports/task-integration-v0.3.10.json)。正式程序不读取 temp 或 replay_crawler。

此前审计的 `replay_crawler/logs` 只有同一回放的 observations/responses/diagnostics，包含 synthetic 模拟任务；[审计记录](../../reports/task-replay-analysis-v0.3.10.json)仅作为资料历史保留。当前实现采用最新提供的实战模块，不从模拟成绩推断任务完成率。新 `teamA (2).log` 仅作离线解析兼容检查，未执行其中命令、未写入其中答案。

本地验证结果与官方实战边界见 [验证报告](../../reports/VALIDATION-v0.3.10.md)。
