# core/ai.py — Enhanced AI with sentiment awareness and human handoff
# Production-grade AI receptionist with escalation capabilities

import logging
from typing import Optional, Dict, Any, List, Tuple

from openai import OpenAI
from core.settings import OPENAI_API_KEY
from core.db import get_session_messages, get_business_by_id

try:
    from core.kb import kb_search
except Exception:
    kb_search = None

try:
    from core.sentiment import analyze_sentiment, SentimentType, IntentType, SentimentResult
    SENTIMENT_AVAILABLE = True
except Exception:
    SENTIMENT_AVAILABLE = False

try:
    from core.escalation import handle_escalation, get_escalation_response
    ESCALATION_AVAILABLE = True
except Exception:
    ESCALATION_AVAILABLE = False

logger = logging.getLogger(__name__)

# Initialize OpenAI client
client = OpenAI(api_key=OPENAI_API_KEY or None)

def _row_to_dict(row):
    """Accepts dict or sqlite3.Row and returns a plain dict."""
    try:
        return {k: row[k] for k in row.keys()}
    except Exception:
        return row or {}

def _business_prompt(bd: dict, sentiment_context: Optional[Dict] = None) -> str:
    """Build the system prompt with optional sentiment-aware adjustments."""
    name = bd.get("name", "this business")
    hours = bd.get("hours", "not provided")
    addr  = bd.get("address", "not provided")
    serv  = bd.get("services", "not provided")
    tone  = bd.get("tone", "friendly and professional")

    # Base prompt
    base_prompt = f"""
You are the AI receptionist for {name}.
Speak naturally, concise, and in a {tone} manner.

Business details (use when relevant, do not invent):
- Hours: {hours}
- Address: {addr}
- Services: {serv}

Guidelines:
- Keep replies to 1–3 sentences unless asked for detail.
- If unsure or info is missing, offer to take a message and escalate to a human.
- If the caller wants to book, ask minimally for: name, phone, service, preferred date/time.
- IMPORTANT: When you have ALL booking details, output EXACTLY ONE machine-readable line:
  <BOOKING>{{"name":"<NAME>","phone":"<PHONE>","service":"<SERVICE>","datetime":"YYYY-MM-DD HH:MM","notes":""}}</BOOKING>
  Use 24-hour time, local timezone. Do NOT include extra commentary inside the tag. Continue your normal reply outside the tag.
"""

    # Add escalation awareness
    escalation_guidance = """
Escalation Awareness:
- If the customer explicitly asks to speak with a human, manager, or staff member, acknowledge their request warmly and let them know someone will reach out.
- If you detect frustration or urgency, be extra empathetic and proactive in offering solutions.
- For medical emergencies or severe pain, prioritize getting them help immediately.
- Never argue or become defensive. Always remain calm and helpful.
"""

    # Sentiment-adaptive additions
    sentiment_guidance = ""
    if sentiment_context:
        sentiment = sentiment_context.get("sentiment")
        if sentiment in ("frustrated", "angry"):
            sentiment_guidance = """
IMPORTANT: The customer appears frustrated. Please:
- Acknowledge their feelings with genuine empathy
- Apologize for any inconvenience
- Be extra patient and helpful
- Focus on solving their problem quickly
- Avoid defensive language
"""
        elif sentiment == "urgent":
            sentiment_guidance = """
IMPORTANT: This appears to be an urgent matter. Please:
- Respond with appropriate urgency
- Prioritize getting them the help they need
- If it's a medical emergency, recommend appropriate emergency services
- Try to connect them with staff as quickly as possible
"""
        elif sentiment == "confused":
            sentiment_guidance = """
IMPORTANT: The customer seems confused. Please:
- Use simpler, clearer language
- Break down information into smaller pieces
- Offer to explain things differently if needed
- Be patient and reassuring
"""

    return (base_prompt + escalation_guidance + sentiment_guidance).strip()

def _history_from_db(session_id: int, limit: int = 12):
    """Build chat history from DB messages for the session (chronological)."""
    if not session_id:
        return []
    rows = get_session_messages(session_id, limit=limit)
    history = []
    for m in reversed(rows):  # DB returns DESC; we need ASC
        role = "assistant" if m["sender"] == "bot" else "user"
        history.append({"role": role, "content": m["text"]})
    return history

def _kb_snippets(business_id: int, query: str, limit: int = 3):
    """Fetch short knowledge snippets via KB search (if available)."""
    if not (kb_search and business_id and query):
        return []
    try:
        rows = kb_search(business_id, query, limit=limit) or []
        snips = []
        for r in rows:
            title = r.get("title") if isinstance(r, dict) else r["title"]
            content = r.get("content") if isinstance(r, dict) else r["content"]
            if title:
                snips.append(f"- {title}: {content}")
            else:
                snips.append(f"- {content}")
        return snips
    except Exception:
        return []

