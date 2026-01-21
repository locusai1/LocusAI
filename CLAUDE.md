# AI Business Utility Agent R&D - Complete Project Documentation

> **This file is automatically read by Claude at the start of each session.**
> Last updated: January 21, 2026

---

## Quick Reference

```bash
# Start the server
cd "/Users/paulomartinez/AI Business Utility Agent R&D"
.venv/bin/python -m flask --app dashboard run --host=0.0.0.0 --port=5050

# Access at: http://127.0.0.1:5050
# Login: admin / admin (dev credentials)
```

---

## Project Overview

**AxisAI** is a multi-tenant AI receptionist SaaS platform for small-to-medium businesses. It handles:
- Automated customer conversations via chat/widget
- Natural language appointment booking
- Sentiment analysis with automatic human handoff
- Customer relationship management
- Business analytics and reporting

**Target Industries (Initial)**:
- **Hairdressers / Hair Salons** - Appointment booking, service catalog
- **Real Estate Agencies** - Property inquiries, viewing scheduling

**Owner**: Paulo Martinez
**Location**: `/Users/paulomartinez/AI Business Utility Agent R&D/`
**Previous Name**: `dentist-ai` (renamed Jan 21, 2026 - legacy name, not the target market)

---

## Tech Stack

| Component | Technology |
|-----------|------------|
| Backend | Python 3.9, Flask |
| Database | SQLite (`receptionist.db`) with WAL mode |
| Frontend | Jinja2 templates, Tailwind CSS (CDN), Chart.js |
| AI | OpenAI GPT-4o-mini via API |
| Auth | Session-based with bcrypt password hashing |
| Virtual Env | `.venv/` |

---

## Environment Variables (.env)

```bash
OPENAI_API_KEY=sk-proj-...          # OpenAI API key for AI conversations
FLASK_SECRET_KEY=bb0a1993...        # Session encryption key
ENV=dev                              # Environment (dev/prod)
DASHBOARD_USERNAME=admin             # Default admin username
DASHBOARD_PASSWORD=admin             # Default admin password
```

---

## Complete File Structure

