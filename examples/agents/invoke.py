"""Invoke one deployed expert with a structured task or a question."""
import argparse
from datetime import datetime, time, timedelta, timezone
import json
from pathlib import Path
import sys
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "runtime"))
from aws_session import AwsSession
from botocore.config import Config


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--expert", choices=["monitoring", "audit"], required=True)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--task", choices=["discover", "metrics", "audit"])
    mode.add_argument("--question")
    parser.add_argument("--instance-id", action="append", default=[])
    args = parser.parse_args()
    path = Path(__file__).resolve().parents[2] / ".local/agents.json"
    state = json.loads(path.read_text(encoding="utf-8"))
    zone = timezone(timedelta(hours=8))
    now = datetime.now(zone)
    start = datetime.combine(now.date(), time.min, tzinfo=zone)
    payload = {"question": args.question} if args.question else {"task": args.task}
    if args.task and args.task != "discover":
        payload.update(start=start.isoformat(), end=now.isoformat())
    if args.task == "metrics":
        if not args.instance_id:
            parser.error("metrics requires --instance-id from discovery")
        payload["instance_ids"] = args.instance_id
    client = AwsSession(state["region"]).client("bedrock-agentcore", config=Config(
        connect_timeout=5, read_timeout=90, retries={"total_max_attempts": 1}))
    result = client.invoke_agent_runtime(agentRuntimeArn=state[args.expert]["runtime_arn"],
        qualifier="DEFAULT", runtimeSessionId=str(uuid.uuid4()),
        payload=json.dumps(payload, ensure_ascii=False).encode("utf-8"))
    print(result["response"].read().decode("utf-8"))


if __name__ == "__main__":
    main()
