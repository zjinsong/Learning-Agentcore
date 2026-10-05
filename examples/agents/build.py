"""Follow chapter 4: lambda -> roles -> image build/push -> runtimes."""
import argparse
import io
import json
from pathlib import Path
import sys
import time
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "runtime"))
from aws_session import AwsSession
from deploy import wait_runtime

ROOT = Path(__file__).resolve().parents[2]
STATE = ROOT / ".local" / "agents.json"


def save(state):
    STATE.parent.mkdir(exist_ok=True)
    STATE.write_text(json.dumps(state, indent=2), encoding="utf-8")


def policy(statements):
    return json.dumps({"Version": "2012-10-17", "Statement": statements})


def allow(actions, resource):
    return {"Effect": "Allow", "Action": actions, "Resource": resource}


def trust(service, account, source):
    statement = {"Effect": "Allow", "Principal": {"Service": service}, "Action": "sts:AssumeRole"}
    if source:
        statement["Condition"] = {"StringEquals": {"aws:SourceAccount": account}, "ArnLike": {"aws:SourceArn": source}}
    return json.dumps({"Version": "2012-10-17", "Statement": [statement]})


def schema(kind):
    return [{"name": "cloud_query", "description": f"Read-only {kind} query",
        "inputSchema": {"type": "object", "properties": {
            "action": {"type": "string", "description": "discover or metrics" if kind == "monitoring" else "audit"},
            "region": {"type": "string", "description": "The tool's deployed China region"},
            "instance_ids": {"type": "array", "items": {"type": "string"}},
            "start": {"type": "string"}, "end": {"type": "string"}},
        "required": ["action", "region"]}}]


def lambdas(session, state, gateway, account):
    iam, lam, logs, cp = (session.client(s) for s in ("iam", "lambda", "logs", "bedrock-agentcore-control"))
    region = state["region"]
    for kind in ("monitoring", "audit"):
        record = state.setdefault(kind, {})
        if record:
            raise RuntimeError(f"Existing {kind} resources: inspect state instead of repeating creation")
        name = f"tutorial-{kind}-tool"
        role_name = f"tutorial-{kind}-lambda"
        role = iam.create_role(RoleName=role_name, AssumeRolePolicyDocument=trust("lambda.amazonaws.com", account, None))["Role"]["Arn"]
        record["lambda_role"] = role
        save(state)
        log_name = f"/aws/lambda/{name}"
        logs.create_log_group(logGroupName=log_name)
        logs.put_retention_policy(logGroupName=log_name, retentionInDays=7)
        statements = [allow(["logs:CreateLogStream", "logs:PutLogEvents"], f"arn:aws-cn:logs:{region}:{account}:log-group:{log_name}:*")]
        actions = ["ec2:DescribeInstances", "cloudwatch:GetMetricStatistics"] if kind == "monitoring" else ["cloudtrail:LookupEvents"]
        read_statement = allow(actions, "*")
        read_statement["Condition"] = {"StringEquals": {"aws:RequestedRegion": region}}
        statements.append(read_statement)
        iam.put_role_policy(RoleName=role_name, PolicyName="tutorial-read-only", PolicyDocument=policy(statements))
        archive = io.BytesIO()
        with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as package:
            package.write(Path(__file__).with_name("tools.py"), "tools.py")
        for attempt in range(12):
            try:
                result = lam.create_function(FunctionName=name, Runtime="python3.12", Role=role,
                    Handler="tools.handler", Code={"ZipFile": archive.getvalue()}, Timeout=30, MemorySize=256,
                    Environment={"Variables": {"TOOL_KIND": kind, "TOOL_REGION": region}})
                break
            except lam.exceptions.InvalidParameterValueException as error:
                if "cannot be assumed" not in str(error) or attempt == 11:
                    raise
                time.sleep(5)
        record["lambda_arn"] = result["FunctionArn"]
        save(state)
        lam.get_waiter("function_active_v2").wait(FunctionName=name)
    # Separate policy name; preserve the original introductory Lambda permission.
    iam.put_role_policy(RoleName=gateway["gateway_role_arn"].split("/")[-1], PolicyName="tutorial-two-agents",
        PolicyDocument=policy([allow("lambda:InvokeFunction", [state[k]["lambda_arn"] for k in ("monitoring", "audit")])]))
    time.sleep(10)
    for kind in ("monitoring", "audit"):
        target = cp.create_gateway_target(gatewayIdentifier=gateway["gateway_id"], name=kind,
            targetConfiguration={"mcp": {"lambda": {"lambdaArn": state[kind]["lambda_arn"], "toolSchema": {"inlinePayload": schema(kind)}}}},
            credentialProviderConfigurations=[{"credentialProviderType": "GATEWAY_IAM_ROLE"}])
        state[kind]["target_id"] = target["targetId"]
        save(state)
        for _ in range(120):
            result = cp.get_gateway_target(gatewayIdentifier=gateway["gateway_id"], targetId=target["targetId"])
            if result["status"] == "READY":
                break
            if result["status"] in {"FAILED", "CREATE_FAILED"}:
                raise RuntimeError(str(result.get("statusReasons")))
            time.sleep(5)
        else:
            raise TimeoutError("Target not READY")


