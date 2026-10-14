"""Maps free-text produce names to catalog crops. Only existing crops are returned."""
import json
import re
from functools import lru_cache
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.data_models.crops_model import Crops

_SYNONYMS_FILE = Path(__file__).resolve().parent.parent / "data" / "commodity_synonyms.json"


@lru_cache(maxsize=1)
def synonyms() -> dict[str, list[str]]:
    data = json.loads(_SYNONYMS_FILE.read_text(encoding="utf-8"))
    return {k.lower(): [s.lower() for s in v] for k, v in data.items() if not k.startswith("_")}


def _norm(term: str) -> str:
    """Lower-case, collapse spaces, and singularise English plurals (tomatoes, chillies, onions)."""
    term = re.sub(r"\s+", " ", (term or "").strip().lower())
    if len(term) <= 3 or not term.isascii():
        return term
    if term.endswith(("oes", "shes", "ches", "lies", "xes")):
        return term[:-2]
    if term.endswith("s") and not term.endswith("ss"):
        return term[:-1]
    return term


def match_terms(terms: list[str], crops: list[tuple[int, str | None, str | None]]) -> list[dict]:
    """Pure matching so it can be unit-tested: exact name > synonym > partial name."""
    vocab = synonyms()
    results, seen = [], set()
    for raw in terms:
        term = _norm(raw)
        if not term:
            continue
        best = None
        for crop_id, name, name_te in crops:
            names = [n.lower() for n in (name, name_te) if n]
            canonical = (name or "").lower()
            if term in names or term in {_norm(n) for n in names}:
                best = (crop_id, name, "exact", 3)
                break
            aliases = vocab.get(canonical) or vocab.get(_norm(canonical), [])
            alias_hit = term in aliases or term in {_norm(s) for s in aliases}
            if alias_hit and (not best or best[3] < 2):
                best = (crop_id, name, "synonym", 2)
            elif len(term) >= 4 and any(term in n or (len(n) >= 4 and n in term) for n in names):
                if not best or best[3] < 1:
                    best = (crop_id, name, "partial", 1)
        if best and best[0] not in seen:
            seen.add(best[0])
            results.append({"crop_id": best[0], "crop_name": best[1], "matched_term": raw, "method": best[2]})
    return results


async def resolve_commodities(db: AsyncSession, terms: list[str]) -> list[dict]:
    if not terms:
        return []
    crops = (await db.execute(select(Crops.id, Crops.crop_name, Crops.name_te))).all()
    return match_terms(terms, [tuple(c) for c in crops])
