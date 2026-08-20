"""
Route schemas — candidates, scores, traffic, and the full plan response.
"""
from __future__ import annotations
from typing import Optional

from pydantic import BaseModel, Field

from .constraints import ConstraintProfile
from .hazards import HazardOnRoute
from .pitstops import Pitstop


class TrafficInfo(BaseModel):
    """Traffic information for a route."""

    available: bool = Field(default=False, description="Whether traffic data is available")
    level: Optional[str] = Field(default=None, description="Traffic level: low | moderate | high | severe")
    delay_seconds: Optional[int] = Field(default=None, description="Estimated delay vs free-flow in seconds")
    source: str = Field(default="unavailable", description="Traffic data source")


class RouteScores(BaseModel):
    """Scoring breakdown for a route. Each score is 0-100."""

    overall: float = Field(..., ge=0, le=100, description="Overall weighted score")
    safety: float = Field(..., ge=0, le=100, description="Safety score")
    accessibility: float = Field(..., ge=0, le=100, description="Accessibility score")
    comfort: float = Field(..., ge=0, le=100, description="Comfort score")
    traffic: float = Field(..., ge=0, le=100, description="Traffic score (higher = less traffic)")
    convenience: float = Field(..., ge=0, le=100, description="Convenience/pitstop score")
    time: float = Field(..., ge=0, le=100, description="Time efficiency score")


class RouteCandidate(BaseModel):
    """A single route candidate with full analysis."""

    route_id: str = Field(..., description="Unique route identifier")
    label: str = Field(default="", description="Route label: Fastest | Recommended | Alternative")
    recommended: bool = Field(default=False, description="Whether this is the recommended route")

    distance_meters: float = Field(..., ge=0, description="Total route distance in meters")
    duration_seconds: float = Field(..., ge=0, description="Estimated duration in seconds")

    traffic: TrafficInfo = Field(default_factory=TrafficInfo, description="Traffic info")
    scores: RouteScores = Field(..., description="Scoring breakdown")

    hazards: list[HazardOnRoute] = Field(default_factory=list, description="Hazards affecting this route")
    pitstops: list[Pitstop] = Field(default_factory=list, description="Relevant pitstops along route")

    advantages: list[str] = Field(default_factory=list, description="Deterministic advantage explanations")
    disadvantages: list[str] = Field(default_factory=list, description="Deterministic disadvantage explanations")
    warnings: list[str] = Field(default_factory=list, description="Route warnings")

    polyline: str = Field(default="", description="Encoded polyline for map display")


class Recommendation(BaseModel):
    """Recommendation summary."""

    route_id: str = Field(..., description="ID of the recommended route")
    reason: str = Field(..., description="Human-readable explanation of why this route is recommended")


class ChallengeInfo(BaseModel):
    """Challenge parsing info included in the plan response."""

    raw_text: str = Field(default="", description="Original user challenge text")
    parsed_constraints: ConstraintProfile = Field(
        default_factory=ConstraintProfile, description="Parsed constraints"
    )


class ResponseMetadata(BaseModel):
    """Metadata about data sources used."""

    routing_source: str = Field(default="demo", description="Routing data source: google | demo")
    traffic_source: str = Field(default="unavailable", description="Traffic data source: google | demo | unavailable")
    places_source: str = Field(default="demo", description="Places data source: google | demo")
    hazard_source: str = Field(default="demo", description="Hazard data source: demo | community")
    parser_source: str = Field(default="fallback", description="Parser source: ollama | openai | fallback")


class RoutePlanResponse(BaseModel):
    """Complete route planning response."""

    request_id: str = Field(..., description="Unique request identifier")
    challenge: ChallengeInfo = Field(default_factory=ChallengeInfo, description="Challenge parsing results")
    recommendation: Optional[Recommendation] = Field(default=None, description="Route recommendation")
    routes: list[RouteCandidate] = Field(default_factory=list, description="Evaluated route candidates")
    metadata: ResponseMetadata = Field(default_factory=ResponseMetadata, description="Data source metadata")
