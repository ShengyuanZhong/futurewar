# 本地验证报告：0.3.2 U形城墙与后排三火箭

日期：2026-09-18。基于用户手动回退的0.3.1，按设计图固定12格U形墙、后排竖排三火箭与P，内侧留一格维修通路，右侧基地水平镜像。图样是用户策略设计，不是官方建造区域核验。

## 结果

| 检查 | 结果 |
|---|---|
| 全部回归 | 86项通过，0失败、0错误，6.472秒 |
| 原图与镜像 | 基地左上角(6,7)时，三炮(5,8)/(5,7)/(5,6)，P(4,7)，12格墙与图一致；右侧绕基地中轴镜像，两种阵营标签均通过 |
| 连续开局反馈 | 两侧均在合成场景第一晚前完成三炮→采12石→12墙，75金币全用于三炮；逐条检查移动/建造目标距离、占用与争抢 |
| 建成后的通路 | 8格内侧维修通路连通，每面墙至少有一个内侧可达相邻格；后方保持开口 |
| 夜间操控 | 两侧均按给定冷却输出A/B/C/等待/A，开拓者留在P，两工人采石；每回合最多一条攻击 |
| 合成观测压力 | 80份，0断言失败；中位20.707ms，最大905.641ms |
| 真实Python入口HTTP | 原样例POST返回200、3条动作、36.768ms；健康检查通过；监听0.0.0.0，默认建造启用 |
| 原样例离线回放 | 成功，保留roleCommandMap/prompt/executeCmd三字段 |
| wheel | 0.3.2构建成功，包内16个Python模块与当前源码逐字节一致 |

## 变更与可复现信息

运行时源码仅修改`CoreGeek/app/config.py`和`CoreGeek/src/agent/construction.py`；另改版本声明和默认布局断言，增加`tests/test_u_layout.py`。与0.3.1机器报告中的源码哈希比较，`brain.py`、`grid.py`、`memory.py`及任务、攻击、动作、HTTP等实现均未改变。五份官方基线/示例文件的SHA256与0.3.1报告一致。

新增图样测试先于实现修改运行：精确墙位在两侧、两阵营下均失败，原布局还使图中位置的工人夜间移开；实现修正后通过。没有放宽碰撞、射程、冷却或单角色动作约束。

执行命令（根目录）：

```powershell
python CoreGeek/tools/validate.py --cases 20 --output reports/validation-v0.3.2.json
python CoreGeek/tools/smoke_server.py --output reports/http-smoke-v0.3.2.json
python CoreGeek/tools/replay.py request.txt --output reports/sample-response-v0.3.2.json
```

在CoreGeek目录构建：

```powershell
python -m pip wheel . --no-build-isolation --no-deps --no-index --wheel-dir dist
```

wheel SHA256：`282002c637f56a80a76567b778498d953e1b7ec804d05166e11552ea233c861e`。

压力种子17、20260917，两阵营各组合20份，夜间0–150个机器人；40份三火箭、40份混合旧炮。环境为Windows Python 3.10.6。机器报告保存源码和规则基线哈希，耗时为本机测量。

## 验证边界

连续反馈仅执行移动、采石和建造，不结算矿点耗尽刷新、机器人战斗、LLM任务和完整比赛，不保证任意地图都能在第一晚前建完。模板所需格不可用时不自动移形，已有旧建筑不搬迁；原0.3.1寻路/复活行为保留。本次未验证官方完整双队回放、实际伤害结算和Linux bash入口，不能作为官方成绩或胜率。

- [机器记录](validation-v0.3.2.json)
- [HTTP记录](http-smoke-v0.3.2.json)
- [样例响应](sample-response-v0.3.2.json)
- [0.3.2安装包](../CoreGeek/dist/coregeek_futurewar-0.3.2-py3-none-any.whl)
- [模板、关键函数与参数](../CoreGeek/docs/U_LAYOUT.md)
- [0.3.1历史报告](VALIDATION-v0.3.1.md)
