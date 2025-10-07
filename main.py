from core.ai import process_message
from core.knowledge import load_business_from_db
from core.db import create_session, log_message

def run():
    business_name = input("Enter business name (e.g. 'Dental Clinic'): ").strip()
    business_data = load_business_from_db(business_name)

    print(f"\n🤖 AI Receptionist ready for {business_data['name']}!\n")

    # create a session for logging
    session_id = create_session(business_data["id"])

    while True:
        user_input = input("👤 You: ")
        if user_input.lower() in ["quit", "exit"]:
            print("👋 Goodbye!")
            break

        # log user message
        log_message(session_id, "user", user_input)

        # process with AI
        bot_response = process_message(user_input, business_data)

        # log bot message
        log_message(session_id, "bot", bot_response)

        print(f"🤖 Bot: {bot_response}")


if __name__ == "__main__":
    run()

