# AxisAI - Complete Project Documentation

> **This file is automatically read by Claude at the start of each session.**
> Last updated: January 21, 2026
>
> **IMPORTANT**: This file contains EVERYTHING about the codebase, strategic plan, and project state.
> Read this entire file to have full context equivalent to the developer who wrote it.

---

## Quick Reference

```bash
# Start the server (option 1 - use alias)
axisai          # jumps to project folder
axisrun         # jumps to folder AND starts server

# Start the server (option 2 - manual)
cd "/Users/paulomartinez/AxisAI"
.venv/bin/python -m flask --app dashboard run --host=0.0.0.0 --port=5050

# Access at: http://127.0.0.1:5050
# Login: admin / admin (dev credentials)

# Run tests (once)
.venv/bin/python -m pytest tests/ -v

# Run tests continuously (watches for file changes)
.venv/bin/ptw tests/ --clear
```

---

## Development Environment Setup

**Folder Location**: `/Users/paulomartinez/AxisAI/`

**Terminal Shortcuts** (configured in ~/.zshrc):
- `axisai` or `axis` - Jump to project folder
- `axisrun` - Jump to folder and start Flask server
- Desktop shortcut: "AxisAI Terminal.command" - Double-click to open Terminal in project folder

**Autosave System**:
- LaunchAgent runs every 15 minutes: `com.axisai.autosave`
- Automatically commits any uncommitted changes to git
- Config: `/Users/paulomartinez/Library/LaunchAgents/com.axisai.autosave.plist`
- Script: `/Users/paulomartinez/AxisAI/tools/autosave.sh`
- Logs: `/Users/paulomartinez/AxisAI/logs/autosave.log`
- To check if running: `launchctl list | grep axisai`

**Git Repository**:
- All code is version controlled with git
- Autosave creates commits automatically every 15 min
- To check status: `git status`
- To see recent saves: `git log --oneline -10`

---

## Project Overview

**AxisAI** is a multi-tenant AI receptionist SaaS platform for small-to-medium businesses. It handles:
- Automated customer conversations via chat/widget
- Natural language appointment booking with confirmation flow
- Sentiment analysis with automatic human handoff
- Customer relationship management
- Business analytics and reporting

**Target Industries (Initial)**:
- **Hairdressers / Hair Salons** - Appointment booking, service catalog
- **Real Estate Agencies** - Property inquiries, viewing scheduling

**Owner**: Paulo Martinez
**Location**: `/Users/paulomartinez/AxisAI/`
**Previous Names**: `AI Business Utility Agent R&D`, `dentist-ai`

---

## Tech Stack

| Component | Technology |
|-----------|------------|
| Backend | Python 3.9, Flask |
| Database | SQLite (`receptionist.db`) with WAL mode |
| Frontend | Jinja2 templates, Tailwind CSS (CDN), Chart.js |
| AI | OpenAI GPT-4o-mini via API |
| Auth | Session-based with bcrypt/pbkdf2 password hashing |
| Testing | pytest (284 tests), pytest-watch for continuous testing |
| Virtual Env | `.venv/` |

---

## Environment Variables (.env)

```bash
OPENAI_API_KEY=sk-proj-...          # OpenAI API key for AI conversations
FLASK_SECRET_KEY=bb0a1993...        # Session encryption key
ENCRYPTION_KEY=...                   # Optional: Fernet key for PII encryption
ENV=dev                              # Environment (dev/prod)
DASHBOARD_USERNAME=admin             # Default admin username
DASHBOARD_PASSWORD=admin             # Default admin password
```

---

## Complete File Structure

