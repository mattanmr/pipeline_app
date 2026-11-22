import tempfile
import unittest
from pathlib import Path

from core.io_handler import safe_copy
from utils.naming import sanitize_name


class SecurityRegressionTests(unittest.TestCase):
    def test_dot_names_are_rejected(self):
        for name in (".", ".."):
            with self.subTest(name=name):
                with self.assertRaises(ValueError):
                    sanitize_name(name)

    def test_safe_copy_rejects_symbolic_link_file(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp = Path(temp_dir)
            target = temp / "target.txt"
            target.write_text("sensitive", encoding="utf-8")
            link = temp / "link.txt"
            try:
                link.symlink_to(target)
            except (OSError, NotImplementedError):
                self.skipTest("Symbolic links are unavailable")

            with self.assertRaises(ValueError):
                safe_copy(link, temp / "copy.txt")


if __name__ == "__main__":
    unittest.main()
