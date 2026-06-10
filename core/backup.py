# core/backup.py — consistent SQLite snapshots with rotation + optional S3 upload
#
# Run from cron / a systemd timer:   python -m core.backup
# Local snapshots always work; set BACKUP_S3_BUCKET (+ AWS creds, boto3) to also
# push off-box. On Railway, point BACKUP_DIR at a mounted volume or use S3 so the
# snapshot survives redeploys.

import os
import glob
import sqlite3
import logging
from datetime import datetime, timezone
from typing import Optional, Dict, Any

from core import settings
import core.db as _db

logger = logging.getLogger(__name__)


def snapshot_db(dest_dir: Optional[str] = None) -> str:
    """Create a consistent online snapshot of the live DB using sqlite's backup
    API (safe while the app is running). Returns the snapshot file path."""
    dest_dir = dest_dir or settings.BACKUP_DIR
    os.makedirs(dest_dir, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_path = os.path.join(dest_dir, f"receptionist-{ts}.db")

    src = sqlite3.connect(_db.DB_PATH)
    try:
        dest = sqlite3.connect(out_path)
        try:
            with dest:
                src.backup(dest)
        finally:
            dest.close()
    finally:
        src.close()
    logger.info("DB snapshot written to %s (%d bytes)", out_path, os.path.getsize(out_path))
    return out_path


def rotate_local(dest_dir: Optional[str] = None, keep: Optional[int] = None) -> int:
    """Keep only the newest `keep` snapshots in dest_dir. Returns count deleted."""
    dest_dir = dest_dir or settings.BACKUP_DIR
    keep = settings.BACKUP_KEEP if keep is None else keep
    files = sorted(glob.glob(os.path.join(dest_dir, "receptionist-*.db")),
                   key=os.path.getmtime, reverse=True)
    deleted = 0
    for old in files[keep:]:
        try:
            os.remove(old)
            deleted += 1
        except OSError:
            pass
    return deleted


def upload_to_s3(path: str) -> bool:
    """Upload a snapshot to S3-compatible storage if configured. Returns True if
    uploaded. No-op (False) when not configured or boto3 is unavailable."""
    if not settings.BACKUP_S3_BUCKET:
        return False
    try:
        import boto3  # optional dependency
    except ImportError:
        logger.warning("BACKUP_S3_BUCKET set but boto3 is not installed; skipping upload")
        return False
    try:
        kwargs = {}
        if settings.BACKUP_S3_ENDPOINT:
            kwargs["endpoint_url"] = settings.BACKUP_S3_ENDPOINT
        s3 = boto3.client("s3", **kwargs)
        key = f"{settings.BACKUP_S3_PREFIX.rstrip('/')}/{os.path.basename(path)}"
        s3.upload_file(path, settings.BACKUP_S3_BUCKET, key)
        logger.info("Uploaded backup to s3://%s/%s", settings.BACKUP_S3_BUCKET, key)
        return True
    except Exception:
        logger.exception("S3 backup upload failed")
        return False


def run_backup() -> Dict[str, Any]:
    """Snapshot + rotate + (optional) upload. Returns a result summary."""
    result: Dict[str, Any] = {"ok": False, "path": None, "uploaded": False, "rotated": 0}
    try:
        path = snapshot_db()
        result["path"] = path
        result["uploaded"] = upload_to_s3(path)
        result["rotated"] = rotate_local()
        result["ok"] = True
    except Exception as e:
        logger.exception("Backup failed")
        result["error"] = str(e)
    return result


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    res = run_backup()
    print(res)
    raise SystemExit(0 if res["ok"] else 1)
