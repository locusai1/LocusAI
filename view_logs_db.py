import sqlite3

DB_PATH = "receptionist.db"

def list_businesses(con):
    rows = con.execute("SELECT id, name FROM businesses ORDER BY name").fetchall()
    return rows

def list_sessions(con, business_id):
    rows = con.execute(
        "SELECT id, started_at FROM sessions WHERE business_id = ? ORDER BY id DESC",
        (business_id,),
    ).fetchall()
    return rows

def show_session_messages(con, session_id):
    rows = con.execute(
        "SELECT timestamp, sender, text FROM messages WHERE session_id = ? ORDER BY id",
        (session_id,),
    ).fetchall()
    for r in rows:
        print(f"[{r['timestamp']}] {r['sender'].upper()}: {r['text']}")

def run():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row

    print("Businesses:")
    for b in list_businesses(con):
        print(f" {b['id']}: {b['name']}")

    bid = int(input("\nEnter business ID: ").strip())
    sessions = list_sessions(con, bid)
    if not sessions:
        print("No sessions yet.")
        return

    print("\nSessions (latest first):")
    for s in sessions[:10]:
        print(f" {s['id']} started {s['started_at']}")

    sid = int(input("\nEnter session ID to view: ").strip())
    print("\n--- Messages ---\n")
    show_session_messages(con, sid)
    print("\n--- End ---\n")

if __name__ == "__main__":
    run()

