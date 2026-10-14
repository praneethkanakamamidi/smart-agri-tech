"""
In-process background jobs. Runs every SCHEDULER_INTERVAL_SECONDS (default 60). A Postgres
advisory lock makes sure only one worker/replica runs a tick at a time, so no extra
infrastructure (Celery/Redis) is needed for the MVP. Set SCHEDULER_ENABLED=false to disable
(e.g. when running a dedicated worker with `python -m src.core.scheduler`).
"""
import asyncio
import os
import time
from datetime import datetime, date, timedelta

from sqlalchemy import select, text, update
from sqlalchemy.exc import SQLAlchemyError

from src.core.audit import audit
from src.core.lookups import misc_id
from src.core.platform_settings import get_setting
from src.db_connections.database import AsyncSessionLocal, async_engine
from src.helpers.logging_config import get_logger

logger = get_logger(__name__)
LOCK_KEY = 7_302_211  # arbitrary, unique to this app
_last_daily_run: dict[str, float] = {}


async def job_expire_offers(db):
    from src.services.negotiations_service import NegotiationsService

    return {"warned": await NegotiationsService.warn_expiring(db), "expired": await NegotiationsService.expire_due(db)}


async def job_confirmation_timeouts(db):
    """Orders not confirmed by both parties in time are cancelled and their stock released."""
    from src.data_models.orders_model import Orders, PENDING_CONFIRMATION, CANCELLED
    from src.services import order_core

    pending_id = await misc_id(db, "order_status", PENDING_CONFIRMATION)
    ids = (await db.execute(select(Orders.id).where(
        Orders.status == pending_id, Orders.confirmation_deadline < datetime.utcnow()
    ).limit(100))).scalars().all()
    for order_id in ids:
        order = await order_core.lock_order(db, order_id)
        if await order_core.status_of(db, order) == PENDING_CONFIRMATION:
            await order_core.transition(db, order, CANCELLED, None, note="not confirmed in time; stock released",
                                        skip_payment_gate=True)
        await db.commit()
    return len(ids)


async def job_listing_expiry(db):
    from src.data_models.crops_model import Crops
    from src.data_models.farmer_inventory_model import FarmerInventory, ACTIVE, RESERVED, EXPIRED
    from src.services.notifications_service import notify_user

    today = date.today()
    expired = (await db.execute(select(FarmerInventory).where(
        FarmerInventory.status == ACTIVE, FarmerInventory.available_until < today
    ).limit(200))).scalars().all()
    for listing in expired:
        listing.status = EXPIRED
        crop = (await db.execute(select(Crops.crop_name).where(Crops.id == listing.crop))).scalar_one_or_none()
        await notify_user(db, listing.created_by, "listing_expired", {"crop": crop}, ref_type="listing",
                          ref_id=listing.id, dedupe_key=f"listing_expired:{listing.id}:{listing.available_until}")
    warn_days = int(await get_setting(db, "listing_expiry_warning_days"))
    soon = (await db.execute(select(FarmerInventory).where(
        FarmerInventory.status.in_((ACTIVE, RESERVED)),
        FarmerInventory.available_until.between(today, today + timedelta(days=warn_days)),
    ).limit(200))).scalars().all()
    for listing in soon:
        crop = (await db.execute(select(Crops.crop_name).where(Crops.id == listing.crop))).scalar_one_or_none()
        await notify_user(db, listing.created_by, "listing_expiring",
                          {"crop": crop, "date": listing.available_until.isoformat()}, ref_type="listing",
                          ref_id=listing.id, category="reminder",
                          dedupe_key=f"listing_expiring:{listing.id}:{listing.available_until}")
    await db.commit()
    return {"expired": len(expired), "warned": len(soon)}


