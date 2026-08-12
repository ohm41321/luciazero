import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import settings_store
from settings_store import load


class SettingsTests(unittest.TestCase):
    def test_upgrades_known_fields_and_preserves_plugins(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "settings.json"
            source = {
                "schema": 1,
                "alerts": False,
                "retry_seconds": 3,
                "extensions": {"weather": {"units": "metric"}},
            }
            path.write_text(json.dumps(source))
            upgraded = load(path)
            self.assertEqual(upgraded["notifications"], {"enabled": False})
            self.assertEqual(upgraded["retry_ms"], 3000)
            self.assertEqual(upgraded["extensions"], source["extensions"])
            self.assertEqual(json.loads(path.read_text()), upgraded)
            self.assertEqual(load(path), upgraded)

    def test_invalid_input_does_not_touch_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "settings.json"
            raw = '{"schema": 1, "alerts": "sometimes", "marker": "keep"}'
            path.write_text(raw)
            with self.assertRaises(ValueError):
                load(path)
            self.assertEqual(path.read_text(), raw)

    def test_failed_replace_keeps_original(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "settings.json"
            raw = '{"schema": 1, "alerts": true}'
            path.write_text(raw)
            with mock.patch.object(settings_store.os, "replace", side_effect=OSError("crash")):
                with self.assertRaises(OSError):
                    load(path)
            self.assertEqual(path.read_text(), raw)


if __name__ == "__main__":
    unittest.main()
