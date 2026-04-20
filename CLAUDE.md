# LocusAI

AI receptionist SaaS for SMBs. Handles inbound calls (voice), web chat, SMS, appointment booking, sentiment analysis, and human escalation. Multi-tenant. UK-based phone number (+442046203253). Built on Flask + SQLite + Retell AI + Telnyx.

**The pitch**: "AI that answers your business calls 24/7, books appointments, and never takes a day off."
**We are**: The AI receptionist that integrates with everything you already use.
**We are NOT**: Another all-in-one platform asking businesses to switch everything.

---

## Quick Start

```bash
cd /Users/paulomartinez/LocusAI
.venv/bin/python -m flask --app dashboard run --host=0.0.0.0 --port=5050

# http://127.0.0.1:5050 | Login: admin@locusai.local / admin

# Tests
.venv/bin/python -m pytest tests/ -v

# Voice WebSocket server (needed only for custom LLM mode)
./start_voice.sh
```

**Default Test Business**: ID 9 — StyleCuts Hair Studio | admin@locusai.local / admin

---

## Tech Stack

| Component | Technology |
|-----------|------------|
| Backend | Python 3.9, Flask |
| Database | SQLite (WAL mode) |
| Frontend | Jinja2, Tailwind CSS (CDN — must remove for prod), Chart.js |
| AI | OpenAI GPT-4o-mini |
| Voice | Retell AI (native LLM) + Telnyx SIP |
| SMS | Telnyx |
| Auth | Session-based, bcrypt/pbkdf2 |
| Encryption | Fernet AES-128 for PII fields |

---

## Project Structure

```
dashboard.py           # Main Flask app — registers all 14 blueprints, middleware, error handlers
voice_ws.py            # WebSocket server for Retell custom LLM mode (port 8080) — optional
start_voice.sh         # Dev script: starts Flask + WebSocket together

Blueprints (14):
  auth_bp.py           # /login, /logout, /signup, /forgot-password, /reset-password, /verify-email,
                       #   /verify-email-pending, /users (admin)
  appointments_bp.py   # /appointments/*, /hours, /closures, /availability
  customers_bp.py      # /customers/* (list, detail, create, edit, merge, voice history)
  services_bp.py       # /services/*
  chat_bp.py           # /chat (conversation viewer with transcript)
  escalations_bp.py    # /escalations/* (list, detail, acknowledge, resolve)
  kb_bp.py             # /kb/* (knowledge base CRUD + CSV bulk import)
  analytics_bp.py      # /analytics/* (KPIs, revenue projection, voice analytics)
  widget_bp.py         # /api/widget/* (embeddable chat API — requires X-Tenant-Key)
  voice_bp.py          # /api/voice/* (Retell webhooks, call-setup dynamic vars)
  sms_bp.py            # /api/sms/* (Telnyx webhooks — missed call, inbound SMS)
  integrations_bp.py   # /integrations (Google Calendar OAuth, Calendly config)
  onboard_bp.py        # /onboard (multi-step wizard for new business setup)
  search_bp.py         # /search (cross-entity: businesses, appointments, customers, KB)

Direct routes on app (dashboard.py):
  /                    → dashboard
  /privacy             → privacy.html (UK GDPR — working draft, needs solicitor review)
  /terms               → terms.html (working draft, needs solicitor review)
  /health              → JSON health check

Core Modules (26) — all in /core/:
  ai.py                # process_message(), process_message_with_metadata(), _kb_snippets() RAG
  booking.py           # extract_pending_booking(), confirm_pending_booking() — token flow
  sentiment.py         # analyze_sentiment(text, history) → SentimentResult with triggers_escalation
  escalation.py        # create_escalation(), handle_escalation()
  db.py                # get_conn(), transaction(), init_db() — all 19 tables defined here
  validators.py        # validate_email(), validate_phone(), validate_name(), validate_slug(), validate_password()
  encryption.py        # encrypt_field(), decrypt_field() — Fernet, enc: prefix
  circuit_breaker.py   # CircuitBreaker class, @with_circuit_breaker decorator
  voice.py             # Voice call management, Retell API client — prompt includes mandatory call recording consent
  security.py          # mask_pii(), verify_signature_hmac(), check_rate_limit()
  sms.py               # send_sms(), parse_telnyx_webhook()
  reminders.py         # schedule_reminders_for_appointment()
  observability.py     # MetricsCollector, @timed, @counted decorators
  mailer.py            # send_email() via SMTP — used for verification, password reset, reminders
  ics.py               # make_ics() — iCalendar file generation
  authz.py             # user_can_access_business()
  knowledge.py         # kb_search() — FTS5 full-text search wrapper
  kb.py                # Additional KB helpers
  settings.py          # Environment config loading (reads .env) — exposes APP_BASE_URL
  google_calendar.py   # Full OAuth2 flow + two-way Calendar sync (built, needs env config)
  integrations.py      # Integration helpers (store/retrieve OAuth tokens)
  csrf.py              # CSRF token generation + validation
  logger.py            # Structured logging setup
  tenantfs.py          # Tenant file system helpers
  utils.py             # Misc utility functions
  __init__.py          # Package init

Templates (39) — all in /templates/:
  base.html                 # Layout with sidebar, nav, flash messages, trial banner
  dashboard.html            # KPI cards, recent appointments, sessions, escalations
  login.html                # Auth — "Forgot password?" and "Start free trial" links now work
  signup.html               # Self-service signup — 14-day trial badge, name/email/password, terms note
  verify_email_sent.html    # "Check your inbox" page shown after signup — 3-step guide
  verify_email_pending.html # Shown to logged-in users who haven't verified — resend button
  forgot_password.html      # Password reset step 1 — email input
  reset_password.html       # Password reset step 2 — new password + confirm, strength indicator
  privacy.html              # UK GDPR Privacy Policy (working draft — needs solicitor review)
  terms.html                # Terms of Service (working draft — needs solicitor review)
  analytics.html            # Charts: revenue projection, voice analytics, sentiment trend
  appointments.html         # List view + new appointment modal
  appointments_new.html     # Create appointment form
  customers.html            # Customer list with search/filter
  customer_detail.html      # Profile + sessions history + voice call history + merge tool
  customer_edit.html        # Edit customer form
  customer_new.html         # Create customer form
  services.html             # Service management
  chat.html                 # Conversation transcript viewer
  escalations.html          # Escalation queue
  escalation_detail.html    # Single escalation with notes + resolution
  kb_list.html              # Knowledge base list + CSV bulk import modal
  kb_edit.html              # KB entry create/edit
  hours.html                # Business hours configuration
  closures.html             # Holiday / closure management
  availability.html         # Availability checker
  integrations.html         # Google Calendar OAuth + Calendly config
  voice.html                # Voice dashboard + settings modal + call log
  onboard.html              # Multi-step wizard (Basics → Services → AI Personality → Review)
  search.html               # Cross-entity search results
  admin_users.html          # User management (admin only)
  businesses.html           # Business list (admin only)
  edit_business.html        # Edit business settings
  delete_business.html      # Business deletion confirmation
  widget_frame.html         # Widget iframe shell (embedded in customer sites)
  error_400.html            # Bad request error page
  error_403.html            # Forbidden error page
  error_404.html            # Not found error page
  error_500.html            # Server error page

Static:
  static/locus.css          # Design system CSS (Linear/Stripe-inspired)
  static/app.js             # Dashboard JS utilities
  static/widget.js          # ~1009 lines — embeddable chat widget (served by Flask currently)
  static/logo.svg           # LocusAI logo

tests/                      # 563 tests across 18 files
```

