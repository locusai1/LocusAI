# LocusAI — Project HQ

> AI receptionist SaaS for SMBs. Handles inbound calls, web chat, SMS, appointment booking, and human escalation.
> **Pitch:** "AI that answers your business calls 24/7, books appointments, and never takes a day off."
> **Stack:** Flask + SQLite + Retell AI + Telnyx + OpenAI

---

## 🗂 Quick Links

- [Launch Checklist](#launch-checklist)
- [External Services & Logins](#external-services--logins)
- [Roadmap](#roadmap)
- [Pricing](#pricing)
- [Competitors](#competitors)

---

## Launch Checklist

### TIER 0 — Nothing ships without these

#### Legal
- [ ] Cookie consent banner (CookieYes free tier — 30 min)
- [ ] Solicitor review of Privacy Policy
- [ ] Solicitor review of Terms of Service
- [ ] Data Processing Agreement template for B2B customers
- [ ] Gate or remove Medical/Dental onboarding template until HIPAA BAAs exist

#### Revenue
- [ ] Stripe billing — `billing_bp.py` + subscriptions table + Checkout + webhooks + Customer Portal
- [ ] Trial expiry enforcement (code exists to store date, nothing checks it yet)
- [ ] Subscription tiers live: Starter £49 / Pro £149 / Business £299

#### Customer Acquisition
- [ ] Public marketing homepage (/ currently requires login — zero public presence)
- [ ] Email provider set up (Postmark or Resend — needed for verification + password reset + reminders)

#### Infrastructure
- [ ] Gunicorn (replace Flask dev server)
- [ ] Nginx reverse proxy (TLS, static files, gzip)
- [ ] SSL via Certbot (Let's Encrypt)
- [ ] Dockerfile + docker-compose
- [ ] Sentry error monitoring (5 lines in dashboard.py, free tier)
- [ ] Remote DB backups (SQLite → S3 or Backblaze, hourly)
- [ ] Remove Tailwind CDN from base.html → compile with npx tailwindcss

#### Voice / Multi-tenant
- [ ] Per-business Telnyx phone number (currently hardcoded to +442046203253)
- [ ] `telnyx_phone_number` stored per business in voice_settings

---

### TIER 1 — Week 1–4 post-launch

- [ ] Appointment reschedule/cancel via AI (top-3 use case, completely missing)
- [ ] Google Calendar end-to-end (code done — just needs GOOGLE_CLIENT_ID/SECRET)
- [ ] Appointment calendar view (week/month grid)
- [ ] In-app onboarding checklist for new businesses (replace empty KPI cards)
- [ ] Dashboard notifications bell (pending escalations count)
- [ ] Sidebar: show user name not just "Logout"
- [ ] KPI cards: make clickable → link to full list pages
- [ ] Flash messages: persist until dismissed (not 5s auto-dismiss)
- [ ] Error pages (404/500): extend standalone base (broken for logged-out users)
- [ ] Mobile table overflow (horizontal scroll)
- [ ] Uptime monitoring (UptimeRobot free, watch /health every 5 min)
- [ ] SMS STOP keyword opt-out handling (TCPA requirement for US)
- [ ] Email sequences: welcome, trial Day 10/13 warning, payment failed dunning

---

### TIER 2 — Month 2–3

- [ ] Spanish / bilingual AI support
- [ ] Public shareable booking page (/book/<slug>)
- [ ] Zapier outbound webhooks
- [ ] Outlook / Microsoft 365 calendar
- [ ] Calendly API (UI exists, no real API calls yet)
- [ ] HubSpot CRM — auto-create contact on first call
- [ ] Voicemail transcription → email
- [ ] Redis (replace in-process rate limiting)
- [ ] Structured JSON logging
- [ ] G2 / Capterra profile
- [ ] Product Hunt launch
- [ ] Demo phone number for prospects

---

### TIER 3 — Month 4+

- [ ] PostgreSQL migration (SQLite fine until ~1,000 DAU)
- [ ] Celery + Redis for background jobs
- [ ] SOC 2 Type I audit
- [ ] HIPAA compliance mode
- [ ] White-label / custom branding
- [ ] Multi-location management
- [ ] Public API + developer docs
- [ ] Mobile app (React Native)
- [ ] Square / Acuity integrations
- [ ] iCal feed import/export

---

## External Services & Logins

> ⚠️ Never store actual passwords here — use 1Password or similar. Just track the account email and purpose.

### Active — Have Accounts

| Service | URL | Account Email | What it does |
|---------|-----|---------------|--------------|
| OpenAI | platform.openai.com | | Powers all AI: chat, voice LLM, post-call analysis, sentiment. Model: GPT-4o-mini. Env: `OPENAI_API_KEY` |
| Retell AI | app.retellai.com | | Hosts the AI voice receptionist. Agent ID: `agent_7fe6433627a68c931f05b7ae84`. Fires webhooks for call setup + analysis. Env: `RETELL_API_KEY` |
| Telnyx | telnyx.com | | Owns UK number +442046203253. Routes inbound calls via SIP to Retell. Also handles SMS. Env: `TELNYX_API_KEY` |
| Cloudflare | dash.cloudflare.com | | Dev: `cloudflared tunnel` for Retell webhooks. Prod: DNS, SSL, CDN for widget.js |

### Needed Soon

| Service | URL | Purpose | Priority |
|---------|-----|---------|----------|
| Postmark or Resend | postmarkapp.com / resend.com | Transactional email — verification, password reset, reminders. Currently broken. | URGENT |
| Stripe | dashboard.stripe.com | Billing — zero code exists yet | TIER 0 |
| Sentry | sentry.io | Error monitoring in prod | TIER 0 |
| UptimeRobot | uptimerobot.com | Monitor /health every 5 min | TIER 1 |
| Google Cloud | console.cloud.google.com | OAuth app for Google Calendar integration. Code is built, just needs CLIENT_ID + SECRET | TIER 1 |

---

## Roadmap

### Now (Pre-launch)
1. Stripe billing (zero code — biggest gap)
2. Trial expiry enforcement
3. Public marketing homepage
4. Email provider (Postmark/Resend)
5. Per-business Telnyx phone numbers
6. Production stack (Gunicorn + Nginx + SSL + Docker)

### Next (Post-launch Month 1)
1. Appointment reschedule/cancel via AI
2. Google Calendar end-to-end
3. Dashboard UX fixes
4. Calendar view (week/month)
5. Onboarding checklist for new businesses

### Later (Month 2–3)
1. Spanish language support
2. Zapier integration
3. HubSpot CRM sync
4. Public booking page

---

## Pricing

| Plan | Price | Limits | Features |
|------|-------|--------|---------|
| Starter | £49/mo | 100 conversations, 1 business, 1 user | Chat widget only |
| Professional | £149/mo | 500 conversations, 3 users | Voice + Chat + SMS, Google Calendar |
| Business | £299/mo | Unlimited conversations, 10 users | Full analytics, priority support |
| Enterprise | Custom | Unlimited | White-label, custom integrations, SLA, HIPAA BAA |

Annual pricing: 2 months free (~16.7% discount)

---

## Competitors

| Competitor | Price | Their Edge Over Us Today |
|------------|-------|--------------------------|
| Synthflow | $29–$1,400/mo | SOC 2 + HIPAA, <100ms latency, 20+ languages, CRM integrations |
| Smith.ai | $97–$292/mo | Live human hybrid, HIPAA, HubSpot/Salesforce, mobile app |
| Bland.ai / Vapi | $0.09/min | Ultra-low latency, 20+ languages, developer API |
| Ruby Receptionist | ~$239/mo | Human + AI hybrid, strong SMB brand trust |

**Our edges:** Cleaner UI, no per-minute pricing, booking confirmation flow, real-time sentiment escalation, CSV KB import, self-service signup, multi-step onboarding.

---

## Key Numbers

| Thing | Value |
|-------|-------|
| UK Phone Number | +442046203253 |
| Retell Agent ID | agent_7fe6433627a68c931f05b7ae84 |
| Retell LLM ID | llm_b41019c52636d5321f084e5bdbbb |
| Telnyx Phone Number ID | 2879031589981914356 |
| Telnyx FQDN Connection ID | 2882485623761929727 |
| Default test business | ID 9 — StyleCuts Hair Studio |
| Dev login | admin@locusai.local / admin |
| Dev URL | http://127.0.0.1:5050 |
| Test suite | 563 tests across 18 files |

---

## Strategy: Wedge → Expand → Platform

**Year 1 — THE WEDGE:** Best AI receptionist on the market.
- Caller recognition, real-time availability, multi-channel, calendar integrations, 10-min setup, Spanish

**Year 2 — THE HOOK:** Strategic integrations + optional native features
- Offer LocusAI scheduling that "works better with the AI"
- Always integrate first, offer native second

**Year 3 — THE PLATFORM:** Full business OS for those who've opted in

**Say NO to in Year 1:** payment processor, complex staff scheduling, inventory, marketing automation, mobile app, multi-location, enterprise.
