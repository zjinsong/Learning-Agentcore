# 3.1 把一个 Python 程序放到 Runtime

先做一个最小程序。你发 `hello`，它返回 `Received: hello`。

它暂时不调用模型。这样，第一步出错时，你只需排查应用和 Runtime，不必同时猜测模型网络、工具权限和数据问题。

## 一、给程序一个入口

普通 Python 函数不会自动变成云端接口。我们使用 AgentCore SDK 提供的应用对象：

```python
from bedrock_agentcore.runtime import BedrockAgentCoreApp
app = BedrockAgentCoreApp()

@app.entrypoint
def handler(event, context):
    prompt = str(event.get("prompt", ""))
    return {"answer": "Received: " + prompt}

if __name__ == "__main__":
    app.run()
```

`event` 是本次请求的内容。`handler` 是入口函数。`@app.entrypoint` 把它注册到应用，`app.run()` 启动服务。

使用 HTTP 模式时，容器监听 `0.0.0.0:8080`，接收 `/invocations` 请求，提供 `/ping` 健康检查。部署镜像需要 ARM64。[HTTP 契约](https://docs.amazonaws.cn/en_us/bedrock-agentcore/latest/devguide/runtime-http-protocol-contract.html)

## 二、先在本地试一下

仓库已附上应用文件，从根目录启动：

```powershell
python -m pip install -r examples/runtime/requirements.txt
python examples/runtime/app.py
```

保持窗口打开，在另一个终端请求：

```powershell
Invoke-RestMethod -Uri http://127.0.0.1:8080/ping
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8080/invocations -ContentType application/json -Body '{"prompt":"hello"}'
```

应该得到健康检查成功，以及含 `Received: hello` 的结果。本地入口能运行，再部署云端。

本例真实代码另外保留了 `check gateway` 分支，供后面的工具接入实验使用。它此时会提示尚未配置 Gateway。

## 三、准备镜像仓库和角色

创建一个中国区 ECR 仓库。ECR 的作用是保存即将运行的镜像：

```python
repository = ecr.create_repository(repositoryName="agentcore-tutorial-runtime")["repository"]
image_uri = repository["repositoryUri"] + ":v1"
```

这里的 `ecr` 是第三章介绍的 botocore 客户端。仓库实际地址由服务返回，包含你的账户和区域，不在教程里写死。

再创建 Runtime execution role。它需要两个部分：信任关系允许 AgentCore 使用它，权限策略允许它拉取指定镜像、写自己的日志。

```python
trust_statement = {
    "Effect": "Allow",
    "Principal": {"Service": "bedrock-agentcore.amazonaws.com"},
    "Action": "sts:AssumeRole",
    "Condition": {
        "StringEquals": {"aws:SourceAccount": account},
        "ArnLike": {"aws:SourceArn": f"arn:aws-cn:bedrock-agentcore:{region}:{account}:runtime/tutorial_hello-*"}
    }
}
```

`account` 从本地 STS 调用取得。中国区资源 ARN 使用 `aws-cn`；服务 Principal 按文档要求填写，不能自行按域名后缀猜测。

把这份信任关系放入策略文档，创建角色：

```python
runtime_role = iam.create_role(
    RoleName="tutorial-runtime-role",
    AssumeRolePolicyDocument=json.dumps({"Version":"2012-10-17", "Statement":[trust_statement]}),
)["Role"]
runtime_role_arn = runtime_role["Arn"]
```

此时角色只允许服务使用，还没有拉镜像的权限。再用 `iam.put_role_policy` 为它添加 ECR 与日志权限，关键范围如下：

| 动作 | 资源范围 |
| --- | --- |
| ecr:GetAuthorizationToken | *，这个动作不支持限定仓库 |
| ecr:BatchGetImage、ecr:GetDownloadUrlForLayer | 刚创建仓库的 repositoryArn |
| logs:CreateLogGroup、logs:DescribeLogStreams、logs:PutResourcePolicy | 本学习 Runtime 的日志组 |
| logs:CreateLogStream、logs:PutLogEvents | 同一日志组下的日志流 |
| logs:DescribeLogGroups | 本账户本区域的日志组 |

准备脚本按上述顺序调用 STS、创建 ECR、创建角色、写角色策略，每创建一个资源就保存它的标识。因此出错后可以知道已经完成到哪一步。[执行角色权限参考](https://docs.amazonaws.cn/en_us/bedrock-agentcore/latest/devguide/runtime-permissions.html)

运行对应的准备步骤：

```powershell
python examples/runtime/deploy.py prepare --region cn-northwest-1
```

它仅准备仓库和角色，不创建 Runtime。结果写入 `.local/runtime.json`。若遇到同名资源或已有记录，先核对，不覆盖别人的资源。

## 四、把程序打包成镜像

Dockerfile 可以理解为打包说明书：从 Python 环境开始，安装依赖，复制代码，然后启动程序。

```dockerfile
FROM public.ecr.aws/docker/library/python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app.py gateway_client.py aws_session.py ./
EXPOSE 8080
CMD ["python", "app.py"]
```

`gateway_client.py` 是后面调用工具的客户端。基础镜像来自公开仓库；下载受限时换成你已批准、可访问的 ARM64 Python 镜像。

读取准备结果，登录 ECR：

```powershell
$lab = Get-Content .local/runtime.json -Raw | ConvertFrom-Json
$registry = $lab.repository_uri.Split('/')[0]
aws ecr get-login-password --region $lab.region | docker login --username AWS --password-stdin $registry
```

构建、检查架构、推送：

```powershell
docker buildx build --platform linux/arm64 --provenance=false --load -t agentcore-tutorial-runtime:v1 examples/runtime
docker image inspect agentcore-tutorial-runtime:v1 --format '{{.Architecture}}'
docker tag agentcore-tutorial-runtime:v1 "$($lab.repository_uri):v1"
docker push "$($lab.repository_uri):v1"
```

检查结果应为 `arm64`，推送完成会显示 digest。到这里，镜像已经上传，但应用还没运行。

## 五、创建 Runtime

现在告诉 AgentCore：使用哪张镜像、哪个角色、什么协议。

```python
result = control.create_agent_runtime(
    agentRuntimeName="tutorial_hello",
    agentRuntimeArtifact={"containerConfiguration": {"containerUri": image_uri}},
    roleArn=runtime_role_arn,
    networkConfiguration={"networkMode": "PUBLIC"},
    protocolConfiguration={"serverProtocol": "HTTP"},
)
```

镜像地址与角色来自前面的步骤。PUBLIC 是本例网络选择，不表示调用免鉴权；入站仍用默认 IAM。企业私网场景需另外设计 VPC 和出站访问。

执行创建步骤：

```powershell
python examples/runtime/deploy.py create
python examples/runtime/deploy.py status
```

程序保存服务返回的 Runtime ID/ARN，并等待 READY。刚创建的 IAM 角色可能有传播延迟，失败时查实际状态与原因，不盲目重复创建。[创建 API](https://docs.aws.amazon.com/botocore/latest/reference/services/bedrock-agentcore-control/client/create_agent_runtime.html)

## 六、创建完成不等于验证完成

READY 表示资源准备就绪。接下来必须发一个真实请求：

```powershell
python examples/runtime/deploy.py invoke --prompt hello
```

预期返回 `Received: hello`。云端请求的结构为什么和本地不同？下一节专门解释。

## 七、遇到错误怎样定位

| 出错位置 | 优先检查 |
| --- | --- |
| 本地启动 | Python 依赖、端口、入口函数 |
| 打包或推送 | 镜像/PyPI 网络、Docker ARM64 支持、ECR 登录 |
| 创建 Runtime | 部署权限、PassRole、角色信任、镜像地址 |
| 调用 403 | 调用者的 Invoke 权限，而不是重新修改镜像 |
| 调用超时或应用异常 | Runtime 日志、程序依赖、请求期限 |

## 最后附上代码

[入口程序](../examples/runtime/app.py)、[Dockerfile](../examples/runtime/Dockerfile)、[依赖](../examples/runtime/requirements.txt)、[分步部署与调用](../examples/runtime/deploy.py)、[botocore 客户端](../examples/runtime/aws_session.py)。

下一节：[怎样调用 Agent](invoke.md)。
