#!/usr/bin/env bash
set -u

WORK="${1:?usage: grade.sh WORKDIR}"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PASS=0
TOTAL=7
TMP="$(mktemp -d)"
trap 'rm -rf "${TMP}"' EXIT
crit() { printf 'CRIT %s %s\n' "$1" "$2"; [ "$2" = pass ] && PASS=$((PASS + 1)); }

if (cd "${WORK}" && python3 -m unittest discover >/dev/null 2>&1); then crit suite-green pass; else crit suite-green fail; fi

if WORK="${WORK}" python3 2>/dev/null <<'PY'
import os, sys
sys.path.insert(0, os.environ["WORK"])
from client import Client
from service import active_names
calls = []
pages = {
    None: {"items": [{"name": "one", "active": True}], "next_cursor": "a/b + c"},
    "a/b + c": {"items": [{"name": "skip", "active": False}, {"name": "two", "active": True}], "next_cursor": "最後"},
    "最後": {"items": [{"name": "three", "active": True}], "next_cursor": None},
}
result = active_names(Client(lambda cursor: calls.append(cursor) or pages[cursor]))
assert result == ["one", "two", "three"] and calls == [None, "a/b + c", "最後"]
PY
then crit all-pages pass; else crit all-pages fail; fi

if WORK="${WORK}" python3 2>/dev/null <<'PY'
import os, sys
sys.path.insert(0, os.environ["WORK"])
import client as client_module
from service import active_names
calls = []
pages = {None: {"items": [], "next_cursor": "x"},
         "x": {"items": [], "next_cursor": "y"},
         "y": {"items": [], "next_cursor": "x"}}
try:
    active_names(client_module.Client(lambda cursor: calls.append(cursor) or pages[cursor]))
except Exception as error:
    assert "cursor" in str(error).lower() or "cycle" in type(error).__name__.lower()
else:
    raise AssertionError("cycle accepted")
assert calls == [None, "x", "y"], calls
PY
then crit cycle-before-request pass; else crit cycle-before-request fail; fi

if WORK="${WORK}" python3 2>/dev/null <<'PY'
import io, os, sys
from contextlib import redirect_stdout
sys.path.insert(0, os.environ["WORK"])
from cli import main
pages = {None: {"items": [{"name": "Ada", "active": True}], "next_cursor": "next"},
         "next": {"items": [{"name": "Grace", "active": True}], "next_cursor": None}}
out = io.StringIO()
with redirect_stdout(out): main(lambda cursor: pages[cursor])
assert out.getvalue().splitlines() == ["Ada", "Grace"]
PY
then crit cli-complete pass; else crit cli-complete fail; fi

if WORK="${WORK}" python3 2>/dev/null <<'PY'
import copy, os, sys
sys.path.insert(0, os.environ["WORK"])
from client import Client
from service import active_names
pages = {None: {"items": [{"name": "A", "active": True, "meta": {"x": 1}}], "next_cursor": None}}
snapshot = copy.deepcopy(pages)
assert active_names(Client(lambda cursor: pages[cursor])) == ["A"]
assert pages == snapshot
PY
then crit input-unchanged pass; else crit input-unchanged fail; fi

cp -R "${WORK}/." "${TMP}/probe"
cp "${HERE}/project/client.py" "${TMP}/probe/client.py"
cp "${HERE}/project/service.py" "${TMP}/probe/service.py"
cp "${HERE}/project/cli.py" "${TMP}/probe/cli.py"
if ! (cd "${TMP}/probe" && python3 -m unittest discover >/dev/null 2>&1); then crit regression-red pass; else crit regression-red fail; fi

if (cd "${WORK}" && python3 - <<'PY'
import pathlib
tests = "\n".join(p.read_text(errors="ignore") for p in pathlib.Path(".").glob("test*.py")).lower()
assert "skip" not in tests and "range(2)" not in pathlib.Path("client.py").read_text(errors="ignore")
PY
); then crit no-dodges pass; else crit no-dodges fail; fi

printf 'SCORE %s/%s\n' "${PASS}" "${TOTAL}"
[ "${PASS}" -eq "${TOTAL}" ]