```
AxisAI/
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
│   │   - Account lockout after 5 failed attempts (15 min)
│   │   - Uses bcrypt/pbkdf2 for password verification
│   │   - Session: user dict with id, email, role
│   │   - PII masking in logs (_mask_email function)
│   │   - Functions: check_account_lockout(), record_failed_attempt(), clear_failed_attempts()
│   │   - Functions: create_user(), change_password()
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
│   │   - GET /api/widget/config               # Widget configuration
│   │   - POST /api/widget/session             # Create new session
│   │   - POST /api/widget/chat                # Chat API (CORS-enabled)
│   │   - GET /api/widget/history              # Get conversation history
│   │   - POST /api/widget/booking/confirm     # Confirm pending booking
│   │   - POST /api/widget/booking/cancel      # Cancel pending booking
│   │   - Uses tenant_key for authentication
│   │   - Rate limiting per tenant
│   │   - CORS validation via _check_origin()
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
│   ├── sentiment.py          # Sentiment analysis engine (35 tests)
│   │   - analyze_sentiment(text, history, failed_attempts) -> SentimentResult
│   │   - SentimentType enum: POSITIVE, NEUTRAL, NEGATIVE, FRUSTRATED, ANGRY, CONFUSED, URGENT, SATISFIED
│   │   - IntentType enum: BOOKING, INQUIRY, COMPLAINT, HUMAN_REQUEST, CANCELLATION, GREETING, FAREWELL, GRATITUDE, UNKNOWN
│   │   - Pattern matching for: human requests, frustration, urgency, confusion, complaints
│   │   - Word-level analysis: negative words, intensifiers, negations
│   │   - Punctuation analysis: caps, exclamation marks
│   │   - Frustration score: 0.0-1.0 (triggers escalation >0.7)
│   │   - get_sentiment_emoji(sentiment_type) -> emoji string
│   │   - summarize_conversation(messages) -> summary string
│   │   - Escalation triggers:
│   │     * Customer explicitly requests human
│   │     * High frustration score (>0.7)
│   │     * Complaint with 2+ negative indicators
│   │     * 3+ failed booking attempts
│   │     * Emergency/urgent keywords
│   │   - Intent detection order: COMPLAINT > BOOKING > CANCELLATION > GRATITUDE/FAREWELL > GREETING > INQUIRY
│   │   - BOOKING triggers on: "book", "appointment", "schedule"
│   │   - CANCELLATION triggers on: "cancel", "reschedule", "change" (without booking keywords)
│   │
│   ├── escalation.py         # Human handoff system
│   │   - create_escalation(business_id, session_id, ...) -> escalation_id
│   │   - handle_escalation(sentiment_result, business, ...) -> escalation_id
│   │   - notify_escalation() - Sends email to business owner
│   │   - get_escalation_response() - Standard handoff message
│   │   - Priority levels: low, normal, high, urgent
│   │   - Status: pending, acknowledged, resolved
│   │
│   ├── booking.py            # Booking logic with confirmation flow (22 tests)
│   │   - Slot availability checking
│   │   - Conflict detection
│   │   - Duration calculations
│   │   - BOOKING CONFIRMATION FLOW:
│   │     * _generate_booking_token() - Creates 32-char hex token
│   │     * extract_pending_booking(ai_response, business_id, session_id) -> {token, booking_data, expires_in}
│   │     * confirm_pending_booking(token) -> {success, appointment_id, message}
│   │     * cancel_pending_booking(token) -> {success, message}
│   │     * get_pending_booking(token) -> booking_data or None
│   │     * cleanup_expired_bookings() - Removes expired pending bookings
│   │   - _PENDING_BOOKINGS dict stores pending bookings in memory
│   │   - Bookings expire after 5 minutes (BOOKING_EXPIRY_MINUTES)
│   │   - AI outputs <BOOKING>{json}</BOOKING>, widget shows confirmation UI
│   │   - User must explicitly confirm before booking is committed
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
│   ├── circuit_breaker.py    # Resilience patterns (23 tests)
│   │   - CircuitBreaker class with states: CLOSED, OPEN, HALF_OPEN
│   │   - CircuitState enum
│   │   - CircuitOpenError exception
│   │   - Configuration: failure_threshold, recovery_timeout, half_open_requests
│   │   - Methods:
│   │     * is_open(service) -> bool
│   │     * record_failure(service) -> bool (True if circuit just opened)
│   │     * record_success(service) -> None
│   │     * reset(service) -> None
│   │     * get_state(service) -> {service, state, failures}
│   │     * get_stats() -> {service: {failure_count, success_count}}
│   │   - Decorators:
│   │     * @with_circuit_breaker(service, breaker, fallback) - Wraps function with circuit breaker
│   │     * @retry_with_backoff(max_attempts, initial_delay, exceptions) - Retries with exponential backoff
│   │     * @resilient_call(service, max_retries, retry_delay, breaker, fallback) - Combined breaker + retry
│   │   - get_ai_circuit_breaker() -> singleton CircuitBreaker for AI calls
│   │   - Thread-safe with threading.Lock
│   │
│   ├── encryption.py         # Field-level encryption for PII (32 tests)
│   │   - Uses Fernet symmetric encryption (or XOR fallback if cryptography not installed)
│   │   - ENCRYPTION_AVAILABLE flag indicates which backend is in use
│   │   - Functions:
│   │     * encrypt_field(value) -> "ENC:..." or "OBF:..." prefixed string
│   │     * decrypt_field(value) -> original string
│   │     * is_encrypted(value) -> bool (checks for ENC: or OBF: prefix)
│   │     * encrypt_dict_fields(data, fields) -> new dict with encrypted fields
│   │     * decrypt_dict_fields(data, fields) -> new dict with decrypted fields
│   │     * hash_token(token, salt) -> hex string (SHA-256)
│   │     * verify_token_hash(token, hash, salt) -> bool
│   │     * generate_encryption_key() -> Fernet key string
│   │   - PII field constants:
│   │     * CUSTOMER_PII_FIELDS = ['name', 'email', 'phone']
│   │     * APPOINTMENT_PII_FIELDS = ['customer_name', 'phone', 'customer_email']
│   │     * SESSION_PII_FIELDS = ['phone']
│   │   - Double-encryption prevented (checks prefix before encrypting)
│   │   - Decrypting unencrypted values returns them unchanged
│   │
│   ├── validators.py         # Input validation (68 tests)
│   │   - validate_email(email) -> (is_valid, normalized_email, error_msg)
│   │   - validate_phone(phone) -> (is_valid, normalized_phone, error_msg)
│   │   - validate_name(name, field_name, required) -> (is_valid, cleaned_name, error_msg)
│   │   - validate_date(date_str) -> (is_valid, parsed_date, error_msg)
│   │   - validate_datetime(dt_str) -> (is_valid, parsed_datetime, error_msg)
│   │   - format_datetime(dt) -> "Jan 21, 2026 at 2:30 PM"
│   │   - format_date(dt) -> "Jan 21, 2026"
│   │   - validate_slug(slug) -> (is_valid, normalized_slug, error_msg)
│   │   - slugify(text) -> url-safe-slug
│   │   - validate_redirect_url(url, default) -> safe_url (prevents open redirect)
│   │   - validate_password(password) -> (is_valid, error_msg)
│   │     * Min 8 chars, max 128 chars
│   │     * Must contain letter and number
│   │   - safe_int(value, default, min_val, max_val) -> clamped int
│   │   - csv_escape(value) -> escaped CSV value (prevents formula injection)
│   │   - build_csv_row(values) -> "val1,val2,val3"
│   │   - validate_json_config(json_str, required_keys) -> (is_valid, parsed_dict, error_msg)
│   │   - Reserved slugs: admin, api, login, logout, static, dashboard, etc.
│   │
│   ├── knowledge.py          # Knowledge base utilities
│   │   - kb_search(business_id, query, limit) - FTS5 search
│   │
│   ├── kb.py                 # Additional KB functions
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
├── tests/                    # Test suite (284 tests total)
│   ├── conftest.py           # Pytest fixtures and configuration
│   │   - test_db fixture (temporary SQLite database)
│   │   - db_conn fixture (database connection)
│   │   - sample_business fixture (creates test business with services, hours)
│   │   - sample_session fixture (creates chat session)
│   │   - sample_user fixture (creates test user with password)
│   │   - admin_user fixture (creates admin user)
│   │   - app fixture (Flask test app)
│   │   - client fixture (Flask test client)
│   │   - authenticated_client fixture (logged-in test client)
│   │   - mock_openai fixture (mocks OpenAI API)
│   │   - mock_mailer fixture (mocks email sending)
│   │   - future_datetime fixture (next Monday at 10:00)
│   │   - booking_json fixture (sample booking data)
│   │   - Auto-cleanup fixtures for pending bookings and circuit breaker
│   │
│   ├── test_validators.py    # 68 tests for core/validators.py
│   │   - Email validation (valid, invalid, normalized, too long)
│   │   - Phone validation (digits, formatting, international)
│   │   - Name validation (required, length, control chars)
│   │   - Date/datetime validation and formatting
│   │   - Slug validation and slugify function
│   │   - Redirect URL validation (prevents open redirect)
│   │   - Password validation (length, complexity)
│   │   - safe_int with clamping
│   │   - CSV escaping (formula injection prevention)
│   │   - JSON config validation
│   │
│   ├── test_encryption.py    # 32 tests for core/encryption.py
│   │   - Field encryption/decryption
│   │   - Empty/None handling
│   │   - Double-encryption prevention
│   │   - Unicode and special characters
│   │   - is_encrypted detection
│   │   - Dict field encryption
│   │   - Token hashing and verification
│   │   - Key generation
│   │   - PII field constants
│   │
│   ├── test_circuit_breaker.py # 23 tests for core/circuit_breaker.py
│   │   - Initial state (closed)
│   │   - Circuit opens after threshold failures
│   │   - Circuit blocks requests when open
│   │   - Half-open state after recovery timeout
│   │   - Success in half-open closes circuit
│   │   - Failure in half-open reopens circuit
│   │   - Multiple services tracked independently
│   │   - @with_circuit_breaker decorator
│   │   - @retry_with_backoff decorator
│   │   - @resilient_call decorator
│   │   - Global AI circuit breaker singleton
│   │   - Thread safety
│   │
│   ├── test_sentiment.py     # 35 tests for core/sentiment.py
│   │   - Basic sentiment detection (positive, neutral, negative)
│   │   - Confusion and urgency detection
│   │   - Frustration detection (words, exclamation, CAPS)
│   │   - Human request detection ("speak to human", "real person")
│   │   - Intent detection (booking, cancellation, complaint, greeting)
│   │   - Escalation triggers
│   │   - Conversation history impact
│   │   - SentimentResult structure
│   │   - Helper functions (emoji, summarize)
│   │   - Edge cases (long messages, unicode, special chars)
│   │
│   ├── test_booking_confirmation.py # 22 tests for booking confirmation flow
│   │   - Token generation (length, uniqueness, hex format)
│   │   - Extract pending booking from AI response
│   │   - Booking tag removal from text
│   │   - Pending booking storage and expiration
│   │   - Confirm valid booking
│   │   - Confirm expired booking (fails)
│   │   - Confirm nonexistent booking (fails)
│   │   - Cancel booking
│   │   - Cleanup expired bookings
│   │   - Full flow integration tests
│   │
│   ├── test_auth.py          # 21 tests for authentication
│   │   - Email masking (_mask_email)
│   │   - Account lockout (threshold, timing, per-IP/email)
│   │   - Failed attempt counter
│   │   - User creation (valid, invalid email, weak password, invalid role)
│   │   - Password change validation
│   │   - Login integration (page load, credentials, redirect)
│   │   - Logout functionality
│   │   - Session security (dashboard requires auth)
│   │
│   ├── test_widget_api.py    # 21 tests for widget API
│   │   - /api/widget/config (requires tenant key, returns business info)
│   │   - /api/widget/session (creates session, returns welcome message)
│   │   - /api/widget/chat (requires session, message length limit)
│   │   - /api/widget/booking/confirm (requires token)
│   │   - /api/widget/booking/cancel (requires token)
│   │   - /api/widget/history (requires session)
│   │   - CORS handling (OPTIONS, headers)
│   │   - Rate limiting
│   │   - /api/widget/frame (requires tenant key)
│   │
│   └── test_booking.py       # 1 smoke test for booking commit
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

## Test Suite

### Running Tests

```bash
# Run all tests once
.venv/bin/python -m pytest tests/ -v

