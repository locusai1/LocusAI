# main.py — safe CLI runner
from core.db import init_db, create_session, log_message
from core.knowledge import load_business_from_db
from core.ai import process_message

def run():
    # Make sure tables/columns exist
    init_db()

    business_query = input("Enter business name (e.g. 'Dental Clinic'): ").strip()
    business = load_business_from_db(business_query)
    print(f"Loaded business: {business['name']} [{business['slug']}]")

    # Create a new session for this run
    session_id = create_session(business["id"])
    state = {}  # in-memory chat state

    print("Type your message. Type 'exit' to quit.")
    while True:
        user = input("You: ").strip()
        if user.lower() in ("exit", "quit"):
            print("Goodbye!")
            break

        # Log the user's message
        log_message(session_id, "user", user)

        # Get AI reply
        reply = process_message(user, business, state)
        # Safety net: ensure string
        reply = (reply or "").strip()

        print("AI :", reply)

        # Log the bot's reply
        log_message(session_id, "bot", reply)

if __name__ == "__main__":
    run()
