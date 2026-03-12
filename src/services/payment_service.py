import razorpay
from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from datetime import datetime

from src.helpers.settings_config import RazorPaySettings
from src.data_models.orders_model import Orders
from src.data_models.transactions_model import Transactions
from src.data_models.miscellaneous_model import Miscellaneous_Data


class PaymentsService:
    def __init__(self):
        self.razorpay_client = razorpay.Client(
            auth=(
                RazorPaySettings().RAZORPAY_KEY_ID,
                RazorPaySettings().RAZORPAY_KEY_SECRET,
            )
        )

    async def create_payment_order(self, payload, db: AsyncSession):
        """Initiates a Razorpay payment order."""
        try:
            stmt = select(Orders).where(Orders.id == payload.order_id)
            result = await db.execute(stmt)
            order = result.scalar_one_or_none()
            if not order:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Order not found",
                )
            razorpay_order = self.razorpay_client.order.create(
                {
                    "amount": payload.amount_paid * 100,
                    "currency": payload.currency,
                    "receipt": f"order_{payload.order_id}",
                    "payment_capture": 1,
                }
            )

            stmt_status = select(Miscellaneous_Data).where(
                Miscellaneous_Data.category == "payment_status",
                Miscellaneous_Data.value == "pending",
            )
            res_status = await db.execute(stmt_status)
            pending_status = res_status.scalar_one_or_none()

            new_transaction = Transactions(
                order_id=payload.order_id,
                razorpay_order_id=razorpay_order["id"],
                amount_paid=payload.amount_paid,
                currency=payload.currency,
                status=pending_status.id,
                created_at=datetime.now(),
            )
            db.add(new_transaction)
            await db.commit()

            return {
                "success": True,
                "message": "Payment order created successfully",
                "razorpay_order_id": razorpay_order["id"],
                "amount": payload.amount_paid,
                "currency": payload.currency,
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

    async def verify_payment(self, payload, db: AsyncSession):
        """Verifies Razorpay payment and updates order status."""
        try:
            params_dict = {
                "razorpay_order_id": payload.razorpay_order_id,
                "razorpay_payment_id": payload.razorpay_payment_id,
                "razorpay_signature": payload.razorpay_signature,
            }
            try:
                self.razorpay_client.utility.verify_payment_signature(params_dict)
            except razorpay.errors.SignatureVerificationError:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Invalid payment signature",
                )

            stmt = select(Transactions).where(
                Transactions.razorpay_order_id == payload.razorpay_order_id
            )
            result = await db.execute(stmt)
            transaction = result.scalar_one_or_none()
            if not transaction:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Transaction not found",
                )

            stmt_status = select(Miscellaneous_Data).where(
                Miscellaneous_Data.category == "payment_status",
                Miscellaneous_Data.value == "paid",
            )
            res_status = await db.execute(stmt_status)
            paid_status = res_status.scalar_one_or_none()

            transaction.razorpay_payment_id = payload.razorpay_payment_id
            transaction.razorpay_signature = payload.razorpay_signature
            transaction.status = paid_status.id
            await db.commit()
            return {"success": True, "message": "Payment verified successfully"}
        except HTTPException:
            await db.rollback()
            raise
        except Exception as e:
            await db.rollback()
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"An error occurred: {str(e)}",
            )