async def job_auto_complete(db):
    """Delivered orders with no open dispute complete after N days if paid; otherwise remind the vendor."""
    from src.data_models.disputes_model import Disputes, ACTIVE_DISPUTE_STATES
    from src.data_models.orders_model import Orders, DELIVERED, COMPLETED
    from src.services import order_core
    from src.services.notifications_service import notify_user

    days = int(await get_setting(db, "auto_complete_days"))
    delivered_id = await misc_id(db, "order_status", DELIVERED)
    ids = (await db.execute(select(Orders.id).where(
        Orders.status == delivered_id, Orders.delivered_at < datetime.utcnow() - timedelta(days=days)
    ).limit(100))).scalars().all()
    completed = reminded = 0
    for order_id in ids:
        order = await order_core.lock_order(db, order_id)
        if (await db.execute(select(Disputes.id).where(
            Disputes.order_id == order.id, Disputes.status.in_(ACTIVE_DISPUTE_STATES)
        ))).first():
            await db.rollback()
            continue
        summary = await order_core.money_summary(db, order)
        if summary["outstanding"] > 0:
            created = await notify_user(db, order.vendor, "payment_reminder",
                                        {"amount": summary["outstanding"], "order_number": order.order_number},
                                        ref_type="order", ref_id=order.id, category="reminder",
                                        dedupe_key=f"payment_reminder:{order.id}:{date.today()}")
            reminded += 1 if created else 0
        else:
            await order_core.transition(db, order, COMPLETED, None, note=f"auto-completed {days} days after delivery")
            completed += 1
        await db.commit()
    return {"completed": completed, "payment_reminders": reminded}


async def job_notifications(db):
    from src.services.notifications_service import NotificationsService

    return await NotificationsService.process_deliveries(db)


async def job_recurring(db):
    from src.services.planning_service import PlanningService

    return await PlanningService.run_due_recurring(db)


async def job_close_buy_requests(db):
    from src.services.buy_requests_service import BuyRequestsService

    return await BuyRequestsService.close_expired(db)


async def job_account_deletion(db):
    """Anonymise accounts whose deletion grace period has passed. Order/payment records are retained."""
    from src.data_models.users_model import Users
    from src.data_models.platform_model import UserSessions, DeviceTokens
    from src.data_models.profiles_model import FarmerProfiles, VendorProfiles

    grace = int(await get_setting(db, "account_deletion_grace_days"))
    users = (await db.execute(select(Users).where(
        Users.deletion_requested_at < datetime.utcnow() - timedelta(days=grace), Users.deleted_at.is_(None)
    ).limit(50))).scalars().all()
    for user in users:
        user.first_name, user.last_name = "Deleted", "user"
        user.user_name = f"deleted-{user.id}@invalid"
        user.email = user.phone = None
        user.password = None
        user.mfa_secret_encrypted = None
        user.status = await misc_id(db, "status", "inactive")
        user.deleted_at = datetime.utcnow()
        await db.execute(update(UserSessions).where(UserSessions.user_id == user.id).values(revoked_at=datetime.utcnow()))
        for model in (DeviceTokens,):
            await db.execute(model.__table__.delete().where(model.user_id == user.id))
        farmer = (await db.execute(select(FarmerProfiles).where(FarmerProfiles.user_id == user.id))).scalar_one_or_none()
        if farmer:
            farmer.bank_account_number_enc = farmer.upi_id_enc = farmer.bank_account_holder = None
            farmer.farm_address = farmer.village = None
        vendor = (await db.execute(select(VendorProfiles).where(VendorProfiles.user_id == user.id))).scalar_one_or_none()
        if vendor:
            vendor.business_address = vendor.billing_address = None
        audit(db, "account.anonymised", "user", user.id)
    await db.commit()
    return len(users)


async def job_price_alerts(db):
    from src.services.insights_service import InsightsService

    return await InsightsService.price_change_alerts(db)


async def job_agent_embeddings(db):
    """Re-embed listings whose text changed (or are new) and purge rows of removed listings."""
    from src.agents.config import settings

    if not settings().enabled:
        return "agents disabled"
    from src.agents.retrieval.indexer import reindex_stale

    return await reindex_stale(db, batch=200)


