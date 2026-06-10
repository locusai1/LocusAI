# Billing Setup (Stripe) — How to Go Live

The billing code is **fully built and tested**. It runs in "not configured" mode
until you add the keys below. Nothing in the app breaks without them — the
pricing page shows, but checkout politely says billing isn't live yet.

When you're ready to take payments, do this (≈15 min, all in the Stripe dashboard):

## 1. Get your API keys
Stripe Dashboard → **Developers → API keys**:
- `STRIPE_SECRET_KEY` = `sk_live_...` (or `sk_test_...` to trial it)
- `STRIPE_PUBLISHABLE_KEY` = `pk_live_...`

## 2. Create the three products/prices
Stripe Dashboard → **Product catalogue** → create a recurring **monthly** price
for each plan, then copy each Price ID (`price_...`):

| Plan          | Price   | Env var                      |
|---------------|---------|------------------------------|
| Starter       | £49/mo  | `STRIPE_PRICE_STARTER`       |
| Professional  | £149/mo | `STRIPE_PRICE_PROFESSIONAL`  |
| Business      | £299/mo | `STRIPE_PRICE_BUSINESS`      |

(Plan names/prices/features live in `core/billing.py → PLANS` if you want to tweak.)

## 3. Create the webhook endpoint
Stripe Dashboard → **Developers → Webhooks → Add endpoint**:
- URL: `https://locusai.co.uk/api/billing/webhook`
- Events to send:
  - `checkout.session.completed`
  - `customer.subscription.created`
  - `customer.subscription.updated`
  - `customer.subscription.deleted`
  - `invoice.paid`
  - `invoice.payment_failed`
- Copy the **Signing secret** (`whsec_...`) → `STRIPE_WEBHOOK_SECRET`

## 4. Set the env vars (Railway → Variables)
```
STRIPE_SECRET_KEY=sk_live_...
STRIPE_PUBLISHABLE_KEY=pk_live_...
STRIPE_WEBHOOK_SECRET=whsec_...
STRIPE_PRICE_STARTER=price_...
STRIPE_PRICE_PROFESSIONAL=price_...
STRIPE_PRICE_BUSINESS=price_...
```
Redeploy. That's it — the "Upgrade" button and `/billing` page go live automatically.

## 5. Enable the Customer Portal (for self-serve cancel/update)
Stripe Dashboard → **Settings → Billing → Customer portal** → activate. The
"Manage subscription" button uses it.

---

### What the code does
- `core/billing.py` — plans, Stripe client (lazy), subscription DB layer, checkout,
  customer portal, webhook verification + event application.
- `billing_bp.py` — routes: `/billing`, `/billing/checkout/<plan>`, `/billing/portal`,
  `/api/billing/webhook` (CSRF-exempt, signature-verified).
- `subscriptions` table in `core/db.py`.
- Trial-banner "Upgrade" link → `/billing`.
- Tests: `tests/test_billing.py` (19 tests, Stripe mocked).

### Test it before going live
Use `sk_test_...` keys + Stripe's test card `4242 4242 4242 4242`. Use the Stripe
CLI (`stripe listen --forward-to localhost:5050/api/billing/webhook`) to replay
webhooks locally.

---

## Security review (self-audited Jun 2026)
- **Webhook authenticity**: verified with `stripe.Webhook.construct_event` against
  `STRIPE_WEBHOOK_SECRET`, using the **raw** request body. Bad/absent signature → 400.
- **CSRF**: `/api/billing/webhook` is CSRF-exempt (signature-verified instead);
  `/billing/checkout` and `/billing/portal` are CSRF-protected POSTs.
- **No IDOR**: checkout uses the logged-in user's id (`client_reference_id` +
  metadata); the Customer Portal opens only the caller's own `stripe_customer_id`.
- **Price integrity**: the amount is never trusted from the client — only the
  plan key is sent; the actual Stripe Price ID is resolved server-side from env.
- **Idempotency**: all webhook handlers are idempotent (upsert keyed by
  `stripe_subscription_id`; status sets), so duplicate/retried events are safe —
  no event-dedup table needed.
- **Premature activation guarded**: `checkout.session.completed` only marks a sub
  `active` when `payment_status` is `paid`/`no_payment_required`; otherwise it
  stays `incomplete` until `invoice.paid` / `customer.subscription.*` confirm.
- **No card data** is ever stored or logged; only Stripe IDs + status. PII is not
  sent to logs.
- **Grace period**: `past_due` keeps access during Stripe dunning retries; access
  is revoked on `canceled`.