```
AI Business Utility Agent R&D/
│
├── dashboard.py              # Main Flask app entry point
│   - Registers all blueprints
│   - Request lifecycle (before_request, after_request)
│   - Security headers (CSP, HSTS, X-Frame-Options)
│   - Tenant isolation enforcement
│   - Branding context processor
│   - Error handlers (400, 403, 404, 500)
│   - Routes: /, /dashboard, /businesses, /business/<id>/edit, /brand/set, /health
│
├── main.py                   # Alternative entry point
│
├── BLUEPRINTS (13 total):
│   │
│   ├── auth_bp.py            # Authentication
│   │   - GET/POST /login     # Login form & handler
│   │   - GET /logout         # Logout (clears session)
│   │   - Uses bcrypt for password verification
│   │   - Session: user dict with id, email, role
│   │
│   ├── appointments_bp.py    # Appointment management
│   │   - GET /appointments                    # List appointments
│   │   - GET /appointments/new                # New appointment form
│   │   - POST /appointments/create            # Create appointment
│   │   - GET/POST /appointments/<id>/edit     # Edit appointment
│   │   - POST /appointments/<id>/status       # Update status
│   │   - POST /appointments/<id>/cancel       # Cancel appointment
│   │   - GET /appointments/<id>.ics           # iCal download
│   │   - GET /availability                    # Availability settings
│   │   - GET/POST /hours                      # Business hours
│   │   - GET/POST /closures                   # Holiday closures
│   │
│   ├── services_bp.py        # Service catalog
│   │   - GET /services                        # List services
│   │   - POST /services/create                # Create service
│   │   - POST /services/<id>/update           # Update service
│   │   - POST /services/<id>/delete           # Delete service
│   │   - POST /services/<id>/toggle           # Toggle active status
│   │
│   ├── customers_bp.py       # Customer management
│   │   - GET /customers                       # List customers
│   │   - GET /customers/new                   # New customer form
│   │   - POST /customers/create               # Create customer
│   │   - GET /customers/<id>                  # Customer detail
│   │   - GET/POST /customers/<id>/edit        # Edit customer
│   │   - POST /customers/<id>/delete          # Delete customer
│   │   - Links appointments and sessions to customers
│   │
│   ├── chat_bp.py            # Conversation viewer
│   │   - GET /chat                            # Session list
│   │   - GET /chat/<session_id>               # View conversation
│   │
│   ├── escalations_bp.py     # Human handoff management
│   │   - GET /escalations                     # List escalations
│   │   - GET /escalations/<id>                # View escalation detail
│   │   - POST /escalations/<id>/acknowledge   # Mark as acknowledged
│   │   - POST /escalations/<id>/resolve       # Mark as resolved
│   │
│   ├── kb_bp.py              # Knowledge base
│   │   - GET /kb                              # List KB entries
│   │   - GET /kb/new                          # New entry form
│   │   - POST /kb/create                      # Create entry
│   │   - GET/POST /kb/<id>/edit               # Edit entry
│   │   - POST /kb/<id>/delete                 # Delete entry
│   │   - Full-text search via FTS5
│   │
│   ├── analytics_bp.py       # Analytics dashboard
│   │   - GET /analytics                       # Main analytics page
│   │   - GET /analytics/api/summary           # JSON summary data
│   │   - GET /analytics/api/conversations     # Conversation metrics
│   │   - GET /analytics/api/appointments      # Appointment metrics
│   │   - GET /analytics/api/ai-performance    # AI performance metrics
│   │   - Metrics: conversations, bookings, sentiment, escalations
│   │
│   ├── widget_bp.py          # Embeddable chat widget
│   │   - GET /api/widget/frame                # Widget iframe HTML
│   │   - POST /api/widget/chat                # Chat API (CORS-enabled)
│   │   - GET /api/widget/settings             # Widget settings
│   │   - Uses tenant_key for authentication
│   │
│   ├── integrations_bp.py    # Third-party integrations
│   │   - GET /integrations                    # Integration settings page
│   │   - POST /integrations/<provider>/enable # Enable integration
│   │   - POST /integrations/<provider>/disable
│   │
│   ├── onboard_bp.py         # New business setup
│   │   - GET /onboard                         # Onboarding wizard
│   │   - POST /onboard/create                 # Create new business
│   │
│   └── search_bp.py          # Global search
│       - GET /search                          # Search results page
│
├── core/                     # Core business logic modules
│   │
│   ├── ai.py                 # AI conversation engine
│   │   - process_message(user_input, business_data, state) -> reply
│   │   - process_message_with_metadata() -> {reply, sentiment, escalated}
│   │   - Uses OpenAI GPT-4o-mini
│   │   - Integrates sentiment analysis
│   │   - Auto-triggers escalation on negative sentiment
│   │   - Booking detection via <BOOKING>{json}</BOOKING> tags
│   │   - RAG: Injects relevant KB snippets
│   │
│   ├── sentiment.py          # Sentiment analysis engine
│   │   - analyze_sentiment(text, history, failed_attempts) -> SentimentResult
│   │   - SentimentType enum: POSITIVE, NEUTRAL, NEGATIVE, FRUSTRATED, ANGRY, CONFUSED, URGENT, SATISFIED
│   │   - IntentType enum: BOOKING, INQUIRY, COMPLAINT, HUMAN_REQUEST, CANCELLATION, GREETING, FAREWELL, GRATITUDE, UNKNOWN
│   │   - Pattern matching for: human requests, frustration, urgency, confusion, complaints
│   │   - Word-level analysis: negative words, intensifiers, negations
│   │   - Punctuation analysis: caps, exclamation marks
│   │   - Frustration score: 0.0-1.0 (triggers escalation >0.7)
│   │   - Escalation triggers:
│   │     * Customer explicitly requests human
│   │     * High frustration score (>0.7)
│   │     * Complaint with 2+ negative indicators
│   │     * 3+ failed booking attempts
│   │     * Emergency/urgent keywords
│   │
│   ├── escalation.py         # Human handoff system
│   │   - create_escalation(business_id, session_id, ...) -> escalation_id
│   │   - handle_escalation(sentiment_result, business, ...) -> escalation_id
│   │   - notify_escalation() - Sends email to business owner
│   │   - get_escalation_response() - Standard handoff message
│   │   - Priority levels: low, normal, high, urgent
│   │   - Status: pending, acknowledged, resolved
│   │
│   ├── db.py                 # Database layer (696 lines)
│   │   - get_conn() -> sqlite3.Connection (with WAL mode)
│   │   - transaction() context manager with auto-rollback
│   │   - init_db() - Creates all tables and indexes
│   │   - Business operations: list_businesses, get_business_by_id, create_business, update_business
│   │   - Session operations: create_session, get_session_messages, log_message
│   │   - Appointment operations: create_appointment, update_appointment_status, check_slot_available
│   │   - Data retention: cleanup_old_data()
│   │
│   ├── booking.py            # Booking logic
│   │   - Slot availability checking
│   │   - Conflict detection
│   │   - Duration calculations
│   │
│   ├── knowledge.py          # Knowledge base utilities
│   │   - kb_search(business_id, query, limit) - FTS5 search
│   │
│   ├── kb.py                 # Additional KB functions
│   │
│   ├── validators.py         # Input validation
│   │   - slugify(text) - URL-safe slug generation
│   │   - validate_redirect_url() - Prevents open redirect
│   │   - safe_int() - Safe integer parsing
│   │   - Input sanitization
│   │
│   ├── settings.py           # Configuration loading
│   │   - OPENAI_API_KEY
│   │   - FLASK_SECRET_KEY
│   │
│   ├── csrf.py               # CSRF protection
│   │   - register_csrf(app) - Adds CSRF to all forms
│   │
│   ├── authz.py              # Authorization helpers
│   │   - get_allowed_business_ids_for_user(user) -> list
│   │   - user_can_access_business(user, business_id) -> bool
│   │
│   ├── mailer.py             # Email sending
│   │   - send_email(to, subject, body)
│   │
│   ├── ics.py                # iCalendar generation
│   │   - generate_ics(appointment) -> ics_string
│   │
│   ├── integrations.py       # Integration provider registry
│   │   - Provider base class
│   │   - register_provider()
│   │
│   ├── tenantfs.py           # Tenant file system
│   │   - write_meta_from_db() - Syncs business data to filesystem
│   │
│   ├── utils.py              # General utilities
│   │
│   └── logger.py             # Logging configuration
│
├── templates/                # Jinja2 HTML templates (31 files)
│   │
│   ├── base.html             # Main layout
│   │   - Sidebar navigation with icons
│   │   - Business switcher dropdown
│   │   - Mobile hamburger menu
│   │   - Tailwind CSS CDN
│   │   - Chart.js CDN
│   │   - Flash message display
│   │
│   ├── login.html            # Standalone login page
│   │   - Centered card layout
│   │   - Password show/hide toggle
│   │   - Includes own Tailwind CDN (doesn't extend base.html)
│   │
│   ├── dashboard.html        # Home dashboard
│   │   - Personalized greeting (Good morning/afternoon/evening)
│   │   - KPI cards: Today's appointments, Pending, Confirmed, Total
│   │   - 7-day appointment chart
│   │   - Quick action buttons
│   │
│   ├── analytics.html        # Analytics dashboard
│   │   - Date range filters (7d, 30d, 90d)
│   │   - Conversation metrics chart
│   │   - Appointment status breakdown
│   │   - AI performance metrics
│   │   - Peak hours heatmap
│   │
│   ├── appointments.html     # Appointments list
│   ├── appointments_new.html # New appointment form
│   ├── customers.html        # Customer list
│   ├── customer_detail.html  # Customer profile with history
│   ├── customer_new.html
│   ├── customer_edit.html
│   ├── services.html         # Service catalog
│   ├── chat.html             # Conversation viewer
│   ├── escalations.html      # Escalation queue
│   ├── escalation_detail.html
│   ├── kb_list.html          # Knowledge base
│   ├── kb_edit.html
│   ├── integrations.html     # Integration settings
│   ├── businesses.html       # Business list
│   ├── edit_business.html    # Business settings
│   ├── delete_business.html
│   ├── onboard.html          # New business wizard
│   ├── search.html           # Search results
│   ├── hours.html            # Business hours
│   ├── availability.html
│   ├── closures.html         # Holiday closures
│   ├── widget_frame.html     # Widget iframe content
│   ├── admin_users.html      # User management
│   └── error_*.html          # Error pages (400, 403, 404, 500)
│
├── static/                   # Static assets
│   ├── axis.css              # Main stylesheet (1200+ lines)
│   │   - CSS variables: --bg-page, --bg-card, --text-primary, etc.
│   │   - Components: cards, buttons, forms, tables, badges, modals
│   │   - Sidebar styles
│   │   - Dark mode support (data-theme="dark")
│   ├── app.js                # Client-side JavaScript
│   ├── logo.svg              # AxisAI logo
│   ├── favicon.svg           # Browser favicon
│   ├── widget.js             # Embeddable widget script
│   │   - Usage: <script src="/widget.js" data-tenant="key"></script>
│   │   - Creates iframe + postMessage communication
│   ├── widget-test.html      # Widget testing page
│   ├── uploads/              # User file uploads
│   └── tenants/              # Per-tenant assets
│
├── adapters/                 # External service adapters
│   ├── local.py              # Local adapter
│   └── twilio.py             # Twilio SMS adapter (ready for use)
│
├── providers/                # Booking providers
│   ├── local_provider.py     # Built-in local booking
│   └── dummy_provider.py     # Testing provider
│
├── businesses/               # Business config files (JSON)
│   ├── dentist.json
│   ├── hair_salon.json
│   ├── template.json
│   └── smile-dental-clinic/
│       ├── meta.json
│       ├── services.csv
│       └── integrations.json
│
├── tools/                    # Utility scripts
│   ├── sync_businesses.py    # Sync DB to filesystem
│   ├── backup_axis.py        # Create backups
│   └── restore_axis.py       # Restore from backup
│
├── tests/                    # Test files
│   ├── conftest.py           # Pytest fixtures
│   └── test_booking.py       # Booking tests
│
├── logs/                     # Application logs
│   ├── app.log               # General app log (10MB rotation)
│   └── security.log          # Security audit log
│
├── receptionist.db           # SQLite database
├── .env                      # Environment variables
├── .gitignore
└── .git/                     # Git repository
```

