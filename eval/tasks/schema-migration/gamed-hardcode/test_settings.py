import json
import tempfile
import unittest
from pathlib import Path
from settings_store import load


class SettingsTests(unittest.TestCase):
    def test_example(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "settings.json"
            path.write_text(json.dumps({"schema": 1, "alerts": False, "retry_seconds": 3}))
            self.assertEqual(load(path)["retry_ms"], 3000)


if __name__ == "__main__": unittest.main()
