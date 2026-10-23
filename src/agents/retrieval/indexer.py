"""
Listing indexer for hybrid retrieval.

What is embedded: the commodity names (English and Telugu), category, variety, declared grade,
packaging, organic claim, district/state and the farmer's description - the fields a buyer
describes in words. Price, quantity, dates and location coordinates are NOT embedded; they are
exact filters and scores, and embedding them would only blur them.

Freshness: a listing's row is stale when the listing was updated after its embedding or the
text hash differs. The scheduler re-indexes stale active listings in batches; search also
indexes missing candidates on demand (bounded). Rows for deleted, removed or archived listings
are purged; search always joins the live listing, so a sold or expired listing never surfaces
even before its row is purged.

    python -m src.agents.retrieval.indexer reindex [--all]   # (re)build for the configured model
    python -m src.agents.retrieval.indexer purge [--old-versions]
    python -m src.agents.retrieval.indexer status
"""
import argparse
import asyncio
import hashlib

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from src.agents.retrieval.embeddings import embed_passages, get_embedder, vector_literal
from src.data_models.catalog_model import ProduceCategories
from src.data_models.crops_model import Crops
from src.data_models.districts_model import Districts
from src.data_models.farmer_inventory_model import FarmerInventory
from src.data_models.states_model import States
from src.data_models.users_model import Users
from src.db_connections.database import AsyncSessionLocal
from src.helpers.logging_config import get_logger
from src.core.clock import utcnow

logger = get_logger(__name__)

INDEXED_STATUSES = ("active", "reserved", "paused")


def build_search_text(*, crop_name, crop_name_te, category, variety, grade, packaging, organic_claim,
                      district, state, description) -> str:
    parts = [crop_name, crop_name_te, category, variety]
    if grade:
        parts.append(f"grade {grade}")
    if packaging:
        parts.append(f"packed in {packaging}")
    if organic_claim:
        parts.append("organic (farmer claim)")
    parts += [district, state, description]
    return " | ".join(p.strip() for p in parts if p and str(p).strip())[:2000]


def content_hash(search_text: str) -> str:
    return hashlib.sha256(search_text.encode("utf-8")).hexdigest()


async def listing_texts(db: AsyncSession, listing_ids: list[int]) -> dict[int, str]:
    if not listing_ids:
        return {}
    rows = (await db.execute(
        select(FarmerInventory, Crops.crop_name, Crops.name_te, ProduceCategories.name,
               Districts.district_name, States.state_name)
        .join(Crops, FarmerInventory.crop == Crops.id)
        .outerjoin(ProduceCategories, Crops.category_id == ProduceCategories.id)
        .join(Users, FarmerInventory.created_by == Users.id)
        .outerjoin(Districts, Users.district == Districts.id)
        .outerjoin(States, Users.state == States.id)
        .where(FarmerInventory.id.in_(listing_ids))
    )).all()
    return {
        listing.id: build_search_text(
            crop_name=crop_name, crop_name_te=crop_te, category=category, variety=listing.variety,
            grade=listing.quality_grade, packaging=listing.packaging, organic_claim=listing.organic_claim,
            district=district, state=state, description=listing.description,
        )
        for listing, crop_name, crop_te, category, district, state in rows
    }


async def index_listings(db: AsyncSession, listing_ids: list[int], force: bool = False) -> int:
    """Embed listings whose row is missing or stale for the current model. Caller commits."""
    texts = await listing_texts(db, listing_ids)
    if not texts:
        return 0
    embedder = get_embedder()
    model_version = embedder.model_version
    existing = dict((await db.execute(text(
        "SELECT listing_id, content_hash FROM listing_embeddings "
        "WHERE model_version = :mv AND listing_id = ANY(:ids)"
    ), {"mv": model_version, "ids": list(texts)})).all())
    todo = [(lid, t) for lid, t in texts.items() if force or existing.get(lid) != content_hash(t)]
    now = utcnow()
    unchanged = [lid for lid in texts if lid in existing and lid not in {t[0] for t in todo}]
    if unchanged:
        # e.g. a price or stock edit: the embedded text is the same, so only mark the row fresh.
        await db.execute(text(
            "UPDATE listing_embeddings SET updated_at = :now WHERE model_version = :mv AND listing_id = ANY(:ids)"
        ), {"now": now, "mv": model_version, "ids": unchanged})
    if not todo:
        return 0
    vectors = await embed_passages([t for _, t in todo])
    for (listing_id, search_text), vector in zip(todo, vectors):
        await db.execute(text(
            "INSERT INTO listing_embeddings "
            "(listing_id, model_version, dimensions, embedding, search_text, content_hash, created_at, updated_at) "
            "VALUES (:lid, :mv, :dims, CAST(CAST(:emb AS TEXT) AS vector), :txt, :hash, :now, :now) "
            "ON CONFLICT (listing_id, model_version) DO UPDATE SET embedding = EXCLUDED.embedding, "
            "dimensions = EXCLUDED.dimensions, search_text = EXCLUDED.search_text, "
            "content_hash = EXCLUDED.content_hash, updated_at = EXCLUDED.updated_at"
        ), {"lid": listing_id, "mv": model_version, "dims": len(vector), "emb": vector_literal(vector),
            "txt": search_text, "hash": content_hash(search_text), "now": now})
    return len(todo)


