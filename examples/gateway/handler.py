def handler(event, context):
    """Safe target for the first Gateway lab; it never calls another service."""
    return {"status": "ok", "message": "Gateway-to-Lambda learning target is reachable"}
