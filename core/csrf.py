import secrets
from flask import session, request, abort

_EXEMPT_METHODS = {"GET", "HEAD", "OPTIONS"}

# Paths that are exempt from CSRF protection (use tenant key auth instead)
_EXEMPT_PATHS = {
    "/api/widget/",      # Widget API uses tenant key auth
    "/api/sms/",         # SMS webhooks use signature verification
    "/api/whatsapp/",    # WhatsApp webhooks use signature verification
}

def _get_token():
    tok = session.get("csrf_token")
    if not tok:
        tok = secrets.token_urlsafe(32)
        session["csrf_token"] = tok
    return tok

def register_csrf(app):
    @app.context_processor
    def inject_csrf():
        return {"csrf_token": _get_token()}

    @app.before_request
    def enforce_csrf():
        if request.method in _EXEMPT_METHODS:
            return

        # Skip CSRF for exempt paths (they use alternative auth)
        for exempt_path in _EXEMPT_PATHS:
            if request.path.startswith(exempt_path):
                return

        # Allow JSON and form: look in header then form field
        sent = request.headers.get("X-CSRF-Token") or request.form.get("csrf_token")
        if not sent or sent != session.get("csrf_token"):
            abort(403)
