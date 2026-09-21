# 本地验证报告

> 本页保留0.2.0历史结果。当前默认开局版本的独立证据见[VALIDATION-v0.3.1.md](VALIDATION-v0.3.1.md)，本页数值不适用于新源码。

日期：2026-09-17。此报告是本轮新增证据，不沿用开发规范提到但当前目录未提供的历史报告，不是官方认证。

## 环境与范围

- Windows，本机 Python 3.10.6，运行代码仅用标准库。
- 规则：本地任务书/接口 v1.0（2026-09-09），来源基线见 `DEVELOPMENT_RULES.md`；没有重新拉取上游。
- 仓库当前没有 `.git`，以机器报告中的逐文件 SHA256 固定本轮源码；官方三份文档与两个样例的 SHA256 也已记录。
- **已完成验证层级1（协议）与部分层级2（单条规则/客户端状态）。**没有完成模拟多图留出集或官方平台回放。

## 结果

| 检查 | 命令/证据 | 结果 |
|---|---|---|
| 规则、策略、状态、HTTP回归 | `python CoreGeek/run_tests.py`，或validate.py内同一测试集 | 56个测试，0失败、0错误；最终报告运行耗时约1.394秒 |
| 合成观测压力 | `python CoreGeek/tools/validate.py --cases 20` | 80份输入，0约束断言失败；中位39.802ms，最大96.246ms |
| 真实进程与原样例 | `python CoreGeek/tools/smoke_server.py` | 200响应，3条动作，55.812ms；日志确认监听0.0.0.0；有D01提示 |
| 原样例离线回放 | `python CoreGeek/tools/replay.py request.txt --output reports/sample-response.json` | 生成完整三字段响应，未执行prompt/executeCmd |
| Python语法编译 | `python -m compileall -q CoreGeek/app CoreGeek/src CoreGeek/tests CoreGeek/tools` | 通过 |
| 可选Python包 | `python -m pip wheel . --no-build-isolation --no-deps --wheel-dir dist`，在CoreGeek目录运行 | wheel构建通过，包含app与agent；独立目录导入已检查 |

最终 wheel 文件：`CoreGeek/dist/coregeek_futurewar-0.2.0-py3-none-any.whl`，SHA256：`9dfcbce017d1a718047f97f1e622a76ac18f35e3c1f247459db1ba3a92f4021b`。

压力参数固定为种子 `17`、`20260917`，阵营 `challenger` / `defender`，每种组合20份观测，夜间0–150个机器人。合成观测使用已存在的武器、随机等级/火箭冷却，检查响应字段、角色互斥、移动距离/占用/争抢、攻击昼夜及控制距离。它不驱动连续比赛、不模拟怪物AI，不等价于80局，也没有胜率或10天存活结论。

## 独立案例覆盖

- 基地左上角展开为4格，切比雪夫距离、斜向移动、障碍与目标预留。
- 回合1/70/71/130/131/1300的昼夜边界与日计数。
- 十二动作合法样例及反例；25金币共享预算、三炮总上限、同位置覆盖、容量与商品价格。
- 夜间与冷却、操作者互斥、等级目标数、加特林90°、火箭20/10伤害与重叠、电磁能量分配的可手算估值。
- 双格任务点接取、跨夜保持任务位置、领取→prompt→executeCmd→结果→答案→修订→结束。
- 普通LLM每日3次和跨日恢复、任务调用不计额、跨日旧错误不污染新额度。
- 重复/并发相同请求幂等、冲突/乱序拒绝、换边与第1轮重置、异常不提交部分记忆。
- 宝藏时间与精确物品集合、夜间窗口、失败方案去重；运送远处升级券不会抢占黄昏回防。
- HTTP健康端点、原样例、错误JSON、大小上限、内部异常日志与空动作兜底。

测试中出现 `protocol_error` 日志是故意发送坏请求的预期结果。真实动作执行失败需读取官方 `lastRoundRoleActionResults`；官方异常需读取 `errors` 和平台日志。当前没有真实比赛，不能报告这两类比赛事件为零。

## 仍未验证

1. **D01：蓝色武器区和黄色围墙区坐标。**默认自动建造关闭，无法据此证明初始无武器的正式对局能存活。配置中的`verified`必须有官方依据。
2. D02样例射程冲突、D07弹道格边界及官方边界轮次；选敌伤害估值与真实统一结算之间的误差尚无量化回放数据。
3. 真实LLM输出质量、真实自进化任务与15秒官方沙盒；当前多轮测试使用固定结构化回复，不能代表解题通过率。
4. 真实双队、隐藏视野、机器人同时移动、复活、计分、上下半场与胜负。
5. Linux目标运行环境的 `bash run.sh port`。当前主机没有可调用bash，已经检查源码入口与Python CLI，但没有声称执行过该命令。

## 可复现证据

- [validation.json](validation.json)：测试数量、压力参数/结果、运行环境、源码与基线文件哈希。
- [http-smoke.json](http-smoke.json)：真实入口POST的状态、耗时和绑定证据。
- [sample-response.json](sample-response.json)：原始样例的离线响应。
- [规则覆盖清单](../CoreGeek/docs/RULE_COVERAGE.md)：R01–R08、D01–D08和新增决策说明。

后续代码变化请重新生成报告，不把当前测量值挪用于新实现。正式平台回放应另外保存平台版本、双方阵营、请求/结果与未覆盖项。
