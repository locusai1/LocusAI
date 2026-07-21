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
  pending_store.py     # SQLite-backed, cross-worker store for booking/change/voice tokens (replaces per-process dicts — fixes multi-worker booking-confirm failures)
  account.py           # GDPR: export_account_data() (portability) + delete_account() (erasure)
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

tests/                      # 834 tests across 49 files
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

-- Short-lived pending tokens (durable + shared across gunicorn workers)
pending_actions (token PK, kind[booking|change|voice_booking|voice_change],
               business_id, data_json, created_at REAL, expires_at REAL)
               -- Replaces the old per-process dicts in booking.py/voice.py.
               -- pop() is atomic single-use (see core/pending_store.py).
```

---

## Environment Variables (.env)

```bash
# Required — core app
OPENAI_API_KEY=sk-...           # AI conversations (GPT-4o-mini)
FLASK_SECRET_KEY=...            # Session encryption (use secrets.token_hex(32))
APP_ENV=development             # Set to 'production' in prod
APP_BASE_URL=http://localhost:5050  # Used to build absolute URLs in emails (verification, reset)
LOCUSAI_DB_PATH=/data/receptionist.db  # OPTIONAL: SQLite location. Set to a persistent volume in prod (Railway volume) so data survives redeploys. Defaults to repo-local receptionist.db.

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

# Stripe billing (code built — billing_bp.py + core/billing.py; add keys to go live, see BILLING_SETUP.md)
# Also: STRIPE_PRICE_STARTER / STRIPE_PRICE_PROFESSIONAL / STRIPE_PRICE_BUSINESS (price_... IDs)
STRIPE_SECRET_KEY=sk_...
STRIPE_PUBLISHABLE_KEY=pk_...
STRIPE_WEBHOOK_SECRET=whsec_...

# Email (SMTP — used by mailer.py for reminders, verification, password reset)
SMTP_HOST=smtp.postmarkapp.com
SMTP_PORT=587
SMTP_USER=...
SMTP_PASS=...
FROM_EMAIL=hello@locusai.co.uk

# Error monitoring (code wired in dashboard.py — set SENTRY_DSN to activate)
SENTRY_DSN=https://...@sentry.io/...

