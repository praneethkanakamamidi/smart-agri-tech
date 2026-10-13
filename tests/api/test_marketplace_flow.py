"""
End-to-end marketplace flows through the real HTTP API and a real PostgreSQL database.
Tests in this module share state (one listing, negotiation, order) and run in file order.
"""
import re
import uuid
from datetime import date, timedelta

import pytest

from tests.api.conftest import ok

STATE: dict = {}


# ---- accounts & profiles ------------------------------------------------------------------

def test_health_and_versioned_path(client):
    assert ok(client.get("/health"))["status"] == "ok"
    assert ok(client.get("/health/ready"))["checks"]["postgres"] == "ok"
    assert client.get("/api/v1/catalog/units").status_code == 401  # v1 alias resolves; auth still required


def test_locations_are_public_and_seeded(client):
    states = ok(client.get("/api/states"))
    assert len(states) == 28 and states == sorted(states, key=lambda s: s["state_name"])
    telangana = next(s for s in states if s["state_name"] == "Telangana")
    districts = ok(client.get(f"/api/states/{telangana['id']}/districts"))
    assert any(d["district_name"] == "Hyderabad" for d in districts)


def test_unauthenticated_requests_get_structured_401(client):
    response = client.get("/api/orders")
    assert response.status_code == 401
    body = response.json()
    assert body["error"]["code"] == "unauthorized" and body["error"]["request_id"]


def test_registration_rejects_weak_password_and_admin_role(client):
    weak = client.post("/api/users", json={"email": "weak@example.com", "first_name": "W", "password": "short", "role": "farmer"})
    assert weak.status_code == 422
    admin = client.post("/api/users", json={"email": "x@example.com", "first_name": "X", "password": "Passw0rd!x", "role": "admin"})
    assert admin.status_code == 422


def test_refresh_rotation_and_reuse_detection(client, register):
    # Separate user: reusing a refresh token revokes every session of that account (theft detection).
    user = register("farmer", "Rotate")
    login = ok(client.post("/api/login/", data={"username": user.identifier, "password": user.password}))
    rotated = ok(client.post("/api/token/refresh", json={"refresh_token": login["refresh_token"]}))
    assert rotated["access_token"] != login["access_token"]
    reuse = client.post("/api/token/refresh", json={"refresh_token": login["refresh_token"]})
    assert reuse.status_code == 401  # rotated refresh tokens can't be reused...
    still_valid = client.get("/api/users/me", headers={"Authorization": f"Bearer {rotated['access_token']}"})
    assert still_valid.status_code == 401  # ...and the reuse revoked every session of the account


def test_profiles_encrypt_and_mask_payout_details(farmer, vendor):
    body = ok(farmer.put("/api/profile/farmer", json={
        "farm_name": "Green Acres", "farm_address": "Village road 1", "payout_method": "bank",
        "bank_account_holder": "Ravi Test", "bank_account_number": "123456789012", "bank_ifsc": "SBIN0001234",
    }))
    profile = body["profile"]
    assert profile["bank_account_number_masked"].endswith("9012")
    assert "bank_account_number_enc" not in profile and "123456789012" not in str(body)
    ok(vendor.put("/api/profile/vendor", json={"business_name": "Sita Stores", "business_type": "retailer",
                                                "business_address": "Market street"}))


# ---- listings & discovery ------------------------------------------------------------------

def test_farmer_creates_listing_with_private_floor_price(farmer, crop_id):
    body = ok(farmer.post("/api/listings", json={
        "crop": crop_id, "variety": "Hybrid", "quantity": 500, "unit": "kg", "asking_price": 25,
        "min_order_qty": 50, "min_acceptable_price": 20, "quality_grade": "A",
        "harvest_date": str(date.today()), "available_until": str(date.today() + timedelta(days=10)),
        "delivery_options": ["pickup"], "low_stock_threshold": 100,
    }))
    STATE["listing_id"] = body["id"]
    mine = ok(farmer.get(f"/api/listings/{body['id']}"))
    assert float(mine["min_acceptable_price"]) == 20  # the owner sees it


