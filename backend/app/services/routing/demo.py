"""
Demo route pipeline.
Provides a complete deterministic demo response that works WITHOUT any external services.
Data is clearly labelled as demo/seeded.
"""
from __future__ import annotations
from typing import Optional

from app.schemas.constraints import (
    ConstraintProfile,
    DrivingExperience,
    Priority,
)
from app.schemas.hazards import (
    Hazard,
    HazardOnRoute,
    HazardSeverity,
    HazardStatus,
    HazardType,
)
from app.schemas.pitstops import Pitstop
from app.schemas.routes import (
    ChallengeInfo,
    Recommendation,
    ResponseMetadata,
    RouteCandidate,
    RoutePlanResponse,
    RouteScores,
    TrafficInfo,
)


def generate_demo_response(
    challenge_text: str = "I'm a new driver and highways make me nervous.",
    constraints: Optional[ConstraintProfile] = None,
) -> RoutePlanResponse:
    """
    Generate a complete deterministic demo response.
    Demonstrates the full concept with realistic Chennai-area data.
    ALL data is clearly labelled as demo.
    """
    if constraints is None:
        constraints = ConstraintProfile(
            avoid_highways=True,
            avoid_heavy_merges=True,
            avoid_complex_intersections=True,
            driving_experience=DrivingExperience.LEARNER,
            priority=Priority.SAFETY,
            confidence=0.85,
            reasoning_summary="User is a new driver who is nervous about highways.",
        )

    # --- Route A: Fastest, highway route with issues ---
    route_a_hazards = [
        HazardOnRoute(
            hazard=Hazard(
                id="HZ-001",
                type=HazardType.POTHOLE,
                severity=HazardSeverity.HIGH,
                latitude=13.0580,
                longitude=80.2490,
                radius_meters=35,
                description="Large pothole on Inner Ring Road near Kotturpuram",
                confidence=0.91,
                reported_at="2026-08-18T10:30:00Z",
                status=HazardStatus.ACTIVE,
            ),
            distance_from_route_meters=12.3,
            penalty=13.65,
        ),
        HazardOnRoute(
            hazard=Hazard(
                id="HZ-002",
                type=HazardType.POTHOLE,
                severity=HazardSeverity.MEDIUM,
                latitude=13.0720,
                longitude=80.2510,
                radius_meters=20,
                description="Medium pothole near Teynampet junction",
                confidence=0.78,
                reported_at="2026-08-17T14:15:00Z",
                status=HazardStatus.ACTIVE,
            ),
            distance_from_route_meters=45.7,
            penalty=5.46,
        ),
    ]

    route_a = RouteCandidate(
        route_id="route_001",
        label="Fastest",
        recommended=False,
        distance_meters=8200,
        duration_seconds=1380,
        traffic=TrafficInfo(
            available=True,
            level="high",
            delay_seconds=360,
            source="demo",
        ),
        scores=RouteScores(
            overall=58.2,
            safety=52.0,
            accessibility=65.0,
            comfort=45.0,
            traffic=60.0,
            convenience=70.0,
            time=95.0,
        ),
        hazards=route_a_hazards,
        pitstops=[],
        advantages=["Fastest route"],
        disadvantages=[
            "Route includes highway segment(s)",
            "2 pothole report(s) along route",
            "Heavy traffic (6 min delay)",
        ],
        warnings=["Highway merge required — may be challenging for new drivers"],
        polyline="m~nAa`x~MtBbCxDfEhCpBzAlAnB~BjCzCnBrBp@r@",
    )

    # --- Route B: Recommended, avoids highway ---
    route_b_pitstops = [
        Pitstop(
            place_id="demo_cafe_001",
            name="Adyar Ananda Bhavan (T. Nagar)",
            category="cafe",
            latitude=13.0401,
            longitude=80.2339,
            rating=4.3,
            accessibility_info=None,
            source="demo",
        ),
    ]

    route_b = RouteCandidate(
        route_id="route_002",
        label="Recommended",
        recommended=True,
        distance_meters=9100,
        duration_seconds=1620,
        traffic=TrafficInfo(
            available=True,
            level="moderate",
            delay_seconds=120,
            source="demo",
        ),
        scores=RouteScores(
            overall=91.5,
            safety=96.0,
            accessibility=92.0,
            comfort=94.0,
            traffic=85.0,
            convenience=82.0,
            time=78.0,
        ),
        hazards=[],
        pitstops=route_b_pitstops,
        advantages=[
            "Avoids highways",
            "No major pothole reports",
            "No active roadblocks",
            "Low traffic conditions",
            "1 relevant pitstop(s) available",
        ],
        disadvantages=[
            "4 minute(s) slower than the fastest route",
        ],
        warnings=[],
        polyline="m~nAa`x~MhA`BfBtCnCpDdBbCpAfBjBzCxAtBtAvBjBbC",
    )

    # --- Route C: Alternative, roadblock issue ---
    route_c_hazards = [
        HazardOnRoute(
            hazard=Hazard(
                id="HZ-003",
                type=HazardType.ROADBLOCK,
                severity=HazardSeverity.CRITICAL,
                latitude=13.0650,
                longitude=80.2580,
                radius_meters=100,
                description="Road closed for metro construction on Anna Salai",
                confidence=0.98,
                reported_at="2026-08-18T06:00:00Z",
                status=HazardStatus.ACTIVE,
            ),
            distance_from_route_meters=25.0,
            penalty=49.0,
        ),
    ]

    route_c = RouteCandidate(
        route_id="route_003",
        label="Alternative",
        recommended=False,
        distance_meters=8800,
        duration_seconds=1500,
        traffic=TrafficInfo(
            available=True,
            level="moderate",
            delay_seconds=180,
            source="demo",
        ),
        scores=RouteScores(
            overall=44.3,
            safety=35.0,
            accessibility=55.0,
            comfort=50.0,
            traffic=75.0,
            convenience=60.0,
            time=85.0,
        ),
        hazards=route_c_hazards,
        pitstops=[],
        advantages=[
            "No major pothole reports",
        ],
        disadvantages=[
            "2 minute(s) slower than the fastest route",
        ],
        warnings=[
            "1 active roadblock(s) on route",
        ],
        polyline="m~nAa`x~MjClDnBrCxAdBpBnCdCjDlBrC~ArBhBdC",
    )

    return RoutePlanResponse(
        request_id="demo_req_001",
        challenge=ChallengeInfo(
            raw_text=challenge_text,
            parsed_constraints=constraints,
        ),
        recommendation=Recommendation(
            route_id="route_002",
            reason="Avoids highways and difficult merges while adding only 4 minutes. No hazards detected along route. Suitable rest stop available.",
        ),
        routes=[route_a, route_b, route_c],
        metadata=ResponseMetadata(
            routing_source="demo",
            traffic_source="demo",
            places_source="demo",
            hazard_source="demo",
            parser_source="demo",
        ),
    )
