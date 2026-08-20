import httpx
from urllib.parse import quote_plus
from typing import Optional
from app.schemas.coordinates import Coordinate
from app.core.logging import get_logger

logger = get_logger("geocoding")

class GeocodingAPIError(Exception):
    pass

class GeocodingService:
    """Service to convert place names and addresses to coordinates using Nominatim API."""

    def __init__(self):
        self.base_url = "https://photon.komoot.io/api/"
        self.headers = {
            "User-Agent": "RouteEase/1.0"
        }

    async def geocode(self, query: str) -> Coordinate:
        """Geocode a text query to a Coordinate. Raises GeocodingAPIError if not found."""
        if not query or not query.strip():
            raise GeocodingAPIError("Empty geocoding query")

        # Append country context to ensure "Phoenix" doesn't resolve to Arizona, USA
        search_query = query
        if "india" not in query.lower():
            search_query = f"{query}, India"

        params = {
            "q": search_query,
            "limit": 1
        }
        
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(self.base_url, params=params, headers=self.headers)
                resp.raise_for_status()
                data = resp.json()

                if not data or "features" not in data or not data["features"]:
                    raise GeocodingAPIError(f"No results found for query: {query}")
                
                # Photon returns [lon, lat] in coordinates
                coords = data["features"][0]["geometry"]["coordinates"]
                lon = float(coords[0])
                lat = float(coords[1])
                
                logger.info(f"Geocoded '{query}' -> ({lat}, {lon})")
                return Coordinate(latitude=lat, longitude=lon)

        except httpx.RequestError as e:
            logger.error(f"Geocoding request failed: {e}")
            raise GeocodingAPIError(f"Failed to communicate with Geocoding API: {e}")
        except (KeyError, ValueError, IndexError) as e:
            logger.error(f"Geocoding data extraction failed: {e}")
            raise GeocodingAPIError(f"Failed to parse Geocoding API response: {e}")
