"""Store a DeepSeek API key for the tutorial and attach it to both Runtime roles."""
from getpass import getpass
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "runtime"))
from aws_session import AwsSession
from deploy import wait_runtime


def main():
    path = Path(__file__).resolve().parents[2] / ".local/agents.json"
    state = json.loads(path.read_text(encoding="utf-8"))
    if state.get("model_secret_arn"):
        raise RuntimeError("Model secret already recorded; inspect before changing")

    model = input("DeepSeek model [deepseek-chat]: ").strip() or "deepseek-chat"
    key = getpass("DeepSeek API key: ")
    if not key:
        raise ValueError("API key required")

    session = AwsSession(region_name=state["region"])
    secret = session.client("secretsmanager").create_secret(
        Name="tutorial-agent-model",
        SecretString=json.dumps({
            "base_url": "https://api.deepseek.com",
            "model": model,
            "key": key,
        }),
    )
    state["model_secret_arn"] = secret["ARN"]
    path.write_text(json.dumps(state, indent=2), encoding="utf-8")

    cp = session.client("bedrock-agentcore-control")
    for kind in ("monitoring", "audit"):
        role = state[kind]["runtime_role"].split("/")[-1]
        session.client("iam").put_role_policy(
            RoleName=role,
            PolicyName="tutorial-model",
            PolicyDocument=json.dumps({
                "Version": "2012-10-17",
                "Statement": [{
                    "Effect": "Allow",
                    "Action": "secretsmanager:GetSecretValue",
                    "Resource": secret["ARN"],
                }],
            }),
        )
        current = cp.get_agent_runtime(agentRuntimeId=state[kind]["runtime_id"])
        env = dict(current.get("environmentVariables", {}))
        env["MODEL_SECRET_ARN"] = secret["ARN"]
        cp.update_agent_runtime(
            agentRuntimeId=state[kind]["runtime_id"],
            agentRuntimeArtifact=current["agentRuntimeArtifact"],
            roleArn=current["roleArn"],
            networkConfiguration=current["networkConfiguration"],
            protocolConfiguration=current["protocolConfiguration"],
            environmentVariables=env,
        )
        wait_runtime(cp, state[kind]["runtime_id"])

    print("DeepSeek configured. Start a new Runtime session for the next test.")


if __name__ == "__main__":
    main()
