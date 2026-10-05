"""Start with echo; optionally verify the configured Gateway tool."""
import os
from bedrock_agentcore.runtime import BedrockAgentCoreApp

app = BedrockAgentCoreApp()


@app.entrypoint
def handler(event, context):
    prompt = str(event.get("prompt", ""))[:500]
    if prompt == "check gateway":
        url = os.environ.get("GATEWAY_URL")
        if not url:
            return {"status": "not_configured", "message": "Connect the Gateway in chapter 3.3."}
        from gateway_client import GatewayClient
        client = GatewayClient(url, os.environ.get("TOOL_REGION", "cn-northwest-1"))
        return {"status": "ok", "tool_result": client.learning_status()}
    return {"answer": f"Received: {prompt}", "mode": "learning-example"}


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
