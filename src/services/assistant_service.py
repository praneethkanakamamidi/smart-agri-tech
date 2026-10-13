"""
Rule-based marketplace assistant (no LLM).

It only reads authoritative records through the same services and permission checks as the
API, and it never acts: it does not send offers, accept deals, reserve stock or move money.
Suggestions are labelled as estimates with their data basis.
"""
import re
from datetime import date, timedelta

from fastapi import HTTPException
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.money import D, money
from src.data_models.catalog_model import QualityStandards
from src.data_models.crops_model import Crops
from src.data_models.districts_model import Districts
from src.data_models.disputes_model import Disputes, ACTIVE_DISPUTE_STATES
from src.data_models.farmer_inventory_model import FarmerInventory
from src.data_models.miscellaneous_model import Miscellaneous_Data
from src.data_models.orders_model import Orders, PENDING_CONFIRMATION, ACTIVE_STATUSES, DELIVERED
from src.data_models.profiles_model import VerificationRequests
from src.data_models.states_model import States
from src.data_models.users_model import Users, PENDING_VERIFICATION
from src.schemas.listings_schema import MarketFilters
from src.services import order_core
from src.services.insights_service import InsightsService
from src.services.market_service import MarketService
from src.services.negotiations_service import NegotiationsService

UNIT_WORDS = {
    "kg": "kg", "kgs": "kg", "kilo": "kg", "kilos": "kg", "kilogram": "kg", "kilograms": "kg", "కిలో": "kg",
    "quintal": "quintal", "quintals": "quintal", "qtl": "quintal", "క్వింటాల్": "quintal",
    "tonne": "tonne", "tonnes": "tonne", "ton": "tonne", "tons": "tonne", "టన్ను": "tonne",
    "bag": "bag", "bags": "bag", "crate": "crate", "crates": "crate",
}
UNIT_PATTERN = "|".join(sorted(map(re.escape, UNIT_WORDS), key=len, reverse=True))
QUALITY_WORDS = {"premium": "A", "best": "A", "good quality": "A", "high quality": "A", "grade a": "A",
                 "a grade": "A", "grade b": "B", "b grade": "B", "medium": "B", "grade c": "C", "c grade": "C"}


def _week_end(today: date) -> date:
    return today + timedelta(days=6 - today.weekday())


