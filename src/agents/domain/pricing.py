"""
Deterministic negotiation pricing. Models may explain trade-offs and draft the message to the
counterparty, but every price an agent proposes is computed here and checked against:

- the user's authorised limit (a vendor's max price / a farmer's private floor) - never crossed;
- monotonic concessions (each counter moves toward the other side, never backwards);
- listing facts (asking price, available stock, minimum order).

Market statistics come from the platform's own recorded deals (InsightsService) and are only
used when the sample is flagged reliable.
"""
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal

from src.core.money import D, money

STEP = Decimal("0.50")  # prices are proposed in 50-paise steps


def round_step(value: Decimal) -> Decimal:
    return money((D(value) / STEP).quantize(Decimal("1"), rounding=ROUND_HALF_UP) * STEP)


@dataclass
class MarketBand:
    p25: Decimal | None = None
    median: Decimal | None = None
    p75: Decimal | None = None
    sample_size: int = 0
    reliable: bool = False

    @classmethod
    def from_insights(cls, insights: dict | None) -> "MarketBand":
        deals = (insights or {}).get("negotiated_prices") or {}
        def dec(v):
            return D(str(v)) if v is not None else None
        return cls(p25=dec(deals.get("p25")), median=dec(deals.get("median")), p75=dec(deals.get("p75")),
                   sample_size=int(deals.get("sample_size") or 0), reliable=bool(deals.get("is_reliable")))


@dataclass
class PriceDecision:
    action: str  # offer | counter | accept | reject | escalate
    unit_price: Decimal | None
    rationale: list[str] = field(default_factory=list)
    within_authority: bool = True

    def as_dict(self) -> dict:
        return {"action": self.action, "unit_price": str(self.unit_price) if self.unit_price is not None else None,
                "rationale": self.rationale, "within_authority": self.within_authority}


def opening_offer(asking: Decimal, band: MarketBand, *, target: Decimal | None, max_price: Decimal | None) -> PriceDecision:
    """A vendor's first offer on a listing."""
    asking = D(asking)
    rationale = []
    if target:
        price = D(target)
        rationale.append(f"your target price ₹{price}")
    elif band.reliable and band.p25 is not None:
        price = min(band.p25, asking)
        rationale.append(f"lower quartile of {band.sample_size} recent platform deals (₹{band.p25})")
    else:
        price = asking * Decimal("0.92")
        rationale.append("8% below the asking price (not enough recent deals for a market benchmark)")
    if price > asking:
        price = asking
        rationale.append("capped at the asking price: offering more than asked gains nothing")
    if max_price and price > D(max_price):
        price = D(max_price)
        rationale.append(f"capped at your maximum ₹{D(max_price)}")
    price = round_step(price)
    if price <= 0:
        return PriceDecision("escalate", None, rationale + ["no positive price satisfies the constraints"], False)
    return PriceDecision("offer", price, rationale)


def vendor_response(counter: Decimal, my_last: Decimal | None, *, max_price: Decimal | None, band: MarketBand,
                    round_no: int, max_rounds: int) -> PriceDecision:
    """What a vendor should do with a farmer's counteroffer, within the vendor's authority."""
    counter = D(counter)
    if max_price is not None and counter <= D(max_price):
        return PriceDecision("accept", counter, [f"the counter ₹{counter} is within your maximum ₹{D(max_price)}"])
    if round_no >= max_rounds:
        return PriceDecision("escalate", None, [f"{round_no} rounds without agreement; you decide the next step"])
    if max_price is None:
        return PriceDecision("escalate", None, ["no maximum price set; an agent can't decide how far to go"], False)
    base = D(my_last) if my_last is not None else D(max_price) * Decimal("0.9")
    price = (base + counter) / 2
    rationale = ["midpoint between your last offer and their counter"]
    if band.reliable and band.p75 is not None and price > band.p75:
        price = max(band.p75, base)
        rationale.append(f"held at the upper quartile of recent deals (₹{band.p75})")
    price = min(price, D(max_price))
    price = round_step(price)
    if my_last is not None and price <= D(my_last):
        price = round_step(D(my_last) + STEP)
        if price > D(max_price):
            return PriceDecision("escalate", None, ["no room left below your maximum"], False)
        rationale.append("a small step up keeps the concession moving forward")
    return PriceDecision("counter", price, rationale)


def farmer_response(offer: Decimal, asking: Decimal, my_last: Decimal | None, *, floor: Decimal | None,
                    band: MarketBand, round_no: int, max_rounds: int) -> PriceDecision:
    """What a farmer should do with a vendor's offer. The private floor is never revealed or crossed."""
    offer, asking = D(offer), D(asking)
    anchor = D(my_last) if my_last is not None else asking
    if offer >= anchor * Decimal("0.97"):
        return PriceDecision("accept", offer, [f"the offer ₹{offer} is within 3% of your price ₹{anchor}"])
    if floor is not None and offer >= D(floor) and band.reliable and band.median is not None and offer >= band.median:
        return PriceDecision("accept", offer, ["at or above your minimum and the recent median deal price"])
    if round_no >= max_rounds:
        return PriceDecision("escalate", None, [f"{round_no} rounds without agreement; you decide the next step"])
    price = (anchor + offer) / 2
    rationale = ["midpoint between your last price and their offer"]
    if band.reliable and band.p25 is not None and price < band.p25:
        price = band.p25
        rationale.append(f"raised to the lower quartile of recent deals (₹{band.p25})")
    if floor is not None and price < D(floor):
        price = D(floor)
        rationale.append("raised to your private minimum price")
    price = round_step(min(price, anchor))
    if my_last is not None and price >= D(my_last):
        price = round_step(D(my_last) - STEP)
        if floor is not None and price < D(floor):
            return PriceDecision("escalate", None, ["no room left above your minimum"], False)
    return PriceDecision("counter", price, rationale)


def validate_terms(*, unit_price: Decimal, quantity: Decimal, available: Decimal, min_order: Decimal | None,
                   max_price: Decimal | None = None, floor: Decimal | None = None) -> list[str]:
    """Policy violations for a proposed offer (empty list = acceptable)."""
    problems = []
    if D(unit_price) <= 0:
        problems.append("price must be positive")
    if D(quantity) <= 0:
        problems.append("quantity must be positive")
    if D(quantity) > D(available):
        problems.append(f"only {D(available)} available")
    if min_order and D(quantity) < D(min_order) and D(available) >= D(min_order):
        problems.append(f"below the minimum order of {D(min_order)}")
    if max_price is not None and D(unit_price) > D(max_price):
        problems.append(f"₹{D(unit_price)} exceeds the authorised maximum ₹{D(max_price)}")
    if floor is not None and D(unit_price) < D(floor):
        problems.append("below the farmer's minimum price")
    return problems
