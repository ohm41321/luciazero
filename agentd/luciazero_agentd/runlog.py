"""Bounded, redacted run logs (ADR 0006).

Provider output is the one place the daemon writes text it did not compose, so
it is the place ADR 0003's redaction contract has to be paid: every chunk goes
through the ``Redactor`` -- with the daemon token and the run's own credential
as literals -- before it reaches the disk, and the file is capped so a chatty
or looping provider cannot fill the state directory.

The cap keeps the head and the tail, which are the two parts anybody reads: the
head says how the turn started, the tail says how it ended, and the marker in
between says exactly how much was dropped.

Redaction happens once, over each whole buffer, at close. Scrubbing each chunk as
it arrived was the obvious design and it was wrong: a provider that prints a
secret across two lines defeated it completely, because neither half matched on
its own. For the same reason, when the cap drops the middle, a margin is
dropped from each side of the gap as well, so a secret split by the drop loses
at least one half outright instead of leaving both in the file.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Optional

from .redact import CREDENTIAL_PREFIX, Redactor

DEFAULT_MAX_BYTES = 256 * 1024
MARKER = "\n... {dropped} bytes dropped by the run-log cap ...\n"
# Dropped from each side of the gap so a secret split by the cap cannot
# survive as two halves. Comfortably longer than any secret shape.
MARGIN_BYTES = 256
# A provider that wraps its output can put a newline inside a secret, and
# neither half matches on its own. These patterns tolerate whitespace between
# any two characters, which is what a wrapped or line-split secret looks like.
WRAPPED_CREDENTIAL = re.compile(r"\s*".join(re.escape(ch) for ch in CREDENTIAL_PREFIX) + r"(?:\s*[0-9a-fA-F]){32}")


def wrapped(literal: str) -> re.Pattern[str]:
    """Match a literal even when whitespace was inserted inside it."""
    return re.compile(r"\s*".join(re.escape(ch) for ch in literal))


class RunLog:
    """One turn's output. Not thread-safe; one writer per run."""

    def __init__(self, path: str | Path, *, redactor: Optional[Redactor] = None, literals: tuple[str, ...] = (), max_bytes: int = DEFAULT_MAX_BYTES) -> None:
        if max_bytes < 1024:
            raise ValueError("a run log needs at least 1 KiB")
        self.path = Path(path)
        # A redactor built here owns the literals; one passed in is assumed to
        # know its own, and the extras are added on top.
        self._redactor = Redactor([*literals]) if redactor is None else redactor
        self._extra = tuple(literal for literal in literals if literal)
        self._wrapped = tuple(wrapped(literal) for literal in self._extra)
        self.max_bytes = max_bytes
        self._head = bytearray()
        self._tail = bytearray()
        self._dropped = 0
        self._closed = False
        self.path.parent.mkdir(parents=True, exist_ok=True)

    @property
    def half(self) -> int:
        return self.max_bytes // 2

    def _scrub(self, text: str) -> str:
        scrubbed, _ = self._redactor.text(text)
        for literal in self._extra:
            scrubbed = scrubbed.replace(literal, "[redacted]")
        # Then the same secrets again, tolerating whitespace inside them: a
        # wrapped line is the ordinary way a credential ends up split, and two
        # halves in one file are one secret to whoever reads it.
        for pattern in self._wrapped:
            scrubbed = pattern.sub("[redacted]", scrubbed)
        return WRAPPED_CREDENTIAL.sub("[redacted]", scrubbed)

    def write(self, chunk: str) -> None:
        """Buffer one chunk. Redaction runs over the whole buffer at close, so
        a secret a provider printed across two lines is still caught; nothing
        reaches the disk before then."""
        if self._closed:
            raise ValueError("the run log is closed")
        if not chunk:
            return
        data = chunk.encode("utf-8", "replace")
        room = self.half - len(self._head)
        if room > 0:
            self._head.extend(data[:room])
            data = data[room:]
        if not data:
            return
        self._tail.extend(data)
        if len(self._tail) > self.half:
            excess = len(self._tail) - self.half
            del self._tail[:excess]
            self._dropped += excess

    def close(self) -> str:
        """Scrub, write the file (0600), and return the ref recorded on the run."""
        if not self._closed:
            self._closed = True
            head, tail, dropped = bytes(self._head), bytes(self._tail), self._dropped
            if dropped:
                # A secret straddling the gap would otherwise survive as two
                # halves; dropping a margin from each side removes one of them.
                margin = min(MARGIN_BYTES, len(head), len(tail))
                if margin:
                    head, tail = head[:-margin], tail[margin:]
                    dropped += 2 * margin
            body = self._scrub(head.decode("utf-8", "replace")).encode("utf-8")
            if dropped:
                body += MARKER.format(dropped=dropped).encode("utf-8")
            body += self._scrub(tail.decode("utf-8", "replace")).encode("utf-8")
            handle = os.open(str(self.path), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            try:
                os.write(handle, body)
            finally:
                os.close(handle)
        return str(self.path)

    @property
    def dropped(self) -> int:
        return self._dropped

    def __enter__(self) -> "RunLog":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()
