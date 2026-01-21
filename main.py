# main.py — CLI runner with booking capture
# Production-grade with proper error handling and logging

import re
import json
import logging
from typing import Optional

from core.db import init_db, create_session, log_message, create_appointment
from core.knowledge import load_business_from_db
from core.ai import process_message

# Configure logging for CLI
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(levelname)s: %(message)s'
)
logger = logging.getLogger(__name__)

BOOKING_RE = re.compile(r"<BOOKING>(.*?)</BOOKING>", re.DOTALL)


def run():
    """Run the interactive CLI chatbot."""
    init_db()

    business_query = input("Enter business name (e.g. 'Dental Clinic'): ").strip()
    if not business_query:
        print("No business name provided. Exiting.")
        return

    try:
        business = load_business_from_db(business_query)
    except ValueError as e:
        print(f"Error: {e}")
        return

    print(f"Loaded business: {business['name']} [{business['slug']}]")

    session_id = create_session(business["id"])
    state = {"session_id": session_id}

    print("Type your message. Type 'exit' to quit.")
    print("-" * 40)

    while True:
        try:
            user_input = input("You: ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\nGoodbye!")
            break

        if user_input.lower() in ("exit", "quit", "q"):
            print("Goodbye!")
            break

        if not user_input:
            continue

        # Log user message
        log_message(session_id, "user", user_input)

        # Process with AI
        try:
            reply = process_message(user_input, business, state)
            reply = (reply or "").strip()
        except Exception as e:
            logger.error(f"AI processing error: {e}")
            reply = "I'm sorry, I encountered an error processing your message."

        # Parse <BOOKING>{...}</BOOKING> and save appointment
        match = BOOKING_RE.search(reply)
        if match:
            raw = match.group(1).strip()
            try:
                payload = json.loads(raw)

                # Create appointment using the updated function (no con parameter needed)
                appt_id = create_appointment(
                    business_id=business["id"],
                    session_id=session_id,
                    customer_name=payload.get("name", ""),
                    phone=payload.get("phone", ""),
                    customer_email=payload.get("email"),
                    service=payload.get("service", ""),
                    start_at=payload.get("datetime", ""),
                    notes=payload.get("notes"),
                    status="pending",
                    source="ai"
                )

                # Strip the booking tag from visible reply
                reply = BOOKING_RE.sub("", reply).strip()

                if appt_id:
                    booking_msg = f"(Booking request captured as #{appt_id}. We'll confirm shortly.)"
                    reply = f"{reply}\n{booking_msg}" if reply else booking_msg
                    logger.info(f"Created appointment {appt_id} from AI booking")
                else:
                    reply += "\n[Note: Booking could not be saved. Please try again.]"

            except json.JSONDecodeError as e:
                logger.warning(f"Failed to parse booking JSON: {e}")
                reply = BOOKING_RE.sub("", reply).strip()
                reply += "\n[Note: Booking details detected but could not be parsed.]"
            except Exception as e:
                logger.error(f"Booking save error: {e}")
                reply = BOOKING_RE.sub("", reply).strip()
                reply += f"\n[Note: Booking details detected but could not be saved: {e}]"

        print(f"AI: {reply}")
        log_message(session_id, "bot", reply)


if __name__ == "__main__":
    run()