def test_vendor_never_sees_private_floor_price(vendor, crop_id):
    detail = ok(vendor.get(f"/api/listings/{STATE['listing_id']}"))
    assert "min_acceptable_price" not in detail and detail["can_negotiate"] is True
    market = ok(vendor.get("/api/market/", params={"crop_id": crop_id, "order_quantity": 100, "sort_by": "best_match"}))
    assert market and all("min_acceptable_price" not in item for item in market)
    assert "password" not in str(market)


def test_only_vendors_negotiate_and_farmers_cannot_buy_own_listing(farmer):
    response = farmer.post("/api/negotiations", json={"listing_id": STATE["listing_id"], "quantity": 100, "unit_price": 20})
    assert response.status_code == 403


# ---- negotiation -> order ---------------------------------------------------------------------

def test_negotiation_offer_counter_accept(farmer, vendor):
    started = ok(vendor.post("/api/negotiations", json={
        "listing_id": STATE["listing_id"], "quantity": 100, "unit_price": 18, "delivery_preference": "pickup",
        "message": "Can you do 18?",
    }))
    STATE["negotiation_id"] = started["negotiation_id"]

    farmer_view = ok(farmer.get(f"/api/negotiations/{started['negotiation_id']}"))
    assert farmer_view["current_offer"]["below_my_minimum_price"] is True  # private hint for the farmer only
    vendor_view = ok(vendor.get(f"/api/negotiations/{started['negotiation_id']}"))
    assert "below_my_minimum_price" not in vendor_view["current_offer"]

    # Vendor can't accept their own offer; farmer counters.
    own = vendor.post(f"/api/negotiations/{started['negotiation_id']}/accept", json={"offer_id": started["offer_id"]})
    assert own.status_code == 403
    counter = ok(farmer.post(f"/api/negotiations/{started['negotiation_id']}/offers", json={"quantity": 100, "unit_price": 22}))

    # Accepting a superseded offer is refused.
    stale = vendor.post(f"/api/negotiations/{started['negotiation_id']}/accept", json={"offer_id": started["offer_id"]})
    assert stale.status_code == 409

    key = str(uuid.uuid4())
    accepted = ok(vendor.post(f"/api/negotiations/{started['negotiation_id']}/accept",
                              json={"offer_id": counter["offer_id"], "payment_terms": "pay_before_dispatch"},
                              headers={"Idempotency-Key": key}))
    replay = ok(vendor.post(f"/api/negotiations/{started['negotiation_id']}/accept",
                            json={"offer_id": counter["offer_id"], "payment_terms": "pay_before_dispatch"},
                            headers={"Idempotency-Key": key}))
    assert replay["order_id"] == accepted["order_id"]  # retried request, same order
    assert accepted["status"] == "pending_confirmation" and float(accepted["agreed_unit_price"]) == 22
    STATE["order_id"] = accepted["order_id"]

    history = ok(vendor.get(f"/api/negotiations/{started['negotiation_id']}"))["history"]
    assert [o["status"] for o in history] == ["COUNTERED", "ACCEPTED"]


def test_stock_is_reserved_and_order_snapshot_is_frozen(farmer, vendor):
    listing = ok(farmer.get(f"/api/listings/{STATE['listing_id']}"))
    assert float(listing["available_quantity"]) == 400 and float(listing["reserved_qty"]) == 100
    order = ok(vendor.get(f"/api/orders/{STATE['order_id']}"))
    assert order["terms_snapshot"]["unit_price"] == "22.00" and float(order["total_price"]) == 2200
    assert order["awaiting_my_confirmation"] is False  # vendor accepted, so already confirmed
    # Changing the listing price later must not change the agreed order.
    ok(farmer.put(f"/api/listings/{STATE['listing_id']}", json={"asking_price": 30}))
    assert float(ok(vendor.get(f"/api/orders/{STATE['order_id']}"))["unit_price"]) == 22


def test_other_users_cannot_see_the_order(register):
    stranger = register("vendor", "Stranger")
    assert stranger.get(f"/api/orders/{STATE['order_id']}").status_code == 404


def test_farmer_confirms_then_payment_gate_blocks_dispatch(farmer, vendor):
    assert ok(farmer.post(f"/api/orders/{STATE['order_id']}/confirm"))["status"] == "confirmed"
    ok(farmer.post(f"/api/orders/{STATE['order_id']}/status", json={"status": "preparing"}))
    blocked = farmer.post(f"/api/orders/{STATE['order_id']}/status", json={"status": "ready_for_pickup"})
    assert blocked.status_code == 409 and "payment" in blocked.json()["detail"].lower()


