#!/usr/bin/env python3
"""Create, validate, inspect, render, and consume Lucia Relay artifacts."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import html
import json
import os
from pathlib import Path, PurePosixPath
import re
import shlex
import stat
import subprocess
import sys
import tempfile
from typing import Any, Optional
from urllib.parse import urlsplit, urlunsplit


MANIFEST = "LUCIA_RELAY.json"
HUMAN = "LUCIA_RELAY.md"
RECEIPT = "LUCIA_RELAY_RECEIPT.json"
MAX_MANIFEST_BYTES = 1024 * 1024
MAX_HUMAN_BYTES = 2 * 1024 * 1024
MAX_DEPTH = 20
MAX_NODES = 8192
MAX_STRING_BYTES = 64 * 1024
GIT_TIMEOUT_SECONDS = 30
MAX_GIT_OUTPUT_BYTES = 16 * 1024 * 1024
MAX_UNTRACKED_BYTES = 64 * 1024 * 1024
SHA_RE = re.compile(r"\A[0-9a-f]{40}(?:[0-9a-f]{24})?\Z")
SECRET_PATTERNS = (
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\bnpm_[A-Za-z0-9]{30,}\b"),
    re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{20,}\b"),
    re.compile(r"\bAIza[0-9A-Za-z_-]{30,}\b"),
    re.compile(r"\bglpat-[0-9A-Za-z_-]{20,}\b"),
    re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}\b"),
    re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]{20,}\b"),
    re.compile(r"(?i)\b(?:aws_secret_access_key|secretaccesskey)\s*[:=]\s*[A-Za-z0-9/+=]{40}\b"),
    re.compile(r"(?i)\b(?:https?|ssh|postgres(?:ql)?|mysql|mongodb(?:\+srv)?|redis)://[^\s/@:]+:[^\s/@]+@"),
    re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b"),
)
POSIX_ABSOLUTE_PATH = re.compile(
    r"(?<![A-Za-z0-9+.\-:/~$%])/(?!/)[^\s\"'`<>]+"
)
WINDOWS_ABSOLUTE_PATH = re.compile(r"(?<![A-Za-z0-9])[A-Za-z]:[\\/][^\s\"'`<>]+")
UNC_PATH = re.compile(r"(?<!\\)\\\\[^\\\s\"'`<>]+\\[^\s\"'`<>]+")
HOME_PATH = re.compile(r"(?<![A-Za-z0-9])(?:~|\$HOME|%USERPROFILE%)[\\/][^\s\"'`<>]+")
FILE_URI_PATH = re.compile(r"\bfile:[^\s\"'`<>]+", re.IGNORECASE)


def git(root: Path, *args: str) -> tuple[int, str]:
    git_env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    git_env["GIT_TERMINAL_PROMPT"] = "0"
    with tempfile.TemporaryFile() as output:
        try:
            proc = subprocess.run(
                ["git", "-C", str(root), *args],
                stdin=subprocess.DEVNULL,
                stdout=output,
                stderr=subprocess.DEVNULL,
                check=False,
                timeout=GIT_TIMEOUT_SECONDS,
                env=git_env,
            )
        except subprocess.TimeoutExpired:
            return 124, ""
        size = output.tell()
        if size > MAX_GIT_OUTPUT_BYTES:
            return 125, ""
        output.seek(0)
        text = output.read().decode("utf-8", errors="surrogateescape").rstrip("\n")
    return proc.returncode, text


def repository_snapshot(root: Path) -> dict[str, Any]:
    rc, top = git(root, "rev-parse", "--show-toplevel")
    if rc != 0:
        return {
            "head": None,
            "branch": None,
            "dirty": None,
            "diff_sha256": None,
            "known_remote_refs": [],
        }
    repo = Path(top)
    snapshot_errors: list[str] = []
    head_rc, head = git(repo, "rev-parse", "HEAD")
    _, branch = git(repo, "branch", "--show-current")
    exclusions = (
        "--", ".", f":(exclude){MANIFEST}", f":(exclude){HUMAN}",
        f":(exclude){RECEIPT}",
    )
    if head_rc == 0:
        modified_rc, raw_modified = git(repo, "diff", "--name-only", "-z", "HEAD", *exclusions)
        diff_rc, diff = git(repo, "diff", "--binary", "HEAD", *exclusions)
        if modified_rc != 0 or diff_rc != 0:
            snapshot_errors.append("Git diff failed, timed out, or exceeded its output budget")
    else:
        staged_names_rc, raw_staged = git(repo, "diff", "--cached", "--name-only", "-z", *exclusions)
        unstaged_names_rc, raw_unstaged = git(repo, "diff", "--name-only", "-z", *exclusions)
        raw_modified = raw_staged + raw_unstaged
        staged_diff_rc, staged_diff = git(repo, "diff", "--cached", "--binary", "--root", *exclusions)
        unstaged_diff_rc, unstaged_diff = git(repo, "diff", "--binary", *exclusions)
        if any(rc != 0 for rc in (staged_names_rc, unstaged_names_rc, staged_diff_rc, unstaged_diff_rc)):
            snapshot_errors.append("Git diff failed, timed out, or exceeded its output budget")
        diff = staged_diff + "\n" + unstaged_diff
    untracked_rc, raw_untracked = git(repo, "ls-files", "--others", "--exclude-standard", "-z")
    if untracked_rc != 0:
        snapshot_errors.append("Git untracked-file scan failed, timed out, or exceeded its output budget")
    modified = sorted(set(item for item in raw_modified.split("\0") if item))
    untracked = [
        item for item in raw_untracked.split("\0")
        if item and item not in (MANIFEST, HUMAN, RECEIPT)
    ]
    digest = hashlib.sha256(diff.encode("utf-8", errors="surrogateescape"))
    untracked_bytes = 0
    untracked_budget_exhausted = False
    for relative in sorted(untracked):
        digest.update(b"\0untracked\0" + relative.encode("utf-8", errors="surrogateescape") + b"\0")
        candidate = repo / relative
        try:
            if candidate.is_symlink():
                digest.update(b"symlink\0" + os.readlink(candidate).encode("utf-8", errors="surrogateescape"))
            elif candidate.is_file() and not untracked_budget_exhausted:
                with candidate.open("rb") as handle:
                    for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                        untracked_bytes += len(chunk)
                        if untracked_bytes > MAX_UNTRACKED_BYTES:
                            snapshot_errors.append("untracked files exceed the fingerprint byte budget")
                            untracked_budget_exhausted = True
                            break
                        digest.update(chunk)
            else:
                # FIFOs, sockets, and devices must affect the fingerprint but
                # must never be opened: reading a FIFO can block forever and a
                # device can have side effects or an unbounded stream.
                mode = candidate.lstat().st_mode
                digest.update(f"special:{mode}".encode())
        except OSError as exc:
            digest.update(f"unreadable:{exc.errno}".encode())
    fingerprint = digest.hexdigest()
    known_remote_refs: list[str] = []
    if head_rc == 0:
        remote_refs_rc, remote_refs = git(
            repo,
            "for-each-ref",
            "--contains=HEAD",
            "--format=%(refname)",
            "refs/remotes",
        )
        if remote_refs_rc != 0:
            snapshot_errors.append("Git remote-ref scan failed, timed out, or exceeded its output budget")
        known_remote_refs = sorted(
            ref[len("refs/remotes/") :]
            for ref in remote_refs.splitlines()
            if ref.startswith("refs/remotes/") and not ref.endswith("/HEAD")
        )
    return {
        "head": head if head_rc == 0 else None,
        "branch": branch or "(detached)",
        "dirty": bool(modified or untracked),
        "diff_sha256": fingerprint,
        "known_remote_refs": known_remote_refs,
        "files": {"modified": modified, "untracked": untracked},
        "_errors": sorted(set(snapshot_errors)),
    }


def sanitize_remote_url(value: str) -> Optional[str]:
    value = value.strip()
    if not value or value.startswith(("/", "./", "../", "~", "file:")):
        return None
    if re.fullmatch(r"[A-Za-z0-9._-]+@[A-Za-z0-9.-]+:[A-Za-z0-9._/+~-]+", value):
        return value
    parsed = urlsplit(value)
    if parsed.scheme not in ("https", "ssh") or not parsed.hostname:
        return None
    user = parsed.username if parsed.scheme == "ssh" else None
    host = parsed.hostname
    try:
        port = parsed.port
    except ValueError:
        return None
    if port:
        host = f"{host}:{port}"
    netloc = f"{user}@{host}" if user else host
    return urlunsplit((parsed.scheme, netloc, parsed.path, "", ""))


def git_url_rewrite_error(root: Path, remote_url: str) -> Optional[str]:
    rc, rewrites = git(root, "config", "--get-regexp", r"^url\..*\.(insteadOf|pushInsteadOf)$")
    if rc not in (0, 1):
        return "cannot safely inspect Git URL rewrite rules"
    if rc == 0:
        for line in rewrites.splitlines():
            parts = line.split(None, 1)
            if len(parts) == 2 and remote_url.startswith(parts[1]):
                return "Git URL rewrite rules apply to the relay repository"
    return None


def git_transport_override_error(root: Path, remote_name: str, remote_url: str) -> Optional[str]:
    rewrite_error = git_url_rewrite_error(root, remote_url)
    if rewrite_error:
        return rewrite_error
    for key in (
        "core.sshCommand",
        f"remote.{remote_name}.uploadpack",
        f"remote.{remote_name}.receivepack",
    ):
        rc, value = git(root, "config", "--get-all", key)
        if rc not in (0, 1):
            return f"cannot safely inspect Git transport override {key}"
        if rc == 0 and value:
            return f"Git transport override {key} applies to the relay repository"
    return None


def remote_snapshot(root: Path, head: str, base: str) -> dict[str, Any]:
    rc, upstream = git(root, "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{upstream}")
    if rc != 0 or "/" not in upstream:
        raise ValueError("cross-machine draft requires a configured upstream branch")
    remote_name, branch = upstream.split("/", 1)
    remote_ref = f"refs/heads/{branch}"
    rc, remote_urls = git(root, "config", "--get-all", f"remote.{remote_name}.url")
    configured_urls = [value for value in remote_urls.splitlines() if value]
    if rc != 0 or len(configured_urls) != 1:
        raise ValueError("cross-machine draft requires exactly one upstream remote URL")
    remote_url = configured_urls[0]
    sanitized_url = sanitize_remote_url(remote_url)
    if sanitized_url is None:
        raise ValueError("cross-machine draft requires a portable HTTPS or SSH upstream URL")
    rc, push_urls = git(root, "config", "--get-all", f"remote.{remote_name}.pushurl")
    if rc not in (0, 1):
        raise ValueError("cross-machine draft cannot safely inspect remote push URLs")
    if rc == 0 and push_urls:
        raise ValueError("cross-machine draft rejects a separate remote push URL")
    transport_error = git_transport_override_error(root, remote_name, remote_url)
    if transport_error:
        raise ValueError(f"cross-machine draft rejects its upstream: {transport_error}")
    rc, remote_lines = git(root, "ls-remote", "--exit-code", remote_name, remote_ref)
    if rc != 0:
        raise ValueError("cross-machine draft cannot verify the upstream ref; push it first")
    remote_oid = next(
        (line.split("\t", 1)[0] for line in remote_lines.splitlines() if line.endswith("\t" + remote_ref)),
        "",
    )
    if remote_oid != head:
        raise ValueError("cross-machine draft HEAD is not the current remote ref; push it first")
    transfer_ref = f"refs/tags/lucia-relay-{head}"
    rc, transfer_lines = git(root, "ls-remote", remote_name, transfer_ref)
    if rc != 0:
        raise ValueError("cross-machine draft cannot safely inspect its transfer tag")
    transfer_oid = next(
        (line.split("\t", 1)[0] for line in transfer_lines.splitlines() if line.endswith("\t" + transfer_ref)),
        "",
    )
    if transfer_oid and transfer_oid != head:
        raise ValueError("cross-machine commit-named transfer tag points at another commit")
    if not transfer_oid:
        rc, _ = git(root, "push", "--porcelain", remote_name, f"{head}:{transfer_ref}")
        if rc != 0:
            raise ValueError("cross-machine draft could not publish its transfer tag")
        rc, transfer_lines = git(root, "ls-remote", "--exit-code", remote_name, transfer_ref)
        transfer_oid = next(
            (line.split("\t", 1)[0] for line in transfer_lines.splitlines() if line.endswith("\t" + transfer_ref)),
            "",
        ) if rc == 0 else ""
        if transfer_oid != head:
            raise ValueError("cross-machine transfer ref was not published at HEAD")
    rc, base_oid = git(root, "rev-parse", f"{base}^{{commit}}")
    if rc != 0 or not SHA_RE.fullmatch(base_oid):
        raise ValueError("cross-machine --base must resolve to a commit")
    rc, _ = git(root, "merge-base", "--is-ancestor", base_oid, head)
    if rc != 0:
        raise ValueError("cross-machine --base must be an ancestor of HEAD")
    rc, changed = git(root, "diff", "--name-only", "-z", "--no-renames", base_oid, head, "--")
    if rc != 0:
        raise ValueError("cross-machine draft could not list committed task files")
    changed_files = sorted(item for item in changed.split("\0") if item)
    return {
        "url": sanitized_url,
        "name": remote_name,
        "ref": transfer_ref,
        "oid": transfer_oid,
        "source_ref": remote_ref,
        "base": base_oid,
        "changed_files": changed_files,
    }


def envelope_remote_errors(root: Path, data: dict[str, Any]) -> list[str]:
    repository = data.get("repository") if isinstance(data.get("repository"), dict) else {}
    remote = repository.get("remote") if isinstance(repository.get("remote"), dict) else {}
    name, expected_url, ref, oid = (
        remote.get("name"), remote.get("url"), remote.get("ref"), remote.get("oid")
    )
    if not all(nonempty(value) for value in (name, expected_url, ref, oid)):
        return ["trusted envelope lacks complete remote metadata"]
    rc, configured_urls = git(root, "config", "--get-all", f"remote.{name}.url")
    urls = [value for value in configured_urls.splitlines() if value]
    if rc != 0 or len(urls) != 1 or sanitize_remote_url(urls[0]) != expected_url:
        return ["trusted envelope repository URL no longer matches configured upstream"]
    configured_url = urls[0]
    transport_error = git_transport_override_error(root, str(name), configured_url)
    if transport_error:
        return [f"trusted envelope rejects repository transport: {transport_error}"]
    rc, push_urls = git(root, "config", "--get-all", f"remote.{name}.pushurl")
    if rc not in (0, 1):
        return ["trusted envelope cannot safely inspect remote push URLs"]
    if rc == 0 and push_urls:
        return ["trusted envelope rejects a separate remote push URL"]
    rc, remote_lines = git(root, "ls-remote", "--exit-code", str(name), str(ref))
    if rc != 0:
        return ["trusted envelope cannot reach its recorded remote ref"]
    live_oid = next(
        (line.split("\t", 1)[0] for line in remote_lines.splitlines() if line.endswith("\t" + str(ref))),
        "",
    )
    if live_oid != oid or oid != repository.get("head"):
        return ["trusted envelope remote ref no longer resolves to its recorded HEAD"]
    return []


def draft(root: Path, recipient: str, base: Optional[str] = None) -> dict[str, Any]:
    snap = repository_snapshot(root)
    snapshot_errors = snap.pop("_errors", [])
    files = snap.pop("files", {"modified": [], "untracked": []})
    schema = 2
    if recipient == "cross-machine":
        if not base:
            raise ValueError("cross-machine draft requires --base <task-base-revision>")
        if snapshot_errors:
            raise ValueError("; ".join(snapshot_errors))
        if snap.get("head") is None or snap.get("dirty") is not False:
            raise ValueError("cross-machine draft requires a clean committed worktree")
        remote = remote_snapshot(root, str(snap["head"]), base)
        snap["remote"] = {
            key: remote[key] for key in ("url", "name", "ref", "oid", "source_ref")
        }
        snap["base"] = remote["base"]
        snap["changed_files"] = remote["changed_files"]
        files = {"modified": [], "untracked": []}
        schema = 3
    return {
        "schema": schema,
        "kind": "luciazero-relay",
        "created_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "route": {"recipient": recipient},
        "source": {
            "harness": os.environ.get("LUCIAZERO_HARNESS", "unknown"),
            "agent": None,
            "session": None,
        },
        "repository": snap,
        "goal": "",
        "state": {
            "done": [],
            "in_progress": [],
            "next_step": {"kind": "command", "value": ""},
        },
        "verification": [],
        "knowledge": {"read_first": [], "inline": [], "hypotheses": [], "landmines": []},
        "files": files,
    }


def structure_errors(value: Any) -> list[str]:
    errors: list[str] = []
    stack = [(value, 0)]
    nodes = 0
    while stack:
        item, depth = stack.pop()
        nodes += 1
        if nodes > MAX_NODES:
            return [f"artifact exceeds {MAX_NODES} values"]
        if depth > MAX_DEPTH:
            return [f"artifact exceeds nesting depth {MAX_DEPTH}"]
        if isinstance(item, str):
            try:
                encoded = item.encode("utf-8")
            except UnicodeEncodeError:
                errors.append("artifact contains invalid Unicode surrogate data")
                continue
            if len(encoded) > MAX_STRING_BYTES:
                errors.append(f"artifact string exceeds {MAX_STRING_BYTES} bytes")
        elif isinstance(item, dict):
            stack.extend((key, depth + 1) for key in item.keys())
            stack.extend((nested, depth + 1) for nested in item.values())
        elif isinstance(item, list):
            stack.extend((nested, depth + 1) for nested in item)
    return errors


def load_json_object(path: Path, label: str, max_bytes: int = MAX_MANIFEST_BYTES) -> dict[str, Any]:
    if path.is_symlink():
        raise ValueError(f"{label} must not be a symlink")
    try:
        info = path.stat()
        if not stat.S_ISREG(info.st_mode):
            raise ValueError(f"{label} must be a regular file")
        if info.st_size > max_bytes:
            raise ValueError(f"{label} exceeds {max_bytes} bytes")
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ValueError(f"{label} does not exist") from exc
    except (OSError, json.JSONDecodeError, RecursionError) as exc:
        raise ValueError(f"cannot read {label}: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{label} must contain a JSON object")
    limits = structure_errors(value)
    if limits:
        raise ValueError(f"{label} {limits[0]}")
    return value


def load_manifest(root: Path) -> dict[str, Any]:
    path = root / MANIFEST
    return load_json_object(path, MANIFEST)


def read_bounded_text(path: Path, label: str, max_bytes: int) -> str:
    if path.is_symlink():
        raise ValueError(f"{label} must not be a symlink")
    try:
        info = path.stat()
        if not stat.S_ISREG(info.st_mode):
            raise ValueError(f"{label} must be a regular file")
        if info.st_size > max_bytes:
            raise ValueError(f"{label} exceeds {max_bytes} bytes")
        return path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise ValueError(f"{label} does not exist") from exc
    except (OSError, UnicodeError) as exc:
        raise ValueError(f"cannot read {label}: {exc}") from exc


def nonempty(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def string_values(value: Any):
    stack = [value]
    while stack:
        item = stack.pop()
        if isinstance(item, str):
            yield item
        elif isinstance(item, dict):
            stack.extend(item.values())
        elif isinstance(item, list):
            stack.extend(item)


def machine_paths(data: dict[str, Any]) -> list[str]:
    found: set[str] = set()
    for value in string_values(data):
        for pattern in (
            POSIX_ABSOLUTE_PATH,
            WINDOWS_ABSOLUTE_PATH,
            UNC_PATH,
            HOME_PATH,
            FILE_URI_PATH,
        ):
            found.update(match.group(0) for match in pattern.finditer(value))
    return sorted(found)


def repo_pointer(value: Any) -> Optional[str]:
    if not nonempty(value):
        return None
    # A short annotation may follow the path, as in
    # "docs/lessons.md — quoted delimiters are parser syntax".
    candidate = str(value).split(" — ", 1)[0].strip()
    path = PurePosixPath(candidate)
    if (
        not candidate
        or "\\" in candidate
        or ":" in candidate
        or path.is_absolute()
        or any(part in ("", ".", "..") for part in path.parts)
    ):
        return None
    return candidate


def safe_command_argv(value: Any) -> Optional[list[str]]:
    if not nonempty(value):
        return None
    try:
        argv = shlex.split(str(value))
    except ValueError:
        return None
    shell_tokens = {"|", "||", "&&", ";", ">", ">>", "<", "2>", "&"}
    if not argv or any(token in shell_tokens for token in argv):
        return None
    executable = PurePosixPath(argv[0].replace("\\", "/")).name.casefold()
    if executable in {"sh", "bash", "zsh", "fish", "cmd", "cmd.exe", "powershell", "pwsh", "env", "xargs"}:
        return None
    if executable == "git" and any(token == "-c" or token.startswith("--config-env=") for token in argv[1:]):
        return None
    if executable in {"python", "python3", "node", "ruby", "perl"} and any(
        token in ("-c", "-e", "--eval") for token in argv[1:]
    ):
        return None
    return argv


def repository_path_error(root: Path, head: str, path: str, base: Optional[str] = None) -> Optional[str]:
    if repo_pointer(path) != path:
        return f"must be one contained repo-relative path: {path}"
    if not SHA_RE.fullmatch(head) or (base is not None and not SHA_RE.fullmatch(base)):
        return "cannot be checked without valid immutable repository OIDs"
    refs = [head] + ([base] if nonempty(base) else [])
    saw_entry = False
    for ref in refs:
        rc, entry = git(root, "ls-tree", str(ref), "--", path)
        if rc != 0 or not entry:
            continue
        saw_entry = True
        metadata = entry.split("\t", 1)[0].split()
        if len(metadata) < 2 or metadata[1] != "blob" or metadata[0] == "120000":
            return f"must resolve to a regular tracked blob: {path}"
        return None
    if not saw_entry:
        return f"is not present in the relay base or HEAD: {path}"
    return None


def cross_machine_repository_errors(root: Path, data: dict[str, Any]) -> list[str]:
    route = data.get("route") if isinstance(data.get("route"), dict) else {}
    if route.get("recipient") != "cross-machine":
        return []
    repository = data.get("repository") if isinstance(data.get("repository"), dict) else {}
    head = repository.get("head")
    base = repository.get("base")
    knowledge = data.get("knowledge") if isinstance(data.get("knowledge"), dict) else {}
    read_first = knowledge.get("read_first")
    if not isinstance(read_first, list):
        return []
    errors: list[str] = []
    for index, item in enumerate(read_first):
        path = repo_pointer(item)
        if path is None:
            errors.append(
                f"knowledge.read_first[{index}] must start with one repo-relative path; move prose or local knowledge to knowledge.inline"
            )
            continue
        if not nonempty(head):
            errors.append(f"knowledge.read_first[{index}] cannot be checked without repository.head")
            continue
        problem = repository_path_error(root, str(head), path)
        if problem:
            errors.append(f"knowledge.read_first[{index}] {problem}")
    changed = repository.get("changed_files")
    if isinstance(changed, list):
        for index, item in enumerate(changed):
            if not isinstance(item, str):
                continue
            problem = repository_path_error(root, str(head), item, str(base) if nonempty(base) else None)
            if problem:
                errors.append(f"repository.changed_files[{index}] {problem}")
    return errors


def receiver_repository_url_error(root: Path, trusted_url: str) -> Optional[str]:
    rc, names = git(root, "remote")
    if rc != 0:
        return "receiver cannot inspect configured Git remotes"
    for name in names.splitlines():
        rc, configured_values = git(root, "config", "--get-all", f"remote.{name}.url")
        configured = [value for value in configured_values.splitlines() if value]
        if rc == 0 and configured == [trusted_url]:
            transport_error = git_transport_override_error(root, name, trusted_url)
            if transport_error:
                return f"receiver rejects trusted repository transport: {transport_error}"
            push_rc, push_urls = git(root, "config", "--get-all", f"remote.{name}.pushurl")
            if push_rc not in (0, 1):
                return "receiver cannot safely inspect trusted remote push URLs"
            if push_rc == 0 and push_urls:
                return "receiver trusted Git remote has a separate push URL"
            return None
    return "receiver clone has no Git remote matching the trusted repository URL"


def validate(data: dict[str, Any]) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    schema = data.get("schema")
    if type(schema) is not int or schema not in (1, 2, 3):
        errors.append("schema must equal 1, 2, or 3")
    if data.get("kind") != "luciazero-relay":
        errors.append("kind must equal luciazero-relay")
    recipient = None
    route = data.get("route")
    if schema in (2, 3):
        if not isinstance(route, dict):
            errors.append("route must be an object")
        else:
            recipient = route.get("recipient")
            if recipient not in ("same-machine", "cross-machine"):
                errors.append("route.recipient must be same-machine or cross-machine")
    elif schema == 1:
        warnings.append(
            "legacy schema 1 has no recipient location; treat it as same-machine and create a new relay before routing cross-machine"
        )
    if not nonempty(data.get("created_at")):
        errors.append("created_at is required")
    else:
        try:
            created = dt.datetime.fromisoformat(str(data["created_at"]).replace("Z", "+00:00"))
            if created.tzinfo is None:
                errors.append("created_at must include a timezone")
        except ValueError:
            errors.append("created_at must be ISO-8601")
    if not nonempty(data.get("goal")):
        errors.append("goal is required")

    state = data.get("state")
    if not isinstance(state, dict):
        errors.append("state must be an object")
    else:
        for key in ("done", "in_progress"):
            if not isinstance(state.get(key), list):
                errors.append(f"state.{key} must be an array")
        next_step = state.get("next_step")
        if not isinstance(next_step, dict):
            errors.append("state.next_step must be an object")
        else:
            if next_step.get("kind") not in ("command", "edit", "decision"):
                errors.append("state.next_step.kind must be command, edit, or decision")
            if not nonempty(next_step.get("value")):
                errors.append("state.next_step.value must be one literal next action")

    verification = data.get("verification")
    if not isinstance(verification, list):
        errors.append("verification must be an array")
    else:
        for index, item in enumerate(verification):
            prefix = f"verification[{index}]"
            if not isinstance(item, dict):
                errors.append(f"{prefix} must be an object")
                continue
            if not nonempty(item.get("command")):
                errors.append(f"{prefix}.command is required")
            elif schema == 3 and recipient == "cross-machine" and safe_command_argv(item.get("command")) is None:
                errors.append(f"{prefix}.command must be one argv-safe command without shell operators")
            if not isinstance(item.get("exit_code"), int):
                errors.append(f"{prefix}.exit_code must be an integer")
            if not nonempty(item.get("decisive_line")):
                errors.append(f"{prefix}.decisive_line is required")
            if not nonempty(item.get("run_at")):
                errors.append(f"{prefix}.run_at is required")
            else:
                try:
                    run_at = dt.datetime.fromisoformat(str(item["run_at"]).replace("Z", "+00:00"))
                    if run_at.tzinfo is None:
                        errors.append(f"{prefix}.run_at must include a timezone")
                except ValueError:
                    errors.append(f"{prefix}.run_at must be ISO-8601")

    knowledge = data.get("knowledge")
    if not isinstance(knowledge, dict):
        errors.append("knowledge must be an object")
    else:
        for key in ("read_first", "hypotheses", "landmines"):
            if not isinstance(knowledge.get(key), list):
                errors.append(f"knowledge.{key} must be an array")
        inline = knowledge.get("inline")
        if schema in (2, 3) and not isinstance(inline, list):
            errors.append("knowledge.inline must be an array")
        elif isinstance(inline, list):
            for index, item in enumerate(inline):
                prefix = f"knowledge.inline[{index}]"
                if not isinstance(item, dict):
                    errors.append(f"{prefix} must be an object")
                    continue
                if not nonempty(item.get("label")) or not nonempty(item.get("content")):
                    errors.append(f"{prefix} requires label and content")
        hypotheses = knowledge.get("hypotheses")
        if isinstance(hypotheses, list):
            for index, item in enumerate(hypotheses):
                prefix = f"knowledge.hypotheses[{index}]"
                if not isinstance(item, dict):
                    errors.append(f"{prefix} must be an object")
                    continue
                if not all(nonempty(item.get(key)) for key in ("id", "claim", "evidence")):
                    errors.append(f"{prefix} requires id, claim, and evidence")
                if item.get("status") not in ("untested", "supported", "refuted"):
                    errors.append(f"{prefix}.status must be untested, supported, or refuted")

    source = data.get("source")
    if not isinstance(source, dict) or not nonempty(source.get("harness")):
        errors.append("source.harness is required")
    repository = data.get("repository")
    if not isinstance(repository, dict):
        errors.append("repository must be an object")
    else:
        for key in ("head", "branch", "dirty", "diff_sha256"):
            if key not in repository:
                errors.append(f"repository.{key} is required")
        if schema in (2, 3):
            known_remote_refs = repository.get("known_remote_refs")
            if not isinstance(known_remote_refs, list):
                errors.append("repository.known_remote_refs must be an array")
            elif not all(nonempty(ref) for ref in known_remote_refs):
                errors.append("repository.known_remote_refs entries must be non-empty strings")
        if schema == 3:
            base = repository.get("base")
            changed_files = repository.get("changed_files")
            remote = repository.get("remote")
            if not nonempty(base) or not SHA_RE.fullmatch(str(base)):
                errors.append("repository.base must be an immutable commit OID")
            if not isinstance(changed_files, list) or not all(
                isinstance(path, str) and repo_pointer(path) == path for path in changed_files
            ):
                errors.append("repository.changed_files must contain repo-relative paths")
            if not isinstance(remote, dict):
                errors.append("repository.remote must be an object")
            else:
                url = remote.get("url")
                if not nonempty(url) or sanitize_remote_url(str(url)) != url:
                    errors.append("repository.remote.url must be a sanitized portable HTTPS or SSH URL")
                if not nonempty(remote.get("name")):
                    errors.append("repository.remote.name is required")
                if not nonempty(remote.get("ref")) or not str(remote.get("ref")).startswith(("refs/heads/", "refs/tags/")):
                    errors.append("repository.remote.ref must be a full heads/tags ref")
                if not nonempty(remote.get("source_ref")) or not str(remote.get("source_ref")).startswith("refs/heads/"):
                    errors.append("repository.remote.source_ref must be a full branch ref")
                if not nonempty(remote.get("oid")) or not SHA_RE.fullmatch(str(remote.get("oid"))):
                    errors.append("repository.remote.oid must be an immutable commit OID")
                if remote.get("oid") != repository.get("head"):
                    errors.append("repository.remote.oid must equal repository.head")
    files = data.get("files")
    if not isinstance(files, dict):
        errors.append("files must be an object")
    else:
        for key in ("modified", "untracked"):
            if not isinstance(files.get(key), list):
                errors.append(f"files.{key} must be an array")
            elif not all(isinstance(path, str) and repo_pointer(path) == path for path in files.get(key)):
                errors.append(f"files.{key} must contain repo-relative paths")

    serialized = json.dumps(data, ensure_ascii=False)
    if any(pattern.search(serialized) for pattern in SECRET_PATTERNS):
        errors.append("possible secret or private key detected; remove it before routing")
    local_paths = machine_paths(data)
    if schema == 3 and recipient != "cross-machine":
        errors.append("schema 3 route.recipient must be cross-machine")
    if recipient == "cross-machine" or schema == 3:
        if schema != 3:
            errors.append("cross-machine relay requires schema 3; re-draft it after push")
        if local_paths:
            errors.append(
                "cross-machine relay contains machine-only paths: "
                + ", ".join(local_paths[:3])
                + (" ..." if len(local_paths) > 3 else "")
                + "; use pushed repo-relative paths or copy the knowledge into knowledge.inline"
            )
        if isinstance(repository, dict):
            if repository.get("dirty") is True:
                errors.append(
                    "cross-machine relay cannot depend on a dirty worktree; commit and push task files, then keep machine-local knowledge in knowledge.inline"
                )
            if schema == 3 and isinstance(files, dict) and (files.get("modified") or files.get("untracked")):
                errors.append("cross-machine schema 3 files.modified/untracked must be empty after commit")
        if not isinstance(verification, list) or not verification:
            errors.append("cross-machine relay requires at least one verification entry")
        if isinstance(knowledge, dict) and not any(
            knowledge.get(key) for key in ("read_first", "inline", "hypotheses", "landmines")
        ):
            errors.append("cross-machine relay requires portable knowledge")
    elif schema == 1 and local_paths:
        warnings.append("legacy relay contains a machine-specific path and is not portable cross-machine")
    return errors, warnings


def markdown_text(value: Any) -> str:
    """Render untrusted text as Markdown text, never as Markdown structure."""
    escaped = html.escape(str(value), quote=True)
    return re.sub(r"([\\`*_[\]{}()#+.!|<>-])", r"\\\1", escaped)


def code_inline(value: Any) -> str:
    return f"<code>{html.escape(str(value), quote=True)}</code>"


def bullets(values: Any, empty: str = "None recorded.") -> list[str]:
    if not isinstance(values, list) or not values:
        return [empty]
    lines = []
    for value in values:
        if isinstance(value, str):
            lines.append(f"- {markdown_text(value)}")
        else:
            lines.append(f"- {code_inline(json.dumps(value, ensure_ascii=False, sort_keys=True))}")
    return lines


def inline_knowledge(values: Any) -> list[str]:
    if not isinstance(values, list) or not values:
        return ["None recorded."]
    lines = []
    for item in values:
        if not isinstance(item, dict):
            lines.append(f"- {code_inline(json.dumps(item, ensure_ascii=False, sort_keys=True))}")
            continue
        label = markdown_text(item.get("label", "unlabelled"))
        content = markdown_text(item.get("content", "")).replace("\n", "<br>\n")
        lines.append(f"- {label}: {content}")
    return lines


def table_cell(value: Any) -> str:
    text = str(value if value is not None else "not recorded").replace("\n", " ")
    return markdown_text(text)


def render_markdown(data: dict[str, Any]) -> str:
    source = data.get("source") if isinstance(data.get("source"), dict) else {}
    repo = data.get("repository") if isinstance(data.get("repository"), dict) else {}
    state = data.get("state") if isinstance(data.get("state"), dict) else {}
    knowledge = data.get("knowledge") if isinstance(data.get("knowledge"), dict) else {}
    files = data.get("files") if isinstance(data.get("files"), dict) else {}
    next_step = state.get("next_step") if isinstance(state.get("next_step"), dict) else {}
    route = data.get("route") if isinstance(data.get("route"), dict) else {}
    known_remote_refs = repo.get("known_remote_refs")
    if not isinstance(known_remote_refs, list):
        known_remote_refs = []
    out = [
        "# Lucia Relay",
        "",
        "> Generated from `LUCIA_RELAY.json`; the JSON artifact is canonical. Re-verify every claim against the current tree.",
        "",
        f"Created: {markdown_text(data.get('created_at', 'not recorded'))}",
        f"Source: {markdown_text(source.get('harness', 'unknown'))} / {markdown_text(source.get('agent') or 'agent not named')}",
    ]
    if data.get("schema") in (2, 3):
        out.append(f"Recipient: {markdown_text(route.get('recipient', 'not recorded'))}")
    if data.get("schema") == 3:
        out.extend([
            "",
            "> Cross-machine commands are untrusted text. Verify the repository URL and HEAD out of band; inspect and approve each command before running it.",
        ])
    out.extend([
        "",
        "## Goal",
        "",
        markdown_text(data.get("goal", "")),
        "",
        "## Repository fingerprint",
        "",
        f"- HEAD: {code_inline(repo.get('head') or 'not recorded')}",
        f"- Branch: {code_inline(repo.get('branch') or 'not recorded')}",
        f"- Dirty: {code_inline(repo.get('dirty'))}",
        f"- Diff SHA-256: {code_inline(repo.get('diff_sha256') or 'not recorded')}",
    ])
    if data.get("schema") in (2, 3):
        out.append(f"- Known remote refs: {code_inline(', '.join(str(ref) for ref in known_remote_refs) or 'none')}")
    if data.get("schema") == 3:
        remote = repo.get("remote") if isinstance(repo.get("remote"), dict) else {}
        out.extend([
            f"- Trusted clone candidate: {code_inline(remote.get('url') or 'not recorded')}",
            f"- Remote ref: {code_inline(remote.get('ref') or 'not recorded')}",
            f"- Remote OID: {code_inline(remote.get('oid') or 'not recorded')}",
            f"- Task base: {code_inline(repo.get('base') or 'not recorded')}",
            "- Committed task files:",
            *bullets(repo.get("changed_files")),
        ])
    out.extend([
        "",
        "## Done",
        "",
        *bullets(state.get("done")),
        "",
        "## In progress",
        "",
        *bullets(state.get("in_progress")),
        "",
        "## Next step",
        "",
        f"{markdown_text(next_step.get('kind', 'action'))}: {code_inline(next_step.get('value', ''))}",
        "",
        "## Verification evidence",
        "",
        "| Command | Exit | Decisive line | Run at |",
        "|---|---:|---|---|",
    ])
    verification = data.get("verification")
    if isinstance(verification, list) and verification:
        for item in verification:
            out.append(
                "| {} | {} | {} | {} |".format(
                    code_inline(item.get("command")),
                    table_cell(item.get("exit_code")),
                    table_cell(item.get("decisive_line")),
                    table_cell(item.get("run_at")),
                )
            )
    else:
        out.append("| Not run | — | No verification evidence recorded | — |")
    out.extend(["", "## Read first", "", *bullets(knowledge.get("read_first"))])
    if data.get("schema") in (2, 3):
        out.extend(["", "## Inline knowledge", "", *inline_knowledge(knowledge.get("inline"))])
    out.extend(["", "## Hypotheses", "", *bullets(knowledge.get("hypotheses"))])
    out.extend(["", "## Landmines", "", *bullets(knowledge.get("landmines"))])
    out.extend(["", "## Files", "", "Modified:", "", *bullets(files.get("modified"))])
    out.extend(["", "Untracked:", "", *bullets(files.get("untracked")), ""])
    return "\n".join(out)


def inspect(
    root: Path,
    data: dict[str, Any],
    check_human: bool = False,
    expected_recipient: Optional[str] = None,
    trusted_head: Optional[str] = None,
    trusted_manifest_sha256: Optional[str] = None,
    trusted_repository_url: Optional[str] = None,
    receiver_context: bool = False,
) -> dict[str, Any]:
    errors, warnings = validate(data)
    if check_human:
        human = root / HUMAN
        try:
            actual = read_bounded_text(human, HUMAN, MAX_HUMAN_BYTES)
        except ValueError as exc:
            errors.append(str(exc))
        else:
            if actual != render_markdown(data):
                errors.append(f"{HUMAN} does not match {MANIFEST}; regenerate it before trusting or consuming the relay")
    current = repository_snapshot(root)
    for snapshot_error in current.pop("_errors", []):
        errors.append(snapshot_error)
    errors.extend(cross_machine_repository_errors(root, data))
    recorded = data.get("repository") if isinstance(data.get("repository"), dict) else {}
    route = data.get("route") if isinstance(data.get("route"), dict) else {}
    recipient = route.get("recipient")
    trust_required = False
    cross_receiver = receiver_context and (data.get("schema") == 3 or recipient == "cross-machine")
    if cross_receiver and expected_recipient is None:
        errors.append("receiver must declare --expected-recipient cross-machine")
        trust_required = True
    if expected_recipient is not None and recipient != expected_recipient:
        errors.append(
            f"receiver expected recipient {expected_recipient}, artifact declares {recipient or 'none'}"
        )
    if receiver_context and (expected_recipient == "cross-machine" or data.get("schema") == 3):
        if data.get("schema") != 3:
            errors.append("receiver refuses legacy schema for cross-machine transfer")
        if not nonempty(trusted_head) or not SHA_RE.fullmatch(str(trusted_head)):
            errors.append("receiver must supply --trusted-head from a trusted channel")
            trust_required = True
        elif recorded.get("head") != trusted_head:
            errors.append("artifact HEAD does not match receiver-supplied trusted HEAD")
        if not nonempty(trusted_manifest_sha256) or not re.fullmatch(
            r"[0-9a-f]{64}", str(trusted_manifest_sha256)
        ):
            errors.append("receiver must supply --trusted-manifest-sha256 from a trusted channel")
            trust_required = True
        else:
            try:
                actual_digest = manifest_sha256(root)
            except ValueError as exc:
                errors.append(str(exc))
            else:
                if actual_digest != trusted_manifest_sha256:
                    errors.append("artifact does not match receiver-supplied trusted manifest digest")
        recorded_remote = recorded.get("remote") if isinstance(recorded.get("remote"), dict) else {}
        if not nonempty(trusted_repository_url) or sanitize_remote_url(str(trusted_repository_url)) != trusted_repository_url:
            errors.append("receiver must supply --trusted-repository-url from a trusted channel")
            trust_required = True
        elif recorded_remote.get("url") != trusted_repository_url:
            errors.append("artifact repository URL does not match receiver-supplied trusted URL")
        else:
            remote_error = receiver_repository_url_error(root, str(trusted_repository_url))
            if remote_error:
                errors.append(remote_error)
    if route.get("recipient") == "cross-machine":
        if current.get("dirty") is True:
            errors.append("current cross-machine worktree is dirty; create a fresh relay after committing")
    compared = ("head", "dirty", "diff_sha256") if data.get("schema") == 3 and recipient == "cross-machine" \
        else ("head", "branch", "dirty", "diff_sha256")
    drift_fields = [key for key in compared if recorded.get(key) != current.get(key)]
    if route.get("recipient") == "cross-machine" and drift_fields:
        errors.append(
            "cross-machine relay repository fingerprint is stale; create a fresh relay from the clean pushed tree"
        )
    age_days = None
    try:
        created = dt.datetime.fromisoformat(str(data.get("created_at", "")).replace("Z", "+00:00"))
        age_days = max(0, (dt.datetime.now(dt.timezone.utc) - created.astimezone(dt.timezone.utc)).days)
    except (ValueError, TypeError):
        pass
    state = data.get("state") if isinstance(data.get("state"), dict) else {}
    return {
        "valid": not errors,
        "errors": errors,
        "warnings": warnings,
        "age_days": age_days,
        "repository_drift": bool(drift_fields),
        "drift_fields": drift_fields,
        "recorded_repository": recorded,
        "current_repository": current,
        "next_step": state.get("next_step"),
        "trust_required": trust_required,
        "recipient": (
            data.get("route", {}).get("recipient")
            if isinstance(data.get("route"), dict)
            else "legacy / same-machine only"
        ),
    }


def manifest_sha256(root: Path) -> str:
    path = root / MANIFEST
    if path.is_symlink():
        raise ValueError(f"{MANIFEST} must not be a symlink")
    try:
        info = path.stat()
        if not stat.S_ISREG(info.st_mode):
            raise ValueError(f"{MANIFEST} must be a regular file")
        if info.st_size > MAX_MANIFEST_BYTES:
            raise ValueError(f"{MANIFEST} exceeds {MAX_MANIFEST_BYTES} bytes")
        payload = path.read_bytes()
    except FileNotFoundError as exc:
        raise ValueError(f"{MANIFEST} does not exist") from exc
    except OSError as exc:
        raise ValueError(f"cannot read {MANIFEST}: {exc}") from exc
    return hashlib.sha256(payload).hexdigest()


def parser() -> argparse.ArgumentParser:
    top = argparse.ArgumentParser(description=__doc__)
    sub = top.add_subparsers(dest="command", required=True)
    draft_command = sub.add_parser("draft")
    draft_command.add_argument("--root", default=".")
    draft_command.add_argument(
        "--recipient",
        default="same-machine",
        choices=("same-machine", "cross-machine"),
        help="where the receiver will consume this relay (default: same-machine for legacy callers)",
    )
    draft_command.add_argument("--base", help="task base revision; required for cross-machine")
    for name in ("render", "validate", "envelope", "inspect"):
        command = sub.add_parser(name)
        command.add_argument("--root", default=".")
        if name == "inspect":
            command.add_argument("--json", action="store_true")
            command.add_argument("--expected-recipient", choices=("same-machine", "cross-machine"))
            command.add_argument("--trusted-head")
            command.add_argument("--trusted-manifest-sha256")
            command.add_argument("--trusted-repository-url")
    consume = sub.add_parser("consume")
    consume.add_argument("--root", default=".")
    consume.add_argument("--verified", action="store_true")
    consume.add_argument("--expected-recipient", choices=("same-machine", "cross-machine"))
    consume.add_argument("--trusted-head")
    consume.add_argument("--trusted-manifest-sha256")
    consume.add_argument("--trusted-repository-url")
    return top


def main() -> int:
    args = parser().parse_args()
    root = Path(args.root).resolve()
    if args.command == "draft":
        try:
            data = draft(root, args.recipient, args.base)
        except ValueError as exc:
            print(f"relay: {exc}", file=sys.stderr)
            return 1
        print(json.dumps(data, ensure_ascii=False, indent=2))
        return 0
    try:
        data = load_manifest(root)
    except ValueError as exc:
        print(f"relay: {exc}", file=sys.stderr)
        return 1
    receiver_context = args.command in ("inspect", "consume")
    expected_recipient = getattr(args, "expected_recipient", None)
    trusted_head = getattr(args, "trusted_head", None)
    trusted_manifest_sha256 = getattr(args, "trusted_manifest_sha256", None)
    trusted_repository_url = getattr(args, "trusted_repository_url", None)
    result = inspect(
        root,
        data,
        check_human=receiver_context or args.command == "envelope",
        expected_recipient=expected_recipient,
        trusted_head=trusted_head,
        trusted_manifest_sha256=trusted_manifest_sha256,
        trusted_repository_url=trusted_repository_url,
        receiver_context=receiver_context,
    )
    if args.command == "validate":
        for message in result["errors"]:
            print(f"ERROR {message}", file=sys.stderr)
        for message in result["warnings"]:
            print(f"WARN  {message}", file=sys.stderr)
        if result["valid"]:
            print(f"VALID luciazero-relay schema={data.get('schema')}")
        return 0 if result["valid"] else 1
    if args.command == "render":
        if not result["valid"]:
            for message in result["errors"]:
                print(f"ERROR {message}", file=sys.stderr)
            return 1
        human = root / HUMAN
        if human.is_symlink():
            print(f"relay: {HUMAN} must not be a symlink", file=sys.stderr)
            return 1
        human.write_text(render_markdown(data), encoding="utf-8")
        for message in result["warnings"]:
            print(f"WARN  {message}", file=sys.stderr)
        print(f"WROTE {root / HUMAN}")
        return 0
    if args.command == "envelope":
        repository = data.get("repository") if isinstance(data.get("repository"), dict) else {}
        remote = repository.get("remote") if isinstance(repository.get("remote"), dict) else {}
        result["errors"].extend(envelope_remote_errors(root, data))
        result["valid"] = not result["errors"]
        if not result["valid"] or data.get("schema") != 3 or result["recipient"] != "cross-machine":
            for message in result["errors"]:
                print(f"ERROR {message}", file=sys.stderr)
            print("relay: trusted envelope requires a valid rendered cross-machine schema 3 relay", file=sys.stderr)
            return 1
        print(json.dumps({
            "repository_url": remote.get("url"),
            "remote_ref": remote.get("ref"),
            "trusted_head": repository.get("head"),
            "trusted_manifest_sha256": manifest_sha256(root),
        }, ensure_ascii=False, indent=2))
        return 0
    if args.command == "inspect":
        if args.json:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            print(f"Relay: {'valid' if result['valid'] else 'invalid'}, age={result['age_days']}d")
            print(f"Recipient: {result['recipient']}")
            print(f"Repository drift: {'yes' if result['repository_drift'] else 'no'}")
            if result["drift_fields"]:
                print("Changed fingerprint fields: " + ", ".join(result["drift_fields"]))
            print("Next: " + json.dumps(result["next_step"], ensure_ascii=False))
            for message in result["warnings"]:
                print(f"WARN  {message}")
            for message in result["errors"]:
                print(f"ERROR {message}")
        if result["valid"]:
            return 0
        return 2 if result["trust_required"] else 1
    if not result["valid"]:
        print("relay: refuse to consume an invalid relay", file=sys.stderr)
        return 2 if result["trust_required"] else 1
    if not args.verified:
        print("relay: refuse to consume without --verified after re-running evidence", file=sys.stderr)
        return 2
    for name in (RECEIPT, HUMAN, MANIFEST):
        path = root / name
        if path.exists() or path.is_symlink():
            path.unlink()
            print(f"CONSUMED {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
