"""Two specialist Runtime applications: structured tasks, with optional model planning."""
from datetime import datetime, time, timedelta, timezone
import json
import os

from bedrock_agentcore.runtime import BedrockAgentCoreApp
from gateway_client import GatewayClient
from aws_session import AwsSession
import requests

app = BedrockAgentCoreApp()


def plan(question, kind, region):
    secret_arn = os.environ.get("MODEL_SECRET_ARN")
    if not secret_arn:
        raise ValueError("Natural-language mode requires MODEL_SECRET_ARN; use a structured task first")
    secret = AwsSession(region_name=region).client("secretsmanager").get_secret_value(SecretId=secret_arn)
    config = json.loads(secret["SecretString"])
    zone = timezone(timedelta(hours=8))
    now = datetime.now(zone)
    day_start = datetime.combine(now.date(), time.min, tzinfo=zone)
    instruction = (
        f"You are a {kind} specialist. Return ONLY JSON. "
        "Allowed fields: task, instance_ids, start, end. "
        f"Allowed tasks: {['discover', 'metrics'] if kind == 'monitoring' else ['audit']}. "
        "Metrics requires actual instance IDs supplied by the user; otherwise select discover. "
        "Do not invent resource IDs. start/end must be ISO timestamps with timezone. "
        f"Today in Beijing starts {day_start.isoformat()}, now {now.isoformat()}. "
        "Plan one operation, no shell commands.")
    response = requests.post(config["url"], headers={"Authorization": "Bearer " + config["key"]},
        json={"model": config["model"], "messages": [{"role": "system", "content": instruction},
             {"role": "user", "content": question}]}, timeout=(5, 30))
    response.raise_for_status()
    return json.loads(response.json()["choices"][0]["message"]["content"])


def execute(event, kind, region):
    allowed = {"monitoring": {"discover", "metrics"}, "audit": {"audit"}}
    task = event.get("task")
    if task not in allowed.get(kind, set()):
        raise ValueError("Unsupported task for this specialist")
    args = {"action": task, "region": region}
    if task != "discover":
        args.update(start=event["start"], end=event["end"])
    if task == "metrics":
        args["instance_ids"] = event["instance_ids"]
    gateway = GatewayClient(os.environ["GATEWAY_URL"], region)
    gateway.initialize()
    tool_name = kind + "___cloud_query"
    if tool_name not in {t["name"] for t in gateway.list_tools()}:
        raise RuntimeError("Expected specialist tool is not registered")
    response = gateway.rpc("tools/call", {"name": tool_name, "arguments": args})
    if response.get("isError"):
        raise RuntimeError("Tool execution failed")
    if response.get("structuredContent") is not None:
        return response["structuredContent"]
    contents = response.get("content", [])
    texts = [item["text"] for item in contents if item.get("type") == "text"]
    if len(texts) != 1:
        raise ValueError("Expected one JSON tool result")
    return json.loads(texts[0])


@app.entrypoint
def handler(event, context):
    kind = os.environ.get("EXPERT_KIND", "monitoring")
    region = os.environ.get("TOOL_REGION", "cn-northwest-1")
    if event.get("question"):
        event = plan(event["question"], kind, region)
    result = execute(event, kind, region)
    return {"expert": kind, "status": "succeeded", "result": result}


if __name__ == "__main__":
    app.run()
