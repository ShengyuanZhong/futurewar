# 本地验证报告：0.3.5 自进化任务模块接入

日期：2026-09-21。以0.3.4为基础，接入用户提供的task_prompt.py，增加v2回复适配、跨回合命令证据、业务错误诊断与回合预算。规则编号R01/R07；官方原件、既有防守和工人策略不变。

## 验证结果

| 项目 | 结果 |
|---|---|
| 完整回归 | 140项，0失败、0错误，11.039秒；新增17项任务测试 |
| v2与旧协议 | 命令映射executeCmd、答案字符串原样映射submitAnswer，旧协议仍兼容 |
| 证据历史 | 连续两次命令的实际输出保留；首尾截断、20条/96000字符总限通过 |
| 错误处理 | exitCode=0且API返回401/400、CRLF退出126、FAIL、TIMEOUT、JUDGER_ERROR；失败命令原样重试被拦截 |
| 回合与隔离 | 接取时捕获timeout、缺省15、首轮已有任务、末段提交、切题/空phase重开/跳轮反馈隔离通过 |
| 回复校验 | 歧义字段、非字符串答案、NUL、超长命令、重复JSON键和非有限数值拒绝 |
| 执行边界 | 返回沙盒命令时模拟subprocess.run/os.system若调用即失败；案例通过，日志命令未在主机执行 |
| 原策略回归 | U墙、三火箭、升级次序、避险、批量购券和第三天夜修通过 |
| 合成观测压力 | 80份，0失败；中位21.387ms，最大828.760ms |
| 真实进程HTTP | 原样例POST返回200、3条动作、45.967ms；健康检查、监听与默认建造配置通过 |
| 离线回放 | 原始request.txt成功输出标准三字段响应 |
| 文档样例 | TASK_INTEGRATION.md中JSON及双层编码llmResp/answer通过解析检查 |
| 安装包 | 0.3.5 wheel构建成功，20个Python模块与当前源码逐字节一致，包含task_prompt及task_context，无temp资料依赖 |

首批10项任务测试在实现前运行时为8失败、1错误，复现原版无法处理v2、遗漏旧命令输出、缺少业务诊断及预算控制等问题。之后追加7项边界案例；没有修改既有测试的权限或判定条件。

## 源码及资料完整性

已存0.3.4源码快照，81个文件均与清单哈希一致；压缩包SHA256：`a113a78dff5e266b9f811e67a6ff49c583ab9ed11dc0838e8fa6a23b6563481b`。原0.3.2、0.3.3快照和历史报告继续保留。

原有运行时代码仅修改memory.py、llm_service.py、task_service.py，版本声明改为0.3.5；新增task_prompt.py、task_context.py。`src/agent`全部策略、Settings、HTTP服务、TurnService与入口保持原有源码哈希。规则文件和官方样例的五项哈希与0.3.4报告相同。当前42项源码/配置哈希记录于机器报告。

用户两个输入文件未改动：task_prompt.py SHA256为`61a5d938962f757bc12cc45e0634cfc114cfade47dde938b22e080e6dbebca02`，teamA.log为`3748b64cfaed1df9781fd8f8640e695bb829861fb41c9c80a5d6dcff45e4297c`。正式提示词副本与原件逐字节相同。

最终wheel SHA256：`8983ee5e25512ecee543b5f969b1e5785d05d1ec89a26f3bc48096e6b790951e`。

## 复现

项目根目录：

```powershell
python CoreGeek/tools/validate.py --cases 20 --output reports/validation-v0.3.5.json
python CoreGeek/tools/smoke_server.py --output reports/http-smoke-v0.3.5.json
python CoreGeek/tools/replay.py request.txt --output reports/sample-response-v0.3.5.json
```

CoreGeek目录：

```powershell
python -m pip wheel . --no-build-isolation --no-deps --no-index --wheel-dir dist
```

压力种子17和20260917，两个阵营各20份，40份三火箭、40份兼容混合武器，夜间0–150机器人；环境Windows/Python3.10.6。

## 验证边界

新增回归使用合成任务与反馈，参考了用户日志中的错误形态，但没有把日志认作本版执行结果。没有调用官方LLM、官方沙盒或运行完整双队对局；不宣称任务成功率或得分提高。进程中途启动无法得知已经过去的任务轮数，接口没有任务ID时无法区分无空phase过渡的同文题目。启发式诊断不能覆盖所有API错误；过长历史会裁剪。实际解题与及时提交仍需官方回放验证。

- [机器报告](validation-v0.3.5.json)
- [HTTP记录](http-smoke-v0.3.5.json)
- [原样例响应](sample-response-v0.3.5.json)
- [任务模块开发文档](../CoreGeek/docs/TASK_INTEGRATION.md)
- [0.3.4源码快照](baselines/v0.3.4-source.zip)
- [快照清单](baselines/v0.3.4-manifest.json)
- [0.3.5安装包](../CoreGeek/dist/coregeek_futurewar-0.3.5-py3-none-any.whl)
