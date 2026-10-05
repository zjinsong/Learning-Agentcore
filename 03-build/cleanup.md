# 3.4 实验结束后清理

先删除使用资源的对象，再删除被它使用的资源。下面命令从仓库根目录执行，只针对本教程创建的资源。保留 `.local/` 记录直到清理完成。

## 一、删除 Gateway target，再删除 Gateway

```bash
runtime_region=$(jq -r .region .local/runtime.json)
runtime_id=$(jq -r .runtime_id .local/runtime.json)
gateway_id=$(jq -r .gateway_id .local/gateway.json)
gateway_region=$(jq -r .region .local/gateway.json)
status_target=$(jq -r .target_id .local/gateway.json)
aws bedrock-agentcore-control delete-gateway-target --gateway-identifier "$gateway_id" --target-id "$status_target" --region "$gateway_region"
```

若完成第四章，执行下面完整代码块。它读取第四章状态，再删除两个业务 target、Runtime、Lambda 与镜像：

```bash
agent_region=$(jq -r .region .local/agents.json)
monitoring_target=$(jq -r .monitoring.target_id .local/agents.json)
audit_target=$(jq -r .audit.target_id .local/agents.json)
monitoring_runtime=$(jq -r .monitoring.runtime_id .local/agents.json)
audit_runtime=$(jq -r .audit.runtime_id .local/agents.json)
aws bedrock-agentcore-control delete-gateway-target --gateway-identifier "$gateway_id" --target-id "$monitoring_target" --region "$gateway_region"
aws bedrock-agentcore-control delete-gateway-target --gateway-identifier "$gateway_id" --target-id "$audit_target" --region "$gateway_region"
aws bedrock-agentcore-control delete-agent-runtime --agent-runtime-id "$monitoring_runtime" --region "$agent_region"
aws bedrock-agentcore-control delete-agent-runtime --agent-runtime-id "$audit_runtime" --region "$agent_region"
aws lambda delete-function --function-name tutorial-monitoring-tool --region "$agent_region"
aws lambda delete-function --function-name tutorial-audit-tool --region "$agent_region"
aws ecr delete-repository --repository-name agentcore-tutorial-agents --force --region "$agent_region"
```

若接入工单 API，读取 `.local/ticket-provider.json`，再删除其中 target_id 对应的 target。未创建的资源跳过。

删除可能异步完成。等列表为空，再删 Gateway：

```bash
aws bedrock-agentcore-control list-gateway-targets --gateway-identifier "$gateway_id" --region "$gateway_region"
aws bedrock-agentcore-control delete-gateway --gateway-identifier "$gateway_id" --region "$gateway_region"
```

## 二、删除 Runtime、Lambda 和镜像

第三章资源：

```bash
aws bedrock-agentcore-control delete-agent-runtime --agent-runtime-id "$runtime_id" --region "$runtime_region"
aws lambda delete-function --function-name agentcore-tutorial-status --region "$runtime_region"
```

确认第三章 Runtime 删除完成后，再删它的学习镜像仓库：

```bash
aws ecr delete-repository --repository-name agentcore-tutorial-runtime --force --region "$runtime_region"
```

第四章的 agents 仓库已在前面的可选代码块删除。`--force` 会删除仓库中全部镜像，先保存需要的数据。

## 三、删除 IAM 角色

角色不能带着策略直接删除。先查看策略，再逐项删除。例如：

```bash
aws iam list-role-policies --role-name tutorial-runtime-role
aws iam delete-role-policy --role-name tutorial-runtime-role --policy-name tutorial-runtime-base
aws iam delete-role-policy --role-name tutorial-runtime-role --policy-name learning-invoke-gateway
aws iam delete-role --role-name tutorial-runtime-role
```

未运行 connect 时，第二份策略不存在，跳过。对其他已创建的角色采用相同方法：

| 角色 | 本教程的内联策略 |
| --- | --- |
| tutorial-lambda-role | tutorial-lambda-logs |
| tutorial-gateway-role | tutorial-invoke-lambda、tutorial-two-agents（第四章）、tutorial-ticket-credentials（可选） |
| tutorial-monitoring-lambda | tutorial-read-only |
| tutorial-audit-lambda | tutorial-read-only |
| tutorial-monitoring-runtime | tutorial-runtime、tutorial-model（可选） |
| tutorial-audit-runtime | tutorial-runtime、tutorial-model（可选） |

若自己追加了其他策略，先核对再解除，不照表格批量删除其他角色。

## 四、日志与可选凭证

Lambda 日志组分别为 `/aws/lambda/agentcore-tutorial-status`、`/aws/lambda/tutorial-monitoring-tool`、`/aws/lambda/tutorial-audit-tool`。Runtime 日志组按实际 Runtime ID 命名，检查 ID 后删除：

```bash
aws logs describe-log-groups --log-group-name-prefix /aws/bedrock-agentcore/runtimes/tutorial_ --region "$runtime_region"
aws logs delete-log-group --log-group-name /aws/lambda/agentcore-tutorial-status --region "$runtime_region"
```

可选 Identity Provider：

```bash
aws bedrock-agentcore-control delete-api-key-credential-provider --name tutorial-ticket-key --region "$runtime_region"
```

再核对对应 Secret 是否按服务行为清理。只清理本实验专用 Secret，优先采用可恢复的计划删除。外部系统签发的 Key 需在那个系统撤销；删除 AWS 配置不等于撤销外部权限。

自己创建的模型 Secret 也单独处理。云资源清理完后，再移除本地不需要的实验记录。

返回：[第三章](README.md)。
