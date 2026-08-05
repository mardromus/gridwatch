import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from app.ai_brief import deterministic_brief
from app.main import BriefRequest, brief_cache, frontend_file, operator_brief, service


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


class OperatorBriefCacheTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        service.reset()
        brief_cache.clear()

    def tearDown(self) -> None:
        service.reset()
        brief_cache.clear()

    async def test_same_incident_brief_uses_model_adapter_once(self) -> None:
        service.inject("span")
        incident = next(iter(service.incidents.values()))
        expected = deterministic_brief(incident.to_dict(), "English")
        adapter = AsyncMock(return_value=expected)

        with patch("app.main.generate_operator_brief", adapter):
            first = await operator_brief(incident.incident_id, BriefRequest())
            second = await operator_brief(incident.incident_id, BriefRequest())

        self.assertEqual(first, expected)
        self.assertEqual(second, expected)
        adapter.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()