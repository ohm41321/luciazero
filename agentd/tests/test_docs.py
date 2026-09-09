"""The commands `/lucia-chat` teaches, checked against the CLI that has to run them.

A skill is prose until something parses it. `skills/lucia-chat/SKILL.md` shipped
a workflow the daemon had outgrown -- three terminals, and a promise that
nothing wakes an idle session -- and no test could tell, because no test read
it. These do: every command line the skill quotes goes through the real parser,
every flag it names has to exist, and the sentences that describe the knock are
tied to the constants the knock is built from. A user following this file is
running these commands, so a rename here is a broken instruction there.

What this cannot check is whether a true sentence is the useful one. The three
latencies in section 6 are asserted by name for that reason: they are the
distinction the log kept losing, and a rewrite that drops one of them is the
defect coming back.
"""
from __future__ import annotations

import argparse
import io
import os
import re
import shlex
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from luciazero_agentd import nudge
from luciazero_agentd import __main__ as cli
from luciazero_agentd.__main__ import main, split_command
from luciazero_agentd.store import Store

SKILL = Path(__file__).resolve().parents[2] / "skills" / "lucia-chat" / "SKILL.md"
#: Every spelling of the daemon a reader could type, longest first so the
#: prefix is stripped whole.
LAUNCHERS = ("python3 -m luciazero_agentd", "luciazero-agentd", "lucia")


def fenced(text: str) -> list[str]:
    """Lines inside ``` fences: the commands a reader copies."""
    lines, inside, out = text.splitlines(), False, []
    for line in lines:
        if line.startswith("```"):
            inside = not inside
            continue
        if inside:
            out.append(line)
    return out


def spans(text: str) -> list[str]:
    """Inline `code`, with line breaks flattened -- a span wrapped by the
    paragraph is still one command."""
    return [" ".join(match.split()) for match in re.findall(r"`([^`]+)`", text)]


def commands(text: str) -> list[str]:
    """Every quoted command, fenced or inline, with its launcher stripped."""
    found = []
    for line in fenced(text) + spans(text):
        line = line.split("  #")[0].strip()
        for launcher in LAUNCHERS:
            if line.startswith(launcher + " "):
                found.append(line[len(launcher):].strip())
                break
            if line == launcher:
                break  # the program's own name, not a command
    return found


def option_strings(parser: argparse.ArgumentParser) -> set[str]:
    """Every flag this parser or any subcommand of it accepts."""
    found: set[str] = set()
    for action in parser._actions:  # the parser has no public tree walk
        found.update(action.option_strings)
        if isinstance(action, argparse._SubParsersAction):
            for sub in action.choices.values():
                found |= option_strings(sub)
    return found


class ChatSkillTests(unittest.TestCase):
    """`skills/lucia-chat/SKILL.md` against `luciazero_agentd`."""

    text = SKILL.read_text(encoding="utf-8")

    def test_every_command_the_skill_quotes_resolves_to_a_real_one(self) -> None:
        quoted = commands(self.text)
        # a rewrite that drops the commands entirely must not pass by default
        self.assertGreaterEqual(len(quoted), 10, quoted)
        for command in quoted:
            argv, provider_command = split_command(shlex.split(command))
            with self.subTest(command=command):
                err = io.StringIO()
                try:
                    with redirect_stderr(err), redirect_stdout(io.StringIO()):
                        args = cli.build_parser().parse_args(argv)
                except SystemExit:
                    self.fail(f"the skill quotes `{command}`, which the CLI refuses: {err.getvalue().strip()}")
                self.assertTrue(callable(getattr(args, "func", None)), command)
                if provider_command:
                    self.assertTrue(getattr(args, "takes_provider_command", False),
                                    f"`{command}` passes a command to a subcommand that takes none")

    def test_every_flag_the_skill_names_exists(self) -> None:
        known = option_strings(cli.build_parser())
        named = {flag for line in fenced(self.text) + spans(self.text)
                 for flag in re.findall(r"(?<![\w-])--[a-z][a-z-]*", line)}
        self.assertTrue(named, "the skill names no flags at all")
        self.assertEqual(sorted(named - known), [], f"named in the skill, absent from the CLI (known: {len(known)})")

    def test_the_knock_it_describes_is_the_one_the_bus_types(self) -> None:
        """Section 3 is the part R02 got wrong. Every number in it is a
        constant in `nudge`, so raising the cap without rewriting the sentence
        fails here rather than in a user's terminal."""
        self.assertIn(f"`{nudge.TEXT}`", self.text)
        self.assertIn(f"{int(nudge.COOLDOWN_SECONDS)}-second cooldown", self.text)
        self.assertIn(f"stops after {nudge.MAX_NUDGES} in a row", self.text)
        # the pull-only flow is a separate explanation, not a footnote
        self.assertIn("`--no-nudge` is the pull-only flow", self.text)

    def test_the_three_latencies_stay_three(self) -> None:
        for name in ("delivery latency", "completion latency", "user-attributed blocking cost"):
            self.assertIn(f"**{name}**", self.text)
        # the defect: reading a send-to-ack gap as time a person spent waiting
        self.assertIn("ask the user for the third", self.text)


