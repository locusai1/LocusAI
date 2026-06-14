# core/demo.py — "Try it now" instant AI receptionist demo.
#
# Top-of-funnel conversion tool: a prospect types their business name + website,
# we scrape the site (SSRF-guarded, reusing kb_ingest.fetch_page_text) and spin
# up a live AI receptionist that answers using THEIR real information — before
# they ever sign up. No database writes, no bookings, no escalations: the whole
# conversation lives in the Flask session.

import logging
from typing import Any, Dict, List, Tuple

from core.settings import OPENAI_MODEL

logger = logging.getLogger(__name__)

MAX_CONTEXT_CHARS = 4500
MAX_HISTORY = 12  # turns kept in the session


def is_available() -> bool:
    from core.settings import OPENAI_API_KEY

    return bool(OPENAI_API_KEY)


def build_demo_context(name: str, url: str = "") -> Tuple[bool, Dict[str, Any]]:
    """Scrape the business site (if given) and assemble the demo context.

    Returns (ok, {"name", "context", "greeting"}) or (False, {"error": ...})."""
    name = (name or "").strip() or "your business"
    context = ""
    if url:
        from core.kb_ingest import fetch_page_text

        ok, text = fetch_page_text(url, max_chars=MAX_CONTEXT_CHARS)
        if ok:
            context = text
        else:
            # Soft-fail: still run the demo, just without site knowledge.
            logger.info("Demo scrape failed for %s: %s", url, text)

    greeting = f"Hi, thanks for calling {name}! I'm your AI receptionist. How can I help you today?"
    return True, {"name": name, "context": context, "greeting": greeting}


def _system_prompt(name: str, context: str) -> str:
    ctx = (
        f"\n\nHere is information from {name}'s website. Use it to answer accurately:\n"
        f'"""\n{context}\n"""'
        if context
        else ""
    )
    return (
        f"You are a friendly, professional AI phone receptionist for {name}. "
        "Answer customer questions helpfully and concisely (1-3 sentences), the way a "
        "great receptionist would on the phone. If you don't know a specific detail "
        "(exact price, address, hours), say you'll check or offer to take a message — "
        "never invent facts. Encourage booking when relevant. This is a live demo of "
        "the LocusAI receptionist." + ctx
    )


def demo_reply(context: Dict[str, Any], history: List[Dict[str, str]], message: str) -> str:
    """Generate one receptionist reply. No side effects."""
    if not is_available():
        return (
            "(Demo unavailable: the AI isn't configured on this server. "
            "Sign up and add your OpenAI key to try the real thing.)"
        )
    from core.ai import client

    messages = [
        {
            "role": "system",
            "content": _system_prompt(context.get("name", ""), context.get("context", "")),
        }
    ]
    for turn in history[-MAX_HISTORY:]:
        role = "assistant" if turn.get("role") == "assistant" else "user"
        messages.append({"role": role, "content": turn.get("content", "")})
    messages.append({"role": "user", "content": message})

    try:
        resp = client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=messages,
            temperature=0.6,
            max_tokens=180,
        )
        return (resp.choices[0].message.content or "").strip() or "Sorry, could you say that again?"
    except Exception as e:
        logger.warning("demo_reply failed: %s", e)
        return "Sorry, I'm having trouble right now — please try again in a moment."
