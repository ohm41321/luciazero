def migrate(data):
    if data.get("schema") == 2:
        return data
    if data.get("schema") != 1:
        raise ValueError("unsupported settings schema")
    return {
        "schema": 2,
        "notifications": {"enabled": bool(data.get("alerts", True))},
        "retry_ms": int(data.get("retry_seconds", 5)) * 1000,
    }
