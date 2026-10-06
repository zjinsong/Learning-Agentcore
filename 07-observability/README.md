# 第七章：Observability 实践

Agent 跑起来之后，至少要回答三个问题：

1. 有没有被调用？
2. 调用是否失败或变慢？
3. 出问题时能不能定位到具体 Runtime、Gateway 或一次请求？

AgentCore 的观测主要依赖 CloudWatch 指标、日志和追踪。学习阶段先从指标开始最容易。

## 一、先看 Runtime 指标

AgentCore Runtime 的指标位于：

```text
AWS/Bedrock-AgentCore
```

常见关注项：

| 指标 | 用途 |
| --- | --- |
| Invocations | Runtime 被调用多少次 |
| SystemErrors | 服务端错误 |
| UserErrors | 应用或请求错误 |
| Throttles | 是否发生限流 |
| Latency | 请求延迟 |
| Duration | Runtime 执行时长 |
| CPUUsed-vCPUHours | CPU 使用量 |
| MemoryUsed-GBHours | 内存使用量 |

不同指标的维度可能不同，所以不要直接猜 `RuntimeId`、`Name` 等维度。

更可靠的方法是：**先用 Runtime ARN 发现实际 metrics，再读取 datapoint。**

## 二、先发现指标和维度

例如：

```python
import boto3

region = "cn-northwest-1"
cloudwatch = boto3.client("cloudwatch", region_name=region)

runtime_arn = "your-runtime-arn"

response = cloudwatch.list_metrics(
    Namespace="AWS/Bedrock-AgentCore",
    MetricName="Invocations",
    Dimensions=[
        {"Name": "Resource", "Value": runtime_arn}
    ],
)

for metric in response.get("Metrics", []):
    print(metric["MetricName"])
    print(metric["Dimensions"])
```

这一步很重要。

不要这样写：

```text
假设维度一定是 RuntimeId
```

应该以 `list_metrics` 返回的真实维度为准。

## 三、读取最近一小时指标

拿到完整维度后：

```python
from datetime import datetime, timedelta, timezone

end = datetime.now(timezone.utc)
start = end - timedelta(hours=1)

dimensions = response["Metrics"][0]["Dimensions"]

points = cloudwatch.get_metric_statistics(
    Namespace="AWS/Bedrock-AgentCore",
    MetricName="Invocations",
    Dimensions=dimensions,
    StartTime=start,
    EndTime=end,
    Period=60,
    Statistics=["Sum"],
)

for point in sorted(points.get("Datapoints", []), key=lambda x: x["Timestamp"]):
    print(point["Timestamp"], point["Sum"])
```

对于计数指标通常看 `Sum`：

```text
Invocations
SystemErrors
UserErrors
Throttles
```

Latency 和 Duration 更适合先看 `Average`，需要进一步分析时再看更细粒度统计。

## 四、不要把空数据当作 0

CloudWatch 返回：

```json
{
  "Datapoints": []
}
```

只表示当前查询窗口没有返回 datapoint。

它可能意味着：

- Runtime 没有被调用
- 指标尚未上报
- 查询维度不对
- 时间窗口不对
- 指标存在延迟

所以 UI 或程序应该显示：

```text
暂无数据
```

而不是：

```text
0 次调用
```

这是观测系统里很重要的区别。

## 五、做一个简单 Runtime 观测函数

可以把发现和查询封装起来：

```python
def find_dimensions(cloudwatch, runtime_arn, metric_name):
    response = cloudwatch.list_metrics(
        Namespace="AWS/Bedrock-AgentCore",
        MetricName=metric_name,
        Dimensions=[{"Name": "Resource", "Value": runtime_arn}],
    )
    metrics = response.get("Metrics", [])
    if not metrics:
        return None

    metrics.sort(
        key=lambda item: len(item.get("Dimensions", [])),
        reverse=True,
    )
    return metrics[0]["Dimensions"]


def read_metric(cloudwatch, runtime_arn, metric_name, start, end):
    dimensions = find_dimensions(
        cloudwatch,
        runtime_arn,
        metric_name,
    )
    if not dimensions:
        return []

    statistic = (
        "Sum"
        if metric_name in {
            "Invocations",
            "SystemErrors",
            "UserErrors",
            "Throttles",
        }
        else "Average"
    )

    response = cloudwatch.get_metric_statistics(
        Namespace="AWS/Bedrock-AgentCore",
        MetricName=metric_name,
        Dimensions=dimensions,
        StartTime=start,
        EndTime=end,
        Period=60,
        Statistics=[statistic],
    )

    return sorted(
        response.get("Datapoints", []),
        key=lambda point: point["Timestamp"],
    )
```

