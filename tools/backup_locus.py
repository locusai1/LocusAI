import os, zipfile, time

ROOT = os.getcwd()
STAMP = time.strftime("%Y%m%d-%H%M%S")
OUT = f"locus-backup-{STAMP}.zip"

INCLUDE_DIRS = ["businesses", os.path.join("static","tenants"), "templates", "core", "adapters"]
INCLUDE_FILES = ["dashboard.py", "main.py", "requirements.lock.txt", "DB_SCHEMA.sql"]
DB_FILE = "receptionist.db"

with zipfile.ZipFile(OUT, "w", zipfile.ZIP_DEFLATED) as z:
    # DB
    if os.path.exists(DB_FILE):
        z.write(DB_FILE, DB_FILE)
    # dirs
    for d in INCLUDE_DIRS:
        if not os.path.exists(d): continue
        for dp, _, files in os.walk(d):
            for f in files:
                p = os.path.join(dp, f)
                z.write(p, p)
    # files
    for f in INCLUDE_FILES:
        if os.path.exists(f): z.write(f, f)

print("Created", OUT)