---

## Complete Database Schema

### businesses
```sql
CREATE TABLE businesses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    slug TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    hours TEXT,
    address TEXT,
    services TEXT,
    tone TEXT,                    -- AI personality: "friendly", "professional", etc.
    escalation_phone TEXT,
    escalation_email TEXT,
    data_retention_days INTEGER DEFAULT 365,
    accent_color TEXT,            -- Hex color for branding
    logo_path TEXT,
    tenant_key TEXT UNIQUE,       -- UUID for widget authentication
    settings_json TEXT,
    files_path TEXT,
    static_path TEXT,
    archived INTEGER NOT NULL DEFAULT 0
);
```

### users
```sql
CREATE TABLE users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    email TEXT NOT NULL UNIQUE COLLATE NOCASE,
    name TEXT NOT NULL,
    password_hash TEXT NOT NULL,  -- bcrypt hashed
    role TEXT NOT NULL CHECK(role IN ('admin','owner')) DEFAULT 'owner',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
```

### business_users (many-to-many mapping)
```sql
CREATE TABLE business_users (
    user_id INTEGER NOT NULL,
    business_id INTEGER NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (user_id, business_id),
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
    FOREIGN KEY (business_id) REFERENCES businesses(id) ON DELETE CASCADE
);
```

### sessions (chat sessions)
```sql
CREATE TABLE sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    business_id INTEGER NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    channel TEXT DEFAULT 'web',        -- 'web', 'sms', 'whatsapp'
    phone TEXT,
    customer_id INTEGER REFERENCES customers(id),
    escalated INTEGER DEFAULT 0,
    escalated_at TEXT,
    escalation_reason TEXT,
    FOREIGN KEY (business_id) REFERENCES businesses(id) ON DELETE CASCADE
);
```

