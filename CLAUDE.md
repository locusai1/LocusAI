# LocusAI

AI receptionist SaaS for SMBs - handles customer chat, appointment booking, sentiment analysis, and human escalation.

## Quick Start

```bash
cd /Users/paulomartinez/LocusAI
.venv/bin/python -m flask --app dashboard run --host=0.0.0.0 --port=5050

# http://127.0.0.1:5050 | Login: admin / admin

# Tests
.venv/bin/python -m pytest tests/ -v

# Voice (Flask + WebSocket)
./start_voice.sh
```

## Tech Stack

| Component | Technology |
|-----------|------------|
| Backend | Python 3.9, Flask |
| Database | SQLite (WAL mode) |
| Frontend | Jinja2, Tailwind CSS, Chart.js |
| AI | OpenAI GPT-4o-mini |
| Voice | Retell AI WebSocket integration |
| Auth | Session-based, bcrypt/pbkdf2 |

## Project Structure

```
dashboard.py           # Main Flask app entry point
voice_ws.py            # WebSocket server for Retell voice (port 8080)
start_voice.sh         # Starts Flask + WebSocket servers

Blueprints (14):
  auth_bp.py           # /login, /logout
  appointments_bp.py   # /appointments/*, /hours, /closures, /availability
  customers_bp.py      # /customers/*
  services_bp.py       # /services/*
  chat_bp.py           # /chat (conversation viewer)
  escalations_bp.py    # /escalations/*
  kb_bp.py             # /kb/* (knowledge base)
  analytics_bp.py      # /analytics/*
  widget_bp.py         # /api/widget/* (embeddable chat)
  voice_bp.py          # /api/voice/* (Retell webhooks)
  sms_bp.py            # SMS webhooks (Twilio)
  integrations_bp.py   # /integrations
  onboard_bp.py        # /onboard
  search_bp.py         # /search

Core Modules (25):
  ai.py                # process_message(), process_message_with_metadata()
  booking.py           # extract_pending_booking(), confirm_pending_booking()
  sentiment.py         # analyze_sentiment() → SentimentResult
  escalation.py        # create_escalation(), handle_escalation()
  db.py                # get_conn(), transaction(), init_db()
  validators.py        # validate_email(), validate_phone(), validate_name()
  encryption.py        # encrypt_field(), decrypt_field() - Fernet AES
  circuit_breaker.py   # CircuitBreaker class, @with_circuit_breaker
  voice.py             # Voice call management, Retell client
  security.py          # mask_pii(), verify_signature_hmac(), check_rate_limit()
  sms.py               # send_sms(), parse_twilio_webhook()
  reminders.py         # schedule_reminders_for_appointment()
  observability.py     # MetricsCollector, @timed, @counted decorators
  mailer.py            # send_email()
  ics.py               # make_ics() - iCalendar generation
  authz.py             # user_can_access_business()
  knowledge.py         # kb_search() - FTS5 search
  settings.py          # Environment config loading

templates/             # 31 Jinja2 templates
static/                # locus.css, app.js, widget.js, logo.svg
tests/                 # 554 tests across 18 files
```

## Database Schema

```sql
businesses    (id, name, slug, tenant_key, hours, address, tone, accent_color, escalation_email)
users         (id, email, name, password_hash, role[admin|owner])
business_users(user_id, business_id)  -- many-to-many
sessions      (id, business_id, channel, phone, customer_id, escalated)
messages      (id, session_id, sender[user|bot], text, timestamp)
appointments  (id, business_id, customer_name, phone, service, start_at, status[pending|confirmed|cancelled|completed])
customers     (id, business_id, name, email, phone, total_appointments, total_sessions)
services      (id, business_id, name, duration_min, price, active)
escalations   (id, business_id, session_id, reason, status[pending|acknowledged|resolved], priority)
kb_entries    (id, business_id, question, answer, tags)  -- FTS5 enabled
business_hours(id, business_id, weekday, open_time, close_time, closed)
closures      (id, business_id, date, reason)
reminders     (id, appointment_id, type[24h|1h|15m], channel[email|sms], scheduled_for, status)
```

