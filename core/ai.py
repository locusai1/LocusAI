from openai import OpenAI

client = OpenAI()

def _to_plain_dict(obj):
    """
    Accepts dict or sqlite3.Row and returns a plain dict.
    """
    try:
        # sqlite3.Row supports .keys()
        return {k: obj[k] for k in obj.keys()}
    except Exception:
        # assume it's already a dict (or None)
        return obj or {}

def process_message(user_input, business_data, state=None):
    """
    Generate a receptionist-like AI response with natural, human tone.
    - user_input: customer's message (str)
    - business_data: dict or sqlite3.Row with keys:
        name, hours, address, services, tone (any may be missing)
    - state: mutable dict to persist chat history across turns
      (we mutate it in-place so callers don't need to handle returns)
    Returns: reply string
    """
    if state is None:
        state = {}

    # Keep a short rolling history (list of {"role","content"})
    history = state.setdefault("history", [])
    # Optional: a per-session id could be stored in state later
    # session_id = state.get("session_id", "default")

    bd = _to_plain_dict(business_data)
    name = bd.get("name", "this business")
    hours = bd.get("hours", "not provided")
    address = bd.get("address", "not provided")
    services = bd.get("services", "not provided")
    tone = bd.get("tone", "friendly and professional")

    system_prompt = f"""
You are the AI receptionist for {name}.
Speak naturally and helpfully in a {tone} manner.
Use these details when relevant:
- Hours: {hours}
- Address: {address}
- Services: {services}

Rules:
- Be concise but warm (1–3 sentences unless the user asks for detail).
- If you don't know something, say you'll pass a message to the team and offer to take contact details.
- If user wants to book, ask the minimal questions needed (name, phone, preferred date/time, service).
- Never invent facts not present in the business info.
"""

    messages = [{"role": "system", "content": system_prompt}]
    # include short rolling history
    messages.extend(history[-8:])
    messages.append({"role": "user", "content": user_input})

    try:
        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=messages,
            max_tokens=300,
            temperature=0.6,
        )
        reply = resp.choices[0].message.content
    except Exception as e:
        reply = f"Sorry, I'm having trouble right now ({e})."

    # update rolling history in-place
    history.append({"role": "user", "content": user_input})
    history.append({"role": "assistant", "content": reply})
    # trim to last 10 exchanges (20 messages)
    if len(history) > 20:
        del history[:-20]
    return (reply or "").strip()

