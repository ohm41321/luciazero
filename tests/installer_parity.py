#!/usr/bin/env python3
"""Installer parity: the Bash installers and their Node port, side by side.

Windows runs bin/lib/installer.js; macOS and Linux run install.sh and its
three siblings. Both must do the same thing, so each scenario below is played
twice from identical fixtures -- once through the shell scripts, once through
the Node module -- and after every step the two runs must agree on the exit
status, on stdout and stderr line for line, and on the resulting tree entry
for entry: kind, bytes, symlink target and permission bits. The only thing
normalized is what cannot match: the sandbox path and the backup timestamp.

POSIX only, since one side is Bash. Usage: installer_parity.py <repo root>
"""
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile

ROOT = os.path.abspath(sys.argv[1])
NODE = shutil.which("node")
# A backup name carries the second it was taken and, when that second already
# had one, a counter -- which the two runs need not share. Messages lose both;
# the tree keeps their order, so a run that made two backups where the other
# made one still differs.
STAMP = re.compile(r"\.bak\.\d{14}(?:\.\d+)?")
BACKUP = re.compile(r"^(.*\.bak\.)(\d{14})(?:\.(\d+))?$")

SHELL = {
    "claude": ["bash", os.path.join(ROOT, "install.sh")],
    "claude-uninstall": ["bash", os.path.join(ROOT, "uninstall.sh")],
    "codex": ["bash", os.path.join(ROOT, "install-codex.sh")],
    "codex-uninstall": ["bash", os.path.join(ROOT, "uninstall-codex.sh")],
}


def node_cmd(name):
    return [NODE, os.path.join(ROOT, "bin", "lib", "installer.js"), name]


def write(path, data, mode=None):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(data if isinstance(data, bytes) else data.encode())
    if mode is not None:
        os.chmod(path, mode)


def env_for(box):
    shim = os.path.join(box, "shim")
    os.makedirs(shim, exist_ok=True)
    write(os.path.join(shim, "claude"), "#!/bin/sh\necho '2.1.140 (Claude Code)'\n", 0o755)
    return {
        "PATH": os.pathsep.join([shim, os.path.dirname(NODE), "/usr/bin", "/bin", "/usr/sbin", "/sbin"]),
        "HOME": os.path.join(box, "home"),
        "TMPDIR": os.path.join(box, "tmp"),
        "LANG": "C",
        "LC_ALL": "C",
        "CLAUDE_CONFIG_DIR": os.path.join(box, "home", ".claude"),
        "CODEX_HOME": os.path.join(box, "home", ".codex"),
        # never the real service files: uninstall stops what it finds here
        "LUCIAZERO_SERVICE_ROOT": os.path.join(box, "no-service"),
    }


# The status line names its script as base64 (settings-wiring.js), so the
# sandbox path inside it is only found once decoded.
B64 = re.compile(rb"Buffer\.from\('([A-Za-z0-9+/=]*)','base64'\)")


def unbox(data, box):
    import base64
    data = B64.sub(lambda m: b"Buffer.from(<" + base64.b64decode(m.group(1)) + b">)", data)
    return data.replace(box.encode(), b"<box>")


def ordinals(base):
    """Each backup name -> '<base>.bak.#k', k its place among its siblings."""
    taken = {}
    for dirpath, dirs, files in os.walk(base):
        for name in dirs + files:
            m = BACKUP.match(name)
            if m:
                taken.setdefault((dirpath, m.group(1)), []).append((m.group(2), int(m.group(3) or 0), name))
    out = {}
    for (dirpath, prefix), names in taken.items():
        for k, (_, _, name) in enumerate(sorted(names), 1):
            out[os.path.join(dirpath, name)] = prefix + "#%d" % k
    return out


def snapshot(base, box):
    out = {}
    if not os.path.lexists(base):
        return out
    renamed = ordinals(base)
    for dirpath, dirs, files in os.walk(base):
        dirs.sort()
        for name in sorted(dirs) + sorted(files):
            p = os.path.join(dirpath, name)
            parts, q = [], p
            while q != base:
                parts.append(os.path.basename(renamed.get(q, q)))
                q = os.path.dirname(q)
            rel = "/".join(reversed(parts))
            st = os.lstat(p)
            if stat.S_ISLNK(st.st_mode):
                entry = ("link", os.readlink(p).replace(box, "<box>"))
            elif stat.S_ISDIR(st.st_mode):
                entry = ("dir", oct(st.st_mode & 0o777))
            else:
                with open(p, "rb") as f:
                    data = f.read()
                entry = ("file", oct(st.st_mode & 0o777), unbox(data, box))
            out[rel] = entry
    return out


def normalize(text, box):
    return STAMP.sub(".bak.<stamp>", unbox(text.encode(), box).decode("utf-8", "replace"))