# Run specific test file
.venv/bin/python -m pytest tests/test_auth.py -v

# Run with coverage
.venv/bin/python -m pytest tests/ --cov=core --cov-report=html

# Run continuously (auto-reruns on file save)
.venv/bin/ptw tests/ --clear
```

### Test Summary (284 tests)

| Test File | Tests | Module Tested |
|-----------|-------|---------------|
| `test_validators.py` | 68 | Input validation, sanitization, CSV escaping |
| `test_sentiment.py` | 35 | Sentiment analysis, intent detection, escalation |
| `test_encryption.py` | 32 | Field encryption, token hashing, PII protection |
| `test_circuit_breaker.py` | 23 | Circuit breaker states, decorators, resilience |
| `test_booking_confirmation.py` | 22 | Booking tokens, confirm/cancel flow, expiration |
| `test_auth.py` | 21 | Login, lockout, user creation, password validation |
| `test_widget_api.py` | 21 | Widget endpoints, CORS, rate limiting |
| `test_booking.py` | 1 | Booking commit smoke test |

### Continuous Testing with pytest-watch

pytest-watch monitors files and automatically reruns tests when you save:

```bash
# Start continuous testing
.venv/bin/ptw tests/ --clear

# Check if watcher is running
ps aux | grep ptw

# Stop the watcher
pkill -f "ptw tests/"
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
    password_hash TEXT NOT NULL,  -- bcrypt/pbkdf2 hashed
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

## Complete Python Files List

All Python files in the project (excluding .venv):

```
# Main entry points
dashboard.py              # Flask app, registers all blueprints
main.py                   # Alternative entry point

# Blueprints (HTTP route handlers)
auth_bp.py                # /login, /logout, lockout
analytics_bp.py           # /analytics, /analytics/api/*
appointments_bp.py        # /appointments/*, /hours, /closures
chat_bp.py                # /chat, /chat/<session_id>
customers_bp.py           # /customers/*
escalations_bp.py         # /escalations/*
integrations_bp.py        # /integrations/*
kb_bp.py                  # /kb/* (knowledge base)
onboard_bp.py             # /onboard
search_bp.py              # /search
services_bp.py            # /services/*
sms_bp.py                 # SMS webhook handler (Twilio)
widget_bp.py              # /api/widget/* (embeddable widget API)

# Core modules (business logic)
core/__init__.py
core/ai.py                # AI conversation with sentiment, escalation, circuit breaker
core/authz.py             # Authorization helpers
core/booking.py           # Booking confirmation flow, slot management
core/circuit_breaker.py   # Circuit breaker pattern for resilience
core/csrf.py              # CSRF protection
core/db.py                # Database layer (SQLite with WAL)
core/encryption.py        # Field-level encryption for PII
core/escalation.py        # Human handoff system
core/ics.py               # iCalendar generation
core/integrations.py      # Integration provider registry
core/kb.py                # Knowledge base helpers
core/knowledge.py         # KB search (FTS5)
core/logger.py            # Logging configuration
core/mailer.py            # Email sending
core/observability.py     # Metrics collection, performance tracking
core/reminders.py         # Appointment reminder scheduling/sending
core/security.py          # Security utilities
core/sentiment.py         # Sentiment analysis, intent detection
core/settings.py          # Environment configuration
core/sms.py               # SMS sending via Twilio
core/tenantfs.py          # Tenant filesystem management
core/utils.py             # General utilities
core/validators.py        # Input validation, sanitization

# Adapters (external service interfaces)
adapters/__init__.py
adapters/local.py         # Local adapter
adapters/twilio.py        # Twilio SMS/voice adapter

# Providers (booking system providers)
providers/__init__.py
providers/dummy_provider.py    # Testing provider
providers/local_provider.py    # Built-in local booking

# Tools (utility scripts)
tools/backup_axis.py      # Create backups
tools/reminder_worker.py  # Background reminder daemon
tools/restore_axis.py     # Restore from backup
tools/sync_businesses.py  # Sync DB to filesystem

# Tests (284 tests total)
tests/conftest.py              # Fixtures
tests/test_auth.py             # 21 tests
tests/test_booking.py          # 1 test
tests/test_booking_confirmation.py  # 22 tests
tests/test_circuit_breaker.py  # 23 tests
tests/test_encryption.py       # 32 tests
tests/test_sentiment.py        # 35 tests
tests/test_validators.py       # 68 tests
tests/test_widget_api.py       # 21 tests

# Standalone scripts
add_kb_doc.py             # Add KB document
view_logs.py              # View application logs
view_logs_db.py           # View logs from database
```

---

## Core Module Deep Dive

### core/ai.py — AI Conversation Engine (488 lines)

**Purpose**: Generates AI receptionist responses with sentiment awareness, escalation triggers, and resilience.

**Key Features**:
- **Model Fallback Chain**: Primary (gpt-4o-mini) → Secondary (gpt-3.5-turbo)
- **Circuit Breaker Integration**: Prevents cascading failures when OpenAI is down
- **Sentiment-Aware Prompts**: Adjusts tone based on detected customer emotion
- **Automatic Escalation**: Hands off to human when triggers detected
- **RAG Integration**: Injects relevant KB snippets into prompts

**Key Functions**:
```python
process_message(user_input, business_data, state, customer_id, customer_info) -> str
# Main entry point. Returns AI reply. Updates state with history, sentiment.

process_message_with_metadata(...) -> Dict
# Same as above but returns {reply, sentiment, intent, escalated, escalation_id}

_call_ai_with_resilience(messages, max_retries=2) -> str
# Calls OpenAI with circuit breaker and model fallback

_business_prompt(bd, sentiment_context) -> str
# Builds system prompt with business info and sentiment-adaptive guidance

_kb_snippets(business_id, query, limit=3) -> List[str]
# Fetches relevant KB entries for RAG

increment_failed_attempts(state) -> int
reset_failed_attempts(state) -> None
```

**Configuration**:
```python
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
FALLBACK_MODELS = [("openai", OPENAI_MODEL), ("openai", "gpt-3.5-turbo")]
FALLBACK_RESPONSE = "I'm having a little trouble right now..."
```

**Flow**:
1. Analyze sentiment of user message
2. Check if escalation should trigger
3. If escalating: create escalation, return handoff message
4. Build prompt with business info + sentiment adjustments + KB snippets
5. Call AI with circuit breaker protection
6. Return reply, update state

---

### core/booking.py — Booking Confirmation Flow (484 lines)

