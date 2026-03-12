# Smart-Agri-Tech Backend API

Backend service for the Smart-Agri-Tech agriculture marketplace. Connects farmers and vendors, manages crop recommendations, inventory, orders, payments, and price bargaining.

**Problem solved:** Centralizes agricultural produce listing, farmer-vendor matching, ML-based crop recommendations, and payment processing for a digital agriculture marketplace.

---

## System Architecture Overview

**Framework:** FastAPI  
**Databases:** PostgreSQL (primary), MongoDB (OTP storage)  
**Pattern:** Router → Service → Database (layered architecture with dependency injection)

```
Client Request
    → FastAPI Router (endpoint)
    → Service Layer (business logic)
    → Database (PostgreSQL async / MongoDB)
    → Response (JSON)
```

---

## Repository Structure

| Folder / File | Responsibility |
|---------------|----------------|
| `main.py` | FastAPI app, CORS, router registration, lifespan |
| `src/routers/` | API route definitions (one file per domain) |
| `src/services/` | Business logic, database access |
| `src/data_models/` | SQLAlchemy ORM models |
| `src/schemas/` | Pydantic request/response schemas |
| `src/db_connections/` | PostgreSQL (sync + async) and MongoDB connections |
| `src/security_utils/` | JWT, OAuth2, password hashing |
| `src/helpers/` | Logging, SMTP, settings (pydantic-settings) |
| `src/ml_models/` | Crop prediction model, scaler, label encoder |
| `src/eda/` | EDA scripts (data inspection, analysis) |
| `alembic/` | Database migrations |
| `docs/` | SQL scripts, table definitions |

---

## Installation Guide

### 1. Clone the repository

```bash
git clone <repository-url>
cd smart-agri-tech
```

### 2. Create virtual environment (Linux / Mac)

```bash
python3 -m venv venv
source venv/bin/activate
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

### 4. Set environment variables

Create a `.env` file in the project root:

```env
# Application
BACKEND_PORT=8000

# PostgreSQL
POSTGRES_USER=postgres
POSTGRES_PASSWORD=your_password
POSTGRES_HOST=localhost
POSTGRES_DB=smart_agri_tech
POSTGRES_DB_INTERNAL_PORT=5432

# MongoDB (OTP storage)
MONGO_USERNAME=
MONGO_PASSWORD=
MONGO_HOST=localhost
MONGO_PORT=27017
MONGO_DB=smart_agri_tech
MONGO_AUTH_SOURCE=admin
MONGO_RETRY_WRITES=true

# JWT / OAuth
ACCESS_TOKEN=your_jwt_secret_key
REFRESH_TOKEN=your_refresh_secret_key
ALGORITHM=HS256
ACCESS_EXPIRY=60
REFRESH_EXPIRY=10080

# SMTP (email / OTP)
EMAIL_SENDER_ADDRESS=your@email.com
EMAIL_SENDER_PASSWORD=your_app_password
EMAIL_SMTP_SERVER=smtp.gmail.com
EMAIL_SMTP_PORT=587

