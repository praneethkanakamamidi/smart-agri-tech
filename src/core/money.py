from decimal import Decimal, ROUND_HALF_UP

TWO_PLACES = Decimal("0.01")
ZERO = Decimal("0")


def D(value) -> Decimal:
    """Exact Decimal from int/float/str/Decimal/None (None -> 0)."""
    if value is None:
        return ZERO
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def money(value) -> Decimal:
    """Round to 2 decimal places, half-up (rupees and paise)."""
    return D(value).quantize(TWO_PLACES, rounding=ROUND_HALF_UP)


def to_paise(value) -> int:
    return int((money(value) * 100).to_integral_value(rounding=ROUND_HALF_UP))
