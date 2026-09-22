# v0.3.8 本地验证记录

日期：2026-09-22。变更类别为策略优化，依据本地任务书/接口文档v1.0及`DEVELOPMENT_RULES.md`，涉及R02/R03/R05/R06。没有重新拉取官方规则，没有修改官方原件，也没有执行日志或任务输出里的沙盒命令。

## 变更和保留基准

用户确认表现最好的v0.3.7已存为[基准ZIP](baselines/v0.3.7-source.zip)，共103个文件，附[逐文件SHA256](baselines/v0.3.7-manifest.json)。保存源码、配置示例、文档和历史报告，排除temp、缓存、构建产物、私有配置和旧基准包；解包逐项哈希核验通过。

基准ZIP SHA256：`c70ae8d6e32d3d920044341d12eff7aebf47128d8910bbbc9c02730c0b2bfd94`。

本轮运行时代码仅修改`brain.py`与`wall_guard.py`：统一普通工人昼夜经济流程，允许夜间采购/配送/升级；指定维修工先修危墙，可在内侧升级，安全商店旁可买缺包再回岗。夜间禁建、避敌、独立任务/让行、城墙掩护、动态库存继续生效。版本号改为0.3.8。

`upgrade_policy.py`、`worker_coordinator.py`、`worker_safety.py`、动作校验、协议、战斗、任务服务、配置和记忆代码均与0.3.7相同。三火箭/U形墙、升级顺序、基地不升级、控炮和最终双工人维修保持。源码差异列表及47个源码/配置指纹见[机器报告](validation-v0.3.8.json)，5个规则/样例基线指纹与0.3.7一致。

## 实际执行结果

| 项目 | 结果 |
|---|---|
| 单元/回归/集成测试 | 185项，0失败、0错误，12.643秒 |
| 合成观测检查 | 80份，0失败；种子17、20260917；challenger/defender各覆盖 |
| 压力配置 | 三火箭40份、混合兼容40份；夜间0–150个机器人 |
| 合成观测耗时 | 中位21.165ms，最大822.552ms |
| 实进程HTTP | 200，3条动作，46.227ms；启动日志确认0.0.0.0绑定 |
| 原始样例回放 | request.txt计算成功，保存响应；不执行executeCmd |
| 包一致性 | wheel中22个Python模块与最终源码逐字节一致 |

错误输入测试中的`protocol_error`日志是故意输入非法JSON/字段产生的预期结果，不是本次请求异常。命令入口实际使用Windows Python，未执行Linux `bash run.sh`。

新增`tests/test_worker_schedule.py`共16项测试：跨黄昏/黎明配送及卖矿、矿点连续、夜间购券及批量、两侧用券、观察等级后再升下一档、失败重试、危险路线约束、缺墙/缺炮夜间不建造、维修工沿内侧升级、优先危墙、到店补货和暴露时不买。修复前最初9项中4项失败、1项错误，复现夜间采矿分支和黄昏购物截止问题；其中相邻火箭夹具随后对齐实际首选ID601所在的(5,6)，未改正式样例。

两项旧测试要求有钱的工人夜间仍只采矿，本轮按明确需求改为夜间允许继续采购当前阶段升级券；保留危墙维修、动作合法性和独立工人任务断言。未放宽ActionPlan或合成观测检查来获得通过。

## 产物与复现

- [HTTP记录](http-smoke-v0.3.8.json)
- [样例响应](sample-response-v0.3.8.json)
- [机器验证报告](validation-v0.3.8.json)
- [工人昼夜调度文档](../CoreGeek/docs/WORKER_SCHEDULE.md)
- [安装包](../CoreGeek/dist/coregeek_futurewar-0.3.8-py3-none-any.whl)，SHA256：`8acbad3f70a78cd6401b4305d447862717b23fe7cbdff9107025a79ac6483f23`

在项目根目录执行：

```powershell
python CoreGeek/tools/validate.py --cases 20 --output reports/validation-v0.3.8.json
python CoreGeek/tools/smoke_server.py --output reports/http-smoke-v0.3.8.json
python CoreGeek/tools/replay.py request.txt --output reports/sample-response-v0.3.8.json
```

## 证据边界

这不是官方平台对战结果，没有测量实际胜率或全局路程减少百分比。跨回合测试只应用所需的位置/库存/等级反馈，不伪装完整判题器。危险变化、被占用路径、资源消失、岗位启用和紧急维修仍可能中断经济任务。维修工不会为追逐升级任务离开内侧职责范围，夜间不从墙内发起新采购。

城墙掩护仍是用户实战观察支持的策略；不改变官方机器人攻击规则。正式双队对局、实际LLM/官方沙盒、弹道边界与目标Linux入口等未覆盖项保留。历史报告单独保留，不能用本版结果冒充官方认证。
