from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import joinedload
from sqlalchemy.ext.asyncio import AsyncSession
from decimal import Decimal
from datetime import datetime

from src.data_models.market_offers_model import MarketOffers
from src.data_models.farmer_inventory_model import FarmerInventory
from src.data_models.orders_model import Orders
from src.data_models.users_model import Users
from src.data_models.crops_model import Crops
from src.data_models.miscellaneous_model import Miscellaneous_Data


class MarketOffersService:
    """Service for farmer-vendor price bargaining and offers."""

    async def create_offer(self, payload, vendor_id: int, db: AsyncSession):
        """Vendor creates a bargain offer on a farmer's listing."""
        try:
            stmt = select(FarmerInventory).where(FarmerInventory.id == payload.stock_id)
            result = await db.execute(stmt)
            inventory = result.scalar_one_or_none()
            if not inventory:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Inventory listing not found.",
                )
            if payload.quantity_kg > inventory.weight_kg:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail=f"Requested quantity ({payload.quantity_kg} kg) exceeds available stock ({inventory.weight_kg} kg).",
                )
            if inventory.created_by == vendor_id:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="You cannot make offers on your own listings.",
                )

            offer = MarketOffers(
                farmer_inventory=payload.stock_id,
                vendor=vendor_id,
                farmer=inventory.created_by,
                vendor_offer_price=payload.vendor_offer_price,
                quantity_kg=payload.quantity_kg,
                message=payload.message,
                status="pending",
                created_at=datetime.utcnow(),
                updated_at=datetime.utcnow(),
            )
            db.add(offer)
            await db.commit()
            return {"success": "Offer submitted. Farmer will review and respond."}
        except HTTPException:
            await db.rollback()
            raise
        except Exception as e:
            await db.rollback()
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"An error occurred: {str(e)}",
            )

    async def get_farmer_offers(self, farmer_id: int, db: AsyncSession) -> list:
        """Get all offers received by a farmer on their listings."""
        try:
            stmt = (
                select(MarketOffers)
                .where(MarketOffers.farmer == farmer_id)
                .order_by(MarketOffers.created_at.desc())
                .options(
                    joinedload(MarketOffers.farmer_inventory_rel).joinedload(FarmerInventory.crop_rel),
                    joinedload(MarketOffers.vendor_user),
                    joinedload(MarketOffers.farmer_user),
                )
            )
            result = await db.execute(stmt)
            offers = result.scalars().unique().all()

            for offer in offers:
                inv = offer.farmer_inventory_rel
                offer.crop_name = inv.crop_rel.crop_name if inv and inv.crop_rel else None
                offer.farmer_asking_price = inv.proposed_cost if inv else None
                vendor = offer.vendor_user
                farmer = offer.farmer_user
                offer.vendor_name = f"{vendor.first_name} {vendor.last_name}" if vendor else None
                offer.farmer_name = f"{farmer.first_name} {farmer.last_name}" if farmer else None
            return offers
        except Exception as e:
            await db.rollback()
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"An error occurred: {str(e)}",
            )

    async def get_vendor_offers(self, vendor_id: int, db: AsyncSession) -> list:
        """Get all offers made by a vendor."""
        try:
            stmt = (
                select(MarketOffers)
                .where(MarketOffers.vendor == vendor_id)
                .order_by(MarketOffers.created_at.desc())
                .options(
                    joinedload(MarketOffers.farmer_inventory_rel).joinedload(FarmerInventory.crop_rel),
                    joinedload(MarketOffers.vendor_user),
                    joinedload(MarketOffers.farmer_user),
                )
            )
            result = await db.execute(stmt)
            offers = result.scalars().unique().all()

            for offer in offers:
                inv = offer.farmer_inventory_rel
                offer.crop_name = inv.crop_rel.crop_name if inv and inv.crop_rel else None
                offer.farmer_asking_price = inv.proposed_cost if inv else None
                vendor = offer.vendor_user
                farmer = offer.farmer_user
                offer.vendor_name = f"{vendor.first_name} {vendor.last_name}" if vendor else None
                offer.farmer_name = f"{farmer.first_name} {farmer.last_name}" if farmer else None
            return offers
        except Exception as e:
            await db.rollback()
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"An error occurred: {str(e)}",
            )

    async def farmer_respond(self, offer_id: int, farmer_id: int, payload, db: AsyncSession):
        """Farmer accepts, rejects, or counters an offer (when status=pending)."""
        try:
            stmt = select(MarketOffers).where(
                MarketOffers.id == offer_id,
                MarketOffers.farmer == farmer_id,
            )
            result = await db.execute(stmt)
            offer = result.scalar_one_or_none()
            if not offer:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Offer not found or you are not the farmer for this offer.",
                )
            if offer.status != "pending":
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Offer is {offer.status}. Farmer can only respond when status is 'pending'.",
                )

            action = payload.action.lower()
            if action not in ("accept", "reject", "counter"):
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail="action must be 'accept', 'reject', or 'counter'.",
                )

            if action == "reject":
                offer.status = "rejected"
                offer.updated_at = datetime.utcnow()
                await db.commit()
                return {"success": "Offer rejected."}

            if action == "counter":
                if payload.counter_price is None or payload.counter_price <= 0:
                    raise HTTPException(
                        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                        detail="counter_price is required and must be positive when action is 'counter'.",
                    )
                offer.farmer_counter_price = payload.counter_price
                offer.status = "countered"
                offer.updated_at = datetime.utcnow()
                await db.commit()
                return {"success": "Counter offer sent. Waiting for vendor response."}

            if action == "accept":
                agreed_price = offer.vendor_offer_price

                stmt_inv = select(FarmerInventory).where(
                    FarmerInventory.id == offer.farmer_inventory
                )
                res_inv = await db.execute(stmt_inv)
                inv = res_inv.scalar_one_or_none()
                if not inv or inv.weight_kg < offer.quantity_kg:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail="Insufficient stock. Offer cannot be accepted.",
                    )

                stmt_status = select(Miscellaneous_Data).where(
                    Miscellaneous_Data.category == "order_status",
                    Miscellaneous_Data.value == "pending",
                )
                res_status = await db.execute(stmt_status)
                pending_status = res_status.scalar_one_or_none()
                if not pending_status:
                    raise HTTPException(
                        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                        detail="Order status 'pending' not found in database.",
                    )

                total_price = int(Decimal(str(offer.quantity_kg)) * Decimal(str(agreed_price)))
                new_order = Orders(
                    farmer_inventory=offer.farmer_inventory,
                    vendor=offer.vendor,
                    farmer=offer.farmer,
                    quantity_kg=offer.quantity_kg,
                    total_price=total_price,
                    status=pending_status.id,
                    created_at=datetime.utcnow(),
                )
                db.add(new_order)
                await db.flush()

                inv.weight_kg -= offer.quantity_kg
                offer.status = "accepted"
                offer.order_id = new_order.id
                offer.updated_at = datetime.utcnow()
                await db.commit()
                return {
                    "success": "Offer accepted. Order created.",
                    "order_id": new_order.id,
                    "agreed_price_per_kg": agreed_price,
                    "quantity_kg": offer.quantity_kg,
                    "total_price": total_price,
                }
        except HTTPException:
            await db.rollback()
            raise
        except Exception as e:
            await db.rollback()
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"An error occurred: {str(e)}",
            )

    async def vendor_accept(self, offer_id: int, vendor_id: int, db: AsyncSession):
        """Vendor accepts farmer's counter offer (when status=countered)."""
        try:
            stmt = select(MarketOffers).where(
                MarketOffers.id == offer_id,
                MarketOffers.vendor == vendor_id,
            )
            result = await db.execute(stmt)
            offer = result.scalar_one_or_none()
            if not offer:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Offer not found or you are not the vendor for this offer.",
                )
            if offer.status != "countered":
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Vendor can only accept when farmer has countered.",
                )
            if not offer.farmer_counter_price:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="No farmer counter price found.",
                )

            agreed_price = offer.farmer_counter_price

            stmt_inv = select(FarmerInventory).where(
                FarmerInventory.id == offer.farmer_inventory
            )
            res_inv = await db.execute(stmt_inv)
            inv = res_inv.scalar_one_or_none()
            if not inv or inv.weight_kg < offer.quantity_kg:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Insufficient stock.",
                )

            stmt_status = select(Miscellaneous_Data).where(
                Miscellaneous_Data.category == "order_status",
                Miscellaneous_Data.value == "pending",
            )
            res_status = await db.execute(stmt_status)
            pending_status = res_status.scalar_one_or_none()
            if not pending_status:
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail="Order status 'pending' not found in database.",
                )

            total_price = int(Decimal(str(offer.quantity_kg)) * Decimal(str(agreed_price)))
            new_order = Orders(
                farmer_inventory=offer.farmer_inventory,
                vendor=offer.vendor,
                farmer=offer.farmer,
                quantity_kg=offer.quantity_kg,
                total_price=total_price,
                status=pending_status.id,
                created_at=datetime.utcnow(),
            )
            db.add(new_order)
            await db.flush()

            inv.weight_kg -= offer.quantity_kg
            offer.status = "accepted"
            offer.order_id = new_order.id
            offer.updated_at = datetime.utcnow()
            await db.commit()
            return {
                "success": "Counter offer accepted. Order created.",
                "order_id": new_order.id,
                "agreed_price_per_kg": agreed_price,
                "quantity_kg": offer.quantity_kg,
                "total_price": total_price,
            }
        except HTTPException:
            await db.rollback()
            raise
        except Exception as e:
            await db.rollback()
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"An error occurred: {str(e)}",
            )

    async def vendor_counter(self, offer_id: int, vendor_id: int, payload, db: AsyncSession):
        """Vendor sends a new offer after farmer countered."""
        try:
            stmt = select(MarketOffers).where(
                MarketOffers.id == offer_id,
                MarketOffers.vendor == vendor_id,
            )
            result = await db.execute(stmt)
            offer = result.scalar_one_or_none()
            if not offer:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Offer not found or you are not the vendor for this offer.",
                )
            if offer.status != "countered":
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="You can only counter when farmer has sent a counter offer.",
                )

            stmt_inv = select(FarmerInventory).where(
                FarmerInventory.id == offer.farmer_inventory
            )
            res_inv = await db.execute(stmt_inv)
            inv = res_inv.scalar_one_or_none()
            if not inv or inv.weight_kg < offer.quantity_kg:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Insufficient stock.",
                )

            offer.vendor_offer_price = payload.vendor_offer_price
            offer.farmer_counter_price = None
            offer.status = "pending"
            offer.updated_at = datetime.utcnow()
            await db.commit()
            return {"success": "New offer sent. Farmer will review."}
        except HTTPException:
            await db.rollback()
            raise
        except Exception as e:
            await db.rollback()
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"An error occurred: {str(e)}",
            )