def roles(session, state, gateway, account):
    if "repository_uri" in state:
        raise RuntimeError("Agent roles/repository already recorded")
    region = state["region"]
    repository = session.client("ecr").create_repository(repositoryName="agentcore-tutorial-agents")["repository"]
    state["repository_uri"] = repository["repositoryUri"]
    save(state)
    iam = session.client("iam")
    for kind in ("monitoring", "audit"):
        name = f"tutorial-{kind}-runtime"
        source = f"arn:aws-cn:bedrock-agentcore:{region}:{account}:runtime/tutorial_{kind}-*"
        role = iam.create_role(RoleName=name, AssumeRolePolicyDocument=trust("bedrock-agentcore.amazonaws.com", account, source))["Role"]["Arn"]
        state.setdefault(kind, {})["runtime_role"] = role
        save(state)
        log = f"arn:aws-cn:logs:{region}:{account}:log-group:/aws/bedrock-agentcore/runtimes/tutorial_{kind}-*"
        iam.put_role_policy(RoleName=name, PolicyName="tutorial-runtime", PolicyDocument=policy([
            allow("ecr:GetAuthorizationToken", "*"),
            allow(["ecr:BatchGetImage", "ecr:GetDownloadUrlForLayer"], repository["repositoryArn"]),
            allow(["logs:CreateLogGroup", "logs:DescribeLogStreams", "logs:PutResourcePolicy"], log),
            allow(["logs:CreateLogStream", "logs:PutLogEvents"], log + ":log-stream:*"),
            allow("logs:DescribeLogGroups", f"arn:aws-cn:logs:{region}:{account}:log-group:*"),
            allow("bedrock-agentcore:InvokeGateway", gateway["gateway_arn"]),
        ]))


def runtimes(session, state, gateway):
    cp = session.client("bedrock-agentcore-control")
    for kind in ("monitoring", "audit"):
        if state[kind].get("runtime_id"):
            raise RuntimeError("Runtime already recorded; inspect rather than recreate")
        response = cp.create_agent_runtime(agentRuntimeName=f"tutorial_{kind}",
            agentRuntimeArtifact={"containerConfiguration": {"containerUri": state["repository_uri"] + ":v1"}},
            roleArn=state[kind]["runtime_role"], networkConfiguration={"networkMode": "PUBLIC"},
            protocolConfiguration={"serverProtocol": "HTTP"},
            environmentVariables={"EXPERT_KIND": kind, "TOOL_REGION": state["region"], "GATEWAY_URL": gateway["gateway_url"]})
        state[kind].update(runtime_id=response["agentRuntimeId"], runtime_arn=response["agentRuntimeArn"])
        save(state)
        wait_runtime(cp, response["agentRuntimeId"])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("step", choices=["lambda", "roles", "runtimes"])
    args = parser.parse_args()
    gateway = json.loads((ROOT / ".local/gateway.json").read_text(encoding="utf-8"))
    region = gateway["region"]
    if region not in {"cn-north-1", "cn-northwest-1"}:
        parser.error("China region required")
    state = json.loads(STATE.read_text(encoding="utf-8")) if STATE.exists() else {"region": region}
    if state["region"] != region:
        raise ValueError("State region mismatch")
    save(state)
    session = AwsSession(region_name=region)
    account = session.client("sts").get_caller_identity()["Account"]
    if args.step == "lambda":
        lambdas(session, state, gateway, account)
    elif args.step == "roles":
        roles(session, state, gateway, account)
    else:
        runtimes(session, state, gateway)
    print("Completed step:", args.step)


if __name__ == "__main__":
    main()
