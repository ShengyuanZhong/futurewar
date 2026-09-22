# v0.3.9 实战日志定位与本地验证

2026-09-22。策略/工程修复，涉及R02移动、R03建筑。保留0.3.8的昼夜统一调度及用户确认的0.3.7策略基准；不改官方规则、布局或升级顺序。

## 实战输入与定位

读取用户提供的`temp/log1.log`与`temp/log2.log`，分别611/903条decision记录。只解析文本，没有执行任何日志命令，原件不修改。源文件指纹、交替区间和行号见[日志分析记录](worker-log-analysis-v0.3.9.json)。

- log2工人20010，第15–80回合：`collect:stone (33,9)`与`move: (31,7)`连续交替。
- log1工人20012，第36–71回合：`build:wall (29,8)`与`move: (28,11)`交替。
- log1工人20010，第522–569回合：`repair_supply (24,19)`与`move: (30,12)`交替。
- 两份日志所有`feedback_failed`与`stalled`均为0。摘要没有完整位置、命令或报文，不能据此声称全部动作已被平台确认成功。

源码冲突：寻路预留炮位与P，却没有预留缺墙格；下一回合`clear_build_cell`将进入缺墙格的角色赶走。循环中的每步都移动，旧“原地不动”计数无法识别。新版本以`movement_reserved`统一正常路线、诊断路线、侧移和清理的预留集合，清理动作明确记作`clear_site`。

新增4个初始回归在修改前全部失败，复现采矿、补货、缺墙位置的路线/清理冲突；修改后通过。采矿重建输入由(30,6)开始，旧版在(30,6)/(31,7)循环，新版第5次决策采矿；补货输入旧版在(29,11)/(30,12)循环，新版第11次决策买到修复包。这是根据日志特征构造的最小测试，不是原比赛完整重放。

另增5项覆盖两侧双人完整建墙、诊断预留一致、往返检测与过期记录、清理任务字段以及服务日志，共9项。旧测试保留未改。

## 最终运行结果

| 检查 | 结果 |
|---|---|
| 完整测试 | 194项，0失败、0错误，15.043秒 |
| 合成观测 | 80份，0失败；种子17/20260917，challenger/defender |
| 压力 | 三火箭40份、混合兼容40份；夜间0–150机器人 |
| 合成耗时 | 中位21.162ms，最大820.365ms |
| 实进程HTTP | 200，3条动作，47.102ms；确认0.0.0.0监听 |
| request.txt原样回放 | 成功保存响应，不执行沙盒命令 |
| 打包 | 0.3.9 wheel，22个Python模块与源码逐字节核验 |

对应[机器报告](validation-v0.3.9.json)、[HTTP记录](http-smoke-v0.3.9.json)及[样例响应](sample-response-v0.3.9.json)。测试中非法JSON产生的`protocol_error`日志属于预期错误用例。

## 源码和基准

0.3.8修改前保存[109文件快照](baselines/v0.3.8-source.zip)和[清单](baselines/v0.3.8-manifest.json)，ZIP SHA256：`4d3b7484edd16e8202e1e175f44c355ba54fb95ed3502278f743e464d17d6759`。用户指定的0.3.7基准仍独立保留。

本轮运行时代码变化仅`brain.py`、`worker_coordinator.py`、`turn_service.py`；新增`test_worker_log_regressions.py`及更新版本号/文档。配置、动作校验、官方协议、危险图、升级策略、维修策略及任务模块不变。机器报告包含48个源码/配置指纹及5个官方规则/样例指纹。

[安装包](../CoreGeek/dist/coregeek_futurewar-0.3.9-py3-none-any.whl) SHA256：`339792bd5c525d149023016fbde835ff1d91b26a0ec4fac208ef1776b6071312`。

新增`worker_motion`日志记录实际position、任务target、最终goal、实际command、上一轮反馈与`oscillating`标记；位置历史最多4项，往返标记仅诊断，不做随机脱困。详细API与排查方法见[开发文档](../CoreGeek/docs/WORKER_PATH_FIX.md)。

## 复现与证据边界

```powershell
python CoreGeek/tools/validate.py --cases 20 --output reports/validation-v0.3.9.json
python CoreGeek/tools/smoke_server.py --output reports/http-smoke-v0.3.9.json
python CoreGeek/tools/replay.py request.txt --output reports/sample-response-v0.3.9.json
```

本轮包括对真实比赛日志的只读分析和修复后的本地重建验证，**未进行修复后的官方实战**，不声明胜率或任意地形无死锁。旧日志缺少完整观测和部署版本，因此不能认定其中每次折返都是同一原因。局部无出口、动态敌人和必要让行仍可能导致等待或短期折返。Linux bash入口、官方LLM/沙盒和完整双队比赛等外部验证未新增。
