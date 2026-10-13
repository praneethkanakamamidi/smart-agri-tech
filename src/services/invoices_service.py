"""Order receipts, payment receipts and invoices, numbered from a database sequence."""
from datetime import datetime
from html import escape

from fastapi import HTTPException
from fastapi.responses import HTMLResponse
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.audit import _jsonable
from src.data_models.orders_model import Orders, Invoices
from src.data_models.transactions_model import Transactions
from src.data_models.users_model import Users
from src.data_models.profiles_model import FarmerProfiles, VendorProfiles

PREFIX = {"order_receipt": "ORC", "payment_receipt": "PRC", "invoice": "INV"}
TITLES = {"order_receipt": "Order Receipt", "payment_receipt": "Payment Receipt", "invoice": "Invoice"}


async def _party(db: AsyncSession, user_id: int, kind: str) -> dict:
    user = (await db.execute(select(Users).where(Users.id == user_id))).scalar_one()
    data = {"id": user.id, "name": f"{user.first_name} {user.last_name}".strip(), "phone": user.phone, "email": user.email}
    if kind == "farmer":
        p = (await db.execute(select(FarmerProfiles).where(FarmerProfiles.user_id == user_id))).scalar_one_or_none()
        if p:
            data.update({"business_name": p.farm_name, "address": p.farm_address})
    else:
        p = (await db.execute(select(VendorProfiles).where(VendorProfiles.user_id == user_id))).scalar_one_or_none()
        if p:
            data.update({"business_name": p.business_name, "address": p.billing_address or p.business_address,
                         "gstin": p.gstin})
    return data


async def issue(db: AsyncSession, order: Orders, invoice_type: str, transaction: Transactions | None = None) -> Invoices:
    """Freeze a document for `order`. The caller commits."""
    existing = None
    if invoice_type != "payment_receipt":
        existing = (await db.execute(select(Invoices).where(
            Invoices.order_id == order.id, Invoices.invoice_type == invoice_type
        ))).scalar_one_or_none()
    if existing:
        return existing
    seq = (await db.execute(text("SELECT nextval('invoice_number_seq')"))).scalar()
    now = datetime.utcnow()
    number = f"{PREFIX[invoice_type]}-{now:%Y}-{seq:07d}"
    data = {
        "title": TITLES[invoice_type],
        "order_number": order.order_number,
        "issued_at": now,
        "seller": await _party(db, order.farmer, "farmer"),
        "buyer": await _party(db, order.vendor, "vendor"),
        "terms": order.terms_snapshot,
        "lines": [{
            "description": (order.terms_snapshot or {}).get("produce", {}).get("display_name"),
            "quantity": order.quantity_kg, "unit": order.unit, "unit_price": order.unit_price,
            "amount": order.subtotal,
        }],
        "charges": {
            "packaging": order.packaging_charge, "transport": order.transport_charge,
            "platform_fee": order.platform_fee, "tax": order.tax_amount, "discount": order.discount_amount,
        },
        "total": order.total_price,
    }
    total = order.total_price
    if transaction is not None:
        data["payment"] = {
            "transaction_id": transaction.id, "amount": transaction.amount_paid, "method": transaction.payment_method,
            "reference": transaction.razorpay_payment_id or transaction.reference, "paid_at": transaction.updated_at,
        }
        total = transaction.amount_paid
    invoice = Invoices(
        order_id=order.id, transaction_id=transaction.id if transaction else None, invoice_number=number,
        invoice_type=invoice_type, total_amount=total, data=_jsonable(data), issued_at=now,
    )
    db.add(invoice)
    return invoice


class InvoicesService:
    async def list_for_order(self, order_id: int, user_id: int, is_admin: bool, db: AsyncSession) -> list[dict]:
        order = (await db.execute(select(Orders).where(Orders.id == order_id))).scalar_one_or_none()
        if not order or (not is_admin and user_id not in (order.farmer, order.vendor)):
            raise HTTPException(status_code=404, detail="Order not found.")
        rows = (await db.execute(select(Invoices).where(Invoices.order_id == order_id).order_by(Invoices.id))).scalars().all()
        return [
            {"id": r.id, "invoice_number": r.invoice_number, "invoice_type": r.invoice_type,
             "total_amount": r.total_amount, "issued_at": r.issued_at,
             "download_url": f"/api/invoices/{r.id}/download"}
            for r in rows
        ]

    async def download(self, invoice_id: int, user_id: int, is_admin: bool, db: AsyncSession) -> HTMLResponse:
        row = (await db.execute(
            select(Invoices, Orders).join(Orders, Invoices.order_id == Orders.id).where(Invoices.id == invoice_id)
        )).first()
        if not row or (not is_admin and user_id not in (row[1].farmer, row[1].vendor)):
            raise HTTPException(status_code=404, detail="Invoice not found.")
        invoice = row[0]
        d = invoice.data
        e = lambda v: escape("" if v is None else str(v))  # noqa: E731
        lines = "".join(
            f"<tr><td>{e(l['description'])}</td><td>{e(l['quantity'])} {e(l['unit'])}</td>"
            f"<td>₹{e(l['unit_price'])}</td><td>₹{e(l['amount'])}</td></tr>"
            for l in d.get("lines", [])
        )
        charges = "".join(
            f"<tr><td colspan='3'>{e(k.replace('_', ' ').title())}</td><td>₹{e(v)}</td></tr>"
            for k, v in d.get("charges", {}).items() if v not in (None, "0", "0.00", 0)
        )
        payment = ""
        if d.get("payment"):
            p = d["payment"]
            payment = (f"<p><b>Payment:</b> ₹{e(p['amount'])} via {e(p['method'])} "
                       f"(ref {e(p['reference'])}) on {e(p['paid_at'])}</p>")

        def party(label, p):
            return (f"<div><h3>{label}</h3><p>{e(p.get('business_name') or p.get('name'))}<br>{e(p.get('name'))}<br>"
                    f"{e(p.get('address'))}<br>{e(p.get('phone'))} {e(p.get('email'))}"
                    f"{'<br>GSTIN ' + e(p['gstin']) if p.get('gstin') else ''}</p></div>")

        html = f"""<!doctype html><html><head><meta charset="utf-8"><title>{e(invoice.invoice_number)}</title>
<style>body{{font-family:sans-serif;max-width:800px;margin:24px auto;color:#222}}table{{width:100%;border-collapse:collapse}}
td,th{{border:1px solid #ccc;padding:6px;text-align:left}}.parties{{display:flex;gap:40px}}</style></head><body>
<h1>{e(d.get('title'))}</h1><p><b>No:</b> {e(invoice.invoice_number)} &nbsp; <b>Order:</b> {e(d.get('order_number'))}
&nbsp; <b>Date:</b> {e(d.get('issued_at'))}</p>
<div class="parties">{party('Seller (farmer)', d['seller'])}{party('Buyer (vendor)', d['buyer'])}</div>
<table><tr><th>Produce</th><th>Quantity</th><th>Agreed unit price</th><th>Amount</th></tr>{lines}{charges}
<tr><th colspan="3">Total payable</th><th>₹{e(d.get('total'))}</th></tr></table>{payment}
<p style="font-size:12px;color:#666">Tax treatment of agricultural produce depends on the transaction; confirm with a tax adviser.</p>
</body></html>"""
        return HTMLResponse(html, headers={"Content-Disposition": f'attachment; filename="{invoice.invoice_number}.html"'})
