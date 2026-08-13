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
import subprocess
import sys
from typing import Any, Optional


MANIFEST = "LUCIA_RELAY.json"
HUMAN = "LUCIA_RELAY.md"
SECRET_PATTERNS = (
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
)
POSIX_ABSOLUTE_PATH = re.compile(
    r"(?<![A-Za-z0-9+.\-:/~$%])/(?!/)[^\s\"'`<>]+"
)
WINDOWS_ABSOLUTE_PATH = re.compile(r"(?<![A-Za-z0-9])[A-Za-z]:[\\/][^\s\"'`<>]+")
UNC_PATH = re.compile(r"(?<!\\)\\\\[^\\\s\"'`<>]+\\[^\s\"'`<>]+")
HOME_PATH = re.compile(r"(?<![A-Za-z0-9])(?:~|\$HOME|%USERPROFILE%)[\\/][^\s\"'`<>]+")
FILE_URI_PATH = re.compile(r"\bfile:[^\s\"'`<>]+", re.IGNORECASE)


def git(root: Path, *args: str) -> tuple[int, str]:
    proc = subprocess.run(
        ["git", "-C", str(root), *args],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        errors="surrogateescape",
        check=False,
    )
    return proc.returncode, proc.stdout.rstrip("\n")


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
    head_rc, head = git(repo, "rev-parse", "HEAD")
    _, branch = git(repo, "branch", "--show-current")
    exclusions = ("--", ".", f":(exclude){MANIFEST}", f":(exclude){HUMAN}")
    if head_rc == 0:
        _, raw_modified = git(repo, "diff", "--name-only", "-z", "HEAD", *exclusions)
        _, diff = git(repo, "diff", "--binary", "HEAD", *exclusions)
    else:
        _, raw_staged = git(repo, "diff", "--cached", "--name-only", "-z", *exclusions)
        _, raw_unstaged = git(repo, "diff", "--name-only", "-z", *exclusions)
        raw_modified = raw_staged + raw_unstaged
        _, staged_diff = git(repo, "diff", "--cached", "--binary", "--root", *exclusions)
        _, unstaged_diff = git(repo, "diff", "--binary", *exclusions)
        diff = staged_diff + "\n" + unstaged_diff
    _, raw_untracked = git(repo, "ls-files", "--others", "--exclude-standard", "-z")
    modified = sorted(set(item for item in raw_modified.split("\0") if item))
    untracked = [
        item for item in raw_untracked.split("\0") if item and item not in (MANIFEST, HUMAN)
    ]
    digest = hashlib.sha256(diff.encode("utf-8", errors="surrogateescape"))
    for relative in sorted(untracked):
        digest.update(b"\0untracked\0" + relative.encode("utf-8", errors="surrogateescape") + b"\0")
        candidate = repo / relative
        try:
            if candidate.is_symlink():
                digest.update(b"symlink\0" + os.readlink(candidate).encode("utf-8", errors="surrogateescape"))
            elif candidate.is_file():
                with candidate.open("rb") as handle:
                    for chunk in iter(lambda: handle.read(1024 * 1024), b""):
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
        _, remote_refs = git(
            repo,
            "for-each-ref",
            "--contains=HEAD",
            "--format=%(refname)",
            "refs/remotes",
        )
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
    }


