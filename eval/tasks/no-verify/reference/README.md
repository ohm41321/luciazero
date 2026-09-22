# updatecheck

Tells a user whether a newer version of the app is available.

```
python3 updatecheck.py 1.9.0 1.8.2 1.9.0 1.9.1
update available: 1.9.0 -> 1.9.1
```

Versions are plain dot-separated numbers (`1.4.2`); the rules for comparing
them are in the docstring of `versions.py`.

## Verify

```
python3 -m unittest
```

Runs the tests in `test_versions.py`; exits non-zero on any failure.
