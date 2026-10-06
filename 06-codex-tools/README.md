# 第六章：Code Interpreter + Browser - Codex 实践

这一章把 AgentCore Code Interpreter 和 Browser 暴露成一个本地 MCP server，让 Codex CLI 直接把它们当工具使用。

完整代码已经放在本章目录：

~~~text
06-codex-tools/
└── example/
    ├── mcp_server.py
    ├── requirements.txt
    └── AGENTS.md
~~~

mcp_server.py 可以直接运行，不需要把示例代码从文章里重新拼起来。

## 一、整体关系

~~~mermaid
flowchart LR
    U[用户] --> C[Codex CLI]
    C --> M[本地 MCP server]
    M --> I[AgentCore Code Interpreter]
    M --> B[AgentCore Browser]
~~~

Codex 负责理解任务和决定调用哪个工具。Code Interpreter 提供隔离代码执行环境，Browser 提供托管浏览器会话。

## 二、安装

在仓库根目录执行：

~~~bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -r 06-codex-tools/example/requirements.txt
playwright install chromium
~~~

配置 AWS 中国区身份和区域：

~~~bash
export AWS_REGION=cn-northwest-1
aws sts get-caller-identity --region cn-northwest-1
~~~

示例默认使用 AgentCore 内置标识：

~~~text
aws.codeinterpreter.v1
aws.browser.v1
~~~

如需指定 Code Interpreter 标识，可以设置 AGENTCORE_CODE_INTERPRETER_ID。

## 三、先直接运行 MCP server

~~~bash
python 06-codex-tools/example/mcp_server.py
~~~

这是 stdio MCP server，启动后等待 MCP 客户端连接，因此终端没有普通 Web 服务的监听提示是正常的。

代码第一次收到 sandbox 工具调用时才创建 Code Interpreter session；第一次收到 browser 工具调用时才创建 Browser session。后续调用复用同一个 session。

进程退出时会尝试停止两个 session。

## 四、接入 Codex CLI

Codex CLI 和 IDE 扩展共用 MCP 配置。可以在 ~/.codex/config.toml 中加入：

~~~toml
[mcp_servers.agentcore_tools]
command = "python"
args = ["/absolute/path/Learning-Agentcore/06-codex-tools/example/mcp_server.py"]

[mcp_servers.agentcore_tools.env]
AWS_REGION = "cn-northwest-1"
~~~

把路径换成你的仓库绝对路径，然后检查：

~~~bash
codex mcp list
~~~

Codex 应能看到 agentcore_tools MCP server。

Codex MCP 配置参考：[OpenAI MCP 文档](https://developers.openai.com/learn/docs-mcp)。

## 五、Code Interpreter 部分做了什么

mcp_server.py 暴露两个工具：

~~~text
sandbox_python
sandbox_command
~~~

sandbox_python 最终调用：

~~~python
dp.invoke_code_interpreter(
    codeInterpreterIdentifier=CODE_ID,
    sessionId=code_session(),
    name="executeCode",
    arguments={"language": "python", "code": code, "clearContext": False},
)
~~~

sandbox_command 使用同一个 session 调 executeCommand。

因此可以让 Codex：

~~~text
使用 sandbox_python 生成 1000 个随机数，计算均值和 P95。
~~~

连续工具调用会复用 session，前一次创建的临时文件和执行上下文可以继续使用。

官方直接调用方式参考：[Using AgentCore Code Interpreter directly](https://docs.amazonaws.cn/bedrock-agentcore/latest/devguide/code-interpreter-using-directly.html)。

## 六、Browser 部分做了什么

示例使用 AgentCore BrowserClient 创建托管 Browser session，再通过 Playwright CDP 连接该 session。

提供的工具是：

~~~text
browser_navigate
browser_text
browser_click
browser_fill
browser_screenshot
~~~

例如：

~~~text
使用 browser_navigate 打开 AWS 中国 AgentCore 页面，
再用 browser_text 读取页面主要内容。
~~~

Browser 不是运行在本机 Chrome 中。Playwright 只是通过 CDP 控制 AgentCore Browser session。

官方方式参考：[Managing Browser Sessions](https://docs.amazonaws.cn/bedrock-agentcore/latest/devguide/browser-managing-sessions.html)。

## 七、为什么保持持续 session

如果每个 MCP tool call 都重新创建 session，前后步骤无法共享状态，而且会增加启动开销。

所以示例采用：

~~~text
Codex process
  ├─ one Code Interpreter session
  └─ one Browser session
~~~

session 的最长时间仍受 AgentCore 服务限制。这个示例适合学习和单用户实践；生产环境还需要考虑用户隔离、并发、超时、持久文件和权限边界。

## 八、验证

先让 Codex 做两个简单任务：

~~~text
用 sandbox_python 计算 21 * 2。
~~~

~~~text
用 browser_navigate 打开 https://www.amazonaws.cn/agentcore/，
然后读取页面标题和正文前 1000 个字符。
~~~

如果 Codex 能看到 MCP tools、Code Interpreter 返回 42、Browser 能返回页面内容，整条链路就已经跑通。

下一章：[Observability 实践](../07-observability/README.md)。