**Purpose**: Detects AI booking suggestions, manages pending bookings, handles confirmation/cancellation.

**Key Features**:
- **Pending Booking Store**: In-memory dict (use Redis in production)
- **Token-Based Confirmation**: Unique 32-char hex tokens
- **5-Minute Expiry**: Bookings expire if not confirmed
- **Slot Verification**: Re-verifies availability at confirmation time
- **Reminder Integration**: Schedules reminders after confirmation

**Key Functions**:
```python
# New Confirmation Flow (recommended)
extract_pending_booking(text, business, session_id) -> (cleaned_text, pending_data)
confirm_pending_booking(token) -> (success, message, appointment_id)
cancel_pending_booking(token) -> (success, message)
get_pending_booking(token) -> booking_data or None

# Legacy Auto-Commit (backward compatibility)
maybe_commit_booking(text, business, session_id) -> (updated_text, committed)
```

**Data Structures**:
```python
_PENDING_BOOKINGS: Dict[str, Dict] = {}  # token -> booking_data
PENDING_BOOKING_TTL = 300  # 5 minutes

# pending_data structure:
{
    "token": "abc123...",
    "business_id": 1,
    "session_id": 42,
    "customer_name": "John Doe",
    "phone": "555-1234",
    "email": "john@example.com",
    "service_name": "Haircut",
    "slot": "2026-01-25 14:00",
    "created_at": 1737500000.0,
    "expires_at": 1737500300.0,
}
```

---

### core/reminders.py — Appointment Reminders (556 lines) ✅ IMPLEMENTED

**Purpose**: Schedules and sends automated appointment reminders via email/SMS.

**Key Classes**:
```python
class ReminderType(Enum):
    TWENTY_FOUR_HOURS = "24h"
    ONE_HOUR = "1h"
    FIFTEEN_MINUTES = "15m"

class ReminderChannel(Enum):
    EMAIL = "email"
    SMS = "sms"

class ReminderStatus(Enum):
    PENDING = "pending"
    SENT = "sent"
    FAILED = "failed"
    CANCELLED = "cancelled"
```

**Key Functions**:
```python
schedule_reminders_for_appointment(appt_id, start_at, email, phone) -> List[int]
cancel_reminders_for_appointment(appointment_id) -> int
reschedule_reminders_for_appointment(appt_id, new_start_at, email, phone) -> List[int]
get_due_reminders(limit=100) -> List[Dict]
process_due_reminders(batch_size=50) -> Dict[str, int]  # For worker
send_reminder(reminder) -> (success, error_message)
generate_email_reminder(reminder) -> {subject, body}
generate_sms_reminder(reminder) -> str  # Max 160 chars
```

**Default Schedule**:
```python
DEFAULT_REMINDER_SCHEDULE = [
    (ReminderType.TWENTY_FOUR_HOURS, ReminderChannel.EMAIL),
    (ReminderType.ONE_HOUR, ReminderChannel.SMS),
]
```

---

### core/observability.py — Metrics & Monitoring (424 lines) ✅ IMPLEMENTED

**Purpose**: In-memory metrics collection for monitoring performance.

**Key Class**:
```python
class MetricsCollector:
    def inc_counter(name, labels, value=1)
    def observe_histogram(name, value, labels)
    def set_gauge(name, value, labels)
    def get_counter(name, labels) -> int
    def get_histogram_stats(name, labels) -> Dict  # count, sum, avg, min, max, p50, p95, p99
    def get_gauge(name, labels) -> float
    def get_all_metrics() -> Dict
```

**Standard Metric Names** (Metrics class):
```python
HTTP_REQUESTS_TOTAL, HTTP_REQUEST_DURATION, HTTP_ERRORS_TOTAL
AI_REQUESTS_TOTAL, AI_REQUEST_DURATION, AI_TOKENS_USED, AI_ERRORS_TOTAL
CONVERSATIONS_TOTAL, BOOKINGS_TOTAL, ESCALATIONS_TOTAL
ACTIVE_SESSIONS
JOBS_PROCESSED, JOBS_FAILED, JOB_DURATION
```

**Decorators**:
```python
@timed(metric_name, labels)  # Time function execution
@counted(metric_name, labels)  # Count function calls
@instrumented(counter, histogram, error_counter, labels)  # Full instrumentation
```

**Context Manager**:
```python
with RequestTracker("GET", "/api/chat") as tracker:
    # handle request
    tracker.set_status(200)
```

---

### widget_bp.py — Widget API (595 lines)

**Purpose**: Embeddable chat widget API with CORS, rate limiting, tenant auth.

**Endpoints**:
```
GET  /api/widget/config       # Widget configuration
POST /api/widget/session      # Create chat session
POST /api/widget/chat         # Send message, get AI reply
POST /api/widget/booking/confirm  # Confirm pending booking
POST /api/widget/booking/cancel   # Cancel pending booking
GET  /api/widget/history      # Get conversation history
GET  /api/widget/frame        # Widget iframe HTML
```

**Security**:
- **Tenant Key Auth**: `X-Tenant-Key` header required
- **CORS Validation**: Only allowed_domains can access
- **Rate Limiting**: 30 requests per 60 seconds per tenant+IP
- **Message Limit**: Max 2000 characters

**Chat Response Format**:
```json
{
  "reply": "AI response text",
  "pending_booking": {
    "token": "abc123...",
    "customer_name": "John",
    "phone": "555-1234",
    "service": "Haircut",
    "datetime": "2026-01-25 14:00",
    "expires_in": 300
  }
}
```

---

### tools/reminder_worker.py — Background Worker

**Purpose**: Daemon that processes due reminders periodically.

**Usage**:
```bash
.venv/bin/python tools/reminder_worker.py
```

**Behavior**:
- Runs every 60 seconds
- Processes up to 50 due reminders per batch
- Sends via email/SMS
- Marks as sent or failed
- Logs statistics

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
│  - Circuit breaker protection           │
└─────────────────────────────────────────┘
    │
    ▼
AI Response (may contain <BOOKING> tag)
    │
    ▼
┌─────────────────────────────────────────┐
│  Booking Confirmation Flow              │
│  - If <BOOKING> tag detected:           │
│    → Extract booking data               │
│    → Generate confirmation token        │
│    → Store in _PENDING_BOOKINGS         │
│    → Return pending_booking to widget   │
│  - Widget shows confirmation UI         │
│  - User confirms → commit to database   │
│  - User cancels → discard booking       │
│  - Expires after 5 minutes              │
└─────────────────────────────────────────┘
```

### Booking Confirmation Flow (Implemented)

The AI no longer auto-commits bookings. Instead:

1. **AI outputs booking tag**: `<BOOKING>{"name":"John","phone":"555-1234",...}</BOOKING>`
2. **extract_pending_booking()** parses the tag and stores booking in memory with a token
3. **Widget receives** `{reply: "...", pending_booking: {token, data, expires_in}}`
4. **Widget shows confirmation UI** with booking details
5. **User confirms** → `POST /api/widget/booking/confirm` with token
6. **confirm_pending_booking()** validates token, checks slot, commits to database
7. **Or user cancels** → `POST /api/widget/booking/cancel` with token
8. **Bookings expire** after 5 minutes if not confirmed

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

### Intent Detection Order

The sentiment module checks intents in this order (first match wins):
1. COMPLAINT - if complaint patterns match
2. BOOKING - if "book", "appointment", or "schedule" in message
3. CANCELLATION - if "cancel", "reschedule", or "change" (without booking keywords)
4. GRATITUDE/FAREWELL - if positive + thank/bye words
5. GREETING - if hello/hi/hey words
6. INQUIRY - default for questions

---

## Security Features

### Authentication
- Session-based authentication
- bcrypt/pbkdf2 password hashing (Python 3.9 compatible)
- 4-hour session timeout
- CSRF protection on all forms
- **Account lockout**: 5 failed attempts → 15 minute lockout
- Per-email AND per-IP tracking for lockout

### Account Lockout System (auth_bp.py)
```python
MAX_FAILED_ATTEMPTS = 5
LOCKOUT_DURATION_MINUTES = 15

