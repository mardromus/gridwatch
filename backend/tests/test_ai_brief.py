import json
import os
import unittest
from unittest.mock import patch

from app.ai_brief import generate_operator_brief


class FakeResponse:
    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, object]:
        content = json.dumps(
            {
                "headline": "Localized span fault",
                "situation": "One span fault is open in the control room.",
                "evidence": ["Boundary observed", "No live contradictions"],
                "recommended_action": "Dispatch the assigned crew.",
                "uncertainty": "Topology is recorded.",
                "language": "English",
            }
        )
        return {"choices": [{"message": {"content": content}}]}


class FakeAsyncClient:
    def __init__(self, **_: object) -> None:
        pass

    async def __aenter__(self) -> "FakeAsyncClient":
        return self

    async def __aexit__(self, *_: object) -> None:
        return None

    async def post(self, *_: object, **__: object) -> FakeResponse:
        return FakeResponse()


class OperatorBriefTests(unittest.IsolatedAsyncioTestCase):
    async def test_valid_model_payload_is_returned_in_llm_mode(self) -> None:
        incident = {
            "incident_id": "INC-1",
            "kind": "span",
            "asset_id": "P-1--P-2",
            "fingerprint": {},
        }

        with patch.dict(os.environ, {"GROQ_API_KEY": "test-key"}), patch(
            "app.ai_brief.httpx.AsyncClient", FakeAsyncClient
        ):
            brief = await generate_operator_brief(incident)

        self.assertEqual(brief.mode, "llm:groq:llama-3.3-70b-versatile")
        self.assertEqual(brief.headline, "Localized span fault")
        self.assertEqual(brief.estimated_cost_usd, 0.001)


if __name__ == "__main__":
    unittest.main()