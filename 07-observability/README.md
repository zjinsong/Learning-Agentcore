# 第七章：Observability 实践

AgentCore Observability 用于查看 AgentCore 资源指标、Runtime 日志和应用 Trace。

AgentCore Observability 把这些信息送到 CloudWatch。官方入口：[AgentCore Observability](https://docs.amazonaws.cn/bedrock-agentcore/latest/devguide/observability.html)。

## 一、默认已经有什么

AgentCore 会为 Runtime、Gateway 等资源提供一组内置指标。Runtime 常见关注项包括调用量、Session、延迟、Duration、错误和 CPU/Memory 使用量。

这些服务级指标可直接在 CloudWatch GenAI Observability 中查看。

## 二、Metrics、Logs、Trace 分别看什么

| 数据 | 主要用途 |
| --- | --- |
| Metrics | 调用量、错误率、延迟、资源使用情况 |
| Logs | Runtime 输出和具体错误信息 |
| Trace / Span | 一次 Agent 请求内部的模型调用、工具调用和耗时路径 |

常用排查顺序是 Metrics → Trace/Span → Logs。

## 三、ADOT 是什么

ADOT 是 AWS Distro for OpenTelemetry。OpenTelemetry 定义 Trace、Span、Metrics、Logs 等遥测标准；ADOT 是 AWS 提供的 OpenTelemetry 发行版，用来把 Agent 应用产生的 telemetry 接入 AWS 的观测体系。

AgentCore 提供基础资源指标；应用级 Trace/Span 需要 Agent framework 产生 OpenTelemetry telemetry，并启用相应 instrumentation。

## 四、开启完整 Agent 观测

第一步是在 CloudWatch 中启用 Transaction Search。这是查看 AgentCore trace/span 的一次性账户配置。

然后为 Agent 应用启用 instrumentation。对于像本教程这样自己构建容器、自己创建 Runtime 的方式，可以在依赖中加入：

~~~text
aws-opentelemetry-distro>=0.18.0
boto3
~~~

并用 OpenTelemetry instrumentation 启动应用：

~~~dockerfile
CMD ["opentelemetry-instrument", "python", "agent_app.py"]
~~~

如果使用的 Agent framework 需要额外的 OTEL 支持，也要按该 framework 的文档启用。官方完整步骤见：[Add observability to AgentCore resources](https://docs.amazonaws.cn/bedrock-agentcore/latest/devguide/observability-configure.html)。

## 五、实际怎么看

打开 CloudWatch → GenAI Observability，选择对应 Agent/Runtime。

先看调用量、错误、Latency、Duration 等指标；需要分析单次请求时进入 session/trace，查看具体 span 和工具调用；应用自己的 stdout/stderr 则从对应 Runtime log group 查看。

排查路径可以简单记成：

~~~text
Metrics 发现异常
   ↓
找到对应 Session / Trace
   ↓
查看模型和 Tool spans
   ↓
结合 Runtime Logs 定位原因
~~~

以上流程即可覆盖本教程的基础观测需求。

参考：[AgentCore Observability](https://docs.amazonaws.cn/bedrock-agentcore/latest/devguide/observability.html)、[Runtime observability data](https://docs.amazonaws.cn/bedrock-agentcore/latest/devguide/observability-runtime-metrics.html)。


完成观测实践后，进入最后一章：[Cleanup](../08-cleanup/README.md)，统一删除本教程创建的 AWS 资源。