### messages
```sql
CREATE TABLE messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER NOT NULL,
    timestamp TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    sender TEXT NOT NULL CHECK(sender IN ('user','bot')),
    text TEXT NOT NULL,
    channel TEXT DEFAULT 'web',
    FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE
);
```

### appointments
```sql
CREATE TABLE appointments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    business_id INTEGER NOT NULL,
    customer_name TEXT,
    phone TEXT,
    customer_email TEXT,
    service TEXT,
    start_at TEXT,                -- ISO datetime
    status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','confirmed','cancelled','completed')),
    session_id INTEGER,
    external_provider_key TEXT,
    external_id TEXT,
    source TEXT CHECK(source IN ('ai','owner','api') OR source IS NULL),
    notes TEXT,
    customer_id INTEGER REFERENCES customers(id),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (business_id) REFERENCES businesses(id) ON DELETE CASCADE
);
```

### services
```sql
CREATE TABLE services (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    business_id INTEGER NOT NULL,
    name TEXT NOT NULL,
    duration_min INTEGER NOT NULL DEFAULT 30 CHECK(duration_min >= 5 AND duration_min <= 480),
    price TEXT,
    active INTEGER NOT NULL DEFAULT 1,
    external_id TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(business_id, name),
    FOREIGN KEY (business_id) REFERENCES businesses(id) ON DELETE CASCADE
);
```

