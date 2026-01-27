# core/ai.py — Enhanced AI with sentiment awareness, human handoff, and resilience
# Production-grade AI receptionist with escalation capabilities and circuit breaker

import logging
import time
import os
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

try:
    from core.circuit_breaker import get_ai_circuit_breaker, CircuitOpenError
    CIRCUIT_BREAKER_AVAILABLE = True
except Exception:
    CIRCUIT_BREAKER_AVAILABLE = False

try:
    from core.observability import get_metrics, Metrics
    OBSERVABILITY_AVAILABLE = True
except Exception:
    OBSERVABILITY_AVAILABLE = False

logger = logging.getLogger(__name__)

# ============================================================================
# Model Configuration
# ============================================================================

# Model fallback chain (primary -> secondary -> emergency)
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
FALLBACK_MODELS = [
    ("openai", OPENAI_MODEL),
    ("openai", "gpt-3.5-turbo"),
]

# Initialize OpenAI client
client = OpenAI(api_key=OPENAI_API_KEY or None)

# Fallback response when all AI models fail
FALLBACK_RESPONSE = (
    "I'm having a little trouble right now. "
    "Could I take your name and number so we can call you back shortly?"
)

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


def _voice_business_prompt(
    bd: dict,
    sentiment_context: Optional[Dict] = None,
    kb_entries: Optional[List] = None,
    customer_info: Optional[Dict] = None
) -> str:
    """Build voice-optimized system prompt — top-tier, natural, fully contextual.

    Args:
        bd: Business data dict
        sentiment_context: Current sentiment analysis
        kb_entries: Relevant knowledge base entries
        customer_info: Known caller info (name, history, preferences)
    """
    from datetime import datetime

    name = bd.get("name", "this business")
    hours = bd.get("hours", "")
    addr = bd.get("address", "")
    tone = bd.get("tone", "friendly and professional")

    # Get current time for context
    now = datetime.now()
    current_time = now.strftime("%I:%M %p").lstrip("0")
    current_day = now.strftime("%A")

    # Build services info if available
    services_info = ""
    services_data = bd.get("services_list") or bd.get("services", "")
    if isinstance(services_data, list) and services_data:
        services_lines = []
        for s in services_data[:10]:  # Limit to top 10
            if isinstance(s, dict):
                svc_name = s.get("name", "")
                duration = s.get("duration_min", "")
                price = s.get("price", "")
                if svc_name:
                    line = f"  • {svc_name}"
                    if duration:
                        line += f" ({duration} minutes)"
                    if price:
                        line += f" - {price}"
                    services_lines.append(line)
        if services_lines:
            services_info = "\n".join(services_lines)
    elif isinstance(services_data, str) and services_data:
        services_info = services_data

    base_prompt = f"""You are the AI phone receptionist for {name}. You sound completely human — warm, natural, and effortlessly professional. Callers should feel like they're speaking with the friendliest, most capable receptionist they've ever encountered.

## Your Personality
- {tone.capitalize()} but never robotic or scripted
- Genuinely helpful — you want to solve their problem
- Quick and efficient — respect their time
- Confident but not pushy
- Use contractions naturally (I'll, you're, we've, that's)

## Current Context
- It's currently {current_day}, {current_time}
- You're answering calls for {name}
"""

    # Add caller recognition context if we know them
    if customer_info and customer_info.get("name"):
        cust_name = customer_info.get("name", "")
        visit_count = customer_info.get("total_appointments", 0) or customer_info.get("visit_count", 0)
        last_service = customer_info.get("last_service", "")
        last_visit = customer_info.get("last_visit", "")
        preferred_staff = customer_info.get("preferred_staff", "")
        notes = customer_info.get("notes", "")

        base_prompt += f"""
## CALLER RECOGNIZED: {cust_name}
You know this caller! Greet them warmly by name.
"""
        if visit_count > 0:
            if visit_count == 1:
                base_prompt += f"- They've visited once before\n"
            else:
                base_prompt += f"- Returning customer with {visit_count} previous visits\n"

        if last_service and last_visit:
            base_prompt += f"- Last visit: {last_service} on {last_visit}\n"
        elif last_service:
            base_prompt += f"- Last service: {last_service}\n"

        if preferred_staff:
            base_prompt += f"- Usually sees: {preferred_staff}\n"

        if notes:
            base_prompt += f"- Notes: {notes}\n"

        base_prompt += """
Use their name naturally in conversation (but don't overdo it).
If rebooking, you can suggest: "Would you like the same service as last time?"
"""

    base_prompt += """
## Business Information
"""

    if hours:
        base_prompt += f"HOURS: {hours}\n"
    if addr:
        base_prompt += f"ADDRESS: {addr}\n"
    if services_info:
        base_prompt += f"\nSERVICES OFFERED:\n{services_info}\n"

    base_prompt += """
## Voice Conversation Rules (CRITICAL)
1. BREVITY IS KEY: 1-2 sentences per response. This is a phone call, not an essay.
2. SOUND HUMAN: Use natural speech — "Sure thing!", "Absolutely!", "Let me check that", "Perfect!"
3. NO FORMATTING: Never use bullet points, numbered lists, or markdown. Just speak naturally.
4. NUMBERS: Say "two thirty" not "14:30", "oh-seven-seven" for phone numbers
5. SPELL CAREFULLY: For names/addresses, offer to spell: "That's S-M-I-T-H, right?"
6. CONFIRM BACK: Repeat important details: "So that's Tuesday at 3pm for a haircut?"
7. SMOOTH TRANSITIONS: "Great!", "Perfect!", "Brilliant!", "Got it!"

## Handling Bookings
When booking, collect naturally through conversation:
1. What service they'd like
2. When works for them (date and time)
3. Their name
4. A contact number

Once you have ALL details AND they confirm, output:
<VOICE_BOOKING>{{"name":"NAME","phone":"PHONE","service":"SERVICE","datetime":"YYYY-MM-DD HH:MM"}}</VOICE_BOOKING>

Before outputting the tag, always confirm: "So that's [service] on [date] at [time] for [name]. Should I book that in for you?"

## Handling Questions
- If you know the answer from the business info above, answer confidently
- If you're not sure, say: "I'm not certain about that — let me have someone get back to you"
- Never make up information

## Transfers & Escalation
- If they ask for a human/manager: "Of course, let me connect you with someone"
- If they're upset: Empathize first, then help: "I'm really sorry about that. Let me sort this out for you."
- For emergencies: Act with appropriate urgency

## What NEVER to Do
- Never say "as an AI" or mention you're artificial
- Never give long responses — keep it punchy
- Never sound scripted or like you're reading
- Never say "I don't have access to" — just say "I'm not sure about that"
- Never repeat the same phrase twice in a row
"""

    # Add KB context if available
    if kb_entries:
        base_prompt += "\n## Business Knowledge Base\n"
        for entry in kb_entries[:5]:
            if isinstance(entry, dict):
                q = entry.get("question", entry.get("title", ""))
                a = entry.get("answer", entry.get("content", ""))
                if q and a:
                    base_prompt += f"Q: {q}\nA: {a}\n\n"

    # Sentiment-adaptive additions
    if sentiment_context:
        sentiment = sentiment_context.get("sentiment")
        frustration = sentiment_context.get("frustration_score", 0)

        if sentiment in ("frustrated", "angry") or frustration > 0.5:
            base_prompt += """
## IMPORTANT: Caller Alert
The caller seems frustrated or upset. Adjust your approach:
- Lead with empathy: "I completely understand" / "I'm sorry you're dealing with this"
- Be extra patient and don't rush them
- Focus on solutions, not explanations
- Offer to escalate if they're not satisfied: "Would you like me to have a manager call you back?"
"""
        elif sentiment == "urgent":
            base_prompt += """
## IMPORTANT: Urgent Call
This seems urgent. Respond with appropriate urgency:
- Skip small talk and get to the point
- Prioritize solving their immediate need
- If it's a medical/safety emergency, recommend appropriate services
"""
        elif sentiment == "confused":
            base_prompt += """
## IMPORTANT: Caller Needs Clarity
The caller seems unsure or confused:
- Use simpler language
- Take it one step at a time
- Offer to explain things differently
- Be reassuring: "No worries, I can help with that"
"""

    return base_prompt.strip()


