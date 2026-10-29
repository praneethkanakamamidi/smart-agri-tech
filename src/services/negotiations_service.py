"""
Price bargaining engine.

A negotiation is one vendor + one farmer + one listing. Each proposal is an immutable Offer
version; a counteroffer marks the previous offer COUNTERED and creates a new PENDING version
that supersedes it. Only the latest PENDING offer is actionable, and only its recipient can
accept, reject or counter it. Acceptance locks the offer and the listing rows, validates expiry
and stock, reserves stock and creates the order in one transaction.
"""
from datetime import datetime, timedelta

from fastapi import HTTPException
from sqlalchemy import select, func, or_
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.audit import audit
from src.core.money import D, money
from src.core.platform_settings import get_setting
from src.core.realtime import queue_event
from src.data_models.crops_model import Crops
from src.data_models.farmer_inventory_model import FarmerInventory
from src.data_models.messages_model import Messages
from src.data_models.negotiation_model import (
    Negotiations, Offers, DRAFT, PENDING, COUNTERED, ACCEPTED, REJECTED, WITHDRAWN, EXPIRED, CANCELLED, NEG_OPEN,
)
from src.data_models.platform_model import UserBlocks
from src.data_models.users_model import Users
from src.helpers.serializers import model_to_dict
from src.services import inventory_core, order_core
from src.services.notifications_service import notify_user
from src.core.clock import utcnow


def _name(user: Users | None) -> str:
    return f"{user.first_name} {user.last_name}".strip() if user else ""


async def ensure_not_blocked(db: AsyncSession, user_a: int, user_b: int):
    blocked = (await db.execute(select(UserBlocks.id).where(or_(
        (UserBlocks.blocker_id == user_a) & (UserBlocks.blocked_id == user_b),
        (UserBlocks.blocker_id == user_b) & (UserBlocks.blocked_id == user_a),
    )))).first()
    if blocked:
        raise HTTPException(status_code=403, detail="You can't interact with this user.")