---

## Database Schema

All tables defined in `core/db.py → init_db()` with idempotent ALTER TABLE migrations.

```sql
-- Multi-tenancy anchor
businesses    (id, name, slug, tenant_key, hours, address, services, tone,
               escalation_phone, escalation_email, data_retention_days,
               accent_color, logo_path, settings_json, files_path, static_path,
               archived, created_at)

users         (id, email NOCASE UNIQUE, name, password_hash,
               role[admin|owner], email_verified[0|1], trial_ends_at TEXT,
               signup_source TEXT, created_at)
               -- email_verified: 0=unverified, 1=verified. Admins bypass check.
               -- trial_ends_at: ISO datetime. NULL for admin-created users.
               -- signup_source: 'signup' for self-service, NULL for admin-created.

business_users(user_id, business_id, created_at)  -- many-to-many join

-- Email & password reset token tables
email_verification_tokens (id, user_id FK, token UNIQUE, expires_at, verified_at,
                            created_at)
               -- token: 32-char hex. expires_at: 24h. verified_at NULL=unused.
               -- Sending new token invalidates old ones (sets expires_at to now).

password_reset_tokens (id, user_id FK, token UNIQUE, expires_at, used[0|1],
                        created_at)
               -- token: 32-char hex. expires_at: 1h. used: 0=fresh, 1=consumed.
               -- Sending new token marks all existing tokens used=1.

-- Conversations
sessions      (id, business_id, channel[web|voice|sms], phone, customer_id,
               escalated, escalated_at, escalation_reason, created_at)

messages      (id, session_id, sender[user|bot], text, channel, timestamp)

-- Scheduling
appointments  (id, business_id, customer_name, phone, customer_email, service,
               start_at, status[pending|confirmed|cancelled|completed],
               session_id, customer_id, external_provider_key, external_id,
               source[ai|owner|api], notes,
               no_show_sms_sent, review_request_sent, created_at)

services      (id, business_id, name, duration_min, price, active,
               external_id, created_at, updated_at)

business_hours(id, business_id, weekday[0-6], open_time, close_time, closed)
closures      (id, business_id, date UNIQUE, reason, created_at)

-- Customers (CRM-lite)
customers     (id, business_id, name, email, phone, notes, tags,
               total_appointments, total_sessions,
               first_seen_at, last_seen_at, created_at, updated_at)

-- Knowledge Base (FTS5)
kb_entries    (id, business_id, question, answer, tags, active, created_at, updated_at)
kb_entries_fts                  -- FTS5 virtual table, synced via triggers

-- Escalations
escalations   (id, business_id, session_id, customer_id, reason,
               status[pending|acknowledged|resolved],
               priority[low|normal|high|urgent],
               notes, notified_at, resolved_at, resolved_by, created_at)

-- Reminders
reminders     (id, appointment_id, type[24h|1h|15m], channel[email|sms],
               scheduled_for, sent_at, status[pending|sent|failed|cancelled],
               error_message, created_at)

-- Voice
voice_calls   (id, business_id, session_id, customer_id, retell_call_id UNIQUE,
               retell_agent_id, direction[inbound|outbound],
               from_number, to_number,
               call_status[registered|ongoing|ended|error|transferred],
               started_at, ended_at, duration_seconds,
               transcript, transcript_json, call_summary, sentiment,
               recording_url, recording_duration_seconds,
               booking_discussed, booking_confirmed, appointment_id,
               transferred, transfer_number, transfer_reason,
               cost_cents, call_intent, call_outcome, action_items,
               caller_message, containment, created_at, updated_at)
               -- NOTE: no is_missed column. Derive: duration_seconds IS NULL
               --   OR duration_seconds=0 OR call_status IN ('error','registered')

voice_settings(business_id PK, retell_agent_id, retell_phone_number,
               voice_id, voice_speed, voice_pitch,
               greeting_message, transfer_message, voicemail_message,
               transfer_enabled, transfer_number, transfer_after_seconds,
               after_hours_enabled, after_hours_message, after_hours_voicemail,
               recording_enabled, transcript_enabled,
               booking_enabled, booking_confirmation_required,
               created_at, updated_at)

-- Widget
widget_settings(business_id PK, enabled, position[bottom-right|bottom-left],
                primary_color, welcome_message, placeholder_text,
                allowed_domains, show_branding, auto_open_delay,
                created_at, updated_at)

-- Third-party OAuth tokens
integrations  (id, business_id, provider_key, status[active|inactive|error],
               access_token, refresh_token, token_expires_at, account_json,
               created_at, updated_at)
               UNIQUE(business_id, provider_key)
```