class AssistantService:
    async def _vocab(self, db: AsyncSession):
        crops = (await db.execute(select(Crops.id, Crops.crop_name, Crops.name_te))).all()
        states = (await db.execute(select(States.id, States.state_name))).all()
        districts = (await db.execute(select(Districts.id, Districts.district_name, Districts.state_id))).all()
        return crops, states, districts

    @staticmethod
    def _find(text: str, candidates):
        """Longest whole-word match of any candidate name in `text`."""
        best = None
        for item_id, *names in candidates:
            for name in names:
                if not name or not isinstance(name, str):
                    continue
                if re.search(rf"(?<!\w){re.escape(name.lower())}(?!\w)", text):
                    if not best or len(name) > len(best[1]):
                        best = (item_id, name)
        return best

    async def parse_query(self, text: str, db: AsyncSession) -> tuple[dict, list[str]]:
        q = " " + text.lower().strip() + " "
        crops, states, districts = await self._vocab(db)
        filters, notes = {}, []
        crop = self._find(q, crops)
        if crop:
            filters["crop_id"] = crop[0]
            notes.append(f"produce: {crop[1]}")
        district = self._find(q, [(d[0], d[1]) for d in districts])
        if district:
            filters["district_id"] = district[0]
            notes.append(f"district: {district[1]}")
        else:
            state = self._find(q, states)
            if state:
                filters["state_id"] = state[0]
                notes.append(f"state: {state[1]}")

        qty = re.search(rf"(\d+(?:\.\d+)?)\s*({UNIT_PATTERN})(?!\w)", q)
        if qty and not re.search(rf"(?:₹|rs\.?|inr)\s*{re.escape(qty.group(1))}", q):
            filters["order_quantity"] = float(qty.group(1))
            filters["unit"] = UNIT_WORDS[qty.group(2)]
            filters["sort_by"] = "best_match"
            notes.append(f"quantity: {qty.group(1)} {filters['unit']}")

        price = re.search(rf"(around|about|approx\.?|near|~|under|below|less than|max(?:imum)?|upto|up to|above|over|at least|min(?:imum)?)?\s*(?:₹|rs\.?|inr)\s*(\d+(?:\.\d+)?)(?:\s*(?:/|per)\s*({UNIT_PATTERN}))?", q)
        if not price:
            price = re.search(rf"(around|about|under|below|above|over)?\s*(\d+(?:\.\d+)?)\s*(?:/|per)\s*({UNIT_PATTERN})", q)
        if price:
            modifier, value = (price.group(1) or "").strip(), float(price.group(2))
            if modifier in ("under", "below", "less than", "max", "maximum", "upto", "up to"):
                filters["max_price"] = value
            elif modifier in ("above", "over", "at least", "min", "minimum"):
                filters["min_price"] = value
            else:
                filters["min_price"], filters["max_price"] = round(value * 0.9, 2), round(value * 1.1, 2)
            notes.append(f"price: {modifier or 'around'} ₹{value}" + (f"/{UNIT_WORDS[price.group(3)]}" if price.group(3) else ""))

        for phrase, grade in sorted(QUALITY_WORDS.items(), key=lambda kv: -len(kv[0])):
            if phrase in q:
                filters["quality_grade"] = grade
                notes.append(f"quality grade: {grade}")
                break

        today = date.today()
        if "today" in q:
            filters["available_by"] = today
        elif "tomorrow" in q:
            filters["available_by"] = today + timedelta(days=1)
        elif "this week" in q:
            filters["available_by"] = _week_end(today)
        elif "next week" in q:
            filters["available_by"] = _week_end(today) + timedelta(days=7)
        else:
            within = re.search(r"within (\d+) days", q)
            if within:
                filters["available_by"] = today + timedelta(days=int(within.group(1)))
        if "available_by" in filters:
            notes.append(f"available by: {filters['available_by']}")
        if "organic" in q:
            filters["organic_verified_only"] = True
            notes.append("verified organic only")
        if "verified" in q:
            filters["verified_farmers_only"] = True
            notes.append("verified farmers only")
        if "pre-harvest" in q or "pre harvest" in q or "advance booking" in q:
            filters["pre_harvest"] = True
            notes.append("pre-harvest listings")
        if "cheapest" in q or "lowest price" in q:
            filters["sort_by"] = "price_asc"
        if "best rated" in q or "highest rated" in q or "top rated" in q:
            filters["sort_by"] = "rating_desc"
        if not filters.get("crop_id") and not notes:
            filters["q"] = text.strip()[:100]
        return filters, notes

    async def search(self, user: Users, text: str, db: AsyncSession) -> dict:
        filters, notes = await self.parse_query(text, db)
        market_filters = MarketFilters(page_size=20, **filters)
        results = await MarketService().get_market(db, market_filters, user.id)
        return {
            "query": text,
            "understood_as": notes or ["free-text search"],
            "applied_filters": market_filters.model_dump(exclude_none=True, exclude={"page", "page_size"}),
            "result_count": len(results),
            "results": results,
            "note": "Results are real live listings. Prices shown are asking prices; the final price is negotiated.",
        }

    async def listing_draft(self, farmer: Users, text: str, db: AsyncSession) -> dict:
        """Turn a sentence like '50 quintal tomato grade A at 2200 per quintal, harvested 2026-10-10' into listing fields."""
        q = " " + text.lower() + " "
        crops, _, _ = await self._vocab(db)
        draft, missing = {}, []
        crop = self._find(q, crops)
        if crop:
            draft["crop"] = crop[0]
            draft["crop_name"] = crop[1]
        else:
            missing.append("crop")
        qty = re.search(rf"(\d+(?:\.\d+)?)\s*({UNIT_PATTERN})(?!\w)", q)
        if qty:
            draft["quantity"], draft["unit"] = float(qty.group(1)), UNIT_WORDS[qty.group(2)]
        else:
            missing.append("quantity")
        price = re.search(rf"(?:₹|rs\.?|inr|at|price|for)\s*(\d+(?:\.\d+)?)(?:\s*(?:/|per)\s*({UNIT_PATTERN}))?", q)
        if price:
            draft["asking_price"] = float(price.group(1))
            if price.group(2) and "unit" in draft and UNIT_WORDS[price.group(2)] != draft["unit"]:
                missing.append("price unit matches quantity unit")
        else:
            missing.append("asking_price")
        grades = set((await db.execute(select(QualityStandards.code))).scalars().all())
        grade = re.search(r"grade\s*([a-z])\b|\b([a-z])\s*grade", q)
        if grade:
            code = (grade.group(1) or grade.group(2)).upper()
            if code in grades:
                draft["quality_grade"] = code
        for key, pattern in (("harvest_date", r"harvest(?:ed)?\s*(?:on|date)?\s*(\d{4}-\d{2}-\d{2})"),
                             ("available_until", r"(?:until|till|expires?)\s*(\d{4}-\d{2}-\d{2})")):
            match = re.search(pattern, q)
            if match:
                draft[key] = match.group(1)
        if "harvest_date" not in draft and "today" in q:
            draft["harvest_date"] = date.today().isoformat()
        if "organic" in q:
            draft["organic_claim"] = True
        for word, option in (("pickup", "pickup"), ("deliver", "farmer_delivery")):
            if word in q:
                draft.setdefault("delivery_options", []).append(option)
        draft["description"] = text.strip()[:500]
        return {
            "draft": draft,
            "missing_fields": missing,
            "next_step": "Review the draft, then POST it to /api/listings (set publish=false to save as a draft).",
            "note": "Nothing has been created. Organic claims are shown as verified only after a certificate is approved.",
        }

    async def negotiation_summary(self, user: Users, negotiation_id: int, db: AsyncSession) -> dict:
        data = await NegotiationsService().get(user, negotiation_id, db)
        history = data["history"]
        listing = data["listing"]
        lines = [f"Negotiation #{negotiation_id} for {listing['crop_name']} (asking ₹{listing['asking_price']}/{listing['unit']}) is {data['status'].lower()}."]
        for offer in history:
            who = "You" if offer["is_mine"] else ("The farmer" if offer["offered_by_role"] == "farmer" else "The vendor")
            lines.append(f"v{offer['version']}: {who} offered ₹{offer['unit_price']}/{offer['unit']} for "
                         f"{offer['quantity']} {offer['unit']} (₹{offer['subtotal']}) - {offer['status'].lower()}.")
        current = data["current_offer"]
        if current and current["is_actionable_by_me"]:
            lines.append(f"It's your turn: accept, reject or counter by {current['expires_at']} UTC.")
            if current.get("below_my_minimum_price"):
                lines.append("This offer is below your private minimum price.")
        elif current and current["status"] == "PENDING":
            lines.append("Waiting for the other party to respond.")
        return {"summary": " ".join(lines), "negotiation": data}

    async def suggest_counter(self, user: Users, negotiation_id: int, db: AsyncSession) -> dict:
        data = await NegotiationsService().get(user, negotiation_id, db)
        current = data["current_offer"]
        if not current or not current["is_actionable_by_me"]:
            raise HTTPException(status_code=409, detail="There is no offer waiting for your response.")
        listing = (await db.execute(select(FarmerInventory).where(FarmerInventory.id == data["listing_id"]))).scalar_one()
        insights = await InsightsService().get_price_insights(listing.crop, db, days=60, unit=listing.unit)
        deals = insights["negotiated_prices"]
        asking, offered = D(listing.proposed_cost), D(current["unit_price"])
        is_farmer = user.id == data["farmer"]
        mine = [o for o in data["history"] if o["is_mine"]]
        anchor = D(mine[-1]["unit_price"]) if mine else asking
        suggestion = (anchor + offered) / 2
        basis = ["midpoint between your last position and their offer"]
        if deals["is_reliable"] and deals["p25"] is not None:
            low, high = D(str(deals["p25"])), D(str(deals["p75"]))
            suggestion = min(max(suggestion, low), high)
            basis.append(f"kept within the typical negotiated range ₹{low}-₹{high} ({deals['sample_size']} deals, 60 days)")
        else:
            basis.append("not enough recent deals for a market range")
        if is_farmer and listing.min_acceptable_price and suggestion < D(listing.min_acceptable_price):
            suggestion = D(listing.min_acceptable_price)
            basis.append("raised to your private minimum price")
        return {
            "suggested_unit_price": money(suggestion),
            "their_offer": offered,
            "your_last_price": anchor,
            "basis": basis,
            "is_estimate": True,
            "how_to_use": f"If you agree, POST /api/negotiations/{negotiation_id}/offers with this price. Nothing has been sent.",
        }

    async def orders_summary(self, user: Users, db: AsyncSession) -> dict:
        rows = (await db.execute(
            select(Orders, Miscellaneous_Data.value).join(Miscellaneous_Data, Orders.status == Miscellaneous_Data.id)
            .where((Orders.farmer == user.id) | (Orders.vendor == user.id),
                   Miscellaneous_Data.value.in_(ACTIVE_STATUSES + (DELIVERED,)))
            .order_by(Orders.created_at.desc())
        )).all()
        actions, outstanding_total = [], D(0)
        for order, status_value in rows:
            is_farmer = order.farmer == user.id
            money_info = await order_core.money_summary(db, order)
            if not is_farmer:
                outstanding_total += money_info["outstanding"]
            if status_value == PENDING_CONFIRMATION and (
                    (is_farmer and not order.farmer_confirmed_at) or (not is_farmer and not order.vendor_confirmed_at)):
                actions.append(f"Confirm order {order.order_number}.")
            elif status_value == "confirmed" and is_farmer:
                actions.append(f"Start preparing order {order.order_number}.")
            elif status_value == DELIVERED and not is_farmer and money_info["outstanding"] > 0:
                actions.append(f"Pay ₹{money_info['outstanding']} for order {order.order_number}.")
            elif status_value == DELIVERED and not is_farmer:
                actions.append(f"Mark order {order.order_number} complete if everything is in order.")
        return {
            "active_orders": len(rows),
            "by_status": {s: sum(1 for _, v in rows if v == s) for s in {v for _, v in rows}},
            "outstanding_to_pay": money(outstanding_total),
            "suggested_next_actions": actions[:10],
            "source": "Your order and payment records.",
        }

    async def admin_summary(self, db: AsyncSession) -> dict:
        pending_verifications = (await db.execute(select(func.count(VerificationRequests.id)).where(
            VerificationRequests.status == PENDING_VERIFICATION))).scalar()
        disputes = (await db.execute(select(Disputes).where(Disputes.status.in_(ACTIVE_DISPUTE_STATES))
                                     .order_by(Disputes.escalated.desc(), Disputes.created_at))).scalars().all()
        from src.services.admin_service import AdminService
        monitoring = await AdminService().monitoring(db, 7)
        return {
            "pending_verifications": pending_verifications,
            "open_disputes": len(disputes),
            "escalated_disputes": [d.id for d in disputes if d.escalated],
            "oldest_open_disputes": [{"id": d.id, "order_id": d.order_id, "reason": d.reason, "opened": d.created_at}
                                     for d in disputes[:5]],
            "last_7_days_flags": monitoring,
            "summary": f"{pending_verifications} verification(s) waiting, {len(disputes)} open dispute(s) "
                       f"({sum(1 for d in disputes if d.escalated)} escalated), {monitoring['pending_refunds']} pending refund(s), "
                       f"{monitoring['open_reports']} open report(s).",
        }
