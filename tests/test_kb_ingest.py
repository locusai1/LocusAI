# tests/test_kb_ingest.py — build KB entries from a website URL

from unittest.mock import MagicMock, patch


class _Resp:
    def __init__(self, content=b"", status=200, ctype="text/html; charset=utf-8", encoding="utf-8"):
        self.content = content
        self.status_code = status
        self.headers = {"Content-Type": ctype}
        self.encoding = encoding


class TestHtmlToText:
    def test_strips_script_and_style(self):
        from core.kb_ingest import _html_to_text

        html = "<html><head><style>.a{color:red}</style></head><body><h1>Hi</h1>"
        html += "<script>alert(1)</script><p>We open at 9am.</p></body></html>"
        text = _html_to_text(html)
        assert "Hi" in text
        assert "We open at 9am." in text
        assert "alert" not in text
        assert "color:red" not in text


class TestFetch:
    def test_rejects_unsafe_url(self):
        from core import kb_ingest

        with patch("core.webhooks.is_safe_url", return_value=False):
            ok, msg = kb_ingest.fetch_page_text("http://169.254.169.254/")
        assert ok is False
        assert "isn't allowed" in msg

    def test_fetches_and_extracts(self):
        from core import kb_ingest

        resp = _Resp(content=b"<body><p>Haircuts cost 25 pounds.</p></body>")
        with (
            patch("core.webhooks.is_safe_url", return_value=True),
            patch("requests.get", return_value=resp),
        ):
            ok, text = kb_ingest.fetch_page_text("https://example.com")
        assert ok is True
        assert "Haircuts cost 25 pounds." in text

    def test_rejects_non_html(self):
        from core import kb_ingest

        resp = _Resp(content=b"%PDF-1.4", ctype="application/pdf")
        with (
            patch("core.webhooks.is_safe_url", return_value=True),
            patch("requests.get", return_value=resp),
        ):
            ok, msg = kb_ingest.fetch_page_text("https://example.com/x.pdf")
        assert ok is False


class TestSuggestFromWebsite:
    def test_not_configured(self):
        from core import kb_ingest

        with patch("core.kb_suggestions.is_configured", return_value=False):
            out = kb_ingest.suggest_from_website(1, "https://example.com")
        assert out["configured"] is False

    def test_happy_path_dedupes(self):
        from core import kb_ingest

        llm = (
            '{"suggestions":[{"question":"Do you do balayage?","answer":"Yes."},'
            '{"question":"What are your hours?","answer":"9 to 5."}]}'
        )
        with (
            patch("core.kb_suggestions.is_configured", return_value=True),
            patch(
                "core.kb_ingest.fetch_page_text",
                return_value=(True, "We offer balayage and open 9 to 5. " * 10),
            ),
            patch("core.kb_suggestions.existing_questions", return_value=["What are your hours?"]),
            patch("core.kb_suggestions._complete", return_value=llm),
        ):
            out = kb_ingest.suggest_from_website(1, "example.com", "Style Cuts")
        questions = [s["question"] for s in out["suggestions"]]
        assert "Do you do balayage?" in questions
        assert "What are your hours?" not in questions  # already in KB

    def test_fetch_error_surfaces(self):
        from core import kb_ingest

        with (
            patch("core.kb_suggestions.is_configured", return_value=True),
            patch(
                "core.kb_ingest.fetch_page_text", return_value=(False, "Couldn't reach that page.")
            ),
        ):
            out = kb_ingest.suggest_from_website(1, "https://example.com")
        assert out["suggestions"] == []
        assert "reach" in out["error"]


class TestEndpoint:
    def test_import_endpoint(self, authenticated_client, sample_business):
        with authenticated_client.session_transaction() as s:
            s["csrf_token"] = "t"
        fake = {"configured": True, "suggestions": [{"question": "Q", "answer": "A"}]}
        with (
            patch("core.kb_ingest.suggest_from_website", return_value=fake),
            patch("core.kb_suggestions.is_configured", return_value=True),
        ):
            resp = authenticated_client.post(
                "/kb/import-website",
                data={
                    "csrf_token": "t",
                    "business_id": sample_business["id"],
                    "url": "https://example.com",
                },
            )
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["configured"] is True
        assert body["suggestions"][0]["question"] == "Q"