---

## Environment Variables (.env)

```bash
# Required — core app
OPENAI_API_KEY=sk-...           # AI conversations (GPT-4o-mini)
FLASK_SECRET_KEY=...            # Session encryption (use secrets.token_hex(32))
APP_ENV=development             # Set to 'production' in prod
APP_BASE_URL=http://localhost:5050  # Used to build absolute URLs in emails (verification, reset)

# Voice (Retell + Telnyx)
RETELL_API_KEY=key_...          # Retell AI API key
RETELL_DEFAULT_AGENT_ID=agent_7fe6433627a68c931f05b7ae84
RETELL_LLM_ID=llm_b41019c52636d5321f084e5bdbbb
TELNYX_API_KEY=KEY...           # Telnyx SIP telephony

# SMS (Telnyx — same account as voice, just needs API key)
# TELNYX_API_KEY set above covers SMS too
# TELNYX_PHONE_NUMBER defaults to +442046203253 (set per-business in voice_settings)

# PII encryption (optional but recommended)
ENCRYPTION_KEY=...              # Fernet key — generate: from cryptography.fernet import Fernet; Fernet.generate_key()

# Google Calendar OAuth (code exists, just needs these)
GOOGLE_CLIENT_ID=...
GOOGLE_CLIENT_SECRET=...
GOOGLE_REDIRECT_URI=https://yourdomain.com/integrations/google/callback

# Stripe billing (to be built — billing_bp.py doesn't exist yet)
STRIPE_SECRET_KEY=sk_...
STRIPE_PUBLISHABLE_KEY=pk_...
STRIPE_WEBHOOK_SECRET=whsec_...

# Email (SMTP — used by mailer.py for reminders, verification, password reset)
SMTP_HOST=smtp.postmarkapp.com
SMTP_PORT=587
SMTP_USER=...
SMTP_PASS=...
FROM_EMAIL=hello@locusai.co.uk

# Error monitoring (to be integrated)
SENTRY_DSN=https://...@sentry.io/...
```

---

## Auth Flows

### Self-Service Signup
1. `GET /signup` → `signup.html` (name, email, password, terms note, "Start free trial →")
2. `POST /signup` → validates, creates user with `email_verified=0`, calls `_send_verification_email()`
3. Redirect to `GET /signup/check-email?email=...` → `verify_email_sent.html` (3-step guide)
4. User clicks link → `GET /verify-email/<token>` → marks `email_verified=1`, sets `trial_ends_at`, auto-logs in
5. Redirect to `/onboard` (multi-step business setup wizard)

### Email Verification Token Details
- `_send_verification_email(user_id, email, name)` in `auth_bp.py`
- Generates 32-char hex token, 24-hour expiry
- Invalidates any previous unused tokens for that user before inserting new one
- Email subject: "Verify your LocusAI email address"
- Absolute URL built from `core.settings.APP_BASE_URL`

