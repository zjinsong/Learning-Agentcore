"""Two small Strands agents hosted by AgentCore Runtime and using Gateway MCP tools."""
import json
import os

from bedrock_agentcore.runtime import BedrockAgentCoreApp
from strands import Agent
from strands.models.openai import OpenAIModel

from aws_session import AwsSession
from gateway_client import GatewayClient
from gateway_tools import gateway_tools

app = BedrockAgentCoreApp()

PROMPTS = {
    "monitoring": (
        "You are a read-only monitoring agent for AWS China. "
        "Use only the monitoring Gateway tool. Discover real running instances before querying metrics "
        "when the user did not provide instance IDs. Never invent resource IDs or metric values."
    ),
    "audit": (
        "You are a read-only audit agent for AWS China. "
        "Use only the audit Gateway tool to inspect CloudTrail StopInstances events. "
        "Distinguish failed API requests from successful requests and never invent events."
    ),
}


def build_model(region):
    secret_arn = os.environ.get("MODEL_SECRET_ARN")
    if not secret_arn:
        raise RuntimeError("MODEL_SECRET_ARN is not configured; run configure_model.py first")
    secret = AwsSession(region_name=region).client("secretsmanager").get_secret_value(
        SecretId=secret_arn
    )
    config = json.loads(secret["SecretString"])
    return OpenAIModel(
        client_args={
            "api_key": config["key"],
            "base_url": config.get("base_url", "https://api.deepseek.com"),
            "timeout": 60,
        },
        model_id=config.get("model", "deepseek-v4-pro"),
        params={"temperature": 0.2, "max_tokens": 2048},
    )


def execute_structured(event, kind, region):
    allowed = {"monitoring": {"discover", "metrics"}, "audit": {"audit"}}
    task = event.get("task")
    if task not in allowed.get(kind, set()):
        raise ValueError("Unsupported task for this specialist")
    arguments = {"action": task, "region": region}
    if task != "discover":
        arguments.update(start=event["start"], end=event["end"])
    if task == "metrics":
        arguments["instance_ids"] = event["instance_ids"]

    gateway = GatewayClient(os.environ["GATEWAY_URL"], region)
    gateway.initialize()
    tool_name = kind + "___cloud_query"
    if tool_name not in {tool["name"] for tool in gateway.list_tools()}:
        raise RuntimeError("Expected specialist tool is not registered")
    response = gateway.rpc("tools/call", {"name": tool_name, "arguments": arguments})
    if response.get("isError"):
        raise RuntimeError("Tool execution failed")
    if response.get("structuredContent") is not None:
        return response["structuredContent"]
    texts = [item["text"] for item in response.get("content", []) if item.get("type") == "text"]
    if len(texts) != 1:
        raise ValueError("Expected one JSON tool result")
    return json.loads(texts[0])


@app.entrypoint
def handler(event, context=None):
    kind = os.environ.get("EXPERT_KIND", "monitoring")
    region = os.environ.get("TOOL_REGION", "cn-northwest-1")
    if kind not in PROMPTS:
        return {"error": "unsupported expert kind"}

    if event.get("task"):
        result = execute_structured(event, kind, region)
        return {"expert": kind, "status": "succeeded", "result": result}

    question = event.get("question") or event.get("prompt")
    if not question:
        return {"error": "question, prompt or task is required"}

    with gateway_tools(os.environ["GATEWAY_URL"], region, kind) as tools:
        if not tools:
            raise RuntimeError(f"No Gateway tools loaded for {kind}")
        agent = Agent(
            model=build_model(region),
            tools=tools,
            system_prompt=PROMPTS[kind],
        )
        answer = str(agent(question))
    return {"expert": kind, "status": "succeeded", "answer": answer}


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
