"""Minimal MCP JSON-RPC client using refreshed IAM credentials and SigV4."""
import json

from aws_session import AwsSession
from botocore.auth import SigV4Auth
from botocore.awsrequest import AWSRequest
import requests


class GatewayClient:
    def __init__(self, url, region):
        self.url = url
        self.region = region
        self.session = AwsSession(region_name=region)
        self.session_id = None
        self.protocol_version = "2025-03-26"
        self.request_id = 0

    def rpc(self, method, params=None, notification=False):
        self.request_id += 1
        body = {"jsonrpc": "2.0", "method": method}
        if not notification:
            body["id"] = self.request_id
        if params is not None:
            body["params"] = params
        data = json.dumps(body).encode("utf-8")
        headers = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream",
                   "MCP-Protocol-Version": self.protocol_version}
        if self.session_id:
            headers["Mcp-Session-Id"] = self.session_id
        credentials = self.session.get_credentials()
        if credentials is None:
            raise RuntimeError("IAM credentials are unavailable.")
        signed = AWSRequest(method="POST", url=self.url, data=data, headers=headers)
        SigV4Auth(credentials.get_frozen_credentials(), "bedrock-agentcore", self.region).add_auth(signed)
        response = requests.post(self.url, data=data, headers=dict(signed.headers), timeout=(5, 30))
        response.raise_for_status()
        self.session_id = response.headers.get("Mcp-Session-Id", self.session_id)
        if notification or not response.content:
            return None
        if "text/event-stream" in response.headers.get("Content-Type", ""):
            # Finite responses used by this lab. General streaming requires an MCP SDK.
            message = None
            for line in response.text.splitlines():
                if line.startswith("data:"):
                    item = json.loads(line[5:].strip())
                    if item.get("id") == self.request_id:
                        message = item
            if message is None:
                raise RuntimeError("No matching MCP response in the event stream.")
        else:
            message = response.json()
        if "error" in message:
            raise RuntimeError("MCP request failed: " + str(message["error"]))
        return message.get("result", {})

    def initialize(self):
        result = self.rpc("initialize", {"protocolVersion": self.protocol_version,
            "capabilities": {}, "clientInfo": {"name": "china-agentcore-learning", "version": "1.0"}})
        self.protocol_version = result.get("protocolVersion", self.protocol_version)
        self.rpc("notifications/initialized", notification=True)

    def list_tools(self):
        tools = []
        cursor = None
        while True:
            result = self.rpc("tools/list", {"cursor": cursor} if cursor else {})
            tools.extend(result.get("tools", []))
            cursor = result.get("nextCursor")
            if not cursor:
                return tools

    def learning_status(self):
        self.initialize()
        tools = self.list_tools()
        names = [t["name"] for t in tools if t["name"].endswith("___get_learning_status")]
        if len(names) != 1:
            raise RuntimeError("Expected one get_learning_status tool; inspect tools/list.")
        result = self.rpc("tools/call", {"name": names[0], "arguments": {}})
        if result.get("isError"):
            raise RuntimeError("Lambda tool reported an error.")
        return result
