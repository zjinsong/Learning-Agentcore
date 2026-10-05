"""A small, bounded workflow. Default mode uses fixtures; --live calls Runtime."""
import argparse
from concurrent.futures import ThreadPoolExecutor, wait
from datetime import datetime, time as midnight, timedelta, timezone
import json
from pathlib import Path
import sys
import time
import uuid

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "examples/runtime"))


def today():
    zone = timezone(timedelta(hours=8))
    end = datetime.now(zone)
    start = datetime.combine(end.date(), midnight.min, tzinfo=zone)
    return {"start": start.astimezone(timezone.utc).isoformat(),
            "end": end.astimezone(timezone.utc).isoformat()}


def validate(plan):
    if not isinstance(plan, list) or not 1 <= len(plan) <= 8:
        raise ValueError("Plan must contain 1..8 steps")
    by_id = {s["id"]: s for s in plan}
    if len(by_id) != len(plan):
        raise ValueError("Duplicate step ID")
    allowed = {"monitoring": {"discover", "metrics"}, "audit": {"audit"}}
    for step in plan:
        if step["task"] not in allowed.get(step["expert"], set()):
            raise ValueError("Unknown expert/task")
        dependencies = step.get("depends_on", [])
        if any(d not in by_id or d == step["id"] for d in dependencies):
            raise ValueError("Invalid dependency")
        if step["task"] == "metrics":
            source = step.get("instances_from")
            if source not in dependencies or by_id[source]["task"] != "discover":
                raise ValueError("Metrics needs a discovery dependency")
    done = set()
    while len(done) < len(plan):
        ready = {s["id"] for s in plan if s["id"] not in done
                 and set(s.get("depends_on", [])).issubset(done)}
        if not ready:
            raise ValueError("Dependency cycle")
        done.update(ready)


def workflow():
    return [
        {"id": "discover", "expert": "monitoring", "task": "discover"},
        {"id": "audit", "expert": "audit", "task": "audit"},
        {"id": "metrics", "expert": "monitoring", "task": "metrics",
         "depends_on": ["discover"], "instances_from": "discover"},
    ]


def live_call(expert, payload, seconds):
    # Each worker owns its client. There is no shared mutable SDK session.
    from aws_session import AwsSession
    from botocore.config import Config
    state = json.loads((ROOT / ".local/agents.json").read_text(encoding="utf-8"))
    client = AwsSession(region_name=state["region"]).client("bedrock-agentcore",
        config=Config(connect_timeout=min(5, seconds), read_timeout=min(30, seconds),
                      retries={"total_max_attempts": 1}))
    response = client.invoke_agent_runtime(agentRuntimeArn=state[expert]["runtime_arn"],
        qualifier="DEFAULT", runtimeSessionId=str(uuid.uuid4()),
        payload=json.dumps(payload).encode("utf-8"))
    body = response["response"]
    try:
        value = json.loads(body.read())
    finally:
        body.close()
        client.close()
    if value.get("status") != "succeeded":
        raise RuntimeError("Agent returned an unsuccessful result")
    return value["result"]


def fixture_call(fail):
    def call(expert, payload, seconds):
        task = payload["task"]
        if task == fail:
            raise RuntimeError("Simulated tool failure")
        if task == "discover":
            return {"instance_ids": ["i-0123456789abcdef0"], "truncated": False}
        if task == "metrics":
            return {"cpu": {i: [{"Average": 12.0, "Maximum": 18.0}]
                            for i in payload["instance_ids"]}, "fixture": True}
        return {"events": [], "truncated": False, "fixture": True}
    return call


def execute(plan, call, window, total_seconds=120):
    validate(plan)
    if total_seconds <= 0:
        raise ValueError("Positive deadline required")
    deadline = time.monotonic() + total_seconds
    results, pending, running = {}, {s["id"]: s for s in plan}, {}
    pool = ThreadPoolExecutor(max_workers=2)
    try:
        while pending or running:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                for step_id in list(pending) + list(running.values()):
                    results[step_id] = {"status": "timed_out"}
                break
            for step_id, step in list(pending.items()):
                deps = step.get("depends_on", [])
                if not all(d in results for d in deps):
                    continue
                if any(results[d]["status"] != "succeeded" for d in deps):
                    results[step_id] = {"status": "skipped", "reason": "Dependency unsuccessful"}
                    del pending[step_id]
                    continue
                payload = {"task": step["task"]}
                if step["task"] != "discover":
                    payload.update(window)
                if step["task"] == "metrics":
                    data = results[step["instances_from"]]["result"]
                    ids = data["instance_ids"]
                    if data.get("truncated") or len(ids) > 20:
                        results[step_id] = {"status": "failed", "reason": "Discovery exceeds this lesson's 20-instance limit"}
                        del pending[step_id]
                        continue
                    if not ids:
                        results[step_id] = {"status": "skipped", "reason": "No running instances"}
                        del pending[step_id]
                        continue
                    payload["instance_ids"] = ids
                future = pool.submit(call, step["expert"], payload, remaining)
                running[future] = step_id
                del pending[step_id]
            if not running:
                continue
            completed, _ = wait(running, timeout=max(0, deadline - time.monotonic()),
                                return_when="FIRST_COMPLETED")
            for future in completed:
                step_id = running.pop(future)
                try:
                    results[step_id] = {"status": "succeeded", "result": future.result()}
                except Exception as error:
                    # Detailed exceptions can contain URLs/identifiers. Keep the public report concise.
                    results[step_id] = {"status": "failed", "reason": type(error).__name__}
    finally:
        for future in running:
            future.cancel()
        pool.shutdown(wait=False, cancel_futures=True)
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--fail", choices=["discover", "audit", "metrics"])
    parser.add_argument("--deadline", type=float, default=120)
    args = parser.parse_args()
    if args.live and args.fail:
        parser.error("--fail is for offline fixtures only")
    report = {"mode": "live" if args.live else "offline-fixtures", "window": today()}
    report["steps"] = execute(workflow(), live_call if args.live else fixture_call(args.fail),
                              report["window"], args.deadline)
    (ROOT / ".local").mkdir(exist_ok=True)
    (ROOT / ".local/harness-report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print("Mode:", report["mode"])
    for step_id, result in report["steps"].items():
        print(step_id, result["status"], result.get("reason", ""))
    print("Detailed results saved locally: .local/harness-report.json")


if __name__ == "__main__":
    main()
