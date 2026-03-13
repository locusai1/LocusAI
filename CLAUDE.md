# LocusAI

AI receptionist SaaS for SMBs - handles customer chat, appointment booking, sentiment analysis, and human escalation.

## Quick Start

```bash
cd /Users/paulomartinez/LocusAI
.venv/bin/python -m flask --app dashboard run --host=0.0.0.0 --port=5050

# http://127.0.0.1:5050 | Login: admin@locusai.local / admin

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
tests/                 # 580 tests across 18 files
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
RETELL_API_KEY=key_...          # Voice AI (Retell)
TELNYX_API_KEY=KEY...           # Voice telephony (Telnyx SIP)
ENCRYPTION_KEY=...              # PII field encryption (optional)
TWILIO_ACCOUNT_SID=...          # SMS (optional)
TWILIO_AUTH_TOKEN=...
TWILIO_PHONE_NUMBER=...
```

## Voice AI Integration (Telnyx + Retell)

**Phone Number**: +442046203253 (UK)

### Architecture
```
Inbound Call → Telnyx SIP → Retell AI → Response
                   ↓
         FQDN Connection: sip.retellai.com:5060 (TCP)
```

### Retell Configuration
| Setting | Value |
|---------|-------|
| Agent ID | `agent_7fe6433627a68c931f05b7ae84` |
| Agent Name | LocusAI Receptionist |
| LLM ID | `llm_b41019c52636d5321f084e5bdbbb` |
| Voice | `11labs-Dorothy` (British female) |
| Language | en-GB |
| Response Engine | Retell LLM (native, not custom WebSocket) |
| Responsiveness | 1.0 (max) |
| Interruption Sensitivity | 0.8 |
| Backchannels | Enabled (0.7 frequency) |

**Current LLM Prompt**:
```
You are a friendly, professional receptionist for LocusAI. You help callers with
answering questions, booking appointments, and taking messages. Be warm and
conversational - speak like a real person. Keep responses concise (1-2 sentences).
Use British English. If unsure, say so honestly. Always confirm names, times, and
numbers. Start with: Hello, thanks for calling! How can I help you today?
```

**Available British Voices** (for voice_id):
- `11labs-Dorothy` - Female, British (current)
- `11labs-Anthony` - Male, British
- `11labs-Amy` - Female, British

**Old Agent** (deprecated): `agent_19e267112e9474a8f53d3368a4` (used custom WebSocket LLM)

### Telnyx Configuration
| Setting | Value |
|---------|-------|
| Phone Number ID | `2879031589981914356` |
| Phone Number | `+442046203253` |
| FQDN Connection ID | `2882485623761929727` |
| SIP Target | `sip.retellai.com:5060` |
| Transport | TCP |

**For Outbound Calls** (credential connection):
- Username: `locusairetell`
- Password: `Locus2026Secure`
- Termination URI: `sip.telnyx.com`

### Retell API Commands
```bash
# Get current agent config
curl -X GET "https://api.retellai.com/get-agent/agent_7fe6433627a68c931f05b7ae84" \
  -H "Authorization: Bearer $RETELL_API_KEY"

# Update agent settings (voice, responsiveness, etc.)
curl -X PATCH "https://api.retellai.com/update-agent/agent_7fe6433627a68c931f05b7ae84" \
  -H "Authorization: Bearer $RETELL_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"voice_id": "11labs-Dorothy", "responsiveness": 1.0}'

# Update LLM prompt
curl -X PATCH "https://api.retellai.com/update-retell-llm/llm_b41019c52636d5321f084e5bdbbb" \
  -H "Authorization: Bearer $RETELL_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"general_prompt": "Your new prompt here..."}'

# List recent calls (check for errors)
curl -X POST "https://api.retellai.com/v2/list-calls" \
  -H "Authorization: Bearer $RETELL_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"limit": 5}'

# List available voices
curl -X GET "https://api.retellai.com/list-voices" \
  -H "Authorization: Bearer $RETELL_API_KEY"

# Assign agent to phone number
curl -X PATCH "https://api.retellai.com/update-phone-number/+442046203253" \
  -H "Authorization: Bearer $RETELL_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"inbound_agent_id": "agent_7fe6433627a68c931f05b7ae84"}'
```

### Telnyx API Commands
```bash
# List phone numbers
curl -X GET "https://api.telnyx.com/v2/phone_numbers" \
  -H "Authorization: Bearer $TELNYX_API_KEY"

# Check FQDN connection
curl -X GET "https://api.telnyx.com/v2/fqdn_connections/2882485623761929727" \
  -H "Authorization: Bearer $TELNYX_API_KEY"
```

### Custom LLM Mode (Optional)
For full control over AI responses (KB access, booking, sentiment), use custom LLM mode:
1. Start WebSocket server: `.venv/bin/python voice_ws.py`
2. Expose via tunnel: `cloudflared tunnel --url http://localhost:8080`
3. Update agent to use custom-llm with the tunnel URL

Note: Custom LLM adds latency. Native Retell LLM is faster but less integrated.

### Troubleshooting Voice Calls

