# tests/test_demo.py — public "try it" instant demo (no auth, no DB writes)

from unittest.mock import MagicMock, patch


class TestBuildContext:
    def test_no_url_builds_greeting(self):
        from core.demo import build_demo_context

        ok, ctx = build_demo_context("StyleCuts", "")
        assert ok is True
        assert "StyleCuts" in ctx["greeting"]
        assert ctx["context"] == ""

    def test_scrape_failure_soft_fails(self):
        from core import demo

        with patch("core.kb_ingest.fetch_page_text", return_value=(False, "blocked")):
            ok, ctx = demo.build_demo_context("Acme", "https://x.example")
        assert ok is True
        assert ctx["context"] == ""

    def test_scrape_success_included(self):
        from core import demo

        with patch("core.kb_ingest.fetch_page_text", return_value=(True, "We open 9-5 daily.")):
            ok, ctx = demo.build_demo_context("Acme", "https://acme.example")
        assert "9-5" in ctx["context"]


class TestDemoReply:
    def test_unavailable_without_key(self):
        from core import demo

        with patch("core.demo.is_available", return_value=False):
            out = demo.demo_reply({"name": "X", "context": ""}, [], "hi")
        assert "Demo unavailable" in out

    def test_reply_uses_client(self):
        from core import demo

        fake = MagicMock()
        fake.chat.completions.create.return_value.choices = [
            MagicMock(message=MagicMock(content="We're open 9 to 5!"))
        ]
        with (
            patch("core.demo.is_available", return_value=True),
            patch("core.ai.client", fake),
        ):
            out = demo.demo_reply({"name": "X", "context": "open 9-5"}, [], "what are your hours?")
        assert out == "We're open 9 to 5!"
        # System prompt should carry the business + scraped context.
        sent = fake.chat.completions.create.call_args.kwargs["messages"]
        assert sent[0]["role"] == "system"
        assert "open 9-5" in sent[0]["content"]


class TestEndpoints:
    def test_try_page_public(self, client):
        resp = client.get("/try")
        assert resp.status_code == 200

    def test_start_requires_name(self, client):
        resp = client.post("/api/try/start", json={"url": "https://x.example"})
        assert resp.status_code == 400

    def test_chat_requires_started_demo(self, client):
        resp = client.post("/api/try/chat", json={"message": "hi"})
        assert resp.status_code == 400

    def test_full_flow(self, client):
        with patch(
            "core.demo.build_demo_context",
            return_value=(True, {"name": "Acme", "context": "", "greeting": "Hi from Acme!"}),
        ):
            r1 = client.post("/api/try/start", json={"name": "Acme"})
        assert r1.status_code == 200
        assert r1.get_json()["greeting"] == "Hi from Acme!"
        with patch("core.demo.demo_reply", return_value="Sure, I can help!"):
            r2 = client.post("/api/try/chat", json={"message": "can you help?"})
        assert r2.status_code == 200
        assert r2.get_json()["reply"] == "Sure, I can help!"