# Functions:
check_account_lockout(email, ip) -> (is_locked, remaining_seconds)
record_failed_attempt(email, ip) -> (attempt_count, is_now_locked)
clear_failed_attempts(email, ip) -> None
```

### PII Protection
- **Email masking in logs**: `_mask_email("john@example.com")` → `j***@e***.com`
- **Field-level encryption** (core/encryption.py):
  - Encrypt customer names, emails, phones before storage
  - Decrypt on retrieval
  - Uses Fernet (AES-128) or XOR fallback

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
- CORS-enabled for allowed domains only
- Separate CSP for iframe embedding
- Rate limiting per tenant key
- Message length limit (2000 chars)

### Input Validation (core/validators.py)
- Email format validation and normalization
- Phone number validation (7-20 digits)
- Name validation (2-100 chars, no control chars)
- Slug validation (reserved words blocked)
- **Open redirect prevention**: `validate_redirect_url()` only allows relative URLs
- **CSV formula injection prevention**: `csv_escape()` prefixes dangerous chars
- **Password complexity**: min 8 chars, must have letter + number

### Circuit Breaker (core/circuit_breaker.py)
Prevents cascading failures when external services (like OpenAI) are down:
- **CLOSED**: Normal operation, requests pass through
- **OPEN**: Service failing, requests blocked (returns fallback)
- **HALF_OPEN**: Testing if service recovered

```python
breaker = CircuitBreaker(failure_threshold=5, recovery_timeout=60)

@with_circuit_breaker("openai", breaker=breaker, fallback=lambda: "Service unavailable")
def call_openai():
    ...
```

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
- `GET /api/widget/config` - Returns widget configuration and business info
- `POST /api/widget/session` - Creates new chat session, returns session_id and welcome message
- `POST /api/widget/chat` - Send message, get AI reply
  - Headers: `X-Tenant-Key`, `X-Session-ID`
  - Body: `{"message": "..."}`
  - Response: `{"reply": "...", "sentiment": "...", "pending_booking": {...}}`
- `POST /api/widget/booking/confirm` - Confirm pending booking
  - Body: `{"token": "..."}`
  - Response: `{"success": true, "appointment_id": 123}`
- `POST /api/widget/booking/cancel` - Cancel pending booking
  - Body: `{"token": "..."}`
  - Response: `{"success": true}`
- `GET /api/widget/history` - Get conversation history
- `GET /api/widget/frame` - Widget iframe HTML

---

## Development Notes

### Running the Server
```bash
cd "/Users/paulomartinez/AxisAI"
.venv/bin/python -m flask --app dashboard run --host=0.0.0.0 --port=5050
```

### Running Tests
```bash
# All tests
.venv/bin/python -m pytest tests/ -v

# Specific file
.venv/bin/python -m pytest tests/test_sentiment.py -v

# With coverage
.venv/bin/python -m pytest tests/ --cov=core

# Continuous (watches for changes)
.venv/bin/ptw tests/ --clear
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
cd "/Users/paulomartinez/AxisAI"
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
- Check circuit breaker state (may be open after failures)

### Tests failing
```bash
# Run with verbose output
.venv/bin/python -m pytest tests/ -v --tb=long

# Run specific failing test
.venv/bin/python -m pytest tests/test_auth.py::TestLoginIntegration -v
```

### pytest-watch not running
```bash
# Check if running
ps aux | grep ptw

# Kill and restart
pkill -f "ptw tests/"
.venv/bin/ptw tests/ --clear
```

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
9. **Booking Confirmation Flow** - AI no longer auto-commits bookings; user must confirm
10. **Account Lockout** - 5 failed login attempts → 15 minute lockout
11. **Circuit Breaker** - Resilience pattern for external API calls
12. **Field Encryption** - PII fields can be encrypted at rest
13. **Comprehensive Test Suite** - 284 tests covering all core modules
14. **Continuous Testing** - pytest-watch for auto-running tests on file save

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

## Strategic Roadmap (18 Months)

> This roadmap transforms AxisAI from a chat-only MVP into a comprehensive, multi-channel AI receptionist platform capable of competing with market leaders like Smith.ai, Ruby, and Synthflow.

### Market Opportunity

**Market Size**:
- AI receptionist market: $10.4B (2024) → $154.8B (2034)
- Growth rate: 31% CAGR
- AI can reduce agent labor costs by $80 billion globally (Gartner)

**Customer Expectations (2026)**:
- 51% of customers prefer AI for immediate service
- 41% say 24/7 availability is top benefit
- Hybrid AI+human preferred for complex issues
- Calendar integration is critical (7.7% of calls are scheduling)
- Appointment reminders reduce no-shows by 20-40%

### Current State vs Competition

**What We Have (Strengths)**:
| Feature | Status | Quality |
|---------|--------|---------|
| Multi-tenant architecture | ✅ Done | Production-ready |
| Chat widget (embeddable) | ✅ Done | Good |
| AI conversation (GPT-4o-mini) | ✅ Done | Basic |
| Sentiment analysis + escalation | ✅ Done | Good |
| Knowledge base (RAG) | ✅ Done | Good |
| Appointment booking | ✅ Done | Needs improvement |
| Customer CRM | ✅ Done | Basic |
| Analytics dashboard | ✅ Done | Basic |
| Human handoff system | ✅ Done | Good |
| Booking confirmation flow | ✅ Done | Good |
| Circuit breaker resilience | ✅ Done | Good |
| Field encryption for PII | ✅ Done | Good |
| Account lockout security | ✅ Done | Good |
| Comprehensive test suite | ✅ Done | 284 tests |

**Critical Gaps (vs Competitors)**:
| Gap | Competitor Standard | Priority |
|-----|---------------------|----------|
| Voice/phone calls | All top competitors | Critical |
| SMS/text channel | Smith.ai, Ruby | Critical |
| Calendar sync (Google/Outlook) | Universal | Critical |
| Automated reminders | Standard | High |
| Payment processing | Smith.ai, Ruby | Medium |
| CRM integrations | All enterprise | Medium |
| Multi-language | Growing demand | Medium |
| WhatsApp/social | Emerging | Lower |

---

### Phase 1: Foundation Strengthening (Months 1-3)

#### 1.1 Booking Confirmation Loop ✅ COMPLETED
- AI outputs `<CONFIRM_BOOKING>` instead of auto-committing
- Widget shows confirmation UI, user must explicitly confirm
- 5-minute cancellation window
- **Success Metric**: Booking completion rate > 85%

#### 1.2 Automated Reminder System (TODO)
**Problem**: `reminders` table exists but no worker process

**New Files**:
- `core/reminders.py` - Reminder scheduling logic
- `tools/reminder_worker.py` - Background daemon
- `core/sms.py` - SMS sending via Twilio

**Send at**: 24h, 2h, 15m before appointment (Email + SMS)
**Success Metric**: No-show rate < 10%

#### 1.3 Multi-Model Support & Fallback (TODO)
**Problem**: Hardcoded to GPT-4o-mini only

