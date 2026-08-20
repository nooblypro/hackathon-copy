"""
Overpass API integration.
Searches for pitstops using OpenStreetMap data.
"""
from __future__ import annotations

import httpx

from app.core.config import get_settings
from app.core.errors import PitstopAPIError
from app.core.logging import get_logger
from app.schemas.pitstops import Pitstop

logger = get_logger("places")

# Maps our category names to Ola Maps types (approximate)
CATEGORY_TO_OLA_TYPES: dict[str, list[str]] = {
    "restroom": ["restroom", "toilet"],
    "pharmacy": ["pharmacy"],
    "hospital": ["hospital", "clinic"],
    "fuel": ["gas_station", "fuel"],
    "ev_charging": ["ev_charging", "charging_station"],
    "cafe": ["cafe", "restaurant", "food"],
    "rest_area": ["rest_area"],
}

# Keep Overpass tags for fallback
CATEGORY_TO_TAGS: dict[str, list[str]] = {
    "restroom": ['node["amenity"="toilets"]'],
    "pharmacy": ['node["amenity"="pharmacy"]'],
    "hospital": ['node["amenity"="hospital"]'],
    "fuel": ['node["amenity"="fuel"]'],
    "ev_charging": ['node["amenity"="charging_station"]'],
    "cafe": ['node["amenity"="cafe"]', 'node["amenity"="restaurant"]'],
    "rest_area": ['node["highway"="rest_area"]'],
}


class PlacesService:
    """Searches for pitstops using Ola Maps API with Overpass fallback."""

    def __init__(self):
        self.settings = get_settings()
        self.base_url = "https://api.olamaps.io/places/v1/nearbysearch"

    async def search_nearby(
        self,
        latitude: float,
        longitude: float,
        categories: list[str],
        radius_meters: float = 1000.0,
        max_results: int = 5,
    ) -> list[Pitstop]:
        """
        Search for pitstops near a location using Ola Maps API.
        Falls back to Overpass if API key is missing or request fails.
        """
        if not self.settings.ola_maps_api_key:
            logger.warning("Ola Maps API key not configured. Falling back to Overpass for places.")
            return await self._fallback_search(latitude, longitude, categories, radius_meters, max_results)

        all_pitstops: list[Pitstop] = []

        # Collect unique types
        included_types: list[str] = []
        for cat in categories:
            types = CATEGORY_TO_OLA_TYPES.get(cat, [])
            for t in types:
                if t not in included_types:
                    included_types.append(t)

        if not included_types:
            return []

        # Ola Maps uses comma separated types
        types_str = ",".join(included_types)

        params = {
            "layers": "venue",
            "types": types_str,
            "location": f"{latitude},{longitude}",
            "radius": int(radius_meters),
            "api_key": self.settings.ola_maps_api_key,
        }

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(self.base_url, params=params)
                if resp.status_code != 200:
                    logger.warning("Ola Maps Places API error: %d %s. Falling back to Overpass.", resp.status_code, resp.text[:200])
                    return await self._fallback_search(latitude, longitude, categories, radius_meters, max_results)
                
                data = resp.json()
                if data.get("status") != "ok":
                    logger.warning("Ola Maps Places API returned non-ok status: %s. Falling back.", data.get("status"))
                    return await self._fallback_search(latitude, longitude, categories, radius_meters, max_results)

                predictions = data.get("predictions", [])
                category_label = categories[0] if categories else "unknown"

                for i, el in enumerate(predictions):
                    if i >= max_results:
                        break
                        
                    display_name = el.get("name", "Unknown")
                    geom = el.get("geometry", {}).get("location", {})
                    lat = geom.get("lat")
                    lng = geom.get("lng")
                    
                    if not lat or not lng:
                        continue
                        
                    all_pitstops.append(
                        Pitstop(
                            place_id=str(el.get("place_id", f"ola_{i}")),
                            name=display_name,
                            category=category_label,
                            latitude=float(lat),
                            longitude=float(lng),
                            rating=None,
                            accessibility_info=None,
                            source="ola_maps",
                        )
                    )

                logger.info("Ola Maps API returned %d result(s) for categories %s", len(all_pitstops), categories)
                return all_pitstops

        except httpx.RequestError as e:
            logger.warning(f"Ola Maps Places request failed: {e}. Falling back.")
            return await self._fallback_search(latitude, longitude, categories, radius_meters, max_results)


    async def _fallback_search(
        self,
        latitude: float,
        longitude: float,
        categories: list[str],
        radius_meters: float,
        max_results: int,
    ) -> list[Pitstop]:
        """Fallback to Overpass API."""
        all_pitstops: list[Pitstop] = []

        # Collect unique tags
        included_tags: list[str] = []
        for cat in categories:
            tags = CATEGORY_TO_TAGS.get(cat, [])
            for t in tags:
                if t not in included_tags:
                    included_tags.append(t)

        if not included_tags:
            return []

        # Construct Overpass QL query
        query_statements = []
        for tag in included_tags:
            query_statements.append(f"{tag}(around:{radius_meters},{latitude},{longitude});")
        
        ql_query = (
            "[out:json];"
            "("
            + "".join(query_statements) +
            ");"
            f"out center {max_results};"
        )

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                headers = {"User-Agent": "CareGPS/1.0 (hackathon project)"}
                resp = await client.post(
                    self.settings.overpass_base_url, 
                    data={"data": ql_query},
                    headers=headers
                )
                if resp.status_code != 200:
                    logger.error("Overpass API error: %d %s", resp.status_code, resp.text[:500])
                    raise PitstopAPIError(f"Overpass API returned status {resp.status_code}")
                data = resp.json()

            elements = data.get("elements", [])
            category_label = categories[0] if categories else "unknown"

            for el in elements:
                tags = el.get("tags", {})
                display_name = tags.get("name", "Unknown")
                lat = el.get("lat")
                lng = el.get("lon")
                
                # Overpass doesn't have standard rating, so None
                rating = None
                
                # Accessibility check using common OSM tags
                accessibility_info = None
                wheelchair = tags.get("wheelchair")
                if wheelchair == "yes":
                    accessibility_info = "Wheelchair accessible entrance"
                elif wheelchair == "no":
                    accessibility_info = "No wheelchair accessible entrance reported"

                all_pitstops.append(
                    Pitstop(
                        place_id=str(el.get("id", "")),
                        name=display_name,
                        category=category_label,
                        latitude=lat,
                        longitude=lng,
                        rating=rating,
                        accessibility_info=accessibility_info,
                        source="overpass",
                    )
                )

            logger.info("Overpass API returned %d result(s) for categories %s", len(all_pitstops), categories)

        except httpx.TimeoutException:
            raise PitstopAPIError("Overpass API request timed out")
        except httpx.RequestError as e:
            raise PitstopAPIError(f"Overpass API request failed: {e}")

        return all_pitstops
