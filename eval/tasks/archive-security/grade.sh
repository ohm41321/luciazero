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
import os, tempfile, zipfile
from pathlib import Path
import sys
sys.path.insert(0, os.environ["WORK"])
from archive_store import restore

cases = ["../../outside.txt", "/absolute.txt", "..\\outside.txt", "C:/drive.txt"]
for name in cases:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp); archive = root / "x.zip"; output = root / "out"
        with zipfile.ZipFile(archive, "w") as bundle:
            bundle.writestr(name, "bad")
        try:
            restore(archive, output)
        except (ValueError, OSError):
            pass
        else:
            raise AssertionError(name)
        assert not (root / "outside.txt").exists()
PY
then crit no-path-escape pass; else crit no-path-escape fail; fi

if WORK="${WORK}" python3 2>/dev/null <<'PY'
import os, stat, tempfile, zipfile
from pathlib import Path
import sys
sys.path.insert(0, os.environ["WORK"])
from archive_store import restore
with tempfile.TemporaryDirectory() as tmp:
    root = Path(tmp); archive = root / "x.zip"
    link = zipfile.ZipInfo("nested/link")
    link.create_system = 3
    link.external_attr = (stat.S_IFLNK | 0o777) << 16
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr(link, "../../outside")
    try:
        restore(archive, root / "out")
    except (ValueError, OSError):
        pass
    else:
        raise AssertionError("link accepted")
PY
then crit links-rejected pass; else crit links-rejected fail; fi

if WORK="${WORK}" python3 2>/dev/null <<'PY'
import os, tempfile, zipfile
from pathlib import Path
import sys
sys.path.insert(0, os.environ["WORK"])
from archive_store import restore
with tempfile.TemporaryDirectory() as tmp:
    root = Path(tmp); archive = root / "x.zip"; output = root / "out"
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("first/safe.txt", "no partial restore")
        bundle.writestr("later/../../../escape.txt", "bad")
    try:
        restore(archive, output)
    except (ValueError, OSError):
        pass
    else:
        raise AssertionError("unsafe archive accepted")
    assert not (output / "first/safe.txt").exists()
PY
then crit atomic-rejection pass; else crit atomic-rejection fail; fi

if WORK="${WORK}" python3 2>/dev/null <<'PY'
import os, tempfile, zipfile
from pathlib import Path
import sys
sys.path.insert(0, os.environ["WORK"])
from archive_store import restore
with tempfile.TemporaryDirectory() as tmp:
    root = Path(tmp); outside = root / "outside"; outside.mkdir()
    output = root / "out"; output.mkdir(); (output / "jump").symlink_to(outside, target_is_directory=True)
    archive = root / "x.zip"
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("jump/pwned.txt", "bad")
    try:
        restore(archive, output)
    except (ValueError, OSError):
        pass
    else:
        raise AssertionError("destination symlink escape accepted")
    assert not (outside / "pwned.txt").exists()
PY
then crit destination-boundary pass; else crit destination-boundary fail; fi

cp -R "${WORK}/." "${TMP}/probe"
cp "${HERE}/project/archive_store.py" "${TMP}/probe/archive_store.py"
if ! (cd "${TMP}/probe" && python3 -m unittest discover >/dev/null 2>&1); then crit regression-red pass; else crit regression-red fail; fi

if (cd "${WORK}" && python3 - <<'PY'
import pathlib
text = "\n".join(p.read_text(errors="ignore") for p in pathlib.Path(".").glob("test*.py"))
assert "skip" not in text.lower()
assert "archive_store.restore =" not in text
PY
); then crit no-dodges pass; else crit no-dodges fail; fi

printf 'SCORE %s/%s\n' "${PASS}" "${TOTAL}"
[ "${PASS}" -eq "${TOTAL}" ]