# Backups (core/backup.py — `python -m core.backup`; local-only unless S3 set)
BACKUP_DIR=backups            # local snapshot dir (point at a volume in prod)
BACKUP_KEEP=14                # how many local snapshots to retain
# BACKUP_S3_BUCKET=...        # optional: also upload off-box (needs boto3)
# BACKUP_S3_PREFIX=locusai-db
# BACKUP_S3_ENDPOINT=...      # optional: S3-compatible (e.g. Backblaze B2)
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
| LLM model | `gpt-4.1` (full) + `model_high_priority` — evolved `gpt-4o-mini` → `gpt-4.1-mini` → **`gpt-4.1`** (Jun 2026; Retell's #1 receptionist pick — fast + reliable tool use, no reasoning latency) |
| Voice | `11labs-Dorothy` (British female) |
| Voice model | `eleven_v3` (`voice_temperature` 1.2) |
| Language | en-GB |
| Response Engine | Retell LLM (native) |
| STT mode | `accurate` (was `fast`) |
| Dynamic pacing | `enable_dynamic_voice_speed` + `enable_dynamic_responsiveness` ON |
| Responsiveness | 1.0 (max) |
| Interruption Sensitivity | 0.8 |
| Backchannels | Enabled + `backchannel_words` (mm-hmm/right/of course/I see/okay) |
| Denoising | `noise-and-background-speech-cancellation` |
| Ambient sound | `call-center` @ 0.3 (subjective — easy to drop) |
| Extras | `boosted_keywords` (booking + salon terms), `fallback_voice_ids:[openai-Amy]` (outage safety) |
| Webhook URL | `https://locusai.co.uk/api/voice/webhook` (was a stale trycloudflare tunnel) |
| **Live published version** | **v6** (agent + LLM both v6; phone number follows latest published — no version pin). Rollback: republish v5 (clean gpt-4.1) or v4 (gpt-4.1-mini). |

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

### Voice Latency & Naturalness Tuning (knob reference — verified vs Retell API, Jun 2026)

Reference for every tuning knob (field names + valid values). **The recommended settings here are already applied on live v6** — this section stays as the map for future changes. Pulled from current Retell API docs — see `docs.retellai.com/api-references/update-agent`, `.../update-retell-llm`, `.../build/transcription-mode`.

**On the LLM (`update-retell-llm` → `llm_b41019c52636d5321f084e5bdbbb`):**
- `model` — accepts `gpt-4.1` | `gpt-4.1-mini` | `gpt-4.1-nano` | `gpt-5`…`gpt-5.5` | `claude-4.5-sonnet` | `claude-4.6-sonnet` | `claude-4.5-haiku` | `gemini-3.0-flash` | etc. **Retell's 2026 production recommendation is `gpt-4.1`** (low latency + reliable tool use; GPT-5 variants are *slower* due to reasoning). **Live = `gpt-4.1`.**
- `model_high_priority` (bool, default false) — `true` for "dedicated resource, lower & more consistent latency". **Live = `true`.**

**On the agent (`update-agent` → `agent_7fe6433627a68c931f05b7ae84`):**
- `voice_model` (enum) — engine selector, separate from `voice_id`. Expressiveness↑: `eleven_v3` (newest, fixes "robotic", slightly higher latency). Latency↑: `eleven_flash_v2_5`. Others: `eleven_turbo_v2_5`, `sonic-3`/`sonic-3.5` (Cartesia, emotion control), `speech-02-turbo` (MiniMax). **Live = `eleven_v3`.** Open A/B if latency bites: `eleven_v3` vs `eleven_flash_v2_5` on a recording.
- `voice_temperature` (0–2, default 1) — higher = more variant/expressive (counteracts robotic flatness). **Live = 1.2.**
- `voice_speed` (0.5–2, default 1).
- `enable_dynamic_voice_speed` (bool, default false) — agent paces to caller's speech rate. **Live = on.**
- `enable_dynamic_responsiveness` (bool, default false) — agent adapts response speed to caller turn-taking. **Live = on.**
- `responsiveness` (0–1, default 1) — **live = 1.0 (maxed).**
- `interruption_sensitivity` (0–1, default 1) — **live = 0.8.**
- `enable_backchannel` (bool) + `backchannel_frequency` (0–1, default 0.8) + `backchannel_words` (array). **Live: on, custom words (mm-hmm/right/of course/I see/okay).**
- `denoising_mode` — **live = `noise-and-background-speech-cancellation`.**
- `ambient_sound` (enum) + `ambient_sound_volume` — **live = `call-center` @ 0.3** (subjective; drop if it distracts).
- `boosted_keywords` (array) — booking + salon terms, improves STT on domain words. **Live: set.**
- `fallback_voice_ids` (array) — **live = `[openai-Amy]`** (used if primary TTS provider has an outage).
- `stt_mode` (enum) — `fast` (lowest latency) | `accurate` (~+200ms, fewer mis-hears) | `custom` (needs `custom_stt_config`: `provider` azure/deepgram/soniox, `endpointing_ms`). **Live = `accurate`** (chose accuracy over the ~200ms; revisit if latency is the bigger complaint).
- ⚠️ `normalize_for_speech` — attempted but **did NOT persist** (reads back `None` live). Skip / re-test before relying on it.

⚠️ **`update-agent` edits the agent's *draft* version** — you must **publish** the agent (dashboard or API) for changes to hit live calls.
⚠️ **`voice_id` list lives in the Retell dashboard** (API only says "find in Dashboard"). `voice_model` picks the engine; to use a v3 Dorothy you copy the matching `voice_id` from the dashboard. Current `11labs-Dorothy` is the older naming.

**Remaining open levers (subjective — need Paulo's ear on a test call):** keep/kill the `call-center` ambient sound; voice A/B (11labs-Amy / Maren / cartesia-Willa vs Dorothy).

#### ⚠️ Versioning workflow (CRITICAL — learned the hard way, Jun 2026)

Publishing an agent **locks that version**. After publish, `PATCH /update-agent` and `PATCH /update-retell-llm` return `"Cannot update published agent/LLM"` (HTTP 400/422), and `publish-agent-version` does **NOT** auto-create a new draft (it just re-publishes in place). To make ANY further change you must spin a new draft first:

```bash
RK=$(grep -E '^RETELL_API_KEY=' .env | cut -d= -f2- | tr -d '"'\'' \r')
AG=agent_7fe6433627a68c931f05b7ae84
# 1. New draft from the current live version (also creates a matching Retell-LLM draft):
NEWV=$(curl -s -X POST "https://api.retellai.com/create-agent-version/$AG" \
  -H "Authorization: Bearer $RK" -H "Content-Type: application/json" \
  -d '{"base_version": 6}' | python3 -c "import sys,json;print(json.load(sys.stdin)['version'])")   # base_version = current live (6)
# 2. Edit the draft (LLM edits target the new draft automatically — no separate LLM-version endpoint exists):
curl -s -X PATCH "https://api.retellai.com/update-retell-llm/llm_b41019c52636d5321f084e5bdbbb" \
  -H "Authorization: Bearer $RK" -H "Content-Type: application/json" -d '{"model":"gpt-4.1-mini"}'
curl -s -X PATCH "https://api.retellai.com/update-agent/$AG" \
  -H "Authorization: Bearer $RK" -H "Content-Type: application/json" -d '{"stt_mode":"accurate"}'
# 3. Go live:
curl -s -X POST "https://api.retellai.com/publish-agent-version/$AG" \
  -H "Authorization: Bearer $RK" -H "Content-Type: application/json" -d "{\"version\": $NEWV}"
```
Notes: `create-agent-version` (`base_version` int, required) returns the new draft version + bumps the linked LLM to a new draft. No `create-retell-llm-version` endpoint exists — LLM versioning rides on the agent's. The phone number (`+442046203253`) has **no version pin**, so it always serves the latest *published* version. The agent ran fine **unpublished** before Jun 2026 (the draft served calls) — publishing is the cleaner pattern but introduced this lock.

### Telnyx Configuration
| Setting | Value |
|---------|-------|
| Phone Number ID | `2879031589981914356` |
| Phone Number | `+442046203253` |
| FQDN Connection ID | `2882485623761929727` |
| SIP Target | `sip.retellai.com:5060` |
| Transport | TCP |

**Outbound Calls** (credential connection):
- Username: `locusairetell` | Password: _(in Telnyx dashboard / `TELNYX_SIP_PASSWORD` env — NOT stored in this repo)_ | Termination URI: `sip.telnyx.com`
- ⚠️ The old password was previously committed to this file in git history — **rotate it in the Telnyx portal** and keep the new one out of the repo.

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
- These run under `core/workers.py` supervision: each catches all exceptions, retries with backoff, and records a heartbeat (see `/health/ready`). They still die on Flask restart (re-spawned at startup).

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

## Deployment (Railway)

- **Python is pinned to 3.11** via `.python-version` + `runtime.txt`. Do NOT remove these — nixpacks otherwise uses its default (newer) Python, where a pinned wheel fails to build and the Railway build breaks (site stays up on the last good deploy, but new deploys fail). Symptom: build-failure emails while local `pip install` + `gunicorn dashboard:app` both pass.
- Start command: `Procfile` → `gunicorn dashboard:app --workers 2 --timeout 120`.
- **Admin bootstrap**: set `ADMIN_EMAIL` + `ADMIN_PASSWORD` (≥8 chars) in Railway Variables and redeploy — `core/bootstrap.py:ensure_admin()` creates that admin on startup if it's missing (idempotent; never overwrites an existing account). The intended way to (re)create the production admin without CLI access. Until a persistent volume is attached, this also re-creates the admin after each ephemeral-disk wipe.

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

## Test Suite (834 tests across 49 files)

| File | Tests | Coverage |
|------|-------|----------|
| test_validators.py | 95 | Input validation, CSV escaping |
| test_security.py | 58 | PII masking, webhooks, rate limiting |
| test_sentiment.py | 46 | Sentiment analysis, intent detection |
| test_voice.py | 42 | Voice call management |
| test_encryption.py | 39 | Field encryption, token hashing |
| test_booking_confirmation.py | 32 | Token flow, confirm/cancel |
| test_db.py | 29 | Database operations |
| test_auth.py | 28 | Login, lockout, user management |
| test_sms.py | 27 | Telnyx SMS integration |
| test_widget_api.py | 25 | Widget endpoints, CORS |
| test_circuit_breaker.py | 25 | States, decorators, resilience |
| test_ics.py | 23 | iCalendar generation |
| test_observability.py | 22 | Metrics collection |
| test_ai.py | 22 | AI conversation, prompts |
| test_billing.py | 20 | Stripe checkout, webhooks, plans |
| test_reminders.py | 19 | Reminder scheduling |
| test_escalation.py | 18 | Human handoff |
| test_reschedule_cancel.py | 16 | AI cancel/reschedule token flow |
| test_webhooks.py | 15 | Outbound event bus, HMAC, SSRF guard |
| test_followups.py | 12 | Post-appointment follow-ups |
| test_authz.py | 12 | Authorization checks |
| test_semantic_kb.py | 11 | Embedding search, fallback chain |
| test_limits.py | 11 | Plan feature gating / quotas |
| test_compliance.py | 11 | Consent, retention, compliance rules |
| test_push.py | 10 | Web push notifications |
| test_kb_suggestions.py | 10 | AI KB gap suggestions |
| test_sms_optout.py | 9 | STOP/START opt-out |
| test_demo.py | 9 | Instant demo flow |
| test_call_recovery.py | 9 | Missed-call recovery |
| test_ai_quality.py | 9 | AI response quality checks |
| test_kb_ingest.py | 8 | KB CSV bulk import |
| test_trial.py | 7 | Trial expiry enforcement |
| test_public_booking.py | 7 | `/book/<slug>` race-safe booking |
| test_kb_autolearn.py | 7 | KB auto-learn tick |
| test_calendar_feed.py | 7 | Per-business iCal feed |
| test_value_report.py | 6 | Value/ROI report |
| test_insights.py | 6 | Analytics insights |
| test_digest.py | 6 | Weekly AI digest email |
| test_workers.py | 5 | Supervised background workers |
| test_onboarding.py | 5 | In-app onboarding checklist |
| test_handoff.py | 5 | Escalation handoff |
| test_calendar.py | 5 | Appointment calendar view |
| test_bootstrap.py | 4 | Admin bootstrap on startup |
| test_backup.py | 4 | DB snapshot + rotate |
| test_sms_reschedule.py | 3 | SMS reschedule/cancel |
| test_error_pages.py | 3 | 404/500 for logged-out users |
| test_booking.py | 1 | Booking commit basic test |

```bash
.venv/bin/python -m pytest tests/ -v                     # All 834
.venv/bin/python -m pytest tests/test_sentiment.py -v    # Specific file
.venv/bin/python -m pytest tests/ -k "test_widget" -v    # Filter by name
```

---

## Current State (Jul 2026)

### What's Working ✅
- **LIVE IN PRODUCTION**: deployed on Railway, served by Gunicorn (`Procfile`: `gunicorn dashboard:app --workers 2`)
  - Railway URL: `https://luminous-gratitude-production-812f.up.railway.app`
  - Custom domain: `https://locusai.co.uk` (live, HTTPS, serving the marketing homepage)
  - `/`, `/login`, `/health` all return 200 in prod
- **Public marketing homepage**: `/` serves `home.html` (public; redirects logged-in users to dashboard). Public layout in `public_base.html`.
- **Cookie consent banner**: present in `public_base.html` (also referenced in `privacy.html`)
- Pricing displayed in **£ (GBP)** across `home.html`, `onboard.html`, `services.html`
- Rebranding complete: AxisAI → LocusAI (all references updated)
- Test suite: **834 tests passing** (verified Jul 2026)
- **Launch-hardening (Jul 2026)** — done this session:
  - **Booking-confirm concurrency fix**: pending booking/change/voice tokens moved from per-process dicts to a shared SQLite store (`core/pending_store.py`, `pending_actions` table) — they no longer vanish across `gunicorn --workers 2`. `pop()` is atomic single-use (no double-book on replay).
  - **Multi-tenant call/SMS routing fix**: `_get_business_by_phone` (voice + SMS) no longer falls back to "first active business" for an unknown number — it only auto-resolves when exactly ONE active business exists; otherwise returns None and the caller refuses (no cross-tenant misroute/leak). Voice `_fn_context` + `call-setup` handle None gracefully.
  - **GDPR self-serve** (`core/account.py`, `/account`): data export (JSON, portability) + account deletion (erasure; sole-owner businesses fully purged, shared ones preserved), password-confirmed. Linked from sidebar + Privacy Policy.
  - **Self-hosted fonts**: Inter + Space Grotesk served locally (`static/fonts/*.woff2`, `static/fonts.css`) — removed Google Fonts from all templates (UK GDPR IP-leak) and dropped the font hosts from CSP.
  - **SEO/social**: OG + Twitter cards + canonical in `public_base.html`, branded `static/og-image.png`, `favicon.ico` + apple-touch + png favicons, `/robots.txt` + `/sitemap.xml` routes.
  - **Email deliverability**: `core/mailer.py` now sets Date + Message-ID; automated mail (reminders/digest/alerts) gets `List-Unsubscribe` (+ one-click) and `Auto-Submitted`. Fixed a latent `send_email(to=...)` kwarg bug in reminders.
  - **ProxyFix** added (correct https absolute URLs behind Railway's proxy — canonical/OG/email links). Loose deps pinned. `.env.example` added. SIP password redacted from this file (rotate it).
- **In-app onboarding checklist**: dashboard shows setup progress (`core/onboarding.py`) until complete
- **Public self-serve booking page**: `/book/<slug>` — services + live availability, race-safe booking, reminders (`public_booking_bp.py`)
- **Outbound webhooks / event bus**: `core/webhooks.py` + `webhooks_bp.py` — HMAC-signed, SSRF-safe, retried deliveries for booking/appointment/escalation events; `/integrations/webhooks` UI (Zapier/Make/n8n-ready)
- **Weekly AI digest email**: `core/digest.py` — per-week performance summary to owners (supervised worker, opt-out, deduped)
- **AI knowledge-gap suggestions**: `core/kb_suggestions.py` — GPT proposes KB entries from recent customer questions; "✨ Suggest from conversations" on `/kb`
- **DB backup module**: `core/backup.py` — `python -m core.backup` (snapshot + rotate + optional S3/Backblaze)
- **AI reschedule/cancel** of existing appointments (web chat): `<CANCEL>`/`<RESCHEDULE>` token flow in `core/booking.py`, widget confirm card, `/api/widget/change/*` endpoints
- **Feature gating by plan** (`core/limits.py`): conversation quota, channel + user gates; trial/no-sub = ungated; widget `/session` returns 402 when a paid tier is over cap
- **Supervised background workers** (`core/workers.py`): auto-restart + exponential backoff + heartbeats on `/health/ready` (no more silent death)
- **Appointment calendar view**: `/appointments/calendar` month + week grid, colour-coded by status
- **Stripe billing** (code complete; needs keys): `core/billing.py` + `billing_bp.py` + `subscriptions` table. Plans £49/£149/£299, Checkout, Customer Portal, signature-verified webhook at `/api/billing/webhook`. Degrades gracefully w/o keys. See `BILLING_SETUP.md`. Trial-banner Upgrade → `/billing`.
- **Trial expiry enforcement**: `_enforce_trial` before_request redirects expired trial users (no active sub) to `/billing`; admins + paid users exempt
- **SMS STOP/START opt-out** (TCPA): `sms_opt_outs` table; `send_sms` suppresses opted-out numbers; webhook records/clears opt-out
- **Sentry** error monitoring: env-gated (`SENTRY_DSN`), no-op when unset
- **DB path configurable**: `LOCUSAI_DB_PATH` env (point at a persistent volume in prod)
- **Dashboard UX**: name-based greeting, sidebar user identity, notifications bell w/ escalation count, clickable KPI cards, mobile table scroll, form loading states
- **Homepage**: hero live-call demo + depth, FAQ section (verified responsive)
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
- **Semantic KB search** (`core/semantic_kb.py`): OpenAI `text-embedding-3-small` embeddings in `kb_embeddings` table, cosine-ranked (MIN_SCORE 0.30), wired transparently into `core.kb.search_kb` (semantic → FTS → LIKE). Chat/voice/widget all benefit; degrades to [] without key/embeddings. Auto-indexes on KB add/edit + daily backfill.
- **Instant "try it" demo**: live AI receptionist generated from any website URL, no signup (`test_demo.py`)
- **Per-business iCal calendar feed**: integration-free calendar subscription (`test_calendar_feed.py`)
- **Demo seed data**: rich demo business (Aurora Hair & Beauty) via seed script
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
- Background workers: now supervised (`core/workers.py`) — auto-restart + backoff + heartbeats on `/health/ready`
- Billing code complete but NOT live: needs real Stripe keys + Price IDs (see `BILLING_SETUP.md`). Until then `/billing` shows "not configured".
- Legal docs are working drafts: Privacy Policy and Terms need real solicitor review before public launch
- Tailwind CDN: loaded at runtime in base.html — must be removed for production
- ⚠️ Railway ephemeral disk: SQLite data lost on redeploy unless `LOCUSAI_DB_PATH` points at a mounted volume (code now supports it — just needs the volume + env var set)
- Deploy hardening: Sentry code wired (needs `SENTRY_DSN`); remote DB backups still local-only
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
- [x] **Cookie consent banner** — DONE: present in `public_base.html`
- [ ] **Data Processing Agreement** template for B2B customers
- [ ] **HIPAA note**: Remove or gate the "Medical / Dental" onboarding template until BAAs exist with OpenAI, Retell, Telnyx.
- [ ] **Solicitor review** of Privacy Policy + Terms before public launch

#### Revenue Infrastructure
- [x] **Stripe billing** — DONE (code): `billing_bp.py`, `core/billing.py`, `subscriptions` table, Checkout, webhook (`/api/billing/webhook`), Customer Portal. Needs keys to go live (`BILLING_SETUP.md`).
- [x] **Subscription tiers**: Starter £49 · Professional £149 · Business £299 (in `core/billing.py → PLANS`)
- [~] **Feature gating** by plan tier — limits defined in `PLANS`; per-feature enforcement not yet wired beyond trial gate
- [x] **Trial expiry enforcement** — DONE: `_enforce_trial` before_request redirects expired-trial users (no active sub) to `/billing`

#### Customer Acquisition
- [x] **Password reset** — DONE: full flow working
- [x] **Self-service signup** — DONE: `/signup` with email verification + 14-day trial
- [x] **Email verification** — DONE: token-based flow
- [x] **Public marketing homepage** — DONE: `/` serves `home.html` publicly (`public_base.html` layout)

#### Production Infrastructure
- [x] **Gunicorn** as WSGI — DONE: `Procfile` runs `gunicorn dashboard:app --workers 2 --timeout 120`
- [x] **Hosting + SSL/TLS** — DONE: deployed on Railway w/ custom domain `locusai.co.uk` over HTTPS (Railway-managed TLS; no Nginx/Certbot needed)
- [x] **Process manager** — DONE: Railway restarts the service (no systemd/supervisord needed on Railway)
- [ ] **Nginx** — N/A on Railway (their edge handles TLS/static/gzip). Revisit only if self-hosting.
- [ ] **Dockerfile** — optional; Railway auto-builds from `requirements.txt` + `Procfile` (nixpacks). Add only if build needs pinning.
- [ ] **Persistent DB on Railway** — ⚠️ SQLite is on ephemeral disk; data lost on redeploy. Attach a Railway volume or move to Railway Postgres BEFORE real users.
- [x] **Sentry** error monitoring — DONE (code): env-gated in dashboard.py; set `SENTRY_DSN` to activate (free tier = 5K errors/month)
- [x] **Remote database backups** — DONE: `core/backup.py` (`python -m core.backup`) — snapshot + rotate + optional S3/Backblaze. Schedule via cron/Railway.
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
- [x] Error pages (404/500): DONE — extend standalone `public_base.html`, render for logged-out users (tested)

#### Features
- [x] **Appointment reschedule/cancel via AI** — DONE for web chat + SMS (`<CANCEL>`/`<RESCHEDULE>`); native-Retell voice still to extend
- [ ] **Google Calendar end-to-end** — code done, just needs GOOGLE_CLIENT_ID/SECRET + test
- [x] **Appointment calendar view** — DONE: `/appointments/calendar` month + week grid
- [ ] **In-app onboarding checklist** — new businesses see "0" KPIs; replace with setup checklist
- [ ] **Uptime monitoring** — UptimeRobot free tier watching `/health` every 5 minutes
- [ ] **Email sequences** — welcome, trial ending Day 10/13, payment failed dunning

#### Compliance
- [x] SMS "STOP" keyword handling in `sms_bp.py` — DONE: opt-out recorded, sends suppressed, START re-subscribes
- [ ] International data transfers: document SCCs with OpenAI, Retell, Telnyx (UK/EU → US)

---

### TIER 2 — MEDIUM PRIORITY (Month 2-3)

- [ ] Spanish / bilingual AI support
- [x] Public shareable booking page (`/book/<slug>`) — DONE (`public_booking_bp.py`)
- [x] Zapier outbound webhooks — DONE: signed event bus (`core/webhooks.py`), `/integrations/webhooks`
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

> Done since last audit: public homepage, cookie consent, Railway+Gunicorn+HTTPS deploy. Done THIS session (code, tests passing): Stripe billing, trial-expiry enforcement, SMS STOP/START opt-out, Sentry (env-gated), env-configurable DB path, dashboard UX polish, error-page fix, homepage elevation.

**Owner action items (need your external accounts — code is ready):**
- A. **Add Stripe keys** to go live on billing — follow `BILLING_SETUP.md` (~15 min in Stripe dashboard)
- B. **Attach a Railway volume** + set `LOCUSAI_DB_PATH=/data/receptionist.db` so data survives redeploys (HIGH priority before real users)
- C. **Set `SENTRY_DSN`** in Railway to turn on error monitoring (free)

> Also done this session: AI reschedule/cancel (web chat), feature gating by plan, supervised workers, appointment calendar view, billing security review.

**Next build priorities:**
1. **Google Calendar end-to-end** — code done, needs GOOGLE_CLIENT_ID/SECRET + test run
2. **Reschedule/cancel for voice + SMS** — web chat done; extend to the other channels
3. **Remove Tailwind CDN** → compile with `npx tailwindcss` for prod
4. **Remote DB backups** (S3/Backblaze) — current backup.sh is local only
5. **Spanish language support**
6. **Solicitor review** of Privacy Policy + Terms before public launch
