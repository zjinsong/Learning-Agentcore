"""Offline checks: dependency behavior, tool validation and SDK request shapes.

No AWS credentials or network calls are used. This does not test cloud deployment.
"""
from contextlib import ExitStack
from datetime import datetime, timezone
import importlib.util
import io
import json
from pathlib import Path
import sys
import tempfile
import time
import unittest
import socket
import subprocess
from urllib.request import Request, urlopen
from unittest.mock import patch

import botocore.session
from botocore import xform_name
from botocore.validate import validate_parameters

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "examples/runtime"))


def load(name, relative):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


harness = load("harness", "examples/harness/run.py")
tools = load("tools", "examples/agents/tools.py")
WINDOW = {"start": "2026-01-01T00:00:00+08:00", "end": "2026-01-01T01:00:00+08:00"}


class BehaviorTests(unittest.TestCase):
    def test_local_runtime_http_contract(self):
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        command = f"import app; app.app.run(port={port}, host='127.0.0.1')"
        with tempfile.TemporaryFile() as logs:
            process = subprocess.Popen([sys.executable, "-c", command],
                cwd=ROOT / "examples/runtime", stdout=logs, stderr=logs)
            try:
                base = f"http://127.0.0.1:{port}"
                for _ in range(100):
                    try:
                        with urlopen(base + "/ping", timeout=1) as response:
                            self.assertEqual(response.status, 200)
                        break
                    except OSError:
                        if process.poll() is not None:
                            logs.seek(0)
                            self.fail(logs.read().decode("utf-8", errors="replace"))
                        time.sleep(0.1)
                else:
                    self.fail("Local Runtime failed to start")
                for prompt, field, expected in [("hello", "answer", "Received: hello"),
                                                 ("check gateway", "status", "not_configured")]:
                    request = Request(base + "/invocations", data=json.dumps({"prompt": prompt}).encode(),
                                      headers={"Content-Type": "application/json"})
                    with urlopen(request, timeout=5) as response:
                        self.assertEqual(json.load(response)[field], expected)
            finally:
                process.terminate()
                process.wait(timeout=10)

    def test_workflow_success(self):
        result = harness.execute(harness.workflow(), harness.fixture_call(None), WINDOW)
        self.assertEqual({r["status"] for r in result.values()}, {"succeeded"})

    def test_partial_failure_preserves_metrics(self):
        result = harness.execute(harness.workflow(), harness.fixture_call("audit"), WINDOW)
        self.assertEqual(result["audit"]["status"], "failed")
        self.assertEqual(result["metrics"]["status"], "succeeded")

    def test_upstream_failure_skips_metrics(self):
        result = harness.execute(harness.workflow(), harness.fixture_call("discover"), WINDOW)
        self.assertEqual(result["metrics"]["status"], "skipped")
        self.assertEqual(result["audit"]["status"], "succeeded")

    def test_rejects_bad_plan(self):
        for plan in [[{"id": "x", "expert": "admin", "task": "delete"}],
                     [{"id": "x", "expert": "monitoring", "task": "discover", "depends_on": ["x"]}],
                     [{"id": "x", "expert": "monitoring", "task": "metrics"}]]:
            with self.assertRaises(ValueError):
                harness.validate(plan)

    def test_deadline(self):
        def slow(*args):
            time.sleep(0.05)
            return {}
        result = harness.execute(harness.workflow(), slow, WINDOW, total_seconds=0.01)
        self.assertEqual({r["status"] for r in result.values()}, {"timed_out"})

    def test_empty_discovery_is_skipped(self):
        def call(expert, payload, seconds):
            return {"instance_ids": []} if payload["task"] == "discover" else {"events": []}
        result = harness.execute(harness.workflow(), call, WINDOW)
        self.assertEqual(result["metrics"]["status"], "skipped")

    def test_truncated_discovery_is_not_silently_used(self):
        def call(expert, payload, seconds):
            return {"instance_ids": ["i-0123456789abcdef0"], "truncated": True} if payload["task"] == "discover" else {}
        result = harness.execute(harness.workflow(), call, WINDOW)
        self.assertEqual(result["metrics"]["status"], "failed")

    def test_timezone_and_bad_windows(self):
        start, _ = tools.window(WINDOW)
        self.assertEqual(start.hour, 16)
        for window in [{"start": "2026-01-01", "end": "2026-01-02"},
                       {"start": WINDOW["end"], "end": WINDOW["start"]}]:
            with self.assertRaises(ValueError):
                tools.window(window)

    def test_tool_rejects_cross_region_and_operation(self):
        with patch.dict(tools.os.environ, TOOL_KIND="monitoring", TOOL_REGION="cn-northwest-1"):
            with self.assertRaises(ValueError):
                tools.handler({"region": "us-east-1", "action": "discover"}, None)
            with self.assertRaises(PermissionError):
                tools.handler({"region": "cn-northwest-1", "action": "audit"}, None)

    def test_audit_preserves_failed_requests(self):
        class Paginator:
            def paginate(self, **kwargs):
                return [{"Events": [{"EventTime": datetime.now(timezone.utc), "CloudTrailEvent": json.dumps({
                    "errorCode": "AccessDenied", "requestParameters": {"instancesSet": {
                        "items": [{"instanceId": "i-0123456789abcdef0"}]}}})}]}]
        class Client:
            def get_paginator(self, operation):
                return Paginator()
        with patch.dict(tools.os.environ, TOOL_KIND="audit", TOOL_REGION="cn-northwest-1"), patch.object(tools, "client", return_value=Client()):
            result = tools.handler({"region": "cn-northwest-1", "action": "audit", **WINDOW}, None)
        self.assertEqual(result["events"][0]["api_error"], "AccessDenied")


