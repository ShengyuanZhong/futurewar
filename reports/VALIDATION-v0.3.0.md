# 本地验证报告：0.3.0三火箭开局

> 本页保留0.3.0历史结果；默认启用基地周围建造的修复见[0.3.1独立报告](VALIDATION-v0.3.1.md)。

日期：2026-09-18。变更类别：策略优化，涉及R01、R03、R04、R06、R07。本报告与[0.2.0历史报告](VALIDATION.md)分别保存，不作为官方认证或对局成绩。

## 环境与规则基线

- Windows，Python 3.10.6，运行代码仅依赖标准库。
- 本地任务书/接口v1.0，日期2026-09-09；上游基线提交登记于DEVELOPMENT_RULES.md，本轮未重新拉取。
- 目录没有Git元数据，通过[机器报告](validation-v0.3.0.json)逐文件SHA256固定源码；官方三份文档和两个样例的哈希保持与旧报告一致。
- 达到的验证范围：协议、单条规则和客户端状态回归、合成观测压力。没有完整双队模拟或官方平台回放。

## 结果

| 项目 | 命令/证据 | 结果 |
|---|---|---|
| 全部回归 | validate.py内执行与run_tests.py相同的测试集 | 75项，0失败、0错误，约2.159秒 |
| 合成观测压力 | `python CoreGeek/tools/validate.py --cases 20 --output reports/validation-v0.3.0.json` | 80份，0断言失败；中位20.173ms、最大800.583ms |
| 真实进程HTTP | `python CoreGeek/tools/smoke_server.py --output reports/http-smoke-v0.3.0.json` | GET健康检查正常；POST原样例200、3条动作、34.512ms；日志确认0.0.0.0及D01提示 |
| 原样例离线回放 | `python CoreGeek/tools/replay.py request.txt --output reports/sample-response-v0.3.0.json` | 完整三字段响应，不执行prompt/executeCmd |
| Python语法 | `python -m compileall -q CoreGeek/app CoreGeek/src CoreGeek/tests CoreGeek/tools` | 通过 |
| 可选wheel | CoreGeek目录执行`python -m pip wheel . --no-build-isolation --no-deps --wheel-dir dist` | 构建成功，包含app、agent及新增construction模块 |

wheel：[coregeek_futurewar-0.3.0-py3-none-any.whl](../CoreGeek/dist/coregeek_futurewar-0.3.0-py3-none-any.whl)。SHA256：`a36eb942978b1519da12a957ad18eb2a664d0e51a89c82e8579f29098f6b1b88`。

交付核对：33份源码/配置/入口文件与机器报告哈希一致；5份官方基线文件与旧报告一致；wheel内16个Python模块逐字节匹配源码，通过`python -I`隔离导入；77处本地文档文件链接及代码围栏配对检查通过。

压力参数：种子17、20260917；challenger/defender各组合20份；夜间随机0–150个机器人。40份使用三火箭、40份保留混合旧炮兼容性；武器等级及火箭冷却变化。独立断言检查响应结构、单角色互斥、移动占用/争抢、夜间攻击、控制距离、仅开拓者操炮及输入冷却0。

压力数值是本机单轮观测耗时，既不是80场比赛，也不是5秒硬实时保证。HTTP测试使用未配置建造区的原样例，不能证明真实初始布局可建成防线。

## 本版新增回归

`tests/test_opening_defense.py`增加19项：

- 默认三火箭；初始75金币先造炮，同轮两工人合计只花50；不被宝藏采购挤占。
- 三炮后按缺墙数攒足石头，建墙优先于卖矿/升级；满包只卖非石头矿物。
- 观测确认施工完成后恢复经济；多轮最小反馈验证三炮→采石→建墙顺序。
- 夜间开拓者一炮、两工人采矿；工人黄昏不回防，开拓者返回共同站位。
- 显式冷却序列产生A→B→C→空→A，跳过冷却炮，保持每轮单操控者单动作。
- 活跃任务停止prompt/executeCmd并让出回防；夜间宝藏让位；开拓者死亡不派工人操炮。
- 工人让出操控格、临时静态阻挡解除后重选完整布局、阵营各自使用确认配置。

原策略测试中与本次分工冲突的预期同步更新；ActionPlan的原有动作权限、金币、数量和互斥约束没有放宽。新增案例在修改实现前已暴露旧策略失败。多轮反馈夹具只更新测试中的移动/建造/采集结果，不模拟战斗、矿刷新、得分或完整判题结算。

测试输出中的`protocol_error`来自故意提交的坏请求，属于预期案例。没有真实比赛执行结果，不能报告官方执行失败或异常次数为零。

## 未验证事项

1. D01官方武器区/墙区坐标仍缺失；默认配置不猜坐标。需要实际布局后才能检查是否有三炮共同站位、墙能否及时建好。
2. 开拓者/工人在第一晚和后续晚上的真实存活率、工人夜间路线风险、任务让位的收益损失。
3. D02样例射程差异、D07弹道边界和真实冷却观测序列；当前直接读取cooldown，测试不替代平台约定。
4. 真实LLM、官方沙盒、真实任务解题质量、完整双队视野/移动/复活/计分链路。
5. Linux目标环境的`bash run.sh port`；本机实际验证的是Windows Python入口。

源码、环境与基线详见[validation-v0.3.0.json](validation-v0.3.0.json)，入口证据见[http-smoke-v0.3.0.json](http-smoke-v0.3.0.json)，样例输出见[sample-response-v0.3.0.json](sample-response-v0.3.0.json)。后续变更须另存报告，不挪用本次数值。
