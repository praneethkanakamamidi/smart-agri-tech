from fastapi import HTTPException, status
from sqlalchemy import select, desc
from sqlalchemy.orm import joinedload, selectinload
from sqlalchemy.ext.asyncio import AsyncSession
from datetime import datetime
from decimal import Decimal

from src.data_models.orders_model import Orders
from src.data_models.farmer_inventory_model import FarmerInventory
from src.data_models.transactions_model import Transactions
from src.data_models.miscellaneous_model import Miscellaneous_Data


class OrdersService:
    async def post_order(self, payload, db: AsyncSession):
        try:
            stmt_status = select(Miscellaneous_Data).where(
                Miscellaneous_Data.category == "order_status",
                Miscellaneous_Data.value == "pending",
            )
            res_status = await db.execute(stmt_status)
            pending_status = res_status.scalar_one_or_none()
            if not pending_status:
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail="Order status 'pending' not found in database",
                )

            stmt_inv = select(FarmerInventory).where(FarmerInventory.id == payload.stock_id)
            res_inv = await db.execute(stmt_inv)
            inventory_data = res_inv.scalar_one_or_none()
            if not inventory_data:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Error: Inventory with the given ID not found",
                )
            if payload.quantity > inventory_data.weight_kg:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail=f"Order quantity ({payload.quantity} kg) exceeds available stock ({inventory_data.weight_kg} kg). Please reduce the quantity.",
                )

            total_price = Decimal(payload.quantity) * Decimal(inventory_data.proposed_cost)
            new_order = Orders(
                farmer_inventory=inventory_data.id,
                vendor=payload.vendor,
                farmer=inventory_data.created_by,
                quantity_kg=payload.quantity,
                total_price=int(total_price),
                status=pending_status.id,
                created_at=datetime.utcnow(),
            )
            db.add(new_order)
            await db.flush()
            if not new_order.id:
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail="Failed to place order. Please try again.",
                )
            inventory_data.weight_kg -= payload.quantity
            await db.commit()
            return {"success": "Order has been placed successfully"}
        except HTTPException:
            await db.rollback()
            raise
        except Exception as e:
            await db.rollback()
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"An unexpected error occurred: {str(e)}",
            )

    async def get_vendor_orders(self, id: int, db: AsyncSession) -> list:
        try:
            stmt = (
                select(Orders)
                .where(Orders.vendor == id)
                .options(
                    joinedload(Orders.farmer_inventory_rel).joinedload(FarmerInventory.crop_rel),
                    joinedload(Orders.farmer_inventory_rel).joinedload(FarmerInventory.soil_rel),
                    joinedload(Orders.farmer_inventory_rel).joinedload(FarmerInventory.fertilizer_rel),
                    joinedload(Orders.vendor_user),
                    joinedload(Orders.farmer_user),
                    joinedload(Orders.status_rel),
                )
            )
            result = await db.execute(stmt)
            vendor_order_data = result.scalars().unique().all()

            for data in vendor_order_data:
                stmt_txn = (
                    select(Transactions)
                    .where(Transactions.order_id == data.id)
                    .order_by(desc(Transactions.created_at))
                    .limit(1)
                )
                res_txn = await db.execute(stmt_txn)
                payment_status_data = res_txn.scalar_one_or_none()
                misc_payment_status_data = None
                if payment_status_data:
                    stmt_misc = select(Miscellaneous_Data).where(
                        Miscellaneous_Data.id == payment_status_data.status
                    )
                    res_misc = await db.execute(stmt_misc)
                    misc_payment_status_data = res_misc.scalar_one_or_none()

                inv = data.farmer_inventory_rel
                data.crop_name = inv.crop_rel.crop_name if inv and inv.crop_rel else None
                data.soil_name = inv.soil_rel.soil_name if inv and inv.soil_rel else None
                data.fertilizer_name = inv.fertilizer_rel.fertilizer_name if inv and inv.fertilizer_rel else None
                data.farmer_name = f"{data.farmer_user.first_name} {data.farmer_user.last_name}" if data.farmer_user else None
                data.order_status = data.status_rel.value if data.status_rel else None
                data.payment_status = misc_payment_status_data.value if misc_payment_status_data else "pending"

            return vendor_order_data
        except Exception as e:
            await db.rollback()
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"An error occurred: {str(e)}",
            )

    async def get_farmer_orders(self, id: int, db: AsyncSession) -> list:
        try:
            stmt = (
                select(Orders)
                .where(Orders.farmer == id)
                .options(
                    joinedload(Orders.farmer_inventory_rel).joinedload(FarmerInventory.crop_rel),
                    joinedload(Orders.farmer_inventory_rel).joinedload(FarmerInventory.soil_rel),
                    joinedload(Orders.farmer_inventory_rel).joinedload(FarmerInventory.fertilizer_rel),
                    joinedload(Orders.vendor_user),
                    joinedload(Orders.status_rel),
                )
            )
            result = await db.execute(stmt)
            farmer_order_data = result.scalars().unique().all()

            for data in farmer_order_data:
                stmt_txn = select(Transactions).where(
                    Transactions.order_id == data.id
                ).order_by(desc(Transactions.created_at)).limit(1)
                res_txn = await db.execute(stmt_txn)
                payment_status_data = res_txn.scalar_one_or_none()
                misc_payment_status_data = None
                if payment_status_data:
                    stmt_misc = select(Miscellaneous_Data).where(
                        Miscellaneous_Data.id == payment_status_data.status
                    )
                    res_misc = await db.execute(stmt_misc)
                    misc_payment_status_data = res_misc.scalar_one_or_none()

                inv = data.farmer_inventory_rel
                data.crop_name = inv.crop_rel.crop_name if inv and inv.crop_rel else None
                data.soil_name = inv.soil_rel.soil_name if inv and inv.soil_rel else None
                data.fertilizer_name = inv.fertilizer_rel.fertilizer_name if inv and inv.fertilizer_rel else None
                data.vendor_name = f"{data.vendor_user.first_name} {data.vendor_user.last_name}" if data.vendor_user else None
                data.order_status = data.status_rel.value if data.status_rel else None
                data.payment_status = misc_payment_status_data.value if misc_payment_status_data else "pending"

            return farmer_order_data
        except Exception as e:
            await db.rollback()
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"An error occurred: {str(e)}",
            )

    async def order_status(self, payload, db: AsyncSession):
        try:
            stmt_status = select(Miscellaneous_Data).where(
                Miscellaneous_Data.category == "order_status",
                Miscellaneous_Data.value == payload.status,
            )
            res_status = await db.execute(stmt_status)
            order_status_data = res_status.scalar_one_or_none()
            if not order_status_data:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Order status '{payload.status}' not found.",
                )

            stmt_order = select(Orders).where(Orders.id == payload.order_id)
            res_order = await db.execute(stmt_order)
            order_data = res_order.scalar_one_or_none()
            if not order_data:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Order with ID {payload.order_id} not found.",
                )

            if payload.status.lower() == "rejected":
                stmt_inv = select(FarmerInventory).where(
                    FarmerInventory.id == order_data.farmer_inventory
                )
                res_inv = await db.execute(stmt_inv)
                inventory_data = res_inv.scalar_one_or_none()
                if inventory_data:
                    inventory_data.weight_kg += order_data.quantity_kg
                    await db.commit()

            order_data.status = order_status_data.id
            await db.commit()
            return {"message": f"Order status has been changed to '{payload.status}'"}
        except HTTPException:
            await db.rollback()
            raise
        except Exception as e:
            await db.rollback()
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"An error occurred: {str(e)}",
            )
