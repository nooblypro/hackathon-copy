import httpx
from typing import Optional
from app.schemas.coordinates import Coordinate
from app.core.logging import get_logger
from app.core.config import get_settings

logger = get_logger("geocoding")

class GeocodingAPIError(Exception):
    pass

class GeocodingService:
    """Service to convert place names and addresses to coordinates using Ola Maps API."""

    def __init__(self):
        self.settings = get_settings()
        self.base_url = "https://api.olamaps.io/places/v1/geocode"
        self.api_key = self.settings.ola_maps_api_key

    async def geocode(self, query: str) -> Coordinate:
        """Geocode a text query to a Coordinate. Raises GeocodingAPIError if not found."""
        if not query or not query.strip():
            raise GeocodingAPIError("Empty geocoding query")
            
        if not self.api_key:
            logger.warning("Ola Maps API key not configured. Falling back to Photon.")
            return await self._fallback_geocode(query)

        search_query = query
        if "india" not in query.lower():
            search_query = f"{query}, India"

        params = {
            "address": search_query,
            "api_key": self.api_key
        }
        
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(self.base_url, params=params)
                resp.raise_for_status()
                data = resp.json()

                if data.get("status") != "ok" or not data.get("geocodingResults"):
                    logger.warning(f"Ola Maps geocoding returned no results for: {query}. Trying fallback.")
                    return await self._fallback_geocode(query)
                
                # Ola Maps returns geometry.location.lat / lng
                location = data["geocodingResults"][0]["geometry"]["location"]
                lat = float(location["lat"])
                lon = float(location["lng"])
                
                logger.info(f"Geocoded (Ola) '{query}' -> ({lat}, {lon})")
                return Coordinate(latitude=lat, longitude=lon)

        except httpx.RequestError as e:
            logger.error(f"Geocoding request failed: {e}")
            raise GeocodingAPIError(f"Failed to communicate with Ola Maps Geocoding API: {e}")
        except (KeyError, ValueError, IndexError) as e:
            logger.error(f"Geocoding data extraction failed: {e}")
            raise GeocodingAPIError(f"Failed to parse Ola Maps response: {e}")
            
    async def _fallback_geocode(self, query: str) -> Coordinate:
        """Fallback to Photon if Ola Maps fails or key is missing."""
        fallback_url = "https://photon.komoot.io/api/"
        search_query = f"{query}, India" if "india" not in query.lower() else query
        
        try:
            # Photon requires a custom user-agent, otherwise it returns 403 Forbidden
            headers = {"User-Agent": "RouteEase/1.0 (hackathon)"}
            async with httpx.AsyncClient(timeout=10.0, headers=headers) as client:
                resp = await client.get(fallback_url, params={"q": search_query, "limit": 1})
                resp.raise_for_status()
                data = resp.json()

                if not data or "features" not in data or not data["features"]:
                    raise GeocodingAPIError(f"No results found for query: {query}")
                
                coords = data["features"][0]["geometry"]["coordinates"]
                lon = float(coords[0])
                lat = float(coords[1])
                
                logger.info(f"Geocoded (Photon Fallback) '{query}' -> ({lat}, {lon})")
                return Coordinate(latitude=lat, longitude=lon)
        except Exception as e:
            logger.error(f"Fallback geocoding failed: {e}")
            raise GeocodingAPIError(f"Failed geocoding for: {query}")