### Password Reset
1. `GET /forgot-password` → `forgot_password.html` (email field)
2. `POST /forgot-password` → looks up user, generates 32-char hex token (1-hour expiry), sends email
   - Always shows "If that email is registered, you'll receive a reset link" — never reveals if email exists
3. User clicks link → `GET /reset-password/<token>` → validates token not used/expired → `reset_password.html`
4. `POST /reset-password/<token>` → validates, calls `change_password()`, marks `token.used=1`, redirect to login

### Trial Banner (base.html)
- Shown to any logged-in user with `session.user.trial_ends_at` set
- JavaScript calculates days remaining from `trial_ends_at` date
- Turns red/urgent styling when ≤3 days remain
- Has dismiss (×) button and "Upgrade" link (placeholder `href="#"` — Stripe not built yet)
- **IMPORTANT**: Do NOT use `now()` in Jinja2 — `now` is a datetime object injected into templates, not callable

### Login Guard for Unverified Users
- Login route checks `email_verified` column
- Unverified non-admin users → redirected to `/verify-email-pending` after login
- Admin users always bypass verification check
- `session["user"]` always includes `email_verified` and `trial_ends_at`

---

## Voice AI Integration (Telnyx + Retell)

**Phone Number**: +442046203253 (UK)

### Architecture
```
Inbound Call → Telnyx SIP → Retell AI Agent (native LLM) → Response
                   ↓
         FQDN Connection: sip.retellai.com:5060 (TCP)

Optional Custom LLM path:
Retell AI → voice_ws.py WebSocket → core/ai.py → OpenAI → Response
(adds latency — only use for KB integration, caller context, booking)
```

### Retell Configuration
| Setting | Value |
|---------|-------|
| Agent ID | `agent_7fe6433627a68c931f05b7ae84` |
| Agent Name | LocusAI Receptionist |
| LLM ID | `llm_b41019c52636d5321f084e5bdbbb` |
| Voice | `11labs-Dorothy` (British female) |
| Language | en-GB |
| Response Engine | Retell LLM (native) |
| Responsiveness | 1.0 (max) |
| Interruption Sensitivity | 0.8 |
| Backchannels | Enabled (0.7 frequency) |

**Current LLM Prompt** (in `core/voice.py` — dynamic per business):
```
Every call MUST begin with:
"Hello, thanks for calling {biz_name}. Just to let you know, this call may be
recorded for quality purposes. How can I help you today?"

If caller_known is 'true', personalise after the recording notice.
Never skip the recording notice. It must always be the first thing said.
```
**Note**: Call recording consent is MANDATORY in the dynamic prompt — it is a UK/US legal requirement. Never remove it.

**Available British Voices**:
- `11labs-Dorothy` — Female, British (current)
- `11labs-Anthony` — Male, British
- `11labs-Amy` — Female, British

**Old Agent** (deprecated): `agent_19e267112e9474a8f53d3368a4` (used custom WebSocket LLM)

### Telnyx Configuration
| Setting | Value |
|---------|-------|
| Phone Number ID | `2879031589981914356` |
| Phone Number | `+442046203253` |
| FQDN Connection ID | `2882485623761929727` |
| SIP Target | `sip.retellai.com:5060` |
| Transport | TCP |

**Outbound Calls** (credential connection):
- Username: `locusairetell` | Password: `Locus2026Secure` | Termination URI: `sip.telnyx.com`

### Retell API Commands
```bash
# Get current agent config
curl -X GET "https://api.retellai.com/get-agent/agent_7fe6433627a68c931f05b7ae84" \
  -H "Authorization: Bearer $RETELL_API_KEY"

# Update agent settings
curl -X PATCH "https://api.retellai.com/update-agent/agent_7fe6433627a68c931f05b7ae84" \
  -H "Authorization: Bearer $RETELL_API_KEY" -H "Content-Type: application/json" \
  -d '{"voice_id": "11labs-Dorothy", "responsiveness": 1.0}'

# Update LLM prompt
curl -X PATCH "https://api.retellai.com/update-retell-llm/llm_b41019c52636d5321f084e5bdbbb" \
  -H "Authorization: Bearer $RETELL_API_KEY" -H "Content-Type: application/json" \
  -d '{"general_prompt": "Your new prompt here..."}'

# List recent calls
curl -X POST "https://api.retellai.com/v2/list-calls" \
  -H "Authorization: Bearer $RETELL_API_KEY" -H "Content-Type: application/json" \
  -d '{"limit": 5}'

# Assign agent to phone number
curl -X PATCH "https://api.retellai.com/update-phone-number/+442046203253" \
  -H "Authorization: Bearer $RETELL_API_KEY" -H "Content-Type: application/json" \
  -d '{"inbound_agent_id": "agent_7fe6433627a68c931f05b7ae84"}'
```

### Telnyx API Commands
```bash
curl -X GET "https://api.telnyx.com/v2/phone_numbers" -H "Authorization: Bearer $TELNYX_API_KEY"
curl -X GET "https://api.telnyx.com/v2/fqdn_connections/2882485623761929727" -H "Authorization: Bearer $TELNYX_API_KEY"
```

