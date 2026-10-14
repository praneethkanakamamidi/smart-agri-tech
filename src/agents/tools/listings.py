"""Listing creation (after the farmer approves the reviewed draft)."""
from sqlalchemy.ext.asyncio import AsyncSession

from src.agents.context import RunContext
from src.agents.tools.base import tool
from src.data_models.users_model import Users
from src.helpers.logging_config import get_logger
from src.schemas.listings_schema import ListingCreateSchema
from src.services.listings_service import ListingsService

logger = get_logger(__name__)


@tool("create_listing", ListingCreateSchema,
      "Create the farmer's listing from the confirmed draft (same validation as POST /api/listings). Needs approval.")
async def create_listing(db: AsyncSession, actor: Users, args: ListingCreateSchema, ctx: RunContext) -> dict:
    result = await ListingsService().create(actor, args, db)
    try:  # index for discovery right away; the scheduler catches up if this fails
        from src.agents.retrieval.indexer import index_listings_now

        await index_listings_now([result["id"]])
    except Exception as e:
        logger.warning(f"listing {result['id']} not indexed yet: {e.__class__.__name__}")
    return {**result, "listing_id": result["id"]}
