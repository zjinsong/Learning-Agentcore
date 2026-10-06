# 第四章：构建一个完整 Agent

第三章已经验证了 Runtime → Gateway → Lambda 工具链。这一章保留第三章创建的 Gateway，并部署新的 Agent Runtime，在此基础上加入模型和 Agent loop。

示例仍然很小：监控 Agent 查询 EC2/CloudWatch，审计 Agent 查询 CloudTrail。两个 Agent 都运行在 AgentCore Runtime，模型使用 DeepSeek，工具来自第三章介绍的 AgentCore Gateway。

~~~mermaid
flowchart LR
    U[用户自然语言] --> R[AgentCore Runtime]
    R --> A[Agent]
    A <--> M[DeepSeek]
    A <--> G[AgentCore Gateway]
    G --> T[Lambda MCP Tool]
    T --> W[AWS API]
~~~

## 一、这一章增加了什么

第三章的重点是基础设施：Runtime 怎么部署，Gateway 怎么注册 target，MCP 工具怎么调用。

这一章的重点是 Agent：

1. 用 DeepSeek 作为模型。
2. 用 Strands 创建 Agent。
3. 把 Gateway 返回的 MCP tools 交给 Agent。
4. 让 Agent 根据自然语言决定什么时候调用工具、调用几次，再根据真实结果回答。

因此不再使用“模型先生成 JSON，再由 Python if/else 执行”的手写流程。

## 二、代码结构

完整代码在 examples/agents：

~~~text
examples/agents/
├── agent_app.py
├── gateway_tools.py
├── configure_model.py
├── build.py
├── invoke.py
├── tools.py
├── aws_session.py
├── Dockerfile
└── requirements.txt
~~~

agent_app.py 是 Runtime 中真正运行的 Agent。gateway_tools.py 负责用 IAM/SigV4 连接 Gateway，并把 MCP tools 加载成 Strands 可以直接使用的工具。

核心调用链：

~~~python
model = OpenAIModel(
    client_args={
        "api_key": config["key"],
        "base_url": "https://api.deepseek.com",
    },
    model_id=config.get("model", "deepseek-v4-pro"),
)

with gateway_tools(gateway_url, region, kind) as tools:
    agent = Agent(
        model=model,
        tools=tools,
        system_prompt=PROMPTS[kind],
    )
    answer = agent(question)
~~~

`OpenAIModel` 用于 OpenAI-compatible API。DeepSeek 通过 `base_url`、API Key 和 `model_id` 配置。

模型配置方法参考：[Using any foundation model](https://docs.amazonaws.cn/bedrock-agentcore/latest/devguide/using-any-model.html)。

## 三、工具仍然走 Gateway

监控和审计工具沿用第三章的 Gateway 思路，只是本章增加两个 target：

| Agent | Gateway target | 能做什么 |
| --- | --- | --- |
| monitoring | monitoring | discover、metrics |
| audit | audit | audit |

模型不会直接获得 AWS 凭证去查询 EC2、CloudWatch 或 CloudTrail。它只能调用分配给自己的 Gateway tool；Lambda 再按自己的 IAM role 查询 AWS API。

例如用户问：

~~~text
检查当前运行中的 EC2，并看看 CPU 情况。
~~~

监控 Agent 可以先调用 discover，取得真实实例 ID，再调用 metrics。这个多步过程由 Agent loop 完成，不需要 Python 预先写死调用顺序。

## 四、部署两个工具和两个 Runtime

先完成第三章，确保 .local/gateway.json 已存在，并且学习 Gateway 可用。

然后：

~~~bash
python -m pip install -r examples/agents/requirements.txt

python examples/agents/build.py lambda
python examples/agents/build.py roles
~~~

构建并上传 Runtime 镜像：

~~~bash
agent_image_uri=$(jq -r .repository_uri .local/agents.json)
agent_region=$(jq -r .region .local/agents.json)
registry=${agent_image_uri%%/*}

aws ecr get-login-password --region "$agent_region" | docker login --username AWS --password-stdin "$registry"
docker buildx build --platform linux/arm64 --provenance=false --load -t tutorial-agents:v1 examples/agents
docker tag tutorial-agents:v1 "${agent_image_uri}:v1"
docker push "${agent_image_uri}:v1"

python examples/agents/build.py runtimes
~~~

两个 Runtime 复用同一个镜像，通过 EXPERT_KIND 区分 monitoring 和 audit。

## 五、配置 DeepSeek

模型 API Key 不写入仓库或镜像。运行：

~~~bash
python examples/agents/configure_model.py
~~~

脚本会安全读取 DeepSeek API Key，默认模型是 deepseek-v4-pro，把配置保存到本实验专用 Secrets Manager Secret，并只给两个 Runtime role 读取该 Secret 的权限。

Runtime 中最终得到的模型配置类似：

~~~python
OpenAIModel(
    client_args={
        "api_key": key,
        "base_url": "https://api.deepseek.com",
    },
    model_id="deepseek-v4-pro",
)
~~~

AgentCore Runtime 负责托管 Agent；模型仍由 Agent 应用自己配置。

## 六、直接用自然语言测试

监控：

~~~bash
python examples/agents/invoke.py   --expert monitoring   --question "找出当前运行中的 EC2，并查询它们今天的 CPU 情况"
~~~

审计：

~~~bash
python examples/agents/invoke.py   --expert audit   --question "查询今天是否有人发起过 EC2 StopInstances"
~~~

调用链应该是：

~~~text
invoke.py
  → AgentCore Runtime
  → Strands Agent
  → DeepSeek 判断是否需要工具
  → AgentCore Gateway
  → Lambda MCP Tool
  → AWS API
  → 工具结果返回 Agent
  → DeepSeek 组织最终回答
~~~

这才是本章要验证的完整 Agent 行为。

## 七、Identity 放在哪里

上面的 AWS 工具使用 IAM，不需要额外 API Key Provider。

如果 Agent 还要通过 Gateway 调用一个使用 API Key 的外部系统，再加入 AgentCore Identity。完整例子见 [Identity：接入外部工单服务](identity.md)。

Identity 解决外部凭证管理，不负责模型选择，也不代替 Runtime 或 Gateway 的 IAM 权限。

## 八、这一章学到了什么

第三章完成 Runtime、Gateway 和工具链验证；第四章复用 Gateway，部署新的 Agent Runtime，并加入模型和 Agent loop。

关键边界是：模型负责理解和决策，Agent loop 负责模型与工具之间的循环，Gateway 提供受控工具，AWS 数据仍由工具用真实 API 查询。

下一章：[Harness 实践](../05-harness/README.md)。
