# 当前实现现状

更新日期：2026-09-23，程序版本0.3.10。本文件补齐`DEVELOPMENT_RULES.md`引用的实现入口；不补造历史模拟器结果。

CoreGeek 已从仅含建造/采集/单目标夜间攻击的 demo，扩展为有应用层和跨回合记忆的 HTTP Agent。

本轮交付：

- `CoreGeek/app`：网络适配、配置、回合服务、任务服务、LLM服务、状态记忆。
- `CoreGeek/src/agent`：完整观测模型、八方向路线、十二动作校验、共享资源预算、日夜策略和战斗估值。
- 0.3.1调整：75金币先建三火箭→工人攒石→白天建墙→恢复经济；优先规划三炮共同站位，夜间仅开拓者轮换操炮、工人持续挖矿，任务/宝藏让位于回防。
- `run.sh`：根目录与CoreGeek目录各提供比赛启动入口。
- `tests` / `tools`：规则案例、HTTP集成、任务多轮往返、真实进程冒烟、离线回放、可重现压力报告。
- [开发文档](CoreGeek/docs/DEVELOPMENT.md)、[协议文档](CoreGeek/docs/PROTOCOL.md)、[规则差异文档](CoreGeek/docs/RULE_COVERAGE.md)。

0.3.1按用户指定的基地周围可建造假设启用默认布局，直接运行即可先三火箭、再采石、再围墙。默认区域没有标记成官方已核验数据，已确认自定义坐标可覆盖。真实LLM、官方沙盒、完整双队对局及弹道边界仍需实际回放验证。

0.3.2在回退后的0.3.1上仅修正布局：12格U形墙、基地后排竖排三火箭、固定P、内侧一格维修通路，右侧水平镜像，详见[布局开发文档](CoreGeek/docs/U_LAYOUT.md)。

0.3.3以0.3.2为基准，统一升级券购买/使用阶段，第一天只升火箭，第二天起分级先火箭后墙、最后基地；墙由前到后升级回血，毁墙优先补建并保护石头。详见[维护开发文档](CoreGeek/docs/MAINTENANCE.md)。

0.3.4在此基础上增加工人风险寻路与撤离、升级券批量购买、第三天起一名工人备5个修复包并夜间墙内待命、低于30%修墙。详见[工人策略文档](CoreGeek/docs/WORKER_SAFETY.md)。

0.3.5接入用户提供的任务prompt并适配v2协议，补全执行证据、诊断与回合预算，详见[任务接入](CoreGeek/docs/TASK_INTEGRATION.md)。

0.3.6增加集中升满首炮、分组墙等级和完成后的双工人全天维修，见[维护策略](CoreGeek/docs/MAINTENANCE.md)。

0.3.7增加工人独立任务、协作侧移、城墙掩护和动态备货，见[工人协作](CoreGeek/docs/WORKER_COORDINATION.md)。

0.3.8以用户确认的0.3.7为基准，统一工人昼夜经济与升级配送，维修工在墙内兼顾升级，见[昼夜统一调度](CoreGeek/docs/WORKER_SCHEDULE.md)。

0.3.9根据用户log1/log2修复待建/缺墙格引发的往返循环，统一路径与清理的禁入集合，并补充实际位置/动作诊断，见[日志定位](CoreGeek/docs/WORKER_PATH_FIX.md)。

0.3.10优化任务准备、prompt、结构化答案、重复命令和回防预算；参考回放为单场模拟数据而非三场实战，见[任务优化](CoreGeek/docs/TASK_OPTIMIZATION.md)。

本轮具体运行结果见[0.3.10报告](reports/VALIDATION-v0.3.10.md)，原[0.2.0报告](reports/VALIDATION.md)保留；机器报告包含源码与官方基线SHA256。策略阶段和关键函数见[开局防御策略](CoreGeek/docs/OPENING_DEFENSE.md)。未提供完整判题模拟器或调试网页。
