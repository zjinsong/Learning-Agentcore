# 第八章：Cleanup

本章删除教程创建的持久 AWS 资源。

## 一、资源范围

cleanup.py 根据 .local/ 中保存的资源标识，按依赖关系删除：

- 第三章的基础 Runtime、Gateway、Lambda、ECR 和 IAM roles
- 第四章的 Monitoring/Audit Runtime、Gateway targets、Lambda、ECR 和 IAM roles
- DeepSeek 配置使用的 Secrets Manager secret
- 如果完成 Identity 扩展示例，对应的 Gateway target 和 API Key credential provider
- 教程创建的 Lambda log groups

第六章的 Code Interpreter 和 Browser 为会话资源，示例进程退出时会停止 session，不在本脚本清理范围内。

## 二、执行

保留 `.local/runtime.json`、`.local/gateway.json` 和 `.local/agents.json`；脚本使用其中的资源标识执行删除。

在仓库根目录执行：

~~~bash
python 08-cleanup/cleanup.py
~~~

脚本仅删除教程固定资源名和 `.local/` 中记录的 ARN/ID，不扫描其他资源。

## 三、验证

清理完成后，可以在对应区域检查 AgentCore Runtime、Gateway、Lambda、ECR、IAM 和 Secrets Manager，确认教程资源已经删除。

如果你额外启用了 Observability、创建了自定义 CloudWatch log group、Dashboard 或其他实验资源，这些不在脚本的固定清单中，需要按实际创建内容删除。
