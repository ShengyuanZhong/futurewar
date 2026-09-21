# 本地验证报告：0.3.4 工人避险、批量购券与专职夜修

日期：2026-09-21。以0.3.3为基础，增加工人风险寻路、批量购买升级券、第三天起维修工备货/返岗及墙血低于30%时维修。U形模板和升级阶段保持。0.3.3源码另存快照，0.3.2基准和历史报告继续保留。

## 结果

| 项目 | 结果 |
|---|---|
| 完整回归 | 123项通过，0失败、0错误，9.639秒 |
| 避险 | 多步绕行避开3格射程及1格警戒缓冲；矿点可达性包含整条路径风险；受威胁先撤离，无路等待；零血机器人忽略，眩晕仍谨慎避开 |
| 批量购券 | 3座火箭可一次买3券；缺12墙券且全队有3券时买9券；金币、容量、全队库存及同轮采购去重通过 |
| 维修工备货 | 第三天启用，目标5包；支持部分补货、零价格、容量约束和修复包预算预留；选择稳定、死亡接替 |
| 夜修 | 两侧镜像；血量分别<300/<450/<600触发，等于30%不修；进入墙内后沿内侧通路前往远端墙，保持另一工人采矿 |
| 反馈与时机 | 黄昏回岗、无包待命、不修零血/满血墙、日间保留应急库存、失败重试、重复HTTP观测幂等、次日补足库存通过 |
| 既有基准策略 | 原图、开局三炮→采石→12墙、夜间开拓者轮换、火箭2→墙2→火箭3→墙3→基地完整阶段通过 |
| 合成观测压力 | 80份，0断言失败；中位20.918ms，最大817.908ms |
| 真实Python入口HTTP | POST原样例返回200、3条动作、47.382ms；健康检查、0.0.0.0监听、默认建造启用通过 |
| 离线回放 | 原始request.txt成功输出三字段响应 |
| wheel | 0.3.4构建成功，包内18个Python模块与当前源码逐字节相同 |

## 回归设计与源码边界

新增20项`tests/test_worker_safety.py`测试。首批12项在实现修改前运行，得到8失败、1错误，复现原地危险采矿、无风险绕行、单张购买和缺少专职维修等旧行为；完成实现及追加边界测试后全部通过。

旧连续配送夹具现在按`num`反馈购买金币与库存，并预置5个维修包以单独验证升级顺序。三个旧“采矿与开火同时进行”案例把机器人移到工人警戒区外，保留安全采矿断言；危险场景下应撤离由新增案例单独断言。动作权限/碰撞/资源校验未放宽。

运行时修改`brain.py`、`grid.py`、Settings、GameMemory及日志，新增`worker_safety.py`和`wall_guard.py`。模板配置函数本身、`construction.py`、`combat.py`、`actions.py`、协议和任务/LLM逻辑保持。五份官方规则基线/示例的SHA256与0.3.3报告一致；机器报告包含所有当前源码/配置指纹。

0.3.3快照包含72个文件，已逐一核对清单SHA256，压缩包SHA256为`62726ed3d968b11dc67a6984f54f02427e8522158e7bd85734d0a73f76ebcf70`。0.3.4 wheel SHA256为`e7fe4cd04d6f521173eda97a04a24416099e522683343a8152f7a6921c8b440d`。

## 复现命令

项目根目录：

```powershell
python CoreGeek/tools/validate.py --cases 20 --output reports/validation-v0.3.4.json
python CoreGeek/tools/smoke_server.py --output reports/http-smoke-v0.3.4.json
python CoreGeek/tools/replay.py request.txt --output reports/sample-response-v0.3.4.json
```

CoreGeek目录：

```powershell
python -m pip wheel . --no-build-isolation --no-deps --no-index --wheel-dir dist
```

压力种子17、20260917，challenger/defender各组合20份，夜间0–150个机器人；40份三火箭、40份旧混合武器。环境Windows Python 3.10.6。

## 证据边界

局部反馈夹具验证动作顺序、几何可达性、金币/库存计数和维修条件，没有完整模拟机器人攻击、矿刷新或官方双队对局。警戒缓冲和风险权重是本地策略，不是官方伤害公式；没有假定城墙挡住远程攻击。低血墙可能在维修工到达前被摧毁，修复包和单回合动作数有限，不宣称基地绝对安全。

尚未验证官方实战存活率、完整多角色拥堵解除、Linux比赛入口及真实LLM/沙盒集成；历史基准用于可比对实现，不冒充本版官方比赛成绩。

- [机器报告](validation-v0.3.4.json)
- [HTTP记录](http-smoke-v0.3.4.json)
- [原样例响应](sample-response-v0.3.4.json)
- [工人策略开发文档](../CoreGeek/docs/WORKER_SAFETY.md)
- [0.3.3源码快照](baselines/v0.3.3-source.zip)
- [快照清单](baselines/v0.3.3-manifest.json)
- [0.3.4安装包](../CoreGeek/dist/coregeek_futurewar-0.3.4-py3-none-any.whl)
- [0.3.3历史报告](VALIDATION-v0.3.3.md)