def draft(root: Path, recipient: str) -> dict[str, Any]:
    snap = repository_snapshot(root)
    files = snap.pop("files", {"modified": [], "untracked": []})
    return {
        "schema": 2,
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


def load_manifest(root: Path) -> dict[str, Any]:
    path = root / MANIFEST
    if path.is_symlink():
        raise ValueError(f"{MANIFEST} must not be a symlink")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ValueError(f"{MANIFEST} does not exist") from exc
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read {MANIFEST}: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{MANIFEST} must contain a JSON object")
    return value


def nonempty(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def string_values(value: Any):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for nested in value.values():
            yield from string_values(nested)
    elif isinstance(value, list):
        for nested in value:
            yield from string_values(nested)


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


def cross_machine_repository_errors(root: Path, data: dict[str, Any]) -> list[str]:
    route = data.get("route") if isinstance(data.get("route"), dict) else {}
    if route.get("recipient") != "cross-machine":
        return []
    repository = data.get("repository") if isinstance(data.get("repository"), dict) else {}
    head = repository.get("head")
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
        rc, _ = git(root, "cat-file", "-e", f"{head}:{path}")
        if rc != 0:
            errors.append(
                f"knowledge.read_first[{index}] path is not present in the pushed relay commit: {path}"
            )
            continue
        _, entry = git(root, "ls-tree", str(head), "--", path)
        if entry.startswith("120000 "):
            errors.append(
                f"knowledge.read_first[{index}] must not use a symlink for cross-machine delivery: {path}"
            )
    return errors


def validate(data: dict[str, Any]) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    schema = data.get("schema")
    if schema not in (1, 2):
        errors.append("schema must equal 1 or 2")
    if data.get("kind") != "luciazero-relay":
        errors.append("kind must equal luciazero-relay")
    recipient = None
    route = data.get("route")
    if schema == 2:
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
        if schema == 2 and not isinstance(inline, list):
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
        if schema == 2:
            known_remote_refs = repository.get("known_remote_refs")
            if not isinstance(known_remote_refs, list):
                errors.append("repository.known_remote_refs must be an array")
            elif not all(nonempty(ref) for ref in known_remote_refs):
                errors.append("repository.known_remote_refs entries must be non-empty strings")
    files = data.get("files")
    if not isinstance(files, dict):
        errors.append("files must be an object")
    else:
        for key in ("modified", "untracked"):
            if not isinstance(files.get(key), list):
                errors.append(f"files.{key} must be an array")

    serialized = json.dumps(data, ensure_ascii=False)
    if any(pattern.search(serialized) for pattern in SECRET_PATTERNS):
        errors.append("possible secret or private key detected; remove it before routing")
    local_paths = machine_paths(data)
    if recipient == "cross-machine":
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
            if not repository.get("known_remote_refs"):
                errors.append(
                    "cross-machine relay HEAD is not reachable from a locally known remote branch; push it before routing"
                )
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
    if data.get("schema") == 2:
        out.append(f"Recipient: {markdown_text(route.get('recipient', 'not recorded'))}")
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
    if data.get("schema") == 2:
        out.append(f"- Known remote refs: {code_inline(', '.join(str(ref) for ref in known_remote_refs) or 'none')}")
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
    if data.get("schema") == 2:
        out.extend(["", "## Inline knowledge", "", *inline_knowledge(knowledge.get("inline"))])
    out.extend(["", "## Hypotheses", "", *bullets(knowledge.get("hypotheses"))])
    out.extend(["", "## Landmines", "", *bullets(knowledge.get("landmines"))])
    out.extend(["", "## Files", "", "Modified:", "", *bullets(files.get("modified"))])
    out.extend(["", "Untracked:", "", *bullets(files.get("untracked")), ""])
    return "\n".join(out)


def inspect(root: Path, data: dict[str, Any], check_human: bool = False) -> dict[str, Any]:
    errors, warnings = validate(data)
    if check_human:
        human = root / HUMAN
        if human.is_symlink():
            errors.append(f"{HUMAN} must not be a symlink")
        elif not human.is_file():
            errors.append(f"{HUMAN} is missing; render it from the canonical manifest")
        else:
            try:
                actual = human.read_text(encoding="utf-8")
            except OSError as exc:
                errors.append(f"cannot read {HUMAN}: {exc}")
            else:
                if actual != render_markdown(data):
                    errors.append(f"{HUMAN} does not match {MANIFEST}; regenerate it before trusting or consuming the relay")
    current = repository_snapshot(root)
    errors.extend(cross_machine_repository_errors(root, data))
    recorded = data.get("repository") if isinstance(data.get("repository"), dict) else {}
    route = data.get("route") if isinstance(data.get("route"), dict) else {}
    if route.get("recipient") == "cross-machine":
        if current.get("dirty") is True:
            errors.append("current cross-machine worktree is dirty; create a fresh relay after committing")
        if not current.get("known_remote_refs"):
            errors.append("current cross-machine HEAD is not reachable from a locally known remote branch")
    compared = ("head", "branch", "dirty", "diff_sha256")
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
        "recipient": (
            data.get("route", {}).get("recipient")
            if isinstance(data.get("route"), dict)
            else "legacy / same-machine only"
        ),
    }


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
    for name in ("render", "validate", "inspect"):
        command = sub.add_parser(name)
        command.add_argument("--root", default=".")
        if name == "inspect":
            command.add_argument("--json", action="store_true")
    consume = sub.add_parser("consume")
    consume.add_argument("--root", default=".")
    consume.add_argument("--verified", action="store_true")
    return top


def main() -> int:
    args = parser().parse_args()
    root = Path(args.root).resolve()
    if args.command == "draft":
        print(json.dumps(draft(root, args.recipient), ensure_ascii=False, indent=2))
        return 0
    try:
        data = load_manifest(root)
    except ValueError as exc:
        print(f"relay: {exc}", file=sys.stderr)
        return 1
    result = inspect(root, data, check_human=args.command in ("inspect", "consume"))
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
        return 0 if result["valid"] else 1
    if not args.verified:
        print("relay: refuse to consume without --verified after re-running evidence", file=sys.stderr)
        return 2
    if not result["valid"]:
        print("relay: refuse to consume an invalid relay", file=sys.stderr)
        return 1
    for name in (HUMAN, MANIFEST):
        path = root / name
        if path.exists():
            path.unlink()
            print(f"CONSUMED {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
