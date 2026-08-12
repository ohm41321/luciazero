import tempfile
import unittest
import zipfile
from pathlib import Path

from archive_store import restore


class RestoreTests(unittest.TestCase):
    def test_rejects_parent_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            archive = root / "backup.zip"
            with zipfile.ZipFile(archive, "w") as bundle:
                bundle.writestr("../escape", "bad")
            with self.assertRaises(ValueError):
                restore(archive, root / "output")


if __name__ == "__main__":
    unittest.main()
