# Lucia Relay

> Generated from `LUCIA_RELAY.json`; the JSON artifact is canonical. Re-verify every claim against the current tree.

Created: 2026\-08\-13T00:05:00\+00:00
Source: reference / fixture

## Goal

Make split\_fields preserve semicolons inside quoted fields while retaining Python 3\.8 compatibility\.

## Repository fingerprint

- HEAD: <code>15b6724c5104972123f72d515687507abdcde828</code>
- Branch: <code>main</code>
- Dirty: <code>False</code>
- Diff SHA-256: <code>e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855</code>

## Done

- Reproduced the quoted\-separator failure
- Added a regression test for the failing ASCII input

## In progress

- The parser implementation is intentionally untouched

## Next step

edit: <code>Edit parser.py to use csv.reader with delimiter=&#x27;;&#x27;, then run ./verify.sh</code>

## Verification evidence

| Command | Exit | Decisive line | Run at |
|---|---:|---|---|
| <code>./verify.sh</code> | 1 | FAIL quoted separator: expected \[&\#x27;alpha&\#x27;, &\#x27;bravo;charlie&\#x27;, &\#x27;delta&\#x27;\] | 2026\-08\-13T00:04:00\+00:00 |

## Read first

- docs/lessons\.md — quoted delimiters are parser syntax

## Hypotheses

- <code>{&quot;claim&quot;: &quot;Input encoding corrupts the separator&quot;, &quot;evidence&quot;: &quot;The ASCII fixture fails too&quot;, &quot;id&quot;: &quot;H1&quot;, &quot;status&quot;: &quot;refuted&quot;}</code>

## Landmines

- Keep Python 3\.8 compatibility; do not introduce newer syntax

## Files

Modified:

None recorded.

Untracked:

None recorded.
