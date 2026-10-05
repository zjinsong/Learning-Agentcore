# 第二章：Vibe coding MCP 使用

现在你知道 Runtime 和 Gateway 做什么了。接下来，找一个帮你写程序的助手。

Kiro、Claude Code、Codex 都能协助编码。但一个助手能写 Python，不代表它知道最新的 AgentCore 接口。**MCP 让它可以先查文档，再按文档动手。**

## 一、这个 MCP 装在哪里

Amazon Bedrock AgentCore MCP Server 安装在你的开发环境，由编码助手连接。

```text
你 → 编码助手 → AgentCore MCP → 文档与开发辅助工具
```

官方入门介绍了改造应用、部署和测试的对话流程。实际安装版本提供哪些工具，要在客户端工具列表里查看。部署还需要相应终端或工具、AWS 身份与权限。[AWS MCP 入门](https://docs.amazonaws.cn/en_us/bedrock-agentcore/latest/devguide/mcp-getting-started.html)

不要把它和 Gateway 混起来。这个 MCP 帮开发者构建应用；Gateway 是部署后的 Agent 访问业务工具的入口。

## 二、准备一个能启动 MCP 的命令

配置里的 `uvx` 是启动程序的命令。它由 uv 提供，可以下载并运行 Python 工具包。

按 [uv 安装文档](https://docs.astral.sh/uv/getting-started/installation/) 安装后，在终端检查：

```powershell
uvx --version
```

能看到版本号再继续。首次启动会下载包，需要网络。下面使用 `@latest` 方便入门；验证完成后，可以锁定具体版本。

查文档可以先不设置部署身份。真正部署前，再按第三章设置 AWS 中国区身份。

## 三、Kiro：添加一个配置文件

在项目中创建 `.kiro/settings/mcp.json`。已有文件时，合并 `mcpServers`，不要覆盖别的配置。

```json
{
  "mcpServers": {
    "bedrock-agentcore-mcp-server": {
      "command": "uvx",
      "args": ["awslabs.amazon-bedrock-agentcore-mcp-server@latest"],
      "env": {
        "FASTMCP_LOG_LEVEL": "ERROR",
        "AWS_REGION": "cn-northwest-1",
        "AWS_DEFAULT_REGION": "cn-northwest-1"
      },
      "disabled": false,
      "autoApprove": ["search_agentcore_docs", "fetch_agentcore_doc"]
    }
  }
}
```

这段配置告诉 Kiro：启动 uvx，运行 AgentCore MCP 包，连接它。`autoApprove` 只放文档读取工具，便于先查询资料。命令与工具名依据 [AWS 配置示例](https://docs.amazonaws.cn/en_us/bedrock-agentcore/latest/devguide/mcp-getting-started.html)。

重启或重连 MCP。确认 Server 已连接，并能看到 `search_agentcore_docs`、`fetch_agentcore_doc`。

## 四、Claude Code：用一条命令注册

在终端执行：

```powershell
claude mcp add --scope user --transport stdio --env AWS_REGION=cn-northwest-1 --env FASTMCP_LOG_LEVEL=ERROR bedrock-agentcore-mcp-server -- uvx awslabs.amazon-bedrock-agentcore-mcp-server@latest
claude mcp list
```

这里使用 Claude Code CLI 的配置方法。`--scope user` 表示当前用户可以复用，`--` 后面是启动 MCP 的命令。在 Claude Code 会话中输入 `/mcp` 查看连接。[Claude Code 官方文档](https://code.claude.com/docs/en/mcp)

项目级共享配置使用 `.mcp.json`。不要把 Kiro 的自动批准字段原样复制过来。

## 五、Codex：命令或配置二选一

通过 CLI 注册：

```powershell
codex mcp add bedrock-agentcore-mcp-server --env AWS_REGION=cn-northwest-1 --env FASTMCP_LOG_LEVEL=ERROR -- uvx awslabs.amazon-bedrock-agentcore-mcp-server@latest
codex mcp list
```

也可以编辑用户目录下的 `~/.codex/config.toml`：

```toml
[mcp_servers.bedrock-agentcore-mcp-server]
command = "uvx"
args = ["awslabs.amazon-bedrock-agentcore-mcp-server@latest"]
startup_timeout_sec = 60

[mcp_servers.bedrock-agentcore-mcp-server.env]
AWS_REGION = "cn-northwest-1"
FASTMCP_LOG_LEVEL = "ERROR"
```

重启 Codex，在 CLI 会话中用 `/mcp` 查看活动工具。[OpenAI MCP 文档](https://developers.openai.com/codex/mcp)

AWS 入门没有明确列出 Codex。这里按 Codex 的标准 stdio MCP 接口连接同一个包，是否成功以实际连接测试为准。

## 六、先问一个小问题

配置完成后，不要一上来要求“部署整个系统”。先验证文档工具。

```text
请通过 AgentCore MCP 查阅 Runtime 的 HTTP 协议要求。
告诉我容器架构、端口、请求路径和健康检查路径，并给出处。
不要创建云资源。
```

成功时，你应看到真实的工具调用记录。回答应解释 ARM64、8080、`/invocations`、`/ping`。只有一段看似正确的回答，不能证明 MCP 已经连上。

## 七、让它一步步帮你做

然后按下面三个小任务推进：

**任务一：改造入口。**

```text
请读取第三章的最小应用，解释 BedrockAgentCoreApp、entrypoint 和 app.run()。
把它在本地运行起来，发一个 hello 请求，展示返回结果。
```

**任务二：构建 Runtime。**

```text
按第三章 botocore 步骤在宁夏创建学习 Runtime。
先解释 IAM 角色和 ECR，再构建 ARM64 镜像。
逐步执行，等 READY 后真实调用。账户信息只保存在 .local/。
```

**任务三：添加工具。**

```text
按第三章创建 AWS_IAM Gateway 和 get_learning_status Lambda 工具。
解释每一层权限，列举工具，再从 Runtime 调用它。
```

中国区部署方式以第三章为准，不让助手直接照搬 Global 的 Cognito 或 Managed EC2 示例。MCP 提供帮助，理解步骤和验收仍由你掌握。

## 八、连接失败先看什么

工具没有出现，先看 Server 启动日志。找不到 uvx，就查客户端所在环境的 PATH。GUI 和终端可能使用不同环境；终端能找到命令，不代表图形客户端能找到。

能查文档却部署失败，检查 AWS 身份和权限。文档服务能访问，不代表你有创建云资源的权限。

下一章：[服务构建指南](../03-build/README.md)。
