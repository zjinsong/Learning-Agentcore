"""China-region learning deployment. Execute explicitly; local imports do not deploy."""
import argparse
import json
import os
from pathlib import Path
import time
import uuid

from aws_session import AwsSession
from botocore.config import Config

ROOT = Path(__file__).resolve().parents[2]
STATE = ROOT / ".local" / "runtime.json"
NAME = "tutorial_hello"
ROLE = "tutorial-runtime-role"
REPOSITORY = "agentcore-tutorial-runtime"


def save(value):
    STATE.parent.mkdir(exist_ok=True)
    STATE.write_text(json.dumps(value, indent=2), encoding="utf-8")


def trust(account, region):
    return {"Version": "2012-10-17", "Statement": [{
        "Effect": "Allow", "Principal": {"Service": "bedrock-agentcore.amazonaws.com"},
        "Action": "sts:AssumeRole", "Condition": {
            "StringEquals": {"aws:SourceAccount": account},
            "ArnLike": {"aws:SourceArn": f"arn:aws-cn:bedrock-agentcore:{region}:{account}:runtime/{NAME}-*"},
        },
    }]}


def prepare(session, region):
    if STATE.exists():
        raise RuntimeError("Local runtime state exists. Reuse it or clean up the previous lab first.")
    account = session.client("sts").get_caller_identity()["Account"]
    ecr = session.client("ecr")
    iam = session.client("iam")
    # Names belong to this lab; an existing resource is a conflict, never overwritten.
    repository = ecr.create_repository(repositoryName=REPOSITORY)["repository"]
    state = {"region": region, "repository_uri": repository["repositoryUri"]}
    save(state)
    role = iam.create_role(RoleName=ROLE, AssumeRolePolicyDocument=json.dumps(trust(account, region)))["Role"]
    state["role_arn"] = role["Arn"]
    save(state)
    log_group = f"arn:aws-cn:logs:{region}:{account}:log-group:/aws/bedrock-agentcore/runtimes/{NAME}-*"
    policy = {"Version": "2012-10-17", "Statement": [
        {"Effect": "Allow", "Action": ["ecr:GetAuthorizationToken"], "Resource": "*"},
        {"Effect": "Allow", "Action": ["ecr:BatchGetImage", "ecr:GetDownloadUrlForLayer"], "Resource": repository["repositoryArn"]},
        {"Effect": "Allow", "Action": ["logs:CreateLogGroup", "logs:DescribeLogStreams", "logs:PutResourcePolicy"], "Resource": log_group},
        {"Effect": "Allow", "Action": ["logs:CreateLogStream", "logs:PutLogEvents"], "Resource": log_group + ":log-stream:*"},
        {"Effect": "Allow", "Action": ["logs:DescribeLogGroups"], "Resource": f"arn:aws-cn:logs:{region}:{account}:log-group:*"},
    ]}
    iam.put_role_policy(RoleName=ROLE, PolicyName="tutorial-runtime-base", PolicyDocument=json.dumps(policy))
    print("Prepared ECR and execution role; push the ARM64 image before running create.")


def wait_runtime(client, runtime_id):
    for _ in range(120):
        result = client.get_agent_runtime(agentRuntimeId=runtime_id)
        status = result["status"]
        print("Runtime:", status)
        if status == "READY":
            return result
        if status in {"CREATE_FAILED", "UPDATE_FAILED", "FAILED"}:
            raise RuntimeError(str(result.get("failureReason", status)))
        time.sleep(5)
    raise TimeoutError("Runtime is not READY after 10 minutes; inspect it before retrying.")


def create(session, state):
    if "runtime_id" in state:
        raise RuntimeError("Runtime already recorded. Use status/invoke, not create again.")
    client = session.client("bedrock-agentcore-control")
    result = client.create_agent_runtime(
        agentRuntimeName=NAME,
        agentRuntimeArtifact={"containerConfiguration": {"containerUri": state["repository_uri"] + ":v1"}},
        roleArn=state["role_arn"],
        networkConfiguration={"networkMode": "PUBLIC"},
        protocolConfiguration={"serverProtocol": "HTTP"},
    )
    state.update(runtime_id=result["agentRuntimeId"], runtime_arn=result["agentRuntimeArn"])
    save(state)
    wait_runtime(client, state["runtime_id"])
    print("Runtime is READY. Run invoke to verify the application response.")


def invoke(session, state, prompt, session_id):
    client = session.client("bedrock-agentcore", config=Config(
        connect_timeout=5, read_timeout=90, retries={"total_max_attempts": 1}))
    response = client.invoke_agent_runtime(
        agentRuntimeArn=state["runtime_arn"], qualifier="DEFAULT",
        runtimeSessionId=session_id or str(uuid.uuid4()),
        payload=json.dumps({"prompt": prompt}).encode("utf-8"),
    )
    print(response["response"].read().decode("utf-8"))


def connect(session, state):
    gateway = json.loads((ROOT / ".local" / "gateway.json").read_text(encoding="utf-8"))
    if gateway["region"] != state["region"]:
        raise ValueError("Runtime and Gateway regions must match for this lab.")
    iam = session.client("iam")
    iam.put_role_policy(RoleName=ROLE, PolicyName="learning-invoke-gateway", PolicyDocument=json.dumps({
        "Version": "2012-10-17", "Statement": [{"Effect": "Allow",
        "Action": "bedrock-agentcore:InvokeGateway", "Resource": gateway["gateway_arn"]}],
    }))
    client = session.client("bedrock-agentcore-control")
    result = client.update_agent_runtime(
        agentRuntimeId=state["runtime_id"], roleArn=state["role_arn"],
        agentRuntimeArtifact={"containerConfiguration": {"containerUri": state["repository_uri"] + ":v1"}},
        networkConfiguration={"networkMode": "PUBLIC"},
        protocolConfiguration={"serverProtocol": "HTTP"},
        environmentVariables={"GATEWAY_URL": gateway["gateway_url"], "TOOL_REGION": state["region"]},
    )
    state["runtime_version"] = result["agentRuntimeVersion"]
    save(state)
    wait_runtime(client, state["runtime_id"])
    print("Gateway connected. Invoke with a NEW session to test the updated version.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["prepare", "create", "status", "invoke", "connect"])
    parser.add_argument("--region", default=os.environ.get("AWS_REGION", "cn-northwest-1"))
    parser.add_argument("--prompt", default="hello")
    parser.add_argument("--session-id")
    args = parser.parse_args()
    if args.region not in {"cn-north-1", "cn-northwest-1"}:
        parser.error("This lab supports China regions only.")
    state = None if args.action == "prepare" else json.loads(STATE.read_text(encoding="utf-8"))
    region = args.region if state is None else state["region"]
    session = AwsSession(region_name=region)
    if args.action == "prepare":
        prepare(session, region)
    elif args.action == "create":
        create(session, state)
    elif args.action == "connect":
        connect(session, state)
    elif args.action == "status":
        print(session.client("bedrock-agentcore-control").get_agent_runtime(agentRuntimeId=state["runtime_id"])["status"])
    else:
        invoke(session, state, args.prompt, args.session_id)


if __name__ == "__main__":
    main()
