"""
Maps and geocoding behind a replaceable adapter.

- OfflineMaps (default, MAPS_PROVIDER=offline): straight-line distance x ROAD_DISTANCE_FACTOR
  and AVG_TRUCK_SPEED_KMPH. Always labelled an estimate. No external calls, no geocoding.
- OsrmMaps (MAPS_PROVIDER=osrm, OSRM_BASE_URL): driving distance/duration from an OSRM server
  (self-hosted or a provider), falling back to the offline estimate if the call fails.
- NominatimGeocoder (GEOCODER_PROVIDER=nominatim): address -> coordinates via OpenStreetMap
  Nominatim. NOMINATIM_USER_AGENT is required by its usage policy; respect its rate limits or
  point NOMINATIM_BASE_URL at your own instance.

Route results are estimates of travel, never bookings: nothing here reserves a vehicle.
"""
import math
from dataclasses import asdict, dataclass

import httpx

from src.agents.config import settings
from src.helpers.logging_config import get_logger

logger = get_logger(__name__)
EARTH_RADIUS_KM = 6371.0088


@dataclass(frozen=True)
class GeoPoint:
    lat: float
    lon: float


@dataclass
class RouteEstimate:
    distance_km: float
    duration_minutes: int
    method: str  # straight_line_estimate | osrm_route
    is_estimate: bool = True
    note: str = "Estimated travel only. No transport has been booked."

    def as_dict(self) -> dict:
        return asdict(self)


def haversine_km(a: GeoPoint, b: GeoPoint) -> float:
    lat1, lat2 = math.radians(a.lat), math.radians(b.lat)
    dlat, dlon = lat2 - lat1, math.radians(b.lon - a.lon)
    h = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 2 * EARTH_RADIUS_KM * math.asin(math.sqrt(h))


class OfflineMaps:
    name = "offline"

    async def route(self, origin: GeoPoint, destination: GeoPoint) -> RouteEstimate:
        cfg = settings()
        straight = haversine_km(origin, destination)
        road = straight * cfg.road_distance_factor
        minutes = int(round(road / max(cfg.avg_truck_speed_kmph, 1) * 60))
        return RouteEstimate(
            distance_km=round(road, 1), duration_minutes=minutes, method="straight_line_estimate",
            note=(f"Estimate: {straight:.1f} km straight-line x {cfg.road_distance_factor} road factor at "
                  f"{cfg.avg_truck_speed_kmph:.0f} km/h. No transport has been booked."),
        )


class OsrmMaps(OfflineMaps):
    name = "osrm"

    def __init__(self, base_url: str, transport: httpx.AsyncBaseTransport | None = None):
        self.base_url = base_url.rstrip("/")
        self._client = httpx.AsyncClient(transport=transport)

    async def route(self, origin: GeoPoint, destination: GeoPoint) -> RouteEstimate:
        url = (f"{self.base_url}/route/v1/driving/{origin.lon:.6f},{origin.lat:.6f};"
               f"{destination.lon:.6f},{destination.lat:.6f}")
        try:
            response = await self._client.get(url, params={"overview": "false"}, timeout=settings().maps_timeout_s)
            response.raise_for_status()
            data = response.json()
            best = (data.get("routes") or [None])[0]
            if data.get("code") != "Ok" or not best:
                raise ValueError(f"OSRM returned {data.get('code')}")
            return RouteEstimate(
                distance_km=round(best["distance"] / 1000, 1), duration_minutes=int(round(best["duration"] / 60)),
                method="osrm_route", note="Road route estimate from OSRM. No transport has been booked.",
            )
        except (httpx.HTTPError, ValueError, KeyError) as e:
            logger.warning(f"OSRM route failed ({e.__class__.__name__}); using straight-line estimate")
            estimate = await super().route(origin, destination)
            estimate.note = "Routing service unavailable; " + estimate.note
            return estimate


class NominatimGeocoder:
    def __init__(self, base_url: str, user_agent: str, transport: httpx.AsyncBaseTransport | None = None):
        self.base_url = base_url.rstrip("/")
        self.user_agent = user_agent
        self._client = httpx.AsyncClient(transport=transport)

    async def geocode(self, query: str, country_code: str = "in") -> GeoPoint | None:
        if not query or len(query.strip()) < 3:
            return None
        try:
            response = await self._client.get(
                f"{self.base_url}/search", params={"q": query, "format": "jsonv2", "limit": 1, "countrycodes": country_code},
                headers={"User-Agent": self.user_agent}, timeout=settings().maps_timeout_s,
            )
            response.raise_for_status()
            results = response.json()
            if not results:
                return None
            return GeoPoint(float(results[0]["lat"]), float(results[0]["lon"]))
        except (httpx.HTTPError, ValueError, KeyError, IndexError) as e:
            logger.warning(f"geocoding failed ({e.__class__.__name__})")
            return None


class NoGeocoder:
    async def geocode(self, query: str, country_code: str = "in") -> GeoPoint | None:
        return None


_maps = None
_geocoder = None


def get_maps():
    global _maps
    if _maps is None:
        cfg = settings()
        _maps = OsrmMaps(cfg.osrm_base_url) if cfg.maps_provider == "osrm" and cfg.osrm_base_url else OfflineMaps()
    return _maps


def get_geocoder():
    global _geocoder
    if _geocoder is None:
        cfg = settings()
        if cfg.geocoder_provider == "nominatim" and cfg.nominatim_user_agent:
            _geocoder = NominatimGeocoder(cfg.nominatim_base_url, cfg.nominatim_user_agent)
        else:
            _geocoder = NoGeocoder()
    return _geocoder


def reset_maps():
    global _maps, _geocoder
    _maps = _geocoder = None
