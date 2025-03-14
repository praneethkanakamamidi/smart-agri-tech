from fastapi import HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy import func
from src.data_models.orders_model import Orders
from src.data_models.farmer_inventory_model import FarmerInventory
from src.data_models.crops_model import Crops
from src.data_models.soil_model import Soil
from src.data_models.fertilizers_model import Fertilizers
from src.data_models.users_model import Users
from src.data_models.transactions_model import Transactions
from src.data_models.miscellaneous_model import Miscellaneous_Data
from datetime import datetime
from decimal import Decimal



class OrdersService:
    def post_order(self, payload, db: Session):
        try:
            pending_status = db.query(Miscellaneous_Data).filter(
                Miscellaneous_Data.category == "order_status",
                Miscellaneous_Data.value == "pending"
            ).first()
            if not pending_status:
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail="Order status 'pending' not found in database"
                )
            inventory_data = db.query(FarmerInventory).filter(
                FarmerInventory.id == payload.stock_id
            ).first()
            if not inventory_data:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Error: Inventory with the given ID not found"
                )
            if payload.quantity > inventory_data.weight_kg:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail=f"Order quantity ({payload.quantity} kg) exceeds available stock ({inventory_data.weight_kg} kg). Please reduce the quantity."
                )
            total_price = Decimal(payload.quantity) * Decimal(inventory_data.proposed_cost)
            new_order = Orders(
                farmer_inventory=inventory_data.id,
                vendor=payload.vendor,
                farmer=inventory_data.created_by,
                quantity_kg=payload.quantity,
                total_price=total_price,
                status=pending_status.id,
                created_at=datetime.utcnow()
            )
            db.add(new_order)
            db.flush()
            if not new_order.id:
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail="Failed to place order. Please try again."
                )
            inventory_data.weight_kg -= payload.quantity
            db.commit()
            return {"success": "Order has been placed successfully"}
        except HTTPException as e:
            db.rollback()
            raise e
        except Exception as e:
            db.rollback()
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"An unexpected error occurred: {str(e)}"
            )
        finally:
            db.close()
        
    def get_vendor_orders(self, id, db: Session) -> list:
        try:
            vendor_order_data = db.query(Orders).filter(Orders.vendor == id).all()
            for data in vendor_order_data:
                payment_status_data = db.query(Transactions).filter(Transactions.order_id == data.id).first()
                misc_payment_status_data = None
                if payment_status_data:
                    misc_payment_status_data = db.query(Miscellaneous_Data).filter(Miscellaneous_Data.id == payment_status_data.status).first()
                inventory_data = db.query(FarmerInventory).filter(FarmerInventory.id == data.farmer_inventory).first()

                if inventory_data:
                    crop_data = db.query(Crops).filter(Crops.id == inventory_data.crop).first()
                    soil_data = db.query(Soil).filter(Soil.id == inventory_data.soil).first()
                    fertilizer_data = db.query(Fertilizers).filter(Fertilizers.id == inventory_data.fertilizer).first()
                    order_status_data = db.query(Miscellaneous_Data).filter(Miscellaneous_Data.id == data.status).first()

                user_data = db.query(Users).filter(Users.id == data.vendor).first()
                data.crop_name = crop_data.crop_name if crop_data else None
                data.soil_name = soil_data.soil_name if soil_data else None
                data.fertilizer_name = fertilizer_data.fertilizer_name if fertilizer_data else None
                data.farmer_name = f"{user_data.first_name} {user_data.last_name}" if user_data else None
                data.order_status = order_status_data.value if order_status_data else None
                data.payment_status = misc_payment_status_data.value if misc_payment_status_data else "pending"

            return vendor_order_data

        except Exception as e:
            db.rollback()
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"An error occurred: {str(e)}"
            )
    
    def get_farmer_orders(self, id, db: Session) -> list:
        try:
            farmer_order_data = db.query(Orders).filter(
                Orders.farmer==id
            ).all()
            for data in farmer_order_data:
                misc_payment_status_data = None
                payment_status_data = db.query(Transactions).filter(Transactions.order_id == data.id).first()
                if payment_status_data:
                    misc_payment_status_data = db.query(Miscellaneous_Data).filter(Miscellaneous_Data.id == payment_status_data.status).first()

                inventory_data = db.query(FarmerInventory).filter(FarmerInventory.id==data.farmer_inventory).first()
                if inventory_data:
                    crop_data =  db.query(Crops).filter(Crops.id==inventory_data.crop).first()
                    soil_data =  db.query(Soil).filter(Soil.id==inventory_data.soil).first()
                    fertilizer_data = db.query(Fertilizers).filter(Fertilizers.id==inventory_data.fertilizer).first()
                    order_status_data = db.query(Miscellaneous_Data).filter(Miscellaneous_Data.id==data.status).first()
                user_data = db.query(Users).filter(Users.id==data.vendor).first()
                data.crop_name = crop_data.crop_name if crop_data else None
                data.soil_name = soil_data.soil_name if soil_data else None
                data.fertilizer_name = fertilizer_data.fertilizer_name if fertilizer_data else None
                data.vendor_name = user_data.first_name + " " + user_data.last_name if user_data else None
                data.order_status = order_status_data.value if order_status_data else None
                data.payment_status = misc_payment_status_data.value if misc_payment_status_data else "pending"
                
            return farmer_order_data
        except Exception as e:
            db.rollback()
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"An error occurred: {str(e)}"
            )

    def order_status(self, payload, db: Session):
        try:
            order_status_data = db.query(Miscellaneous_Data).filter(
                Miscellaneous_Data.category == "order_status",
                Miscellaneous_Data.value == payload.status
            ).first()
            if not order_status_data:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Order status '{payload.status}' not found."
                )
            order_data = db.query(Orders).filter(Orders.id == payload.order_id).first()
            if not order_data:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Order with ID {payload.order_id} not found."
                )
            if payload.status.lower() == "rejected":
                inventory_data = db.query(FarmerInventory).filter(
                    FarmerInventory.id == order_data.farmer_inventory
                ).first()
                if inventory_data:
                    inventory_data.weight_kg += order_data.quantity_kg
                    db.commit()
            order_data.status = order_status_data.id
            db.commit()
            return {"message": f"Order status has been changed to '{payload.status}'"}
        except HTTPException as e:
            db.rollback()
            raise e
        except Exception as e:
            db.rollback()
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"An error occurred: {str(e)}"
            )
