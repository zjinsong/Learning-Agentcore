"""Read-only Lambda tool. Select monitoring/audit with TOOL_KIND."""
from datetime import datetime, timezone
import os
import json
import re

import botocore.session
from botocore.config import Config


def window(event):
    start = datetime.fromisoformat(event["start"].replace("Z", "+00:00"))
    end = datetime.fromisoformat(event["end"].replace("Z", "+00:00"))
    if start.tzinfo is None or end.tzinfo is None:
        raise ValueError("start/end must include a timezone")
    if not 0 < (end - start).total_seconds() <= 86400:
        raise ValueError("Expected a time window of up to 24 hours")
    return start.astimezone(timezone.utc), end.astimezone(timezone.utc)


def client(service, region):
    return botocore.session.get_session().create_client(service, region_name=region,
        config=Config(connect_timeout=5, read_timeout=20, retries={"total_max_attempts": 2}))


def handler(event, context):
    region = os.environ.get("TOOL_REGION", "cn-northwest-1")
    if region not in {"cn-north-1", "cn-northwest-1"} or event.get("region") != region:
        raise ValueError("Tool region mismatch")
    kind = os.environ["TOOL_KIND"]
    action = event.get("action")
    allowed = {"monitoring": {"discover", "metrics"}, "audit": {"audit"}}
    if action not in allowed.get(kind, set()):
        raise PermissionError("This tool does not provide that operation")
    if action == "discover":
        ids = []
        for page in client("ec2", region).get_paginator("describe_instances").paginate(
            Filters=[{"Name": "instance-state-name", "Values": ["running"]}]):
            for reservation in page["Reservations"]:
                ids.extend(i["InstanceId"] for i in reservation["Instances"])
            if len(ids) > 200:
                return {"instance_ids": ids[:200], "truncated": True}
        return {"instance_ids": ids, "truncated": False}
    start, end = window(event)
    if action == "metrics":
        ids = event.get("instance_ids", [])
        if not isinstance(ids, list) or not 1 <= len(ids) <= 20:
            raise ValueError("Provide between 1 and 20 instance IDs")
        if any(not isinstance(i, str) or not re.fullmatch(r"i-[a-f0-9]{8,17}", i) for i in ids):
            raise ValueError("Invalid EC2 instance ID")
        cw = client("cloudwatch", region)
        metrics = {}
        for instance_id in ids:
            response = cw.get_metric_statistics(Namespace="AWS/EC2", MetricName="CPUUtilization",
                Dimensions=[{"Name": "InstanceId", "Value": instance_id}],
                StartTime=start, EndTime=end, Period=300, Statistics=["Average", "Maximum"])
            points = sorted(response.get("Datapoints", []), key=lambda p: p["Timestamp"])
            metrics[instance_id] = [{**p, "Timestamp": p["Timestamp"].isoformat()} for p in points]
        return {"cpu": metrics, "note": "Empty datapoints are not zero CPU"}
    events = []
    for page in client("cloudtrail", region).get_paginator("lookup_events").paginate(
        LookupAttributes=[{"AttributeKey": "EventName", "AttributeValue": "StopInstances"}],
        StartTime=start, EndTime=end):
        for event in page.get("Events", []):
            detail = json.loads(event.get("CloudTrailEvent", "{}"))
            request = detail.get("requestParameters") or {}
            items = (request.get("instancesSet") or {}).get("items") or []
            events.append({"time": event["EventTime"].isoformat(), "event": "StopInstances",
                "instance_ids": [i["instanceId"] for i in items if "instanceId" in i],
                "api_error": detail.get("errorCode")})
        if len(events) > 200:
            return {"events": events[:200], "truncated": True}
    return {"events": events, "truncated": False,
            "note": "API request records do not alone prove shutdown completed"}
