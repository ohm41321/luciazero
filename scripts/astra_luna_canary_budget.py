#!/usr/bin/env python3
"""Reserve and enforce the Slice 3 provider-start budget.

The canary launcher is the only supported path for starting a provider in a
Slice 3 cell.  Root launches use the dedicated ``root`` subcommand, which
requires Codex native ``multi_agent`` and ``multi_agent_v2`` collaboration to
be disabled before calling ``Popen``.  Role launches use ``spawn --role`` with
an explicit ``--role-file``.  The wrapper fingerprints that file, passes a
nonce-bound binding to the provider, and requires a provider-side
acknowledgement before a successful exit can be counted as completed.  A
role-less ``spawn`` is rejected so it cannot bypass the root policy.  Each
launch reserves a unique cell/role slot under an inter-process lock before
calling ``Popen``.
The ledger records reservations separately from runtime start and exit
observations, so a failed launch still consumes its planned slot without being
retried.
"""

from __future__ import annotations

import argparse
import copy
import fcntl
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator, Sequence


SCHEMA_VERSION = 1
ROLE_NAMES = (
    "lucia-explorer",
    "lucia-researcher",
    "lucia-worker",
    "lucia-tester",
    "lucia-reviewer",
)
NATIVE_COLLABORATION_FEATURES = ("multi_agent", "multi_agent_v2")
DIRECT_PROVIDER_EXECUTABLES = {"claude", "claude.exe", "codex", "codex.exe"}

# This is deliberately immutable in the launcher.  A ledger stores its digest
# and the complete copy; loading a modified plan is refused before any spawn.
CANARY_PLAN = {
    "total_starts": 17,
    "cells": {
        "C1-root": {"root_limit": 1, "roles": []},
        "C1-adapter": {"root_limit": 1, "roles": []},
        "C2-root": {"root_limit": 1, "roles": []},
        "C2-adapter": {
            "root_limit": 1,
            "roles": ["lucia-explorer", "lucia-worker", "lucia-tester"],
        },
        "C3-root": {"root_limit": 1, "roles": []},
        "C3-adapter": {
            "root_limit": 1,
            "roles": [
                "lucia-explorer",
                "lucia-worker",
                "lucia-tester",
                "lucia-reviewer",
            ],
        },
        "C4-root": {"root_limit": 1, "roles": []},
        "C4-adapter": {
            "root_limit": 1,
            "roles": ["lucia-researcher", "lucia-reviewer"],
        },
    },
}

OBSERVED_KEYS = (
    "root_started",
    "role_started",
    "failed_start",
    "failed_exit",
    "failed_binding",
    "completed",
    "refused_quota",
    "refused_invalid",
)

ROLE_ACK_METHOD = "luciazero-role-ack-v1"
ROLE_ACK_RETURN_CODE = 125
ROLE_FIELD_RE = re.compile(
    r'^\s*(name|description|sandbox_mode|developer_instructions)'
    r'\s*=\s*"((?:\\.|[^"\\])*)"\s*$'
)
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
ROLE_REQUIRED_FIELDS = ("name", "description", "sandbox_mode", "developer_instructions")


class BudgetError(Exception):
    """A reservation or ledger operation was refused."""

    category = "refused_invalid"


class DuplicateReservation(BudgetError):
    category = "refused_invalid"


class OutsideMatrix(BudgetError):
    category = "refused_invalid"


class QuotaExceeded(BudgetError):
    category = "refused_quota"


class LedgerError(BudgetError):
    category = "refused_invalid"


class NativeSpawnPolicyError(BudgetError):
    """A Codex command did not disable native subagent spawning."""

    category = "refused_invalid"


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def plan_digest(plan: dict[str, Any]) -> str:
    return hashlib.sha256(canonical_json(plan).encode("utf-8")).hexdigest()


