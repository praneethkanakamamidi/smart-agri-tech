
from fastapi import HTTPException
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.audit import audit
from src.core.crypto import encrypt, decrypt, mask
from src.data_models.profiles_model import FarmerProfiles, VendorProfiles, VerificationRequests
from src.data_models.users_model import Users, PENDING_VERIFICATION, VERIFIED, SUSPENDED
from src.data_models.farmer_inventory_model import FarmerInventory, ACTIVE
from src.helpers.serializers import model_to_dict
from src.security_utils.role_guard import get_role_name, FARMER, VENDOR
from src.services.files_service import FilesService
from src.services.trust_service import trust_indicators
from src.core.clock import utcnow

FARMER_PLAIN_FIELDS = (
    "farm_name", "farm_address", "village", "pincode", "state", "district", "produce_categories",
    "farming_type", "farm_size_acres", "harvest_schedule", "payout_method", "bank_account_holder", "bank_ifsc",
)
VENDOR_FIELDS = (
    "business_name", "business_type", "business_address", "pincode", "state", "district", "gstin",
    "purchase_categories", "typical_quantity", "typical_quantity_unit", "billing_address",
    "delivery_preference", "payment_preference",
)


async def _set_location(profile, payload, address_fields: tuple[str, ...]):
    """GPS/manual coordinates win; otherwise geocode a changed address if a geocoder is configured."""
    if (payload.latitude is None) != (payload.longitude is None):
        raise HTTPException(status_code=422, detail="Send latitude and longitude together.")
    if payload.latitude is not None:
        profile.latitude, profile.longitude, profile.location_source = payload.latitude, payload.longitude, "gps"
        return
    address = ", ".join(str(getattr(payload, f)) for f in address_fields if getattr(payload, f, None))
    if address and profile.location_source != "gps":
        from src.agents.integrations.maps import get_geocoder

        point = await get_geocoder().geocode(address)
        if point:
            profile.latitude, profile.longitude, profile.location_source = point.lat, point.lon, "geocoded"


def _farmer_view(profile: FarmerProfiles | None) -> dict | None:
    if not profile:
        return None
    data = model_to_dict(profile)
    data.pop("bank_account_number_enc", None)
    data.pop("upi_id_enc", None)
    data["bank_account_number_masked"] = mask(decrypt(profile.bank_account_number_enc))
    data["upi_id_masked"] = mask(decrypt(profile.upi_id_enc), visible=6)
    return data