### customers
```sql
CREATE TABLE customers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    business_id INTEGER NOT NULL,
    name TEXT,
    email TEXT,
    phone TEXT,
    notes TEXT,
    tags TEXT,                    -- JSON array of tags
    first_seen_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    last_seen_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    total_appointments INTEGER NOT NULL DEFAULT 0,
    total_sessions INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (business_id) REFERENCES businesses(id) ON DELETE CASCADE
);
-- Indexes on (business_id, email) and (business_id, phone)
```

### escalations
```sql
CREATE TABLE escalations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    business_id INTEGER NOT NULL,
    session_id INTEGER,
    customer_id INTEGER,
    reason TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending', 'acknowledged', 'resolved')),
    priority TEXT NOT NULL DEFAULT 'normal' CHECK(priority IN ('low', 'normal', 'high', 'urgent')),
    notes TEXT,
    notified_at TEXT,
    resolved_at TEXT,
    resolved_by TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (business_id) REFERENCES businesses(id) ON DELETE CASCADE,
    FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE SET NULL,
    FOREIGN KEY (customer_id) REFERENCES customers(id) ON DELETE SET NULL
);
```

### kb_entries (knowledge base)
```sql
CREATE TABLE kb_entries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    business_id INTEGER NOT NULL,
    question TEXT NOT NULL,
    answer TEXT NOT NULL,
    tags TEXT,
    active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (business_id) REFERENCES businesses(id) ON DELETE CASCADE
);
-- FTS5 virtual table: kb_entries_fts (question, answer, tags)
```

### business_hours
```sql
CREATE TABLE business_hours (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    business_id INTEGER NOT NULL,
    weekday INTEGER NOT NULL CHECK(weekday >= 0 AND weekday <= 6),  -- 0=Mon, 6=Sun
    open_time TEXT,              -- "09:00"
    close_time TEXT,             -- "17:00"
    closed INTEGER NOT NULL DEFAULT 0,
    UNIQUE(business_id, weekday),
    FOREIGN KEY (business_id) REFERENCES businesses(id) ON DELETE CASCADE
);
```

### closures (holidays)
```sql
CREATE TABLE closures (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    business_id INTEGER NOT NULL,
    date TEXT NOT NULL,          -- "2026-12-25"
    reason TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(business_id, date),
    FOREIGN KEY (business_id) REFERENCES businesses(id) ON DELETE CASCADE
);
```

### widget_settings
```sql
CREATE TABLE widget_settings (
    business_id INTEGER PRIMARY KEY,
    enabled INTEGER NOT NULL DEFAULT 1,
    position TEXT NOT NULL DEFAULT 'bottom-right' CHECK(position IN ('bottom-right', 'bottom-left')),
    primary_color TEXT,
    welcome_message TEXT DEFAULT 'Hi! How can I help you today?',
    placeholder_text TEXT DEFAULT 'Type a message...',
    allowed_domains TEXT,        -- JSON array of allowed origins
    show_branding INTEGER NOT NULL DEFAULT 1,
    auto_open_delay INTEGER,     -- ms before auto-opening
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (business_id) REFERENCES businesses(id) ON DELETE CASCADE
);
```

