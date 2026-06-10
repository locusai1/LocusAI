# tests/test_bootstrap.py — env-driven admin bootstrap

from unittest.mock import patch
import pytest


def _admin_count(test_db, email):
    from core.db import get_conn
    with get_conn() as con:
        return con.execute("SELECT COUNT(*) FROM users WHERE email=? COLLATE NOCASE AND role='admin'",
                           (email,)).fetchone()[0]


class TestEnsureAdmin:
    def test_creates_when_missing(self, test_db):
        from core import bootstrap
        from werkzeug.security import check_password_hash
        from core.db import get_conn
        with patch("core.db.DB_PATH", test_db), \
             patch.dict("os.environ", {"ADMIN_EMAIL": "owner@x.com", "ADMIN_PASSWORD": "StrongPass1"}):
            assert bootstrap.ensure_admin() is True
            assert _admin_count(test_db, "owner@x.com") == 1
            with get_conn() as con:
                h = con.execute("SELECT password_hash FROM users WHERE email='owner@x.com'").fetchone()[0]
            assert check_password_hash(h, "StrongPass1")

    def test_noop_when_already_exists(self, test_db):
        from core import bootstrap
        with patch("core.db.DB_PATH", test_db), \
             patch.dict("os.environ", {"ADMIN_EMAIL": "owner@x.com", "ADMIN_PASSWORD": "StrongPass1"}):
            assert bootstrap.ensure_admin() is True
            # second call must not create a duplicate or error
            assert bootstrap.ensure_admin() is False
            assert _admin_count(test_db, "owner@x.com") == 1

    def test_noop_when_env_unset(self, test_db):
        from core import bootstrap
        import os
        with patch("core.db.DB_PATH", test_db), \
             patch.dict(os.environ, {}, clear=False):
            os.environ.pop("ADMIN_EMAIL", None)
            os.environ.pop("ADMIN_PASSWORD", None)
            assert bootstrap.ensure_admin() is False

    def test_rejects_short_password(self, test_db):
        from core import bootstrap
        with patch("core.db.DB_PATH", test_db), \
             patch.dict("os.environ", {"ADMIN_EMAIL": "a@b.com", "ADMIN_PASSWORD": "short"}):
            assert bootstrap.ensure_admin() is False
            assert _admin_count(test_db, "a@b.com") == 0
