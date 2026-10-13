import hashlib
import uuid
from datetime import datetime

from fastapi import HTTPException, UploadFile, status
from fastapi.responses import Response
from sqlalchemy import select, or_, cast, String
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.platform_settings import get_setting
from src.core.storage import storage, detect_content_type
from src.data_models.platform_model import StoredFiles, SupportTicketMessages, SupportTickets
from src.data_models.messages_model import Messages
from src.data_models.disputes_model import Disputes, DisputeMessages
from src.data_models.logistics_model import Shipments
from src.data_models.orders_model import Orders
from src.data_models.listing_extras_model import ListingImages, ListingCertifications
from src.data_models.users_model import Users

IMAGES = {"image/jpeg", "image/png", "image/webp"}
IMAGES_AND_PDF = IMAGES | {"application/pdf"}
EXTENSIONS = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp", "application/pdf": "pdf"}

# purpose -> allowed content types
PURPOSES = {
    "listing_image": IMAGES,
    "chat_attachment": IMAGES_AND_PDF,
    "verification_document": IMAGES_AND_PDF,
    "dispute_evidence": IMAGES_AND_PDF,
    "delivery_proof": IMAGES,
    "pickup_proof": IMAGES,
    "certification": IMAGES_AND_PDF,
    "support_attachment": IMAGES_AND_PDF,
}
PUBLIC_PURPOSES = {"listing_image"}


class FilesService:
    async def upload(self, user: Users, upload: UploadFile, purpose: str, db: AsyncSession) -> dict:
        if purpose not in PURPOSES:
            raise HTTPException(status_code=422, detail=f"purpose must be one of: {', '.join(sorted(PURPOSES))}.")
        max_bytes = int(await get_setting(db, "max_upload_mb")) * 1024 * 1024
        content = await upload.read(max_bytes + 1)
        if len(content) > max_bytes:
            raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                                detail=f"File is larger than {max_bytes // (1024 * 1024)} MB.")
        if not content:
            raise HTTPException(status_code=422, detail="File is empty.")
        content_type = detect_content_type(content)
        if content_type not in PURPOSES[purpose]:
            raise HTTPException(
                status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
                detail="Unsupported file type. Allowed: " + ", ".join(sorted(PURPOSES[purpose])),
            )
        file_id = str(uuid.uuid4())
        now = datetime.utcnow()
        key = f"{purpose}/{now:%Y/%m}/{file_id}.{EXTENSIONS[content_type]}"
        storage.save(key, content)
        db.add(StoredFiles(
            id=file_id, owner_id=user.id, purpose=purpose,
            original_name=(upload.filename or "")[:255], content_type=content_type,
            size_bytes=len(content), sha256=hashlib.sha256(content).hexdigest(),
            storage_path=key, created_at=now,
        ))
        await db.commit()
        return {"file_id": file_id, "content_type": content_type, "size_bytes": len(content),
                "url": f"/api/files/{file_id}"}

    @staticmethod
    async def require_owned(db: AsyncSession, file_ids: list[str] | None, owner_id: int, purposes: set[str]) -> list[str]:
        """Validate that files exist, belong to `owner_id` and were uploaded for an allowed purpose."""
        file_ids = [f for f in (file_ids or []) if f]
        if not file_ids:
            return []
        rows = (await db.execute(select(StoredFiles).where(
            StoredFiles.id.in_(file_ids), StoredFiles.deleted_at.is_(None)
        ))).scalars().all()
        found = {r.id: r for r in rows}
        for file_id in file_ids:
            row = found.get(file_id)
            if not row or row.owner_id != owner_id or row.purpose not in purposes:
                raise HTTPException(status_code=422, detail=f"File {file_id} is not a valid upload for this action.")
        return file_ids

    async def _can_access(self, user: Users, role: str | None, f: StoredFiles, db: AsyncSession) -> bool:
        if role == "admin" or f.owner_id == user.id or f.purpose in PUBLIC_PURPOSES:
            return True
        if f.purpose == "chat_attachment":
            return bool((await db.execute(select(Messages.id).where(
                Messages.attachment_file_id == f.id,
                or_(Messages.sender == user.id, Messages.receiver == user.id),
            ))).first())
        if f.purpose == "dispute_evidence":
            return bool((await db.execute(
                select(DisputeMessages.id)
                .join(Disputes, DisputeMessages.dispute_id == Disputes.id)
                .where(
                    cast(DisputeMessages.file_ids, String).contains(f.id),
                    or_(Disputes.raised_by == user.id, Disputes.against == user.id),
                )
            )).first())
        if f.purpose in ("delivery_proof", "pickup_proof"):
            return bool((await db.execute(
                select(Shipments.id)
                .join(Orders, Shipments.order_id == Orders.id)
                .where(
                    or_(Shipments.delivery_proof_file_id == f.id, Shipments.pickup_proof_file_id == f.id),
                    or_(Orders.farmer == user.id, Orders.vendor == user.id),
                )
            )).first())
        if f.purpose == "certification":
            return bool((await db.execute(select(ListingCertifications.id).where(
                ListingCertifications.file_id == f.id, ListingCertifications.status == "verified",
            ))).first())
        if f.purpose == "support_attachment":
            return bool((await db.execute(
                select(SupportTicketMessages.id)
                .join(SupportTickets, SupportTicketMessages.ticket_id == SupportTickets.id)
                .where(cast(SupportTicketMessages.file_ids, String).contains(f.id), SupportTickets.user_id == user.id)
            )).first())
        return False  # verification documents: owner and admins only

    async def download(self, file_id: str, user: Users, role: str | None, db: AsyncSession) -> Response:
        f = (await db.execute(select(StoredFiles).where(
            StoredFiles.id == file_id, StoredFiles.deleted_at.is_(None)
        ))).scalar_one_or_none()
        if not f or not await self._can_access(user, role, f, db):
            raise HTTPException(status_code=404, detail="File not found.")
        try:
            content = storage.read(f.storage_path)
        except FileNotFoundError:
            raise HTTPException(status_code=404, detail="File content is missing.")
        return Response(
            content=content,
            media_type=f.content_type,
            headers={
                "Content-Disposition": f'inline; filename="{f.id}.{EXTENSIONS.get(f.content_type, "bin")}"',
                "X-Content-Type-Options": "nosniff",
                "Cache-Control": "private, max-age=3600",
            },
        )

    async def delete(self, file_id: str, user: Users, db: AsyncSession) -> dict:
        f = (await db.execute(select(StoredFiles).where(StoredFiles.id == file_id))).scalar_one_or_none()
        if not f or f.owner_id != user.id or f.deleted_at:
            raise HTTPException(status_code=404, detail="File not found.")
        in_use = (await db.execute(select(ListingImages.id).where(ListingImages.file_id == file_id))).first()
        if f.purpose not in ("listing_image",) or in_use:
            raise HTTPException(status_code=409, detail="This file is attached to a record and is kept as evidence.")
        f.deleted_at = datetime.utcnow()
        storage.delete(f.storage_path)
        await db.commit()
        return {"success": "File deleted."}