### reminders
```sql
CREATE TABLE reminders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    appointment_id INTEGER NOT NULL,
    type TEXT NOT NULL CHECK(type IN ('24h', '1h', '15m')),
    channel TEXT NOT NULL CHECK(channel IN ('email', 'sms')),
    scheduled_for TEXT NOT NULL,
    sent_at TEXT,
    status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending', 'sent', 'failed', 'cancelled')),
    error_message TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (appointment_id) REFERENCES appointments(id) ON DELETE CASCADE
);
```

### integrations
```sql
CREATE TABLE integrations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    business_id INTEGER NOT NULL,
    provider_key TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active' CHECK(status IN ('active','inactive','error')),
    access_token TEXT,
    refresh_token TEXT,
    token_expires_at TEXT,
    account_json TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(business_id, provider_key),
    FOREIGN KEY (business_id) REFERENCES businesses(id) ON DELETE CASCADE
);
```

---

## AI System Architecture

### Conversation Flow
```
User Message
    │
    ▼
┌─────────────────────────────────────────┐
│  Sentiment Analysis (core/sentiment.py) │
│  - Pattern matching (human request,     │
│    frustration, urgency, confusion)     │
│  - Word-level analysis                  │
│  - Frustration score calculation        │
└─────────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────────┐
│  Escalation Check                       │
│  - If triggers_escalation=True:         │
│    → Create escalation record           │
│    → Send notification email            │
│    → Return handoff message             │
└─────────────────────────────────────────┘
    │ (if no escalation)
    ▼
┌─────────────────────────────────────────┐
│  Build AI Prompt                        │
│  - Business info (name, hours, address) │
│  - Sentiment-adaptive guidance          │
│  - Conversation history (last 12 msgs)  │
│  - KB snippets (RAG)                    │
└─────────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────────┐
│  OpenAI GPT-4o-mini                     │
│  - max_tokens=300                       │
│  - temperature=0.6                      │
└─────────────────────────────────────────┘
    │
    ▼
AI Response (may contain <BOOKING> tag)
```

### Booking Detection
The AI outputs bookings in this format:
```
<BOOKING>{"name":"John Doe","phone":"555-1234","service":"Cleaning","datetime":"2026-01-25 14:00","notes":""}</BOOKING>
```

### Sentiment Patterns
```python
# Human request triggers (immediate escalation)
HUMAN_REQUEST_PATTERNS = [
    r'\b(speak|talk|connect)\s+(to|with)\s+(a\s+)?(human|person|someone|agent)',
    r'\breal\s+person\b',
    r'\bnot\s+(a\s+)?(bot|robot|ai)\b',
    ...
]

# Frustration patterns (>0.7 score triggers escalation)
FRUSTRATION_PATTERNS = [
    r'\b(ridiculous|absurd|unacceptable|terrible|horrible)\b',
    r'\b(frustrated|annoyed|upset|angry|furious)\b',
    r'[!]{2,}',  # Multiple exclamation marks
    ...
]

# Urgency patterns
URGENCY_PATTERNS = [
    r'\b(urgent|emergency|asap|immediately)\b',
    r'\b(in\s+pain|bleeding|severe)\b',
    ...
]
```

---

## Security Features

### Authentication
- Session-based authentication
- bcrypt password hashing
- 4-hour session timeout
- CSRF protection on all forms

### Tenant Isolation
- `before_request` hook enforces tenant boundaries
- `g.allowed_business_ids` whitelist per user
- Admin role bypasses tenant restrictions
- Security logger tracks access violations

### HTTP Security Headers
```
X-Content-Type-Options: nosniff
X-XSS-Protection: 1; mode=block
X-Frame-Options: DENY (except widget)
Referrer-Policy: strict-origin-when-cross-origin
Content-Security-Policy: default-src 'self'; ...
Strict-Transport-Security: (production only)
```

### Widget Security
- Tenant key authentication (UUID)
- CORS-enabled for allowed domains
- Separate CSP for iframe embedding
- Rate limiting per tenant key

---

## UI Design System (axis.css)

### Color Palette
```css
:root {
    --bg-page: #fafafa;
    --bg-card: #ffffff;
    --border-light: #ebebeb;
    --border-default: #e5e5e5;
    --text-primary: #171717;
    --text-secondary: #525252;
    --text-tertiary: #737373;
    --text-muted: #a3a3a3;
}
```

