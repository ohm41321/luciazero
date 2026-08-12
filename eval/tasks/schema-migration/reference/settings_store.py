import json
import os
import tempfile
from pathlib import Path

from settings import migrate


def _atomic_write(path, value):
    path = Path(path)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as output:
            json.dump(value, output, sort_keys=True)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
    except BaseException:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise


def load(path):
    path = Path(path)
    with path.open(encoding="utf-8") as source:
        original = json.load(source)
    upgraded = migrate(original)
    if upgraded != original:
        _atomic_write(path, upgraded)
    return upgraded