def role_instruction_binding(role: str, role_file: Path | None) -> dict[str, str]:
    """Validate and fingerprint the exact role instructions used by a start."""

    if role_file is None:
        raise LedgerError(
            f"role {role} requires --role-file with its lucia role instructions"
        )
    if "\n" in str(role_file) or "\r" in str(role_file):
        raise LedgerError("role instruction path contains a newline")
    if role_file.name != f"{role}.toml":
        raise LedgerError(
            f"role instruction file must be named {role}.toml"
        )
    if role_file.is_symlink() or not role_file.is_file():
        raise LedgerError("role instruction file must be a regular file")
    try:
        content = role_file.read_bytes()
    except OSError as exc:
        raise LedgerError(f"cannot read role instruction file: {exc}") from exc
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise LedgerError("role instruction file is not UTF-8") from exc
    fields: dict[str, str] = {}
    for line in text.splitlines():
        match = ROLE_FIELD_RE.match(line)
        if match is None:
            continue
        field, value = match.groups()
        if field in fields:
            raise LedgerError(f"role instruction file repeats {field}")
        fields[field] = value
    missing = [field for field in ROLE_REQUIRED_FIELDS if field not in fields]
    if missing:
        raise LedgerError(
            "role instruction file is missing " + ", ".join(missing)
        )
    if fields["name"] != role:
        raise LedgerError(
            f"role instruction file must declare name = {role!r}"
        )
    if not fields["description"].strip():
        raise LedgerError("role instruction file has an empty description")
    if fields["sandbox_mode"] not in {"read-only", "workspace-write"}:
        raise LedgerError("role instruction file has an invalid sandbox_mode")
    if not fields["developer_instructions"].strip():
        raise LedgerError("role instruction file has empty developer_instructions")
    return {
        "role": role,
        "sha256": hashlib.sha256(content).hexdigest(),
        "ack": "pending",
    }


def _validate_instruction_binding(binding: Any, role: str) -> None:
    if not isinstance(binding, dict):
        raise LedgerError(f"role {role} has no instruction binding")
    if binding.get("role") != role or not isinstance(binding.get("sha256"), str):
        raise LedgerError(f"role {role} has an invalid instruction binding")
    if not SHA256_RE.fullmatch(binding["sha256"]):
        raise LedgerError(f"role {role} has an invalid instruction hash")
    if binding.get("ack") not in {"pending", "verified", "failed"}:
        raise LedgerError(f"role {role} has an invalid instruction acknowledgement")


def _validate_plan(plan: dict[str, Any]) -> None:
    if not isinstance(plan, dict) or type(plan.get("total_starts")) is not int:
        raise LedgerError("plan total_starts is not an integer")
    if plan["total_starts"] <= 0 or not isinstance(plan.get("cells"), dict):
        raise LedgerError("plan shape is invalid")
    for cell, spec in plan["cells"].items():
        if not isinstance(cell, str) or not isinstance(spec, dict):
            raise LedgerError("plan cell shape is invalid")
        if type(spec.get("root_limit")) is not int or spec["root_limit"] < 0:
            raise LedgerError(f"plan root limit is invalid for {cell}")
        roles = spec.get("roles")
        if not isinstance(roles, list) or any(not isinstance(role, str) for role in roles):
            raise LedgerError(f"plan roles are invalid for {cell}")
        if len(set(roles)) != len(roles):
            raise LedgerError(f"plan roles are duplicated for {cell}")
        if any(role not in ROLE_NAMES for role in roles):
            raise LedgerError(f"plan role is outside the lucia namespace for {cell}")


def new_ledger(plan: dict[str, Any] | None = None) -> dict[str, Any]:
    selected = copy.deepcopy(CANARY_PLAN if plan is None else plan)
    _validate_plan(selected)
    return {
        "schema_version": SCHEMA_VERSION,
        "plan_digest": plan_digest(selected),
        "planned_budget": selected,
        "reservations": [],
        "observed_usage": {key: 0 for key in OBSERVED_KEYS},
    }


def _reservation_key(cell: str, role: str | None) -> tuple[str, str]:
    return cell, role if role is not None else "__root__"


def _find_reservation(state: dict[str, Any], reservation_id: str) -> dict[str, Any]:
    for item in state["reservations"]:
        if item["reservation_id"] == reservation_id:
            return item
    raise LedgerError(f"unknown reservation {reservation_id}")