class Pair:
    def __init__(self, top, name):
        self.boxes = {}
        for side in ("sh", "node"):
            box = os.path.join(top, name, side)
            os.makedirs(os.path.join(box, "home"))
            os.makedirs(os.path.join(box, "tmp"))
            self.boxes[side] = box
        self.name = name
        self.step = 0

    def both(self, fn):
        for side, box in self.boxes.items():
            fn(box)

    def run(self, command, *args):
        self.step += 1
        got = {}
        for side, box in self.boxes.items():
            cmd = (SHELL[command] if side == "sh" else node_cmd(command)) + list(args)
            p = subprocess.run(cmd, env=env_for(box), cwd=os.path.join(box, "home"),
                               capture_output=True, timeout=300)
            got[side] = (
                p.returncode,
                normalize(p.stdout.decode("utf-8", "replace"), box),
                normalize(p.stderr.decode("utf-8", "replace"), box),
                snapshot(os.path.join(box, "home"), box),
            )
        a, b = got["sh"], got["node"]
        where = "%s step %d (%s %s)" % (self.name, self.step, command, " ".join(args))
        problems = []
        if a[0] != b[0]:
            problems.append("exit status: sh %d, node %d" % (a[0], b[0]))
        for i, stream in ((1, "stdout"), (2, "stderr")):
            if a[i] != b[i]:
                la, lb = a[i].splitlines(), b[i].splitlines()
                for n in range(max(len(la), len(lb))):
                    x = la[n] if n < len(la) else "<none>"
                    y = lb[n] if n < len(lb) else "<none>"
                    if x != y:
                        problems.append("%s line %d:\n      sh:   %s\n      node: %s" % (stream, n + 1, x, y))
                        break
        if a[3] != b[3]:
            for rel in sorted(set(a[3]) | set(b[3])):
                x, y = a[3].get(rel), b[3].get(rel)
                if x != y:
                    at = 0
                    if x and y and x[0] == y[0] == "file":
                        while at < min(len(x[2]), len(y[2])) and x[2][at] == y[2][at]:
                            at += 1
                    short = lambda e: e if e is None or e[0] != "file" else (e[0], e[1], e[2][max(0, at - 40):at + 60])
                    problems.append("tree %s:\n      sh:   %r\n      node: %r" % (rel, short(x), short(y)))
                    if len(problems) > 6:
                        break
        if problems:
            print("FAIL: installer parity, " + where)
            for p in problems:
                print("   " + p)
            raise SystemExit(1)
        return a


def cfg(box, *parts):
    return os.path.join(box, "home", ".claude", *parts)


def codex(box, *parts):
    return os.path.join(box, "home", ".codex", *parts)


