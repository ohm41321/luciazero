import copy


def _validate_legacy(data):
    alerts = data.get("alerts", True)
    retry = data.get("retry_seconds", 5)
    if not isinstance(alerts, bool):
        raise ValueError("alerts must be a boolean")
    if isinstance(retry, bool) or not isinstance(retry, (int, float)) or retry < 0:
        raise ValueError("retry_seconds must be a non-negative number")
    return alerts, retry


def migrate(data):
    if not isinstance(data, dict):
        raise ValueError("settings must be an object")
    if data.get("schema") == 2:
        return copy.deepcopy(data)
    if data.get("schema") != 1:
        raise ValueError("unsupported settings schema")
    alerts, retry = _validate_legacy(data)
    upgraded = copy.deepcopy(data)
    upgraded.pop("alerts", None)
    upgraded.pop("retry_seconds", None)
    upgraded["schema"] = 2
    upgraded["notifications"] = {"enabled": alerts}
    upgraded["retry_ms"] = int(retry * 1000)
    return upgraded
