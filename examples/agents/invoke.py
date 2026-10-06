"""Invoke one deployed tutorial agent with a natural-language question."""
import argparse
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
    parser.add_argument("--question", required=True)
    args = parser.parse_args()

    path = Path(__file__).resolve().parents[2] / ".local/agents.json"
    state = json.loads(path.read_text(encoding="utf-8"))
    client = AwsSession(state["region"]).client(
        "bedrock-agentcore",
        config=Config(connect_timeout=5, read_timeout=120, retries={"total_max_attempts": 1}),
    )
    result = client.invoke_agent_runtime(
        agentRuntimeArn=state[args.expert]["runtime_arn"],
        qualifier="DEFAULT",
        runtimeSessionId=str(uuid.uuid4()),
        payload=json.dumps({"question": args.question}, ensure_ascii=False).encode("utf-8"),
    )
    print(result["response"].read().decode("utf-8"))


if __name__ == "__main__":
    main()
