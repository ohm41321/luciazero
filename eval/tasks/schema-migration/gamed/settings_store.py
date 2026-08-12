import json
import os
import tempfile
from pathlib import Path
from settings import migrate


def load(path):
    path = Path(path)
    original = json.loads(path.read_text())
    upgraded = migrate(original)
    if upgraded != original:
        fd, temporary = tempfile.mkstemp(dir=path.parent)
        try:
            with os.fdopen(fd, "w") as output:
                json.dump(upgraded, output)
                output.flush(); os.fsync(output.fileno())
            os.replace(temporary, path)
        except BaseException:
            try: os.unlink(temporary)
            except FileNotFoundError: pass
            raise
    return upgraded
