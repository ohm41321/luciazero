#!/usr/bin/env python3
"""Trace evidence of skill invocation in one eval invocation's provider log.

Usage: skill_use.py --provider claude|codex --catalog a,b,c [--skills-dir DIR] LOG

Prints one JSON object:

  status    observed      — the log names a catalog skill through a channel
                            the trace shows: a Skill tool call, the skill body
                            the harness injects after one, a Read of a
                            SKILL.md, a shell command running a skill script
            not observed  — the log carries assistant messages (Claude) or
                            completed turns (Codex) and none of them show one
            unknown       — the log carries neither: a result-only log, plain
                            text, an empty file, so the trace cannot say
  names     the catalog skills observed, sorted
  evidence  one object per distinct observation: channel (Skill, Read, Bash,
            command), name, path (the skill's path fragment, `skills/<name>/…`)
            and source — `sandbox` when the path resolved into the sandbox
            install, `other` when it resolved elsewhere (a built-in skill of
            the same name), `unresolved` when a Skill call was never followed
            by a body naming its directory
  visible   the catalog skills the harness listed in its init event, or
            null when the log has no such list
  reason    for unknown, why

Installed is not used, and not observed is not unread: a harness can put a
skill's description in front of the model without any tool call showing in
the trace. Evidence carries skill names and path fragments only — never
prompt text, file content or command output.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from agent_log import load_claude_log, read_events  # noqa: E402

SKILL_PATH = re.compile(r"skills/([^/\s'\"]+)/([^\s'\"]*)")
SKILL_BODY = re.compile(r"^Base directory for this skill: (\S+)")
# what ends a path inside a shell command or a quoted argument
PATH_BREAK = set(" \t\r\n'\"=;|&()<>`$")
TRAILING_PUNCT = ";|&)>"


def skill_name(raw: str) -> str:
    """`/luciazero:debug extra words` -> `debug`."""
    return raw.strip().lstrip("/").split()[0].split(":")[-1] if raw.strip() else ""


class Reader:
    def __init__(self, catalog: set[str], skills_dir: str | None) -> None:
        self.catalog = catalog
        self.skills_dir = (os.path.realpath(skills_dir) + os.sep) if skills_dir else None
        self.evidence: list[dict] = []
        self.visible: list[str] | None = None
        self.turns = 0  # assistant messages (claude) or completed turns (codex)

    @property
    def names(self) -> list[str]:
        return sorted({item["name"] for item in self.evidence})

    def source_of(self, path: str) -> str:
        # realpath on both sides: a sandbox under macOS's /var/folders is
        # reported as /private/var/folders by anything that canonicalises
        if self.skills_dir and (os.path.realpath(path) + os.sep).startswith(self.skills_dir):
            return "sandbox"
        return "other"

    def note(self, channel: str, name: str, path: str, source: str) -> None:
        """Record one observation; a repeat of the same one adds nothing."""
        item = {"channel": channel, "name": name, "path": path, "source": source}
        if item not in self.evidence:
            self.evidence.append(item)

    def path_evidence(self, channel: str, text: str) -> None:
        for match in SKILL_PATH.finditer(text):
            name, rest = match.group(1), match.group(2).rstrip(TRAILING_PUNCT)
            if name not in self.catalog:
                continue
            start = match.start()
            # `skills/` must begin the path or follow a directory separator:
            # `myskills/x` is not a skill directory
            if start > 0 and text[start - 1] != "/" and text[start - 1] not in PATH_BREAK:
                continue
            # the path runs back to the previous break, whatever came before
            # it — a space, a quote, `VAR=`, a newline
            while start > 0 and text[start - 1] not in PATH_BREAK:
                start -= 1
            path = text[start:match.end()].rstrip(TRAILING_PUNCT)
            fragment = f"skills/{name}/{rest}"
            self.note(channel, name, fragment, self.source_of(path))

    def tool_use(self, block: dict) -> None:
        name = block.get("name")
        args = block.get("input") if isinstance(block.get("input"), dict) else {}
        if name in ("Skill", "SlashCommand"):
            raw = args.get("skill") or args.get("command") or ""
            skill = skill_name(str(raw))
            if skill in self.catalog:
                self.note("Skill", skill, f"skills/{skill}/", "unresolved")
        elif name == "Read":
            self.path_evidence("Read", str(args.get("file_path") or ""))
        elif name == "Bash":
            self.path_evidence("Bash", str(args.get("command") or ""))

    def skill_body(self, text: str) -> None:
        match = SKILL_BODY.match(text)
        if not match:
            return
        path = match.group(1).rstrip("/")
        name = os.path.basename(path)
        if name not in self.catalog:
            return
        source = self.source_of(path)
        # the body follows the Skill call it belongs to: resolve that call's
        # source rather than adding a second observation for one event
        for item in self.evidence:
            if item["channel"] == "Skill" and item["name"] == name \
                    and item["source"] == "unresolved":
                item["source"] = source
                self.dedupe()
                return
        self.note("Skill", name, f"skills/{name}/", source)

    def dedupe(self) -> None:
        seen: list[dict] = []
        for item in self.evidence:
            if item not in seen:
                seen.append(item)
        self.evidence = seen

    def claude(self, events: list) -> None:
        for event in events:
            if not isinstance(event, dict):
                continue
            kind = event.get("type")
            if kind == "system" and event.get("subtype") == "init":
                listed = event.get("skills")
                if listed is None:
                    listed = event.get("slash_commands")
                if isinstance(listed, list):
                    self.visible = sorted(
                        {skill_name(str(item)) for item in listed if isinstance(item, str)}
                        & self.catalog)
                continue
            if kind == "assistant":
                self.turns += 1
            message = event.get("message")
            content = message.get("content") if isinstance(message, dict) else None
            if not isinstance(content, list):
                continue
            for block in content:
                if not isinstance(block, dict):
                    continue
                if kind == "assistant" and block.get("type") == "tool_use":
                    self.tool_use(block)
                elif kind == "user" and block.get("type") == "text":
                    self.skill_body(str(block.get("text") or ""))

    def codex(self, events: list) -> None:
        for event in events:
            if not isinstance(event, dict):
                continue
            kind = event.get("type")
            item = event.get("item")
            # one command is started, updated and completed: read it once
            if kind == "item.completed" and isinstance(item, dict) \
                    and item.get("type") == "command_execution":
                self.path_evidence("command", str(item.get("command") or ""))
            elif kind == "turn.completed":
                self.turns += 1

    def result(self, reason: str | None, provider: str) -> dict:
        if reason is None and self.evidence:
            status = "observed"
        elif reason is None and self.turns:
            status = "not observed"
        else:
            status = "unknown"
            reason = reason or ("stream has no completed turns" if provider == "codex"
                                else "stream has no assistant messages")
        return {"status": status,
                "names": self.names if status == "observed" else [],
                "evidence": self.evidence if status == "observed" else [],
                "visible": self.visible,
                "reason": reason if status == "unknown" else None}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--provider", choices=("claude", "codex"), required=True)
    parser.add_argument("--catalog", required=True, help="comma-separated skill names")
    parser.add_argument("--skills-dir", help="the sandbox's skills directory")
    parser.add_argument("log")
    args = parser.parse_args()
    catalog = {name for name in args.catalog.split(",") if name}
    reader = Reader(catalog, args.skills_dir)
    try:
        with open(args.log, encoding="utf-8", errors="replace") as handle:
            text = handle.read()
    except OSError as exc:
        print(f"skill_use.py: cannot read {args.log}: {exc}", file=sys.stderr)
        return 1
    reason = None
    if args.provider == "codex":
        events = read_events(text)
        if events is None:
            reason = "no structured events in log"
        else:
            reader.codex(events)
    else:
        shape, payload = load_claude_log(text)
        if shape == "text":
            reason = "no structured events in log"
        elif shape == "object":
            reason = "result-only log (no tool events)"
        else:
            reader.claude(payload)
    print(json.dumps(reader.result(reason, args.provider), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