**Call not connecting:**
1. Check Telnyx FQDN points to `sip.retellai.com:5060` (TCP)
2. Verify phone number is assigned to correct agent in Retell
3. Check Retell call logs: `curl -X POST "https://api.retellai.com/v2/list-calls" ...`

**Call connects but no speech:**
1. If using custom LLM: ensure WebSocket server is running and tunnel is active
2. Check `disconnection_reason` in call logs (e.g., `error_llm_websocket_open`)
3. Verify agent's `llm_websocket_url` is reachable

**Slow responses:**
1. Switch from custom-llm to retell-llm (native) - eliminates tunnel latency
2. Increase `responsiveness` to 1.0
3. Check OpenAI API latency if using custom LLM

**Robotic voice:**
1. Try different ElevenLabs voices (Dorothy, Amy, Anthony)
2. Enable backchannels for more natural conversation
3. Keep prompt responses short (1-2 sentences)

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

## Test Suite (580 tests)

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
| test_booking.py | 1 | Booking commit basic test |

```bash
.venv/bin/python -m pytest tests/ -v                    # All
.venv/bin/python -m pytest tests/test_sentiment.py -v   # Specific
```

## Current State (Feb 2026)

### What's Working
- ✅ Rebranding complete: AxisAI → LocusAI (all references updated)
- ✅ Test suite: 580 tests passing
- ✅ Voice AI: Telnyx SIP + Retell integration live (+442046203253)
- ✅ Chat Widget: Embeddable with booking confirmation flow
- ✅ SMS: Twilio integration ready
- ✅ Security: Lockout, encryption, rate limiting, validation
- ✅ Premium UI: Linear/Stripe-inspired visual overhaul

### Known Issues / Needs Work
- ⚠️ **Voice latency**: Response time still too slow for natural conversation
- ⚠️ **Voice naturalness**: Dorothy voice is better but still sounds robotic
- ⚠️ **Voice context**: Agent uses generic prompt, not connected to business KB/services
- ⚠️ **No caller recognition**: Year 1 priority, not implemented yet
- ⚠️ **No calendar sync**: Google/Outlook integration not built
- ⚠️ **No onboarding flow**: 10-minute setup goal not achieved

### Default Test Business
- **Business ID**: 9 (StyleCuts Hair Studio)
- **Tenant Key**: Used for widget API authentication
- **Dashboard Login**: admin@locusai.local / admin

---

## STRATEGY: Wedge → Expand → Platform

**See STRATEGY.md for full details.**

### Core Insight
Businesses DON'T switch their entire operating system. But they WILL add something new that solves a painful gap. An AI receptionist is ADDITIVE - it doesn't replace anything they have.

### Execution Plan

**Year 1: THE WEDGE - Best AI Receptionist on the market. Period.**
- Caller recognition ("Hi Sarah!")
- Real-time availability checking
- Multi-channel: Voice + SMS + Chat
- Integrates with existing calendars (Google, Outlook, Calendly)
- Dead simple setup (10 minutes)
- Multi-language (Spanish priority)

**Year 2: THE HOOK - Strategic integrations + optional native features**
- Offer LocusAI scheduling that "works better with the AI"
- Offer CRM that "tracks everyone who calls"
- Always integrate first, offer native second

**Year 3: THE PLATFORM - Full business OS for those ready**
- By now customers trust us and use multiple features
- Switching cost works in our favor
- We've earned the right to be their platform

### What We Say NO To (Year 1)
- Building our own payment processor
- Complex staff scheduling
- Inventory management
- Marketing automation
- Mobile apps
- Multi-location complexity
- Enterprise features

### The Pitch
"AI that answers your business calls 24/7, books appointments, and never takes a day off."

**We are:** The AI receptionist that integrates with everything you already use.
**We are NOT:** Another all-in-one platform asking you to switch everything.

### Year 1 Priorities (Ranked)
1. Incredible AI Voice Receptionist (caller recognition, natural conversation)
2. Multi-Channel Excellence (Voice, SMS, Web Widget)
3. Calendar Integrations (Google, Outlook, Calendly, Acuity, iCal)
4. Dead Simple Onboarding (10-minute setup)
5. Multi-Language Support (Spanish first)
6. Industry Templates (Medical, Salon, Auto)

---

## Development Guidelines

When building new features, always ask:
1. Does this make the AI receptionist better?
2. Does this integrate with tools businesses already use?
3. Can this be set up in under 10 minutes?

If the answer is NO to all three, it's probably a Year 2+ feature.

---

## Next Up (Priority Order)

1. **Fix Voice Quality**
   - Reduce latency (target: <1s response time)
   - More natural voice (try different voices, tune settings)
   - Connect to business KB for context-aware responses

2. **Caller Recognition**
   - Match incoming phone number to customer database
   - Personalized greeting: "Hi Sarah, calling about your appointment?"
   - Show call history to AI for context

3. **Calendar Integration**
   - Google Calendar sync (read availability, write bookings)
   - Outlook/Microsoft 365 support
   - Real-time availability checking during calls

4. **Onboarding Flow**
   - Guided setup wizard
   - Business info collection
   - Voice agent configuration
   - Test call feature
