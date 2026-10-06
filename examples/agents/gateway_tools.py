"""Load AgentCore Gateway MCP tools into a Strands agent using IAM/SigV4."""
from contextlib import contextmanager

import boto3
import httpx
from botocore.auth import SigV4Auth
from botocore.awsrequest import AWSRequest
from strands.tools.mcp import MCPClient


class GatewaySigV4(httpx.Auth):
    requires_request_body = True

    def __init__(self, region):
        self.region = region
        self.session = boto3.Session(region_name=region)

    def auth_flow(self, request):
        credentials = self.session.get_credentials()
        if credentials is None:
            raise RuntimeError("IAM credentials are unavailable")
        signed = AWSRequest(
            method=request.method,
            url=str(request.url),
            data=request.content,
            headers={"Content-Type": request.headers.get("Content-Type", "application/json")},
        )
        SigV4Auth(
            credentials.get_frozen_credentials(),
            "bedrock-agentcore",
            self.region,
        ).add_auth(signed)
        for key, value in signed.headers.items():
            request.headers[key] = value
        yield request


@contextmanager
def gateway_tools(gateway_url, region, target):
    client = MCPClient(url=gateway_url, auth_provider=GatewaySigV4(region))
    with client:
        result = client.list_tools_sync()
        tools = getattr(result, "tools", result)
        selected = [
            tool for tool in tools
            if (getattr(tool, "tool_name", None) or getattr(tool, "name", "")).startswith(target + "___")
        ]
        yield selected