def reserve_slot(
    state: dict[str, Any],
    cell: str,
    role: str | None,
    *,
    plan: dict[str, Any] | None = None,
    instruction_binding: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Reserve one unique root/role slot in an in-memory ledger state."""

    selected = state.get("planned_budget") if plan is None else plan
    if selected is None:
        selected = CANARY_PLAN
    _validate_plan(selected)
    if cell not in selected["cells"]:
        raise OutsideMatrix(f"cell {cell!r} is not in the canary matrix")
    if role is not None and role not in selected["cells"][cell]["roles"]:
        raise OutsideMatrix(f"role {role!r} is not allowed in {cell}")
    if role is not None:
        _validate_instruction_binding(instruction_binding, role)
    elif instruction_binding is not None:
        raise LedgerError("root reservations cannot carry role instructions")
    key = _reservation_key(cell, role)
    if any(_reservation_key(item["cell"], item.get("role")) == key for item in state["reservations"]):
        raise DuplicateReservation(f"duplicate reservation for {cell}/{role or 'root'}")
    if len(state["reservations"]) >= selected["total_starts"]:
        raise QuotaExceeded(f"quota exhausted: {selected['total_starts']} starts reserved")

    spec = selected["cells"][cell]
    same_cell = [item for item in state["reservations"] if item["cell"] == cell]
    if role is None:
        if sum(item.get("role") is None for item in same_cell) >= spec["root_limit"]:
            raise QuotaExceeded(f"root quota exhausted for {cell}")
        kind = "root"
    else:
        role_count = sum(item.get("role") is not None for item in same_cell)
        if role_count >= len(spec["roles"]):
            raise QuotaExceeded(f"role quota exhausted for {cell}")
        kind = "role"

    item = {
        "reservation_id": f"reservation-{uuid.uuid4().hex}",
        "cell": cell,
        "kind": kind,
        "role": role,
        "state": "reserved",
    }
    if instruction_binding is not None:
        item["instruction_binding"] = copy.deepcopy(instruction_binding)
    state["reservations"].append(item)
    return item


def mark_started(state: dict[str, Any], reservation_id: str) -> None:
    item = _find_reservation(state, reservation_id)
    if item["state"] != "reserved":
        raise LedgerError(f"reservation {reservation_id} is not pending start")
    item["state"] = "started"
    key = "root_started" if item["kind"] == "root" else "role_started"
    state["observed_usage"][key] += 1


def mark_failed_start(state: dict[str, Any], reservation_id: str, error: str) -> None:
    item = _find_reservation(state, reservation_id)
    if item["state"] != "reserved":
        raise LedgerError(f"reservation {reservation_id} is not pending start")
    item["state"] = "failed_start"
    item["error"] = error[:240]
    if item.get("role") is not None:
        item["instruction_binding"]["ack"] = "failed"
    state["observed_usage"]["failed_start"] += 1


def mark_binding_verified(state: dict[str, Any], reservation_id: str) -> None:
    item = _find_reservation(state, reservation_id)
    if item["state"] != "started" or item.get("role") is None:
        raise LedgerError(f"reservation {reservation_id} has no pending role binding")
    item["instruction_binding"]["ack"] = "verified"


def mark_binding_failed(state: dict[str, Any], reservation_id: str, error: str) -> None:
    item = _find_reservation(state, reservation_id)
    if item["state"] != "started" or item.get("role") is None:
        raise LedgerError(f"reservation {reservation_id} has no pending role binding")
    item["instruction_binding"]["ack"] = "failed"
    item["binding_error"] = error[:240]
    state["observed_usage"]["failed_binding"] += 1


def mark_exit(state: dict[str, Any], reservation_id: str, returncode: int) -> None:
    item = _find_reservation(state, reservation_id)
    if item["state"] != "started":
        raise LedgerError(f"reservation {reservation_id} was not started")
    item["exit_code"] = returncode
    if returncode == 0 and item.get("binding_error"):
        item["state"] = "failed_binding"
    elif returncode == 0:
        item["state"] = "completed"
        state["observed_usage"]["completed"] += 1
    else:
        item["state"] = "failed_exit"
        state["observed_usage"]["failed_exit"] += 1


def _validate_state(state: dict[str, Any], plan: dict[str, Any] = CANARY_PLAN) -> None:
    _validate_plan(plan)
    if state.get("schema_version") != SCHEMA_VERSION:
        raise LedgerError("ledger schema version is unsupported")
    if state.get("plan_digest") != plan_digest(plan) or state.get("planned_budget") != plan:
        raise LedgerError("ledger plan does not match the approved canary plan")
    if not isinstance(state.get("reservations"), list):
        raise LedgerError("ledger reservations are not a list")
    if len(state["reservations"]) > plan["total_starts"]:
        raise QuotaExceeded(f"ledger already exceeds {plan['total_starts']} starts")
    observed = state.get("observed_usage")
    if not isinstance(observed, dict) or any(type(observed.get(key)) is not int or observed[key] < 0 for key in OBSERVED_KEYS):
        raise LedgerError("ledger observed usage is invalid")
    seen: set[tuple[str, str]] = set()
    for item in state["reservations"]:
        if not isinstance(item, dict) or not isinstance(item.get("reservation_id"), str):
            raise LedgerError("ledger reservation shape is invalid")
        cell = item.get("cell")
        role = item.get("role")
        if cell not in plan["cells"]:
            raise LedgerError("ledger contains a cell outside the canary matrix")
        if role is not None and role not in plan["cells"][cell]["roles"]:
            raise LedgerError("ledger contains a role outside its cell matrix")
        if role is not None:
            _validate_instruction_binding(item.get("instruction_binding"), role)
        key = _reservation_key(cell, role)
        if key in seen:
            raise LedgerError("ledger contains duplicate reservation keys")
        seen.add(key)


def _lexists(path: Path) -> bool:
    return os.path.lexists(path)


def _reject_symlink(path: Path, label: str) -> None:
    if _lexists(path) and path.is_symlink():
        raise LedgerError(f"{label} is a symlink; refusing to follow it")


@contextmanager
def _ledger_lock(path: Path) -> Iterator[None]:
    parent = path.parent
    if not parent.is_dir():
        raise LedgerError(f"ledger parent does not exist: {parent}")
    lock_path = Path(f"{path}.lock")
    _reject_symlink(lock_path, "ledger lock")
    try:
        fd = os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o600)
    except OSError as exc:
        raise LedgerError(f"cannot open ledger lock: {exc}") from exc
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


def _read_state(path: Path) -> dict[str, Any]:
    _reject_symlink(path, "ledger")
    if not path.is_file():
        raise LedgerError(f"ledger does not exist: {path}")
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise LedgerError(f"ledger is unreadable: {exc}") from exc
    _validate_state(state)
    return state


def _write_state(path: Path, state: dict[str, Any]) -> None:
    _reject_symlink(path, "ledger")
    _validate_state(state)
    parent = path.parent
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=parent)
    temp_path = Path(temp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(state, stream, indent=2, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp_path, path)
    finally:
        if temp_path.exists() or temp_path.is_symlink():
            try:
                temp_path.unlink()
            except OSError:
                pass


@contextmanager
def _locked_state(path: Path) -> Iterator[dict[str, Any]]:
    with _ledger_lock(path):
        state = _read_state(path)
        yield state


def init_ledger(path: Path) -> None:
    with _ledger_lock(path):
        _reject_symlink(path, "ledger")
        if _lexists(path):
            raise LedgerError(f"ledger already exists: {path}")
        _write_state(path, new_ledger())


def _record_refusal(path: Path, error: BudgetError) -> None:
    with _ledger_lock(path):
        state = _read_state(path)
        state["observed_usage"][error.category] += 1
        _write_state(path, state)


def _refuse(path: Path, error: BudgetError) -> int:
    """Record a preflight refusal without starting or reserving a process."""

    try:
        _record_refusal(path, error)
    except BudgetError:
        # The original error is the useful contract failure.  A missing or
        # malformed ledger is reported by the command that attempted it.
        pass
    print(f"REFUSED {error}", file=sys.stderr)
    return 2


def _new_role_ack(path: Path) -> tuple[Path, str]:
    """Create a private, unused acknowledgement pathname and nonce."""

    fd, name = tempfile.mkstemp(prefix=".role-ack.", dir=path.parent)
    os.close(fd)
    ack_path = Path(name)
    try:
        ack_path.unlink()
    except OSError as exc:
        raise LedgerError(f"cannot prepare role acknowledgement path: {exc}") from exc
    return ack_path, uuid.uuid4().hex


def _new_role_marker(path: Path) -> Path:
    """Create a private, unused provider-identity pathname."""

    fd, name = tempfile.mkstemp(prefix=".role-provider.", dir=path.parent)
    os.close(fd)
    marker_path = Path(name)
    try:
        marker_path.unlink()
    except OSError as exc:
        raise LedgerError(f"cannot prepare role provider marker: {exc}") from exc
    return marker_path


def _write_role_marker(marker_path: Path, nonce: str, provider_pid: int) -> None:
    payload = {"nonce": nonce, "provider_pid": provider_pid}
    try:
        temp_fd, temp_name = tempfile.mkstemp(
            prefix=f".{marker_path.name}.", dir=marker_path.parent
        )
    except OSError as exc:
        # Marker publication happens after Popen.  Convert allocation errors
        # into the same guarded path as write/link failures so the already
        # started provider is still waited for and recorded as a failed
        # binding/exit rather than being misclassified as failed_start.
        raise LedgerError(f"cannot prepare role provider marker: {exc}") from exc
    temp_path = Path(temp_name)
    try:
        with os.fdopen(temp_fd, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        # The marker pathname was prepared as absent.  A hard link publishes
        # the complete file without replacing a planted file or symlink.
        os.link(temp_path, marker_path)
    except OSError as exc:
        try:
            temp_path.unlink()
        except OSError:
            pass
        raise LedgerError(f"cannot write role provider marker: {exc}") from exc
    finally:
        if _lexists(temp_path):
            try:
                temp_path.unlink()
            except OSError:
                pass


def _read_role_ack(
    ack_path: Path,
    *,
    role: str,
    expected_hash: str,
    nonce: str,
    provider_pid: int,
) -> tuple[bool, str]:
    if not _lexists(ack_path):
        return False, "provider did not acknowledge role instructions"
    if ack_path.is_symlink() or not ack_path.is_file():
        return False, "role acknowledgement is not a regular file"
    try:
        payload = json.loads(ack_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        return False, f"role acknowledgement is unreadable: {exc}"
    if not isinstance(payload, dict):
        return False, "role acknowledgement is not an object"
    if payload.get("method") != ROLE_ACK_METHOD:
        return False, "role acknowledgement method is invalid"
    if payload.get("role") != role:
        return False, "role acknowledgement names the wrong role"
    if payload.get("sha256") != expected_hash:
        return False, "role acknowledgement hash does not match the bound file"
    if payload.get("content_sha256") != expected_hash:
        return False, "provider did not attest the bound instruction bytes"
    if payload.get("nonce") != nonce:
        return False, "role acknowledgement nonce is invalid"
    if payload.get("provider_pid") != provider_pid:
        return False, "role acknowledgement is not bound to this provider process"
    return True, "verified"


def _has_option(command: Sequence[str], option: str, value: str) -> bool:
    return any(
        command[index] == option
        and index + 1 < len(command)
        and command[index + 1] == value
        for index in range(len(command))
    )


def _is_codex_executable(token: str) -> bool:
    return Path(token).name in {"codex", "codex.exe"}


def _is_direct_provider_executable(token: str) -> bool:
    return Path(token).name in DIRECT_PROVIDER_EXECUTABLES


def _reject_native_config_overrides(command: Sequence[str]) -> None:
    """Reject feature config forms whose effective precedence is unverified."""

    for index, part in enumerate(command):
        if part in {"--config", "--config-file"} or part.startswith(
            ("--config=", "--config-file=")
        ):
            raise NativeSpawnPolicyError(
                "Codex launch must not use an uninspected native feature config override"
            )
        if part == "-c" and index + 1 < len(command):
            setting = command[index + 1].replace(" ", "").strip("'\"")
            if setting.startswith(("features.multi_agent=", "features.multi_agent_v2=")):
                raise NativeSpawnPolicyError(
                    "Codex launch must not use a native multi-agent config override"
                )
        compact = part[2:] if part.startswith("-c") else ""
        if compact.startswith(("features.multi_agent=", "features.multi_agent_v2=")):
            raise NativeSpawnPolicyError(
                "Codex launch must not use a native multi-agent enable/config override"
            )


def validate_root_command(command: Sequence[str]) -> None:
    """Require the canary root to make native Codex collaboration impossible.

    Native Codex collaboration is intentionally disabled for this harness.
    The explicit flag must be adjacent to the executable so a prompt or an
    argument passed after it cannot masquerade as a feature setting.  A
    conflicting enable, including the ``-c`` form, is always rejected.
    """

    parts = list(command)
    if len(parts) < 2:
        raise NativeSpawnPolicyError(
            "root launch requires a Codex command beginning with "
            "--disable multi_agent --disable multi_agent_v2"
        )
    if not _is_codex_executable(parts[0]):
        raise NativeSpawnPolicyError("root launch must execute the Codex provider")
    disabled: set[str] = set()
    index = 1
    while index < len(parts):
        option = parts[index]
        if option.startswith("--disable="):
            disabled.add(option.split("=", 1)[1])
            index += 1
            continue
        if option == "--disable" and index + 1 < len(parts):
            disabled.add(parts[index + 1])
            index += 2
            continue
        break
    missing = set(NATIVE_COLLABORATION_FEATURES) - disabled
    if missing:
        raise NativeSpawnPolicyError(
            "root launch must disable native collaboration features: "
            + ", ".join(sorted(missing))
        )
    if _has_option(parts, "--enable", "multi_agent") or _has_option(
        parts, "--enable", "multi_agent_v2"
    ) or any(
        part in {"--enable=multi_agent", "--enable=multi_agent_v2"}
        for part in parts
    ):
        raise NativeSpawnPolicyError(
            "Codex launch must not enable native multi-agent spawning"
        )
    _reject_native_config_overrides(parts)


def root_cli(path: Path, cell: str, command: list[str]) -> int:
    """Launch a root process only after enforcing the native-spawn barrier."""

    if not command:
        return _refuse(
            path,
            NativeSpawnPolicyError(
                "root requires a Codex command after --"
            ),
        )
    try:
        validate_root_command(command)
    except NativeSpawnPolicyError as exc:
        return _refuse(path, exc)
    print("ROOT_NATIVE_MULTI_AGENT=disabled")
    print("ROOT_NATIVE_MULTI_AGENT_V2=disabled")
    return spawn_cli(path, cell, None, command, root=True)


def reserve_cli(
    path: Path,
    cell: str,
    role: str | None,
    role_file: Path | None = None,
) -> int:
    try:
        if role is None and role_file is not None:
            raise LedgerError("root reservations cannot carry role instructions")
        binding = role_instruction_binding(role, role_file) if role is not None else None
        with _locked_state(path) as state:
            item = reserve_slot(state, cell, role, instruction_binding=binding)
            _write_state(path, state)
    except BudgetError as exc:
        try:
            _record_refusal(path, exc)
        except BudgetError:
            pass
        print(f"REFUSED {exc}", file=sys.stderr)
        return 2
    print(f"RESERVED {item['reservation_id']} {item['kind']} {cell} {role or 'root'}")
    return 0


def spawn_cli(
    path: Path,
    cell: str,
    role: str | None,
    command: list[str],
    *,
    root: bool = False,
    role_file: Path | None = None,
) -> int:
    if not command:
        print("spawn requires a command after --", file=sys.stderr)
        return 2
    if role is None and not root:
        return _refuse(
            path,
            NativeSpawnPolicyError(
                "root starts must use the root command so native multi_agent is disabled"
            ),
        )
    if root and role is not None:
        return _refuse(path, NativeSpawnPolicyError("root cannot carry a role"))
    if root and role_file is not None:
        return _refuse(path, NativeSpawnPolicyError("root cannot carry role instructions"))
    if root:
        try:
            validate_root_command(command)
        except NativeSpawnPolicyError as exc:
            return _refuse(path, exc)
    if role is not None and not _is_direct_provider_executable(command[0]):
        return _refuse(
            path,
            NativeSpawnPolicyError(
                "role must execute claude or codex as the direct provider executable"
            ),
        )
    binding = None
    absolute_role_file: Path | None = None
    if role is not None:
        try:
            binding = role_instruction_binding(role, role_file)
            absolute_role_file = Path(os.path.abspath(role_file)) if role_file is not None else None
        except LedgerError as exc:
            return _refuse(path, exc)
    if role is not None and _is_codex_executable(command[0]):
        try:
            validate_root_command(command)
        except NativeSpawnPolicyError as exc:
            return _refuse(path, exc)
    try:
        with _locked_state(path) as state:
            item = reserve_slot(state, cell, role, instruction_binding=binding)
            _write_state(path, state)
    except BudgetError as exc:
        return _refuse(path, exc)

    reservation_id = item["reservation_id"]
    ack_path: Path | None = None
    marker_path: Path | None = None
    ack_nonce: str | None = None
    marker_error: str | None = None
    child_env = None
    if role is not None and binding is not None and absolute_role_file is not None:
        try:
            ack_path, ack_nonce = _new_role_ack(path)
            marker_path = _new_role_marker(path)
        except LedgerError as exc:
            for leftover in (ack_path, marker_path):
                if leftover is not None and _lexists(leftover):
                    try:
                        leftover.unlink()
                    except OSError:
                        pass
            with _locked_state(path) as state:
                mark_failed_start(state, reservation_id, str(exc))
                _write_state(path, state)
            print(f"FAILED_START {reservation_id}: {exc}", file=sys.stderr)
            return 127
        child_env = os.environ.copy()
        child_env.update(
            {
                "LUCIAZERO_ROLE_NAME": role,
                "LUCIAZERO_ROLE_FILE": str(absolute_role_file),
                "LUCIAZERO_ROLE_SHA256": binding["sha256"],
                "LUCIAZERO_ROLE_ACK_FILE": str(ack_path),
                "LUCIAZERO_ROLE_ACK_NONCE": ack_nonce,
                "LUCIAZERO_ROLE_PROVIDER_MARKER": str(marker_path),
                "LUCIAZERO_ROLE_ACK_TOOL": str(
                    Path(__file__).with_name("astra_luna_role_ack.py").absolute()
                ),
            }
        )
    try:
        if child_env is not None:
            # Publish the Popen identity after the child exists.  Descendant
            # helpers (including a shell tool) read this marker, so the ack
            # remains bound to this provider rather than its immediate shell.
            process = subprocess.Popen(command, shell=False, env=child_env)
            try:
                _write_role_marker(marker_path, ack_nonce, process.pid)
            except LedgerError as exc:
                marker_error = str(exc)
        else:
            process = subprocess.Popen(command, shell=False)
    except OSError as exc:
        for leftover in (ack_path, marker_path):
            if leftover is not None and _lexists(leftover):
                try:
                    leftover.unlink()
                except OSError:
                    pass
        with _locked_state(path) as state:
            mark_failed_start(state, reservation_id, str(exc))
            _write_state(path, state)
        print(f"FAILED_START {reservation_id}: {exc}", file=sys.stderr)
        return 127

    try:
        with _locked_state(path) as state:
            mark_started(state, reservation_id)
            _write_state(path, state)
    except Exception as exc:
        # Popen has already handed ownership of a live child to this wrapper.
        # If the started-state record cannot be persisted, do not let that
        # ledger error abandon the child or its private binding files.  The
        # reservation remains consumed on disk; report the accounting failure
        # and make a clean child exit non-zero rather than claiming success.
        accounting_error = f"cannot record provider start: {exc}"
        try:
            returncode = process.wait()
        except Exception as wait_exc:
            accounting_error += f"; provider wait failed: {wait_exc}"
            returncode = ROLE_ACK_RETURN_CODE
        for leftover in (ack_path, marker_path):
            if leftover is not None and _lexists(leftover):
                try:
                    leftover.unlink()
                except OSError:
                    pass
        print(
            f"ACCOUNTING_FAILED {reservation_id}: {accounting_error}; "
            f"provider_exit={returncode}",
            file=sys.stderr,
        )
        return returncode if returncode != 0 else ROLE_ACK_RETURN_CODE
    returncode = process.wait()
    binding_error: str | None = None
    if role is not None and binding is not None and ack_path is not None and ack_nonce is not None:
        # The provider inherits the nonce and exact path/hash.  Its ack helper
        # reads the wrapper-published Popen identity, so a generic process
        # with only a role label cannot be counted as a role start.
        ok, message = _read_role_ack(
            ack_path,
            role=role,
            expected_hash=binding["sha256"],
            nonce=ack_nonce,
            provider_pid=process.pid,
        )
        if not ok:
            binding_error = message
    if marker_error is not None:
        binding_error = marker_error
    for leftover in (ack_path, marker_path):
        if leftover is not None and _lexists(leftover):
            try:
                leftover.unlink()
            except OSError:
                pass
    with _locked_state(path) as state:
        if binding_error is None and role is not None:
            mark_binding_verified(state, reservation_id)
        elif role is not None:
            mark_binding_failed(state, reservation_id, binding_error)
        mark_exit(state, reservation_id, returncode)
        _write_state(path, state)
    if binding_error is not None:
        print(f"ROLE_BINDING_FAILED {reservation_id}: {binding_error}", file=sys.stderr)
        return ROLE_ACK_RETURN_CODE if returncode == 0 else returncode
    if role is not None and binding is not None:
        print(
            f"ROLE_BINDING_VERIFIED role={role} sha256={binding['sha256']}"
        )
    return returncode


def status_cli(path: Path) -> int:
    try:
        with _ledger_lock(path):
            state = _read_state(path)
    except BudgetError as exc:
        print(f"ERROR {exc}", file=sys.stderr)
        return 2
    print(json.dumps(state, indent=2, sort_keys=True))
    return 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="subcommand", required=True)
    init = subparsers.add_parser("init")
    init.add_argument("--ledger", type=Path, required=True)
    reserve = subparsers.add_parser("reserve")
    reserve.add_argument("--ledger", type=Path, required=True)
    reserve.add_argument("--cell", required=True)
    reserve.add_argument("--role")
    reserve.add_argument("--role-file", type=Path)
    spawn = subparsers.add_parser("spawn")
    spawn.add_argument("--ledger", type=Path, required=True)
    spawn.add_argument("--cell", required=True)
    spawn.add_argument("--role")
    spawn.add_argument("--role-file", type=Path)
    spawn.add_argument("argv", nargs=argparse.REMAINDER)
    root = subparsers.add_parser(
        "root", help="start a root Codex process with native multi-agent disabled"
    )
    root.add_argument("--ledger", type=Path, required=True)
    root.add_argument("--cell", required=True)
    root.add_argument("argv", nargs=argparse.REMAINDER)
    status = subparsers.add_parser("status")
    status.add_argument("--ledger", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.subcommand == "init":
        try:
            init_ledger(args.ledger)
        except BudgetError as exc:
            print(f"ERROR {exc}", file=sys.stderr)
            return 2
        print(f"LEDGER_INITIALIZED {args.ledger} plan={plan_digest(CANARY_PLAN)}")
        return 0
    if args.subcommand == "reserve":
        return reserve_cli(args.ledger, args.cell, args.role, args.role_file)
    if args.subcommand == "spawn":
        command = list(args.argv)
        if command and command[0] == "--":
            command = command[1:]
        return spawn_cli(
            args.ledger, args.cell, args.role, command, role_file=args.role_file
        )
    if args.subcommand == "root":
        command = list(args.argv)
        if command and command[0] == "--":
            command = command[1:]
        return root_cli(args.ledger, args.cell, command)
    if args.subcommand == "status":
        return status_cli(args.ledger)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
