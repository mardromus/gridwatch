import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.main import frontend_file


class FrontendFileTests(unittest.TestCase):
    def test_resolves_frontend_files_but_not_paths_outside_static_root(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            static_root = root / "static"
            static_root.mkdir()
            index = static_root / "index.html"
            asset = static_root / "app.js"
            secret = root / "secret.txt"
            index.write_text("shell", encoding="utf-8")
            asset.write_text("bundle", encoding="utf-8")
            secret.write_text("secret", encoding="utf-8")

            with patch("app.main.static_dir", static_root):
                self.assertEqual(frontend_file("app.js"), asset)
                self.assertEqual(frontend_file("../secret.txt"), index)


if __name__ == "__main__":
    unittest.main()