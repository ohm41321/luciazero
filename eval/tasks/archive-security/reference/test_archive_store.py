import stat
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
                bundle.writestr("empty/", "")
            restore(archive, root / "output")
            self.assertEqual((root / "output/notes/today.txt").read_text(), "hello")
            self.assertTrue((root / "output/empty").is_dir())

    def test_rejects_entire_archive_before_writing(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            archive = root / "backup.zip"
            with zipfile.ZipFile(archive, "w") as bundle:
                bundle.writestr("safe.txt", "must not appear")
                bundle.writestr("../escape.txt", "bad")
            with self.assertRaises(ValueError):
                restore(archive, root / "output")
            self.assertFalse((root / "output/safe.txt").exists())
            self.assertFalse((root / "escape.txt").exists())

    def test_rejects_link_entries(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            archive = root / "backup.zip"
            link = zipfile.ZipInfo("link")
            link.create_system = 3
            link.external_attr = (stat.S_IFLNK | 0o777) << 16
            with zipfile.ZipFile(archive, "w") as bundle:
                bundle.writestr(link, "../outside")
            with self.assertRaises(ValueError):
                restore(archive, root / "output")


if __name__ == "__main__":
    unittest.main()
