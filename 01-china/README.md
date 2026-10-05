# 第一章：AWS 中国区功能介绍

很多教程先画一张很大的架构图，读者还没开始，就遇到十几个名词。

我们换一种方式。只问一个问题：**一个助手怎样替你查服务器？**

## 一、先把请求走一遍

你发送一句话：“看看服务器的 CPU。”

程序先把问题交给模型。模型决定调用监控工具。工具从 CloudWatch 取回数据。模型读完数据，再组织回答。

```text
提问 → 应用 → 模型选择工具 → 工具查数据 → 应用整理回答
```

这条路径里，模型不是唯一的工作者。程序、工具、权限和数据都必须存在。

## 二、Runtime：让程序有地方运行

在电脑上，你用 `python app.py` 启动程序。关闭电脑，别人就不能继续访问它。

Runtime 提供云端运行环境。你上传程序或容器，通过服务接口向它发请求。它启动运行环境，执行入口函数，返回结果。

Runtime 可以运行使用不同框架和模型的应用。它不会看到一个普通 Python 函数，就自动替你生成模型逻辑。

中国区支持 Runtime，但容量提供方式限于 MicroVM。本教程使用容器部署，不依赖 Global 的 Managed EC2 容量提供方。[中国区差异](https://docs.amazonaws.cn/en_us/aws/latest/userguide/bedrock-agentcore.html)

## 三、Gateway：让工具有统一入口

工具是什么？其实就是能做一件具体事情的函数。

例如：`list_instances` 列出实例，`query_cpu` 查 CPU，`lookup_stop_events` 查关机事件。

这些函数可以放在 Lambda，也可以由已有 API 提供。Gateway 将它们描述成统一的 MCP 工具，供 Agent 发现和调用。

```text
Agent → Gateway → Lambda / API
```

MCP 是工具交互协议。你先列举工具，看到名字、用途和参数；然后按参数调用。Gateway 不负责替你写查询 CPU 的业务代码。

中国区没有 Gateway 语义工具搜索，但正常列举和调用工具不受影响。开始时使用明确的工具清单就可以。

## 四、Identity：访问外部系统时，凭证放在哪里

假设助手还要读取企业工单。工单 API 要求一个 API Key。

你可以自行管理它，也可以让 Identity 保存凭证，由获准的应用或 Gateway 获取并使用。Identity 还支持 OAuth 相关凭证管理和 Agent 工作负载身份。

已有企业 SSO 不一定需要替换。SSO 常解决用户登录；外部系统的凭证管理是另一件事。如果你的现有方案已经覆盖两者，就按需要决定是否使用 Identity。[Identity 概览](https://docs.amazonaws.cn/en_us/bedrock-agentcore/latest/devguide/identity.html)

| 方向 | 谁访问谁 | 这里如何处理 |
| --- | --- | --- |
| 入站 | 你的应用访问 Runtime / Gateway | IAM 签名，或按配置校验 JWT |
| 出站 | Agent / Gateway 访问外部 API | IAM、OAuth token、API Key，按目标要求选择 |

Identity 的 API Key Provider 是管理外部服务凭证的配置，不是让客户拿 API Key 直接调用 Runtime 的入站开关。中国区 Gateway 入站使用 AWS_IAM 或 CUSTOM_JWT；Runtime 支持 IAM/SigV4 或 JWT。[Runtime 鉴权](https://docs.amazonaws.cn/en_us/bedrock-agentcore/latest/devguide/runtime-oauth.html)

## 五、另外三个组件

**Observability** 帮你看执行过程。你需要知道请求耗时、工具返回了什么错误、模型调用在哪一步。它与 CloudWatch 等观测能力配合，应用仍须按需要记录和配置追踪。

**Browser** 提供托管浏览器会话。只有必须点击网页、填写表单等任务才需要它。已有稳定 API 时，可以直接调用 API。

**Code Interpreter** 提供隔离执行环境。比如把查询得到的数据交给 Python，计算平均值，再生成图表。它与负责运行整个应用的 Runtime 分工不同。

## 六、Global 与中国区的差异

北京是 `cn-north-1`，宁夏是 `cn-northwest-1`。中国区不是只修改 Global 示例里的 region，ARN 分区和某些服务配置也不同。

| 能力 | 中国区情况 | 实际影响 |
| --- | --- | --- |
| Runtime / Gateway / Identity / Observability / Browser / Code Interpreter | 可用 | 可构建基本 Agent 应用链路 |
| Memory | 未提供 | 自己保存会话和摘要 |
| Harness | 未提供 | 自己实现执行控制逻辑 |
| Registry | 未提供 | 自己维护能力清单 |
| Policy | 未提供 | 组合 IAM 与应用、工具限制 |
| Knowledge Bases | 未提供 | 选择可用的检索系统 |
| Evaluations / Optimizations | 未提供 | 自建测试问题和评测记录 |
| Payments | 未提供 | 本教程不依赖 |

以上“未提供”指 AgentCore 平台的对应能力，不是 AWS 其他产品的所有同名功能。

可用组件内部也有差异。读到 Global 示例时，对照这张表：

| Global 示例中的选项 | 中国区情况 | 如何处理 |
| --- | --- | --- |
| Runtime Managed EC2 | 不可用 | 使用 MicroVM；不要把托管 EC2 与自己运行 Agent 的 EC2 混淆 |
| Runtime / Tools 的 S3 Files 挂载 | 不可用 | 应用按需通过 S3 API 读写，再处理本地临时文件 |
| Cognito 入站登录快速配置 | 不支持 | 用 IAM，或可信企业 OIDC IdP 与 CUSTOM_JWT |
| Identity Private IdP | 不支持 | 核对 IdP 网络与受支持配置；不能仅改名称假装是支持的 Provider |
| GitHub、Google、Facebook、X、Reddit、Twitch、Dropbox、CyberArk 内置 OAuth Provider | 不提供 | 目标兼容时评估 Custom OAuth 配置；网络可达与目标授权仍要验证 |
| Browser / Tools Web Bot Auth Signer | 不提供 | 优先用目标 API，或目标允许的正常网页认证流程 |
| Gateway 语义工具搜索 | 不提供 | tools/list，加应用维护的能力清单与路由 |
| Gateway 无鉴权入站 | 不提供 | 所有 Gateway 选 IAM 或 CUSTOM_JWT |
| Gateway inference target | 不提供 | Agent 代码直接调用可访问的模型接口 |
| 控制台 connector catalog | 不提供 | 按真实 API 手动定义 OpenAPI / MCP / Lambda target |
| Gateway WAF 集成 | 不提供 | 在自建应用入口设置防护；Gateway 本身仍强制鉴权，防止绕过入口 |
| Gateway rules、ConfigBundle A/B | 不提供 | 应用做校验、路由与分流，分别验证两个版本 |

文档首页部分 Console / GitHub / boto3 快捷入口也缺失，可以直接访问对应文档与 API 参考。功能会变化，完整清单以 [官方中国区差异页](https://docs.amazonaws.cn/en_us/aws/latest/userguide/bedrock-agentcore.html) 为准。

## 七、缺失能力如何替代

替代不是立刻造一个“完整平台”。先解决应用当前需要的问题。

如果你只想记住几轮对话，可以先保存会话记录；需要跨任务恢复时，再设计数据库。如果只有两个 Agent，一个 JSON 配置文件就能记录能力，无需先搭大型注册系统。

| 需求 | 可以从什么开始 | 成长后的选择 |
| --- | --- | --- |
| 保存历史 | 本地学习文件 | 按用户隔离的 DynamoDB / S3，设计保留期限 |
| 发现专家 | 配置中的名字、能力和 Runtime ARN | 数据库、版本、健康检查 |
| 控制权限 | 最小 IAM 权限、工具参数校验 | 多租户授权、细粒度策略与审计 |
| 执行多步任务 | Python 工作流 | 任务数据库、队列、恢复与总期限 |
| 文档检索 | 文档 MCP 或已有检索 API | 按权限建设应用 RAG |
| 评测 | 固定问题与预期行为 | 持续评测、质量和成本统计 |

这也是第五章 Harness 的出发点：先让一个任务可靠完成，再逐步完善。

下一章：[Vibe coding MCP 使用](../02-mcp/README.md)。