### Custom LLM Mode (Optional — adds latency)
1. Start WebSocket server: `.venv/bin/python voice_ws.py`
2. Expose via tunnel: `cloudflared tunnel --url http://localhost:8080`
3. Update agent to use `custom-llm` with the tunnel URL

### Voice Troubleshooting
- **Not connecting**: Check Telnyx FQDN → `sip.retellai.com:5060` (TCP), verify agent assignment
- **No speech**: If custom LLM, ensure WebSocket + tunnel active; check `disconnection_reason` in call logs
- **Slow responses**: Switch to native Retell LLM; check responsiveness=1.0
- **Robotic**: Try different ElevenLabs voices; enable backchannels; shorten prompt responses

---

## Key Flows

### Booking Confirmation (Widget Chat)
1. AI detects booking intent → outputs `<BOOKING>{"name":"...","phone":"...","service":"...","slot":"..."}</BOOKING>`
2. `extract_pending_booking()` parses tag → stores in memory with 32-char token, 5-min expiry
3. Widget shows confirmation card (name, service, time, price)
4. User clicks Confirm → `POST /api/widget/booking/confirm` → `confirm_pending_booking(token)` → DB
5. User clicks Cancel → token discarded, no DB write

### Sentiment & Escalation (Live in Widget)
- `analyze_sentiment(text, history)` called on every chat message in `widget_bp.py`
- Returns `SentimentResult` with `triggers_escalation` flag
- Triggers: "speak to human", `frustration_score > 0.7`, complaint + negative indicators, 3+ failed attempts
- If triggered and session not already escalated: `handle_escalation()` → creates escalation record + sends email + sets `sessions.escalated=1`
- Response includes `escalated: true` for widget to show handoff UI

### KB RAG (AI Knowledge Injection)
- `_kb_snippets(business_id, query, limit=3)` in `core/ai.py` runs FTS5 search
- Injects top-3 Q&A pairs into system prompt before OpenAI call
- Schema uses `question`/`answer` keys (NOT `title`/`content` — this was a bug, now fixed)

### Caller Recognition (Voice)
- Retell fires `inbound_dynamic_variables_webhook_url` → `/api/voice/call-setup`
- Endpoint looks up caller's phone number against `customers` table
- Returns caller name, appointment history to inject into Retell agent's dynamic variables
- Agent can then greet: "Hi Sarah, calling about your appointment?"

### Post-Call AI Analysis (Automatic)
- Retell fires `call_analyzed` webhook → `voice_bp.py`
- Runs GPT-4o-mini on transcript: extracts `call_intent`, `call_outcome`, `call_summary`, `containment`, `sentiment`, `action_items`
- Updates `voice_calls` record with all AI-extracted fields

### Background Automation Workers (3 threads in Flask process)
- `_background_call_sync` — syncs Retell call logs to `voice_calls` table
- `_background_reminder_worker` — dispatches appointment reminders (24h, 1h, 15m before)
- `_background_appointment_automation` — no-show detection + review request SMS
- WARNING: These are daemon threads. They crash silently, die on Flask restart, and don't auto-recover.

### Widget API (Public — requires X-Tenant-Key header)
```
POST /api/widget/session          → create session, get welcome message
POST /api/widget/chat             → send message, get AI reply + optional pending_booking + optional escalated:true
POST /api/widget/booking/confirm  → confirm pending booking with token
POST /api/widget/booking/cancel   → cancel pending booking
```

### Embedding the Widget (Customer-Facing)
```html
<script src="https://yourdomain.com/static/widget.js"
  data-tenant-key="YOUR_TENANT_KEY"
  data-position="bottom-right">
</script>
```
Tenant key is in `businesses.tenant_key` — shown in the Dashboard integrations section.

---

## Known Gotchas / Bugs Fixed

- **`daily_trend.values` in Jinja2**: Jinja2 resolves `dict.attr` via `getattr` first, then `getitem`. So `daily_trend.values` returns the dict's built-in `.values()` method, NOT the key `"values"`. The key in `analytics_bp.py` was renamed to `"amounts"` to avoid this. Never name dict keys the same as Python built-in method names when passing to Jinja2.
- **`voice_calls.is_missed`**: This column does NOT exist. Derive "missed" as: `duration_seconds IS NULL OR duration_seconds = 0 OR call_status IN ('error','registered')`.
- **`now()` in base.html**: `now` is a datetime object injected into Jinja2 context, NOT a callable. Never write `now()`. Date math for the trial banner is done in JavaScript.
- **`url_for('voice.voice_dashboard')`**: Wrong — the voice dashboard is registered directly on `app`, not on a blueprint. Use `url_for('voice_dashboard')`.

---

## Security Features

