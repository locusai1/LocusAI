# tests/test_backup.py — SQLite snapshot, rotation, and backup orchestration

import os
import sqlite3
import time
from unittest.mock import patch

import pytest


class TestSnapshot:
    def test_snapshot_is_valid_copy(self, test_db, sample_business, tmp_path):
        from core import backup

        with patch("core.db.DB_PATH", test_db):
            path = backup.snapshot_db(dest_dir=str(tmp_path))
        assert os.path.exists(path)
        # The snapshot opens and contains the schema + seeded business.
        con = sqlite3.connect(path)
        try:
            n = con.execute(
                "SELECT COUNT(*) FROM businesses WHERE id=?", (sample_business["id"],)
            ).fetchone()[0]
        finally:
            con.close()
        assert n == 1


class TestRotation:
    def test_keeps_newest_n(self, tmp_path):
        from core import backup

        d = str(tmp_path)
        for i in range(5):
            p = os.path.join(d, f"receptionist-2026010{i}T000000Z.db")
            open(p, "w").close()
            os.utime(p, (time.time() + i, time.time() + i))  # ascending mtime
        deleted = backup.rotate_local(dest_dir=d, keep=2)
        remaining = sorted(
            os.path.basename(f)
            for f in __import__("glob").glob(os.path.join(d, "receptionist-*.db"))
        )
        assert deleted == 3
        assert len(remaining) == 2
        # the two newest (i=3,4) survive
        assert "receptionist-20260103T000000Z.db" in remaining
        assert "receptionist-20260104T000000Z.db" in remaining


class TestRunBackup:
    def test_local_only_no_s3(self, test_db, sample_business, tmp_path):
        from core import backup

        with (
            patch("core.db.DB_PATH", test_db),
            patch.object(backup.settings, "BACKUP_DIR", str(tmp_path)),
            patch.object(backup.settings, "BACKUP_S3_BUCKET", None),
        ):
            res = backup.run_backup()
        assert res["ok"] is True
        assert res["uploaded"] is False
        assert os.path.exists(res["path"])

    def test_upload_noop_when_unconfigured(self):
        from core import backup

        with patch.object(backup.settings, "BACKUP_S3_BUCKET", None):
            assert backup.upload_to_s3("/tmp/whatever.db") is False