class ProfilesService:
    async def get_my_profile(self, user: Users, db: AsyncSession) -> dict:
        role = await get_role_name(user, db)
        if role == FARMER:
            profile = (await db.execute(select(FarmerProfiles).where(FarmerProfiles.user_id == user.id))).scalar_one_or_none()
            return {"role": role, "profile": _farmer_view(profile), "is_complete": self._farmer_complete(profile)}
        if role == VENDOR:
            profile = (await db.execute(select(VendorProfiles).where(VendorProfiles.user_id == user.id))).scalar_one_or_none()
            return {"role": role, "profile": model_to_dict(profile) if profile else None,
                    "is_complete": bool(profile and profile.business_name and profile.business_type and profile.business_address)}
        return {"role": role, "profile": None, "is_complete": True}

    @staticmethod
    def _farmer_complete(profile: FarmerProfiles | None) -> bool:
        return bool(profile and profile.farm_address and profile.district and profile.payout_method
                    and (profile.bank_account_number_enc or profile.upi_id_enc))

    async def upsert_farmer_profile(self, user: Users, payload, db: AsyncSession) -> dict:
        if await get_role_name(user, db) != FARMER:
            raise HTTPException(status_code=403, detail="Only farmers have a farmer profile.")
        profile = (await db.execute(select(FarmerProfiles).where(FarmerProfiles.user_id == user.id))).scalar_one_or_none()
        now = utcnow()
        if not profile:
            profile = FarmerProfiles(user_id=user.id, created_at=now)
            db.add(profile)
        for field in FARMER_PLAIN_FIELDS:
            value = getattr(payload, field)
            if value is not None:
                setattr(profile, field, value.upper() if field == "bank_ifsc" else value)
        payout_changed = False
        if payload.bank_account_number:
            profile.bank_account_number_enc = encrypt(payload.bank_account_number)
            payout_changed = True
        if payload.upi_id:
            profile.upi_id_enc = encrypt(payload.upi_id)
            payout_changed = True
        await _set_location(profile, payload, ("farm_address", "village", "pincode"))
        profile.updated_at = now
        if payload.district and not user.district:
            user.state, user.district = payload.state, payload.district
        audit(db, "profile.farmer_updated", "farmer_profile", user.id, actor_id=user.id,
              after={"payout_details_changed": payout_changed})
        await db.commit()
        return await self.get_my_profile(user, db)

    async def upsert_vendor_profile(self, user: Users, payload, db: AsyncSession) -> dict:
        if await get_role_name(user, db) != VENDOR:
            raise HTTPException(status_code=403, detail="Only vendors have a vendor profile.")
        profile = (await db.execute(select(VendorProfiles).where(VendorProfiles.user_id == user.id))).scalar_one_or_none()
        now = utcnow()
        if not profile:
            profile = VendorProfiles(user_id=user.id, created_at=now)
            db.add(profile)
        for field in VENDOR_FIELDS:
            value = getattr(payload, field)
            if value is not None:
                setattr(profile, field, value.upper() if field == "gstin" else value)
        await _set_location(profile, payload, ("business_address", "pincode"))
        profile.updated_at = now
        if payload.district and not user.district:
            user.state, user.district = payload.state, payload.district
        audit(db, "profile.vendor_updated", "vendor_profile", user.id, actor_id=user.id)
        await db.commit()
        return await self.get_my_profile(user, db)

    # ---- verification ------------------------------------------------------

    async def submit_verification(self, user: Users, payload, db: AsyncSession) -> dict:
        role = await get_role_name(user, db)
        if payload.verification_type == "farm" and role != FARMER:
            raise HTTPException(status_code=422, detail="Farm verification is for farmers.")
        if payload.verification_type == "business" and role != VENDOR:
            raise HTTPException(status_code=422, detail="Business verification is for vendors.")
        if user.verification_status == SUSPENDED:
            raise HTTPException(status_code=403, detail="Suspended accounts can't submit verification.")
        pending = (await db.execute(select(VerificationRequests.id).where(
            VerificationRequests.user_id == user.id,
            VerificationRequests.verification_type == payload.verification_type,
            VerificationRequests.status == PENDING_VERIFICATION,
        ))).first()
        if pending:
            raise HTTPException(status_code=409, detail="A request of this type is already under review.")
        file_ids = await FilesService.require_owned(db, payload.file_ids, user.id, {"verification_document"})
        request = VerificationRequests(
            user_id=user.id,
            verification_type=payload.verification_type,
            document_type=payload.document_type,
            document_number_masked=mask(payload.document_number) if payload.document_number else None,
            file_ids=file_ids,
            status=PENDING_VERIFICATION,
            submitted_at=utcnow(),
        )
        db.add(request)
        if user.verification_status != VERIFIED:
            user.verification_status = PENDING_VERIFICATION
        audit(db, "verification.submitted", "verification_request", None, actor_id=user.id,
              after={"type": payload.verification_type, "document_type": payload.document_type})
        await db.commit()
        return {"success": "Verification submitted for review.", "request_id": request.id,
                "verification_status": user.verification_status}

    async def my_verifications(self, user: Users, db: AsyncSession) -> dict:
        rows = (await db.execute(
            select(VerificationRequests).where(VerificationRequests.user_id == user.id)
            .order_by(VerificationRequests.submitted_at.desc())
        )).scalars().all()
        return {"verification_status": user.verification_status, "requests": [model_to_dict(r) for r in rows]}

    # ---- public profile ------------------------------------------------------

    async def public_profile(self, user_id: int, db: AsyncSession) -> dict:
        user = (await db.execute(select(Users).where(Users.id == user_id, Users.deleted_at.is_(None)))).scalar_one_or_none()
        if not user:
            raise HTTPException(status_code=404, detail="User not found.")
        role = await get_role_name(user, db)
        if role not in (FARMER, VENDOR):
            raise HTTPException(status_code=404, detail="User not found.")
        profile_public = {}
        if role == FARMER:
            p = (await db.execute(select(FarmerProfiles).where(FarmerProfiles.user_id == user_id))).scalar_one_or_none()
            if p:
                profile_public = {"farm_name": p.farm_name, "village": p.village, "farming_type": p.farming_type,
                                  "produce_categories": p.produce_categories, "harvest_schedule": p.harvest_schedule}
            profile_public["active_listings"] = (await db.execute(select(func.count(FarmerInventory.id)).where(
                FarmerInventory.created_by == user_id, FarmerInventory.status == ACTIVE
            ))).scalar() or 0
        else:
            p = (await db.execute(select(VendorProfiles).where(VendorProfiles.user_id == user_id))).scalar_one_or_none()
            if p:
                profile_public = {"business_name": p.business_name, "business_type": p.business_type,
                                  "purchase_categories": p.purchase_categories}
        return {
            "id": user.id,
            "name": f"{user.first_name} {user.last_name}".strip(),
            "role": role,
            "state": user.state,
            "district": user.district,
            "member_since": user.created_time,
            **profile_public,
            "trust": await trust_indicators(db, user_id),
        }