def test_cash_payment_then_dispatch_and_delivery_code(farmer, vendor):
    paid = ok(farmer.post(f"/api/orders/{STATE['order_id']}/payments/manual", json={"amount": 2200, "method": "cash"}))
    assert float(paid["outstanding"]) == 0
    ok(farmer.post(f"/api/orders/{STATE['order_id']}/status", json={"status": "ready_for_pickup"}))

    notes = ok(vendor.get("/api/notifications", params={"page_size": 50}))["data"]
    code_note = next(n for n in notes if n["type"] == "delivery_code" and n["ref_id"] == STATE["order_id"])
    code = re.search(r"\b(\d{6})\b", code_note["message"]).group(1)

    wrong = farmer.post(f"/api/orders/{STATE['order_id']}/delivery/confirm", json={"delivery_code": "000000"})
    assert wrong.status_code == 400
    ok(farmer.post(f"/api/orders/{STATE['order_id']}/delivery/confirm",
                   json={"delivery_code": code, "accepted_quantity": 100, "quality_accepted": True}))
    listing = ok(farmer.get(f"/api/listings/{STATE['listing_id']}"))
    assert float(listing["reserved_qty"]) == 0 and float(listing["sold_qty"]) == 100


def test_vendor_completes_order_creating_settlement_and_invoice(farmer, vendor):
    ok(vendor.post(f"/api/orders/{STATE['order_id']}/status", json={"status": "completed"}))
    order = ok(vendor.get(f"/api/orders/{STATE['order_id']}"))
    assert order["order_status"] == "completed"
    assert [t["to"] for t in order["timeline"]] == [
        "pending_confirmation", "confirmed", "preparing", "ready_for_pickup", "delivered", "completed"]
    invoices = ok(vendor.get(f"/api/orders/{STATE['order_id']}/invoices"))
    assert {i["invoice_type"] for i in invoices} >= {"order_receipt", "payment_receipt", "invoice"}
    download = vendor.get(invoices[0]["download_url"])
    assert download.status_code == 200 and "Ravi" in download.text
    settlements = ok(farmer.get("/api/settlements"))
    # The farmer was paid in cash directly, so nothing is owed by the platform for this order.
    assert any(s["order_id"] == STATE["order_id"] for s in settlements["settlements"])


def test_reviews_and_public_trust_profile(farmer, vendor):
    ok(vendor.post("/api/reviews", json={"order_id": STATE["order_id"], "rating": 5, "quality_rating": 5,
                                          "comment": "Fresh tomatoes"}))
    duplicate = vendor.post("/api/reviews", json={"order_id": STATE["order_id"], "rating": 4})
    assert duplicate.status_code == 409
    ok(farmer.post(f"/api/reviews/{ok(farmer.get(f'/api/reviews/user/{farmer.id}'))['data'][0]['id']}/response",
                   json={"response": "Thank you!"}))
    profile = ok(vendor.get(f"/api/users/{farmer.id}/public-profile"))
    assert profile["trust"]["completed_orders"] >= 1 and profile["trust"]["review_count"] == 1
    assert profile["trust"]["cancellation_rate_percent"] is None  # below the minimum sample size


# ---- direct orders, cancellation, stock release ---------------------------------------------

def test_direct_order_cancel_releases_stock(farmer, vendor):
    before = float(ok(farmer.get(f"/api/listings/{STATE['listing_id']}"))["available_quantity"])
    order = ok(vendor.post("/api/orders/direct", json={"listing_id": STATE["listing_id"], "quantity": 60}))
    assert float(ok(farmer.get(f"/api/listings/{STATE['listing_id']}"))["available_quantity"]) == before - 60
    ok(farmer.post(f"/api/orders/{order['order_id']}/cancel", json={"reason": "No longer available"}))
    assert float(ok(farmer.get(f"/api/listings/{STATE['listing_id']}"))["available_quantity"]) == before