然后：

```python
metrics = [
    "Invocations",
    "SystemErrors",
    "UserErrors",
    "Throttles",
    "Latency",
    "Duration",
]

for metric_name in metrics:
    points = read_metric(
        cloudwatch,
        runtime_arn,
        metric_name,
        start,
        end,
    )
    print(metric_name, points)
```

## 六、多 Agent 怎么做

不要在观测页面里写死：

```text
monitoring
audit
finops
...
```

更好的方式是维护一个 Agent registry：

```python
agents = [
    {
        "name": "monitoring",
        "runtime_arn": "...",
    },
    {
        "name": "audit",
        "runtime_arn": "...",
    },
]
```

观测代码遍历 registry：

```python
for agent in agents:
    arn = agent["runtime_arn"]

    invocations = read_metric(
        cloudwatch,
        arn,
        "Invocations",
        start,
        end,
    )

    print(agent["name"], invocations)
```

以后增加新 Agent，只要注册 Runtime ARN，观测页面自然会出现新卡片，不需要再改页面代码。

## 七、Gateway 也要单独看

多个 Agent 可能共用一个 Gateway，所以 Gateway 指标不要重复放到每个 Agent 卡片里。

可以单独展示：

```text
Gateway

Invocations
SystemErrors
UserErrors
Throttles
Latency
Duration
TargetExecutionTime
```

Gateway 指标同样应先通过 `list_metrics` 看真实维度。

如果只有一个 Gateway，可以先做整体概览。

如果以后有多个 Gateway，就应该按实际 Gateway resource 进行过滤，不要混在一起。

## 八、一个简单观测页面

学习项目可以先做成：

```text
Agent Observability
────────────────────────────────────

Agents     Invocations     Errors     Avg Latency
  4            126            2          850 ms

Runtime
────────────────────────────────────
Monitoring Agent
Invocations  50
Errors        0
Latency     620 ms

Audit Agent
Invocations  32
Errors        1
Latency     910 ms

...

Shared Gateway
────────────────────────────────────
Invocations  210
Errors         1
Latency      120 ms
```

常用时间窗口：

```text
1h
6h
24h
7d
```

页面每分钟刷新一次已经足够做学习和 Demo。

## 九、什么时候需要日志和 Trace

指标适合回答：

```text
有没有问题？
什么时候开始变慢？
错误率有没有上升？
```

日志和 Trace 更适合回答：

```text
为什么失败？
具体哪一次调用失败？
Agent 调用了哪个工具？
耗时在哪一步？
```

因此实际排查通常是：

```text
Metrics
   ↓
发现异常 Runtime
   ↓
Logs / Trace
   ↓
定位具体请求和工具调用
```

不要一开始就把所有 Trace 做成复杂平台。先把 Runtime 和 Gateway 的核心指标看清楚，再增加日志和追踪。

## 十、实践原则

1. 以 Runtime ARN 为资源标识，不猜维度。
2. 先 `list_metrics`，再查询数据。
3. 空 datapoint 不等于 0。
4. 多 Agent 从 registry 动态枚举。
5. Gateway 单独观测，不重复塞进每个 Agent。
6. 指标用于发现问题，日志和 Trace 用于解释问题。
7. CPU 和 Memory 属于资源使用量指标，不要把它们当作 CPU 百分比或内存百分比。

做到这些，就已经有一个足够实用的 AgentCore 基础观测方案。