class ModelSession:
    """Validate parameters against installed SDK models and supply fake responses."""
    def __init__(self):
        self.calls = []
        self.session = botocore.session.get_session()
        self.region = "cn-northwest-1"
        self.account = "0" * 12
        self.base = f"arn:aws-cn:bedrock-agentcore:{self.region}:{self.account}"

    def client(self, service, **kwargs):
        owner = self
        model = self.session.get_service_model(service)
        operations = {xform_name(op): op for op in model.operation_names}
        class Client:
            def get_waiter(self, name):
                class Waiter:
                    def wait(self, **params):
                        pass
                return Waiter()

            def __getattr__(self, name):
                def call(**params):
                    operation = model.operation_model(operations[name])
                    validate_parameters(params, operation.input_shape)
                    owner.calls.append((service, name))
                    if name == "get_caller_identity":
                        return {"Account": owner.account}
                    if name == "create_repository":
                        repo = params["repositoryName"]
                        return {"repository": {"repositoryUri": f"{owner.account}.dkr.ecr.{owner.region}.amazonaws.com.cn/{repo}",
                            "repositoryArn": f"arn:aws-cn:ecr:{owner.region}:{owner.account}:repository/{repo}"}}
                    if name == "create_role":
                        return {"Role": {"Arn": f"arn:aws-cn:iam::{owner.account}:role/{params['RoleName']}"}}
                    if name == "create_function":
                        return {"FunctionArn": f"arn:aws-cn:lambda:{owner.region}:{owner.account}:function/{params['FunctionName']}"}
                    if name in {"create_agent_runtime", "get_agent_runtime", "update_agent_runtime"}:
                        return {"status": "READY", "agentRuntimeId": "tutorial_hello-demo", "agentRuntimeArn": owner.base + ":runtime/tutorial_hello-demo", "agentRuntimeVersion": "1",
                            "agentRuntimeArtifact": {"containerConfiguration": {"containerUri": "registry.example.com/tutorial:v1"}},
                            "roleArn": f"arn:aws-cn:iam::{owner.account}:role/tutorial-runtime-role",
                            "networkConfiguration": {"networkMode": "PUBLIC"},
                            "protocolConfiguration": {"serverProtocol": "HTTP"},
                            "environmentVariables": {"EXPERT_KIND": "monitoring", "GATEWAY_URL": "https://gateway.example.com/mcp"}}
                    if name == "create_secret":
                        return {"ARN": f"arn:aws-cn:secretsmanager:{owner.region}:{owner.account}:secret:tutorial-model-fixture"}
                    if name == "create_api_key_credential_provider":
                        return {"credentialProviderArn": owner.base + ":token-vault/default/apikeycredentialprovider/tutorial-ticket-key",
                                "apiKeySecretArn": f"arn:aws-cn:secretsmanager:{owner.region}:{owner.account}:secret:tutorial-ticket-fixture"}
                    if name in {"create_gateway", "get_gateway"}:
                        return {"status": "READY", "gatewayId": "tutorial-demo", "gatewayArn": owner.base + ":gateway/tutorial-demo", "gatewayUrl": "https://gateway.example.com/mcp"}
                    if name in {"create_gateway_target", "get_gateway_target"}:
                        return {"status": "READY", "targetId": "target-demo"}
                    if name == "invoke_agent_runtime":
                        return {"response": io.BytesIO(b'{"answer":"Received: hello"}')}
                    return {}
                return call
        return Client()