async def job_agent_retention(db):
    """
    Retention for agent data:
    - workflow events and model-call logs: AGENT_EVENT_RETENTION_DAYS / AGENT_MODEL_CALL_RETENTION_DAYS;
    - tool-call log: AGENT_TOOL_CALL_RETENTION_DAYS, except mutations, which are kept with the
      audit log (they are the record of who approved what);
    - photos uploaded only for analysis (listing_image never attached to a listing):
      UNUSED_ANALYSIS_IMAGE_RETENTION_DAYS. Dispute evidence is never deleted here.
    """
    from src.agents.config import settings
    from src.core.storage import storage
    from src.data_models.agents_model import AgentModelCalls, AgentToolCalls, AgentWorkflowEvents
    from src.data_models.listing_extras_model import ListingImages
    from src.data_models.platform_model import StoredFiles

    cfg = settings()
    now = datetime.utcnow()
    events = await db.execute(AgentWorkflowEvents.__table__.delete().where(
        AgentWorkflowEvents.created_at < now - timedelta(days=cfg.event_retention_days)))
    calls = await db.execute(AgentModelCalls.__table__.delete().where(
        AgentModelCalls.created_at < now - timedelta(days=cfg.model_call_retention_days)))
    tools = await db.execute(AgentToolCalls.__table__.delete().where(
        AgentToolCalls.created_at < now - timedelta(days=cfg.tool_call_retention_days), AgentToolCalls.kind != "mutate"))
    orphans = (await db.execute(select(StoredFiles).where(
        StoredFiles.purpose == "listing_image", StoredFiles.deleted_at.is_(None),
        StoredFiles.created_at < now - timedelta(days=cfg.unused_image_retention_days),
        ~select(ListingImages.id).where(ListingImages.file_id == StoredFiles.id).exists(),
    ).limit(200))).scalars().all()
    for f in orphans:
        f.deleted_at = now
        storage.delete(f.storage_path)
    await db.commit()
    return {"events": events.rowcount, "model_calls": calls.rowcount, "tool_calls": tools.rowcount,
            "unused_images": len(orphans)}


FREQUENT_JOBS = (
    ("expire_offers", job_expire_offers),
    ("confirmation_timeouts", job_confirmation_timeouts),
    ("notifications", job_notifications),
)
HOURLY_JOBS = (
    ("listing_expiry", job_listing_expiry),
    ("auto_complete", job_auto_complete),
    ("recurring", job_recurring),
    ("close_buy_requests", job_close_buy_requests),
    ("agent_embeddings", job_agent_embeddings),
)
DAILY_JOBS = (
    ("account_deletion", job_account_deletion),
    ("price_alerts", job_price_alerts),
    ("agent_retention", job_agent_retention),
)


async def run_jobs(names: set[str] | None = None, force: bool = False) -> dict:
    """Run due jobs (or the named ones). Each job gets its own session; failures don't stop the others."""
    results = {}
    now = time.monotonic()
    plan = list(FREQUENT_JOBS)
    for interval, jobs in ((3600, HOURLY_JOBS), (86400, DAILY_JOBS)):
        for name, fn in jobs:
            if force or names or now - _last_daily_run.get(name, -1e9) >= interval:
                plan.append((name, fn))
    for name, fn in plan:
        if names and name not in names:
            continue
        async with AsyncSessionLocal() as db:
            try:
                results[name] = await fn(db)
                _last_daily_run[name] = now
            except Exception as e:  # keep the scheduler alive; the next tick retries
                await db.rollback()
                logger.exception(f"Scheduled job {name} failed: {e}")
                results[name] = f"error: {e}"
    return results


async def tick() -> dict | None:
    async with async_engine.connect() as conn:
        locked = (await conn.execute(text("SELECT pg_try_advisory_lock(:k)"), {"k": LOCK_KEY})).scalar()
        if not locked:
            return None
        try:
            return await run_jobs()
        finally:
            await conn.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": LOCK_KEY})
            await conn.commit()


async def scheduler_loop(stop: asyncio.Event):
    interval = int(os.getenv("SCHEDULER_INTERVAL_SECONDS", "60"))
    logger.info(f"Background scheduler started (every {interval}s).")
    while not stop.is_set():
        try:
            await tick()
        except SQLAlchemyError as e:
            logger.error(f"Scheduler tick failed: {e}")
        except Exception as e:
            logger.exception(f"Scheduler tick failed: {e}")
        try:
            await asyncio.wait_for(stop.wait(), timeout=interval)
        except asyncio.TimeoutError:
            pass


def scheduler_enabled() -> bool:
    return os.getenv("SCHEDULER_ENABLED", "true").lower() != "false"


if __name__ == "__main__":  # dedicated worker process
    import src.data_models.registry  # noqa: F401

    asyncio.run(scheduler_loop(asyncio.Event()))
