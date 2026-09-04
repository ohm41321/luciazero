"""Secret redaction for everything the bus stores or shows (M3).

Applied to message and task payloads, task titles, agent roles and
capabilities, event payloads, tool results and tool error messages before
they touch the database or a peer. Provider adapters (M6) must pass captured
model output through ``Redactor`` as well; nothing else is allowed to write
free text into the store.

Two tiers:

- ``strict`` rules are unambiguous secret shapes (PEM private keys, bearer
  credentials, approval nonces, cloud and platform tokens, URL userinfo).
  They are scrubbed from free text and, because they cannot be rewritten
  inside an identifier, a path or a file without breaking it, they make an
  id field, an artifact ref, artifact content or a worktree path *refused*
  (``Redactor.scan``).
- The ``key = value`` heuristic (``password=...``, ``access_token: ...``)
  scrubs free text only, and only when the value carries a digit, so prose
  ("password: required for login") and ordinary code
  (``token = request.headers.get(...)``) survive. It is left out of ``scan``
  so a patch artifact is never refused for it.

Inside JSON, keys are scrubbed like values, and a string under a key whose
name contains a secret word (``password``, ``client_secret``,
``GITHUB_TOKEN``, ``AWS_SECRET_ACCESS_KEY``) is blanked whatever it looks
like.

Literal secrets the daemon knows (its own capability token) are added at
construction time and count as strict.
"""

from __future__ import annotations

import re
from typing import Any, Iterable, NamedTuple, Pattern

NONCE_PREFIX = "lzap_"
NONCE_PATTERN = re.compile(r"^lzap_[0-9a-f]{32}$")
# Session credential of a terminal binding (ADR 0004). Same handling as an
# approval nonce: minted in the human channel, stored as a sha256, and
# refused in every channel an agent can write to.
CREDENTIAL_PREFIX = "lzsc_"
CREDENTIAL_PATTERN = re.compile(r"^lzsc_[0-9a-f]{32}$")
SECRET_WORD = r"(?:api[_-]?key|secret|password|passwd|token)"
# The secret word may sit mid-name (AWS_SECRET_ACCESS_KEY, token_v2); the
# trailing run is short so "token_type" style names still qualify but a
# sentence never does.
SECRET_KEY = re.compile(rf"(?i)^[A-Za-z0-9_.-]{{0,60}}{SECRET_WORD}[A-Za-z0-9_.-]{{0,20}}$")


class Rule(NamedTuple):
    label: str
    pattern: Pattern[str]
    replacement: str
    strict: bool


