import razorpay
from fastapi import HTTPException, status
from sqlalchemy.orm import aliased
from sqlalchemy.orm import Session
from datetime import datetime
from decimal import Decimal
from src.data_models.orders_model import Orders
from src.data_models.transactions_model import Transactions
from src.data_models.users_model import Users
from src.data_models.miscellaneous_model import Miscellaneous_Data
from src.data_models.farmer_inventory_model import FarmerInventory
from src.data_models.crops_model import Crops
from sqlalchemy import func


class PaymentsHistory:
    def farmer_payments_history(self, id: int, db: Session, page: int = 1, page_size: int = 10):
        try:
            total_records = (
                db.query(func.count(Transactions.id))
                .join(Orders, Transactions.order_id == Orders.id)
                .filter(Orders.farmer == id)
                .scalar()
            )

            if total_records == 0:
                raise HTTPException(status_code=404, detail="No transactions found for this vendor.")

            total_pages = (total_records + page_size - 1) // page_size

            txn_status = aliased(Miscellaneous_Data)
            vendor = aliased(Users)
            crop = aliased(Crops)

            transactions = (
                db.query(
                    Transactions.id.label("transaction_id"),
                    Transactions.order_id,
                    Transactions.amount_paid,
                    Transactions.currency,
                    Transactions.status.label("status_id"),
                    txn_status.value.label("status_value"),
                    Transactions.created_at,
                    Transactions.razorpay_order_id,
                    Transactions.razorpay_payment_id,
                    vendor.first_name.label("vendor_first_name"),
                    vendor.last_name.label("vendor_last_name"),
                    crop.crop_name.label("crop_name")
                )
                .join(Orders, Transactions.order_id == Orders.id)
                .join(vendor, Orders.vendor == vendor.id)
                .join(FarmerInventory, Orders.farmer_inventory == FarmerInventory.id)
                .join(crop, FarmerInventory.crop == crop.id)
                .outerjoin(txn_status, Transactions.status == txn_status.id)
                .filter(Orders.farmer == id)
                .limit(page_size)
                .offset((page - 1) * page_size)
                .all()
            )

            result = [
                {
                    "transaction_id": txn.transaction_id,
                    "order_id": txn.order_id,
                    "amount_paid": txn.amount_paid,
                    "currency": txn.currency,
                    "status_id": txn.status_id,
                    "status_value": txn.status_value,
                    "created_at": txn.created_at,
                    "razorpay_order_id": txn.razorpay_order_id,
                    "razorpay_payment_id": txn.razorpay_payment_id,
                    "vendor": f"{txn.vendor_first_name} {txn.vendor_last_name}" if txn.vendor_first_name else None,
                    "crop_name": txn.crop_name
                }
                for txn in transactions
            ]

            return {
                "page": page,
                "page_size": page_size,
                "total_records": total_records,
                "total_pages": total_pages,
                "data": result
            }

        except Exception as e:
            db.rollback()
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"An unexpected error occurred: {str(e)}"
            )

    def vendor_payments_history(self, id: int, db: Session, page: int = 1, page_size: int = 10):
        try:
            total_records = (
                db.query(func.count(Transactions.id))
                .join(Orders, Transactions.order_id == Orders.id)
                .filter(Orders.vendor == id)
                .scalar()
            )

            if total_records == 0:
                raise HTTPException(status_code=404, detail="No transactions found for this vendor.")

            total_pages = (total_records + page_size - 1) // page_size

            txn_status = aliased(Miscellaneous_Data)
            farmer = aliased(Users)
            crop = aliased(Crops)

            transactions = (
                db.query(
                    Transactions.id.label("transaction_id"),
                    Transactions.order_id,
                    Transactions.amount_paid,
                    Transactions.currency,
                    Transactions.status.label("status_id"),
                    txn_status.value.label("status_value"),
                    Transactions.created_at,
                    Transactions.razorpay_order_id,
                    Transactions.razorpay_payment_id,
                    farmer.first_name.label("farmer_first_name"),
                    farmer.last_name.label("farmer_last_name"),
                    crop.crop_name.label("crop_name")
                )
                .join(Orders, Transactions.order_id == Orders.id)
                .join(farmer, Orders.farmer == farmer.id)
                .join(FarmerInventory, Orders.farmer_inventory == FarmerInventory.id)
                .join(crop, FarmerInventory.crop == crop.id)
                .outerjoin(txn_status, Transactions.status == txn_status.id)
                .filter(Orders.vendor == id)
                .limit(page_size)
                .offset((page - 1) * page_size)
                .all()
            )

            result = [
                {
                    "transaction_id": txn.transaction_id,
                    "order_id": txn.order_id,
                    "amount_paid": txn.amount_paid,
                    "currency": txn.currency,
                    "status_id": txn.status_id,
                    "status_value": txn.status_value,
                    "created_at": txn.created_at,
                    "razorpay_order_id": txn.razorpay_order_id,
                    "razorpay_payment_id": txn.razorpay_payment_id,
                    "farmer": f"{txn.farmer_first_name} {txn.farmer_last_name}" if txn.farmer_first_name else None,
                    "crop_name": txn.crop_name
                }
                for txn in transactions
            ]

            return {
                "page": page,
                "page_size": page_size,
                "total_records": total_records,
                "total_pages": total_pages,
                "data": result
            }

        except Exception as e:
            db.rollback()
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"An unexpected error occurred: {str(e)}"
            )
