# 本地验证报告：0.3.1默认启用开局建设

日期：2026-09-18。修复0.3.0默认缺坐标时跳过开局建设的问题。按用户明确要求，基地周围作为可建造区域：内圈选择三座火箭，外圈建墙并留四向通道。此几何布局是本地假设，不标记为官方核验数据；官方文档原件保留。

## 结果

| 检查 | 结果 |
|---|---|
| 全部回归 | 81项通过，0失败、0错误，约4.323秒 |
| 无配置连续回合开局 | challenger、defender均先完成三火箭，随后采石、建墙，并在该合成场景第一晚前观察到完成；75金币全部用于三炮 |
| 默认布局及配置 | 地图边界、中立点过滤、共同操控格、墙通道、旧未核验空配置回退、自定义确认坐标优先通过 |
| 合成观测压力 | 80份，0断言失败；中位20.803ms、最大810.407ms |
| 真实Python入口HTTP | 原样例POST返回200、3条动作、36.759ms；GET健康检查通过；日志确认0.0.0.0及base_surroundings模式，未出现禁建D01提示 |
| 原样例离线回放 | 成功生成roleCommandMap/prompt/executeCmd，不执行LLM或沙盒 |
| wheel构建 | coregeek_futurewar-0.3.1-py3-none-any.whl成功构建，包含app与agent |

执行命令（根目录）：

```powershell
python CoreGeek/tools/validate.py --cases 20 --output reports/validation-v0.3.1.json
python CoreGeek/tools/smoke_server.py --output reports/http-smoke-v0.3.1.json
python CoreGeek/tools/replay.py request.txt --output reports/sample-response-v0.3.1.json
```

wheel在CoreGeek目录通过`python -m pip wheel . --no-build-isolation --no-deps --wheel-dir dist`生成，SHA256：`0573a47b54cdf282be24ed8097ae9f70cd5c0f498538d565b2255caca8d0b347`。

## 新增案例与验证边界

新增6项`tests/test_default_opening.py`案例。修改实现前，默认建造和连续开局测试出现4个失败（含两阵营子测试），复现“没有炮就先采矿”的旧问题；修改后全部通过。HTTP测试也检查默认首轮工人执行建造/前往建造，不提前采矿。

两个阵营的连续测试使用正常75金币、零初始武器/墙、空背包和真实服务默认Settings；按输出逐轮反馈移动、建造与采集。该夹具不结算战斗、矿刷新、LLM任务或完整比赛，不意味着所有地图一定在相同轮次完成。夜间单人操炮、火箭冷却、工人夜采及石头保护仍由既有19项开局策略测试覆盖。

原动作权限、白天建造、25金币成本、石头消耗、三炮上限、冷却与角色互斥保持。仅区域来源增加用户授权默认布局，显式`allow_base_surroundings:false`可恢复仅确认区域模式；相关拒绝案例继续验证。

压力参数仍是种子17、20260917，两阵营各组合20份，夜间0–150个机器人，40份三火箭、40份混合旧炮。环境为Windows Python 3.10.6；机器报告保存源码及官方基线SHA256。本次没有重新获取上游规则，历史报告不覆盖。

尚未验证官方完整双队对局、真实LLM/沙盒、伤害估值与平台结算误差及Linux bash入口。上述测试和耗时均为本地证据，不是官方成绩或胜率。

- [机器报告](validation-v0.3.1.json)
- [HTTP入口记录](http-smoke-v0.3.1.json)
- [原样例响应](sample-response-v0.3.1.json)
- [0.3.1安装包](../CoreGeek/dist/coregeek_futurewar-0.3.1-py3-none-any.whl)
- [默认开局与开发说明](../CoreGeek/docs/OPENING_DEFENSE.md)
- [0.3.0历史报告](VALIDATION-v0.3.0.md)
