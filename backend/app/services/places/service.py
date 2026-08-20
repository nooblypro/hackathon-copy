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

# Maps our category names to Overpass API tags
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
    """Searches for pitstops using Overpass API."""

    def __init__(self):
        self.settings = get_settings()

    async def search_nearby(
        self,
        latitude: float,
        longitude: float,
        categories: list[str],
        radius_meters: float = 1000.0,
        max_results: int = 5,
    ) -> list[Pitstop]:
        """
        Search for pitstops near a location using Overpass API.
        """
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