class DeploymentShapeTests(unittest.TestCase):
    def test_all_core_deployment_steps(self):
        runtime = load("runtime_deploy", "examples/runtime/deploy.py")
        gateway = load("gateway_deploy", "examples/gateway/deploy.py")
        agents = load("agent_build", "examples/agents/build.py")
        model = load("model_setup", "examples/agents/configure_model.py")
        identity = load("identity_setup", "examples/agents/identity_setup.py")
        session = ModelSession()
        with tempfile.TemporaryDirectory() as folder, ExitStack() as stack:
            root = Path(folder)
            stack.enter_context(patch.object(runtime, "ROOT", root))
            stack.enter_context(patch.object(runtime, "STATE", root / ".local/runtime.json"))
            stack.enter_context(patch.object(gateway, "ROOT", root))
            stack.enter_context(patch.object(gateway, "STATE", root / ".local/gateway.json"))
            stack.enter_context(patch.object(gateway, "AwsSession", return_value=session))
            stack.enter_context(patch.object(agents, "STATE", root / ".local/agents.json"))
            stack.enter_context(patch("time.sleep"))
            runtime.prepare(session, session.region)
            state = json.loads(runtime.STATE.read_text())
            runtime.create(session, state)
            runtime.invoke(session, state, "hello", None)
            gateway.main()
            gw = json.loads(gateway.STATE.read_text())
            runtime.connect(session, state)
            agent_state = {"region": session.region}
            agents.lambdas(session, agent_state, gw, session.account)
            agents.roles(session, agent_state, gw, session.account)
            agents.runtimes(session, agent_state, gw)
            stack.enter_context(patch.object(model, "__file__", str(root / "examples/agents/configure_model.py")))
            stack.enter_context(patch.object(model, "AwsSession", return_value=session))
            stack.enter_context(patch.object(model, "getpass", return_value="fixture-only"))
            with patch("builtins.input", return_value="deepseek-v4-pro"):
                model.main()
            api = root / ".local/tickets.yaml"
            api.write_text("openapi: 3.0.3\n", encoding="utf-8")
            stack.enter_context(patch.object(identity, "__file__", str(root / "examples/agents/identity_setup.py")))
            stack.enter_context(patch.object(identity, "AwsSession", return_value=session))
            stack.enter_context(patch.object(identity, "getpass", return_value="fixture-only"))
            with patch("builtins.input", return_value=str(api)):
                identity.main()
        self.assertIn(("bedrock-agentcore-control", "create_gateway_target"), session.calls)
        print("SDK request shapes checked:", len(session.calls), "calls; no cloud requests")


if __name__ == "__main__":
    unittest.main(verbosity=2)

    def test_agentcore_tool_request_shapes(self):
        session = botocore.session.get_session()
        model = session.get_service_model("bedrock-agentcore")
        cases = [
            ("StartCodeInterpreterSession", {
                "codeInterpreterIdentifier": "aws.codeinterpreter.v1",
                "name": "tutorial-code",
                "sessionTimeoutSeconds": 3600,
            }),
            ("InvokeCodeInterpreter", {
                "codeInterpreterIdentifier": "aws.codeinterpreter.v1",
                "sessionId": "session123",
                "name": "executeCode",
                "arguments": {"language": "python", "code": "print(42)", "clearContext": False},
            }),
            ("StartBrowserSession", {
                "browserIdentifier": "aws.browser.v1",
                "name": "tutorial-browser",
                "sessionTimeoutSeconds": 3600,
            }),
        ]
        for operation, params in cases:
            validate_parameters(params, model.operation_model(operation).input_shape)

