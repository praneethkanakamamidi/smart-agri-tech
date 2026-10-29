from datetime import date

from fastapi import HTTPException, status
from sqlalchemy import select, func, or_
from sqlalchemy.orm import joinedload
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.audit import audit
from src.core.money import D, money
from src.data_models.buy_requests_model import BuyRequests, BuyRequestResponses, BuyRequestInvites
from src.data_models.catalog_model import Units
from src.data_models.crops_model import Crops
from src.data_models.farmer_inventory_model import FarmerInventory
from src.data_models.negotiation_model import Negotiations, Offers, PENDING, NEG_OPEN
from src.data_models.users_model import Users
from src.helpers.serializers import model_to_dict
from src.security_utils.role_guard import get_role_name, FARMER
from src.services import inventory_core, order_core
from src.services.negotiations_service import NegotiationsService, ensure_not_blocked
from src.services.notifications_service import notify_user
from src.services.trust_service import ratings_for, completed_counts
from src.core.clock import utcnow


def _name(user):
    return f"{user.first_name} {user.last_name}".strip() if user else None


class BuyRequestsService:
    """Procurement requests: vendors post demand, invite farmers, compare quotes, negotiate and accept."""

    _request_options = (
        joinedload(BuyRequests.vendor_user), joinedload(BuyRequests.crop_rel),
        joinedload(BuyRequests.state_rel), joinedload(BuyRequests.district_rel),
    )

    async def _get_owned_request(self, request_id: int, vendor_id: int, db: AsyncSession, lock=False) -> BuyRequests:
        stmt = select(BuyRequests).where(BuyRequests.id == request_id)
        if lock:
            stmt = stmt.with_for_update()
        buy_request = (await db.execute(stmt)).scalar_one_or_none()
        if not buy_request or buy_request.vendor != vendor_id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Buy request not found.")
        return buy_request

    async def _response_counts(self, request_ids, db: AsyncSession) -> dict:
        if not request_ids:
            return {}
        return dict((await db.execute(
            select(BuyRequestResponses.buy_request_id, func.count(BuyRequestResponses.id))
            .where(BuyRequestResponses.buy_request_id.in_(request_ids))
            .group_by(BuyRequestResponses.buy_request_id)
        )).all())

    async def _accepted_qty(self, db: AsyncSession, request_id: int):
        return D((await db.execute(select(func.coalesce(func.sum(BuyRequestResponses.quantity_kg), 0)).where(
            BuyRequestResponses.buy_request_id == request_id, BuyRequestResponses.status == "accepted",
        ))).scalar())

    def _request_view(self, r: BuyRequests, response_count: int = 0, **extra) -> dict:
        return model_to_dict(
            r, vendor_name=_name(r.vendor_user), crop_name=r.crop_rel.crop_name if r.crop_rel else None,
            state_name=r.state_rel.state_name if r.state_rel else None,
            district_name=r.district_rel.district_name if r.district_rel else None,
            response_count=response_count, **extra,
        )

    async def _invite(self, db: AsyncSession, buy_request: BuyRequests, farmer_ids: list[int], vendor: Users) -> int:
        crop = (await db.execute(select(Crops.crop_name).where(Crops.id == buy_request.crop))).scalar_one_or_none()
        invited = 0
        for farmer_id in set(farmer_ids):
            farmer = (await db.execute(select(Users).where(Users.id == farmer_id))).scalar_one_or_none()
            if not farmer or await get_role_name(farmer, db) != FARMER:
                continue
            exists = (await db.execute(select(BuyRequestInvites.id).where(
                BuyRequestInvites.buy_request_id == buy_request.id, BuyRequestInvites.farmer == farmer_id))).first()
            if exists:
                continue
            db.add(BuyRequestInvites(buy_request_id=buy_request.id, farmer=farmer_id, created_at=utcnow()))
            await notify_user(db, farmer_id, "buy_request_invite",
                              {"party": _name(vendor), "quantity": D(buy_request.quantity_kg), "unit": buy_request.unit,
                               "crop": crop}, ref_type="buy_request", ref_id=buy_request.id)
            invited += 1
        return invited

    # ---- vendor ---------------------------------------------------------------------

    async def create_request(self, payload, vendor: Users, db: AsyncSession):
        crop = (await db.execute(select(Crops).where(Crops.id == payload.crop))).scalar_one_or_none()
        if not crop:
            raise HTTPException(status_code=404, detail="Crop not found.")
        if not (await db.execute(select(Units.id).where(Units.code == payload.unit.lower()))).first():
            raise HTTPException(status_code=422, detail=f"Unknown unit '{payload.unit}'.")
        if payload.needed_by and payload.needed_by < date.today():
            raise HTTPException(status_code=422, detail="needed_by cannot be in the past.")
        now = utcnow()
        buy_request = BuyRequests(
            vendor=vendor.id, crop=payload.crop, quantity_kg=payload.quantity_kg, unit=payload.unit.lower(),
            max_price_per_kg=payload.max_price_per_kg, quality_grade=(payload.quality_grade or "").upper() or None,
            quality_spec=payload.quality_spec, packaging=payload.packaging, state=payload.state,
            district=payload.district, needed_by=payload.needed_by, description=payload.description,
            status="open", created_at=now, updated_at=now,
        )
        db.add(buy_request)
        await db.flush()
        invited = await self._invite(db, buy_request, payload.invite_farmer_ids, vendor)
        audit(db, "buy_request.created", "buy_request", buy_request.id, actor_id=vendor.id, actor_role="vendor")
        await db.commit()
        return {"success": "Buy request posted.", "buy_request_id": buy_request.id, "invited_farmers": invited}

    async def invite(self, request_id: int, farmer_ids: list[int], vendor: Users, db: AsyncSession) -> dict:
        buy_request = await self._get_owned_request(request_id, vendor.id, db)
        if buy_request.status != "open":
            raise HTTPException(status_code=409, detail="This buy request is not open.")
        invited = await self._invite(db, buy_request, farmer_ids, vendor)
        await db.commit()
        return {"success": f"{invited} farmer(s) invited to quote."}

    async def list_my_requests(self, vendor_id: int, db: AsyncSession):
        requests = (await db.execute(
            select(BuyRequests).where(BuyRequests.vendor == vendor_id).options(*self._request_options)
            .order_by(BuyRequests.created_at.desc())
        )).scalars().unique().all()
        counts = await self._response_counts([r.id for r in requests], db)
        result = []
        for r in requests:
            accepted = await self._accepted_qty(db, r.id)
            result.append(self._request_view(r, counts.get(r.id, 0), accepted_quantity=accepted,
                                             remaining_quantity=max(D(r.quantity_kg) - accepted, D(0))))
        return result

    async def close_request(self, request_id: int, vendor_id: int, db: AsyncSession):
        buy_request = await self._get_owned_request(request_id, vendor_id, db, lock=True)
        if buy_request.status != "open":
            raise HTTPException(status_code=400, detail=f"Buy request is already {buy_request.status}.")
        buy_request.status = "closed"
        buy_request.updated_at = utcnow()
        crop = (await db.execute(select(Crops.crop_name).where(Crops.id == buy_request.crop))).scalar_one_or_none()
        pending = (await db.execute(select(BuyRequestResponses).where(
            BuyRequestResponses.buy_request_id == request_id, BuyRequestResponses.status == "pending"
        ))).scalars().all()
        for response in pending:
            response.status = "rejected"
            response.updated_at = utcnow()
            await notify_user(db, response.farmer, "buy_response_rejected", {"crop": crop},
                              ref_type="buy_request", ref_id=request_id)
        await db.commit()
        return {"success": "Buy request closed."}

    async def compare_responses(self, request_id: int, vendor_id: int, db: AsyncSession):
        """All quotations with total cost and farmer trust indicators, cheapest first."""
        buy_request = await self._get_owned_request(request_id, vendor_id, db)
        responses = (await db.execute(
            select(BuyRequestResponses).where(BuyRequestResponses.buy_request_id == request_id)
            .options(joinedload(BuyRequestResponses.farmer_user), joinedload(BuyRequestResponses.farmer_inventory_rel))
            .order_by(BuyRequestResponses.price_per_kg.asc(), BuyRequestResponses.created_at.asc())
        )).scalars().unique().all()
        farmer_ids = [r.farmer for r in responses]
        ratings = await ratings_for(db, farmer_ids)
        completed = await completed_counts(db, farmer_ids)
        result = []
        for r in responses:
            listing = r.farmer_inventory_rel
            rating = ratings.get(r.farmer)
            result.append(model_to_dict(
                r, farmer_name=_name(r.farmer_user), total_cost=money(D(r.price_per_kg) * D(r.quantity_kg)),
                quality_grade=listing.quality_grade if listing else None,
                harvest_date=listing.harvest_date if listing else None,
                listing_available=listing.weight_kg if listing else None,
                farmer_rating=rating[0] if rating else None, farmer_review_count=rating[1] if rating else 0,
                farmer_completed_orders=completed.get(r.farmer, 0),
                within_max_price=(buy_request.max_price_per_kg is None or r.price_per_kg <= buy_request.max_price_per_kg),
            ))
        return {"buy_request": model_to_dict(buy_request), "accepted_quantity": await self._accepted_qty(db, request_id),
                "quotations": result}

    async def _pending_response_for_vendor(self, response_id: int, vendor_id: int, db: AsyncSession, allowed=("pending",)):
        response = (await db.execute(
            select(BuyRequestResponses).where(BuyRequestResponses.id == response_id)
            .options(joinedload(BuyRequestResponses.buy_request_rel)).with_for_update(of=BuyRequestResponses)
        )).scalar_one_or_none()
        if not response or response.buy_request_rel.vendor != vendor_id:
            raise HTTPException(status_code=404, detail="Response not found.")
        if response.status not in allowed:
            raise HTTPException(status_code=400, detail=f"Response is already {response.status}.")
        if response.buy_request_rel.status != "open":
            raise HTTPException(status_code=400, detail=f"Buy request is {response.buy_request_rel.status}.")
        return response

    async def shortlist(self, response_id: int, vendor_id: int, shortlisted: bool, db: AsyncSession):
        response = await self._pending_response_for_vendor(response_id, vendor_id, db, ("pending", "negotiating"))
        response.shortlisted = shortlisted
        await db.commit()
        return {"success": "Shortlisted." if shortlisted else "Removed from shortlist."}

    async def negotiate(self, response_id: int, vendor: Users, db: AsyncSession):
        """Turn a quotation into a negotiation: the farmer's quote becomes the first offer to the vendor."""
        response = await self._pending_response_for_vendor(response_id, vendor.id, db)
        listing = await inventory_core.lock_listing(db, response.farmer_inventory)
        if not inventory_core.is_listing_live(listing):
            raise HTTPException(status_code=409, detail="The farmer's listing is no longer available.")
        await ensure_not_blocked(db, vendor.id, response.farmer)
        now = utcnow()
        negotiation = Negotiations(listing_id=listing.id, vendor=vendor.id, farmer=response.farmer, status=NEG_OPEN,
                                   source="buy_request", source_ref_id=response.id, created_at=now, updated_at=now)
        db.add(negotiation)
        await db.flush()
        service = NegotiationsService()
        quantity, price = D(response.quantity_kg), D(response.price_per_kg)
        offer = Offers(
            negotiation_id=negotiation.id, version=1, offered_by=response.farmer, recipient=vendor.id,
            offered_by_role="farmer", quantity=quantity, unit=listing.unit, unit_price=price,
            subtotal=money(quantity * price), message=response.message, status=PENDING,
            expires_at=await service._expiry(db, None), expiry_notified=False, created_at=now,
        )
        db.add(offer)
        await db.flush()
        negotiation.current_offer_id = offer.id
        response.status = "negotiating"
        response.negotiation_id = negotiation.id
        response.updated_at = now
        await db.commit()
        return {"success": "Negotiation opened from the quotation. You can now counter or accept it.",
                "negotiation_id": negotiation.id, "offer_id": offer.id}

    async def accept_response(self, response_id: int, vendor: Users, payload, db: AsyncSession):
        response = await self._pending_response_for_vendor(response_id, vendor.id, db)
        buy_request = response.buy_request_rel
        listing = await inventory_core.lock_listing(db, response.farmer_inventory)
        order = await order_core.create_order(
            db, listing=listing, vendor_id=vendor.id, quantity=response.quantity_kg, unit_price=response.price_per_kg,
            source="buy_request", accepted_by=vendor.id, fulfillment_mode=payload.fulfillment_mode if payload else None,
            payment_terms=payload.payment_terms if payload else None, expected_delivery_date=buy_request.needed_by,
            farmer_confirmed=True, vendor_confirmed=True,
            extra_terms={"buy_request_id": buy_request.id, "quotation_id": response.id,
                         "quality_spec": buy_request.quality_spec, "packaging_spec": buy_request.packaging},
        )
        response.status = "accepted"
        response.order_id = order.id
        response.updated_at = utcnow()
        await db.flush()
        if await self._accepted_qty(db, buy_request.id) >= D(buy_request.quantity_kg):
            buy_request.status = "fulfilled"
            buy_request.updated_at = utcnow()
        crop = (await db.execute(select(Crops.crop_name).where(Crops.id == buy_request.crop))).scalar_one_or_none()
        await notify_user(db, response.farmer, "buy_response_accepted", {"order_number": order.order_number, "crop": crop},
                          ref_type="order", ref_id=order.id)
        await db.commit()
        return {"success": "Quotation accepted. Order created.", "order_id": order.id, "order_number": order.order_number,
                "total_payable": order.total_price, "buy_request_status": buy_request.status}

    async def reject_response(self, response_id: int, vendor_id: int, db: AsyncSession):
        response = await self._pending_response_for_vendor(response_id, vendor_id, db, ("pending", "negotiating"))
        response.status = "rejected"
        response.updated_at = utcnow()
        crop = (await db.execute(select(Crops.crop_name).where(Crops.id == response.buy_request_rel.crop))).scalar_one_or_none()
        await notify_user(db, response.farmer, "buy_response_rejected", {"crop": crop},
                          ref_type="buy_request", ref_id=response.buy_request_id)
        await db.commit()
        return {"success": "Response rejected."}

    # ---- farmer ---------------------------------------------------------------------

    async def list_open_requests(self, farmer: Users, db: AsyncSession, crop_id=None, state_id=None, district_id=None,
                                 invited_only: bool = False, page: int = 1, page_size: int = 20):
        invited_ids = set((await db.execute(select(BuyRequestInvites.buy_request_id).where(
            BuyRequestInvites.farmer == farmer.id))).scalars().all())
        stmt = (
            select(BuyRequests)
            .where(BuyRequests.status == "open",
                   or_(BuyRequests.needed_by.is_(None), BuyRequests.needed_by >= date.today()))
            .options(*self._request_options).order_by(BuyRequests.created_at.desc())
            .limit(page_size).offset((page - 1) * page_size)
        )
        if crop_id:
            stmt = stmt.where(BuyRequests.crop == crop_id)
        if state_id:
            stmt = stmt.where(or_(BuyRequests.state.is_(None), BuyRequests.state == state_id))
        if district_id:
            stmt = stmt.where(or_(BuyRequests.district.is_(None), BuyRequests.district == district_id))
        if invited_only:
            stmt = stmt.where(BuyRequests.id.in_(invited_ids or {-1}))
        requests = (await db.execute(stmt)).scalars().unique().all()
        counts = await self._response_counts([r.id for r in requests], db)
        return [self._request_view(r, counts.get(r.id, 0), invited=r.id in invited_ids) for r in requests]

    async def respond(self, request_id: int, payload, farmer_id: int, db: AsyncSession):
        buy_request = (await db.execute(select(BuyRequests).where(BuyRequests.id == request_id))).scalar_one_or_none()
        if not buy_request or buy_request.status != "open":
            raise HTTPException(status_code=404, detail="Open buy request not found.")
        if buy_request.vendor == farmer_id:
            raise HTTPException(status_code=403, detail="You cannot respond to your own buy request.")
        await ensure_not_blocked(db, farmer_id, buy_request.vendor)
        listing = (await db.execute(select(FarmerInventory).where(FarmerInventory.id == payload.farmer_inventory))).scalar_one_or_none()
        if not listing or listing.created_by != farmer_id or listing.deleted_at:
            raise HTTPException(status_code=404, detail="Listing not found.")
        if listing.crop != buy_request.crop:
            raise HTTPException(status_code=422, detail="Listing crop does not match the buy request.")
        if listing.unit != (buy_request.unit or "kg"):
            raise HTTPException(status_code=422, detail=f"Quote in the requested unit ({buy_request.unit}).")
        if D(payload.quantity_kg) > D(listing.weight_kg):
            raise HTTPException(status_code=422, detail=f"Quantity exceeds your available stock ({D(listing.weight_kg)}).")
        if D(payload.quantity_kg) > D(buy_request.quantity_kg):
            raise HTTPException(status_code=422, detail=f"Quantity exceeds what the vendor needs ({buy_request.quantity_kg}).")
        if (await db.execute(select(BuyRequestResponses.id).where(
            BuyRequestResponses.buy_request_id == request_id, BuyRequestResponses.farmer == farmer_id,
            BuyRequestResponses.status.in_(("pending", "negotiating")),
        ))).first():
            raise HTTPException(status_code=409, detail="You already have an active quotation on this buy request.")
        now = utcnow()
        response = BuyRequestResponses(
            buy_request_id=request_id, farmer=farmer_id, farmer_inventory=listing.id,
            price_per_kg=payload.price_per_kg, quantity_kg=payload.quantity_kg, message=payload.message,
            status="pending", shortlisted=False, created_at=now, updated_at=now,
        )
        db.add(response)
        await db.flush()
        crop = (await db.execute(select(Crops.crop_name).where(Crops.id == buy_request.crop))).scalar_one_or_none()
        await notify_user(db, buy_request.vendor, "buy_response_received",
                          {"price": payload.price_per_kg, "unit": buy_request.unit, "quantity": payload.quantity_kg,
                           "crop": crop}, ref_type="buy_request", ref_id=request_id)
        await db.commit()
        return {"success": "Quotation sent to the vendor.", "response_id": response.id}

    async def list_my_responses(self, farmer_id: int, db: AsyncSession):
        responses = (await db.execute(
            select(BuyRequestResponses).where(BuyRequestResponses.farmer == farmer_id)
            .options(joinedload(BuyRequestResponses.buy_request_rel).joinedload(BuyRequests.crop_rel),
                     joinedload(BuyRequestResponses.buy_request_rel).joinedload(BuyRequests.vendor_user))
            .order_by(BuyRequestResponses.created_at.desc())
        )).scalars().unique().all()
        return [
            model_to_dict(r, crop_name=r.buy_request_rel.crop_rel.crop_name if r.buy_request_rel.crop_rel else None,
                          vendor_name=_name(r.buy_request_rel.vendor_user), request_status=r.buy_request_rel.status)
            for r in responses
        ]

    async def withdraw_response(self, response_id: int, farmer_id: int, db: AsyncSession):
        response = (await db.execute(select(BuyRequestResponses).where(BuyRequestResponses.id == response_id))).scalar_one_or_none()
        if not response or response.farmer != farmer_id:
            raise HTTPException(status_code=404, detail="Response not found.")
        if response.status != "pending":
            raise HTTPException(status_code=400, detail=f"Response is already {response.status}.")
        response.status = "withdrawn"
        response.updated_at = utcnow()
        await db.commit()
        return {"success": "Response withdrawn."}

    @staticmethod
    async def close_expired(db: AsyncSession) -> int:
        rows = (await db.execute(select(BuyRequests).where(
            BuyRequests.status == "open", BuyRequests.needed_by < date.today()
        ))).scalars().all()
        for r in rows:
            r.status = "closed"
            r.updated_at = utcnow()
        await db.commit()
        return len(rows)
