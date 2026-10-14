"""
Negotiation tools. Mutations delegate to NegotiationsService, so the same row locks, expiry
checks, recipient rules, stock validation and audit apply as through the REST API. Acceptance
creates the order atomically (stock is re-validated and reserved under a row lock).
"""
from datetime import date
from typing import Literal

from fastapi import HTTPException
from pydantic import BaseModel, Field, model_validator
from sqlalchemy.ext.asyncio import AsyncSession

from src.agents.context import RunContext
from src.agents.tools.base import tool
from src.data_models.users_model import Users
from src.schemas.negotiations_schema import AcceptOfferSchema, OfferTermsSchema, StartNegotiationSchema
from src.services.negotiations_service import NegotiationsService

DeliveryPreference = Literal["pickup", "farmer_delivery", "vendor_transport", "third_party"]
PaymentTerms = Literal["full_advance", "partial_advance", "pay_before_dispatch", "pay_on_delivery", "cash_on_delivery"]


class NegotiationRef(BaseModel):
    negotiation_id: int = Field(..., gt=0)


@tool("get_offer_history", NegotiationRef, "A negotiation's current offer and full version history (participants only).")
async def get_offer_history(db: AsyncSession, actor: Users, args: NegotiationRef, ctx: RunContext) -> dict:
    return await NegotiationsService().get(actor, args.negotiation_id, db)


class SubmitOfferInput(BaseModel):
    listing_id: int | None = Field(None, gt=0, description="Start a new negotiation on this listing.")
    negotiation_id: int | None = Field(None, gt=0, description="Counter / re-offer in this negotiation.")
    quantity: float = Field(..., gt=0)
    unit_price: float = Field(..., gt=0)
    delivery_preference: DeliveryPreference | None = None
    preferred_date: date | None = None
    message: str | None = Field(None, max_length=1000)
    expires_in_hours: int | None = Field(None, ge=1, le=168)

    @model_validator(mode="after")
    def one_target(self):
        if bool(self.listing_id) == bool(self.negotiation_id):
            raise ValueError("give exactly one of listing_id or negotiation_id")
        return self


@tool("submit_offer", SubmitOfferInput, "Send an offer (new negotiation) or a counteroffer. Needs approval.")
async def submit_offer(db: AsyncSession, actor: Users, args: SubmitOfferInput, ctx: RunContext) -> dict:
    terms = dict(quantity=args.quantity, unit_price=args.unit_price, delivery_preference=args.delivery_preference,
                 preferred_date=args.preferred_date, message=args.message, expires_in_hours=args.expires_in_hours)
    service = NegotiationsService()
    if args.listing_id:
        result = await service.start(actor, StartNegotiationSchema(listing_id=args.listing_id, draft=False, **terms), db)
    else:
        result = await service.submit_offer(actor, args.negotiation_id, OfferTermsSchema(**terms), db)
        result["negotiation_id"] = args.negotiation_id
    return result


class RespondInput(BaseModel):
    negotiation_id: int = Field(..., gt=0)
    offer_id: int = Field(..., gt=0)
    action: Literal["reject"]
    reason: str | None = Field(None, max_length=255)


@tool("respond_to_offer", RespondInput, "Reject the current offer. Counter with submit_offer; accept with create_order.")
async def respond_to_offer(db: AsyncSession, actor: Users, args: RespondInput, ctx: RunContext) -> dict:
    data = await NegotiationsService().get(actor, args.negotiation_id, db)
    current = data.get("current_offer") or {}
    if current.get("id") != args.offer_id:
        raise HTTPException(status_code=409, detail="That offer is no longer the current offer.")
    return await NegotiationsService().reject(actor, args.negotiation_id, args.reason, db)


class CreateOrderInput(BaseModel):
    negotiation_id: int = Field(..., gt=0)
    offer_id: int = Field(..., gt=0, description="The exact offer being accepted (stale offers are refused).")
    payment_terms: PaymentTerms | None = None
    delivery_instructions: str | None = Field(None, max_length=1000)


@tool("create_order", CreateOrderInput,
      "Accept the counterparty's current offer, which creates the order and reserves stock. Needs approval.")
async def create_order(db: AsyncSession, actor: Users, args: CreateOrderInput, ctx: RunContext) -> dict:
    return await NegotiationsService().accept(actor, args.negotiation_id, AcceptOfferSchema(
        offer_id=args.offer_id, payment_terms=args.payment_terms, delivery_instructions=args.delivery_instructions,
    ), db)
