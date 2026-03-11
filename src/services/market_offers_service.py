from fastapi import HTTPException, status
from sqlalchemy.orm import Session
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

    def create_offer(self, payload, vendor_id: int, db: Session):
        """Vendor creates a bargain offer on a farmer's listing."""
        try:
            inventory = db.query(FarmerInventory).filter(
                FarmerInventory.id == payload.stock_id
            ).first()
            if not inventory:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Inventory listing not found."
                )
            if payload.quantity_kg > inventory.weight_kg:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail=f"Requested quantity ({payload.quantity_kg} kg) exceeds available stock ({inventory.weight_kg} kg)."
                )
            if inventory.created_by == vendor_id:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="You cannot make offers on your own listings."
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
            db.commit()
            return {"success": "Offer submitted. Farmer will review and respond."}
        except HTTPException:
            db.rollback()
            raise
        except Exception as e:
            db.rollback()
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"An error occurred: {str(e)}"
            )

    def get_farmer_offers(self, farmer_id: int, db: Session) -> list:
        """Get all offers received by a farmer on their listings."""
        try:
            offers = db.query(MarketOffers).filter(
                MarketOffers.farmer == farmer_id
            ).order_by(MarketOffers.created_at.desc()).all()

            for offer in offers:
                self._enrich_offer(offer, db)
            return offers
        except Exception as e:
            db.rollback()
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"An error occurred: {str(e)}"
            )

    def get_vendor_offers(self, vendor_id: int, db: Session) -> list:
        """Get all offers made by a vendor."""
        try:
            offers = db.query(MarketOffers).filter(
                MarketOffers.vendor == vendor_id
            ).order_by(MarketOffers.created_at.desc()).all()

            for offer in offers:
                self._enrich_offer(offer, db)
            return offers
        except Exception as e:
            db.rollback()
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"An error occurred: {str(e)}"
            )

    def _enrich_offer(self, offer, db: Session):
        """Add display fields to offer."""
        inv = db.query(FarmerInventory).filter(
            FarmerInventory.id == offer.farmer_inventory
        ).first()
        if inv:
            crop = db.query(Crops).filter(Crops.id == inv.crop).first()
            offer.crop_name = crop.crop_name if crop else None
            offer.farmer_asking_price = inv.proposed_cost
        vendor = db.query(Users).filter(Users.id == offer.vendor).first()
        farmer = db.query(Users).filter(Users.id == offer.farmer).first()
        offer.vendor_name = f"{vendor.first_name} {vendor.last_name}" if vendor else None
        offer.farmer_name = f"{farmer.first_name} {farmer.last_name}" if farmer else None

    def farmer_respond(self, offer_id: int, farmer_id: int, payload, db: Session):
        """Farmer accepts, rejects, or counters an offer (when status=pending)."""
        try:
            offer = db.query(MarketOffers).filter(
                MarketOffers.id == offer_id,
                MarketOffers.farmer == farmer_id,
            ).first()
            if not offer:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Offer not found or you are not the farmer for this offer."
                )
            if offer.status != "pending":
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Offer is {offer.status}. Farmer can only respond when status is 'pending'."
                )

            action = payload.action.lower()
            if action not in ("accept", "reject", "counter"):
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail="action must be 'accept', 'reject', or 'counter'."
                )

            if action == "reject":
                offer.status = "rejected"
                offer.updated_at = datetime.utcnow()
                db.commit()
                return {"success": "Offer rejected."}

            if action == "counter":
                if payload.counter_price is None or payload.counter_price <= 0:
                    raise HTTPException(
                        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                        detail="counter_price is required and must be positive when action is 'counter'."
                    )
                offer.farmer_counter_price = payload.counter_price
                offer.status = "countered"
                offer.updated_at = datetime.utcnow()
                db.commit()
                return {"success": "Counter offer sent. Waiting for vendor response."}

            if action == "accept":
                agreed_price = offer.vendor_offer_price

                inv = db.query(FarmerInventory).filter(
                    FarmerInventory.id == offer.farmer_inventory
                ).first()
                if not inv or inv.weight_kg < offer.quantity_kg:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail="Insufficient stock. Offer cannot be accepted."
                    )

                pending_status = db.query(Miscellaneous_Data).filter(
                    Miscellaneous_Data.category == "order_status",
                    Miscellaneous_Data.value == "pending"
                ).first()
                if not pending_status:
                    raise HTTPException(
                        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                        detail="Order status 'pending' not found in database."
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
                db.flush()

                inv.weight_kg -= offer.quantity_kg
                offer.status = "accepted"
                offer.order_id = new_order.id
                offer.updated_at = datetime.utcnow()
                db.commit()
                return {
                    "success": "Offer accepted. Order created.",
                    "order_id": new_order.id,
                    "agreed_price_per_kg": agreed_price,
                    "quantity_kg": offer.quantity_kg,
                    "total_price": total_price,
                }
        except HTTPException:
            db.rollback()
            raise
        except Exception as e:
            db.rollback()
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"An error occurred: {str(e)}"
            )

    def vendor_accept(self, offer_id: int, vendor_id: int, db: Session):
        """Vendor accepts farmer's counter offer (when status=countered)."""
        try:
            offer = db.query(MarketOffers).filter(
                MarketOffers.id == offer_id,
                MarketOffers.vendor == vendor_id,
            ).first()
            if not offer:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Offer not found or you are not the vendor for this offer."
                )
            if offer.status != "countered":
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Vendor can only accept when farmer has countered."
                )
            if not offer.farmer_counter_price:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="No farmer counter price found."
                )

            agreed_price = offer.farmer_counter_price

            inv = db.query(FarmerInventory).filter(
                FarmerInventory.id == offer.farmer_inventory
            ).first()
            if not inv or inv.weight_kg < offer.quantity_kg:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Insufficient stock."
                )

            pending_status = db.query(Miscellaneous_Data).filter(
                Miscellaneous_Data.category == "order_status",
                Miscellaneous_Data.value == "pending"
            ).first()
            if not pending_status:
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail="Order status 'pending' not found in database."
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
            db.flush()

            inv.weight_kg -= offer.quantity_kg
            offer.status = "accepted"
            offer.order_id = new_order.id
            offer.updated_at = datetime.utcnow()
            db.commit()
            return {
                "success": "Counter offer accepted. Order created.",
                "order_id": new_order.id,
                "agreed_price_per_kg": agreed_price,
                "quantity_kg": offer.quantity_kg,
                "total_price": total_price,
            }
        except HTTPException:
            db.rollback()
            raise
        except Exception as e:
            db.rollback()
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"An error occurred: {str(e)}"
            )

    def vendor_counter(self, offer_id: int, vendor_id: int, payload, db: Session):
        """Vendor sends a new offer after farmer countered."""
        try:
            offer = db.query(MarketOffers).filter(
                MarketOffers.id == offer_id,
                MarketOffers.vendor == vendor_id,
            ).first()
            if not offer:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Offer not found or you are not the vendor for this offer."
                )
            if offer.status != "countered":
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="You can only counter when farmer has sent a counter offer."
                )

            inv = db.query(FarmerInventory).filter(
                FarmerInventory.id == offer.farmer_inventory
            ).first()
            if not inv or inv.weight_kg < offer.quantity_kg:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Insufficient stock."
                )

            offer.vendor_offer_price = payload.vendor_offer_price
            offer.farmer_counter_price = None
            offer.status = "pending"
            offer.updated_at = datetime.utcnow()
            db.commit()
            return {"success": "New offer sent. Farmer will review."}
        except HTTPException:
            db.rollback()
            raise
        except Exception as e:
            db.rollback()
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"An error occurred: {str(e)}"
            )
