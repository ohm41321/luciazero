import os
import shutil
import stat
import zipfile
from pathlib import Path, PurePosixPath


def _safe_target(destination, info):
    name = info.filename.replace("\\", "/")
    path = PurePosixPath(name)
    if not name or not path.parts or path.is_absolute() or path.parts[0].endswith(":"):
        raise ValueError(f"unsafe archive entry: {info.filename!r}")
    if any(part in ("", ".", "..") for part in path.parts):
        raise ValueError(f"unsafe archive entry: {info.filename!r}")
    mode = info.external_attr >> 16
    if stat.S_ISLNK(mode):
        raise ValueError(f"archive links are not allowed: {info.filename!r}")
    target = destination.joinpath(*path.parts)
    try:
        target.resolve().relative_to(destination.resolve())
    except ValueError as exc:
        raise ValueError(f"archive entry escapes destination: {info.filename!r}") from exc
    return target


def restore(zip_path, destination):
    destination = Path(destination)
    with zipfile.ZipFile(zip_path) as bundle:
        planned = [(info, _safe_target(destination, info)) for info in bundle.infolist()]
        destination.mkdir(parents=True, exist_ok=True)
        for info, target in planned:
            if info.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with bundle.open(info) as source, open(target, "wb") as output:
                shutil.copyfileobj(source, output)
