import razorpay
from fastapi import HTTPException, status
from sqlalchemy.orm import Session
from datetime import datetime
from decimal import Decimal
from src.helpers.settings_config import RazorPaySettings
from src.data_models.orders_model import Orders
from src.data_models.transactions_model import Transactions
from src.data_models.miscellaneous_model import Miscellaneous_Data


class PaymentsService:
    def __init__(self):
        self.razorpay_client = razorpay.Client(
            auth=(
                RazorPaySettings().RAZORPAY_KEY_ID, 
                  RazorPaySettings().RAZORPAY_KEY_SECRET
                  )
        )
        
    def create_payment_order(self, payload, db: Session):
        """Initiates a Razorpay payment order."""
        try:
            order = db.query(Orders).filter(Orders.id == payload.order_id).first()
            if not order:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Order not found"
                )
            razorpay_order = self.razorpay_client.order.create({
                "amount": payload.amount_paid * 100,
                "currency": payload.currency,
                "receipt": f"order_{payload.order_id}",
                "payment_capture": 1
            })
            new_transaction = Transactions(
                order_id=payload.order_id,
                razorpay_order_id=razorpay_order["id"],
                amount_paid=payload.amount_paid,
                currency=payload.currency,
                status=db.query(Miscellaneous_Data).filter(
                    Miscellaneous_Data.category == "payment_status",
                    Miscellaneous_Data.value == "pending"
                ).first().id,
                created_at=datetime.now()
            )
            db.add(new_transaction)
            db.commit()

            return {
                "success": True,
                "message": "Payment order created successfully",
                "razorpay_order_id": razorpay_order["id"],
                "amount": payload.amount_paid,
                "currency": payload.currency
            }

        except Exception as e:
            db.rollback()
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"An unexpected error occurred: {str(e)}"
            )

    def verify_payment(self, payload, db: Session):
        """Verifies Razorpay payment and updates order status."""
        try:
            params_dict = {
                "razorpay_order_id": payload.razorpay_order_id,
                "razorpay_payment_id": payload.razorpay_payment_id,
                "razorpay_signature": payload.razorpay_signature
            }
            try:
                self.razorpay_client.utility.verify_payment_signature(params_dict)
            except razorpay.errors.SignatureVerificationError:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Invalid payment signature"
                )
            transaction = db.query(Transactions).filter(
                Transactions.razorpay_order_id == payload.razorpay_order_id
            ).first()
            if not transaction:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Transaction not found"
                )
            transaction.razorpay_payment_id = payload.razorpay_payment_id
            transaction.razorpay_signature = payload.razorpay_signature
            transaction.status = db.query(Miscellaneous_Data).filter(
                Miscellaneous_Data.category == "payment_status",
                Miscellaneous_Data.value == "completed"
            ).first().id
            db.commit()
            return {"success": True, "message": "Payment verified successfully"}
        except HTTPException as e:
            db.rollback()
            raise e
        except Exception as e:
            db.rollback()
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"An error occurred: {str(e)}"
            )