**Solution**:
- Use `OPENAI_MODEL` setting (already defined)
- Fallback chain: Primary → Backup → Emergency
- Support Claude, GPT-4, GPT-4-mini
- Model-specific prompt tuning

**Success Metric**: AI availability > 99.9%

#### 1.4 Enhanced Analytics (TODO)
- Conversation resolution rate
- Average turns to booking
- Top unanswered questions (KB gaps)
- Sentiment trends over time

---

### Phase 2: Channel Expansion (Months 3-6)

#### 2.1 SMS/Text Channel (Twilio)
**New Files**:
- `sms_bp.py` - Incoming webhook handler
- `core/sms.py` - Twilio SMS client wrapper

**Settings Required**:
```python
TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN")
TWILIO_PHONE_NUMBER = os.getenv("TWILIO_PHONE_NUMBER")
```

**Success Metric**: SMS response rate > 40%

#### 2.2 Voice AI Channel
**Recommended Approach**: Retell AI Integration ($0.07/minute)
- Pre-built templates, real-time voice
- Much faster than building from scratch

**Alternative (Build Later)**: Twilio Voice + OpenAI Whisper + ElevenLabs

**New Files**:
- `voice_bp.py` - Voice webhook handler
- `core/voice.py` - Voice session management
- `providers/retell_provider.py` - Retell AI integration

**Success Metric**: Voice call resolution rate > 60%

#### 2.3 WhatsApp Business Channel
- Via Twilio WhatsApp API (same account as SMS)
- Rich messages support (buttons, images)

**New Files**: `whatsapp_bp.py`

---

### Phase 3: Integration Ecosystem (Months 6-9)

#### 3.1 Google Calendar 2-Way Sync
**#1 Requested Feature** - Prevents double-booking

**New Files**:
- `providers/google_calendar.py` - Calendar provider
- `gcal_bp.py` - OAuth callback routes

**Success Metric**: Zero double-bookings from sync failures

#### 3.2 Outlook Calendar Sync
Same architecture as Google, different API.

#### 3.3 CRM Integrations
**Priority**: HubSpot, Salesforce, Zoho

**Capabilities**:
- Auto-create contacts from conversations
- Log activities (calls, chats, bookings)
- Sync appointment status

**New Files**:
- `core/crm.py` - CRM provider interface
- `providers/hubspot.py`, `providers/salesforce.py`, `providers/zoho.py`

#### 3.4 Payment Processing (Stripe/Square)
Collect deposits at booking (reduces no-shows by 50%+)

**Schema Changes**:
```sql
ALTER TABLE appointments ADD COLUMN deposit_amount TEXT;
ALTER TABLE appointments ADD COLUMN payment_status TEXT;
ALTER TABLE appointments ADD COLUMN payment_id TEXT;
```

**New Files**: `core/payments.py`, `payments_bp.py`

---

### Phase 4: AI Enhancement (Months 9-12)

#### 4.1 Multi-Language Support
**Languages**: Spanish, French, Portuguese, Mandarin

- Language detection on first message
- Translate system prompts
- Store `language` preference on session

#### 4.2 Industry-Specific Templates
**Pre-built configurations for**:
- Hair Salons / Spas
- Real Estate Agencies
- Medical/Dental Clinics
- Auto Repair Shops
- Legal Services
- Fitness Studios

**Each Template Includes**:
- Industry-specific system prompts
- Pre-populated KB entries
- Common service catalog
- Typical business hours

**New Files**: `businesses/templates/{industry}.json`

#### 4.3 Advanced Intent Classification
- OpenAI function calling for structured extraction
- Better booking intent detection
- Train on real conversation data

#### 4.4 Conversation Intelligence Dashboard
- Resolution rate (booking vs escalation)
- Common unanswered questions (auto-suggest KB)
- Weekly email reports

---

### Phase 5: Enterprise & Monetization (Months 12-18)

#### 5.1 Usage-Based Billing Infrastructure
**New Tables**:
```sql
CREATE TABLE usage_records (
    id INTEGER PRIMARY KEY,
    business_id INTEGER NOT NULL,
    period TEXT NOT NULL,          -- "2026-01"
    conversations INTEGER DEFAULT 0,
    voice_minutes INTEGER DEFAULT 0,
    sms_count INTEGER DEFAULT 0,
    created_at TEXT NOT NULL
);

CREATE TABLE subscriptions (
    id INTEGER PRIMARY KEY,
    business_id INTEGER NOT NULL,
    tier TEXT NOT NULL,
    stripe_subscription_id TEXT,
    status TEXT NOT NULL,
    current_period_end TEXT
);
```

**New Files**: `core/billing.py`, `billing_bp.py`, `tools/billing_worker.py`

#### 5.2 Pricing Tiers

| Tier | Price | Conversations | Voice | SMS | Key Features |
|------|-------|---------------|-------|-----|--------------|
| **Starter** | $49/mo | 500 | - | - | Chat widget, Email alerts |
| **Professional** | $149/mo | 2,000 | 100 min | 200 | + SMS, Calendar sync |
| **Business** | $349/mo | 5,000 | 500 min | 1,000 | + Voice AI, CRM, Payments |
| **Enterprise** | Custom | Unlimited | Unlimited | Unlimited | + Custom training, SLA, API |

#### 5.3 White-Label Program
For agencies to resell under their brand:
- Custom branding (logo, colors, domain)
- Reseller dashboard for sub-accounts
- Revenue sharing via Stripe Connect

#### 5.4 Public API
```
POST /api/v1/conversations - Start conversation
GET  /api/v1/conversations/{id}/messages - Get messages
POST /api/v1/appointments - Create appointment
GET  /api/v1/customers - List customers
POST /api/v1/kb - Add knowledge entry
```

**New File**: `api_v1_bp.py`

---

### Success Metrics by Phase

| Phase | Key Metric | Target |
|-------|-----------|--------|
| 1 | Booking completion rate | > 85% |
| 1 | No-show rate | < 10% |
| 2 | Voice resolution rate | > 60% |
| 2 | SMS response rate | > 40% |
| 3 | Calendar sync adoption | > 70% of businesses |
| 3 | Double-booking incidents | 0 |
| 4 | Multi-language coverage | 5 languages |
| 4 | Escalation rate | < 8% |
| 5 | MRR growth | > 15% MoM |
| 5 | Enterprise retention | > 95% |

---

## Security & Compliance Framework

### Regulatory Landscape (2026)

**Why This Matters**:
- GDPR fines exceeded €2 billion in 2025
- CCPA 2026 introduces enhanced requirements for automated decision-making
- 12 US states now require honoring Opt-Out Preference Signals
- SOC 2 certification is baseline for B2B SaaS

### Compliance Requirements by Customer Type

| Customer Type | Required Compliance | Priority |
|---------------|---------------------|----------|
| All Businesses | GDPR, CCPA, Basic Security | Immediate |
| US Healthcare | HIPAA + BAA | Phase 2 |
| Financial Services | SOC 2 Type 2 | Phase 3 |
| EU Businesses | GDPR, EU AI Act | Phase 2 |
| Enterprise | SOC 2 + Custom Audits | Phase 4 |

### GDPR Compliance Checklist

| Requirement | Implementation | Status |
|-------------|----------------|--------|
| **Right to Access** | Export all user data as JSON | TODO |
| **Right to Erasure** | Delete user + cascade all data | TODO |
| **Right to Portability** | Export in machine-readable format | TODO |
| **Consent Management** | Explicit consent before AI processing | TODO |
| **Data Minimization** | Only collect necessary data | PARTIAL |
| **Privacy Policy** | Clear disclosure of AI use | TODO |
| **Data Breach Notification** | 72-hour notification process | TODO |

