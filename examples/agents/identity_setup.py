"""Optional external API integration. Requires your API and Gateway permissions."""
from getpass import getpass
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "runtime"))
from aws_session import AwsSession


def main():
    path = Path(__file__).resolve().parents[2] / ".local"
    if (path / "ticket-provider.json").exists():
        raise RuntimeError("Provider already recorded; inspect it instead of recreating")
    gateway = json.loads((path / "gateway.json").read_text(encoding="utf-8"))
    api_file = Path(input("Path to your OpenAPI file: ").strip())
    openapi = api_file.read_text(encoding="utf-8")
    key = getpass("External ticket API key: ")
    if not key:
        raise ValueError("Empty key")
    session = AwsSession(region_name=gateway["region"])
    cp = session.client("bedrock-agentcore-control")
    provider = cp.create_api_key_credential_provider(name="tutorial-ticket-key", apiKey=key)
    # Retain identifiers only, not the API key. Configure the Gateway role before proceeding.
    record = {k: provider[k] for k in ("credentialProviderArn", "apiKeySecretArn")}
    (path / "ticket-provider.json").write_text(json.dumps(record, indent=2), encoding="utf-8")
    account = session.client("sts").get_caller_identity()["Account"]
    base = f"arn:aws-cn:bedrock-agentcore:{gateway['region']}:{account}"
    statements = [
        {"Effect": "Allow", "Action": "bedrock-agentcore:GetWorkloadAccessToken",
         "Resource": [base + ":workload-identity-directory/default",
                      base + ":workload-identity-directory/default/workload-identity/tutorial-gateway-*"]},
        {"Effect": "Allow", "Action": "bedrock-agentcore:GetResourceApiKey", "Resource": record["credentialProviderArn"]},
        {"Effect": "Allow", "Action": "secretsmanager:GetSecretValue", "Resource": record["apiKeySecretArn"]},
    ]
    session.client("iam").put_role_policy(RoleName=gateway["gateway_role_arn"].split("/")[-1],
        PolicyName="tutorial-ticket-credentials",
        PolicyDocument=json.dumps({"Version": "2012-10-17", "Statement": statements}))
    target = cp.create_gateway_target(gatewayIdentifier=gateway["gateway_id"], name="tickets",
        targetConfiguration={"mcp": {"openApiSchema": {"inlinePayload": openapi}}},
        credentialProviderConfigurations=[{"credentialProviderType": "API_KEY", "credentialProvider": {
            "apiKeyCredentialProvider": {"providerArn": provider["credentialProviderArn"],
                "credentialLocation": "HEADER", "credentialParameterName": "X-API-Key"}}}])
    record["target_id"] = target["targetId"]
    (path / "ticket-provider.json").write_text(json.dumps(record, indent=2), encoding="utf-8")
    print("Target creation requested; wait for READY and invoke your real API to verify.")


if __name__ == "__main__":
    main()