## Environment Variables (.env)

```bash
OPENAI_API_KEY=sk-...           # Required - AI conversations
FLASK_SECRET_KEY=...            # Required - session encryption
RETELL_API_KEY=key_...          # Voice AI
ENCRYPTION_KEY=...              # PII field encryption (optional)
TWILIO_ACCOUNT_SID=...          # SMS (optional)
TWILIO_AUTH_TOKEN=...
TWILIO_PHONE_NUMBER=...
```

## Key Flows

**Booking Confirmation**:
1. AI detects booking intent → outputs `<BOOKING>{"name":"...","phone":"...","service":"...","slot":"..."}</BOOKING>`
2. `extract_pending_booking()` parses tag, stores with 32-char token, 5-min expiry
3. Widget shows confirmation card with booking details
4. User clicks Confirm → `POST /api/widget/booking/confirm` → `confirm_pending_booking(token)` commits to DB
5. User clicks Cancel → booking discarded

**Sentiment & Escalation**:
- `analyze_sentiment(text, history)` returns `SentimentResult` with `triggers_escalation` flag
- Triggers: "speak to human", frustration_score > 0.7, complaint + negative indicators, 3+ failed attempts
- On escalation: creates record, sends email notification, returns handoff message

**Widget API** (requires X-Tenant-Key header):
- `POST /api/widget/session` → creates session, returns welcome message
- `POST /api/widget/chat` → sends message, returns AI reply + optional pending_booking
- `POST /api/widget/booking/confirm` → confirms booking with token
- `POST /api/widget/booking/cancel` → cancels pending booking

## Security Features

- **Account Lockout**: 5 failed logins → 15 min lockout (per email + IP)
- **CSRF**: All forms protected
- **Rate Limiting**: Widget API 30 req/60s per tenant
- **PII Encryption**: Fernet AES-128, `enc:` prefix
- **Input Validation**: Email, phone, name, slug, redirect URL validation
- **Webhook Verification**: HMAC, Twilio, Stripe signature verification

## Test Suite (554 tests)

| File | Tests | Coverage |
|------|-------|----------|
| test_validators.py | 95 | Input validation, CSV escaping |
| test_security.py | 61 | PII masking, webhooks, rate limiting |
| test_sentiment.py | 46 | Sentiment analysis, intent detection |
| test_sms.py | 41 | Twilio integration, TwiML |
| test_encryption.py | 39 | Field encryption, token hashing |
| test_db.py | 29 | Database operations |
| test_auth.py | 28 | Login, lockout, user management |
| test_booking_confirmation.py | 25 | Token flow, confirm/cancel |
| test_circuit_breaker.py | 25 | States, decorators, resilience |
| test_widget_api.py | 25 | Widget endpoints, CORS |
| test_ics.py | 23 | iCalendar generation |
| test_voice.py | 23 | Voice call management |
| test_ai.py | 22 | AI conversation, prompts |
| test_observability.py | 22 | Metrics collection |
| test_reminders.py | 19 | Reminder scheduling |
| test_escalation.py | 18 | Human handoff |
| test_authz.py | 12 | Authorization checks |
| test_booking.py | 1 | Booking commit smoke test |

```bash
.venv/bin/python -m pytest tests/ -v                    # All
.venv/bin/python -m pytest tests/test_sentiment.py -v   # Specific
```

## Current State (Jan 2026)

- ✅ Rebranding complete: AxisAI → LocusAI (all references updated)
- ✅ Test suite expanded: 307 → 554 tests
- ✅ Voice AI: Retell integration working (WebSocket + webhooks)
- ✅ Booking confirmation flow: User must confirm before commit
- ✅ Security hardened: Lockout, encryption, rate limiting, validation