**New Files Required**:
- `privacy_bp.py` - Data export, deletion endpoints
- `core/gdpr.py` - Data export/deletion logic
- `templates/privacy_settings.html` - User privacy controls

**New Tables**:
```sql
CREATE TABLE consent_records (
    id INTEGER PRIMARY KEY,
    business_id INTEGER,
    customer_id INTEGER,
    consent_type TEXT,      -- 'ai_processing', 'marketing', 'data_retention'
    granted INTEGER,
    granted_at TEXT,
    ip_address TEXT,
    user_agent TEXT
);

CREATE TABLE data_requests (
    id INTEGER PRIMARY KEY,
    business_id INTEGER,
    customer_email TEXT,
    request_type TEXT,      -- 'export', 'delete'
    status TEXT,            -- 'pending', 'processing', 'completed'
    completed_at TEXT,
    created_at TEXT
);
```

### HIPAA Compliance (For Healthcare Customers)

| Requirement | Implementation |
|-------------|----------------|
| **BAA with Vendors** | Require from OpenAI, Twilio, Retell, hosting |
| **PHI Encryption** | AES-256 at rest, TLS 1.3 in transit |
| **Access Controls** | Role-based, audit all PHI access |
| **Audit Logs** | Immutable, 6-year retention |
| **Breach Notification** | 60-day notification to HHS |

### Security Audit Checklist (Existing Code)

| Item | Current State | Action Required |
|------|---------------|-----------------|
| Password hashing | ✅ bcrypt/pbkdf2 | None |
| Session timeout | ✅ 4hr enforced | None |
| CSRF protection | ✅ All forms | Verify API endpoints |
| Account lockout | ✅ 5 attempts | None |
| Password complexity | ✅ validate_password() | None |
| SQL injection | ✅ Parameterized queries | Audit all queries |
| XSS prevention | ⚠️ Jinja2 auto-escapes | Verify |safe usage |
| PII in logs | ✅ Partial masking | Audit all log calls |
| API rate limiting | ✅ Widget API | Add to all endpoints |
| CORS | ✅ Whitelist per tenant | None |
| Webhook verification | ❌ Missing | Add for Twilio/Stripe |
| Request size limits | ❌ Missing | Add 1MB limit |

### Pre-Production Security Checklist

Before going live with real customers:
- [ ] Run `pip-audit` - fix any vulnerable dependencies
- [ ] Run `bandit -r .` - fix any code security issues
- [ ] Change all default passwords
- [ ] Generate new FLASK_SECRET_KEY (production-only)
- [ ] Enable HTTPS (SSL certificate)
- [ ] Disable debug mode
- [ ] Set up automated backups
- [ ] Configure firewall rules
- [ ] Test account lockout works
- [ ] Test session timeout works
- [ ] Test CSRF protection works
- [ ] Test rate limiting works
- [ ] Verify no PII in logs
- [ ] Verify error pages don't leak info

---

## Production Reliability & Resilience

### Observability Stack

| Pillar | Tool Options | Purpose |
|--------|--------------|---------|
| **Metrics** | Prometheus + Grafana, Datadog | CPU, memory, latency, error rates |
| **Logs** | ELK Stack, Loki, Datadog | Structured JSON logs, error tracking |
| **Traces** | Jaeger, Datadog APM | Request flow through services |

### Dashboard Alerts to Configure

- Error rate > 1% for 5 minutes → Page on-call
- AI API latency > 5s → Warning
- AI API failures > 3 in 1 minute → Critical
- Database connections > 80% capacity → Warning
- Memory usage > 90% → Critical
- Background job queue > 100 items → Warning

### Graceful Degradation Hierarchy

When things fail, degrade gracefully:

1. **AI Model Unavailable**
   → Fall back to simpler model
   → Fall back to scripted responses
   → Collect contact info for callback

2. **Database Unavailable**
   → Return cached responses
   → Queue writes for later
   → Show "maintenance mode" message

3. **Third-Party Unavailable**
   → Queue operations for retry
   → Notify user of delay
   → Continue with available features

### Disaster Recovery Plan

| Scenario | RTO | RPO | Recovery Procedure |
|----------|-----|-----|-------------------|
| Database corruption | 1 hour | 15 min | Restore from automated backup |
| API key compromised | 30 min | 0 | Rotate keys, revoke old |
| Full service outage | 4 hours | 1 hour | Failover to backup region |
| Data breach | 24 hours | N/A | Incident response plan |

---

## External Services Required

| Service | Purpose | Est. Cost |
|---------|---------|-----------|
| Twilio | SMS, Voice, WhatsApp | Pay-per-use |
| Retell AI | Voice AI platform | $0.07/min |
| Stripe | Payments, billing | 2.9% + $0.30 |
| Google APIs | Calendar sync | Free tier |
| DeepL/Google | Translation | Pay-per-use |
| Sentry | Error tracking | Free tier |

### Infrastructure Upgrades (As We Scale)

- **Database**: SQLite → PostgreSQL when >50 tenants
- **Background Jobs**: Add Celery or APScheduler
- **Caching**: Add Redis for sessions, rate limiting
- **Hosting**: Move from dev to production (Railway, Render, or AWS)

---

## Implementation Priority Matrix

### Do First (Highest ROI)
1. ✅ Booking confirmation loop - Builds trust, reduces errors
2. Automated reminders - 20-40% no-show reduction
3. SMS channel - Many customers prefer text
4. Google Calendar sync - #1 requested integration

### Do Next (Months 3-6)
5. Voice AI (Retell integration)
6. Multi-model fallback
7. Outlook Calendar sync
8. Payment processing

### Do Later (Months 6-12)
9. CRM integrations
10. Multi-language support
11. Industry templates
12. WhatsApp channel

### Enterprise (Months 12-18)
13. Usage-based billing
14. White-label program
15. Public API
16. Advanced analytics

---

## Contacts

**Project Owner**: Paulo Martinez
**Project Name**: AI Business Utility Agent (AxisAI)
**Target Markets**: Hairdressers, Real Estate Agencies (initial), expandable to any SMB
**Competitive Positioning**: SMB-first simplicity, multi-channel coverage, seamless integrations, enterprise-grade security

---

## Module Interaction Map

### How Modules Work Together

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              HTTP REQUEST                                    │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│  dashboard.py (Flask App)                                                    │
│  - before_request: tenant isolation, session validation                     │
│  - after_request: security headers, logging                                 │
│  - Registers all blueprints                                                 │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
        ┌───────────────────────────┼───────────────────────────┐
        ▼                           ▼                           ▼
┌───────────────────┐   ┌───────────────────┐   ┌───────────────────┐
│   widget_bp.py    │   │    auth_bp.py     │   │  Other Blueprints │
│   (Widget API)    │   │   (Login/Logout)  │   │                   │
└───────────────────┘   └───────────────────┘   └───────────────────┘
        │                                                │
        │  POST /api/widget/chat                        │
        ▼                                                │
┌───────────────────┐                                   │
│   core/ai.py      │◄──────────────────────────────────┘
│  (AI Processing)  │
└───────────────────┘
        │
        ├────────────────────┬────────────────────┬────────────────────┐
        ▼                    ▼                    ▼                    ▼