### Key CSS Classes
- `.card` - White card with border and shadow
- `.btn`, `.btn-primary`, `.btn-secondary` - Buttons
- `.input`, `.form-group`, `.form-label` - Form elements
- `.badge`, `.badge-success`, `.badge-warning` - Status badges
- `.alert`, `.alert-success`, `.alert-error` - Flash messages
- `.sidebar`, `.sidebar-nav`, `.sidebar-section` - Navigation

### Dark Mode
Add `data-theme="dark"` to `<html>` element.

---

## Widget Integration

### Embed Code
```html
<script src="https://yoursite.com/static/widget.js" data-tenant="YOUR_TENANT_KEY"></script>
```

### Widget API Endpoints
- `GET /api/widget/frame` - Returns iframe HTML
- `POST /api/widget/chat` - Chat API
  - Body: `{"message": "...", "session_id": "..."}`
  - Response: `{"reply": "...", "session_id": "...", "sentiment": "..."}`

---

## Development Notes

### Running Tests
```bash
.venv/bin/pytest tests/ -v
```

### Database Access
```bash
sqlite3 receptionist.db
.tables
.schema businesses
SELECT * FROM users;
```

### Creating Backup
```bash
cd "/Users/paulomartinez/AI Business Utility Agent R&D"
zip -r backup.zip . -x ".venv/*" -x ".git/*"
```

---

## Planned Features (Not Yet Implemented)

From the plan file, these features are designed but not built:

1. **SMS/Text via Twilio** (`core/sms.py`, `sms_bp.py`)
   - Twilio webhook for incoming SMS
   - Route to same AI flow
   - Store messages with channel='sms'

2. **Appointment Reminders** (`core/reminders.py`, `tools/reminder_worker.py`)
   - 24h and 1h before appointment
   - Email + SMS
   - Background worker

3. **Google Calendar 2-Way Sync** (`providers/google_calendar.py`, `gcal_bp.py`)
   - OAuth 2.0 flow
   - Create events on booking
   - Webhook for external changes

4. **WhatsApp Business** (`core/whatsapp.py`, `whatsapp_bp.py`)
   - Via Twilio WhatsApp API
   - Rich messages support

### Dependencies for Future Features
```bash
pip install twilio google-auth google-auth-oauthlib google-api-python-client
```

---

## Troubleshooting

### Server won't start
```bash
# Check if port is in use
lsof -i :5050
# Kill process using port
kill -9 <PID>
```

### Database locked
- SQLite uses WAL mode for better concurrency
- If locked, check for hanging connections

### Login page looks broken
- Ensure Tailwind CDN is included: `<script src="https://cdn.tailwindcss.com"></script>`
- Hard refresh: Cmd+Shift+R

### AI not responding
- Check OPENAI_API_KEY in .env
- Check logs/app.log for errors

---

## Recent Changes (January 2026)

1. **Enhanced AI** - Added sentiment analysis and automatic escalation
2. **Analytics Dashboard** - Full metrics with Chart.js visualizations
3. **UI Overhaul** - New design system inspired by ElevenLabs
4. **Customer Profiles** - CRM functionality with history tracking
5. **Escalation System** - Human handoff with email notifications
6. **Widget** - Embeddable chat widget for external websites
7. **Project Rename** - Renamed from `dentist-ai` to `AI Business Utility Agent R&D`
8. **Cleanup** - Removed all .bak files, old backups, temporary files

---

## Target Industry Details

### Hairdressers / Hair Salons
- Service-based booking (haircuts, coloring, styling, treatments)
- Duration varies by service (30 mins - 3 hours)
- Often need stylist assignment
- Walk-ins vs appointments
- Cancellation/reschedule handling

### Real Estate Agencies
- Property viewing scheduling
- Inquiry handling (price, location, features)
- Lead capture and qualification
- Agent assignment
- Multi-property management

### Extensible to Other Industries
The platform is designed to work with any appointment-based or inquiry-based business:
- Medical/dental clinics
- Fitness studios
- Consulting services
- Auto repair shops
- Spas and wellness centers

---

## Contacts

**Project Owner**: Paulo Martinez
**Project Name**: AI Business Utility Agent (AxisAI)
**Target Markets**: Hairdressers, Real Estate Agencies (initial), expandable to any SMB
