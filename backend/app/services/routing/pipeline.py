"""
Route planning pipeline orchestrator.
Integrates: challenge parsing → routing → traffic → hazards → places → scoring → ranking → recommendation.
"""
from __future__ import annotations
from typing import Optional

import uuid

import polyline as polyline_lib  # type: ignore

from app.core.config import get_settings
from app.core.errors import PitstopAPIError, RouteNotFoundError, RoutingAPIError
from app.core.logging import get_logger
from app.schemas.challenges import RoutePlanRequest
from app.schemas.constraints import ConstraintProfile
from app.schemas.routes import (
    ChallengeInfo,
    Recommendation,
    ResponseMetadata,
    RouteCandidate,
    RoutePlanResponse,
    TrafficInfo,
)
from app.services.hazards.service import HazardAnalysisService
from app.services.llm.service import ChallengeParserService, create_llm_provider
from app.services.places.service import PlacesService
from app.services.routing.demo import generate_demo_response
from app.services.routing.service import RoutingService
from app.services.scoring.service import RouteScoringService

logger = get_logger("pipeline")


class RoutePlanningPipeline:
    """
    Orchestrates the complete route planning pipeline.
    Each step is explicit and logged.
    """

    def __init__(self):
        self.settings = get_settings()
        self.hazard_service = HazardAnalysisService()
        self.scoring_service = RouteScoringService()
        self.routing_service = RoutingService()
        self.places_service = PlacesService()

        # Create LLM provider
        provider = create_llm_provider()
        self.parser_service = ChallengeParserService(provider)

    async def plan(self, request: RoutePlanRequest, base_constraints: Optional[ConstraintProfile] = None) -> RoutePlanResponse:
        """
        Execute the full pipeline:
        1. Validate request
        2. Parse challenge → constraints
        3. Get route candidates
        4. Analyze traffic
        5. Analyze hazards
        6. Find pitstops
        7. Apply hard constraint filter
        8. Score routes
        9. Rank routes
        10. Generate recommendation
        11. Return explainable response
        """
        request_id = f"req_{uuid.uuid4().hex[:12]}"
        metadata = ResponseMetadata()

        # ── Step 1: Parse challenge ──
        logger.info("[%s] Step 1: Parsing challenge", request_id)
        constraints, parser_source = await self.parser_service.parse(request.challenge_text)
        
        if base_constraints:
            from app.schemas.constraints import MobilityLevel, Priority, DrivingExperience
            # Merge boolean flags
            for field in base_constraints.model_fields:
                val = getattr(base_constraints, field)
                if isinstance(val, bool) and val:
                    setattr(constraints, field, True)
            # Merge enums if non-default
            if base_constraints.mobility_level != MobilityLevel.FULL:
                constraints.mobility_level = base_constraints.mobility_level
            if base_constraints.priority != Priority.BALANCED:
                constraints.priority = base_constraints.priority
            if base_constraints.driving_experience != DrivingExperience.EXPERIENCED:
                constraints.driving_experience = base_constraints.driving_experience

        metadata.parser_source = parser_source
        logger.info("[%s] Parser source: %s, priority: %s", request_id, parser_source, constraints.priority)

        # ── Step 2: Get route candidates from Ola Maps ──
        logger.info("[%s] Step 2: Fetching route candidates", request_id)
        try:
            raw_routes = await self.routing_service.get_routes(
                request.origin.latitude,
                request.origin.longitude,
                request.destination.latitude,
                request.destination.longitude,
                constraints,
            )
            metadata.routing_source = "ola_maps"
            metadata.traffic_source = "unavailable"
        except RoutingAPIError as e:
            logger.error("[%s] Ola Maps API unavailable: %s", request_id, e)
            raise RouteNotFoundError(request_id=request_id)

        if not raw_routes:
            raise RouteNotFoundError(request_id=request_id)

        # ── Step 3: Parse routes ──
        logger.info("[%s] Step 3: Parsing %d route(s)", request_id, len(raw_routes))
        parsed_routes = []
        for i, raw in enumerate(raw_routes):
            parsed = RoutingService.parse_osrm_route(raw, i)
            parsed_routes.append(parsed)

        # ── Step 4: Analyze hazards for each route ──
        logger.info("[%s] Step 4: Hazard analysis", request_id)
        metadata.hazard_source = "demo"  # Our hazards are seeded demo data
        route_hazards = []
        for parsed in parsed_routes:
            if parsed["polyline"]:
                try:
                    points = polyline_lib.decode(parsed["polyline"])
                    hazards = self.hazard_service.analyze_route(points)
                except Exception as e:  # noqa: BLE001
                    logger.warning("[%s] Polyline decode failed: %s", request_id, e)
                    hazards = []
            else:
                hazards = []
            route_hazards.append(hazards)

        # ── Step 5: Check pitstop needs ──
        logger.info("[%s] Step 5: Pitstop search", request_id)
        needed_categories = _get_needed_categories(constraints)
        pitstop_needed = bool(needed_categories)
        route_pitstops: list[list] = []

        if pitstop_needed:
            for parsed in parsed_routes:
                # Search near route midpoint
                if parsed["polyline"]:
                    try:
                        points = polyline_lib.decode(parsed["polyline"])
                        mid = points[len(points) // 2]
                        pitstops = await self.places_service.search_nearby(
                            mid[0], mid[1], needed_categories, radius_meters=1500
                        )
                    except (PitstopAPIError, Exception) as e:  # noqa: BLE001
                        logger.warning("[%s] Places search failed: %s", request_id, e)
                        pitstops = []
                else:
                    pitstops = []
                route_pitstops.append(pitstops)
                metadata.places_source = "overpass"
        else:
            route_pitstops = [[] for _ in parsed_routes]
            metadata.places_source = "unavailable" if pitstop_needed else "not_needed"

        # ── Step 6: Hard constraint filter ──
        logger.info("[%s] Step 6: Hard constraint filter", request_id)
        viable_indices: list[int] = []
        filter_reasons: dict[int, list[str]] = {}

        for i, hazards in enumerate(route_hazards):
            violated, reasons = self.hazard_service.has_hard_constraint_violation(
                hazards,
                avoid_roadblocks=constraints.avoid_roadblocks,
                avoid_unpaved=constraints.avoid_unpaved,
                avoid_potholes=constraints.avoid_potholes,
            )
            if violated:
                filter_reasons[i] = reasons
                logger.info("[%s] Route %d filtered: %s", request_id, i, reasons)
            else:
                viable_indices.append(i)

        # If all routes filtered, use all but add warnings
        if not viable_indices:
            logger.warning("[%s] All routes have hard constraint violations — using all with warnings", request_id)
            viable_indices = list(range(len(parsed_routes)))

        # ── Step 7: Score routes ──
        logger.info("[%s] Step 7: Scoring %d viable route(s)", request_id, len(viable_indices))
        durations = [parsed_routes[i]["duration_seconds"] for i in viable_indices]
        min_dur = min(durations) if durations else 0
        max_dur = max(durations) if durations else 0

        candidates: list[RouteCandidate] = []
        for idx in viable_indices:
            parsed = parsed_routes[idx]
            hazards = route_hazards[idx]
            pitstops = route_pitstops[idx] if idx < len(route_pitstops) else []

            traffic_delay = parsed.get("traffic_delay_seconds")
            traffic_avail = traffic_delay is not None

            scores = self.scoring_service.score_route(
                constraints=constraints,
                duration_seconds=parsed["duration_seconds"],
                distance_meters=parsed["distance_meters"],
                min_duration=min_dur,
                max_duration=max_dur,
                hazards=hazards,
                traffic_delay_seconds=traffic_delay,
                traffic_available=traffic_avail,
                has_highway=parsed.get("has_highway", False),
                pitstop_count=len(pitstops),
                pitstop_needed=pitstop_needed,
            )

            is_fastest = parsed["duration_seconds"] == min_dur
            advantages, disadvantages, warnings = self.scoring_service.generate_advantages_disadvantages(
                constraints=constraints,
                hazards=hazards,
                duration_seconds=parsed["duration_seconds"],
                min_duration=min_dur,
                traffic_delay=traffic_delay,
                traffic_available=traffic_avail,
                has_highway=parsed.get("has_highway", False),
                pitstop_count=len(pitstops),
                is_fastest=is_fastest,
            )

            # Add hard constraint violation warnings
            if idx in filter_reasons:
                for reason in filter_reasons[idx]:
                    warnings.append(f"Hard constraint violation: {reason}")

            # Determine traffic level
            traffic_level = None
            if traffic_avail and traffic_delay is not None:
                if traffic_delay <= 60:
                    traffic_level = "low"
                elif traffic_delay <= 300:
                    traffic_level = "moderate"
                elif traffic_delay <= 600:
                    traffic_level = "high"
                else:
                    traffic_level = "severe"

            candidates.append(
                RouteCandidate(
                    route_id=f"route_{idx + 1:03d}",
                    distance_meters=parsed["distance_meters"],
                    duration_seconds=parsed["duration_seconds"],
                    traffic=TrafficInfo(
                        available=traffic_avail,
                        level=traffic_level,
                        delay_seconds=traffic_delay,
                        source="ola_maps" if traffic_avail else "unavailable",
                    ),
                    scores=scores,
                    hazards=hazards,
                    pitstops=pitstops,
                    advantages=advantages,
                    disadvantages=disadvantages,
                    warnings=warnings if warnings else parsed.get("warnings", []),
                    polyline=parsed["polyline"],
                )
            )

        # ── Step 8: Rank and recommend ──
        logger.info("[%s] Step 8: Ranking and recommendation", request_id)
        candidates.sort(key=lambda c: c.scores.overall, reverse=True)

        # Label routes
        fastest_idx = min(range(len(candidates)), key=lambda i: candidates[i].duration_seconds)
        
        is_none_challenge = request.challenge_text.lower().strip() in ["none", "", "no", "nothing"]
        if is_none_challenge and len(candidates) > 1 and fastest_idx != 0:
            # Force fastest to be top recommended if challenge is "none"
            candidates.insert(0, candidates.pop(fastest_idx))
            fastest_idx = 0

        for i, c in enumerate(candidates):
            if i == 0:
                c.recommended = True
                c.label = "Recommended"
            elif i == fastest_idx:
                c.label = "Fastest"
            else:
                c.label = "Alternative"

        # Generate recommendation
        recommended = candidates[0]
        reason_parts = list(recommended.advantages[:3])
        if recommended.disadvantages:
            reason_parts.append(recommended.disadvantages[0])
        reason = ". ".join(reason_parts) + "." if reason_parts else "Best overall score based on your needs."

        recommendation = Recommendation(
            route_id=recommended.route_id,
            reason=reason,
        )

        return RoutePlanResponse(
            request_id=request_id,
            challenge=ChallengeInfo(
                raw_text=request.challenge_text,
                parsed_constraints=constraints,
            ),
            recommendation=recommendation,
            routes=candidates,
            metadata=metadata,
        )


def _get_needed_categories(constraints: ConstraintProfile) -> list[str]:
    """Determine pitstop categories needed based on constraints."""
    cats: list[str] = []
    
    has_specific_needs = (constraints.needs_rest_stops or constraints.needs_accessible_restrooms or 
                          constraints.needs_pharmacy or constraints.needs_hospital or 
                          constraints.needs_fuel or constraints.needs_ev_charging)
                          
    if constraints.needs_rest_stops:
        cats.append("cafe")
        cats.append("rest_area")
    if constraints.needs_accessible_restrooms:
        cats.append("restroom")
    if constraints.needs_pharmacy:
        cats.append("pharmacy")
    if constraints.needs_hospital:
        cats.append("hospital")
    if constraints.needs_fuel:
        cats.append("fuel")
    if constraints.needs_ev_charging:
        cats.append("ev_charging")
        
    return cats