┌──────────────┐    ┌──────────────┐    ┌──────────────┐    ┌──────────────┐
│core/sentiment│    │ core/kb.py   │    │core/circuit_ │    │core/escalat- │
│    .py       │    │(KB Search)   │    │  breaker.py  │    │   ion.py     │
└──────────────┘    └──────────────┘    └──────────────┘    └──────────────┘
        │                                                           │
        │ (triggers_escalation=True)                               │
        └──────────────────────────────────────────────────────────┘
                                    │
                                    ▼
                        Creates escalation record
                        Sends notification email
                        Returns handoff message


AI Response Flow (with booking):
───────────────────────────────────
core/ai.py
    │ (returns reply with <BOOKING> tag)
    ▼
widget_bp.py
    │ calls extract_pending_booking()
    ▼
core/booking.py
    │ stores in _PENDING_BOOKINGS
    │ returns {token, booking_data}
    ▼
Widget (frontend)
    │ shows confirmation UI
    ▼
User confirms → POST /api/widget/booking/confirm
    │
    ▼
core/booking.py::confirm_pending_booking()
    │ validates token
    │ re-verifies slot availability
    │ creates appointment in DB
    │ links to customer (customers_bp.find_or_create_customer)
    │
    ├─► core/reminders.py::schedule_reminders_for_appointment()
    │       schedules 24h email + 1h SMS reminders
    │
    └─► Returns success + appointment_id


Reminder Processing Flow:
─────────────────────────
tools/reminder_worker.py (daemon)
    │ runs every 60 seconds
    ▼
core/reminders.py::process_due_reminders()
    │ gets reminders where scheduled_for <= now
    ▼
core/reminders.py::send_reminder()
    │
    ├─► core/mailer.py::send_email()  (for email channel)
    │
    └─► core/sms.py::send_sms()  (for sms channel)
```

### Key Integration Points

| Module A | Module B | Integration |
|----------|----------|-------------|
| `ai.py` | `sentiment.py` | Analyzes user message before AI call |
| `ai.py` | `escalation.py` | Creates escalation when triggers detected |
| `ai.py` | `circuit_breaker.py` | Protects OpenAI calls from cascading failures |
| `ai.py` | `kb.py` | Fetches relevant KB entries for RAG |
| `ai.py` | `observability.py` | Records metrics (latency, tokens, errors) |
| `widget_bp.py` | `booking.py` | Extracts pending bookings from AI response |
| `booking.py` | `reminders.py` | Schedules reminders after confirmation |
| `booking.py` | `customers_bp.py` | Links bookings to customer records |
| `reminders.py` | `mailer.py` | Sends email reminders |
| `reminders.py` | `sms.py` | Sends SMS reminders |
| `auth_bp.py` | `encryption.py` | Could encrypt PII fields |
| All blueprints | `validators.py` | Input validation/sanitization |
| All blueprints | `db.py` | Database operations |

---

## Current Development State

### What's Running
- **pytest-watch**: Continuous testing daemon (if started with `ptw tests/ --clear`)
- **Check status**: `ps aux | grep ptw`
- **Stop**: `pkill -f "ptw tests/"`

### Test Results (as of last run)
- **Total Tests**: 284
- **Pass Rate**: 100%
- **Time**: ~7 seconds

### Known Issues / TODOs
1. **SMS sending**: `core/sms.py` exists but needs Twilio credentials configured
2. **Email sending**: `core/mailer.py` needs SMTP configuration
3. **Reminder worker**: Not running by default, needs manual start
4. **Voice AI**: Not implemented (planned for Phase 2)
5. **Calendar sync**: Not implemented (planned for Phase 3)

### Environment Setup Checklist
```bash
# 1. Navigate to project
cd "/Users/paulomartinez/AxisAI"

# 2. Activate virtual environment
source .venv/bin/activate

# 3. Ensure dependencies installed
pip install -r requirements.txt 2>/dev/null || echo "No requirements.txt"

# 4. Check .env has required keys
cat .env | grep -E "OPENAI_API_KEY|FLASK_SECRET_KEY"

# 5. Initialize database (if needed)
.venv/bin/python -c "from core.db import init_db; init_db()"

# 6. Run tests
.venv/bin/python -m pytest tests/ -v

# 7. Start server
.venv/bin/python -m flask --app dashboard run --host=0.0.0.0 --port=5050

# 8. (Optional) Start continuous testing
.venv/bin/ptw tests/ --clear
```

---

## Code Patterns & Conventions

### Database Access Pattern
```python
from core.db import get_conn, transaction

# Read operations
with get_conn() as con:
    row = con.execute("SELECT * FROM table WHERE id = ?", (id,)).fetchone()
    return dict(row) if row else None

# Write operations (with transaction)
with transaction() as con:
    cur = con.cursor()
    cur.execute("INSERT INTO table (col) VALUES (?)", (value,))
    new_id = cur.lastrowid
```

### Blueprint Pattern
```python
from flask import Blueprint, request, jsonify, g

bp = Blueprint("name", __name__, url_prefix="/prefix")

@bp.route("/endpoint", methods=["GET", "POST"])
def handler():
    # Access current business via g.business (set by dashboard.py)
    business_id = g.get("active_business_id")
    # ...
```

### Input Validation Pattern
```python
from core.validators import validate_email, validate_phone, safe_int

# Validate and normalize
is_valid, normalized, error = validate_email(email)
if not is_valid:
    return jsonify({"error": error}), 400

# Safe integer with bounds
page = safe_int(request.args.get("page"), default=1, min_val=1, max_val=100)
```

### Error Handling Pattern
```python
import logging
logger = logging.getLogger(__name__)

try:
    result = some_operation()
except SpecificError as e:
    logger.warning(f"Expected error: {e}")
    return fallback_value
except Exception as e:
    logger.error(f"Unexpected error: {e}")
    raise  # or return error response
```

### Testing Pattern
```python
import pytest
from unittest.mock import patch

class TestFeatureName:
    """Tests for specific feature."""

    def test_happy_path(self, client, sample_business):
        """Should succeed with valid input."""
        response = client.post("/endpoint", json={"key": "value"})
        assert response.status_code == 200

    def test_invalid_input(self, client):
        """Should reject invalid input."""
        response = client.post("/endpoint", json={})
        assert response.status_code == 400

# Use fixtures from conftest.py:
# - test_db: temporary database
# - sample_business: test business with services, hours
# - sample_user: test user with password
# - client: Flask test client
# - authenticated_client: logged-in client
# - mock_openai: mocked OpenAI API
```

---

## Quick Debugging Guide

### Check logs
```bash
# Application logs
tail -f logs/app.log

# Security logs
tail -f logs/security.log
```

### Database inspection
```bash
sqlite3 receptionist.db
.tables
.schema appointments
SELECT * FROM appointments ORDER BY created_at DESC LIMIT 5;
```

### Check circuit breaker state
```python
from core.circuit_breaker import get_ai_circuit_breaker
breaker = get_ai_circuit_breaker()
print(breaker.get_stats())
```

### Check pending bookings
```python
from core.booking import _PENDING_BOOKINGS
print(_PENDING_BOOKINGS)
```

### Test AI response
```python
from core.ai import process_message
from core.db import get_business_by_id

business = get_business_by_id(1)
state = {}
reply = process_message("I want to book an appointment", business, state)
print(reply)
print(state)  # Contains history, sentiment_history
```

### Test sentiment analysis
```python
from core.sentiment import analyze_sentiment
result = analyze_sentiment("I'm so frustrated with this terrible service!")
print(f"Sentiment: {result.sentiment.value}")
print(f"Intent: {result.intent.value}")
print(f"Escalation: {result.triggers_escalation}")
print(f"Frustration: {result.details['frustration_score']}")
```
