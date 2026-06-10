# tests/test_kb_suggestions.py — AI knowledge-gap suggestions

from unittest.mock import patch
import pytest


def _seed_questions(test_db, business_id, texts):
    from core.db import get_conn
    with get_conn() as con:
        cur = con.cursor()
        cur.execute("INSERT INTO sessions (business_id, channel) VALUES (?, 'web')", (business_id,))
        sid = cur.lastrowid
        for t in texts:
            cur.execute("INSERT INTO messages (session_id, sender, text) VALUES (?, 'user', ?)", (sid, t))
        con.commit()


class TestGather:
    def test_filters_to_questions(self, test_db, sample_business):
        from core import kb_suggestions as kbs
        bid = sample_business["id"]
        with patch("core.db.DB_PATH", test_db):
            _seed_questions(test_db, bid, [
                "Do you do balayage?",
                "How much is a cut and colour?",
                "thanks!",            # not a question -> dropped
                "ok",                 # too short -> dropped
                "Are you open Sundays?",
            ])
            qs = kbs.gather_recent_questions(bid)
        assert "Do you do balayage?" in qs
        assert "Are you open Sundays?" in qs
        assert "thanks!" not in qs
        assert "ok" not in qs


class TestParse:
    def test_plain_json(self):
        from core.kb_suggestions import _parse
        out = _parse('{"suggestions":[{"question":"Q1","answer":"A1"}]}')
        assert out == [{"question": "Q1", "answer": "A1"}]

    def test_code_fenced_json(self):
        from core.kb_suggestions import _parse
        out = _parse('```json\n{"suggestions":[{"question":"Q","answer":"A"}]}\n```')
        assert out == [{"question": "Q", "answer": "A"}]

    def test_junk_returns_empty(self):
        from core.kb_suggestions import _parse
        assert _parse("sorry, I can't help") == []
        assert _parse("") == []

    def test_drops_incomplete_items(self):
        from core.kb_suggestions import _parse
        out = _parse('{"suggestions":[{"question":"Q","answer":""},{"question":"Q2","answer":"A2"}]}')
        assert out == [{"question": "Q2", "answer": "A2"}]


class TestSuggest:
    def test_not_configured_returns_empty(self, test_db, sample_business):
        from core import kb_suggestions as kbs
        with patch.object(kbs, "OPENAI_API_KEY", None), patch("core.db.DB_PATH", test_db):
            assert kbs.suggest_kb_entries(sample_business["id"]) == []

    def test_too_few_questions_returns_empty(self, test_db, sample_business):
        from core import kb_suggestions as kbs
        with patch.object(kbs, "OPENAI_API_KEY", "sk-test"), patch("core.db.DB_PATH", test_db):
            _seed_questions(test_db, sample_business["id"], ["Do you open Sundays?"])
            assert kbs.suggest_kb_entries(sample_business["id"]) == []

    def test_suggests_and_dedupes_existing(self, test_db, sample_business):
        from core import kb_suggestions as kbs
        from core.db import get_conn
        bid = sample_business["id"]
        with patch.object(kbs, "OPENAI_API_KEY", "sk-test"), patch("core.db.DB_PATH", test_db):
            _seed_questions(test_db, bid, [
                "Do you do balayage?", "How much is a colour?", "Are you open Sundays?"])
            with get_conn() as con:
                con.execute("INSERT INTO kb_entries (business_id, question, answer, active) "
                            "VALUES (?, 'Are you open Sundays?', 'No, closed Sundays.', 1)", (bid,))
                con.commit()
            llm_json = ('{"suggestions":[{"question":"Do you do balayage?","answer":"Yes we do."},'
                        '{"question":"Are you open Sundays?","answer":"dup should be dropped"}]}')
            with patch.object(kbs, "_complete", return_value=llm_json):
                out = kbs.suggest_kb_entries(bid, "Style Cuts")
        questions = [s["question"] for s in out]
        assert "Do you do balayage?" in questions
        assert "Are you open Sundays?" not in questions  # already in KB -> deduped


class TestEndpoints:
    def test_suggestions_endpoint_not_configured(self, authenticated_client, sample_business):
        from core import kb_suggestions as kbs
        with patch.object(kbs, "OPENAI_API_KEY", None):
            resp = authenticated_client.get(f"/kb/suggestions?business_id={sample_business['id']}")
        assert resp.status_code == 200
        assert resp.get_json()["configured"] is False

    def test_add_suggestion_creates_entry(self, authenticated_client, sample_business, test_db):
        with authenticated_client.session_transaction() as s:
            s["csrf_token"] = "t"
        resp = authenticated_client.post("/kb/suggestions/add", data={
            "csrf_token": "t", "business_id": sample_business["id"],
            "question": "Do you offer gift cards?", "answer": "Yes, ask in store."})
        assert resp.status_code in (302, 303)
        with patch("core.db.DB_PATH", test_db):
            from core.db import get_conn
            with get_conn() as con:
                row = con.execute("SELECT * FROM kb_entries WHERE business_id=? AND question=?",
                                  (sample_business["id"], "Do you offer gift cards?")).fetchone()
        assert row is not None
        assert row["tags"] == "ai-suggested"
