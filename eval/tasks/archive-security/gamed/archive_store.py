import os
import shutil
import stat
import zipfile
from pathlib import Path, PurePosixPath


def _safe_target(destination, info):
    name = info.filename.replace("\\", "/")
    path = PurePosixPath(name)
    if not name or not path.parts or path.is_absolute() or path.parts[0].endswith(":"):
        raise ValueError("unsafe archive entry")
    if any(part in ("", ".", "..") for part in path.parts):
        raise ValueError("unsafe archive entry")
    if stat.S_ISLNK(info.external_attr >> 16):
        raise ValueError("archive links are not allowed")
    target = destination.joinpath(*path.parts)
    target.resolve().relative_to(destination.resolve())
    return target


def restore(zip_path, destination):
    destination = Path(destination)
    with zipfile.ZipFile(zip_path) as bundle:
        planned = [(info, _safe_target(destination, info)) for info in bundle.infolist()]
        destination.mkdir(parents=True, exist_ok=True)
        for info, target in planned:
            if info.is_dir():
                target.mkdir(parents=True, exist_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                with bundle.open(info) as source, open(target, "wb") as output:
                    shutil.copyfileobj(source, output)
