# Smart-Agri-Tech Backend API

Backend for a negotiation-first agricultural marketplace. Farmers list produce, vendors negotiate
prices and quantities, and every agreed deal becomes an order. The order is then tracked through
preparation, delivery, payment, settlement, reviews and disputes.

Interactive API docs: `http://localhost:8000/docs` (every endpoint is listed with its request and
response schema).

---

## Contents

1. [Features](#features)
2. [Architecture](#architecture)
3. [Repository structure](#repository-structure)
4. [Setup](#setup)
5. [Configuration](#configuration)
6. [API overview](#api-overview)
7. [Core workflows](#core-workflows)
8. [API conventions](#api-conventions)
9. [Background jobs](#background-jobs)
10. [Notifications](#notifications)
11. [Security](#security)
12. [Database, migrations and seeding](#database-migrations-and-seeding)
13. [Testing](#testing)
14. [Deployment](#deployment)
15. [Known limitations](#known-limitations)

---

## Features

| Area | What's included |
|---|---|
| **Accounts** | Registration by mobile number and/or email with OTP verification; login by email, phone or username; password reset by OTP; per-device sessions; logout of one or all devices; deactivation; deletion requests (anonymised after a grace period); TOTP MFA for admins; suspension appeals |
| **Profiles & trust** | Farmer and vendor onboarding profiles (bank/UPI details encrypted at rest); identity, farm and business verification reviewed by admins; public profiles with verification badges, completed orders, cancellation, on-time and dispute rates, and ratings shown only once enough data exists |
| **Listings** | Variety, unit, asking price, private minimum price, minimum order, quality grade, harvest/availability/expiry dates, packaging, delivery options, photos, quantity-discount tiers, certifications, drafts, pause/resume, duplicate, soft delete, stock ledger, low-stock alerts, view/inquiry stats |
| **Discovery** | Search and filters (produce, category, variety, region, price, quantity, minimum order, grade, harvest date, availability, verified farmers, verified organic, delivery option); sorting by price, recency, harvest date, rating, or best match for a quantity; saved listings with price-change alerts; favourite farmers and their new-stock feed; saved-search crop alerts |
| **Negotiation** | Versioned offers and counteroffers, expiry and expiry warnings, withdraw, reject, cancel, drafts, full history, offer comparison across farmers, a private below-minimum warning for farmers, and atomic acceptance that reserves stock |
| **Orders** | An immutable snapshot of the agreed terms; server-side totals (platform fee, tax, packaging, transport, discount); confirmation by both parties; a 12-state lifecycle; payment-term gating; cancellation policy with farmer-approved cancellation requests; status timeline; receipts and invoices; reorder |
| **Inventory** | Available, reserved and sold quantities; row-locked reservations that release on cancellation or confirmation timeout; append-only stock movement history |
| **Payments** | Razorpay checkout with server-computed amounts, signature verification, a signed webhook, reconciliation, duplicate and idempotency protection, cash/UPI/bank payments recorded by farmers, separate refund records, and farmer settlements |
| **Logistics** | Pickup and delivery plans, time windows, transporter details, dispatch with photo proof, a one-time delivery code, accepted quantity and quality, failed delivery and rescheduling |
| **Chat** | One-to-one messages linked to a listing, negotiation, order or dispute; image/PDF attachments; offer summaries posted into the chat; read receipts; unread counts; block and report; rate limiting; live delivery over WebSocket |
| **Reviews** | Overall, quality, communication, reliability and quantity-accuracy ratings after delivery; replies; reporting; admin moderation |
| **Disputes** | Evidence uploads, case thread, assignment, escalation, withdrawal, internal notes, and resolutions that create refund records (payments are never edited) |
| **Procurement** | Vendor buy requests with quality and packaging specs, farmer invitations, quotation comparison, shortlisting, negotiating from a quote, split fulfilment across farmers, and recurring supply agreements (farmer-approved) |
| **Planning** | Harvest calendar and publishing a planned harvest as a pre-harvest listing |
| **Insights** | Asking and negotiated prices reported separately (average, median, range, sample size, reliability flag); weekly trends; listing price check; vendor procurement trends; demand forecast; price-change alerts |
| **Dashboards & reports** | Farmer and vendor dashboards (booked value, realised sales and cash received kept separate); farmer, vendor and admin reports; marketplace success metrics |
| **Assistant** | Rule-based (no LLM): natural-language search over real listings, listing drafts parsed from text, negotiation summaries, counteroffer suggestions based on recorded deals, order summaries, an admin summary. It never acts on a user's behalf. |
| **Admin** | User search, suspend and reactivate, verification and appeal review, listing moderation, certification review, reports queue, review moderation, audited order adjustments, refunds, settlements, payment reconciliation, transaction monitoring, versioned platform settings, catalog management, announcements and campaigns, support tickets, audit log, metrics, manual job runs |
| **Localisation** | English and Telugu notification templates, status labels and catalog names |
| **Legacy** | Crop recommendation (`POST /api/predict/`) and the original `/inventory`, `/order`, `/vendor/orders`, `/farmer/orders` and `/order-status` endpoints, now backed by the new services |

---

## Architecture

- **Framework:** FastAPI (async), Python 3.10+ (the Docker image and CI use 3.13); gunicorn + uvicorn workers in production
- **Primary database:** PostgreSQL via SQLAlchemy 2.0. The asyncpg driver serves the API; the psycopg2 driver serves migrations and seeding.
- **OTP store:** MongoDB (default) or PostgreSQL (`OTP_STORE=postgres`)
- **Pattern:** Router → Service → Database, with dependency injection

```
Client ──HTTP/WebSocket──▶ Middleware (API version, CORS, request id + metrics, rate limit)
                           ▶ Router (validation, auth, role guard)
                           ▶ Service (business rules, row locks, audit, notifications)
                           ▶ PostgreSQL ── Alembic migrations + `python -m src.seeds`
In-process scheduler ─────▶ expiry, timeouts, auto-complete, notification delivery, recurring orders
```

Key shared modules live in `src/core/`:

| Module | Purpose |
|---|---|
| `platform_settings.py` | Versioned, admin-editable settings (fees, expiry defaults, cancellation policy, thresholds) |
| `audit.py` | Append-only audit trail |
| `idempotency.py` | `Idempotency-Key` handling for critical writes |
| `rate_limit.py` | Sliding-window rate limiting |
| `crypto.py` / `totp.py` / `otp.py` | Field encryption, admin MFA, one-time codes |
| `channels.py` | Email / SMS / push / WhatsApp providers |
| `realtime.py` | WebSocket fan-out after commit, shared across workers via PostgreSQL LISTEN/NOTIFY |
| `scheduler.py` | Background jobs |
| `storage.py` | File storage (local disk; same interface for S3-compatible stores) |
| `i18n.py` | Telugu and English templates |
| `observability.py` | Error format, request ids, metrics, `/api/v1` versioning |

Order creation and every order status change go through `src/services/order_core.py`. Stock
changes go through `src/services/inventory_core.py`.

---

## Repository structure

| Path | Responsibility |
|---|---|
| `main.py` | App, middleware, router registration, scheduler lifecycle |
| `src/routers/` | HTTP endpoints, one file per domain |
| `src/services/` | Business logic |
| `src/core/` | Cross-cutting infrastructure (see above) |
| `src/data_models/` | SQLAlchemy models; `registry.py` imports them all |
| `src/schemas/` | Pydantic request schemas |
| `src/security_utils/` | Hashing, JWT helpers, role guard |
| `src/seeds/` | Reference-data seeder and its version-controlled JSON data |
| `src/db_connections/` | PostgreSQL (sync and async), MongoDB, migration helpers |
| `src/helpers/` | Logging, SMTP, settings, serializers |
| `src/ml_models/`, `src/eda/` | Crop recommendation model and analysis scripts |
| `alembic/` | Schema migrations `000`–`004` |
| `docs/` | `seeding.md`; the legacy SQL scripts (reference only) |
| `tests/` | Pytest suite: `unit/`, `seeds/`, `api/` (end-to-end) |
| `Dockerfile`, `entrypoint.sh`, `gunicorn.conf.py`, `compose.yml` | Container image, process commands, server tuning, local stack |
| `.github/workflows/ci.yml` | Lint, tests on PostgreSQL, migration drift check, Docker build |
| `.env.example` | Every setting, with safe placeholders |

---

## Setup

```bash
git clone <repository-url> && cd smart-agri-tech
python3 -m venv venv && source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements-dev.txt                      # runtime + test/lint tools
cp .env.example .env                                     # then fill in the values
```

`.env.example` lists every setting (see [Configuration](#configuration)). At minimum set the
`POSTGRES_*` variables, `ACCESS_TOKEN`, `REFRESH_TOKEN` and `ALGORITHM`, plus either `MONGO_DB`
or `OTP_STORE=postgres`.

**Quickest start (Docker):** `docker compose up --build`. This starts PostgreSQL and MongoDB, runs
migrations and seeding once, then starts the API on `BACKEND_PORT`.

### Database

```bash
psql -U postgres -c "CREATE DATABASE smart_agri_tech;"
alembic upgrade head        # 1. schema (safe on databases created from the old SQL scripts)
python -m src.seeds         # 2. reference data: lookups, roles, states, districts (idempotent)
```

Seeding is a separate, explicit step: it doesn't run on startup or inside migrations. See
[docs/seeding.md](docs/seeding.md).

**Upgrading an existing database:** run `alembic upgrade head`. Migration `001` detects a
`market_offers` table created by the old SQL script. Migration `003` converts existing orders to
the new lifecycle and records already-deducted stock as reserved or sold. Migration `004` merges
duplicate reference rows. Back up first.

### First admin account

Registration only allows Farmer or Vendor. Register normally, then promote the account in SQL:

```sql
UPDATE users SET role_id = (SELECT id FROM roles WHERE lower(name) = 'admin')
WHERE email = 'admin@example.com';
```

Then enable MFA for it (`POST /api/auth/mfa/setup`, then `/enable`). Set `ADMIN_MFA_REQUIRED=true`
in staging and production to make MFA mandatory.

### Run

```bash
uvicorn main:smart_agri_tech_app --port 8000 --reload     # development (or: python main.py)
./entrypoint.sh serve                                      # production: gunicorn + uvicorn workers
```

---

## Configuration

Settings come from environment variables (`.env` is loaded automatically).

| Variable | Required | Default | Description |
|---|---|---|---|
| `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_HOST`, `POSTGRES_DB` | Yes | – | PostgreSQL connection |
| `POSTGRES_DB_INTERNAL_PORT` | No | `5432` | PostgreSQL port |
| `BACKEND_PORT` | No | `8000` | Port for `python main.py` |
| `ACCESS_TOKEN`, `REFRESH_TOKEN` | Yes | – | JWT signing secrets (use long random values) |
| `ALGORITHM` | Yes | – | JWT algorithm, e.g. `HS256` |
| `ACCESS_EXPIRY`, `REFRESH_EXPIRY` | No | `60`, `10080` | Token lifetimes in minutes |
| `DATA_ENCRYPTION_KEY` | Production | derived from `ACCESS_TOKEN` | Fernet key for bank, UPI and MFA secrets. Generate with `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`. **Changing it makes stored secrets unreadable.** |
| `ADMIN_MFA_REQUIRED` | No | `false` | Block admin endpoints until the admin enables MFA |
| `CORS_ALLOW_ORIGINS` | No | localhost origins | Comma-separated allowed origins |
| `OTP_STORE` | No | `mongo` | `mongo` or `postgres` |
| `MONGO_DB`, `MONGO_HOST`, `MONGO_PORT`, `MONGO_USERNAME`, `MONGO_PASSWORD`, `MONGO_AUTH_SOURCE`, `MONGO_RETRY_WRITES` | With `OTP_STORE=mongo` | – | MongoDB connection |
| `OTP_DEBUG_ECHO` | No | `false` | Return OTPs in API responses. **Development and tests only.** |
| `EMAIL_PROVIDER` | No | `smtp` if SMTP is set, else `log` | `smtp` or `log` |
| `EMAIL_SENDER_ADDRESS`, `EMAIL_SENDER_PASSWORD`, `EMAIL_SMTP_SERVER`, `EMAIL_SMTP_PORT` | With SMTP | – | SMTP settings |
| `SMS_PROVIDER`, `PUSH_PROVIDER`, `WHATSAPP_PROVIDER` | No | `log` | `log` or `webhook` |
| `SMS_WEBHOOK_URL` / `_TOKEN`, `PUSH_WEBHOOK_URL` / `_TOKEN`, `WHATSAPP_WEBHOOK_URL` / `_TOKEN` | With `webhook` | – | Gateway that receives `{to, title, body, data}` |
| `RAZORPAY_KEY_ID`, `RAZORPAY_KEY_SECRET` | For online payments | – | Without them, payment endpoints return 503 |
| `RAZORPAY_WEBHOOK_SECRET` | For webhooks | – | Verifies `X-Razorpay-Signature` |
| `UPLOAD_DIR` | No | `uploads` | Local file storage directory |
| `RATE_LIMIT_ENABLED` | No | `true` | Disable only in tests |
| `TRUST_PROXY_HEADERS` | No | `false` | Use `X-Forwarded-For` for client IPs behind a trusted proxy |
| `SCHEDULER_ENABLED` | No | `true` | Run background jobs inside the API process |
| `SCHEDULER_INTERVAL_SECONDS` | No | `60` | Job tick interval |
| `METRICS_TOKEN` | No | – | Enables `GET /metrics` when sent as `X-Metrics-Token` |
| `REALTIME_PUBSUB` | No | `true` | Fan real-time events out across worker processes and replicas via PostgreSQL LISTEN/NOTIFY |
| `API_DOCS_ENABLED` | No | `true` | Set `false` in production to hide `/docs`, `/redoc` and `/openapi.json` |
| `LOG_LEVEL` | No | `INFO` | Log level. Logs are JSON on stdout and include the request id |
| `LOG_FILE` | No | – | Also write logs to this file |
| `DB_POOL_SIZE`, `DB_MAX_OVERFLOW` | No | `10`, `20` | Connection pool per worker process |
| `DB_POOL_TIMEOUT`, `DB_POOL_RECYCLE` | No | `30`, `1800` | Seconds |
| `DB_STATEMENT_TIMEOUT_MS` | No | `30000` | Cancels runaway queries (`0` disables) |
| `WEB_CONCURRENCY` | No | `2×CPU+1` (max 8) | Gunicorn worker processes |
| `GUNICORN_TIMEOUT`, `GUNICORN_GRACEFUL_TIMEOUT`, `GUNICORN_MAX_REQUESTS`, `GUNICORN_ACCESS_LOG`, `FORWARDED_ALLOW_IPS` | No | see `gunicorn.conf.py` | Gunicorn tuning |
| `TEST_DATABASE_URL` | Tests | – | PostgreSQL server the tests may create databases on |

Marketplace rules can be changed at runtime by admins (`GET` / `PUT /api/admin/settings/{key}`).
Changes are versioned and audited:

- offer expiry and expiry warnings;
- order confirmation window and auto-complete delay;
- dispute window;
- platform fee %, who pays it, and tax % on the fee;
- partial-advance %;
- verification requirements for pay-on-delivery and high-value orders;
- upload size, minimum sample size for statistics, price-alert threshold;
- message rate, account deletion grace period;
- cancellation policy.

---

## API overview

Every path is available under both `/api/...` and `/api/v1/...`. Authenticate with
`Authorization: Bearer <access_token>`. Request and response details are in `/docs`.

| Area | Main endpoints | Who |
|---|---|---|
| Auth | `POST /api/users` (register), `/verify-otp`, `/login/`, `/login/mfa`, `/token/refresh`, `/auth/logout`, `GET/DELETE /auth/sessions`, `/auth/password-reset/request` + `/confirm`, `/auth/password/change`, `/auth/mfa/setup` + `/enable` + `/disable`, `/auth/otp/resend`, `/appeals` | Public / any user |
| Account | `GET/PUT /api/users/me`, `/users/me/contact` + `/verify`, `/users/me/deactivate`, `POST/DELETE /users/me/deletion-request` | Any user |
| Profiles | `GET /api/profile`, `PUT /profile/farmer`, `PUT /profile/vendor`, `POST/GET /verification`, `GET /users/{id}/public-profile` | Farmer / vendor |
| Files | `POST /api/files` (multipart, `purpose`), `GET/DELETE /files/{id}` | Any user, access-checked |
| Locations | `GET /api/states`, `GET /api/states/{id}/districts` | Public (needed by the registration form) |
| Catalog | `GET /api/catalog/categories`, `/units`, `/quality-standards`, `/produce`; legacy `/crops/`, `/soil/`, `/fertilizers/` (writes are admin-only) | Any user |
| Listings | `POST /api/listings`, `GET /listings/mine`, `GET/PUT/DELETE /listings/{id}`, `/stock`, `/stock-history`, `/publish`, `/pause`, `/duplicate`, `/images`, `/price-tiers`, `/certifications`, `POST/DELETE /listings/{id}/save`, `GET /listings/saved` | Farmer (vendors can save) |
| Market | `GET /api/market/` with filters and sorting | Any user |
| Negotiations | `POST /api/negotiations`, `GET /negotiations`, `/negotiations/compare`, `GET /negotiations/{id}`, `/offers`, `/send`, `/accept`, `/reject`, `/withdraw`, `/cancel` | Vendor starts; both respond |
| Orders | `POST /api/orders/direct`, `GET /orders`, `GET /orders/{id}`, `/confirm`, `/status`, `/cancel`, `/cancel-request/{approve\|decline}`, `/reorder`, `/invoices`, `GET /invoices/{id}/download` | Parties |
| Delivery | `GET/PUT /api/orders/{id}/shipment`, `/dispatch`, `/delivery/confirm`, `/delivery/failed`, `/delivery/reschedule` | Parties |
| Payments | `POST /api/order/payment`, `/order/verify-payment`, `GET /orders/{id}/payments`, `POST /orders/{id}/payments/manual`, `GET /settlements`, `POST /payments/webhook/razorpay`; legacy `/farmer|vendor/payments_history/{id}` | Vendor pays; farmer records cash |
| Chat | `POST /api/inbox/messages`, `GET /inbox/conversations`, `/inbox/conversations/{user_id}`, `/inbox/unread-count`, `POST/DELETE /users/{id}/block`, `POST /reports`, WebSocket `/api/ws?token=` | Any user |
| Notifications | `GET /api/notifications`, `/unread-count`, `PUT /read-all`, `PUT /{id}/read`, `GET/PUT /notifications/preferences`, `POST/DELETE /notifications/devices` | Any user |
| Reviews | `POST /api/reviews`, `GET /reviews/pending`, `POST /reviews/{id}/response`, `GET /reviews/user/{id}` (+ `/summary`) | Parties |
| Disputes | `POST /api/disputes`, `GET /disputes/mine`, `GET /disputes/{id}`, `/messages`, `/withdraw`, `/escalate` | Parties |
| Procurement | `POST /api/buy-requests`, `/mine`, `/{id}/invite`, `/{id}/close`, `/{id}/responses` (compare), `/responses/{id}/shortlist|negotiate|accept|reject`; farmers: `GET /buy-requests`, `POST /{id}/responses`, `/responses/mine`, `/responses/{id}/withdraw` | Vendor / farmer |
| Vendor tools | `GET/POST/DELETE /api/favourites(/{farmer_id})`, `/favourites/feed`, `/crop-alerts`, `GET /vendor/suppliers/compare` | Vendor |
| Planning | `POST /api/harvest-plans`, `/harvest-plans/calendar`, `PUT /{id}`, `/{id}/publish`; `POST/GET /recurring-orders`, `/{id}/{approve\|reject\|pause\|resume\|cancel}` | Farmer / vendor |
| Expenses | `POST/GET /api/expenses`, `/expenses/summary`, `PUT/DELETE /expenses/{id}` | Farmer |
| Insights | `GET /api/insights/prices`, `/prices/trend`, `/listings/{id}/price-check`, `/procurement`, `/demand-forecast` | Any user / role-specific |
| Dashboards & reports | `GET /api/dashboard/farmer`, `/dashboard/vendor`, `/reports/farmer`, `/reports/vendor` | Farmer / vendor |
| Assistant | `POST /api/assistant/search`, `/listing-draft`; `GET /assistant/negotiations/{id}/summary`, `/suggest-counter`, `/orders/summary`, `/admin/summary` | Role-specific |
| Support | `POST/GET /api/support/tickets`, `/support/tickets/{id}`, `/messages`; `GET /announcements` | Any user |
| Admin | `/api/admin/users`, `/verifications`, `/appeals`, `/listings`, `/certifications`, `/reports`, `/reviews/{id}/moderate`, `/orders/{id}` (+ `/cancel`, `/adjustments`, `/refunds`), `/refunds`, `/settlements`, `/payments/reconcile`, `/monitoring`, `/settings`, `/catalog/*`, `/announcements`, `/support/tickets`, `/disputes` (+ `/assign`, `/status`, `/resolve`), `/audit-logs`, `/analytics`, `/metrics/success`, `/metrics`, `/jobs/run` | Admin |
| System | `GET /`, `/health`, `/health/ready`, `/metrics` | Public / token |

---

## Core workflows

### Negotiation

```
Vendor starts (offer v1, PENDING) ──▶ recipient: accept │ reject │ counter (v2 supersedes v1, which becomes COUNTERED)
Offer author: withdraw │ either party: cancel negotiation │ scheduler: EXPIRED (a new offer can follow)
Accept ──▶ offer & listing rows locked ──▶ expiry, stock and minimum order checked ──▶ stock reserved ──▶ order created
```

- **Offer states:** `DRAFT`, `PENDING`, `COUNTERED`, `ACCEPTED`, `REJECTED`, `WITHDRAWN`, `EXPIRED`, `CANCELLED`.
- **Who can act:** only the recipient of the current `PENDING` offer can accept, reject or counter it.
- **Stale offers:** the accept call must name the `offer_id`, so a changed offer can't be accepted by mistake.
- **Private floor price:** a farmer's minimum price is never shown to vendors and never triggers automatic acceptance.

### Order lifecycle

```
pending_confirmation ─▶ confirmed ─▶ preparing ─▶ ready_for_pickup ─▶ (in_transit) ─▶ delivered ─▶ completed
        │                   │            │               │                 │             │
        └─ cancelled ◀──────┴────────────┴───────────────┘           delivery_failed   disputed ─▶ refund_pending ─▶ refunded
```

- **Confirmation:** both parties confirm the full price breakdown. Unconfirmed orders are
  cancelled after `order_confirmation_hours`, which releases the stock.
- **Payment-term gating:**

  | Terms | Rule |
  |---|---|
  | `full_advance` | Fully paid before preparation |
  | `partial_advance` | Advance paid before preparation |
  | `pay_before_dispatch` | Fully paid before dispatch |
  | `pay_on_delivery` / `cash_on_delivery` | Paid before completion |

- **Fulfilment modes:**
  - **`pickup`:** the order goes from `ready_for_pickup` straight to `delivered`.
  - **`farmer_delivery` / `third_party`:** the order goes from `preparing` to `in_transit`.
  - **`vendor_transport`:** the order passes through both `ready_for_pickup` and `in_transit`.
- **Cancellation:**
  - Before preparation: either party can cancel.
  - After preparation starts: the vendor's cancellation becomes a request the farmer approves.
  - After dispatch: only through a dispute.
  - Payments already made become refund records.
- **Proof of delivery:** the vendor gets a one-time delivery code. The farmer enters it, or the
  vendor confirms receipt directly, optionally with the accepted quantity, quality acceptance
  and a photo.
- **Completion:** creates the farmer's settlement and the invoice. Delivered, fully paid orders
  with no open dispute complete automatically after `auto_complete_days`.

### Disputes and refunds

- **States:** `open` → `under_review` / `awaiting_evidence` → `resolved` | `rejected` | `withdrawn`.
- **Order freeze:** raising a dispute on a dispatched or delivered order moves it to `disputed`.
- **Resolution types:**
  - **`full_refund` / `partial_refund`:** creates a refund record.
  - **`replacement` / `no_action`:** restores the order's previous state.
- **Refund processing:**
  - Gateway payments are refunded through Razorpay (`/api/admin/refunds/{id}/process`).
  - Cash and bank refunds are marked done with a reference.
  - Original payment records are never modified.

---

## API conventions

- **Errors:** responses keep FastAPI's `detail` and add a structured error:

  ```json
  {"detail": "...", "error": {"code": "conflict", "status": 409, "message": "...", "details": null, "request_id": "..."}}
  ```

- **Request ids:** send `X-Request-ID` or one is generated; it is echoed in responses and logs.
- **Idempotency:** send `Idempotency-Key: <uuid>` on `POST /api/orders/direct`,
  `/api/negotiations/{id}/accept` and `/api/order/payment`. A retry returns the original response;
  reusing a key with a different body returns 409.
- **Pagination:** `page` and `page_size`, with `total_records` and `total_pages` in the response.
- **Money and quantities:** exact decimals, computed on the server. Clients never send totals.
- **Language:** users set `preferred_language` (`en` / `te`); catalog endpoints also honour
  `Accept-Language`.
- **Real-time updates:** connect to `ws://host/api/ws?token=<access_token>` to receive `message`,
  `messages_read`, `notification` and `negotiation` events. Events are sent only after the data
  is committed.

---

## Background jobs

These run inside the API process (`SCHEDULER_ENABLED=true`). A PostgreSQL advisory lock ensures
only one replica runs each tick. To use a dedicated worker instead, set `SCHEDULER_ENABLED=false`
on the API and run `python -m src.core.scheduler`.

| Frequency | Jobs |
|---|---|
| Every tick (60 s) | Offer expiry warnings and expiry; order confirmation timeouts (stock released); notification delivery with retries |
| Hourly | Listing expiry and expiry warnings; auto-complete and payment reminders; recurring orders; closing past-deadline buy requests |
| Daily | Price-change alerts; anonymising accounts whose deletion grace period has passed |

Admins can trigger jobs immediately with `POST /api/admin/jobs/run {"jobs": ["expire_offers"]}`.

---

## Notifications

- **In-app:** every notification is stored and pushed over WebSocket.
- **External channels:**
  - **Security:** email + SMS; these can't be switched off.
  - **Transactional:** email, SMS and push.
  - **Reminders:** push + SMS; respect quiet hours.
  - **Promotional:** opt-in only; respect quiet hours.
- **Rules:**
  - Email and SMS go only to verified addresses.
  - Failed deliveries retry with exponential backoff, up to 5 attempts.
  - Duplicates are suppressed with dedupe keys.
- **Providers:** SMS, push and WhatsApp default to the `log` provider. Set `*_PROVIDER=webhook`
  to forward to your gateway (e.g. an Indian SMS/WhatsApp provider or an FCM bridge).

---

## Security

- **Authorisation:**
  - Every endpoint checks the role (`require_roles`) and that the record belongs to the caller.
  - Identities always come from the token, never from the request body.
- **Sessions:**
  - Each login creates a device session, and refresh tokens rotate.
  - Reusing an old refresh token revokes every session.
  - Logout and password changes revoke sessions.
  - Inactive or suspended accounts are rejected on every request.
- **Secrets:**
  - Passwords are hashed with bcrypt.
  - OTPs and delivery codes are stored only as keyed hashes.
  - Bank, UPI and MFA secrets are encrypted at rest.
  - Responses never include password hashes or the farmer's minimum price.
- **Transactions:**
  - Totals are computed on the server.
  - Stock is protected with row-level locks.
  - Critical writes accept idempotency keys.
  - Payment success is confirmed server-side (signature check, signed webhook, or reconciliation).
  - Duplicate webhook events are ignored.
- **Abuse protection:**
  - Login, OTP and registration endpoints are rate-limited per IP.
  - Chat is rate-limited per user.
  - Users can block and report others.
- **Uploads:**
  - The type is detected from the file's bytes; only JPEG, PNG, WebP and PDF are accepted.
  - Size is capped.
  - Files are served only to users related to the record they belong to.
- **Auditing:** logins, offers, orders, payments, refunds, settings and every admin action are
  written to `audit_logs`.
- **Response headers:** `X-Content-Type-Options`, `X-Frame-Options` and `Referrer-Policy` are set
  on every response.

---

## Database, migrations and seeding

| Step | Command | What it does |
|---|---|---|
| Schema | `alembic upgrade head` | `000` baseline (old schema, no-op on existing databases), `001` market offers, `002` marketplace tables, `003` full marketplace and conversion of existing data, `004` uniqueness for reference data |
| Reference data | `python -m src.seeds [--dry-run] [--only ...]` | Idempotent lookups, roles, states and districts from `src/seeds/data/*.json` |

Migration `003` also adds the default units, quality grades (A/B/C) and produce categories, which
admins can edit under `/api/admin/catalog/*`.

`docs/tables_scripts.txt` and `docs/migration_market_offers.sql` are kept for reference only.
Use Alembic and the seeder instead. Details: [docs/seeding.md](docs/seeding.md).

---

## Testing

```bash
pip install -r requirements-dev.txt
ruff check src alembic tests main.py                      # lint
pytest                                                    # unit tests (no database needed)
TEST_DATABASE_URL=postgresql+psycopg2://postgres:pass@localhost:5432/postgres pytest   # everything
```

With `TEST_DATABASE_URL` set, the session creates a throwaway database on that server, runs
`alembic upgrade head` and the seeder, runs the tests, then drops it.

| Suite | What it covers |
|---|---|
| `tests/unit` | Money rounding, TOTP (incl. the RFC 6238 vector), field encryption, OTP hashing, Telugu templates, rate limiter, order transition table, realtime payload encoding |
| `tests/seeds` | Seed-file validation, repeatability, uniqueness at database level, preservation of runtime data, rollback, dry run, command line |
| `tests/api` | End to end through HTTP on PostgreSQL. See the flows below |

The `tests/api` flows:

- **Accounts:** registration with OTP, refresh-token rotation and reuse detection, logout.
- **Privacy:** encrypted payout details; the private floor price is never shown to vendors.
- **Negotiation:** offer, counter, stale-offer protection, idempotent accept.
- **Orders:** stock reservation, immutable terms, confirmation, payment gating, cash payment,
  delivery code, completion, settlement and invoices.
- **Trust:** reviews and public trust profile.
- **Stock:** cancellation releases stock; minimum order and overselling are refused.
- **Chat:** contextual chat, blocking, WebSocket authentication.
- **Other flows:** Telugu notifications, procurement quotes, a dispute with a partial refund.
- **Role-specific endpoints:** dashboards, reports, insights and the assistant.
- **Admin:** RBAC, versioned settings, background jobs, crop prediction.

CI (`.github/workflows/ci.yml`) runs lint, the full suite against PostgreSQL 16, `alembic check`
(fails if models and migrations drift apart) and a Docker build on every push and pull request.

---

## Deployment

The image is multi-stage, runs as a non-root user and has a health check. The entrypoint takes a
command:

| Command | What it runs |
|---|---|
| `serve` (default) | Gunicorn with uvicorn workers (`gunicorn.conf.py`) |
| `migrate` | `alembic upgrade head` |
| `seed [--dry-run]` | `python -m src.seeds` |
| `worker` | Background jobs in their own process (set `SCHEDULER_ENABLED=false` on the API) |
| anything else | Run as-is, e.g. `pytest` |

```bash
docker build -t smart-agri-tech .
docker run --rm --env-file .env smart-agri-tech migrate      # 1. schema
docker run --rm --env-file .env smart-agri-tech seed         # 2. reference data
docker run -d -p 8000:8000 --env-file .env -v uploads:/data/uploads smart-agri-tech   # 3. API
```

`docker compose up --build` does the same locally: PostgreSQL 16 and MongoDB 7 with health checks,
then a one-shot migrate+seed job, then the API. `docker compose --profile tools up` adds pgAdmin.

Production checklist:

- Copy `.env.example`. Set a long random `ACCESS_TOKEN` and `REFRESH_TOKEN`, a stable
  `DATA_ENCRYPTION_KEY`, `ADMIN_MFA_REQUIRED=true`, `CORS_ALLOW_ORIGINS`, `API_DOCS_ENABLED=false`,
  `RAZORPAY_WEBHOOK_SECRET` and the provider settings.
- Leave `OTP_DEBUG_ECHO` unset.
- Run `migrate`, then `seed`, as explicit deploy steps before starting new app instances.
- Mount persistent or shared storage at `UPLOAD_DIR` (`/data/uploads` in the image).
- Put the app behind HTTPS. Set `TRUST_PROXY_HEADERS=true` and `FORWARDED_ALLOW_IPS` only behind a
  trusted proxy. Limit request body size at the proxy.
- Register `https://<host>/api/payments/webhook/razorpay` in the Razorpay dashboard.
- Size the pool: `WEB_CONCURRENCY × (DB_POOL_SIZE + DB_MAX_OVERFLOW)` must stay below PostgreSQL's
  `max_connections`. Each worker also holds one connection for real-time events.

---

## Known limitations

- **Untested paths:** Razorpay checkout, webhooks, refunds and reconciliation, SMTP, and webhook
  providers are implemented but not exercised by the tests, because they call external services.
  Test them in the provider's sandbox before going live.
- **Per-process rate limits:** each worker process keeps its own rate-limit counters. For exact
  global limits, put a shared limiter (gateway or Redis) in front. Real-time events, by contrast,
  are shared across workers and replicas through PostgreSQL LISTEN/NOTIFY.
- **No real messaging providers:** SMS, push and WhatsApp have no built-in vendor integration
  (log or webhook only). Voice input, text-to-speech and maps are client-side concerns.
- **Rule-based assistant:** it doesn't use an LLM.
- **Prices are platform-only:** market prices come from platform data only; no external market
  feed is integrated.
- **Incomplete districts:** the seed data comes from `docs/tables_scripts.txt`. Assam, Bihar and
  Mizoram have no districts there, and some lists are incomplete; extend `src/seeds/data/locations.json`.
- **Tax treatment:** platform fee tax is configurable; tax and invoicing rules for agricultural
  produce must be confirmed for your business before going live.
