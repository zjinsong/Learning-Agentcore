# 第八章：Cleanup

完成教程后，可以统一删除前面章节创建的持久 AWS 资源。

本章不在中途清理资源，因为第四章会复用第三章创建的 Gateway，第五章还会调用第四章部署的 Agent Runtime。

## 一、清理范围

cleanup.py 根据 .local/ 中保存的资源标识，按依赖关系删除：

- 第三章的基础 Runtime、Gateway、Lambda、ECR 和 IAM roles
- 第四章的 Monitoring/Audit Runtime、Gateway targets、Lambda、ECR 和 IAM roles
- DeepSeek 配置使用的 Secrets Manager secret
- 如果完成 Identity 扩展示例，对应的 Gateway target 和 API Key credential provider
- 教程创建的 Lambda log groups

Code Interpreter 和 Browser 使用的是会话资源，第六章示例在进程退出时会停止 session，不属于这里的持久资源清理。

## 二、执行

先确认当前目录仍保留 .local/runtime.json、.local/gateway.json、.local/agents.json；这些文件用于准确识别教程创建的资源。

在仓库根目录执行：

~~~bash
python 08-cleanup/cleanup.py
~~~

脚本只按本教程固定资源名和 .local/ 中记录的 ARN/ID 删除资源，不扫描或删除其他资源。

## 三、最后检查

清理完成后，可以在对应区域检查 AgentCore Runtime、Gateway、Lambda、ECR、IAM 和 Secrets Manager，确认教程资源已经删除。

如果你额外启用了 Observability、创建了自定义 CloudWatch log group、Dashboard 或其他实验资源，这些不在脚本的固定清单中，需要按实际创建内容删除。
