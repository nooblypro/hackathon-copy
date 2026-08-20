"""
Pitstop schemas.
"""
from __future__ import annotations
from typing import Optional

from pydantic import BaseModel, Field


class Pitstop(BaseModel):
    """A pitstop (place) relevant to the user's route."""

    place_id: str = Field(default="", description="Google Place ID or internal ID")
    name: str = Field(..., description="Place name")
    category: str = Field(..., description="Category: restroom | pharmacy | hospital | fuel | ev_charging | cafe | rest_area")
    latitude: float = Field(..., description="Latitude")
    longitude: float = Field(..., description="Longitude")
    distance_from_route_meters: float = Field(default=0.0, description="Distance from nearest route point")
    rating: Optional[float] = Field(default=None, description="User rating if available")
    accessibility_info: Optional[str] = Field(
        default=None,
        description="Accessibility information if available from API. null = unavailable.",
    )
    source: str = Field(default="google", description="Data source: google | demo")


class PitstopSearchRequest(BaseModel):
    """Request body for pitstop search endpoint."""

    latitude: float = Field(..., description="Search center latitude")
    longitude: float = Field(..., description="Search center longitude")
    categories: list[str] = Field(
        default=["cafe"],
        description="Categories to search: restroom | pharmacy | hospital | fuel | ev_charging | cafe | rest_area",
    )
    radius_meters: float = Field(default=1000.0, ge=100, le=5000, description="Search radius in meters")
