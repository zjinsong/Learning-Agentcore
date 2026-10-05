"""Create an isolated, same-account Gateway/Lambda learning lab in AWS China."""
import io
import json
from pathlib import Path
import time
import zipfile

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "runtime"))
from aws_session import AwsSession

ROOT = Path(__file__).resolve().parents[2]
STATE = ROOT / ".local" / "gateway.json"
FUNCTION = "agentcore-tutorial-status"


def save(state):
    STATE.parent.mkdir(exist_ok=True)
    STATE.write_text(json.dumps(state, indent=2), encoding="utf-8")


def wait(client, operation, params):
    for _ in range(120):
        result = getattr(client, operation)(**params)
        status = result["status"]
        print(operation, status)
        if status == "READY":
            return result
        if status in {"FAILED", "CREATE_FAILED", "UPDATE_FAILED"}:
            raise RuntimeError(str(result.get("statusReasons", status)))
        time.sleep(5)
    raise TimeoutError("Resource not READY; inspect status before retrying.")


def main():
    if STATE.exists():
        raise RuntimeError("Gateway state already exists; inspect it rather than creating duplicates.")
    runtime = json.loads((ROOT / ".local" / "runtime.json").read_text(encoding="utf-8"))
    region = runtime["region"]
    if region not in {"cn-north-1", "cn-northwest-1"}:
        raise ValueError("China region required.")
    session = AwsSession(region_name=region)
    account = session.client("sts").get_caller_identity()["Account"]
    iam, lam, control = (session.client(s) for s in ("iam", "lambda", "bedrock-agentcore-control"))
    state = {"region": region}
    save(state)
    lambda_trust = {"Version": "2012-10-17", "Statement": [{"Effect": "Allow",
        "Principal": {"Service": "lambda.amazonaws.com"}, "Action": "sts:AssumeRole"}]}
    lambda_role = iam.create_role(RoleName="tutorial-lambda-role", AssumeRolePolicyDocument=json.dumps(lambda_trust))["Role"]["Arn"]
    state["lambda_role_arn"] = lambda_role
    save(state)
    iam.put_role_policy(RoleName="tutorial-lambda-role", PolicyName="tutorial-lambda-logs", PolicyDocument=json.dumps({
        "Version": "2012-10-17", "Statement": [{"Effect": "Allow",
        "Action": ["logs:CreateLogStream", "logs:PutLogEvents"],
        "Resource": f"arn:aws-cn:logs:{region}:{account}:log-group:/aws/lambda/{FUNCTION}:*"}],
    }))
    session.client("logs").create_log_group(logGroupName=f"/aws/lambda/{FUNCTION}")
    session.client("logs").put_retention_policy(logGroupName=f"/aws/lambda/{FUNCTION}", retentionInDays=7)
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as package:
        package.write(Path(__file__).with_name("handler.py"), "handler.py")
    for attempt in range(12):
        try:
            result = lam.create_function(FunctionName=FUNCTION, Runtime="python3.12", Role=lambda_role,
                Handler="handler.handler", Code={"ZipFile": archive.getvalue()}, Timeout=30, MemorySize=128)
            break
        except lam.exceptions.InvalidParameterValueException as error:
            if "cannot be assumed" not in str(error) or attempt == 11:
                raise
            time.sleep(5)
    state["lambda_arn"] = result["FunctionArn"]
    save(state)
    lam.get_waiter("function_active_v2").wait(FunctionName=FUNCTION)
    gateway_trust = {"Version": "2012-10-17", "Statement": [{"Effect": "Allow",
        "Principal": {"Service": "bedrock-agentcore.amazonaws.com"}, "Action": "sts:AssumeRole",
        "Condition": {"StringEquals": {"aws:SourceAccount": account},
        "ArnLike": {"aws:SourceArn": f"arn:aws-cn:bedrock-agentcore:{region}:{account}:gateway/*"}}}]}
    gateway_role = iam.create_role(RoleName="tutorial-gateway-role", AssumeRolePolicyDocument=json.dumps(gateway_trust))["Role"]["Arn"]
    state["gateway_role_arn"] = gateway_role
    save(state)
    iam.put_role_policy(RoleName="tutorial-gateway-role", PolicyName="tutorial-invoke-lambda", PolicyDocument=json.dumps({
        "Version": "2012-10-17", "Statement": [{"Effect": "Allow", "Action": "lambda:InvokeFunction", "Resource": state["lambda_arn"]}],
    }))
    time.sleep(10)  # IAM propagation; a failed create is retained for inspection.
    result = control.create_gateway(name="tutorial-gateway", roleArn=gateway_role,
        protocolType="MCP", authorizerType="AWS_IAM")
    state.update(gateway_id=result["gatewayId"], gateway_arn=result["gatewayArn"], gateway_url=result["gatewayUrl"])
    save(state)
    wait(control, "get_gateway", {"gatewayIdentifier": state["gateway_id"]})
    gateway_trust["Statement"][0]["Condition"]["ArnLike"]["aws:SourceArn"] = state["gateway_arn"]
    iam.update_assume_role_policy(RoleName="tutorial-gateway-role", PolicyDocument=json.dumps(gateway_trust))
    result = control.create_gateway_target(gatewayIdentifier=state["gateway_id"], name="tutorial-status",
        targetConfiguration={"mcp": {"lambda": {"lambdaArn": state["lambda_arn"],
            "toolSchema": {"inlinePayload": [{"name": "get_learning_status", "description": "Check Gateway to Lambda connectivity",
                "inputSchema": {"type": "object", "properties": {}, "required": []}}]}}}},
        credentialProviderConfigurations=[{"credentialProviderType": "GATEWAY_IAM_ROLE"}])
    state["target_id"] = result["targetId"]
    save(state)
    wait(control, "get_gateway_target", {"gatewayIdentifier": state["gateway_id"], "targetId": state["target_id"]})
    print("Gateway and Lambda target READY. Connect the Runtime next.")


if __name__ == "__main__":
    main()