class ChatCommandTests(unittest.TestCase):
    """What `chat` prints is the same instruction, so it drifts the same way."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="agentd-docs-")
        self.state_dir = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)
        store = Store.open(str(self.state_dir / "bus.sqlite3"))
        store.migrate()
        store.trust = "bound"
        store.register_agent("codex-architect", provider="codex", role="architect")
        store.register_agent("claude-implementer", provider="claude", role="implementer")
        store.close()

    def chat(self, *argv: str) -> str:
        out = io.StringIO()
        with redirect_stdout(out), redirect_stderr(io.StringIO()):
            code = main(["chat", "--state-dir", str(self.state_dir),
                         "--between", "codex-architect", "claude-implementer", *argv])
        self.assertEqual(code, 0)
        return out.getvalue()

    def test_it_names_the_knock_and_the_way_to_turn_it_off(self) -> None:
        printed = self.chat()
        self.assertIn(nudge.TEXT, printed)
        self.assertIn("--no-nudge", printed)

    def test_it_asks_for_a_window_per_agent_and_offers_the_watcher(self) -> None:
        printed = self.chat()
        self.assertNotIn("three terminals", printed)
        self.assertIn("optional", printed)
        self.assertIn("watch --between", printed)


CATALOG = Path(__file__).resolve().parents[2] / "skills" / "catalog.txt"
SKILLS = CATALOG.parent
#: How a skill names a script it ships. The reader resolves the prefix against
#: the directory the skill was installed into, which is the one location that
#: survives a checkout, an npm package, and either provider's install.
BUNDLED = "<this-skill-dir>/scripts/"


def cataloged() -> list[str]:
    """The skills the installers copy, from the file they read."""
    names = []
    for line in CATALOG.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            names.append(line)
    return names


class BundledScriptTests(unittest.TestCase):
    """A script a skill tells the reader to run has to be findable from it.

    `skills/lucia-relay/SKILL.md` said `relay.py` six times. The file it means
    is installed beside the skill, at `<this-skill-dir>/scripts/relay.py`, and
    nothing puts that directory on PATH -- so a reader who followed Relay after
    a normal install failed on its first command, while Ready, Bisect and Done,
    whose scripts sit in exactly the same place, named theirs the way that
    resolves. Prose is the only thing carrying that difference, so a test reads
    it: every mention of a bundled script's name has to carry the prefix, and
    the file it points at has to be there and be runnable.
    """

    def test_every_bundled_script_is_named_by_a_path_that_resolves(self) -> None:
        named = 0
        for name in cataloged():
            skill = SKILLS / name
            body = (skill / "SKILL.md").read_text()
            for script in sorted((skill / "scripts").glob("*")):
                if not script.is_file():
                    continue
                for hit in re.finditer(re.escape(script.name), body):
                    start = hit.start()
                    self.assertEqual(
                        body[max(0, start - len(BUNDLED)):start], BUNDLED,
                        f"skills/{name}/SKILL.md names {script.name} without "
                        f"the {BUNDLED} prefix, so the command it teaches does "
                        f"not resolve after an install")
                    named += 1
        self.assertGreater(named, 0, "no skill named a bundled script; this read nothing")

    def test_every_bundled_script_is_there_and_executable(self) -> None:
        for name in cataloged():
            for script in sorted((SKILLS / name / "scripts").glob("*")):
                if not script.is_file():
                    continue
                self.assertTrue(
                    os.access(script, os.X_OK),
                    f"skills/{name}/scripts/{script.name} is not executable, so "
                    f"the command the skill quotes cannot run")


if __name__ == "__main__":
    unittest.main()
