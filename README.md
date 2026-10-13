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
13. [Technical reference](#technical-reference)
14. [Testing](#testing)
15. [Deployment](#deployment)
16. [Known limitations](#known-limitations)

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
| `alembic/` | Schema migrations `000`–`005` |
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
duplicate reference rows. Migration `005` adds query indexes with `CREATE INDEX CONCURRENTLY`, so
writes continue while it runs. It commits outside the migration transaction; if it is interrupted,
re-running `alembic upgrade head` rebuilds any half-built index. Back up first.

New foreign keys need an index (`tests/unit/test_schema_indexes.py` fails otherwise) unless they
point at a seeded lookup table or only record who made a change.

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
| Schema | `alembic upgrade head` | `000` baseline (old schema, no-op on existing databases), `001` market offers, `002` marketplace tables, `003` full marketplace and conversion of existing data, `004` uniqueness for reference data, `005` query indexes |
| Reference data | `python -m src.seeds [--dry-run] [--only ...]` | Idempotent lookups, roles, states and districts from `src/seeds/data/*.json` |

Migration `003` also adds the default units, quality grades (A/B/C) and produce categories, which
admins can edit under `/api/admin/catalog/*`.

`docs/tables_scripts.txt` and `docs/migration_market_offers.sql` are kept for reference only.
Use Alembic and the seeder instead. Details: [docs/seeding.md](docs/seeding.md).

---

## Technical reference

This chapter describes how each part of the platform works internally. The values given are the
code defaults.

- [Technology stack](#technology-stack)
- [Request pipeline](#request-pipeline)
- [Application lifecycle](#application-lifecycle)
- [Data access layer](#data-access-layer)
- [Data model](#data-model)
- [Indexing strategy](#indexing-strategy)
- [Concurrency and consistency](#concurrency-and-consistency)
- [Order state machine](#order-state-machine)
- [Inventory accounting](#inventory-accounting)
- [Money handling](#money-handling)
- [Authentication and sessions](#authentication-and-sessions)
- [Cryptography](#cryptography)
- [One-time passwords](#one-time-passwords)
- [Rate limiting](#rate-limiting)
- [Idempotency keys](#idempotency-keys)
- [Real-time delivery](#real-time-delivery)
- [Scheduler internals](#scheduler-internals)
- [Notification pipeline](#notification-pipeline)
- [Payments internals](#payments-internals)
- [File storage](#file-storage)
- [Platform settings reference](#platform-settings-reference)
- [Observability](#observability)
- [Localisation](#localisation)
- [Crop recommendation model](#crop-recommendation-model)
- [Seeder internals](#seeder-internals)
- [Migration history](#migration-history)

### Technology stack

All runtime versions are pinned in `requirements.txt`.

| Layer | Technology |
|---|---|
| Language | Python 3.10+ (Docker image and CI: 3.13) |
| Web framework | FastAPI 0.115.7 on Starlette 0.45.3, Pydantic 2.11 for validation, pydantic-settings for config |
| ASGI server | Uvicorn 0.34 (development); Gunicorn 23 with `uvicorn.workers.UvicornWorker` (production) |
| ORM / database | SQLAlchemy 2.0.37 on PostgreSQL 16; asyncpg 0.30 for the API, psycopg2 2.9 for migrations and the seeder |
| Migrations | Alembic 1.19 |
| Document store | MongoDB 7 through Motor 3.7 (optional, used only for OTPs) |
| Auth | python-jose (JWT, HS256 by default), passlib with bcrypt 4.2 |
| Encryption | `cryptography` 45 (Fernet: AES-128-CBC with HMAC-SHA256) |
| Payments | Razorpay SDK 1.4 |
| HTTP client | httpx 0.28 (webhook notification providers) |
| Real time | Native WebSockets (`websockets` 16), PostgreSQL LISTEN/NOTIFY for fan-out between processes |
| ML | scikit-learn 1.6 RandomForest, pandas 2.3, numpy 2.2 |
| Quality | pytest 9, ruff 0.16 (`pyproject.toml`: rules `F`, `E9`, `B006`, line length 130) |
| Packaging | Multi-stage Docker image (`python:3.13-slim`), docker compose, GitHub Actions |

The API serves 255 HTTP routes and one WebSocket route. Twelve legacy routes are marked
`deprecated`. Every route is also served under `/api/v1`.

### Request pipeline

Middleware runs outermost first:

```
ApiVersionMiddleware      rewrites /api/v1/... to /api/... (HTTP and WebSocket)
  └─ CORSMiddleware       origins from CORS_ALLOW_ORIGINS; methods GET/POST/PUT/DELETE/OPTIONS;
                          credentials allowed; exposes X-Request-ID
      └─ RequestContextMiddleware   request id, security headers, per-route metrics, 5xx logging
          └─ RateLimitMiddleware    per-IP sliding window (see Rate limiting)
              └─ Router             Pydantic validation → auth dependency → role guard → service
                  └─ Exception handlers  uniform error body for HTTPException, validation errors, unhandled errors
```

The dependency chain for a protected endpoint:

1. `OAuth2PasswordBearer` reads the token from `Authorization: Bearer`.
2. `get_db_async` opens one `AsyncSession` for the request.
3. `LoginService.get_current_active_user` decodes the token, loads the user, checks the session
   and checks the account status.
4. `require_roles(...)` checks the role. For admins it also enforces MFA when
   `ADMIN_MFA_REQUIRED=true`. It sets `user.role_name`.
5. The service applies the ownership checks.

### Application lifecycle

`main.py` defines a FastAPI `lifespan`:

- **Startup:**
  1. Start the scheduler loop as an asyncio task, if `SCHEDULER_ENABLED` is on.
  2. Open the LISTEN connection for real-time events, if `REALTIME_PUBSUB` is on.
- **Shutdown:**
  1. Signal the scheduler and wait for its current tick to finish.
  2. Close the LISTEN connection.
  3. Close the MongoDB client.
  4. Dispose both SQLAlchemy engines.

Importing `src/data_models/registry.py` registers every model, so relationships and Alembic
autogenerate always see the complete schema.

### Data access layer

`src/db_connections/database.py` defines two engines that share one `Base`:

| Engine | Driver | Used by |
|---|---|---|
| `async_engine` / `AsyncSessionLocal` | `postgresql+asyncpg` | API requests, scheduler, real-time publishing |
| `sync_engine` / `SyncSessionLocal` | `postgresql+psycopg2` | Alembic, seeder, scripts |

**Pool and connection settings:**
- Pool size, overflow, timeout and recycle come from `DB_POOL_SIZE` (10), `DB_MAX_OVERFLOW` (20),
  `DB_POOL_TIMEOUT` (30 s) and `DB_POOL_RECYCLE` (1800 s).
- `pool_pre_ping` is on for both engines.
- API connections set `application_name=smart-agri-tech-api`, so they're easy to find in
  `pg_stat_activity`.
- API connections also set `statement_timeout` from `DB_STATEMENT_TIMEOUT_MS` (30 s; `0`
  disables it).

**Sessions:**
- `autoflush=False` and `expire_on_commit=False`, so objects stay usable after commit without
  extra queries.
- `get_db_async` gives one session per request. On any exception it rolls back and re-raises
  unchanged, so a 404 or 409 keeps its status.
- Services commit explicitly. The shared cores (`order_core`, `inventory_core`) never commit; the
  caller does.

**Relationships:**
- Every relationship is declared `lazy="raise"`. An accidental lazy load fails loudly instead of
  silently issuing N+1 queries.
- Code that needs related rows loads them with `joinedload` / `selectinload` or a join.

### Data model

There are 64 tables, grouped below by domain. Every table has a surrogate integer primary key,
except `stored_files`, which uses a UUID string.

| Domain | Tables |
|---|---|
| Identity & access | `users`, `roles`, `permissions`, `role_permissions`, `user_sessions`, `device_tokens`, `otp_codes`, `account_appeals`, `user_blocks` |
| Profiles & trust | `farmer_profiles`, `vendor_profiles`, `verification_requests`, `reviews`, `reports` |
| Reference data | `miscellaneous_data` (lookup values by `category`: status, order_status, payment_status, …), `states`, `districts`, `crops`, `soil`, `fertilizers`, `produce_categories`, `units`, `quality_standards` |
| Listings & stock | `farmer_inventory` (listings), `listing_images`, `listing_price_tiers`, `listing_certifications`, `saved_listings`, `inventory_reservations`, `inventory_movements` |
| Negotiation | `negotiations`, `offers` (immutable, versioned), `market_offers` (legacy) |
| Orders & fulfilment | `orders`, `order_status_history`, `order_adjustments`, `invoices`, `shipments` |
| Money | `transactions`, `refunds`, `settlements`, `webhook_events` |
| Communication | `messages`, `notifications`, `notification_deliveries`, `notification_preferences`, `announcements` |
| Disputes & support | `disputes`, `dispute_messages`, `support_tickets`, `support_ticket_messages` |
| Procurement & planning | `buy_requests`, `buy_request_invites`, `buy_request_responses`, `recurring_orders`, `harvest_plans`, `crop_alerts`, `favourite_farmers`, `farm_expenses` |
| Platform | `platform_settings`, `platform_settings_history`, `audit_logs` (BigInteger key), `idempotency_keys`, `stored_files` |

**Integrity rules enforced by the database:**
- **One-per-entity:**
  - one review per order and reviewer (`uq_reviews_order_reviewer`), with `rating BETWEEN 1 AND 5`;
  - one shipment and one settlement per order;
  - one profile per user.
- **Versioning:** offer versions are unique per negotiation (`uq_offer_version`).
- **Unique external ids:** `order_number`, `invoice_number`, Razorpay order and payment ids,
  webhook event ids, session `jti`, device tokens.
- **Unique pairs:** saved listings, price tiers, favourites, blocks and buy-request invites.
- **Case-insensitive uniqueness:**
  - emails (partial, `lower(email)`);
  - roles, states, and districts within a state (`lower(btrim(name))`).
- **Phones:** unique (partial, `phone IS NOT NULL`).
- **Notification dedupe:** `(user_id, dedupe_key)` is unique when a dedupe key is set.

**Foreign-key delete rules:**
- Ownership links cascade.
- Optional context links use `SET NULL`; for example, a message keeps existing when its listing is
  deleted.
- Audit columns on reference tables have no foreign key, because `users` itself references
  `roles` and the constraint would be circular.

### Indexing strategy

There are 121 declared indexes. Migration `005` added most of them, built
`CONCURRENTLY`. The rules:

- **Foreign keys:** every foreign key that is queried or cascaded through has an index whose
  leading column is that key. PostgreSQL doesn't create these automatically.
  `tests/unit/test_schema_indexes.py` enforces this. The only exceptions are actor/audit columns
  (`created_by`, `reviewed_by`, `actor_id`, …) and pointers into seeded lookup tables, whose rows
  are never deleted.
- **List endpoints:** composite indexes match the filter *and* the sort, so pages come straight
  from the index. Examples: `(vendor, created_at)` for "my orders", `(farmer, updated_at)` for
  negotiations, `(user_id, updated_at)` for support tickets.
- **Job sweeps:** partial indexes match each job's predicate, so they stay tiny.

  | Index | Predicate |
  |---|---|
  | `idx_offers_pending_expiry` | `status = 'PENDING'` |
  | `idx_notification_deliveries_due` | `status = 'pending'` |
  | `idx_recurring_orders_due` | `status = 'active'` |
  | `idx_users_pending_deletion` | `deletion_requested_at IS NOT NULL AND deleted_at IS NULL` |
  | `idx_listing_available_until` | `available_until IS NOT NULL` |

- **Marketplace feed:** `idx_listing_feed_recent` on `(created_at DESC NULLS LAST, id DESC)
  WHERE status = 'active' AND deleted_at IS NULL` serves the default newest-first page without a
  sort step.
- **Login lookups:** `idx_users_user_name`, the unique email and phone indexes. The username
  lookup runs on every authenticated request.
- **Optional (`SET NULL`) links on large tables:** partial `... WHERE col IS NOT NULL` indexes,
  for example on chat context columns. They keep parent deletes fast and cost nothing for the
  NULL rows.

`alembic check` in CI fails if the models and migrations declare different indexes.

### Concurrency and consistency

| Risk | Mechanism |
|---|---|
| Overselling when two vendors accept at once | `inventory_core.lock_listing` takes `SELECT … FOR UPDATE` on the listing row before any stock change |
| Two parties acting on one order at once | `order_core.lock_order` row-locks the order for every transition |
| Accepting an offer that changed meanwhile | The accept call must name the current `offer_id`; offer and listing rows are locked |
| Double-processing a refund or settlement | `FOR UPDATE` on the refund, settlement and transaction rows |
| Concurrent settings edits | `FOR UPDATE` on the `platform_settings` row; every change is versioned in history |
| Several replicas running the same job | `pg_try_advisory_lock(7302211)` around each scheduler tick |
| Sweeps blocking user requests | Offer-expiry and recurring-order sweeps use `FOR UPDATE SKIP LOCKED` and batch limits (100–200 rows) |
| Two seeders running at once | `pg_advisory_xact_lock(7302212)` |
| Client retries creating duplicates | Idempotency keys; unique constraints as the final guard |
| Duplicate webhook delivery | `webhook_events.event_id` is unique; repeats return `{"status": "duplicate"}` |
| Duplicate notifications | Partial unique index on `(user_id, dedupe_key)` |
| Events for rolled-back data | Real-time events are queued on the session and sent only from `after_commit` |

### Order state machine

`order_core.TRANSITIONS` is the single source of truth. Each entry maps a `(from, to)` pair to the
parties allowed to make that change. `system` means the scheduler or an internal flow such as
dispute resolution.

| From → To | Allowed |
|---|---|
| `pending_confirmation` → `confirmed` | system (after both parties confirm) |
| `pending_confirmation` → `cancelled` | farmer, vendor, system, admin |
| `confirmed` → `preparing` | farmer |
| `confirmed` → `cancelled` | farmer, vendor, admin |
| `preparing` → `ready_for_pickup` / `in_transit` | farmer |
| `preparing` → `cancelled` | farmer, admin (the vendor can only request it) |
| `ready_for_pickup` → `in_transit` | farmer, vendor |
| `ready_for_pickup` → `delivered` | farmer, vendor |
| `ready_for_pickup` → `cancelled` | farmer, admin |
| `in_transit` → `delivered` | farmer, vendor |
| `in_transit` → `delivery_failed` | farmer, vendor |
| `delivery_failed` → `in_transit` / `ready_for_pickup` | farmer |
| `delivery_failed` → `cancelled` | farmer, vendor, admin |
| `delivered` → `completed` | vendor, system, admin |
| `in_transit` / `delivered` / `delivery_failed` / `completed` → `disputed` | system (raising a dispute) |
| `disputed` → `completed` / `delivered` / `refund_pending` / `cancelled` | system, admin |
| `cancelled` → `refund_pending` | system |
| `refund_pending` → `refunded` | system, admin |

**Side effects of each transition:**
- A row in `order_status_history` (from, to, actor, note).
- An audit row.
- Notifications to the other party.
- The matching stock operation:
  - cancellation → `release`;
  - full confirmation → `hold_until_fulfilment`;
  - delivery → `consume`.
- On completion, the settlement and invoice.

Payment-term gates are checked before `preparing`, `in_transit` and `completed`.

### Inventory accounting

A listing holds three quantities in its own unit:
- `weight_kg`: available (the column keeps its historical name);
- `reserved_qty`;
- `sold_qty`.

| Operation | Effect | Ledger `movement_type` |
|---|---|---|
| Create listing / increase stock | available ↑ | `add` |
| Farmer reduces stock | available ↓ (never below 0) | `adjust` |
| Accept offer / create order | available → reserved (409 if insufficient) | `reserve` |
| Cancel / confirmation timeout | reserved → available | `release` |
| Delivery | reserved → sold | `sell` |

**The ledger:** every operation appends an `inventory_movements` row. Each row records the
resulting available, reserved and sold quantities, the actor and the order reference, so the
ledger fully explains the current figures.

**Reservations:**
- A reservation (`inventory_reservations`) carries an `expires_at` until both parties confirm the
  order. From then on it is held until fulfilment.

**Listing status:**
- The status (`active` / `reserved` / `sold`) is derived from the quantities.
- Manual states (`draft`, `paused`, `expired`, `removed`, `archived`) are never overridden.
- A low-stock notification fires, once per day at most, when available stock falls to or below
  the farmer's `low_stock_threshold`.

### Money handling

**Representation:**
- Amounts and quantities are `NUMERIC(12,2)` / `NUMERIC(14,2)` in the database and `Decimal` in
  Python (`src/core/money.py`).
- `money()` rounds to two places with `ROUND_HALF_UP`.
- `to_paise()` converts rupees to integer paise for Razorpay.
- Floats are never used for money in calculations.

**Order totals** (`order_core.compute_breakdown`):

```
subtotal       = quantity × unit_price
platform_fee   = subtotal × platform_fee_percent / 100
tax            = platform_fee × tax_percent_on_fee / 100
total_payable  = subtotal + packaging + transport − discount (+ platform_fee + tax if the vendor pays the fee)
```

- If the farmer pays the fee instead, it is deducted from the farmer's settlement.
- A discount larger than the order value is rejected.
- The breakdown is frozen into `orders.terms_snapshot`.

**Running totals:** `money_summary` recomputes paid, refunded, refund-pending, adjustments,
outstanding and advance-outstanding from the records each time. No running total is stored that
could drift.

### Authentication and sessions

**Tokens** (python-jose JWTs):

| Token | Claims | Secret | Lifetime |
|---|---|---|---|
| Access | `uid` (username), `sid` (session id), `typ=access`, `iat`, `exp` | `ACCESS_TOKEN` | `ACCESS_EXPIRY` (60 min) |
| Refresh | same, `typ=refresh` | `REFRESH_TOKEN` | `REFRESH_EXPIRY` (7 days) |
| MFA challenge | `uid`, `typ=mfa` | `ACCESS_TOKEN` | 5 min |

`exp` and `iat` are computed from timezone-aware UTC. A token of the wrong `typ` is rejected, so a
refresh or MFA token can't be used as an access token.

**Sessions** (`user_sessions`):
- **Creation:** every login creates a session row: a random 128-bit `jti`, device name (from the
  `X-Device-Name` header), user agent, IP and expiry.
- **Validation:** each request checks that the session exists and isn't revoked.
- **Activity tracking:** `last_used_at` is updated at most every 5 minutes, which limits write
  load.
- **Refresh rotation:** a refresh revokes the old session and issues a new one. Presenting an
  already-rotated refresh token revokes *all* of the user's sessions and writes an
  `auth.refresh_reuse_detected` audit event.
- **Account status:** checked on every request (`active` required). Suspended accounts get 403
  with a pointer to `/api/appeals`. A self-deactivated account is reactivated by logging in.

**Login and roles:**
- **Identifiers:** username, email (case-insensitive) or phone.
- **Phone normalisation:** numbers are normalised to E.164. A 10-digit Indian number becomes
  `+91XXXXXXXXXX`.
- **Role names:** cached per process by `role_id`.

### Cryptography

| Data | Protection | Where |
|---|---|---|
| Passwords | bcrypt, 12 rounds (passlib) | `security_utils/hashing_config.py` |
| Bank account, UPI id, MFA secret | Fernet with `DATA_ENCRYPTION_KEY` (falls back to a key derived from `ACCESS_TOKEN` with a warning). Undecryptable values return `None` and are logged | `core/crypto.py` |
| OTPs, delivery codes | HMAC-SHA256 keyed with `ACCESS_TOKEN`, compared in constant time | `core/crypto.py` |
| Admin MFA | RFC 6238 TOTP: SHA-1, 6 digits, 30 s step, ±1 step tolerance, 160-bit secret, `otpauth://` provisioning URI | `core/totp.py` |
| Razorpay checkout | SDK signature verification | `services/payment_service.py` |
| Razorpay webhook | HMAC-SHA256 of the raw body with `RAZORPAY_WEBHOOK_SECRET`, compared in constant time | `services/payment_service.py` |
| Idempotency request fingerprint | SHA-256 of the canonical JSON body | `core/idempotency.py` |
| Uploaded files | SHA-256 of the content stored with the metadata | `services/files_service.py` |
| Displayed secrets | Masked to the last 4 characters | `core/crypto.mask` |

### One-time passwords

- **Format:** 6 digits from `secrets`, valid for 10 minutes, 3 attempts.
- **Lifecycle:** a wrong code decrements the attempt count. The last failed attempt deletes the
  code, and so does successful use.
- **Purposes:** `verify_email`, `verify_phone`, `password_reset`.
- **Storage:** only the HMAC is stored, either in the MongoDB `otps` collection (`OTP_STORE=mongo`)
  or in the `otp_codes` table (`OTP_STORE=postgres`, unique per identifier and purpose).
- **Delivery:** codes go through the SMS or email channel. If delivery fails, the API returns 503.
- **Debugging:** `OTP_DEBUG_ECHO=true` returns the code in the response (development and tests
  only).

### Rate limiting

`RateLimitMiddleware` keeps a sliding window per client IP. The client IP is taken from
`X-Forwarded-For` only when `TRUST_PROXY_HEADERS=true`.

| Bucket (POST/PUT, path prefix) | Limit |
|---|---|
| `/api/login` | 10 per minute |
| `/api/auth/` | 10 per minute |
| `/api/verify-otp` | 10 per minute |
| `/api/users` (registration, profile writes) | 20 per minute |
| `/api/token/refresh` | 30 per minute |
| Everything else | 300 per minute |

- **Over the limit:** the client gets `429` with a `Retry-After` header.
- **Chat:** has a separate per-user limit (`message_rate_per_minute`, default 30).
- **Scope:** counters live in process memory (see [Known limitations](#known-limitations)).
- **Tests:** `RATE_LIMIT_ENABLED=false` turns limiting off.

### Idempotency keys

These endpoints accept `Idempotency-Key`:
- `POST /api/orders/direct`
- `POST /api/negotiations/{id}/accept`
- `POST /api/order/payment`

How a key is handled (`core/idempotency.py`):

1. The key is scoped to `(user_id, endpoint, key)`, which has a unique constraint. Keys longer
   than 100 characters get `422`.
2. The request body is fingerprinted with SHA-256.
3. If the key was already used with the same fingerprint, the stored response is returned without
   running the action again.
4. If it was used with a different body, the API returns `409`. If the first request is still in
   progress, the API also returns `409`.
5. If two requests with the same key race, the unique constraint lets only one record. The loser
   rolls back its bookkeeping, and the side effect that committed first is the one that counts.

### Real-time delivery

```
service ─ queue_event(db, user_id, payload)          (stored in session.info, nothing sent yet)
        ─ db.commit() ─▶ SQLAlchemy after_commit ─▶ pubsub.publish()
                                                   ├─ SELECT pg_notify('smart_agri_realtime', {"u":…, "p":…})
                                                   │     ─▶ every worker's LISTEN connection ─▶ local sockets of user u
                                                   └─ fallback: deliver to sockets in this process
rollback ─▶ after_rollback drops the queued events
```

**Connecting:**
- **Endpoint:** `GET /api/ws?token=<access token>` (also `/api/v1/ws`). An invalid token closes
  the socket with code `4401`.
- **Keep-alive:** a client may send `ping`; the server answers `{"event": "pong"}`.
- **Multiple devices:** a user may hold several sockets, and every one receives the events.

**Event types:** `message`, `messages_read`, `notification`, `negotiation`. Payloads pass through
`jsonable_encoder`, so datetimes and decimals serialise safely.

**Fan-out across processes:**
- Each process holds one dedicated asyncpg LISTEN connection.
- Publishing uses a pooled connection, because a LISTEN connection can't run queries concurrently.
- Payloads over 7,900 bytes (NOTIFY's limit is 8,000) are delivered locally instead.
- A watchdog reconnects a dropped listener every 15 s.
- If the listener is unavailable, delivery degrades to in-process only instead of failing.

### Scheduler internals

`src/core/scheduler.py`:

| Group | Job name | What it does |
|---|---|---|
| Every tick | `expire_offers` | Warns parties about offers close to expiry, then expires due offers (`SKIP LOCKED`, 200 per tick) |
| Every tick | `confirmation_timeouts` | Cancels `pending_confirmation` orders past `confirmation_deadline` and releases their stock (100 per tick) |
| Every tick | `notifications` | Sends due external deliveries with backoff |
| Hourly | `listing_expiry` | Marks listings past `available_until` as `expired`; warns `listing_expiry_warning_days` ahead |
| Hourly | `auto_complete` | Completes delivered, fully paid orders after `auto_complete_days` if there is no open dispute; otherwise sends a payment reminder |
| Hourly | `recurring` | Creates orders for active recurring agreements whose `next_run_date` has arrived |
| Hourly | `close_buy_requests` | Closes open buy requests past `needed_by` |
| Daily | `account_deletion` | Anonymises accounts past the deletion grace period: name, contact details, password and MFA secret are cleared, sessions revoked, device tokens deleted, payout details wiped. Orders and payments are kept |
| Daily | `price_alerts` | Notifies users when the week-over-week deal price moves by `price_change_alert_percent` or more |

**How a tick runs:**
- Each tick takes the advisory lock. A replica that can't get it skips the tick.
- Each job runs in its own session. A failing job is rolled back and logged, and the other jobs
  still run.
- Hourly and daily intervals are tracked per process.

**Running jobs:**
- `POST /api/admin/jobs/run` runs named jobs immediately.
- `python -m src.core.scheduler` (`./entrypoint.sh worker`) runs the loop as a dedicated process.

### Notification pipeline

`notify_user` (in `services/notifications_service.py`):

1. Checks `dedupe_key`; returns early if the notification already exists.
2. Renders the template in the user's `preferred_language`.
3. Stores the in-app `notifications` row and queues a WebSocket event.
4. Queues one `notification_deliveries` row per external channel the category uses:

   | Category | External channels |
   |---|---|
   | `security` | email, SMS (can't be switched off) |
   | `transactional` | email, SMS, push |
   | `reminder` | push, SMS |
   | `promotional` | email, push, WhatsApp; opt-in only |

   It filters these by the user's preferences, verified email or phone, and registered device
   tokens. Reminders and promotions that arrive in quiet hours are deferred until the quiet period
   ends.

5. The scheduler sends due deliveries (`status='pending' AND next_attempt_at <= now`).
   - **On failure:** the next attempt is scheduled `2^attempts` minutes later, up to 5 attempts.
     The row is then marked `failed` with the last error.

Providers are configured in `core/channels.py`:

| Channel | Providers |
|---|---|
| Email | `smtp` (sent in a worker thread) or `log` |
| SMS, push, WhatsApp | `log` or `webhook` |

`webhook` POSTs `{to, title, body, data}` with a bearer token, a 10-second timeout, and treats any
non-2xx response as a failure.

### Payments internals

**Online payment (Razorpay):**
1. `POST /api/order/payment` works out the amount on the server from `money_summary`, according to
   the purpose:

   | Purpose | Amount |
   |---|---|
   | `auto` | The advance if one is due, otherwise the full amount |
   | `advance` | The advance outstanding |
   | `full` / `balance` | Everything outstanding |

   Payment is refused for cancelled, refunded and unconfirmed orders, and for cash-on-delivery
   orders.

2. If an unpaid gateway order for the same amount and purpose was created in the last 30 minutes,
   it is reused. This prevents duplicate checkouts.
3. Otherwise, a Razorpay order is created (in a worker thread, amount in paise) and a `pending`
   transaction is recorded.
4. The payment is confirmed by whichever of the following arrives first. Marking a payment paid is
   idempotent, so later confirmations change nothing.
   - **Client signature check:** `/order/verify-payment`, using the SDK.
   - **Signed webhook:** `/payments/webhook/razorpay`. The raw body is HMAC-verified and events
     are deduplicated by event id. On `payment.captured` / `order.paid`, the captured amount must
     match the transaction, or the event is flagged as `amount mismatch`.
   - **Reconciliation:** `/admin/payments/reconcile` queries Razorpay for gateway transactions
     still pending after 5 minutes.

**Offline and corrective payments:**
- **Offline payments:** cash, UPI and bank transfers are recorded by the farmer with a reference
  (`/orders/{id}/payments/manual`).
- **Refunds:** separate `refunds` rows (`REFUND_PENDING` → `REFUNDED` / `FAILED`). Gateway refunds
  go through the Razorpay refund API and are finalised by the `refund.processed` / `refund.failed`
  webhooks. The original transaction is never edited.
- **Settlements:** one per completed order. The net amount is computed as:

  ```
  net = gross − fee (if the farmer pays it) + adjustments − refunds − cash already collected directly
  ```

  States: `pending`, `paid` (with a payout reference) and `on_hold`. A settlement whose net amount
  is zero or less is created as `paid`.

### File storage

- **Upload:** `POST /api/files` (multipart) with a `purpose`. The maximum size is the
  `max_upload_mb` setting (5 MB); larger files get `413`.
- **Type detection:** the type comes from the file's magic bytes, not the client header. JPEG
  (`FF D8 FF`), PNG, WebP (`RIFF…WEBP`) and PDF (`%PDF-`) are recognised. Anything else gets
  `415`.
- **Allowed types per purpose:**

  | Purpose | Allowed |
  |---|---|
  | `listing_image`, `delivery_proof`, `pickup_proof` | Images |
  | `chat_attachment`, `verification_document`, `dispute_evidence`, `certification`, `support_attachment` | Images and PDF |

- **Storage key:** `<purpose>/<YYYY>/<MM>/<uuid>.<ext>` under `UPLOAD_DIR`. The storage backend
  resolves paths and refuses anything outside its root, which blocks path traversal. Replacing
  `LocalStorage` (`save`, `read`, `delete`) with an S3-compatible class needs no other change.
- **Metadata:** owner, purpose, original name, type, size, SHA-256 and storage path, in
  `stored_files`.
- **Access:**
  - The owner and admins can always read a file.
  - Listing images are public.
  - Verified certificates are readable by any user.
  - Chat attachments: the two chat participants.
  - Dispute evidence: the dispute's parties.
  - Delivery and pickup proof: the order's parties.
  - Support attachments: the ticket owner.
  - Verification documents: the owner and admins only.
  - Anyone else gets `404`, so the API never confirms whether a file exists.
- **Download headers:** files are served inline with `X-Content-Type-Options: nosniff` and
  `Cache-Control: private, max-age=3600`.
- **Deletion:** only listing images that aren't attached to a listing can be deleted. The record
  is soft-deleted and its content removed. Every other file is kept as evidence (`409`).

### Platform settings reference

These are the defaults from `core/platform_settings.py`. Admins change them through
`PUT /api/admin/settings/{key}`. The value must have the same type as the default. Every change
increments `version`, writes a `platform_settings_history` row with a reason, and is audited.

| Key | Default | Meaning |
|---|---|---|
| `offer_expiry_hours` | 48 | Default offer validity |
| `offer_max_expiry_hours` | 168 | Longest validity a user may set |
| `offer_expiry_warning_hours` | 2 | Warning lead time before expiry |
| `order_confirmation_hours` | 24 | Time to confirm before the reservation is released |
| `auto_complete_days` | 3 | Delivered → completed delay (if paid and undisputed) |
| `dispute_window_days` | 7 | Days after delivery to raise a dispute |
| `platform_fee_percent` | 0 | Commission on the produce subtotal |
| `platform_fee_payer` | `vendor` | `vendor` (added to payable) or `farmer` (deducted from settlement) |
| `tax_percent_on_fee` | 18 | Tax (e.g. GST) on the fee |
| `partial_advance_percent` | 30 | Advance for `partial_advance` terms |
| `pay_on_delivery_requires_verification` | `true` | Only verified vendors may use pay-on-delivery |
| `high_value_order_threshold` | 100000 | At or above this, both parties must be verified |
| `listing_expiry_warning_days` | 1 | Listing expiry warning lead time |
| `max_upload_mb` | 5 | Upload size limit |
| `min_sample_size` | 5 | Data points before a price statistic is marked reliable |
| `price_change_alert_percent` | 10 | Week-over-week change that triggers alerts |
| `message_rate_per_minute` | 30 | Chat messages per user per minute |
| `cancellation_policy` | see below | Who may cancel at each stage |
| `account_deletion_grace_days` | 30 | Days before a deletion request is executed |

Default cancellation policy:

| Stage | Who may cancel |
|---|---|
| `pending_confirmation`, `confirmed` | Either party |
| `preparing`, `ready_for_pickup` | The farmer, or the vendor by request |
| `in_transit`, `delivered` | Only through a dispute |

### Observability

**Logs:**
- **Format:** one JSON object per line on stdout, with `timestamp` (UTC ISO-8601), `level`, `name`,
  `message`, `module`, `function`, `line`, `request_id` (when inside a request), `exception`
  (stack trace), and any `extra={…}` fields.
- **Settings:**
  - `LOG_LEVEL` sets the level.
  - `LOG_FILE` adds a file handler.
  - `ACCESS_LOG_LEVEL` (default `WARNING`) quiets uvicorn's access log.
- **Errors:** every 5xx is logged with method, path, duration and request id.

**Request ids:**
- A caller-supplied `X-Request-ID` is accepted only if it is ASCII, at most 64 characters and
  alphanumeric (hyphens allowed). This prevents log injection.
- Otherwise a UUID4 hex id is generated.
- The id is returned in the response header and inside every error body.

**Response headers** on every response: `X-Content-Type-Options: nosniff`,
`X-Frame-Options: DENY`, `Referrer-Policy: no-referrer`.

**Metrics:**
- **Prometheus:** `GET /metrics` returns `http_requests_total{method,route,status}`,
  `http_request_duration_ms_sum{method,route}` and `process_uptime_seconds`. It is enabled only
  when `METRICS_TOKEN` is set and sent as `X-Metrics-Token`; otherwise it returns 404.
- **Admin JSON:** `GET /api/admin/metrics` returns uptime, request and 5xx totals, and per-route
  count, 5xx count and average latency.
- **Scope:** metrics are per worker process.
- **Low cardinality:** routes are labelled by template, e.g. `/api/orders/{order_id}`.

**Health:**

| Endpoint | Purpose |
|---|---|
| `GET /health` | Liveness, used by the Docker `HEALTHCHECK` |
| `GET /health/ready` | Readiness. Runs `SELECT 1` on PostgreSQL and pings MongoDB when it is the OTP store; returns 503 with per-check detail when degraded |

**Error body:** every error uses `{detail, error: {code, status, message, details, request_id}}`.

| Status | `error.code` |
|---|---|
| 400 | `bad_request` |
| 401 | `unauthorized` |
| 403 | `forbidden` |
| 404 | `not_found` |
| 409 | `conflict` |
| 413 | `payload_too_large` |
| 415 | `unsupported_media_type` |
| 422 | `validation_error` (`details` lists `{field, message}`) |
| 429 | `rate_limited` |
| 500 | `internal_error` (no internals leaked) |
| 502 | `bad_gateway` |
| 503 | `service_unavailable` |

**Audit trail:** `audit_logs` records the actor, role, action (e.g. `order.status_changed`,
`auth.refresh_reuse_detected`, `seed.applied`), entity type and id, before and after JSON, IP and
time. It is searchable at `GET /api/admin/audit-logs` by actor, entity, action prefix and date
range.

### Localisation

- **Languages:** `en` (default) and `te` (Telugu). The user's `preferred_language` selects them.
- **What is translated** (`core/i18n.py`): notification titles and bodies, order and payment
  status labels, and catalog names (`name_te` columns).
- **Catalog endpoints:** also honour `Accept-Language`.
- **Fallback:** missing translations fall back to English. Unknown language codes are normalised
  to `en`.

### Crop recommendation model

- **Endpoint:** `POST /api/predict/`
- **Model:** a scikit-learn `RandomForestClassifier`, trained by `src/ml_models/train_model.py`.
- **Inputs:** `N`, `P`, `K`, `temperature`, `humidity`, `ph`, `rainfall`.
- **Artifacts:** `model.pkl`, `scaler.pkl` and `label_encoder.pkl`. They are bundled, trusted
  files, loaded lazily once per process under a lock.
- **Inference:** the input is built as a DataFrame with the scaler's training feature names and
  order, scaled, predicted and decoded back to a crop name.
- **Failure:** returns 503 instead of a stack trace.

### Seeder internals

`python -m src.seeds` uses `src/seeds/seeder.py` and `src/seeds/data/*.json`.

**Datasets**, always applied in dependency order: `lookups` → `roles` → `states` → `districts`.

**What one run does:**
- Runs in a single transaction, under `pg_advisory_xact_lock(7302212)`, so concurrent seeders
  can't interleave.
- Matches rows by natural key, never by id: `(category, value)` for lookups, `lower(btrim(name))`
  for roles and states, and the state plus `lower(btrim(name))` for districts.
  - Missing rows are inserted.
  - Rows whose spelling differs only in case or spacing are corrected.
  - Nothing is deleted. Running it again changes nothing.
- Validates the seed files before touching the database: duplicates, empty names and length
  limits.
- Stops with an explanation if the database already holds duplicate rows. Running
  `alembic upgrade head` first (migration `004`) merges them.
- Fingerprints the seed files with a SHA-256 checksum and records it in an `audit_logs` row
  (`seed.applied`).

**CLI flags:**

| Flag | Effect |
|---|---|
| `--dry-run` | Reports the changes, then rolls back |
| `--only lookups,roles` | Seeds only the named datasets |
| `--database-url` | Uses a different database |
| `--json` | Machine-readable output |
| `--verbose` | Lists every row changed |

### Migration history

| Revision | Content |
|---|---|
| `000` | Baseline of the original SQL-script schema for fresh databases. Every statement is `CREATE … IF NOT EXISTS`, so it is a no-op on databases built from the old scripts |
| `001` | `market_offers` (legacy), skipped if the old SQL script already created it |
| `002` | First marketplace features: notifications, inbox, reviews, buy requests, favourites, crop alerts, farm expenses, disputes, listing lifecycle columns |
| `003` | Full marketplace schema: profiles, sessions, negotiations/offers, order lifecycle columns, reservations, ledger, payments/refunds/settlements, shipments, chat context, notification channels, platform, admin and support tables, catalog defaults; converts existing orders and stock |
| `004` | Merges duplicate reference rows (repointing every FK to the kept row) and adds case-insensitive unique indexes |
| `005` | Query indexes (FK coverage, list/sort composites, partial job indexes), built `CONCURRENTLY` in an autocommit block; rebuilds any index left `INVALID` by an interrupted run |

Shared migration helpers (`has_table`, `has_column`, `add_column`, `drop_column`,
`insert_if_missing`, `seed_misc`, `seed_role`) live in
`src/db_connections/migration_helpers.py`. Migrations work against both fresh databases and those
created by the legacy SQL scripts.

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
