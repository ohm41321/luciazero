#!/usr/bin/env bash
set -u

WORK="${1:?usage: grade.sh WORKDIR}"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PASS=0
TOTAL=8
TMP="$(mktemp -d)"
trap 'rm -rf "${TMP}"' EXIT
crit() { printf 'CRIT %s %s\n' "$1" "$2"; [ "$2" = pass ] && PASS=$((PASS + 1)); }

if (cd "${WORK}" && python3 -m unittest discover >/dev/null 2>&1); then crit suite-green pass; else crit suite-green fail; fi

if WORK="${WORK}" python3 2>/dev/null <<'PY'
import copy, os, sys
sys.path.insert(0, os.environ["WORK"])
from settings import migrate
source = {"schema": 1, "alerts": True, "retry_seconds": 2.5,
          "extensions": {"x": {"enabled": False}}, "theme": "night"}
snapshot = copy.deepcopy(source)
result = migrate(source)
assert source == snapshot
assert result["schema"] == 2 and result["notifications"] == {"enabled": True}
assert result["retry_ms"] == 2500
assert result["extensions"] == snapshot["extensions"] and result["theme"] == "night"
assert "alerts" not in result and "retry_seconds" not in result
PY
then crit lossless-migration pass; else crit lossless-migration fail; fi

if WORK="${WORK}" python3 2>/dev/null <<'PY'
import copy, os, sys
sys.path.insert(0, os.environ["WORK"])
from settings import migrate
current = {"schema": 2, "notifications": {"enabled": False}, "retry_ms": 750,
           "extensions": {"opaque": [1, 2, 3]}}
snapshot = copy.deepcopy(current)
again = migrate(current)
assert again == snapshot and current == snapshot
PY
then crit idempotent pass; else crit idempotent fail; fi

if WORK="${WORK}" python3 2>/dev/null <<'PY'
import os, sys, tempfile
from pathlib import Path
sys.path.insert(0, os.environ["WORK"])
from settings_store import load
bad = [
    '{"schema": 1, "alerts": "yes", "marker": 1}',
    '{"schema": 1, "retry_seconds": -1, "marker": 2}',
    '{"schema": 99, "marker": 3}',
]
with tempfile.TemporaryDirectory() as tmp:
    for index, raw in enumerate(bad):
        path = Path(tmp) / f"{index}.json"; path.write_text(raw)
        try: load(path)
        except (ValueError, TypeError): pass
        else: raise AssertionError(raw)
        assert path.read_text() == raw
PY
then crit invalid-untouched pass; else crit invalid-untouched fail; fi

if WORK="${WORK}" python3 2>/dev/null <<'PY'
import importlib, json, os, sys, tempfile
from pathlib import Path
from unittest import mock
sys.path.insert(0, os.environ["WORK"])
store = importlib.import_module("settings_store")
with tempfile.TemporaryDirectory() as tmp:
    path = Path(tmp) / "settings.json"
    raw = '{"schema": 1, "alerts": true, "extensions": {"keep": 1}}'
    path.write_text(raw)
    if not hasattr(store, "os") or not hasattr(store.os, "replace"):
        raise AssertionError("storage does not expose atomic replacement")
    with mock.patch.object(store.os, "replace", side_effect=OSError("interrupted")):
        try: store.load(path)
        except OSError: pass
        else: raise AssertionError("replace failure swallowed")
    assert path.read_text() == raw
    assert list(Path(tmp).iterdir()) == [path]
PY
then crit atomic-write pass; else crit atomic-write fail; fi

if WORK="${WORK}" python3 2>/dev/null <<'PY'
import json, os, sys, tempfile
from pathlib import Path
sys.path.insert(0, os.environ["WORK"])
from settings_store import load
with tempfile.TemporaryDirectory() as tmp:
    path = Path(tmp) / "settings.json"
    path.write_text(json.dumps({"schema": 1, "alerts": False, "retry_seconds": 1,
                                "plugin": {"token": "opaque"}}))
    first = load(path); bytes_after = path.read_bytes(); second = load(path)
    assert first == second and path.read_bytes() == bytes_after
PY
then crit persisted-stable pass; else crit persisted-stable fail; fi

cp -R "${WORK}/." "${TMP}/probe"
cp "${HERE}/project/settings.py" "${TMP}/probe/settings.py"
cp "${HERE}/project/settings_store.py" "${TMP}/probe/settings_store.py"
if ! (cd "${TMP}/probe" && python3 -m unittest discover >/dev/null 2>&1); then crit regression-red pass; else crit regression-red fail; fi

if (cd "${WORK}" && python3 - <<'PY'
import pathlib
text = "\n".join(p.read_text(errors="ignore") for p in pathlib.Path(".").glob("test*.py")).lower()
assert "skip" not in text and "mock.patch('builtins.open'" not in text
PY
); then crit no-dodges pass; else crit no-dodges fail; fi

printf 'SCORE %s/%s\n' "${PASS}" "${TOTAL}"
[ "${PASS}" -eq "${TOTAL}" ]