- **Account Lockout**: 5 failed logins → 15-min lockout (per email + IP)
- **CSRF**: All forms protected via `core/csrf.py`
- **Rate Limiting**: Widget API 30 req/60s per tenant (in-process dict — replace with Redis for prod)
- **PII Encryption**: Fernet AES-128, `enc:` prefix on stored fields
- **Input Validation**: Email, phone, name, slug, redirect URL, password via `core/validators.py`
- **Webhook Verification**: HMAC signatures, Telnyx, Stripe
- **Authorization**: `user_can_access_business()` enforced on all business-scoped routes
- **Password hashing**: bcrypt/pbkdf2 via Flask's `generate_password_hash`
- **Email verification**: unverified users blocked from dashboard (admins exempt)
- **Password reset tokens**: single-use, 1-hour expiry, old tokens invalidated on new request
- **Session fixation protection**: `_regenerate_session()` called on every successful login

---

## Test Suite (563 tests)

| File | Tests | Coverage |
|------|-------|----------|
| test_validators.py | 95 | Input validation, CSV escaping |
| test_security.py | 61 | PII masking, webhooks, rate limiting |
| test_sentiment.py | 46 | Sentiment analysis, intent detection |
| test_sms.py | 27 | Telnyx SMS integration |
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
| test_booking.py | 1 | Booking commit basic test |

```bash
.venv/bin/python -m pytest tests/ -v                     # All 580
.venv/bin/python -m pytest tests/test_sentiment.py -v    # Specific file
.venv/bin/python -m pytest tests/ -k "test_widget" -v    # Filter by name
```

---

## Current State (Apr 2026)

### What's Working ✅
- Rebranding complete: AxisAI → LocusAI (all references updated)
- Test suite: 563 tests passing
- Voice AI: Telnyx SIP + Retell native LLM live (+442046203253)
- Caller recognition: `/api/voice/call-setup` dynamic variable injection
- Post-call AI analysis: intent, outcome, sentiment, containment from transcript
- **Call recording consent**: mandatory in every Retell dynamic prompt (`core/voice.py`)
- Chat Widget: embeddable with booking confirmation flow + real-time sentiment escalation
- SMS: Telnyx integration (missed call SMS, no-show SMS, review request SMS) — needs TELNYX_API_KEY (same account as voice)
- Security: lockout, Fernet encryption, rate limiting, CSRF, webhook verification
- Premium UI: Linear/Stripe-inspired design system (locus.css) — consistent across ALL pages
- Multi-step onboarding wizard: 8 industry templates (Salon, Medical, Auto, Fitness, Restaurant, Legal, Cleaning)
- KB CSV bulk import: paste CSV in modal at /kb
- Analytics: revenue projection + voice call analytics + charts (all 500 errors fixed)
- Search: cross-entity (businesses, appointments, customers, KB)
- Customer detail: voice call history tab with intent/sentiment/summary
- Sentiment: real-time escalation in widget chat endpoint
- KB RAG: fixed question/answer field mapping in `_kb_snippets`
- Google Calendar: full OAuth2 flow + two-way sync built (`core/google_calendar.py`) — needs GOOGLE_* env vars
- Voice settings modal: editable voice_id, greeting, transfer, after-hours, recording
- User management: /users (admin only) — create, delete, change password, assign businesses
- Automation workers: reminder dispatch, no-show detection, review requests (background threads)
- Appointment automation: no-show SMS + review request SMS via background worker
- **Password reset**: full working flow — `/forgot-password` → token email → `/reset-password/<token>`
- **Self-service signup**: `/signup` → email verification → 14-day trial → onboarding wizard
- **Email verification**: token-based (24h expiry), resend available, unverified users blocked from dashboard
- **Trial banner**: in `base.html`, shows days remaining, turns red at ≤3 days
- **Privacy Policy**: `/privacy` — UK GDPR-compliant working draft (needs solicitor review)
- **Terms of Service**: `/terms` — working draft (needs solicitor review)

### Known Issues / Needs Work ⚠️
- Voice latency: response time too slow for natural conversation (target: <1s)
- Voice naturalness: Dorothy voice still sounds robotic in some scenarios
- Background workers: daemon threads crash silently, no auto-restart
- No billing: Stripe completely absent — zero code exists. "Upgrade" link in trial banner goes to `href="#"`
- No public website: zero public presence. `/privacy` and `/terms` exist but no homepage.
- No cookie consent banner: UK GDPR violation (can use CookieYes free tier in 30 min)
- Legal docs are working drafts: Privacy Policy and Terms need real solicitor review before public launch
- Tailwind CDN: loaded at runtime in base.html — must be removed for production
- Google Calendar: code done but GOOGLE_CLIENT_ID/SECRET not configured
- No Spanish/bilingual support
- Error pages (404/500): extend auth-required base — broken for logged-out users

---

## Strategy: Wedge → Expand → Platform

**Year 1 — THE WEDGE**: Best AI Receptionist on the market. Period.
- Caller recognition ("Hi Sarah!")
- Real-time availability checking
- Multi-channel: Voice + SMS + Web Chat
- Calendar integrations (Google, Outlook, Calendly, Acuity, iCal)
- Dead-simple setup (10 minutes)
- Multi-language (Spanish priority)

**Year 2 — THE HOOK**: Strategic integrations + optional native features
- Offer LocusAI scheduling that "works better with the AI"
- Offer lightweight CRM that "tracks everyone who calls"
- Always integrate first, offer native second

