import tempfile
import unittest
import zipfile
from pathlib import Path

from archive_store import restore


class RestoreTests(unittest.TestCase):
    def test_restores_nested_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            archive = root / "backup.zip"
            with zipfile.ZipFile(archive, "w") as bundle:
                bundle.writestr("notes/today.txt", "hello")
            restore(archive, root / "output")
            self.assertEqual((root / "output/notes/today.txt").read_text(), "hello")


if __name__ == "__main__":
    unittest.main()
