# tests/test_account.py — GDPR export (portability) + delete (erasure)

import pytest
from werkzeug.security import generate_password_hash

from core import account
from core.db import get_conn


def _mk_user(con, email, pw="secret123"):
    cur = con.execute(
        "INSERT INTO users (email, name, password_hash, role) VALUES (?, ?, ?, 'owner')",
        (email, email.split("@")[0],
         generate_password_hash(pw, method="pbkdf2:sha256:260000")),
    )
    return cur.lastrowid


def _mk_business(con, name, slug):
    cur = con.execute(
        "INSERT INTO businesses (name, slug, tenant_key) VALUES (?, ?, ?)",
        (name, slug, f"key-{slug}"),
    )
    return cur.lastrowid


def _link(con, uid, bid):
    con.execute(
        "INSERT INTO business_users (user_id, business_id) VALUES (?, ?)", (uid, bid)
    )


def _seed(con, bid):
    con.execute(
        "INSERT INTO customers (business_id, name, email, phone) VALUES (?, 'Jo', 'jo@x.com', '+15551')",
        (bid,),
    )
    con.execute(
        "INSERT INTO appointments (business_id, customer_name, service, start_at, status) "
        "VALUES (?, 'Jo', 'Cut', '2026-08-01 10:00', 'confirmed')",
        (bid,),
    )
    con.execute(
        "INSERT INTO kb_entries (business_id, question, answer) VALUES (?, 'Q', 'A')", (bid,)
    )
    con.execute(
        "INSERT INTO sessions (business_id, channel) VALUES (?, 'web')", (bid,)
    )


class TestExport:
    def test_export_includes_account_and_business_data(self, test_db):
        with get_conn() as con:
            uid = _mk_user(con, "owner@x.com")
            bid = _mk_business(con, "Salon", "salon")
            _link(con, uid, bid)
            _seed(con, bid)
            con.commit()

        data = account.export_account_data(uid)
        assert data["account"]["email"] == "owner@x.com"
        assert "password_hash" not in data["account"]
        assert len(data["businesses"]) == 1
        biz = data["businesses"][0]
        assert biz["name"] == "Salon"
        assert "tenant_key" not in biz  # secret excluded
        assert len(biz["customers"]) == 1
        assert len(biz["appointments"]) == 1
        assert len(biz["knowledge_base"]) == 1

    def test_export_excludes_other_tenants(self, test_db):
        with get_conn() as con:
            uid = _mk_user(con, "a@x.com")
            mine = _mk_business(con, "Mine", "mine")
            other = _mk_business(con, "Other", "other")
            _link(con, uid, mine)
            _seed(con, other)  # not linked to uid
            con.commit()

        data = account.export_account_data(uid)
        names = [b["name"] for b in data["businesses"]]
        assert names == ["Mine"]


class TestDelete:
    def test_wrong_password_refused(self, test_db):
        with get_conn() as con:
            uid = _mk_user(con, "owner@x.com", pw="rightpass")
            con.commit()
        ok, msg = account.delete_account(uid, "wrongpass")
        assert ok is False and "incorrect" in msg.lower()
        with get_conn() as con:
            assert con.execute("SELECT 1 FROM users WHERE id=?", (uid,)).fetchone()

    def test_sole_owner_deletes_business_and_cascades(self, test_db):
        with get_conn() as con:
            uid = _mk_user(con, "owner@x.com", pw="rightpass")
            bid = _mk_business(con, "Salon", "salon")
            _link(con, uid, bid)
            _seed(con, bid)
            con.commit()

        ok, msg = account.delete_account(uid, "rightpass")
        assert ok is True

        with get_conn() as con:
            assert con.execute("SELECT 1 FROM users WHERE id=?", (uid,)).fetchone() is None
            assert con.execute("SELECT 1 FROM businesses WHERE id=?", (bid,)).fetchone() is None
            # Cascades cleared the scoped data.
            for tbl in ("customers", "appointments", "kb_entries", "sessions"):
                cnt = con.execute(
                    f"SELECT COUNT(*) c FROM {tbl} WHERE business_id=?", (bid,)
                ).fetchone()["c"]
                assert cnt == 0, f"{tbl} not cascaded"

    def test_shared_business_is_preserved(self, test_db):
        with get_conn() as con:
            me = _mk_user(con, "me@x.com", pw="rightpass")
            other = _mk_user(con, "other@x.com")
            bid = _mk_business(con, "Shared", "shared")
            _link(con, me, bid)
            _link(con, other, bid)
            _seed(con, bid)
            con.commit()

        ok, _ = account.delete_account(me, "rightpass")
        assert ok is True

        with get_conn() as con:
            # Business kept (other member remains); my membership removed.
            assert con.execute("SELECT 1 FROM businesses WHERE id=?", (bid,)).fetchone()
            assert con.execute(
                "SELECT 1 FROM business_users WHERE user_id=? AND business_id=?", (me, bid)
            ).fetchone() is None
            assert con.execute(
                "SELECT 1 FROM business_users WHERE user_id=? AND business_id=?", (other, bid)
            ).fetchone()
            assert con.execute("SELECT 1 FROM users WHERE id=?", (me,)).fetchone() is None