def test_minimum_order_and_overselling_are_rejected(vendor):
    too_small = vendor.post("/api/orders/direct", json={"listing_id": STATE["listing_id"], "quantity": 10})
    assert too_small.status_code == 422
    too_big = vendor.post("/api/orders/direct", json={"listing_id": STATE["listing_id"], "quantity": 100000})
    assert too_big.status_code == 409


# ---- chat, notifications, safety ---------------------------------------------------------------

def test_contextual_chat_and_blocking(farmer, vendor):
    ok(vendor.post("/api/inbox/messages", json={"receiver_id": farmer.id, "body": "When can I pick up?",
                                                 "negotiation_id": STATE["negotiation_id"]}))
    conversations = ok(farmer.get("/api/inbox/conversations"))
    assert any(c["user_id"] == vendor.id and c["unread_count"] >= 1 for c in conversations)
    thread = ok(farmer.get(f"/api/inbox/conversations/{vendor.id}", params={"negotiation_id": STATE["negotiation_id"]}))
    assert any(m["message_type"] == "offer_summary" for m in thread["data"])
    ok(farmer.post(f"/api/users/{vendor.id}/block"))
    assert vendor.post("/api/inbox/messages", json={"receiver_id": farmer.id, "body": "hello"}).status_code == 403
    ok(farmer.delete(f"/api/users/{vendor.id}/block"))


def test_notifications_are_localised(vendor, farmer):
    ok(farmer.put("/api/notifications/preferences", json={"preferred_language": "te"}))
    ok(vendor.post("/api/inbox/messages", json={"receiver_id": farmer.id, "body": "నమస్తే"}))
    latest = ok(farmer.get("/api/notifications", params={"page_size": 1}))["data"][0]
    assert "సందేశం" in latest["title"]  # Telugu template
    ok(farmer.put("/api/notifications/preferences", json={"preferred_language": "en"}))


# ---- procurement ----------------------------------------------------------------------------------

def test_buy_request_quote_and_accept(farmer, vendor, crop_id):
    request = ok(vendor.post("/api/buy-requests", json={"crop": crop_id, "quantity_kg": 100, "unit": "kg",
                                                         "max_price_per_kg": 30, "invite_farmer_ids": [farmer.id]}))
    open_requests = ok(farmer.get("/api/buy-requests", params={"invited_only": True}))
    assert any(r["id"] == request["buy_request_id"] and r["invited"] for r in open_requests)
    quote = ok(farmer.post(f"/api/buy-requests/{request['buy_request_id']}/responses",
                           json={"farmer_inventory": STATE["listing_id"], "price_per_kg": 24, "quantity_kg": 100}))
    compared = ok(vendor.get(f"/api/buy-requests/{request['buy_request_id']}/responses"))
    assert float(compared["quotations"][0]["total_cost"]) == 2400
    accepted = ok(vendor.put(f"/api/buy-requests/responses/{quote['response_id']}/accept"))
    assert accepted["buy_request_status"] == "fulfilled"
    order = ok(vendor.get(f"/api/orders/{accepted['order_id']}"))
    assert order["order_status"] == "confirmed"  # quote = farmer's terms, accept = vendor's: both confirmed


# ---- disputes and refunds ---------------------------------------------------------------------------

def test_dispute_with_partial_refund(farmer, vendor, admin):
    dispute = ok(vendor.post("/api/disputes", json={"order_id": STATE["order_id"], "reason": "quality_issue",
                                                     "description": "Some were bruised"}))
    assert ok(vendor.get(f"/api/orders/{STATE['order_id']}"))["order_status"] == "disputed"
    ok(farmer.post(f"/api/disputes/{dispute['dispute_id']}/messages", json={"body": "They were fine at pickup."}))
    resolved = ok(admin.put(f"/api/admin/disputes/{dispute['dispute_id']}/resolve", json={
        "status": "resolved", "resolution": "Refund 10% for bruised produce", "resolution_type": "partial_refund",
        "refund_amount": 220}))
    assert resolved["refund_id"]
    money = ok(vendor.get(f"/api/orders/{STATE['order_id']}/payments"))
    assert float(money["refund_pending"]) == 220 and float(money["paid"]) == 2200  # original payment untouched
    ok(admin.post(f"/api/admin/refunds/{resolved['refund_id']}/mark-refunded", json={"reference": "UTR123"}))
    assert float(ok(vendor.get(f"/api/orders/{STATE['order_id']}/payments"))["refunded"]) == 220
    assert ok(vendor.get(f"/api/orders/{STATE['order_id']}"))["order_status"] == "completed"