class NegotiationsService:
    # ---- helpers -------------------------------------------------------------------

    async def _expiry(self, db: AsyncSession, hours: int | None) -> datetime:
        default = int(await get_setting(db, "offer_expiry_hours"))
        maximum = int(await get_setting(db, "offer_max_expiry_hours"))
        return utcnow() + timedelta(hours=min(hours or default, maximum))

    async def _get_negotiation(self, db: AsyncSession, negotiation_id: int, user_id: int, lock: bool = False) -> Negotiations:
        stmt = select(Negotiations).where(Negotiations.id == negotiation_id)
        if lock:
            stmt = stmt.with_for_update()
        negotiation = (await db.execute(stmt)).scalar_one_or_none()
        if not negotiation or user_id not in (negotiation.vendor, negotiation.farmer):
            raise HTTPException(status_code=404, detail="Negotiation not found.")
        return negotiation

    async def _current_offer(self, db: AsyncSession, negotiation: Negotiations, lock: bool = False) -> Offers | None:
        if not negotiation.current_offer_id:
            return None
        stmt = select(Offers).where(Offers.id == negotiation.current_offer_id)
        if lock:
            stmt = stmt.with_for_update()
        return (await db.execute(stmt)).scalar_one_or_none()

    @staticmethod
    def _check_offer_live(offer: Offers):
        if offer.status == PENDING and offer.expires_at and offer.expires_at <= utcnow():
            raise HTTPException(status_code=409, detail="This offer has expired. Send a new offer instead.")

    def _validate_terms(self, listing: FarmerInventory, terms, unit_price=None):
        quantity = D(terms.quantity)
        if quantity > D(listing.weight_kg):
            raise HTTPException(status_code=422, detail=f"Only {D(listing.weight_kg)} {listing.unit} is available.")
        if listing.min_order_qty and quantity < D(listing.min_order_qty) and D(listing.weight_kg) >= D(listing.min_order_qty):
            raise HTTPException(status_code=422, detail=f"Minimum order is {D(listing.min_order_qty)} {listing.unit}.")
        options = [o for o in (listing.delivery_options or "pickup").split(",") if o]
        if terms.delivery_preference and terms.delivery_preference not in options:
            raise HTTPException(status_code=422, detail=f"This listing supports: {', '.join(options)}.")

    async def _crop_name(self, db: AsyncSession, listing: FarmerInventory) -> str:
        return (await db.execute(select(Crops.crop_name).where(Crops.id == listing.crop))).scalar_one_or_none() or ""

    def _new_offer(self, negotiation, version, offered_by, recipient, role, listing, terms, expires_at, status_, supersedes=None):
        quantity, price = D(terms.quantity), D(terms.unit_price)
        return Offers(
            negotiation_id=negotiation.id, version=version, offered_by=offered_by, recipient=recipient,
            offered_by_role=role, quantity=quantity, unit=listing.unit, unit_price=price,
            subtotal=money(quantity * price), delivery_preference=terms.delivery_preference,
            preferred_date=terms.preferred_date, packaging=terms.packaging, quality_spec=terms.quality_spec,
            message=terms.message, status=status_, supersedes_offer_id=supersedes,
            expires_at=expires_at, expiry_notified=False, created_at=utcnow(),
        )

    async def _announce(self, db: AsyncSession, negotiation: Negotiations, offer: Offers, listing: FarmerInventory,
                        template: str):
        """Notify the recipient and drop an offer summary into the chat thread."""
        sender = (await db.execute(select(Users).where(Users.id == offer.offered_by))).scalar_one()
        crop = await self._crop_name(db, listing)
        params = {"party": _name(sender), "price": D(offer.unit_price), "unit": offer.unit, "quantity": D(offer.quantity),
                  "crop": crop}
        await notify_user(db, offer.recipient, template, params, ref_type="negotiation", ref_id=negotiation.id)
        summary = (f"Offer v{offer.version}: {D(offer.quantity)} {offer.unit} {crop} at ₹{D(offer.unit_price)}/{offer.unit} "
                   f"= ₹{D(offer.subtotal)}" + (f". Expires {offer.expires_at:%Y-%m-%d %H:%M} UTC" if offer.expires_at else "")
                   + (f". Note: {offer.message}" if offer.message else ""))
        db.add(Messages(sender=offer.offered_by, receiver=offer.recipient, negotiation_id=negotiation.id,
                        listing_id=listing.id, message_type="offer_summary", body=summary[:1000], is_read=False,
                        created_at=utcnow()))
        queue_event(db, offer.recipient, {"event": "negotiation", "negotiation_id": negotiation.id,
                                          "offer_id": offer.id, "status": offer.status})

    @staticmethod
    async def _close_quotation(db: AsyncSession, response_id: int, order_id: int):
        from src.data_models.buy_requests_model import BuyRequests, BuyRequestResponses

        response = (await db.execute(select(BuyRequestResponses).where(BuyRequestResponses.id == response_id))).scalar_one_or_none()
        if not response:
            return
        response.status = "accepted"
        response.order_id = order_id
        response.updated_at = utcnow()
        await db.flush()
        request = (await db.execute(select(BuyRequests).where(BuyRequests.id == response.buy_request_id))).scalar_one()
        accepted = D((await db.execute(select(func.coalesce(func.sum(BuyRequestResponses.quantity_kg), 0)).where(
            BuyRequestResponses.buy_request_id == request.id, BuyRequestResponses.status == "accepted"))).scalar())
        if accepted >= D(request.quantity_kg):
            request.status = "fulfilled"
            request.updated_at = utcnow()

    # ---- actions ---------------------------------------------------------------------

    async def start(self, vendor: Users, payload, db: AsyncSession) -> dict:
        listing = await inventory_core.lock_listing(db, payload.listing_id)
        if listing.created_by == vendor.id:
            raise HTTPException(status_code=403, detail="You cannot negotiate on your own listing.")
        if not inventory_core.is_listing_live(listing):
            raise HTTPException(status_code=409, detail="This listing is not open for offers.")
        await ensure_not_blocked(db, vendor.id, listing.created_by)
        self._validate_terms(listing, payload)

        existing = (await db.execute(select(Negotiations.id).where(
            Negotiations.listing_id == listing.id, Negotiations.vendor == vendor.id,
            Negotiations.status.in_((NEG_OPEN, EXPIRED)),
        ))).scalar_one_or_none()
        if existing:
            raise HTTPException(status_code=409, detail=f"You already have an open negotiation (#{existing}) on this listing. Continue it instead.")

        now = utcnow()
        negotiation = Negotiations(listing_id=listing.id, vendor=vendor.id, farmer=listing.created_by,
                                   status=NEG_OPEN, source="listing", created_at=now, updated_at=now)
        db.add(negotiation)
        await db.flush()
        expires_at = None if payload.draft else await self._expiry(db, payload.expires_in_hours)
        offer = self._new_offer(negotiation, 1, vendor.id, listing.created_by, "vendor", listing, payload,
                                expires_at, DRAFT if payload.draft else PENDING)
        db.add(offer)
        await db.flush()
        negotiation.current_offer_id = offer.id
        listing.inquiries_count = (listing.inquiries_count or 0) + 1
        if not payload.draft:
            await self._announce(db, negotiation, offer, listing, "offer_received")
        audit(db, "offer.created", "offer", offer.id, actor_id=vendor.id, actor_role="vendor",
              after=model_to_dict(offer))
        await db.commit()
        return {"success": "Draft saved." if payload.draft else "Offer sent.", "negotiation_id": negotiation.id,
                "offer_id": offer.id, "status": offer.status, "subtotal": offer.subtotal, "expires_at": offer.expires_at}

    async def send_draft(self, user: Users, negotiation_id: int, payload, db: AsyncSession) -> dict:
        negotiation = await self._get_negotiation(db, negotiation_id, user.id, lock=True)
        offer = await self._current_offer(db, negotiation, lock=True)
        if not offer or offer.status != DRAFT or offer.offered_by != user.id:
            raise HTTPException(status_code=409, detail="There is no draft offer of yours to send.")
        listing = await inventory_core.lock_listing(db, negotiation.listing_id)
        if not inventory_core.is_listing_live(listing):
            raise HTTPException(status_code=409, detail="This listing is no longer open for offers.")
        self._validate_terms(listing, offer)
        offer.status = PENDING
        offer.expires_at = await self._expiry(db, payload.expires_in_hours if payload else None)
        negotiation.updated_at = utcnow()
        await self._announce(db, negotiation, offer, listing, "offer_received")
        audit(db, "offer.sent", "offer", offer.id, actor_id=user.id)
        await db.commit()
        return {"success": "Offer sent.", "offer_id": offer.id, "expires_at": offer.expires_at}

    async def submit_offer(self, user: Users, negotiation_id: int, payload, db: AsyncSession) -> dict:
        """Counter the actionable offer, or make a new offer after one expired/was withdrawn."""
        negotiation = await self._get_negotiation(db, negotiation_id, user.id, lock=True)
        if negotiation.status not in (NEG_OPEN, EXPIRED):
            raise HTTPException(status_code=409, detail=f"This negotiation is {negotiation.status.lower()}.")
        listing = await inventory_core.lock_listing(db, negotiation.listing_id)
        if not inventory_core.is_listing_live(listing):
            raise HTTPException(status_code=409, detail="This listing is no longer open for offers.")
        await ensure_not_blocked(db, negotiation.vendor, negotiation.farmer)
        self._validate_terms(listing, payload)

        current = await self._current_offer(db, negotiation, lock=True)
        now = utcnow()
        template = "offer_received"
        supersedes = None
        if current and current.status == PENDING and (not current.expires_at or current.expires_at > now):
            if current.recipient != user.id:
                raise HTTPException(status_code=409, detail="Your offer is waiting for a response. Withdraw it to change it.")
            current.status = COUNTERED
            current.responded_at = now
            supersedes = current.id
            template = "offer_countered"
        elif current and current.status == DRAFT:
            raise HTTPException(status_code=409, detail="Send or discard the draft first.")
        elif current and current.status == PENDING:
            current.status = EXPIRED  # lazily expire before replacing
            supersedes = current.id
        elif current:
            supersedes = current.id

        version = (await db.execute(select(func.coalesce(func.max(Offers.version), 0)).where(
            Offers.negotiation_id == negotiation.id
        ))).scalar() + 1
        role = "farmer" if user.id == negotiation.farmer else "vendor"
        recipient = negotiation.vendor if role == "farmer" else negotiation.farmer
        offer = self._new_offer(negotiation, version, user.id, recipient, role, listing, payload,
                                await self._expiry(db, payload.expires_in_hours), PENDING, supersedes)
        db.add(offer)
        await db.flush()
        negotiation.current_offer_id = offer.id
        negotiation.status = NEG_OPEN
        negotiation.updated_at = now
        await self._announce(db, negotiation, offer, listing, template)
        audit(db, "offer.countered" if template == "offer_countered" else "offer.created", "offer", offer.id,
              actor_id=user.id, actor_role=role, after=model_to_dict(offer))
        await db.commit()
        return {"success": "Counteroffer sent." if template == "offer_countered" else "Offer sent.",
                "offer_id": offer.id, "version": version, "subtotal": offer.subtotal, "expires_at": offer.expires_at}

    async def accept(self, user: Users, negotiation_id: int, payload, db: AsyncSession) -> dict:
        negotiation = await self._get_negotiation(db, negotiation_id, user.id, lock=True)
        if negotiation.status != NEG_OPEN:
            raise HTTPException(status_code=409, detail=f"This negotiation is {negotiation.status.lower()}.")
        offer = await self._current_offer(db, negotiation, lock=True)
        if not offer or offer.id != payload.offer_id:
            raise HTTPException(status_code=409, detail="That offer is no longer the current offer. Refresh and review the latest terms.")
        if offer.status != PENDING:
            raise HTTPException(status_code=409, detail=f"This offer is {offer.status.lower()} and can't be accepted.")
        if offer.recipient != user.id:
            raise HTTPException(status_code=403, detail="Only the recipient of an offer can accept it.")
        self._check_offer_live(offer)

        listing = await inventory_core.lock_listing(db, negotiation.listing_id)
        now = utcnow()
        order = await order_core.create_order(
            db, listing=listing, vendor_id=negotiation.vendor, quantity=offer.quantity, unit_price=offer.unit_price,
            source="negotiation", accepted_by=user.id, negotiation_id=negotiation.id, offer_id=offer.id,
            fulfillment_mode=offer.delivery_preference, payment_terms=payload.payment_terms,
            expected_delivery_date=offer.preferred_date, delivery_instructions=payload.delivery_instructions,
            farmer_confirmed=(user.id == negotiation.farmer), vendor_confirmed=(user.id == negotiation.vendor),
            extra_terms={"packaging_spec": offer.packaging, "quality_spec": offer.quality_spec,
                         "offer_version": offer.version},
        )
        offer.status = ACCEPTED
        offer.responded_at = now
        negotiation.status = ACCEPTED
        negotiation.order_id = order.id
        negotiation.closed_at = now
        negotiation.updated_at = now
        if negotiation.source == "buy_request" and negotiation.source_ref_id:
            await self._close_quotation(db, negotiation.source_ref_id, order.id)
        crop = await self._crop_name(db, listing)
        await notify_user(db, offer.offered_by, "offer_accepted", {"crop": crop, "order_number": order.order_number},
                          ref_type="order", ref_id=order.id)
        audit(db, "offer.accepted", "offer", offer.id, actor_id=user.id,
              after={"order_id": order.id, "unit_price": offer.unit_price, "quantity": offer.quantity})
        await db.commit()
        return {
            "success": "Offer accepted. Order created - the other party now confirms the final charges.",
            "order_id": order.id, "order_number": order.order_number,
            "agreed_unit_price": offer.unit_price, "quantity": offer.quantity, "unit": offer.unit,
            "total_payable": order.total_price, "status": await order_core.status_of(db, order),
        }

    async def reject(self, user: Users, negotiation_id: int, reason: str | None, db: AsyncSession) -> dict:
        negotiation = await self._get_negotiation(db, negotiation_id, user.id, lock=True)
        offer = await self._current_offer(db, negotiation, lock=True)
        if not offer or offer.status != PENDING:
            raise HTTPException(status_code=409, detail="There is no pending offer to reject.")
        if offer.recipient != user.id:
            raise HTTPException(status_code=403, detail="Only the recipient of an offer can reject it.")
        now = utcnow()
        offer.status = REJECTED
        offer.responded_at = now
        negotiation.status = REJECTED
        negotiation.closed_at = now
        negotiation.updated_at = now
        negotiation.cancel_reason = reason
        listing = (await db.execute(select(FarmerInventory).where(FarmerInventory.id == negotiation.listing_id))).scalar_one()
        await notify_user(db, offer.offered_by, "offer_rejected",
                          {"party": _name(user), "crop": await self._crop_name(db, listing)},
                          ref_type="negotiation", ref_id=negotiation.id)
        audit(db, "offer.rejected", "offer", offer.id, actor_id=user.id, after={"reason": reason})
        await db.commit()
        return {"success": "Offer rejected."}

    async def withdraw(self, user: Users, negotiation_id: int, db: AsyncSession) -> dict:
        negotiation = await self._get_negotiation(db, negotiation_id, user.id, lock=True)
        offer = await self._current_offer(db, negotiation, lock=True)
        if not offer or offer.status not in (PENDING, DRAFT) or offer.offered_by != user.id:
            raise HTTPException(status_code=409, detail="You have no pending offer to withdraw.")
        was_draft = offer.status == DRAFT
        offer.status = WITHDRAWN
        offer.responded_at = utcnow()
        negotiation.updated_at = utcnow()
        if not was_draft:
            listing = (await db.execute(select(FarmerInventory).where(FarmerInventory.id == negotiation.listing_id))).scalar_one()
            await notify_user(db, offer.recipient, "offer_withdrawn",
                              {"party": _name(user), "crop": await self._crop_name(db, listing)},
                              ref_type="negotiation", ref_id=negotiation.id)
        audit(db, "offer.withdrawn", "offer", offer.id, actor_id=user.id)
        await db.commit()
        return {"success": "Offer withdrawn. You can send a new offer in this negotiation."}

    async def cancel(self, user: Users, negotiation_id: int, reason: str | None, db: AsyncSession) -> dict:
        negotiation = await self._get_negotiation(db, negotiation_id, user.id, lock=True)
        if negotiation.status not in (NEG_OPEN, EXPIRED):
            raise HTTPException(status_code=409, detail=f"This negotiation is already {negotiation.status.lower()}.")
        offer = await self._current_offer(db, negotiation, lock=True)
        now = utcnow()
        if offer and offer.status in (PENDING, DRAFT):
            offer.status = CANCELLED
            offer.responded_at = now
        negotiation.status = CANCELLED
        negotiation.cancelled_by = user.id
        negotiation.cancel_reason = reason
        negotiation.closed_at = now
        negotiation.updated_at = now
        other = negotiation.farmer if user.id == negotiation.vendor else negotiation.vendor
        listing = (await db.execute(select(FarmerInventory).where(FarmerInventory.id == negotiation.listing_id))).scalar_one()
        await notify_user(db, other, "negotiation_cancelled",
                          {"party": _name(user), "crop": await self._crop_name(db, listing)},
                          ref_type="negotiation", ref_id=negotiation.id)
        audit(db, "negotiation.cancelled", "negotiation", negotiation.id, actor_id=user.id, after={"reason": reason})
        await db.commit()
        return {"success": "Negotiation cancelled."}

    # ---- reads --------------------------------------------------------------------------

    def _offer_view(self, offer: Offers, viewer_id: int, floor) -> dict:
        data = model_to_dict(offer)
        data["is_actionable_by_me"] = (
            offer.status == PENDING and offer.recipient == viewer_id
            and (not offer.expires_at or offer.expires_at > utcnow())
        )
        data["is_mine"] = offer.offered_by == viewer_id
        if floor is not None:  # only passed for the farmer
            data["below_my_minimum_price"] = D(offer.unit_price) < D(floor)
        return data

    async def get(self, user: Users, negotiation_id: int, db: AsyncSession) -> dict:
        negotiation = await self._get_negotiation(db, negotiation_id, user.id)
        listing = (await db.execute(select(FarmerInventory).where(FarmerInventory.id == negotiation.listing_id))).scalar_one()
        offers = (await db.execute(
            select(Offers).where(Offers.negotiation_id == negotiation_id).order_by(Offers.version)
        )).scalars().all()
        is_farmer = user.id == negotiation.farmer
        floor = listing.min_acceptable_price if is_farmer else None
        if not is_farmer:
            offers = [o for o in offers if not (o.status == DRAFT and o.offered_by != user.id)]
        else:
            offers = [o for o in offers if o.status != DRAFT]
        users = {u.id: u for u in (await db.execute(
            select(Users).where(Users.id.in_((negotiation.vendor, negotiation.farmer)))
        )).scalars().all()}
        current = next((o for o in offers if o.id == negotiation.current_offer_id), None)
        return {
            **model_to_dict(negotiation),
            "vendor_name": _name(users.get(negotiation.vendor)),
            "farmer_name": _name(users.get(negotiation.farmer)),
            "listing": {
                "id": listing.id, "crop_name": await self._crop_name(db, listing), "variety": listing.variety,
                "asking_price": listing.proposed_cost, "unit": listing.unit, "available_quantity": listing.weight_kg,
                "min_order_qty": listing.min_order_qty, "quality_grade": listing.quality_grade,
                **({"my_minimum_acceptable_price": listing.min_acceptable_price} if is_farmer else {}),
            },
            "current_offer": self._offer_view(current, user.id, floor) if current else None,
            "history": [self._offer_view(o, user.id, floor) for o in offers],
        }

    async def list_mine(self, user: Users, db: AsyncSession, status_filter: str | None = None,
                        listing_id: int | None = None, crop_id: int | None = None) -> list[dict]:
        stmt = (
            select(Negotiations, Offers, FarmerInventory, Crops)
            .join(FarmerInventory, Negotiations.listing_id == FarmerInventory.id)
            .join(Crops, FarmerInventory.crop == Crops.id)
            .outerjoin(Offers, Offers.id == Negotiations.current_offer_id)
            .where(or_(Negotiations.vendor == user.id, Negotiations.farmer == user.id))
            .order_by(Negotiations.updated_at.desc())
        )
        if status_filter:
            stmt = stmt.where(Negotiations.status == status_filter.upper())
        if listing_id:
            stmt = stmt.where(Negotiations.listing_id == listing_id)
        if crop_id:
            stmt = stmt.where(FarmerInventory.crop == crop_id)
        rows = (await db.execute(stmt)).all()
        other_ids = {n.farmer if n.vendor == user.id else n.vendor for n, *_ in rows}
        names = {u.id: _name(u) for u in (await db.execute(select(Users).where(Users.id.in_(other_ids)))).scalars().all()} if other_ids else {}
        result = []
        for negotiation, offer, listing, crop in rows:
            is_farmer = user.id == negotiation.farmer
            visible_offer = offer if offer and not (offer.status == DRAFT and offer.offered_by != user.id) else None
            result.append({
                "negotiation_id": negotiation.id,
                "status": negotiation.status,
                "my_role": "farmer" if is_farmer else "vendor",
                "counterparty_id": negotiation.vendor if is_farmer else negotiation.farmer,
                "counterparty_name": names.get(negotiation.vendor if is_farmer else negotiation.farmer),
                "listing_id": listing.id,
                "crop_name": crop.crop_name,
                "asking_price": listing.proposed_cost,
                "unit": listing.unit,
                "current_offer": self._offer_view(visible_offer, user.id,
                                                  listing.min_acceptable_price if is_farmer else None) if visible_offer else None,
                "order_id": negotiation.order_id,
                "updated_at": negotiation.updated_at,
            })
        return result

    async def compare(self, vendor: Users, crop_id: int, db: AsyncSession) -> list[dict]:
        """Vendor view: current terms across farmers for one crop, cheapest first."""
        rows = await self.list_mine(vendor, db, crop_id=crop_id)
        rows = [r for r in rows if r["my_role"] == "vendor" and r["status"] in (NEG_OPEN, EXPIRED) and r["current_offer"]]
        for r in rows:
            r["current_unit_price"] = r["current_offer"]["unit_price"]
            r["current_subtotal"] = r["current_offer"]["subtotal"]
            r["awaiting_my_response"] = r["current_offer"]["is_actionable_by_me"]
        return sorted(rows, key=lambda r: D(r["current_unit_price"]))

    # ---- scheduler hooks ------------------------------------------------------------------

    @staticmethod
    async def expire_due(db: AsyncSession) -> int:
        now = utcnow()
        offers = (await db.execute(
            select(Offers).where(Offers.status == PENDING, Offers.expires_at <= now)
            .with_for_update(skip_locked=True).limit(200)
        )).scalars().all()
        for offer in offers:
            offer.status = EXPIRED
            negotiation = (await db.execute(select(Negotiations).where(Negotiations.id == offer.negotiation_id))).scalar_one()
            if negotiation.current_offer_id == offer.id and negotiation.status == NEG_OPEN:
                negotiation.status = EXPIRED
                negotiation.updated_at = now
            listing = (await db.execute(select(FarmerInventory).where(FarmerInventory.id == negotiation.listing_id))).scalar_one()
            crop = (await db.execute(select(Crops.crop_name).where(Crops.id == listing.crop))).scalar_one_or_none()
            for party_id in (offer.offered_by, offer.recipient):
                await notify_user(db, party_id, "offer_expired", {"crop": crop}, ref_type="negotiation",
                                  ref_id=negotiation.id, dedupe_key=f"offer_expired:{offer.id}")
            audit(db, "offer.expired", "offer", offer.id)
        await db.commit()
        return len(offers)

    @staticmethod
    async def warn_expiring(db: AsyncSession) -> int:
        hours = int(await get_setting(db, "offer_expiry_warning_hours"))
        now = utcnow()
        offers = (await db.execute(
            select(Offers).where(
                Offers.status == PENDING, Offers.expiry_notified.is_(False),
                Offers.expires_at > now, Offers.expires_at <= now + timedelta(hours=hours),
            ).limit(200)
        )).scalars().all()
        for offer in offers:
            negotiation = (await db.execute(select(Negotiations).where(Negotiations.id == offer.negotiation_id))).scalar_one()
            listing = (await db.execute(select(FarmerInventory).where(FarmerInventory.id == negotiation.listing_id))).scalar_one()
            crop = (await db.execute(select(Crops.crop_name).where(Crops.id == listing.crop))).scalar_one_or_none()
            for party_id in (offer.offered_by, offer.recipient):
                await notify_user(db, party_id, "offer_expiring",
                                  {"crop": crop, "expires_at": offer.expires_at.strftime("%Y-%m-%d %H:%M")},
                                  ref_type="negotiation", ref_id=negotiation.id, category="reminder",
                                  dedupe_key=f"offer_expiring:{offer.id}")
            offer.expiry_notified = True
        await db.commit()
        return len(offers)