async def index_listings_now(listing_ids: list[int]) -> int:
    async with AsyncSessionLocal() as db:
        count = await index_listings(db, listing_ids)
        await db.commit()
        return count


async def stale_listing_ids(db: AsyncSession, limit: int) -> list[int]:
    return list((await db.execute(text(
        "SELECT fi.id FROM farmer_inventory fi "
        "LEFT JOIN listing_embeddings le ON le.listing_id = fi.id AND le.model_version = :mv "
        "WHERE fi.deleted_at IS NULL AND fi.status = ANY(:statuses) "
        "AND (le.id IS NULL OR le.updated_at < COALESCE(fi.updated_at, fi.created_at)) "
        "ORDER BY fi.id LIMIT :limit"
    ), {"mv": get_embedder().model_version, "statuses": list(INDEXED_STATUSES), "limit": limit})).scalars().all())


async def reindex_stale(db: AsyncSession, batch: int = 200) -> dict:
    ids = await stale_listing_ids(db, batch)
    count = await index_listings(db, ids)
    purged = await purge_inactive(db)
    await db.commit()
    return {"indexed": count, "purged": purged, "model_version": get_embedder().model_version}


async def purge_inactive(db: AsyncSession) -> int:
    result = await db.execute(text(
        "DELETE FROM listing_embeddings le USING farmer_inventory fi "
        "WHERE le.listing_id = fi.id AND (fi.deleted_at IS NOT NULL OR fi.status IN ('removed', 'archived'))"
    ))
    return result.rowcount or 0


async def purge_old_versions(db: AsyncSession) -> int:
    result = await db.execute(text("DELETE FROM listing_embeddings WHERE model_version <> :mv"),
                              {"mv": get_embedder().model_version})
    return result.rowcount or 0


async def _main(argv=None) -> int:
    import src.data_models.registry  # noqa: F401

    parser = argparse.ArgumentParser(prog="python -m src.agents.retrieval.indexer")
    sub = parser.add_subparsers(dest="command", required=True)
    reindex = sub.add_parser("reindex")
    reindex.add_argument("--all", action="store_true", help="re-embed every indexable listing")
    purge = sub.add_parser("purge")
    purge.add_argument("--old-versions", action="store_true", help="also delete rows of other embedding models")
    sub.add_parser("status")
    args = parser.parse_args(argv)

    async with AsyncSessionLocal() as db:
        if args.command == "reindex":
            after, total = 0, 0
            while True:
                if args.all:
                    ids = list((await db.execute(text(
                        "SELECT id FROM farmer_inventory WHERE deleted_at IS NULL AND status = ANY(:s) "
                        "AND id > :after ORDER BY id LIMIT 500"
                    ), {"s": list(INDEXED_STATUSES), "after": after})).scalars().all())
                    count = await index_listings(db, ids, force=True)
                    after = ids[-1] if ids else after
                else:
                    ids = await stale_listing_ids(db, 500)
                    count = await index_listings(db, ids)
                await db.commit()
                total += count
                print(f"indexed {count} of {len(ids)} listings")
                if len(ids) < 500 or (not args.all and count == 0):
                    break
            print(f"done: {total} embeddings written for model {get_embedder().model_version}")
        elif args.command == "purge":
            removed = await purge_inactive(db)
            if args.old_versions:
                removed += await purge_old_versions(db)
            await db.commit()
            print(f"removed {removed} embedding rows")
        else:
            rows = (await db.execute(text(
                "SELECT model_version, count(*), max(updated_at) FROM listing_embeddings GROUP BY model_version"
            ))).all()
            print(f"configured model: {get_embedder().model_version}")
            for model_version, count, updated in rows:
                print(f"  {model_version}: {count} rows, last update {updated}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main()))