# ---- dashboards, insights, assistant, admin ------------------------------------------------------------

@pytest.mark.parametrize("path", [
    "/api/dashboard/farmer", "/api/reports/farmer", "/api/expenses/summary", "/api/harvest-plans/calendar",
    "/api/assistant/orders/summary", "/api/listings/mine",
])
def test_farmer_read_endpoints(farmer, path):
    ok(farmer.get(path))


@pytest.mark.parametrize("path", [
    "/api/dashboard/vendor", "/api/reports/vendor", "/api/insights/procurement", "/api/favourites/feed",
    "/api/listings/saved", "/api/negotiations",
])
def test_vendor_read_endpoints(vendor, path):
    ok(vendor.get(path))


def test_price_insights_separate_asking_and_negotiated(vendor, crop_id):
    insights = ok(vendor.get("/api/insights/prices", params={"crop_id": crop_id, "days": 30}))
    assert insights["negotiated_prices"]["sample_size"] >= 1
    assert insights["asking_prices"]["sample_size"] >= 1
    assert ok(vendor.get("/api/insights/demand-forecast", params={"crop_id": crop_id}))["is_estimate"] is True


def test_assistant_search_uses_real_listings(vendor):
    result = ok(vendor.post("/api/assistant/search", json={"text": "100 kg tomato grade a around ₹30/kg"}))
    assert result["applied_filters"]["quality_grade"] == "A" and result["result_count"] >= 1


@pytest.mark.parametrize("path", [
    "/api/admin/users", "/api/admin/monitoring", "/api/admin/settings", "/api/admin/audit-logs",
    "/api/admin/analytics", "/api/admin/metrics/success", "/api/admin/metrics", "/api/assistant/admin/summary",
])
def test_admin_read_endpoints(admin, path):
    ok(admin.get(path))


def test_admin_only_routes_reject_other_roles(vendor):
    assert vendor.get("/api/admin/users").status_code == 403


def test_settings_are_versioned_and_audited(admin):
    ok(admin.put("/api/admin/settings/offer_expiry_hours", json={"value": 24, "reason": "Faster turnover"}))
    history = ok(admin.get("/api/admin/settings/offer_expiry_hours/history"))
    assert history[0]["value"] == 24 and history[0]["version"] == 1
    logs = ok(admin.get("/api/admin/audit-logs", params={"action": "admin.setting_changed"}))
    assert logs["total_records"] >= 1
    bad = admin.put("/api/admin/settings/offer_expiry_hours", json={"value": "soon"})
    assert bad.status_code == 422


def test_background_jobs_run_cleanly(admin):
    results = ok(admin.post("/api/admin/jobs/run", json={}))
    errors = {name: value for name, value in results.items() if isinstance(value, str) and value.startswith("error")}
    assert not errors, errors


def test_crop_prediction(farmer):
    body = ok(farmer.post("/api/predict/", json={"N": 90, "P": 42, "K": 43, "temperature": 20.87,
                                                  "humidity": 82.0, "ph": 6.5, "rainfall": 202.94}))
    assert body["predicted_crop"] == "rice"
    assert farmer.post("/api/predict/", json={"N": 90}).status_code == 422


def test_websocket_authenticates(client, farmer):
    # Live push across HTTP + WebSocket needs a real server (TestClient runs WebSockets on a
    # separate event loop); delivery is covered by tests/unit/test_realtime.py and was verified
    # against uvicorn. Here: authentication and the connection protocol.
    from starlette.websockets import WebSocketDisconnect

    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("/api/ws?token=not-a-token") as ws:
            ws.receive_json()
    with client.websocket_connect(f"/api/ws?token={farmer.token}") as ws:
        ws.send_text("ping")
        assert ws.receive_json() == {"event": "pong"}


def test_logout_revokes_the_session(client, register):
    user = register("vendor", "Leaving")
    ok(user.post("/api/auth/logout", json={"all_devices": False}))
    assert user.get("/api/users/me").status_code == 401
