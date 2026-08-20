"""
OSRM API integration.
Uses the public OSRM driving profile.
"""
from __future__ import annotations

import httpx

from app.core.config import get_settings
from app.core.errors import RoutingAPIError
from app.core.logging import get_logger
from app.schemas.constraints import ConstraintProfile

logger = get_logger("routing")


class RoutingService:
    """
    Fetches route candidates from OSRM public API.
    """

    def __init__(self):
        self.settings = get_settings()

    async def get_routes(
        self,
        origin_lat: float,
        origin_lng: float,
        dest_lat: float,
        dest_lng: float,
        constraints: ConstraintProfile,
    ) -> list[dict]:
        """
        Fetch route candidates from OSRM API.
        Returns list of raw route dicts from OSRM.
        Raises RoutingAPIError if the call fails.
        """
        # OSRM expects longitude,latitude format
        url = (
            f"{self.settings.osrm_base_url}/route/v1/driving/"
            f"{origin_lng},{origin_lat};{dest_lng},{dest_lat}"
        )
        params = {
            "alternatives": "true",
            "steps": "true",
            "annotations": "true",
            "overview": "full",
        }

        # OSRM public server doesn't natively support all the exclude parameters easily in the driving profile
        # So we fetch routes and let the downstream scoring service penalize highways/tolls if present

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.get(url, params=params)
                if resp.status_code != 200:
                    logger.error("OSRM API error: %d %s", resp.status_code, resp.text[:500])
                    raise RoutingAPIError(f"OSRM API returned status {resp.status_code}")
                data = resp.json()
                
                if data.get("code") != "Ok":
                    logger.error("OSRM API returned non-Ok code: %s", data.get("code"))
                    raise RoutingAPIError(f"OSRM API returned {data.get('code')}")

                routes = data.get("routes", [])
                logger.info("OSRM API returned %d route(s)", len(routes))
                return routes
        except httpx.TimeoutException:
            raise RoutingAPIError("OSRM API request timed out")
        except httpx.RequestError as e:
            raise RoutingAPIError(f"OSRM API request failed: {e}")

    @staticmethod
    def parse_osrm_route(raw: dict, route_index: int) -> dict:
        """
        Parse an OSRM Routes API response into our internal format.
        Returns dict with: distance_meters, duration_seconds, static_duration_seconds,
                          traffic_delay_seconds, polyline, has_highway, warnings
        """
        duration_seconds = float(raw.get("duration", 0.0))
        distance_meters = float(raw.get("distance", 0.0))

        polyline = raw.get("geometry", "")

        # OSRM demo doesn't have live traffic delay differences, static duration is the same
        static_duration_seconds = duration_seconds
        
        # ---- INJECT MOCK TRAFFIC FOR DEMONSTRATION ----
        # Generate some deterministic random traffic based on polyline
        import hashlib
        import random
        route_hash = hashlib.md5(polyline.encode()).hexdigest() if polyline else "default"
        random.seed(route_hash)
        
        # Add 0 to 15 minutes of random delay
        traffic_delay = random.randint(0, 900) if random.random() < 0.7 else 0
        duration_seconds += traffic_delay
        # ---- END INJECT ----

        # Check if route uses highways by inspecting the steps
        has_highway = False
        legs = raw.get("legs", [])
        for leg in legs:
            for step in leg.get("steps", []):
                ref = str(step.get("ref", "")).upper()
                name = str(step.get("name", "")).upper()
                if any(x in ref or x in name for x in ("HWY", "HIGHWAY", "EXPRESSWAY", "FREEWAY", "I-", "US-", "STATE ROUTE")):
                    has_highway = True
                    break
            if has_highway:
                break

        warnings: list[str] = []
        return {
            "distance_meters": distance_meters,
            "duration_seconds": duration_seconds,
            "static_duration_seconds": static_duration_seconds,
            "traffic_delay_seconds": traffic_delay,
            "polyline": polyline,
            "has_highway": has_highway,
            "warnings": warnings,
            "route_index": route_index,
        }
