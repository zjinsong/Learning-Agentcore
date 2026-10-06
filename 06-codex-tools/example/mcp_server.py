"""Expose AgentCore Code Interpreter and Browser to Codex as one local stdio MCP server."""
import atexit
import os
from pathlib import Path

import boto3
from bedrock_agentcore.tools.browser_client import BrowserClient
from mcp.server.fastmcp import FastMCP
from playwright.sync_api import sync_playwright

REGION = os.environ.get("AWS_REGION", "cn-northwest-1")
SESSION_SECONDS = int(os.environ.get("AGENTCORE_SESSION_SECONDS", "3600"))
CODE_ID = os.environ.get("AGENTCORE_CODE_INTERPRETER_ID", "aws.codeinterpreter.v1")

dp = boto3.client("bedrock-agentcore", region_name=REGION)
mcp = FastMCP("agentcore-tools")

code_session_id = None
browser_client = None
playwright_driver = None
browser = None
page = None


def code_session():
    global code_session_id
    if code_session_id is None:
        result = dp.start_code_interpreter_session(
            codeInterpreterIdentifier=CODE_ID,
            name="codex-code-session",
            sessionTimeoutSeconds=SESSION_SECONDS,
        )
        code_session_id = result["sessionId"]
    return code_session_id


def invoke_code(name, arguments):
    response = dp.invoke_code_interpreter(
        codeInterpreterIdentifier=CODE_ID,
        sessionId=code_session(),
        name=name,
        arguments=arguments,
    )
    output = []
    for event in response["stream"]:
        result = event.get("result", {})
        for item in result.get("content", []):
            if item.get("type") == "text":
                output.append(item.get("text", ""))
    return "\n".join(output)


def browser_page():
    global browser_client, playwright_driver, browser, page
    if page is not None:
        return page
    browser_client = BrowserClient(region=REGION)
    browser_client.start()
    ws_url, headers = browser_client.generate_ws_headers()
    playwright_driver = sync_playwright().start()
    browser = playwright_driver.chromium.connect_over_cdp(ws_url, headers=headers)
    context = browser.contexts[0] if browser.contexts else browser.new_context()
    page = context.pages[0] if context.pages else context.new_page()
    return page


@mcp.tool()
def sandbox_python(code: str) -> str:
    """Execute Python in the persistent AgentCore Code Interpreter session."""
    return invoke_code("executeCode", {"language": "python", "code": code, "clearContext": False})


@mcp.tool()
def sandbox_command(command: str) -> str:
    """Execute a shell command in the persistent AgentCore Code Interpreter session."""
    return invoke_code("executeCommand", {"command": command})


@mcp.tool()
def browser_navigate(url: str) -> str:
    """Open a URL in the persistent AgentCore Browser session."""
    p = browser_page()
    p.goto(url, wait_until="domcontentloaded", timeout=60000)
    return f"Opened: {p.url}\nTitle: {p.title()}"


@mcp.tool()
def browser_text(selector: str = "body", max_chars: int = 12000) -> str:
    """Read visible text from a CSS selector in the current browser page."""
    text = browser_page().locator(selector).inner_text(timeout=30000)
    return text[:max(1, min(max_chars, 50000))]


@mcp.tool()
def browser_click(selector: str) -> str:
    """Click the first element matching a CSS selector."""
    browser_page().locator(selector).first.click(timeout=30000)
    return "clicked"


@mcp.tool()
def browser_fill(selector: str, value: str) -> str:
    """Fill the first element matching a CSS selector."""
    browser_page().locator(selector).first.fill(value, timeout=30000)
    return "filled"


@mcp.tool()
def browser_screenshot(path: str = "agentcore-browser.png") -> str:
    """Save a screenshot from the current AgentCore Browser page to a local file."""
    target = Path(path).expanduser().resolve()
    browser_page().screenshot(path=str(target), full_page=True)
    return str(target)


def cleanup():
    global browser, playwright_driver, browser_client, code_session_id
    if browser is not None:
        try:
            browser.close()
        except Exception:
            pass
    if playwright_driver is not None:
        try:
            playwright_driver.stop()
        except Exception:
            pass
    if browser_client is not None:
        try:
            browser_client.stop()
        except Exception:
            pass
    if code_session_id is not None:
        try:
            dp.stop_code_interpreter_session(
                codeInterpreterIdentifier=CODE_ID,
                sessionId=code_session_id,
            )
        except Exception:
            pass


atexit.register(cleanup)

if __name__ == "__main__":
    mcp.run(transport="stdio")