**Year 3 — THE PLATFORM**: Full business OS for those who've opted in
- Switching cost now works in our favor
- We've earned the right to be their platform

**What we say NO to in Year 1**: payment processor, complex staff scheduling, inventory, marketing automation, mobile app, multi-location, enterprise features.

### Year 1 Priorities (Ranked)
1. Incredible AI Voice Receptionist (caller recognition, natural conversation)
2. Multi-Channel Excellence (Voice + SMS + Widget)
3. Calendar Integrations (Google, Outlook, Calendly, Acuity, iCal)
4. Dead Simple Onboarding (10-minute setup)
5. Multi-Language Support (Spanish first)
6. Industry Templates (Medical, Salon, Auto, Legal)

---

## Development Guidelines

When building new features, always ask:
1. Does this make the AI receptionist better?
2. Does this integrate with tools businesses already use?
3. Can it be set up in under 10 minutes?

If NO to all three → Year 2+ feature.

**Design rule**: All pages — public, auth, and dashboard — must match the same visual design system (locus.css, Inter font, #171717 dark, white cards, same button styles). No exceptions.

---

## Road to Production — Full Gap Audit (Apr 2026)

### TIER 0 — CRITICAL BLOCKERS (Nothing ships without these)

#### Legal (UK GDPR Applies NOW — phone number is +44)
- [x] **Call recording consent** — DONE: mandatory in `core/voice.py` dynamic prompt
- [x] **Privacy Policy** at `/privacy` — DONE: working draft, needs solicitor review before launch
- [x] **Terms of Service** at `/terms` — DONE: working draft, needs solicitor review before launch
- [ ] **Cookie consent banner** — use CookieYes free tier, 30 minutes (DIY)
- [ ] **Data Processing Agreement** template for B2B customers
- [ ] **HIPAA note**: Remove or gate the "Medical / Dental" onboarding template until BAAs exist with OpenAI, Retell, Telnyx.
- [ ] **Solicitor review** of Privacy Policy + Terms before public launch

#### Revenue Infrastructure
- [ ] **Stripe billing** — zero Stripe code exists. Need: `billing_bp.py`, `subscriptions` table, Stripe Checkout flow, webhook handler (`invoice.paid`, `customer.subscription.deleted`), Customer Portal redirect
- [ ] **Subscription tiers**: Starter $49/mo · Professional $149/mo · Business $299/mo · Enterprise custom
- [ ] **Feature gating** by plan tier (conversation limits, user limits, integrations)
- [ ] **Trial expiry enforcement** — `trial_ends_at` stored in DB, no enforcement code yet

#### Customer Acquisition
- [x] **Password reset** — DONE: full flow working
- [x] **Self-service signup** — DONE: `/signup` with email verification + 14-day trial
- [x] **Email verification** — DONE: token-based flow
- [ ] **Public marketing homepage** — zero public presence; `/` requires login

#### Production Infrastructure
- [ ] **Gunicorn** as WSGI (replace Flask dev server)
- [ ] **Nginx** reverse proxy (TLS termination, static files, gzip, WebSocket proxying)
- [ ] **SSL/TLS** via Certbot (Let's Encrypt)
- [ ] **Dockerfile + docker-compose**
- [ ] **Process manager** (systemd or supervisord for auto-restart)
- [ ] **Sentry** error monitoring — 5 lines in dashboard.py, free tier = 5K errors/month
- [ ] **Remote database backups** — current backup.sh is local only. Replace with hourly SQLite → S3/Backblaze.
- [ ] **Remove Tailwind CDN** from base.html → compile with `npx tailwindcss`

---

### TIER 1 — HIGH PRIORITY (Week 1-4 post-launch)

#### Dashboard UX Fixes
- [ ] Header: notifications bell showing count of pending escalations
- [ ] Sidebar footer: show user name, not just "Logout"
- [ ] KPI cards: make clickable, linking to their full-list pages
- [ ] Business switcher: raw `<select>` → custom dropdown
- [ ] Form submit buttons: add loading/spinner state
- [ ] Tables: add horizontal scroll on mobile (silent overflow currently)
- [ ] Dashboard greeting: use `user.name` not `email.split('@')[0]`
- [ ] Flash messages: persist until dismissed (not 5s auto-dismiss)
- [ ] Error pages (404/500): must extend standalone base (broken for logged-out users)

#### Features
- [ ] **Appointment reschedule/cancel via AI** — top-3 use case, completely absent
- [ ] **Google Calendar end-to-end** — code done, just needs GOOGLE_CLIENT_ID/SECRET + test
- [ ] **Appointment calendar view** — week/month calendar (every SMB buyer expects this)
- [ ] **In-app onboarding checklist** — new businesses see "0" KPIs; replace with setup checklist
- [ ] **Uptime monitoring** — UptimeRobot free tier watching `/health` every 5 minutes
- [ ] **Email sequences** — welcome, trial ending Day 10/13, payment failed dunning

#### Compliance
- [ ] SMS "STOP" keyword handling in `sms_bp.py` (required by TCPA for US)
- [ ] International data transfers: document SCCs with OpenAI, Retell, Telnyx (UK/EU → US)

---

### TIER 2 — MEDIUM PRIORITY (Month 2-3)

- [ ] Spanish / bilingual AI support
- [ ] Public shareable booking page (`/book/<slug>`)
- [ ] Zapier outbound webhooks → then Zapier app (unlocks 5,000+ apps)
- [ ] Outlook / Microsoft 365 calendar (professional services + medical)
- [ ] Calendly API — UI exists but uses raw JSON textarea, no actual API calls
- [ ] HubSpot CRM — auto-create contact on first call, log activities
- [ ] Voicemail transcription — transcript + audio link via email
- [ ] Redis — replace in-process rate limit dict + improve session scaling
- [ ] Structured JSON logging (replace plain text logs)
- [ ] Industry landing pages: `/ai-receptionist-for-salons`, `/for-medical`, `/for-law-firms`
- [ ] Blog content: comparison posts ("Synthflow vs LocusAI", "Smith.ai vs LocusAI")
- [ ] G2 / Capterra profile with beta user reviews
- [ ] Product Hunt launch
- [ ] Demo phone number — prospects call before signing up

---

### TIER 3 — LONGER TERM (Month 4+)

- [ ] PostgreSQL migration (SQLite fine until ~1,000 daily active users)
- [ ] Celery + Redis for background jobs (replace daemon threads)
- [ ] SOC 2 Type I audit process
- [ ] HIPAA compliance mode (BAAs with all subprocessors)
- [ ] White-label / custom branding
- [ ] Multi-location management
- [ ] Public API + developer documentation
- [ ] Mobile app (React Native)
- [ ] Outbound calling campaigns
- [ ] Staff-specific booking ("I want Maria specifically")
- [ ] iCal feed import/export
- [ ] Square / Acuity scheduling integrations
- [ ] Content Security Policy headers
- [ ] CDN for static assets (widget.js must be fast — it loads on every customer website)

---

## Competitor Benchmarks

| Competitor | Price | Key Advantage Over Us Today |
|---|---|---|
| Synthflow | $29–$1,400/mo | SOC 2 + HIPAA, <100ms latency, 20+ languages, CRM integrations |
| Smith.ai | $97–$292/mo | Live human hybrid, HIPAA, HubSpot/Salesforce, mobile app |
| Bland.ai / Vapi | $0.09/min | Ultra-low latency, 20+ languages, developer API |
| Ruby Receptionist | ~$239/mo | Human + AI hybrid, strong SMB brand trust |

**Our current edges**: Cleaner UI, more affordable, no per-minute pricing, booking confirmation flow, real-time sentiment escalation, CSV KB import, multi-step onboarding, self-service signup, working password reset.

---

## Recommended Pricing

- **Starter** $49/mo — chat widget only, 100 conversations/mo, 1 business
- **Professional** $149/mo — voice + chat + SMS, 500 conversations, 3 users, Google Calendar
- **Business** $299/mo — unlimited conversations, full analytics, 10 users, priority support
- **Enterprise** custom — white-label, custom integrations, SLA, HIPAA BAA

Annual pricing: 2 months free (~16.7% discount).

---

## Key Marketing Messages

- "Never miss a call again — even at 2am"
- "Set up in 10 minutes, not 10 weeks"
- "Works with Google Calendar, Calendly, and more"
- "Sounds human, not robotic" (addresses #1 objection)
- "Your competitor already has this" (FOMO)
- "No per-minute pricing. No surprises."

### Target SEO Keywords (Year 1)
- "AI receptionist for small business" — 3,400/mo searches
- "AI phone answering service" — 2,900/mo
- "AI receptionist for salons" — 720/mo, LOW competition
- "AI answering service for medical office" — 590/mo, LOW competition
- "Synthflow alternative" / "Smith.ai alternative" — HIGH purchase intent
- "AI receptionist UK" — geographic, LOW competition

---

## Next Up (Priority Order)

1. **Stripe billing** — zero code exists. `billing_bp.py` + `subscriptions` table + Checkout flow + webhook (`invoice.paid`, `customer.subscription.deleted`) + Customer Portal. Fix "Upgrade" link in trial banner.
2. **Trial expiry enforcement** — check `trial_ends_at` on dashboard load; restrict access or prompt upgrade when expired
3. **Public marketing homepage** — zero exists; `/` currently requires login; entire public website is greenfield
4. **Cookie consent banner** — CookieYes free tier, 30 minutes (DIY, not a code task)
5. **Solicitor review** of Privacy Policy + Terms — working drafts exist, need real legal review before launch
6. **Production stack** — Gunicorn + Nginx + SSL + Dockerfile + Sentry + remote DB backups
7. **Appointment reschedule/cancel via AI** — top-3 use case, missing
8. **Google Calendar end-to-end** — code done, just needs GOOGLE_CLIENT_ID/SECRET + test run
9. **Dashboard UX fixes** — notifications bell, clickable KPIs, mobile tables, error pages
10. **Appointment calendar view** — week/month grid
11. **Spanish language support**