def _call_ai_with_resilience(messages: List[Dict], max_retries: int = 2) -> str:
    """Call AI model with circuit breaker and fallback chain.

    Implements:
    1. Circuit breaker to prevent cascading failures
    2. Model fallback (primary -> secondary models)
    3. Retry with exponential backoff
    4. Metrics collection

    Returns:
        AI response string, or empty string on complete failure
    """
    circuit_breaker = get_ai_circuit_breaker() if CIRCUIT_BREAKER_AVAILABLE else None
    metrics = get_metrics() if OBSERVABILITY_AVAILABLE else None

    for provider, model in FALLBACK_MODELS:
        service_key = f"{provider}:{model}"

        # Check circuit breaker
        if circuit_breaker and circuit_breaker.is_open(service_key):
            logger.warning(f"Circuit open for {service_key}, trying next model")
            continue

        # Try with retries
        for attempt in range(max_retries + 1):
            start_time = time.time()

            try:
                # Record attempt
                if metrics:
                    metrics.inc_counter(Metrics.AI_REQUESTS_TOTAL, {"model": model})

                # Make API call
                resp = client.chat.completions.create(
                    model=model,
                    messages=messages,
                    max_tokens=300,
                    temperature=0.6,
                    timeout=30,  # 30 second timeout
                )

                reply = resp.choices[0].message.content or ""
                duration = time.time() - start_time

                # Record success metrics
                if metrics:
                    metrics.observe_histogram(
                        Metrics.AI_REQUEST_DURATION,
                        duration,
                        {"model": model}
                    )
                    if hasattr(resp, 'usage') and resp.usage:
                        metrics.inc_counter(
                            Metrics.AI_TOKENS_USED,
                            {"model": model},
                            resp.usage.total_tokens
                        )

                # Record circuit breaker success
                if circuit_breaker:
                    circuit_breaker.record_success(service_key)

                logger.debug(f"AI response from {model} in {duration:.2f}s")
                return reply

            except Exception as e:
                duration = time.time() - start_time

                # Record failure metrics
                if metrics:
                    metrics.inc_counter(
                        Metrics.AI_ERRORS_TOTAL,
                        {"model": model, "error_type": type(e).__name__}
                    )
                    metrics.observe_histogram(
                        Metrics.AI_REQUEST_DURATION,
                        duration,
                        {"model": model, "status": "error"}
                    )

                # Record circuit breaker failure
                if circuit_breaker:
                    circuit_breaker.record_failure(service_key, str(e))

                logger.warning(
                    f"AI call to {model} failed (attempt {attempt + 1}/{max_retries + 1}): {e}"
                )

                # Retry with backoff
                if attempt < max_retries:
                    backoff = 2 ** attempt  # 1s, 2s, 4s...
                    time.sleep(min(backoff, 10))
                    continue

                # Move to next model in fallback chain
                break

    # All models failed
    logger.error("All AI models failed, returning fallback response")
    return ""

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
    # Generate AI Response (with circuit breaker and fallback)
    # =========================================================================
    reply = _call_ai_with_resilience(messages)
    if not reply:
        reply = FALLBACK_RESPONSE

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