# Applied in this order. Every quantifier that could run over hyphenated or
# repetitive text is bounded, so a 64 KiB payload stays linear.
RULES: tuple[Rule, ...] = (
    Rule("private-key", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----", re.S), "[redacted:private-key]", True),
    # In header context every value after "Bearer" is a credential, digits or
    # not. Outside it ("the bearer credentials keep users out") the value
    # must carry a digit; an all-letter opaque token pasted bare is the one
    # accepted false negative, stated in ADR 0003.
    Rule("bearer", re.compile(r"(?i)\bauthorization\s*[:=]\s*bearer\s+[A-Za-z0-9._~+/=-]{8,}"), "Authorization: Bearer [redacted]", True),
    Rule("bearer", re.compile(r"(?i)\bbearer\s+(?=[A-Za-z0-9._~+/=-]{0,256}\d)[A-Za-z0-9._~+/=-]{8,}"), "Bearer [redacted]", True),
    Rule("approval-nonce", re.compile(r"\blzap_[A-Za-z0-9_-]{16,}"), "[redacted:approval-nonce]", True),
    Rule("session-credential", re.compile(r"\blzsc_[A-Za-z0-9_-]{16,}"), "[redacted:session-credential]", True),
    Rule("aws-key", re.compile(r"\bAKIA[0-9A-Z]{16}\b"), "[redacted:aws-key]", True),
    Rule("github-token", re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{20,}\b"), "[redacted:github-token]", True),
    Rule("github-token", re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}\b"), "[redacted:github-token]", True),
    Rule("api-key", re.compile(r"\bsk-(?=[A-Za-z0-9_-]{0,256}\d)[A-Za-z0-9_-]{20,}\b"), "[redacted:api-key]", True),
    Rule("slack-token", re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}\b"), "[redacted:slack-token]", True),
    Rule("url-credential", re.compile(r"(?i)\b([a-z][a-z0-9+.-]{0,31}://)[^/\s@:]{0,256}:[^/\s@]{1,1024}@"), r"\1[redacted]@", True),
    Rule("secret-assignment", re.compile(rf"(?i)\b([A-Za-z0-9_-]{{0,40}}?{SECRET_WORD}[A-Za-z0-9_-]{{0,20}})(\s*[=:]\s*)(['\"]?)(?=[^\s'\"]{{0,256}}\d)([^\s'\"]{{8,}})"), r"\1\2\3[redacted]", False),
)

CREDENTIAL_URL = re.compile(r"(?i)\b[a-z][a-z0-9+.-]{0,31}://[^/\s@:]{0,256}:[^/\s@]{1,1024}@")


class Redactor:
    """Stateless text scrubber; ``literals`` are exact secrets to blank too."""

    def __init__(self, literals: Iterable[str] = ()) -> None:
        self._literals = tuple(sorted({x for x in literals if isinstance(x, str) and len(x) >= 8}, key=len, reverse=True))

    def text(self, value: str) -> tuple[str, int]:
        """Return the scrubbed text and how many replacements were made."""
        count = 0
        for literal in self._literals:
            if literal in value:
                count += value.count(literal)
                value = value.replace(literal, "[redacted]")
        for rule in RULES:
            value, n = rule.pattern.subn(rule.replacement, value)
            count += n
        return value, count

    def scan(self, value: str) -> list[str]:
        """Labels of every strict secret shape (and known literal) present in
        ``value``; empty when it is clean. Used where scrubbing is impossible
        because the value must stay intact: ids, artifact refs, file
        contents, worktree paths."""
        found: list[str] = []
        if any(literal in value for literal in self._literals):
            found.append("daemon-token")
        for rule in RULES:
            if rule.strict and rule.pattern.search(value):
                found.append(rule.label)
        return found

    def json(self, value: Any) -> tuple[Any, int]:
        """Scrub every string inside a JSON-like structure, keys included.
        A string under a secret-named key is blanked outright."""
        if isinstance(value, str):
            return self.text(value)
        if isinstance(value, list):
            out_list: list[Any] = []
            total = 0
            for item in value:
                scrubbed, n = self.json(item)
                out_list.append(scrubbed)
                total += n
            return out_list, total
        if isinstance(value, dict):
            out_dict: dict[Any, Any] = {}
            total = 0
            for key, item in value.items():
                clean_key = key
                if isinstance(key, str):
                    clean_key, n = self.text(key)
                    total += n
                if isinstance(key, str) and isinstance(item, str) and len(item) >= 8 and SECRET_KEY.fullmatch(key):
                    scrubbed, n = "[redacted]", 1
                else:
                    scrubbed, n = self.json(item)
                out_dict[clean_key] = scrubbed
                total += n
            return out_dict, total
        return value, 0


def find_credential_url(value: Any) -> str | None:
    """Return the first string carrying ``scheme://user:secret@`` inside a
    JSON-like structure, or ``None``. Such URLs are refused, not scrubbed: a
    peer that needs the repository must be told to fetch it through its own
    credentials rather than receive them through the bus."""
    if isinstance(value, str):
        return value if CREDENTIAL_URL.search(value) else None
    if isinstance(value, list):
        for item in value:
            hit = find_credential_url(item)
            if hit is not None:
                return hit
        return None
    if isinstance(value, dict):
        for item in value.values():
            hit = find_credential_url(item)
            if hit is not None:
                return hit
    return None


DEFAULT = Redactor()
