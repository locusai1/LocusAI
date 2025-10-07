from core.db import log_message

def log_interaction(session_id: int, user_input: str, response: str):
    # Store both the user message and the bot reply
    log_message(session_id, "user", user_input)
    log_message(session_id, "bot", response)

