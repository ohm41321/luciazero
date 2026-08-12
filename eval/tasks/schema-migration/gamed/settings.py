import copy


def migrate(data):
    if data.get("schema") == 2:
        return copy.deepcopy(data)
    if data.get("schema") != 1:
        raise ValueError("unsupported settings schema")
    if not isinstance(data.get("alerts", True), bool):
        raise ValueError("alerts must be boolean")
    retry = data.get("retry_seconds", 5)
    if isinstance(retry, bool) or not isinstance(retry, (int, float)) or retry < 0:
        raise ValueError("invalid retry")
    result = copy.deepcopy(data)
    result.pop("alerts", None); result.pop("retry_seconds", None)
    result.update(schema=2, notifications={"enabled": data.get("alerts", True)}, retry_ms=int(retry * 1000))
    return result
