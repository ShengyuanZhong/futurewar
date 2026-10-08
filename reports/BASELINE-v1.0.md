# v1.0 比赛程序封版记录

封版日期：2026-10-08。用户已确认当前版本作为 **v1.0**；版本字段在 `CoreGeek/pyproject.toml` 声明为 `1.0`。封版前 Git HEAD 为 `5da6424`（`task update`）。本次只改版本元数据和开发文档，未改动参赛决策源码；`32_docs/` 为用户新加入的复赛参考原件。

源码指纹：按相对路径排序，把 `CoreGeek/app/**/*.py` 与 `CoreGeek/src/agent/**/*.py` 的路径和原始内容（以 NUL 分隔）串联后计算 SHA-256，26 个文件为 `342bb893375aabf1abfdd2c95ad9d21f22763c6fe1baf7be6782f32d117087a5`。本次本地回归 **222 项通过、0 失败**，80份合成观测通过；原样初赛 `request.txt` 的 HTTP 调用返回200。机器结果见[回归与源码哈希](validation-v1.0.json)、[HTTP冒烟](http-smoke-v1.0.json)、[离线响应](sample-response-v1.0.json)。该测试集基于初赛规则和本地夹具；没有运行官方复赛对局。

32进16规则资料： [需求变更](../32_docs/2026云核心网第十届编程大赛-32进16-需求变更.md)、[v2.0任务书](../32_docs/任务书.md)、[v2.0接口文档](../32_docs/接口文档.md)、[新版请求](../32_docs/request.txt)、[新版响应目录](../32_docs/response.txt)。来源、适用顺序、已知差异与未实现范围见[复赛规则接入索引](../CoreGeek/docs/ROUND_OF_32_RULES.md)。只把新版样例输入当前程序时，它能返回响应，但不会控制新增捣乱鬼；该现象不是复赛功能通过验证。

提供资料的 SHA-256（用于后续判断原件是否变化）：

| 文件 | SHA-256 |
|---|---|
| `32_docs/2026云核心网第十届编程大赛-32进16-需求变更.md` | `492322e2cf30c2856dd8041fa1e90a4f2fb961d51a0a696afb2b3d72d903b6f8` |
| `32_docs/任务书.md` | `7fed95c68721d81708d36b63c8a3f10cb56432dc1ff598043c95b773e6d5a7db` |
| `32_docs/接口文档.md` | `0115208871b49d313e2b5bf7d24b6a2e1f35fb6e9f0c20b40b207f364ee7b217` |
| `32_docs/request.txt` | `b2fbf8b5176b27a119e760f2a8b83271d0c6ec2b4f0927e605c34e74d66c2c08` |
| `32_docs/response.txt` | `44dbbce580311962063ed9a26cb3882f013b8eaed29aa777fcae7e56e3460dcb` |

历史本地测试和合成观测见[v0.4.3验证报告](VALIDATION-v0.4.3.md)。后续复赛适配应从 v1.0 单独推进，并对真实官方判题结果重新取证。