def process_message(
    user_input: str,
    business_data: Dict,
    state: Optional[Dict] = None,
    customer_id: Optional[int] = None,
    customer_info: Optional[Dict] = None
) -> str:
    """
    Generate a human-like receptionist reply with sentiment awareness.

    Uses DB-backed history if state['session_id'] is present.
    Falls back to in-memory state['history'].
    Analyzes sentiment and triggers escalation when needed.

    Returns:
        Reply string (never empty)
    """
    if state is None:
        state = {}

    bd = _row_to_dict(business_data)
    business_id = bd.get("id")
    session_id = state.get("session_id")
    user_text = (user_input or "").strip() or "Hello"

    # Get conversation history for sentiment analysis
    conversation_history = []
    if session_id:
        conversation_history = _history_from_db(session_id, limit=12)
    else:
        conversation_history = state.get("history", [])[-8:]

    # =========================================================================
    # Sentiment Analysis
    # =========================================================================
    sentiment_result = None
    sentiment_context = None
    failed_attempts = state.get("failed_attempts", 0)

    if SENTIMENT_AVAILABLE:
        try:
            sentiment_result = analyze_sentiment(
                text=user_text,
                conversation_history=conversation_history,
                failed_attempts=failed_attempts
            )

            # Build context for prompt adjustment
            sentiment_context = {
                "sentiment": sentiment_result.sentiment.value,
                "intent": sentiment_result.intent.value,
                "confidence": sentiment_result.confidence,
                "frustration_score": sentiment_result.details.get("frustration_score", 0)
            }

            logger.debug(
                f"Sentiment: {sentiment_result.sentiment.value} "
                f"(confidence: {sentiment_result.confidence:.2f}), "
                f"Intent: {sentiment_result.intent.value}"
            )
        except Exception as e:
            logger.warning(f"Sentiment analysis failed: {e}")

    # =========================================================================
    # Escalation Check
    # =========================================================================
    if sentiment_result and sentiment_result.triggers_escalation and ESCALATION_AVAILABLE:
        try:
            # Get full business data if we only have partial
            business = bd
            if business_id and not business.get("email"):
                full_business = get_business_by_id(business_id)
                if full_business:
                    business = _row_to_dict(full_business)

            escalation_id = handle_escalation(
                sentiment_result=sentiment_result,
                business=business,
                session_id=session_id,
                customer_id=customer_id,
                customer_info=customer_info,
                conversation_history=conversation_history + [{"role": "user", "content": user_text}]
            )

            if escalation_id:
                logger.info(
                    f"Escalation {escalation_id} created for session {session_id}: "
                    f"{sentiment_result.escalation_reason}"
                )

                # Store escalation info in state
                state["escalated"] = True
                state["escalation_id"] = escalation_id
                state["escalation_reason"] = sentiment_result.escalation_reason

                # Return the escalation response
                escalation_reply = get_escalation_response()

                # Still maintain history
                hist = state.setdefault("history", [])
                hist.append({"role": "user", "content": user_text})
                hist.append({"role": "assistant", "content": escalation_reply})
                if len(hist) > 20:
                    del hist[:-20]

                return escalation_reply

        except Exception as e:
            logger.error(f"Escalation handling failed: {e}")
            # Continue with normal processing if escalation fails

    # =========================================================================
    # Build AI Messages
    # =========================================================================
    system_prompt = _business_prompt(bd, sentiment_context)
    messages = [{"role": "system", "content": system_prompt}]

    # Add conversation history
    messages.extend(conversation_history)

    # Optional RAG: inject relevant knowledge
    kb_snips = _kb_snippets(business_id, user_text, limit=3)
    if kb_snips:
        messages.append({
            "role": "system",
            "content": "Relevant business knowledge:\n" + "\n".join(kb_snips)
        })

    messages.append({"role": "user", "content": user_text})

    # =========================================================================
    # Generate AI Response
    # =========================================================================
    try:
        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=messages,
            max_tokens=300,
            temperature=0.6,
        )
        reply = resp.choices[0].message.content or ""
    except Exception as e:
        logger.error(f"OpenAI API error: {e}")
        reply = (
            "Sorry, I'm having a little trouble right now. "
            "Could I take your name and number and we'll call you back shortly?"
        )

    # =========================================================================
    # Update State
    # =========================================================================
    hist = state.setdefault("history", [])
    hist.append({"role": "user", "content": user_text})
    hist.append({"role": "assistant", "content": reply})
    if len(hist) > 20:
        del hist[:-20]

    # Track sentiment trends in state for analytics
    if sentiment_result:
        sentiment_history = state.setdefault("sentiment_history", [])
        sentiment_history.append({
            "sentiment": sentiment_result.sentiment.value,
            "confidence": sentiment_result.confidence,
            "intent": sentiment_result.intent.value
        })
        if len(sentiment_history) > 20:
            del sentiment_history[:-20]

    return (reply or "").strip()


def process_message_with_metadata(
    user_input: str,
    business_data: Dict,
    state: Optional[Dict] = None,
    customer_id: Optional[int] = None,
    customer_info: Optional[Dict] = None
) -> Dict[str, Any]:
    """
    Enhanced version that returns metadata along with the reply.

    Returns:
        Dict with keys:
        - reply: The AI response string
        - sentiment: Detected sentiment (if available)
        - intent: Detected intent (if available)
        - escalated: Whether escalation was triggered
        - escalation_id: ID of escalation if created
    """
    if state is None:
        state = {}

    # Process the message
    reply = process_message(
        user_input=user_input,
        business_data=business_data,
        state=state,
        customer_id=customer_id,
        customer_info=customer_info
    )

    # Extract metadata from state
    result = {
        "reply": reply,
        "sentiment": None,
        "intent": None,
        "escalated": state.get("escalated", False),
        "escalation_id": state.get("escalation_id"),
    }

    # Get latest sentiment if available
    sentiment_history = state.get("sentiment_history", [])
    if sentiment_history:
        latest = sentiment_history[-1]
        result["sentiment"] = latest.get("sentiment")
        result["intent"] = latest.get("intent")

    return result


def increment_failed_attempts(state: Dict) -> int:
    """Increment and return the failed attempts counter."""
    state["failed_attempts"] = state.get("failed_attempts", 0) + 1
    return state["failed_attempts"]


def reset_failed_attempts(state: Dict) -> None:
    """Reset the failed attempts counter (e.g., after successful booking)."""
    state["failed_attempts"] = 0
