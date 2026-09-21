# 本地验证报告：0.3.3 建筑升级与毁墙补建

日期：2026-09-21。基于用户认可的0.3.2基准，调整购券/用券阶段、墙升级前后顺序、升级优先回血及毁墙补建。基准源码快照与SHA256清单保存在`reports/baselines/`，不覆盖历史报告。

## 结果

| 检查 | 结果 |
|---|---|
| 全部回归 | 103项，0失败、0错误，10.401秒 |
| 第一日限制 | 只购/用武器券；即使基地低血或背包已有其他券也不提前升墙/基地；火箭可继续升3级 |
| 第二日起升级顺序 | 火箭2→墙2→火箭3→墙3→基地；费用不足不采购低优先级券 |
| 墙升级与回血 | 左右基地镜像，按迎敌列由前到后，同列残血优先，升级优先于修复包；失败观测不推进阶段 |
| 完整配送反馈 | 实际TurnService生成单工人买券/移动/用券，确认券序列3武器1、12墙1、3武器2、12墙2、基地1/2；每次墙升级列顺序均为9×6、8×2、7×2、6×2 |
| 并发资源约束 | 已有库存、本轮购买/消耗计数阻止超买；两工人不重复升级同一墙 |
| 毁墙补建 | 零血和从报文移除均识别；有石优先补墙，无石优先采石，夜间不建造且不卖墙材；新一级墙重新纳入升级 |
| 0.3.2基准回归 | U形模板、两侧镜像、P、完整开局顺序及夜间轮换测试继续通过 |
| 合成观测压力 | 80份，0失败；中位20.206ms，最大812.236ms |
| 真实Python入口HTTP | POST原样例返回200、3条动作、22.545ms；健康检查、0.0.0.0监听、默认建造启用均通过 |
| 离线回放 / wheel | 原样例回放成功；0.3.3 wheel构建成功，包内Python模块与源码逐字节相同 |

## 证据与命令

新增17项`test_maintenance.py`测试。首批11项先于实现修改运行，得到11个失败（含阶段子案例），复现低血基地插队、缺墙补建延后、第一天用墙/基地券、背包顺序先修再升级等问题。修复后新旧案例全部通过。旧“第一天买基地券”的测试改为第二天独立购券/用券场景，第一天禁令用新增反例检验。

运行时源码只改`CoreGeek/src/agent/brain.py`；另改版本声明与一项旧策略测试，新增维护测试。通过0.3.2报告源码哈希对比确认`app/config.py`、`construction.py`、`grid.py`、`combat.py`、`actions.py`、服务和记忆层未改。五份官方基线/示例文件SHA256与0.3.2相同。

基准快照保存66个文件，解压前可用清单校验；压缩包SHA256：`e18c26d032954f43a973b330bf9365fc21f87595c32fd360bda485cd4c141d6f`。

根目录执行：

```powershell
python CoreGeek/tools/validate.py --cases 20 --output reports/validation-v0.3.3.json
python CoreGeek/tools/smoke_server.py --output reports/http-smoke-v0.3.3.json
python CoreGeek/tools/replay.py request.txt --output reports/sample-response-v0.3.3.json
```

CoreGeek目录执行：

```powershell
python -m pip wheel . --no-build-isolation --no-deps --no-index --wheel-dir dist
```

wheel SHA256：`3270c9484af81ae6a9169dff9835fb67d3305b23216346a169f68eb1587f18f1`。

## 范围限制

压力沿用种子17、20260917，两阵营各组合20份，夜间0–150机器人，40份三火箭和40份旧混合炮；运行环境Windows Python 3.10.6。机器报告记录源码/规则SHA256与环境。

连续维护反馈夹具只处理白天的配送、升级及少量采集/交易，跳过夜晚战斗。升级后满血由测试输入按任务书更新，Agent本身不结算血量。夹具使用单工人隔离尚未处理的拥堵寻路问题；多工人本轮动作互斥另有独立案例，不宣称完整对局卡位已解决。

满级墙的主动修复包采购不在本次实现范围；仍支持已有修复包库存。无完整双队官方回放、实战收益/存活率、真实LLM/沙盒及Linux比赛入口验证。这些结果仅为本地证据。

- [机器报告](validation-v0.3.3.json)
- [HTTP记录](http-smoke-v0.3.3.json)
- [样例响应](sample-response-v0.3.3.json)
- [开发文档与参数](../CoreGeek/docs/MAINTENANCE.md)
- [0.3.2基准源码](baselines/v0.3.2-source.zip)
- [0.3.2基准清单](baselines/v0.3.2-manifest.json)
- [0.3.2历史验证](VALIDATION-v0.3.2.md)