# Razorpay
RAZORPAY_KEY_ID=your_razorpay_key
RAZORPAY_KEY_SECRET=your_razorpay_secret
```

### 5. Database setup

**PostgreSQL:** Create database and run schema:

```bash
psql -U postgres -c "CREATE DATABASE smart_agri_tech;"
psql -U postgres -d smart_agri_tech -f docs/tables_scripts.txt
psql -U postgres -d smart_agri_tech -f docs/migration_market_offers.sql
```

**Or use Alembic:**

```bash
alembic upgrade head
```

**MongoDB:** Create database and `otps` collection (created automatically on first use).

### 6. Start the server

```bash
uvicorn main:smart_agri_tech_app --host 0.0.0.0 --port 8000 --reload
```

API docs: http://localhost:8000/docs

---

## API Documentation

All endpoints use prefix `/api` unless noted. Protected routes require Bearer token in `Authorization` header.

### Health Check

| Method | Endpoint | Auth | Description |
|--------|----------|------|-------------|
| GET | `/` | No | Health check |

**Response:**

```json
{
  "message": "Smart-Agri-Tech backend application is successfully running.",
  "status": "success"
}
```

---

### Authentication

| Method | Endpoint | Auth | Description |
|--------|----------|------|-------------|
| POST | `/api/login/` | No | Login (OAuth2 form: username, password) |

**Request:** `application/x-www-form-urlencoded`

- `username` (string)
- `password` (string)

**Response:**

```json
{
  "status": "success",
  "id": 1,
  "user_name": "farmer1",
  "role": "farmer",
  "access_token": "eyJ...",
  "refresh_token": "eyJ...",
  "permissions": [
    {
      "permission_name": "Crops",
      "permission_key": "crops",
      "access": ["can_read", "can_write"]
    }
  ]
}
```

**Errors:** 404 (user not found), 401 (wrong password), 403 (inactive account)

---

### Users

| Method | Endpoint | Auth | Description |
|--------|----------|------|-------------|
| POST | `/api/users` | No | Register user |
| POST | `/api/verify-otp` | No | Verify OTP and activate account |
| GET | `/api/users/{id}` | Yes | Get user by ID |
| GET | `/api/users/` | Yes | List all users |
| GET | `/api/user-status/{id}` | Yes | Toggle user active/inactive |

**POST /api/users** Request:

```json
{
  "user_name": "farmer1@example.com",
  "first_name": "John",
  "last_name": "Doe",
  "password": "secret123",
  "role_id": 1
}
```

**POST /api/verify-otp** Request:

```json
{
  "user_name": "farmer1@example.com",
  "otp": "ABC123"
}
```

**Errors:** 409 (user exists), 404 (user/OTP not found), 400 (invalid/expired OTP)

---

### Crop Prediction (ML)

| Method | Endpoint | Auth | Description |
|--------|----------|------|-------------|
| POST | `/api/predict/` | Yes | Predict crop from soil/weather features |

**Request:**

```json
{
  "N": 90,
  "P": 42,
  "K": 43,
  "temperature": 20.87,
  "humidity": 82.00,
  "ph": 6.50,
  "rainfall": 202.94
}
```

**Response:**

```json
{
  "status": "success",
  "input_features": { "...": "..." },
  "predicted_crop": "rice"
}
```

**Errors:** 500 (model/prediction error)

---

### Crops (Reference Data)

| Method | Endpoint | Auth | Description |
|--------|----------|------|-------------|
| POST | `/api/crops/` | Yes | Create crop |
| PUT | `/api/crops/` | Yes | Update crop |
| GET | `/api/crops/{id}` | Yes | Get crop by ID |
| GET | `/api/crops/` | Yes | List all crops |
| PUT | `/api/crops-status/` | Yes | Toggle crop active/inactive |

**POST /api/crops/** Request:

```json
{
  "crop_name": "Rice",
  "crop_type": "cereal",
  "description": "Paddy rice",
  "created_by": 1
}
```

**PUT /api/crops-status/** Request:

```json
{
  "id": 1,
  "updated_by": 1
}
```

**Errors:** 422 (duplicate name), 404 (crop not found)

---

### Soil (Reference Data)

| Method | Endpoint | Auth | Description |
|--------|----------|------|-------------|
| POST | `/api/soil/` | Yes | Create soil type |
| PUT | `/api/soil/` | Yes | Update soil |
| GET | `/api/soil/{id}` | Yes | Get soil by ID |
| GET | `/api/soil/` | Yes | List all soils |
| PUT | `/api/soil-status/` | Yes | Toggle soil active/inactive |

**POST /api/soil/** Request:

```json
{
  "soil_name": "Loamy",
  "soil_texture": "medium",
  "description": "Loamy soil",
  "created_by": 1
}
```

**Errors:** 422 (duplicate name), 404 (soil not found)

---

### Fertilizers (Reference Data)

| Method | Endpoint | Auth | Description |
|--------|----------|------|-------------|
| POST | `/api/fertilizers/` | Yes | Create fertilizer |
| PUT | `/api/fertilizers/` | Yes | Update fertilizer |
| GET | `/api/fertilizer/{id}` | Yes | Get fertilizer by ID |
| GET | `/api/fertilizers/` | Yes | List all fertilizers |
| PUT | `/api/fertilizers-status/` | Yes | Toggle fertilizer active/inactive |

**POST /api/fertilizers/** Request:

```json
{
  "fertilizer_name": "Urea",
  "application_method": "broadcast",
  "description": "Nitrogen fertilizer",
  "created_by": 1
}
```

**Errors:** 422 (duplicate name), 404 (fertilizer not found)

---

### Inventory (Farmer Stock)

| Method | Endpoint | Auth | Description |
|--------|----------|------|-------------|
| POST | `/api/inventory/` | Yes | Add stock listing |
| PUT | `/api/inventory/` | Yes | Update stock |
| GET | `/api/inventory/stock/{id}` | Yes | Get stock by ID |
| GET | `/api/inventory/stocks/{user_id}` | Yes | List stocks for farmer |
| DELETE | `/api/delete-stock/{id}` | Yes | Delete stock |

**POST /api/inventory/** Request:

```json
{
  "crop": 1,
  "fertilizer": 1,
  "soil": 1,
  "weight_kg": 100,
  "proposed_cost": 50,
  "description": "Organic rice",
  "created_by": 1
}
```

**Errors:** 404 (stock not found)

---

### Location

| Method | Endpoint | Auth | Description |
|--------|----------|------|-------------|
| POST | `/api/states/` | Yes | List states |
| PUT | `/api/districts/{id}` | Yes | List districts by state ID |

**Errors:** 404 (states/districts not found)

---

### Market

| Method | Endpoint | Auth | Description |
|--------|----------|------|-------------|
| GET | `/api/market/` | Yes | List all market listings (farmer inventory with details) |

**Response:** Array of listings with farmer name, state, district, crop, soil, fertilizer, weight, proposed cost.

---

### Market Offers (Price Bargaining)

| Method | Endpoint | Auth | Description |
|--------|----------|------|-------------|
| POST | `/api/market/offers` | Yes | Vendor creates bargain offer |
| GET | `/api/market/offers/farmer/{farmer_id}` | Yes | Farmer lists offers (owner only) |
| GET | `/api/market/offers/vendor/{vendor_id}` | Yes | Vendor lists own offers (owner only) |
| PUT | `/api/market/offers/{offer_id}/farmer-respond` | Yes | Farmer accept/reject/counter |
| PUT | `/api/market/offers/{offer_id}/vendor-accept` | Yes | Vendor accepts farmer counter |
| PUT | `/api/market/offers/{offer_id}/vendor-counter` | Yes | Vendor sends new offer after counter |

**POST /api/market/offers** Request:

```json
{
  "stock_id": 1,
  "vendor_offer_price": 45.5,
  "quantity_kg": 100,
  "message": "Can we do 45 per kg?"
}
```

**PUT .../farmer-respond** Request:

```json
{
  "action": "accept"
}
```
or `{"action": "reject"}` or `{"action": "counter", "counter_price": 48}`

**PUT .../vendor-counter** Request:

```json
{
  "vendor_offer_price": 47
}
```

**Errors:** 403 (not owner), 404 (offer/listing not found), 422 (invalid action/price)

---

### Orders

| Method | Endpoint | Auth | Description |
|--------|----------|------|-------------|
| POST | `/api/order/` | Yes | Create order |
| GET | `/api/vendor/orders/` | Yes | Vendor orders (query: `id`) |
| GET | `/api/farmer/orders/` | Yes | Farmer orders (query: `id`) |
| PUT | `/api/order-status/` | Yes | Update order status |

**POST /api/order/** Request:

```json
{
  "stock_id": 1,
  "vendor": 2,
  "quantity": 50
}
```

**PUT /api/order-status/** Request:

```json
{
  "order_id": 1,
  "status": "accepted"
}
```
(`status`: pending, accepted, rejected)

**Errors:** 404 (inventory not found), 422 (quantity exceeds stock)

---

### Payments

| Method | Endpoint | Auth | Description |
|--------|----------|------|-------------|
| POST | `/api/order/payment` | Yes | Create Razorpay payment order |
| POST | `/api/order/verify-payment` | Yes | Verify Razorpay payment |

**POST /api/order/payment** Request:

```json
{
  "order_id": 1,
  "amount_paid": 2500,
  "currency": "INR"
}
```

**POST /api/order/verify-payment** Request:

```json
{
  "razorpay_order_id": "order_xxx",
  "razorpay_payment_id": "pay_xxx",
  "razorpay_signature": "signature_xxx"
}
```

**Errors:** 404 (order/transaction not found), 400 (invalid signature)

---

### Payment History

| Method | Endpoint | Auth | Description |
|--------|----------|------|-------------|
| GET | `/api/farmer/payments_history/{id}` | Yes | Farmer payment history (query: `page`, `page_size`) |
| GET | `/api/vendor/payments_history/{id}` | Yes | Vendor payment history (query: `page`, `page_size`) |

**Query:** `page=1`, `page_size=10` (defaults)

**Response:**

```json
{
  "page": 1,
  "page_size": 10,
  "total_records": 25,
  "total_pages": 3,
  "data": [
    {
      "transaction_id": 1,
      "order_id": 1,
      "amount_paid": 2500,
      "currency": "INR",
      "status_value": "paid",
      "created_at": "...",
      "vendor": "Vendor Name",
      "crop_name": "Rice"
    }
  ]
}
```

**Errors:** 404 (no transactions)

---

### Miscellaneous Data

| Method | Endpoint | Auth | Description |
|--------|----------|------|-------------|
| GET | `/api/miscellaneous/{id}` | No | Get lookup value by ID |

**Errors:** 404 (not found)

---

## Authentication

**Mechanism:** JWT (OAuth2 password flow)

**Header for protected endpoints:**

```
Authorization: Bearer <access_token>
```

**Token structure:** `{"uid": "<username>", "exp": <timestamp>}`

**Expiry:** Access token 60 minutes (configurable via `ACCESS_EXPIRY`), refresh 7 days (configurable via `REFRESH_EXPIRY`).

**Roles:** `farmer`, `vendor`, etc. Permissions are returned at login and used for UI-level access control.

---

## Database

### PostgreSQL

| Table | Purpose |
|-------|---------|
| `users` | Farmers, vendors, admins |
| `roles` | Role definitions |
| `permissions`, `role_permissions` | RBAC |
| `miscellaneous_data` | Status and lookup values |
| `crops`, `soil`, `fertilizers` | Reference data |
| `states`, `districts` | Location hierarchy |
| `farmer_inventory` | Farmer produce listings |
| `orders` | Orders between farmers and vendors |
| `transactions` | Razorpay payment records |
| `market_offers` | Farmer-vendor price bargaining |

### MongoDB

| Collection | Purpose |
|------------|---------|
| `otps` | OTP for user verification (expiry, attempts) |

### Migrations

- **Alembic:** `alembic upgrade head` to apply migrations.
- **Manual SQL:** `docs/tables_scripts.txt` (base schema), `docs/migration_market_offers.sql` (market_offers).

---

## Logging and Monitoring

- **Format:** JSON (timestamp, level, message, module, function, line, exception if any).
- **Output:** Console (stdout) and `logs/app.log`.
- **Config:** `src/helpers/logging_config.py`, `JSONFormatter`.

---

## Error Handling

**HTTP errors:** `HTTPException` with `status_code` and `detail`.

**Example:**

```json
{
  "detail": "User not found: Enter valid user details"
}
```

**Common codes:** 400 (bad request), 401 (unauthorized), 403 (forbidden), 404 (not found), 422 (validation), 500 (server error).

---

## Configuration

Environment variables (via `.env` and pydantic-settings):

| Variable | Required | Description |
|----------|----------|-------------|
| `BACKEND_PORT` | Yes | Server port |
| `POSTGRES_USER` | Yes | PostgreSQL user |
| `POSTGRES_PASSWORD` | Yes | PostgreSQL password |
| `POSTGRES_HOST` | Yes | PostgreSQL host |
| `POSTGRES_DB` | Yes | PostgreSQL database |
| `POSTGRES_DB_INTERNAL_PORT` | No | Default 5432 |
| `MONGO_USERNAME` | No | MongoDB user |
| `MONGO_PASSWORD` | No | MongoDB password |
| `MONGO_HOST` | No | Default `smart-agri-tech-mongo` |
| `MONGO_PORT` | No | Default 27017 |
| `MONGO_DB` | Yes | MongoDB database |
| `ACCESS_TOKEN` | Yes | JWT signing secret |
| `REFRESH_TOKEN` | Yes | Refresh token secret |
| `ALGORITHM` | Yes | JWT algorithm (e.g. HS256) |
| `ACCESS_EXPIRY` | No | Minutes, default 60 |
| `REFRESH_EXPIRY` | No | Minutes, default 10080 |
| `EMAIL_SENDER_ADDRESS` | Yes | SMTP sender |
| `EMAIL_SENDER_PASSWORD` | Yes | SMTP password |
| `EMAIL_SMTP_SERVER` | Yes | SMTP host |
| `EMAIL_SMTP_PORT` | Yes | SMTP port |
| `RAZORPAY_KEY_ID` | Yes | Razorpay key |
| `RAZORPAY_KEY_SECRET` | Yes | Razorpay secret |

---

## Development Workflow

- **Branch:** Feature branches from `main`.
- **Commits:** Descriptive messages.
- **PRs:** Include description and link to issues.

---

## Testing

No test suite is present. Add tests under `tests/` and run with `pytest`.

---

## Deployment

### Docker

```bash
docker build -t smart-agri-tech .
docker run -p 8000:8000 --env-file .env smart-agri-tech
```

**Note:** `entrypoint.sh` expects `create_tables.py` for table creation. Prefer Alembic in production.

### Manual

```bash
pip install -r requirements.txt
alembic upgrade head
uvicorn main:smart_agri_tech_app --host 0.0.0.0 --port $BACKEND_PORT
```

---

## Security Practices

- **Validation:** Pydantic schemas for request bodies.
- **Secrets:** `.env` for local/dev; use secrets manager in production.
- **Password:** Bcrypt via passlib.
- **CORS:** Configured for allowed origins; restrict in production.
- **Rate limiting:** Not implemented; add middleware for production.

---
