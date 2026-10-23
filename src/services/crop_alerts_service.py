from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import joinedload
from sqlalchemy.ext.asyncio import AsyncSession

from src.data_models.crop_alerts_model import CropAlerts
from src.data_models.crops_model import Crops
from src.helpers.serializers import model_to_dict
from src.core.clock import utcnow


class CropAlertsService:
    """Vendor saved searches. Matching is done when a farmer lists stock (see FarmerInventoryService)."""

    async def _get_owned_alert(self, alert_id: int, vendor_id: int, db: AsyncSession) -> CropAlerts:
        alert = (await db.execute(select(CropAlerts).where(CropAlerts.id == alert_id))).scalar_one_or_none()
        if not alert or alert.vendor != vendor_id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Alert not found.")
        return alert

    async def create_alert(self, payload, vendor_id: int, db: AsyncSession):
        try:
            crop = (await db.execute(select(Crops).where(Crops.id == payload.crop))).scalar_one_or_none()
            if not crop:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Crop not found.")
            alert = CropAlerts(
                vendor=vendor_id,
                crop=payload.crop,
                state=payload.state,
                district=payload.district,
                min_quantity_kg=payload.min_quantity_kg,
                max_price_per_kg=payload.max_price_per_kg,
                is_active=True,
                created_at=utcnow(),
            )
            db.add(alert)
            await db.commit()
            return {"success": "Alert created. You'll be notified when matching stock is listed.", "alert_id": alert.id}
        except HTTPException:
            await db.rollback()
            raise
        except Exception as e:
            await db.rollback()
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"An error occurred: {str(e)}",
            )

    async def list_alerts(self, vendor_id: int, db: AsyncSession):
        try:
            stmt = (
                select(CropAlerts)
                .where(CropAlerts.vendor == vendor_id)
                .options(joinedload(CropAlerts.crop_rel))
                .order_by(CropAlerts.created_at.desc())
            )
            alerts = (await db.execute(stmt)).scalars().unique().all()
            return [
                model_to_dict(a, crop_name=a.crop_rel.crop_name if a.crop_rel else None)
                for a in alerts
            ]
        except Exception as e:
            await db.rollback()
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"An error occurred: {str(e)}",
            )

    async def toggle_alert(self, alert_id: int, vendor_id: int, db: AsyncSession):
        try:
            alert = await self._get_owned_alert(alert_id, vendor_id, db)
            alert.is_active = not alert.is_active
            await db.commit()
            return {"success": f"Alert {'activated' if alert.is_active else 'paused'}.", "is_active": alert.is_active}
        except HTTPException:
            await db.rollback()
            raise
        except Exception as e:
            await db.rollback()
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"An error occurred: {str(e)}",
            )

    async def delete_alert(self, alert_id: int, vendor_id: int, db: AsyncSession):
        try:
            alert = await self._get_owned_alert(alert_id, vendor_id, db)
            await db.delete(alert)
            await db.commit()
            return {"success": "Alert deleted."}
        except HTTPException:
            await db.rollback()
            raise
        except Exception as e:
            await db.rollback()
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"An error occurred: {str(e)}",
            )
