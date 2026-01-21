from core.db import get_conn
from core.knowledge import load_business_from_db
import sys
if len(sys.argv) < 4:
    print("Usage: python add_kb_doc.py <business> <title> <content>")
    raise SystemExit(1)
biz = load_business_from_db(sys.argv[1])
title, content = sys.argv[2], sys.argv[3]
with get_conn() as con:
    cur = con.execute("INSERT INTO kb_docs (business_id, title, content) VALUES (?,?,?)",
                      (biz["id"], title, content))
    print("Inserted KB doc id:", cur.lastrowid)
