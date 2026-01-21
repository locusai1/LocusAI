import smtplib, ssl, os
from email.message import EmailMessage
from typing import Optional, List, Tuple
from core.settings import SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASS, SMTP_FROM, SMTP_TLS

def send_email(to_email: str, subject: str, body: str,
               attachments: Optional[List[Tuple[str,str,bytes]]] = None) -> bool:
    """
    attachments: list of (filename, mime_type, content_bytes)
    Returns True if sent (or logged when SMTP not configured).
    """
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
    msg.set_content(body)

    for fn, mt, content in (attachments or []):
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
