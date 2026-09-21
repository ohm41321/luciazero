#!/usr/bin/env python3
"""Write a nonce-bound attestation for a canary role instruction file.

The canary wrapper supplies the role name, file, expected digest, nonce, and
acknowledgement pathname in the environment.  A provider process calls this
helper only after it has read the role file and independently calculated its
digest.  The helper rechecks the file and writes one exclusive JSON record;
the wrapper then binds that record to the provider PID and nonce.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import time
from pathlib import Path


METHOD = "luciazero-role-ack-v1"
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def _fail(message: str) -> int:
    print(f"role acknowledgement refused: {message}", file=sys.stderr)
    return 2


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ack-file", required=True, type=Path)
    parser.add_argument("--content-sha256", required=True)
    args = parser.parse_args(argv)

    role = os.environ.get("LUCIAZERO_ROLE_NAME")
    role_file_name = os.environ.get("LUCIAZERO_ROLE_FILE")
    expected_hash = os.environ.get("LUCIAZERO_ROLE_SHA256")
    expected_ack = os.environ.get("LUCIAZERO_ROLE_ACK_FILE")
    nonce = os.environ.get("LUCIAZERO_ROLE_ACK_NONCE")
    marker_name = os.environ.get("LUCIAZERO_ROLE_PROVIDER_MARKER")
    if not all((role, role_file_name, expected_hash, expected_ack, nonce, marker_name)):
        return _fail("wrapper binding environment is incomplete")
    if not SHA256_RE.fullmatch(args.content_sha256):
        return _fail("provider content hash is not sha256")
    if not SHA256_RE.fullmatch(expected_hash):
        return _fail("wrapper content hash is not sha256")
    ack_path = Path(os.path.abspath(args.ack_file))
    if ack_path != Path(os.path.abspath(expected_ack)):
        return _fail("acknowledgement path is not the wrapper path")
    role_file = Path(os.path.abspath(role_file_name))
    if role_file.is_symlink() or not role_file.is_file():
        return _fail("role instruction file is not a regular file")
    try:
        content = role_file.read_bytes()
    except OSError as exc:
        return _fail(f"cannot read role instruction file: {exc}")
    actual_hash = hashlib.sha256(content).hexdigest()
    if actual_hash != expected_hash:
        return _fail("role instruction file changed after wrapper validation")
    if args.content_sha256 != actual_hash:
        return _fail("provider content hash does not match the instruction file")
    marker_path = Path(os.path.abspath(marker_name))
    marker = None
    deadline = time.monotonic() + 2.0
    while time.monotonic() < deadline:
        if marker_path.is_symlink() or (marker_path.exists() and not marker_path.is_file()):
            return _fail("provider marker is not a regular file")
        if marker_path.is_file():
            try:
                marker = json.loads(marker_path.read_text(encoding="utf-8"))
            except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
                if time.monotonic() < deadline:
                    time.sleep(0.01)
                    continue
                return _fail(f"provider marker is unreadable: {exc}")
            break
        time.sleep(0.01)
    if not isinstance(marker, dict) or marker.get("nonce") != nonce:
        return _fail("provider marker is missing or has the wrong nonce")
    provider_pid = marker.get("provider_pid")
    if type(provider_pid) is not int or provider_pid <= 0:
        return _fail("provider marker has an invalid pid")
    payload = {
        "method": METHOD,
        "role": role,
        "sha256": actual_hash,
        "content_sha256": args.content_sha256,
        "nonce": nonce,
        "provider_pid": provider_pid,
    }
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        fd = os.open(ack_path, flags, 0o600)
    except OSError as exc:
        return _fail(f"cannot reserve acknowledgement file: {exc}")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
    except OSError as exc:
        try:
            ack_path.unlink()
        except OSError:
            pass
        return _fail(f"cannot write acknowledgement file: {exc}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
