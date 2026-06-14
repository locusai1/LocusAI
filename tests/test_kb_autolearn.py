# tests/test_kb_autolearn.py — self-improving knowledge base

from unittest.mock import patch


def _ask(test_db, bid, text, n_sessions):
    """Insert `text` as a user message across n_sessions distinct sessions."""
    from core.db import get_conn

    with patch("core.db.DB_PATH", test_db), get_conn() as con:
        for _ in range(n_sessions):
            cur = con.execute(
                "INSERT INTO sessions (business_id, channel) VALUES (?, 'web')", (bid,)
            )
            sid = cur.lastrowid
            con.execute(
                "INSERT INTO messages (session_id, sender, text) VALUES (?, 'user', ?)", (sid, text)
            )
        con.commit()


class TestFrequentUnanswered:
    def test_requires_min_frequency(self, test_db, sample_business):
        from core import kb_autolearn

        bid = sample_business["id"]
        _ask(test_db, bid, "Do you offer gift cards?", 3)
        _ask(test_db, bid, "Do you do home visits?", 1)  # too rare
        with patch("core.db.DB_PATH", test_db):
            out = kb_autolearn.frequent_unanswered_questions(bid, min_frequency=3)
        qs = [c["question"] for c in out]
        assert "Do you offer gift cards?" in qs
        assert "Do you do home visits?" not in qs

    def test_excludes_already_in_kb(self, test_db, sample_business):
        from core import kb_autolearn
        from core.db import get_conn

        bid = sample_business["id"]
        _ask(test_db, bid, "Do you offer gift cards?", 4)
        with patch("core.db.DB_PATH", test_db):
            with get_conn() as con:
                con.execute(
                    "INSERT INTO kb_entries (business_id, question, answer, active) "
                    "VALUES (?, 'Do you offer gift cards?', 'Yes.', 1)",
                    (bid,),
                )
                con.commit()
            out = kb_autolearn.frequent_unanswered_questions(bid, min_frequency=3)
        assert out == []


class TestAutoLearn:
    def test_adds_grounded_answer(self, test_db, sample_business):
        from core import kb_autolearn
        from core.db import get_conn

        bid = sample_business["id"]
        _ask(test_db, bid, "How much is a haircut?", 3)
        with (
            patch("core.db.DB_PATH", test_db),
            patch("core.kb_suggestions.is_configured", return_value=True),
            patch("core.kb_autolearn._ground_answer", return_value="A haircut is £25."),
        ):
            added = kb_autolearn.auto_learn_kb(bid, "Style Cuts")
            assert len(added) == 1
            with get_conn() as con:
                row = con.execute(
                    "SELECT question, answer, tags FROM kb_entries WHERE business_id=? "
                    "AND question='How much is a haircut?'",
                    (bid,),
                ).fetchone()
        assert row is not None
        assert row["answer"] == "A haircut is £25."
        assert row["tags"] == "auto-learned"

    def test_skips_when_not_groundable(self, test_db, sample_business):
        from core import kb_autolearn

        bid = sample_business["id"]
        _ask(test_db, bid, "Do you accept crypto payments?", 3)
        with (
            patch("core.db.DB_PATH", test_db),
            patch("core.kb_suggestions.is_configured", return_value=True),
            patch("core.kb_autolearn._ground_answer", return_value=None),
        ):
            added = kb_autolearn.auto_learn_kb(bid, "Style Cuts")
        assert added == []

    def test_not_configured_returns_empty(self, test_db, sample_business):
        from core import kb_autolearn

        bid = sample_business["id"]
        _ask(test_db, bid, "How much is a haircut?", 3)
        with (
            patch("core.db.DB_PATH", test_db),
            patch("core.kb_suggestions.is_configured", return_value=False),
        ):
            assert kb_autolearn.auto_learn_kb(bid, "Style Cuts") == []

    def test_run_for_enabled_only(self, test_db, sample_business):
        from core import kb_autolearn
        from core.db import get_conn

        bid = sample_business["id"]
        _ask(test_db, bid, "How much is a haircut?", 3)
        with patch("core.db.DB_PATH", test_db):
            # Not enabled yet → skipped.
            with patch("core.kb_autolearn.auto_learn_kb") as m:
                kb_autolearn.run_autolearn_for_enabled()
                m.assert_not_called()
            # Enable it → included.
            with get_conn() as con:
                con.execute("UPDATE businesses SET kb_autolearn_enabled=1 WHERE id=?", (bid,))
                con.commit()
            with patch("core.kb_autolearn.auto_learn_kb", return_value=[{"question": "q"}]) as m:
                total = kb_autolearn.run_autolearn_for_enabled()
                m.assert_called_once()
        assert total == 1


class TestEndpoint:
    def test_autolearn_endpoint(self, authenticated_client, sample_business):
        with authenticated_client.session_transaction() as s:
            s["csrf_token"] = "t"
        with (
            patch(
                "core.kb_autolearn.auto_learn_kb", return_value=[{"question": "Q", "answer": "A"}]
            ),
            patch("core.kb_suggestions.is_configured", return_value=True),
        ):
            resp = authenticated_client.post(
                "/kb/autolearn", data={"csrf_token": "t", "business_id": sample_business["id"]}
            )
        assert resp.status_code == 200
        assert resp.get_json()["added"][0]["question"] == "Q"