def _get_business_services(business_id: int) -> List[Dict]:
    """Fetch active services for a business."""
    try:
        from core.db import get_conn
        with get_conn() as con:
            rows = con.execute("""
                SELECT name, duration_min, price FROM services
                WHERE business_id = ? AND active = 1
                ORDER BY name
            """, (business_id,)).fetchall()
            return [dict(r) for r in rows]
    except Exception:
        return []


def _get_kb_entries_for_voice(business_id: int, query: str, limit: int = 5) -> List[Dict]:
    """Fetch relevant KB entries for voice context."""
    if not kb_search or not business_id:
        return []
    try:
        rows = kb_search(business_id, query, limit=limit) or []
        entries = []
        for r in rows:
            if isinstance(r, dict):
                entries.append(r)
            else:
                entries.append({
                    "question": r.get("title", "") if hasattr(r, "get") else "",
                    "answer": r.get("content", "") if hasattr(r, "get") else ""
                })
        return entries
    except Exception:
        return []


def process_message_for_voice(
    user_input: str,
    business_data: Dict,
    state: Optional[Dict] = None,
    customer_id: Optional[int] = None,
    customer_info: Optional[Dict] = None
) -> str:
    """
    Generate a voice-optimized receptionist reply with full business context.

    This is the top-tier voice AI that:
    - Uses natural, human-like conversation
    - Has full access to business services, hours, KB
    - Handles booking with verbal confirmation
    - Adapts tone based on sentiment
    - Keeps responses short and punchy for voice

    Returns:
        Reply string optimized for voice
    """
    if state is None:
        state = {}

    bd = _row_to_dict(business_data)
    business_id = bd.get("id")
    session_id = state.get("session_id")
    user_text = (user_input or "").strip() or "Hello"

    # Enrich business data with services if not already present
    if business_id and "services_list" not in bd:
        bd["services_list"] = _get_business_services(business_id)

    # Get conversation history
    conversation_history = []
    if session_id:
        conversation_history = _history_from_db(session_id, limit=8)
    else:
        conversation_history = state.get("history", [])[-6:]

    # Sentiment Analysis
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
            sentiment_context = {
                "sentiment": sentiment_result.sentiment.value,
                "intent": sentiment_result.intent.value,
                "confidence": sentiment_result.confidence,
                "frustration_score": sentiment_result.details.get("frustration_score", 0)
            }
        except Exception as e:
            logger.warning(f"Sentiment analysis failed: {e}")

    # Escalation Check
    if sentiment_result and sentiment_result.triggers_escalation and ESCALATION_AVAILABLE:
        try:
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
                state["escalated"] = True
                state["escalation_id"] = escalation_id
                # Voice-optimized escalation response
                return "I understand. Let me connect you with a team member who can help you directly."
        except Exception as e:
            logger.error(f"Escalation handling failed: {e}")

    # Get relevant KB entries for context
    kb_entries = []
    if business_id:
        kb_entries = _get_kb_entries_for_voice(business_id, user_text, limit=5)

    # Build voice-optimized prompt with full context including caller recognition
    sys_prompt = _voice_business_prompt(bd, sentiment_context, kb_entries, customer_info)

    # Build messages
    messages = [{"role": "system", "content": sys_prompt}]
    messages.extend(conversation_history)
    messages.append({"role": "user", "content": user_text})

    # Call AI
    reply = _call_ai_with_resilience(messages, max_retries=2)

    if not reply:
        reply = "I'm having a little trouble right now. Could you say that again?"

    # Update state
    if "history" not in state:
        state["history"] = []
    state["history"].append({"role": "user", "content": user_text})
    state["history"].append({"role": "assistant", "content": reply})
    if len(state["history"]) > 16:
        state["history"] = state["history"][-16:]

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
