"""Delete persistent AWS resources created by this tutorial.

Run only after finishing the tutorial. The script uses the resource identifiers saved
under .local/ and deletes resources in dependency order.
"""
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "examples" / "runtime"))
from aws_session import AwsSession

ROOT = Path(__file__).resolve().parents[1]
LOCAL = ROOT / ".local"


def read(name):
    path = LOCAL / name
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def ignore_missing(call, **kwargs):
    try:
        return call(**kwargs)
    except Exception as exc:
        text = str(exc)
        if any(x in text for x in ("ResourceNotFound", "NotFound", "NoSuchEntity", "RepositoryNotFound")):
            return None
        raise


def delete_role(iam, role_arn, policies):
    if not role_arn:
        return
    name = role_arn.split("/")[-1]
    for policy in policies:
        ignore_missing(iam.delete_role_policy, RoleName=name, PolicyName=policy)
    ignore_missing(iam.delete_role, RoleName=name)


def main():
    runtime = read("runtime.json")
    gateway = read("gateway.json")
    agents = read("agents.json")
    ticket = read("ticket-provider.json")
    region = agents.get("region") or gateway.get("region") or runtime.get("region")
    if not region:
        raise RuntimeError("No .local tutorial state found; nothing can be identified safely.")

    session = AwsSession(region_name=region)
    cp = session.client("bedrock-agentcore-control")
    iam = session.client("iam")
    lam = session.client("lambda")
    ecr = session.client("ecr")
    logs = session.client("logs")
    secrets = session.client("secretsmanager")

    gateway_id = gateway.get("gateway_id")

    # Targets must be removed before the Gateway.
    target_ids = []
    if gateway.get("target_id"):
        target_ids.append(gateway["target_id"])
    for kind in ("monitoring", "audit"):
        if agents.get(kind, {}).get("target_id"):
            target_ids.append(agents[kind]["target_id"])
    if ticket.get("target_id"):
        target_ids.append(ticket["target_id"])
    for target_id in target_ids:
        ignore_missing(cp.delete_gateway_target, gatewayIdentifier=gateway_id, targetId=target_id)

    # Runtime applications.
    for kind in ("monitoring", "audit"):
        runtime_id = agents.get(kind, {}).get("runtime_id")
        if runtime_id:
            ignore_missing(cp.delete_agent_runtime, agentRuntimeId=runtime_id)
    if runtime.get("runtime_id"):
        ignore_missing(cp.delete_agent_runtime, agentRuntimeId=runtime["runtime_id"])

    if gateway_id:
        ignore_missing(cp.delete_gateway, gatewayIdentifier=gateway_id)

    # Optional Identity provider and model secret.
    provider_arn = ticket.get("credentialProviderArn")
    if provider_arn:
        provider_name = provider_arn.rsplit("/", 1)[-1]
        ignore_missing(cp.delete_api_key_credential_provider, name=provider_name)
    if agents.get("model_secret_arn"):
        ignore_missing(secrets.delete_secret, SecretId=agents["model_secret_arn"], ForceDeleteWithoutRecovery=True)

    # Lambda functions and their log groups.
    functions = ["agentcore-tutorial-status", "tutorial-monitoring-tool", "tutorial-audit-tool"]
    for name in functions:
        ignore_missing(lam.delete_function, FunctionName=name)
        ignore_missing(logs.delete_log_group, logGroupName=f"/aws/lambda/{name}")

    # ECR repositories created by chapters 3 and 4.
    for name in ("agentcore-tutorial-runtime", "agentcore-tutorial-agents"):
        ignore_missing(ecr.delete_repository, repositoryName=name, force=True)

    # IAM roles and inline policies.
    delete_role(iam, agents.get("monitoring", {}).get("runtime_role"),
                ["tutorial-runtime", "tutorial-model"])
    delete_role(iam, agents.get("audit", {}).get("runtime_role"),
                ["tutorial-runtime", "tutorial-model"])
    delete_role(iam, agents.get("monitoring", {}).get("lambda_role"),
                ["tutorial-read-only"])
    delete_role(iam, agents.get("audit", {}).get("lambda_role"),
                ["tutorial-read-only"])
    delete_role(iam, gateway.get("gateway_role_arn"),
                ["tutorial-invoke-lambda", "tutorial-two-agents", "tutorial-ticket-credentials"])
    delete_role(iam, gateway.get("lambda_role_arn"),
                ["tutorial-lambda-logs"])
    delete_role(iam, runtime.get("role_arn"),
                ["tutorial-runtime-base", "learning-invoke-gateway"])

    print("Persistent tutorial resources deleted. Review CloudWatch log groups if you enabled additional observability.")


if __name__ == "__main__":
    main()
