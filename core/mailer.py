import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formatdate, make_msgid, parseaddr
from typing import List, Optional, Tuple

from core.settings import SMTP_FROM, SMTP_HOST, SMTP_PASS, SMTP_PORT, SMTP_TLS, SMTP_USER


def _from_domain() -> str:
    """The domain of the From address, for Message-ID and default unsubscribe."""
    addr = parseaddr(SMTP_FROM or "")[1]
    return addr.split("@", 1)[1] if "@" in addr else "locusai.co.uk"


def send_email(
    to_email: str,
    subject: str,
    body: str,
    attachments: Optional[List[Tuple[str, str, bytes]]] = None,
    *,
    reply_to: Optional[str] = None,
    list_unsubscribe_url: Optional[str] = None,
    unsubscribe_mailto: Optional[str] = None,
    auto_generated: bool = False,
    to: Optional[str] = None,
) -> bool:
    """Send a plain-text email.

    attachments: list of (filename, mime_type, content_bytes)

    Deliverability extras (all optional):
      reply_to               — Reply-To header.
      list_unsubscribe_url   — enables one-click List-Unsubscribe (RFC 8058).
      unsubscribe_mailto     — mailto: unsubscribe address; defaults to
                               unsubscribe@<from-domain> for bulk/automated mail.
      auto_generated         — marks reminders/digests as auto-generated so
                               receivers suppress vacation auto-replies.

    `to` is accepted as an alias for `to_email` for backward compatibility.
    Returns True if sent (or logged when SMTP not configured).
    """
    to_email = to_email or to
    if not to_email:
        raise ValueError("send_email: recipient address is required")

    if not SMTP_HOST:
        # Fallback: log to stdout/file so you can see the email without SMTP
        print("=== EMAIL (LOG ONLY) ===")
        print("To:", to_email)
        print("Subject:", subject)
        print("Body:\n", body)
        if attachments:
            for fn, mt, _ in attachments:
                print(f"[Attachment simulated: {fn} ({mt})]")
        print("========================")
        return True

    msg = EmailMessage()
    msg["From"] = SMTP_FROM
    msg["To"] = to_email
    msg["Subject"] = subject
    # Date + Message-ID materially improve spam scoring / threading.
    msg["Date"] = formatdate(localtime=True)
    msg["Message-ID"] = make_msgid(domain=_from_domain())
    if reply_to:
        msg["Reply-To"] = reply_to

    # List-Unsubscribe (bulk / automated mail): give recipients a clear opt-out,
    # which reduces spam complaints and improves inbox placement.
    if list_unsubscribe_url or unsubscribe_mailto or auto_generated:
        mailto = unsubscribe_mailto or f"unsubscribe@{_from_domain()}"
        parts = []
        if list_unsubscribe_url:
            parts.append(f"<{list_unsubscribe_url}>")
        parts.append(f"<mailto:{mailto}?subject=unsubscribe>")
        msg["List-Unsubscribe"] = ", ".join(parts)
        if list_unsubscribe_url:
            # RFC 8058 one-click unsubscribe.
            msg["List-Unsubscribe-Post"] = "List-Unsubscribe=One-Click"

    if auto_generated:
        msg["Auto-Submitted"] = "auto-generated"

    msg.set_content(body)

    for fn, mt, content in attachments or []:
        maintype, subtype = (mt.split("/", 1) + ["octet-stream"])[:2]
        msg.add_attachment(content, maintype=maintype, subtype=subtype, filename=fn)

    ctx = ssl.create_default_context()
    if SMTP_TLS:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as s:
            s.starttls(context=ctx)
            if SMTP_USER:
                s.login(SMTP_USER, SMTP_PASS or "")
            s.send_message(msg)
    else:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as s:
            if SMTP_USER:
                s.login(SMTP_USER, SMTP_PASS or "")
            s.send_message(msg)
    return True
