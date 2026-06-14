# core/kb_ingest.py — build KB entries from a business's website.
# Owner pastes a URL; we fetch the page (SSRF-guarded), extract the text, and
# ask GPT to turn it into receptionist-ready Q&A. Cuts onboarding from minutes
# of typing to one paste.

from __future__ import annotations

import logging
import re
from html.parser import HTMLParser
from typing import Dict, List

logger = logging.getLogger(__name__)

FETCH_TIMEOUT = 10  # seconds
MAX_BYTES = 2_000_000  # 2 MB cap on the downloaded page
MAX_TEXT_CHARS = 6000  # how much page text we feed the model
MIN_TEXT_CHARS = 80  # below this there's nothing worth learning from
_SKIP_TAGS = {"script", "style", "noscript", "svg", "head"}


class _TextExtractor(HTMLParser):
    """Collect visible text, skipping script/style/etc."""

    def __init__(self) -> None:
        super().__init__()
        self.parts: List[str] = []
        self._skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in _SKIP_TAGS:
            self._skip += 1

    def handle_endtag(self, tag):
        if tag in _SKIP_TAGS and self._skip:
            self._skip -= 1

    def handle_data(self, data):
        if self._skip == 0:
            t = data.strip()
            if t:
                self.parts.append(t)


def _html_to_text(html: str) -> str:
    p = _TextExtractor()
    try:
        p.feed(html)
    except Exception:
        # Malformed HTML — fall back to a crude tag strip.
        return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html)).strip()
    return re.sub(r"\s+", " ", " ".join(p.parts)).strip()


def fetch_page_text(url: str, *, max_chars: int = MAX_TEXT_CHARS):
    """Fetch a URL and return (ok, text_or_error_message). SSRF-guarded."""
    from core.webhooks import is_safe_url

    if not is_safe_url(url):
        return False, "That URL isn't allowed. Use a public https:// web address."

    import requests

    try:
        resp = requests.get(
            url,
            timeout=FETCH_TIMEOUT,
            headers={"User-Agent": "LocusAI-KB-Import/1.0"},
            allow_redirects=True,
        )
    except Exception as e:
        logger.info("KB import fetch failed for %s: %s", url, e)
        return False, "Couldn't reach that page. Check the address and try again."

    if resp.status_code >= 400:
        return False, f"That page returned an error ({resp.status_code})."

    ctype = (resp.headers.get("Content-Type") or "").lower()
    if "html" not in ctype and "text" not in ctype:
        return False, "That link isn't a web page I can read."

    raw = resp.content[:MAX_BYTES]
    try:
        html = raw.decode(resp.encoding or "utf-8", errors="replace")
    except Exception:
        html = raw.decode("utf-8", errors="replace")

    text = _html_to_text(html)
    return True, text[:max_chars]


def _build_prompt(business_name: str, page_text: str, existing: List[str]) -> str:
    name = business_name or "this business"
    existing_block = ""
    if existing:
        existing_block = (
            "\n\nThe knowledge base ALREADY covers these questions — do NOT repeat them:\n- "
            + "\n- ".join(existing[:40])
        )
    return f"""You are setting up an AI receptionist for "{name}".
Below is text scraped from the business's website. Turn it into the most useful
FAQ entries a receptionist would need: services offered, prices, opening hours,
location/parking, booking/cancellation policy, contact details, and anything
else a caller commonly asks.

Rules:
- Only use facts present in the website text. Never invent prices, hours, or policies.
- Phrase each "question" the way a real customer would ask it.
- Keep answers short and factual (1-3 sentences).
- Produce at most 8 entries. If the text is too thin, produce fewer (or none).
- Respond with ONLY valid JSON: {{"suggestions":[{{"question":"...","answer":"..."}}]}}{existing_block}

WEBSITE TEXT:
\"\"\"
{page_text}
\"\"\""""


def suggest_from_website(business_id: int, url: str, business_name: str = "") -> Dict:
    """Fetch a URL and return KB suggestions derived from it.

    Returns {"configured": bool, "suggestions": [...], "error": optional str}.
    """
    from core.kb_suggestions import _complete, _parse, existing_questions, is_configured

    if not is_configured():
        return {"configured": False, "suggestions": []}

    url = (url or "").strip()
    if not url:
        return {"configured": True, "suggestions": [], "error": "Enter a website address."}
    if not re.match(r"^https?://", url, re.I):
        url = "https://" + url

    ok, text = fetch_page_text(url)
    if not ok:
        return {"configured": True, "suggestions": [], "error": text}
    if len(text) < MIN_TEXT_CHARS:
        return {
            "configured": True,
            "suggestions": [],
            "error": "There wasn't enough readable text on that page to learn from.",
        }

    existing = existing_questions(business_id)
    try:
        raw = _complete(_build_prompt(business_name, text, existing))
        items = _parse(raw)
    except Exception:
        logger.warning("KB website suggestion generation failed", exc_info=True)
        return {"configured": True, "suggestions": [], "error": "Couldn't generate suggestions."}

    seen = {q.strip().lower() for q in existing}
    out: List[Dict[str, str]] = []
    for it in items:
        q = (it.get("question") or "").strip()
        if q and q.lower() not in seen:
            seen.add(q.lower())
            out.append({"question": q, "answer": (it.get("answer") or "").strip()})
    return {"configured": True, "suggestions": out}
