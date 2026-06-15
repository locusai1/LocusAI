# tests/test_semantic_kb.py — semantic (embedding-based) KB search + graceful fallback

import json
from unittest.mock import patch


def _add_kb(test_db, bid, question, answer, active=1):
    from core.db import get_conn

    with get_conn() as con:
        cur = con.execute(
            "INSERT INTO kb_entries (business_id, question, answer, tags, active) VALUES (?, ?, ?, 'faq', ?)",
            (bid, question, answer, active),
        )
        con.commit()
        return cur.lastrowid


def _store_vec(test_db, kb_id, bid, vec):
    from core.db import get_conn

    with get_conn() as con:
        con.execute(
            "INSERT INTO kb_embeddings (kb_entry_id, business_id, vector, model) VALUES (?, ?, ?, 'test')",
            (kb_id, bid, json.dumps(vec)),
        )
        con.commit()


class TestCosine:
    def test_identical_is_one(self):
        from core.semantic_kb import _cosine

        assert _cosine([1, 0, 0], [1, 0, 0]) == 1.0

    def test_orthogonal_is_zero(self):
        from core.semantic_kb import _cosine

        assert _cosine([1, 0], [0, 1]) == 0.0

    def test_mismatched_length_safe(self):
        from core.semantic_kb import _cosine

        assert _cosine([1, 2, 3], [1, 2]) == 0.0


class TestSemanticSearch:
    def test_unavailable_returns_empty(self, test_db, sample_business):
        from core import semantic_kb

        with (
            patch("core.db.DB_PATH", test_db),
            patch.object(semantic_kb, "is_available", return_value=False),
        ):
            assert semantic_kb.semantic_search("hours?", sample_business["id"]) == []

    def test_ranks_by_similarity(self, test_db, sample_business):
        from core import semantic_kb

        bid = sample_business["id"]
        with patch("core.db.DB_PATH", test_db):
            pets = _add_kb(
                test_db, bid, "Do you allow pets?", "Yes, well-behaved dogs are welcome."
            )
            park = _add_kb(test_db, bid, "Is there parking?", "Yes, free parking on site.")
            _store_vec(test_db, pets, bid, [1.0, 0.0, 0.0])
            _store_vec(test_db, park, bid, [0.0, 1.0, 0.0])

            # Query embedding closest to the "pets" vector.
            with (
                patch.object(semantic_kb, "is_available", return_value=True),
                patch.object(semantic_kb, "embed_text", return_value=[0.9, 0.1, 0.0]),
                patch.object(semantic_kb, "_maybe_kick_backfill"),
            ):
                results = semantic_kb.semantic_search("can I bring my dog?", bid, limit=2)

        assert results
        assert results[0]["id"] == pets
        assert results[0]["score"] > results[-1]["score"] if len(results) > 1 else True

    def test_filters_below_min_score(self, test_db, sample_business):
        from core import semantic_kb

        bid = sample_business["id"]
        with patch("core.db.DB_PATH", test_db):
            kid = _add_kb(test_db, bid, "Parking?", "Free parking.")
            _store_vec(test_db, kid, bid, [0.0, 1.0])
            with (
                patch.object(semantic_kb, "is_available", return_value=True),
                patch.object(semantic_kb, "embed_text", return_value=[1.0, 0.0]),  # orthogonal
                patch.object(semantic_kb, "_maybe_kick_backfill"),
            ):
                results = semantic_kb.semantic_search("totally unrelated", bid)
        assert results == []

    def test_no_embeddings_returns_empty(self, test_db, sample_business):
        from core import semantic_kb

        bid = sample_business["id"]
        with patch("core.db.DB_PATH", test_db):
            _add_kb(test_db, bid, "Parking?", "Free parking.")  # entry but no vector
            with (
                patch.object(semantic_kb, "is_available", return_value=True),
                patch.object(semantic_kb, "embed_text", return_value=[1.0, 0.0]),
                patch.object(semantic_kb, "_maybe_kick_backfill") as kick,
            ):
                results = semantic_kb.semantic_search("parking", bid)
            assert results == []
            kick.assert_called_once()  # should schedule a backfill


class TestIndexAndBackfill:
    def test_index_entry_stores_vector(self, test_db, sample_business):
        from core import semantic_kb
        from core.db import get_conn

        bid = sample_business["id"]
        with patch("core.db.DB_PATH", test_db):
            kid = _add_kb(test_db, bid, "Q", "A")
            with (
                patch.object(semantic_kb, "is_available", return_value=True),
                patch.object(semantic_kb, "embed_text", return_value=[0.1, 0.2, 0.3]),
            ):
                ok = semantic_kb.index_entry(kid, bid, "Q", "A")
            assert ok
            with get_conn() as con:
                row = con.execute(
                    "SELECT vector FROM kb_embeddings WHERE kb_entry_id=?", (kid,)
                ).fetchone()
            assert json.loads(row["vector"]) == [0.1, 0.2, 0.3]

    def test_backfill_only_missing(self, test_db, sample_business):
        from core import semantic_kb

        bid = sample_business["id"]
        with patch("core.db.DB_PATH", test_db):
            k1 = _add_kb(test_db, bid, "Q1", "A1")
            _add_kb(test_db, bid, "Q2", "A2")
            _store_vec(test_db, k1, bid, [1.0])  # k1 already indexed
            with (
                patch.object(semantic_kb, "is_available", return_value=True),
                patch.object(semantic_kb, "embed_text", return_value=[0.5]) as emb,
            ):
                done = semantic_kb.backfill_pending(bid)
            assert done == 1  # only the un-indexed entry
            emb.assert_called_once()


class TestSearchKbIntegration:
    def test_search_kb_prefers_semantic(self, test_db, sample_business):
        from core import kb

        bid = sample_business["id"]
        with patch("core.db.DB_PATH", test_db):
            with patch(
                "core.semantic_kb.semantic_search",
                return_value=[{"id": 1, "question": "Q", "answer": "A", "tags": "", "score": 0.9}],
            ):
                out = kb.search_kb("anything", bid)
        assert out and out[0]["answer"] == "A"

    def test_search_kb_falls_back_to_fts(self, test_db, sample_business):
        from core import kb

        bid = sample_business["id"]
        with patch("core.db.DB_PATH", test_db):
            _add_kb(test_db, bid, "What are your opening hours?", "We open 9 to 5.")
            with patch("core.semantic_kb.semantic_search", return_value=[]):
                out = kb.search_kb("opening hours", bid)
        assert any("9 to 5" in r["answer"] for r in out)
