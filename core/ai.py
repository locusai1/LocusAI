from core.booking import book_appointment

def classify_intent(user_input, business_data):
    """
    Very simple keyword-based intent classifier.
    Later this can be upgraded to AI-based.
    """
    text = user_input.lower()

    # FAQ intent
    for question in business_data.get("faqs", {}):
        if question in text:
            return "faq"

    # Booking intent
    if "book" in text or "appointment" in text or "schedule" in text:
        return "booking"

    # Escalation (fallback)
    return "escalation"


def process_message(user_input, business_data, state={}):
    """
    Main receptionist flow manager.
    Decides what to do based on intent.
    """

    intent = classify_intent(user_input, business_data)

    # Handle FAQ
    if intent == "faq":
        for question, answer in business_data["faqs"].items():
            if question in user_input.lower():
                return answer

    # Handle Booking
    if intent == "booking":
        if "date" not in state:
            state["stage"] = "booking_date"
            return "Sure, I can help with booking. What date works for you?"

        elif "time" not in state:
            state["stage"] = "booking_time"
            return "Great! What time works best?"

        elif "service" not in state:
            state["stage"] = "booking_service"
            return "Got it. What service would you like to book?"

        else:
            # Call booking function (dummy for now)
            return book_appointment(state["date"], state["time"], state["service"])

    # Escalation
    if intent == "escalation":
        return "I’ll forward this to a staff member. Can you share your name and number?"

