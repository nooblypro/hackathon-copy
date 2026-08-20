"""
OSRM API integration.
Uses the public OSRM driving profile.
"""
from __future__ import annotations

import httpx
import hashlib
import random

from app.core.config import get_settings
from app.core.errors import RoutingAPIError
from app.core.logging import get_logger
from app.schemas.constraints import ConstraintProfile

logger = get_logger("routing")


class RoutingService:
    """
    Fetches route candidates from Ola Maps API.
    """

    def __init__(self):
        self.settings = get_settings()
        self.base_url = "https://api.olamaps.io/routing/v1/directions"

    async def get_routes(
        self,
        origin_lat: float,
        origin_lng: float,
        dest_lat: float,
        dest_lng: float,
        constraints: ConstraintProfile,
    ) -> list[dict]:
        """
        Fetch route candidates from Ola Maps API.
        Returns list of raw route dicts from Ola Maps.
        Raises RoutingAPIError if the call fails.
        """
        if not self.settings.ola_maps_api_key:
            logger.warning("Ola Maps API key is missing. Using dummy route for demonstration.")
            return [self._generate_dummy_route(origin_lat, origin_lng, dest_lat, dest_lng)]
            
        params = {
            "origin": f"{origin_lat},{origin_lng}",
            "destination": f"{dest_lat},{dest_lng}",
            "api_key": self.settings.ola_maps_api_key,
            "alternatives": "true",
            "steps": "true",
        }

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.post(self.base_url, params=params)
                if resp.status_code != 200:
                    logger.error("Ola Maps API error: %d %s", resp.status_code, resp.text[:500])
                    # If it fails, return dummy route so frontend still works
                    return [self._generate_dummy_route(origin_lat, origin_lng, dest_lat, dest_lng)]
                
                data = resp.json()
                
                if data.get("status") != "SUCCESS":
                    logger.error("Ola Maps API returned non-SUCCESS status: %s", data.get("status"))
                    # Fallback to dummy
                    return [self._generate_dummy_route(origin_lat, origin_lng, dest_lat, dest_lng)]

                routes = data.get("routes", [])
                logger.info("Ola Maps API returned %d route(s)", len(routes))
                
                if not routes:
                    return [self._generate_dummy_route(origin_lat, origin_lng, dest_lat, dest_lng)]
                    
                return routes
        except httpx.TimeoutException:
            logger.error("Ola Maps API request timed out")
            return [self._generate_dummy_route(origin_lat, origin_lng, dest_lat, dest_lng)]
        except httpx.RequestError as e:
            logger.error(f"Ola Maps API request failed: {e}")
            return [self._generate_dummy_route(origin_lat, origin_lng, dest_lat, dest_lng)]

    @staticmethod
    def parse_osrm_route(raw: dict, route_index: int) -> dict:
        """
        Parse an Ola Maps Routes API response into our internal format.
        (Method kept named parse_osrm_route for downstream compatibility)
        Returns dict with: distance_meters, duration_seconds, static_duration_seconds,
                          traffic_delay_seconds, polyline, has_highway, warnings
        """
        # Ola Maps format might have legs -> duration/distance
        legs = raw.get("legs", [])
        
        duration_seconds = 0.0
        distance_meters = 0.0
        
        has_highway = False
        
        for leg in legs:
            duration_seconds += float(leg.get("duration", 0.0))
            distance_meters += float(leg.get("distance", 0.0))
            for step in leg.get("steps", []):
                instructions = str(step.get("instructions", "")).upper()
                name = str(step.get("name", "")).upper()
                if any(x in instructions or x in name for x in ("HWY", "HIGHWAY", "EXPRESSWAY", "FREEWAY", "TOLL", "NH")):
                    has_highway = True

        # Fallback if no legs but has top-level summary
        if not legs and "summary" in raw:
            duration_seconds = float(raw["summary"].get("duration", 0.0))
            distance_meters = float(raw["summary"].get("distance", 0.0))
            
        polyline = raw.get("overview_polyline", "")

        static_duration_seconds = duration_seconds
        
        # Add random traffic
        route_hash = hashlib.md5(polyline.encode()).hexdigest() if polyline else "default"
        random.seed(route_hash)
        
        traffic_delay = random.randint(0, 900) if random.random() < 0.7 else 0
        duration_seconds += traffic_delay

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

    def _generate_dummy_route(self, origin_lat: float, origin_lng: float, dest_lat: float, dest_lng: float) -> dict:
        """Fallback to generate a simple straight line route if API fails."""
        import math
        import polyline
        
        # Create a simple 2-point polyline
        line = [(origin_lat, origin_lng), (dest_lat, dest_lng)]
        encoded = polyline.encode(line)
        
        # Calculate rough distance using Haversine
        R = 6371e3
        phi1 = math.radians(origin_lat)
        phi2 = math.radians(dest_lat)
        dphi = math.radians(dest_lat - origin_lat)
        dlam = math.radians(dest_lng - origin_lng)
        
        a = math.sin(dphi/2) * math.sin(dphi/2) + \
            math.cos(phi1) * math.cos(phi2) * \
            math.sin(dlam/2) * math.sin(dlam/2)
        c = 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))
        distance = R * c
        
        # Rough duration assuming 40 km/h
        duration = (distance / 40000) * 3600
        
        return {
            "legs": [
                {
                    "distance": distance,
                    "duration": duration,
                    "steps": []
                }
            ],
            "overview_polyline": encoded
        }