def scenarios(top):
    legacy_status = open(os.path.join(ROOT, "tests", "fixtures", "legacy-luciazero-statusline.sh"), "rb").read()

    s = Pair(top, "claude-fresh")
    s.run("claude", "--status")
    s.run("claude")
    s.run("claude", "--status")
    s.run("claude")
    s.run("claude", "--with-hooks")
    s.run("claude", "--status")
    s.run("claude", "--with-hooks")
    s.run("claude-uninstall")
    s.run("claude-uninstall")
    s.run("claude", "--bogus")

    s = Pair(top, "claude-existing")

    def existing(box):
        write(cfg(box, "CLAUDE.md"), "# mine\n\nkeep this")
        write(cfg(box, "skills", "plan", "SKILL.md"), "---\nname: plan\n---\n# someone else's plan\n")
        os.makedirs(os.path.join(box, "outside", "debug"))
        write(os.path.join(box, "outside", "debug", "SKILL.md"), "my debug skill\n")
        os.symlink(os.path.join(box, "outside", "debug"), cfg(box, "skills", "debug"))
        write(cfg(box, "luciazero.md"), "my own doctrine notes\n", 0o640)
        write(cfg(box, "agents", "reviewer.md"), "someone's reviewer\n")
        write(cfg(box, "settings.json"),
              '{\n  "statusLine": {"type": "command", "command": "my-status"},\n'
              '  "hooks": {"Stop": [{"hooks": [{"type": "command", "command": "my-stop"}]}]}\n}\n', 0o600)
        write(cfg(box, "hooks", "luciazero-statusline.sh"), legacy_status, 0o755)
        write(cfg(box, "hooks", "luciazero-verify.sh"), "#!/bin/sh\n# edited by hand\n", 0o755)
        write(cfg(box, "bin", "lucia"), "#!/bin/sh\necho not ours\n", 0o755)
    s.both(existing)
    s.run("claude", "--with-hooks")
    s.run("claude", "--status")
    s.run("claude", "--with-hooks")
    s.run("claude-uninstall")

    s = Pair(top, "claude-separator")
    s.both(lambda box: write(cfg(box, "CLAUDE.md"), "# mine\n\nkeep this\n", 0o640))
    s.run("claude")
    s.run("claude")
    s.run("claude-uninstall")
    for side, box in s.boxes.items():
        with open(cfg(box, "CLAUDE.md"), "rb") as f:
            if f.read() != b"# mine\n\nkeep this\n":
                print("FAIL: installer parity, claude-separator: %s CLAUDE.md did not come back byte for byte" % side)
                raise SystemExit(1)

    s = Pair(top, "claude-separator-edited")
    s.both(lambda box: write(cfg(box, "CLAUDE.md"), "# mine\n"))
    s.run("claude")
    s.both(lambda box: open(cfg(box, "CLAUDE.md"), "ab").write(b"\nadded later\n"))
    s.run("claude-uninstall")

    s = Pair(top, "claude-import-own")
    s.both(lambda box: write(cfg(box, "CLAUDE.md"), "# notes\n\n@luciazero.md\n"))
    s.run("claude")
    s.run("claude-uninstall")

    s = Pair(top, "claude-import-only")
    s.run("claude")
    s.both(lambda box: write(cfg(box, "extra.txt"), "x\n"))
    s.run("claude-uninstall")

    s = Pair(top, "claude-bad-settings")
    s.both(lambda box: write(cfg(box, "settings.json"), "{not json\n"))
    s.run("claude", "--with-hooks")
    s.run("claude", "--status")
    s.run("claude-uninstall")

    s = Pair(top, "claude-retired")

    def retired(box):
        write(cfg(box, "skills", "handoff", "SKILL.md"),
              open(os.path.join(ROOT, "migrations", "handoff-v1.5.0.SKILL.md"), "rb").read())
        src = os.path.join(ROOT, "migrations", "luciazero-bootstrap-v2.2.0", "SKILL.md")
        write(cfg(box, "skills", "luciazero-bootstrap", "SKILL.md"), open(src, "rb").read())
        write(cfg(box, ".luciazero-managed", "skills", "luciazero-bootstrap", "SKILL.md"), open(src, "rb").read())
    s.both(retired)
    s.run("claude")
    s.run("claude-uninstall")

    # A retired skill already gone by hand leaves only its snapshot, which
    # goes quietly; one the user changed stays, with a warning.
    s = Pair(top, "claude-retired-leftovers")

    def leftovers(box):
        src = os.path.join(ROOT, "migrations", "luciazero-bootstrap-v2.2.0", "SKILL.md")
        write(cfg(box, ".luciazero-managed", "skills", "luciazero-bootstrap", "SKILL.md"), open(src, "rb").read())
    s.both(leftovers)
    s.run("claude")
    s.both(leftovers)
    s.both(lambda box: write(cfg(box, "skills", "luciazero-bootstrap", "SKILL.md"), b"changed by the user\n"))
    s.run("claude")
    s.run("claude-uninstall")

    s = Pair(top, "codex-fresh")
    s.run("codex")
    s.run("codex")
    s.run("codex-uninstall")
    s.run("codex-uninstall")
    s.run("codex", "--bogus")

    for name, text in (("codex-terminated", "# rules\n\nbe careful\n"),
                       ("codex-unterminated", "# rules\n\nno final newline"),
                       ("codex-blank-tail", "# rules\n\n\n")):
        s = Pair(top, name)
        s.both(lambda box, t=text: write(codex(box, "AGENTS.md"), t, 0o640))
        s.run("codex")
        s.run("codex")
        s.run("codex-uninstall")
        for side, box in s.boxes.items():
            with open(codex(box, "AGENTS.md"), "rb") as f:
                if f.read() != text.encode():
                    print("FAIL: installer parity, %s: %s AGENTS.md did not come back byte for byte" % (name, side))
                    raise SystemExit(1)

    s = Pair(top, "codex-ambiguous")
    s.both(lambda box: write(codex(box, "AGENTS.md"), "<!-- luciazero:start -->\nx\n"))
    s.run("codex")
    s.run("codex-uninstall")

    s = Pair(top, "codex-collision")
    s.both(lambda box: write(codex(box, "skills", "plan", "SKILL.md"), "theirs\n"))
    s.run("codex")
    s.run("codex-uninstall")


def main():
    if NODE is None:
        print("FAIL: installer parity needs node")
        return 1
    top = tempfile.mkdtemp(prefix="luciazero-parity.")
    try:
        scenarios(top)
    finally:
        shutil.rmtree(top, ignore_errors=True)
    print("ok  installer parity: the Node installers match the Bash ones step for step")
    return 0


if __name__ == "__main__":
    sys.exit(main())
