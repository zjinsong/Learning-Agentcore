# 4.1 用 Identity 管理外部工单 API Key

设想你有一个工单 API。它允许查询工单，但要求请求头中携带 `X-API-Key`。

Key 由工单系统签发，不由 AgentCore 生成。Identity 保存这个凭证，Gateway 在调用工具时使用它。

## 一、先确认真的需要它

若目标只接受 IAM，就使用 IAM。若目标接受 OAuth，就按 OAuth 流程。这里为了讲清楚，选择 API Key。

你需要自己提供：可访问的 HTTPS API 地址、有效 Key、准确的接口描述。这不是 AWS 内置的免费工单服务。

## 二、创建 API Key Provider

下面从本地安全输入中取得 Key，不把它写进脚本：

```python
from getpass import getpass
key = getpass("请输入工单系统 API Key：")
provider = control.create_api_key_credential_provider(
    name="tutorial-ticket-key",
    apiKey=key,
)
provider_arn = provider["credentialProviderArn"]
```

Provider 是“保存及引用这份凭证的配置”。返回的是引用标识，不能拿这个 ARN 代替真正的 Key 发给工单系统。

底层使用 botocore 创建 control 客户端，和第三章一样。创建过程需要 Identity、相关 Secrets Manager / KMS 配置权限；角色需要的具体权限按对应加密和凭证配置限定。[凭证 Provider 文档](https://docs.amazonaws.cn/en_us/bedrock-agentcore/latest/devguide/resource-providers.html)

## 三、把外部 API 描述成工具

准备 OpenAPI 文件，写明服务器地址、查询路径和参数。比如 `GET /tickets/{ticket_id}`。下面地址只是示意，必须换成你拥有的接口：

```yaml
openapi: 3.0.3
info:
  title: Ticket lookup
  version: '1.0'
servers:
  - url: https://tickets.example.com
paths:
  /tickets/{ticket_id}:
    get:
      operationId: get_ticket
      description: Read one ticket
      parameters:
        - name: ticket_id
          in: path
          required: true
          schema:
            type: string
      responses:
        '200':
          description: Ticket data
          content:
            application/json:
              schema:
                type: object
                properties:
                  ticket_id:
                    type: string
                  status:
                    type: string
```

Gateway 用这个文件知道如何把工具调用转换成 HTTP 请求。模型只需传 ticket_id，不负责拼认证头。

## 四、先给 Gateway 获取凭证的权限

本教程手动创建 Gateway role，也要手动追加凭证权限。在创建 Provider 后，使用返回的两个 ARN。`region`、`account` 使用本地区域与 STS 返回的账户。

```python
base = f"arn:aws-cn:bedrock-agentcore:{region}:{account}"
statements = [
    {"Effect": "Allow", "Action": "bedrock-agentcore:GetWorkloadAccessToken",
     "Resource": [base + ":workload-identity-directory/default",
                  base + ":workload-identity-directory/default/workload-identity/tutorial-gateway-*"]},
    {"Effect": "Allow", "Action": "bedrock-agentcore:GetResourceApiKey",
     "Resource": provider["credentialProviderArn"]},
    {"Effect": "Allow", "Action": "secretsmanager:GetSecretValue",
     "Resource": provider["apiKeySecretArn"]},
]
iam.put_role_policy(
    RoleName="tutorial-gateway-role", PolicyName="tutorial-ticket-credentials",
    PolicyDocument=json.dumps({"Version":"2012-10-17", "Statement":statements}),
)
```

第一项允许 Gateway 取得自己的工作负载令牌；第二项允许引用指定 Key Provider；第三项允许读取指定 Secret。使用自定义 KMS 密钥时，还要按对应配置补充解密权限与密钥策略。[出站 API Key 权限步骤](https://docs.amazonaws.cn/en_us/bedrock-agentcore/latest/devguide/gateway-outbound-auth.html)

## 五、注册 target 时引用凭证

```python
target = control.create_gateway_target(
    gatewayIdentifier=gateway_id,
    name="tickets",
    targetConfiguration={"mcp": {"openApiSchema": {"inlinePayload": openapi_text}}},
    credentialProviderConfigurations=[{
        "credentialProviderType": "API_KEY",
        "credentialProvider": {"apiKeyCredentialProvider": {
            "providerArn": provider_arn,
            "credentialLocation": "HEADER",
            "credentialParameterName": "X-API-Key",
        }},
    }],
)
```

Gateway service role 必须有权获取对应凭证，以及按配置读取相关 Secret / 使用 KMS。将范围限定到此 Provider 和它实际使用的资源，不把读取所有 Secret 的权限给整个团队。[出站凭证配置](https://docs.amazonaws.cn/en_us/bedrock-agentcore/latest/devguide/gateway-building-adding-targets-authorization.html)

若 Gateway 入站仍为 AWS_IAM，Agent 继续用 IAM 签名调用 Gateway。外部 API Key 是下一跳的凭证，两者没有冲突。

## 六、实际检查什么

把前面的 OpenAPI 内容保存为 `.local/tickets.yaml`，替换为你自己的 API 地址；然后执行：

```powershell
python examples/agents/identity_setup.py
```

按提示输入文件路径和 Key。它按本节顺序创建 Provider、追加 Gateway role 策略、注册 target。自定义 KMS 配置需要按前述说明调整角色。

先独立确认外部 API 接口能访问，再等 target READY。从 tools/list 取得实际名字，以一个学习工单 ID 调用。

例如在 Python 中使用第三章的 GatewayClient，先列举，再调用。`gateway_url` 使用 `.local/gateway.json` 中的值，名字以实际返回为准：

```python
client = GatewayClient(gateway_url, "cn-northwest-1")
client.initialize()
print(client.list_tools())
result = client.rpc("tools/call", {
    "name": "tickets___get_ticket",
    "arguments": {"ticket_id": "TUTORIAL-1"},
})
```

成功时，Agent 看到工单结果；Key 应由 Gateway 在下一跳使用，不在 Agent 答复、日志或工具结果里返回。失败时分清 Gateway 鉴权、凭证获取和外部 API 403，三者不是同一个错误。

通过 Gateway 使用 Identity，不额外收取 Identity 的凭证请求费；Gateway 和外部服务自身费用仍适用。[中国区定价](https://www.amazonaws.cn/agentcore/pricing/)

## 七、已有 SSO 怎么办

企业 SSO 可以继续管理用户登录。这个 Key 是外部工单接口的访问凭证，通常对应一个服务身份；不会自动变成每个登录用户的工单权限。

需要“以用户自己的身份访问”时，应按外部系统的 OAuth 授权、scope 和用户绑定方案设计。Key 足够的场景用 Key，现有凭证管理足够的场景也不必再引入 Identity。

最后参考：[API Key 与 OpenAPI 配置片段](../examples/agents/identity_setup.py)。此文件需要真实外部 API，教程不默认部署它。
