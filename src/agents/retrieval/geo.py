"""
PostGIS expressions for radius matching. Points are built from the latitude/longitude columns
with the same expression the GiST indexes in migration 006 use, so ST_DWithin can use them.
Distances are geodesic metres on the WGS84 spheroid (geography type), reported in km.
"""
from sqlalchemy import Float, cast, func
from sqlalchemy.types import UserDefinedType


class Geography(UserDefinedType):
    cache_ok = True

    def get_col_spec(self, **kw):
        return "geography"


def point(lat_col, lon_col):
    return cast(func.ST_SetSRID(func.ST_MakePoint(cast(lon_col, Float), cast(lat_col, Float)), 4326), Geography())


def origin(lat: float, lon: float):
    return cast(func.ST_SetSRID(func.ST_MakePoint(lon, lat), 4326), Geography())


def within_km(point_expr, origin_expr, radius_km: float):
    return func.ST_DWithin(point_expr, origin_expr, radius_km * 1000.0)


def distance_km(point_expr, origin_expr):
    return func.ST_Distance(point_expr, origin_expr) / 1000.0


def valid_coordinates(lat, lon) -> bool:
    try:
        return lat is not None and lon is not None and -90 <= float(lat) <= 90 and -180 <= float(lon) <= 180
    except (TypeError, ValueError):
        return False
