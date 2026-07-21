# tests/test_pending_store.py — durable cross-worker pending-token store
#
# These guard the fix for the bug where booking-confirm tokens lived in a
# per-process dict and vanished across gunicorn workers.

import time

import pytest

from core import pending_store


class TestPutGet:
    def test_put_then_get_roundtrips(self, test_db):
        pending_store.put("tok1", "booking", {"a": 1, "name": "Jo"}, 300)
        got = pending_store.get("tok1", "booking")
        assert got == {"a": 1, "name": "Jo"}

    def test_get_missing_returns_none(self, test_db):
        assert pending_store.get("nope", "booking") is None

    def test_get_wrong_kind_returns_none(self, test_db):
        pending_store.put("tok1", "booking", {"a": 1}, 300)
        assert pending_store.get("tok1", "change") is None
        # No kind filter still finds it.
        assert pending_store.get("tok1") == {"a": 1}

    def test_get_does_not_consume(self, test_db):
        pending_store.put("tok1", "booking", {"a": 1}, 300)
        assert pending_store.get("tok1", "booking") is not None
        assert pending_store.get("tok1", "booking") is not None

    def test_put_overwrites(self, test_db):
        pending_store.put("tok1", "booking", {"v": 1}, 300)
        pending_store.put("tok1", "booking", {"v": 2}, 300)
        assert pending_store.get("tok1", "booking") == {"v": 2}


class TestExpiry:
    def test_expired_get_returns_none(self, test_db):
        pending_store.put("tok1", "booking", {"a": 1}, -1)  # already expired
        assert pending_store.get("tok1", "booking") is None

    def test_cleanup_removes_only_expired(self, test_db):
        pending_store.put("live", "booking", {"a": 1}, 300)
        pending_store.put("dead", "booking", {"a": 1}, -1)
        removed = pending_store.cleanup()
        assert removed == 1
        assert pending_store.get("live", "booking") is not None
        assert pending_store.get("dead", "booking") is None


class TestPopSingleUse:
    def test_pop_returns_and_deletes(self, test_db):
        pending_store.put("tok1", "booking", {"a": 1}, 300)
        assert pending_store.pop("tok1", "booking") == {"a": 1}
        assert pending_store.get("tok1", "booking") is None

    def test_double_pop_only_succeeds_once(self, test_db):
        """The core guarantee: a replayed confirm can't double-book."""
        pending_store.put("tok1", "booking", {"a": 1}, 300)
        first = pending_store.pop("tok1", "booking")
        second = pending_store.pop("tok1", "booking")
        assert first is not None
        assert second is None

    def test_pop_missing_returns_none(self, test_db):
        assert pending_store.pop("nope", "booking") is None

    def test_pop_expired_returns_none_but_clears_row(self, test_db):
        pending_store.put("tok1", "booking", {"a": 1}, -1)
        assert pending_store.pop("tok1", "booking") is None
        # Row is gone regardless (found-and-deleted).
        assert pending_store.get("tok1") is None

    def test_pop_wrong_kind_returns_none(self, test_db):
        pending_store.put("tok1", "booking", {"a": 1}, 300)
        assert pending_store.pop("tok1", "change") is None


class TestIsolationBetweenKinds:
    def test_same_token_different_kinds_are_independent_on_put(self, test_db):
        # put() overwrites by token (token is the PK), so this documents that
        # callers must use distinct tokens/keys per kind — which booking + voice
        # do (random hex tokens vs call_ids).
        pending_store.put("k", "voice_booking", {"x": 1}, 300)
        pending_store.put("k", "voice_change", {"y": 2}, 300)
        assert pending_store.get("k", "voice_booking") is None
        assert pending_store.get("k", "voice_change") == {"y": 2}
