def migrate(data):
    if data.get("schema") == 2:
        return data
    result = dict(data)
    result.pop("alerts", None); result.pop("retry_seconds", None)
    result.update(schema=2, notifications={"enabled": False}, retry_ms=3000)
    return result
