"""
Route scoring engine.
Deterministic, explainable, configurable scoring.
"""
from __future__ import annotations
from typing import Optional

from dataclasses import dataclass

from app.core.logging import get_logger
from app.schemas.constraints import (
    ConstraintProfile,
    DrivingExperience,
    MobilityLevel,
    Priority,
)
from app.schemas.hazards import HazardOnRoute, HazardType
from app.schemas.routes import RouteScores

logger = get_logger("scoring")


@dataclass
class ScoringWeights:
    """Configurable scoring weights. Must sum to 1.0."""
    safety: float = 0.30
    accessibility: float = 0.25
    comfort: float = 0.20
    traffic: float = 0.15
    convenience: float = 0.05
    time: float = 0.05

    def validate(self) -> None:
        total = self.safety + self.accessibility + self.comfort + self.traffic + self.convenience + self.time
        if abs(total - 1.0) > 0.01:
            raise ValueError(f"Scoring weights must sum to 1.0, got {total:.4f}")

    def as_dict(self) -> dict[str, float]:
        return {
            "safety": self.safety,
            "accessibility": self.accessibility,
            "comfort": self.comfort,
            "traffic": self.traffic,
            "convenience": self.convenience,
            "time": self.time,
        }


def adjust_weights_for_profile(constraints: ConstraintProfile) -> ScoringWeights:
    """
    Adjust scoring weights based on user's constraint profile.
    Returns a new ScoringWeights instance.
    """
    w = ScoringWeights()

    # --- Priority-based adjustment ---
    if constraints.priority == Priority.SPEED:
        w.time = 0.35
        w.safety = 0.20
        w.accessibility = 0.15
        w.comfort = 0.15
        w.traffic = 0.10
        w.convenience = 0.05

    elif constraints.priority == Priority.SAFETY:
        w.safety = 0.40
        w.accessibility = 0.20
        w.comfort = 0.20
        w.traffic = 0.10
        w.convenience = 0.05
        w.time = 0.05

    elif constraints.priority == Priority.ACCESSIBILITY:
        w.accessibility = 0.35
        w.safety = 0.25
        w.comfort = 0.20
        w.traffic = 0.10
        w.convenience = 0.05
        w.time = 0.05

    elif constraints.priority == Priority.COMFORT:
        w.comfort = 0.30
        w.safety = 0.25
        w.accessibility = 0.20
        w.traffic = 0.15
        w.convenience = 0.05
        w.time = 0.05

    # --- Learner/new driver profile ---
    if constraints.driving_experience in (DrivingExperience.LEARNER, DrivingExperience.BEGINNER):
        w.safety = max(w.safety, 0.35)
        w.comfort += 0.05
        w.time = max(0.03, w.time - 0.05)
        # Renormalize
        _normalize(w)

    # --- Mobility profile ---
    if constraints.mobility_level in (MobilityLevel.LIMITED, MobilityLevel.WHEELCHAIR):
        w.accessibility = max(w.accessibility, 0.35)
        w.comfort = max(w.comfort, 0.20)
        w.time = max(0.03, w.time - 0.05)
        _normalize(w)

    w.validate()
    return w


def _normalize(w: ScoringWeights) -> None:
    """Normalize weights to sum to 1.0."""
    total = w.safety + w.accessibility + w.comfort + w.traffic + w.convenience + w.time
    if total > 0:
        w.safety /= total
        w.accessibility /= total
        w.comfort /= total
        w.traffic /= total
        w.convenience /= total
        w.time /= total


class RouteScoringService:
    """Scores route candidates based on constraints and route data."""

    def score_route(
        self,
        *,
        constraints: ConstraintProfile,
        duration_seconds: float,
        distance_meters: float,
        min_duration: float,
        max_duration: float,
        hazards: list[HazardOnRoute],
        traffic_delay_seconds: Optional[int],
        traffic_available: bool,
        has_highway: bool = False,
        pitstop_count: int = 0,
        pitstop_needed: bool = False,
    ) -> RouteScores:
        """
        Compute deterministic scores for a single route candidate.
        All scores are 0-100 (higher = better).
        """
        weights = adjust_weights_for_profile(constraints)

        safety = self._score_safety(hazards, constraints)
        accessibility = self._score_accessibility(hazards, constraints)
        comfort = self._score_comfort(hazards, has_highway, traffic_delay_seconds, constraints)
        traffic = self._score_traffic(traffic_delay_seconds, traffic_available)
        convenience = self._score_convenience(pitstop_count, pitstop_needed, constraints)
        time_score = self._score_time(duration_seconds, min_duration, max_duration)

        overall = (
            safety * weights.safety
            + accessibility * weights.accessibility
            + comfort * weights.comfort
            + traffic * weights.traffic
            + convenience * weights.convenience
            + time_score * weights.time
        )

        return RouteScores(
            overall=round(overall, 1),
            safety=round(safety, 1),
            accessibility=round(accessibility, 1),
            comfort=round(comfort, 1),
            traffic=round(traffic, 1),
            convenience=round(convenience, 1),
            time=round(time_score, 1),
        )

    def _score_safety(self, hazards: list[HazardOnRoute], constraints: ConstraintProfile) -> float:
        """Score safety based on hazard penalties."""
        score = 100.0
        for hor in hazards:
            penalty = hor.penalty
            # Extra penalty for hazard types the user specifically avoids
            if constraints.avoid_potholes and hor.hazard.type == HazardType.POTHOLE:
                penalty *= 1.5
            if constraints.avoid_roadblocks and hor.hazard.type == HazardType.ROADBLOCK:
                penalty *= 2.0
            score -= penalty
        return max(0.0, min(100.0, score))

    def _score_accessibility(self, hazards: list[HazardOnRoute], constraints: ConstraintProfile) -> float:
        """Score accessibility based on unpaved segments, potholes, and mobility needs."""
        score = 100.0
        for hor in hazards:
            if hor.hazard.type in (HazardType.UNPAVED_SEGMENT, HazardType.POTHOLE):
                penalty = hor.penalty
                if constraints.mobility_level in (MobilityLevel.LIMITED, MobilityLevel.WHEELCHAIR):
                    penalty *= 2.0
                score -= penalty
            if hor.hazard.type == HazardType.CONSTRUCTION:
                score -= hor.penalty * 0.5
        return max(0.0, min(100.0, score))

    def _score_comfort(
        self,
        hazards: list[HazardOnRoute],
        has_highway: bool,
        traffic_delay: Optional[int],
        constraints: ConstraintProfile,
    ) -> float:
        """Score comfort based on road quality, highway avoidance, and traffic."""
        score = 100.0
        # Hazard discomfort
        for hor in hazards:
            score -= hor.penalty * 0.3

        # Highway discomfort for learners
        if has_highway and constraints.driving_experience in (
            DrivingExperience.LEARNER,
            DrivingExperience.BEGINNER,
        ):
            score -= 20

        if has_highway and constraints.avoid_highways:
            score -= 25

        # Traffic discomfort
        if traffic_delay is not None and traffic_delay > 300:
            score -= min(20, traffic_delay / 60)

        return max(0.0, min(100.0, score))

    def _score_traffic(self, traffic_delay: Optional[int], traffic_available: bool) -> float:
        """Score traffic: lower delay = higher score."""
        if not traffic_available or traffic_delay is None:
            return 70.0  # Neutral when unknown
        if traffic_delay <= 0:
            return 100.0
        if traffic_delay <= 60:
            return 95.0
        if traffic_delay <= 180:
            return 85.0
        if traffic_delay <= 300:
            return 75.0
        if traffic_delay <= 600:
            return 60.0
        return max(30.0, 100.0 - traffic_delay / 10)

    def _score_convenience(self, pitstop_count: int, pitstop_needed: bool, constraints: ConstraintProfile) -> float:
        """Score convenience based on pitstop availability."""
        if not pitstop_needed:
            return 85.0  # No pitstops needed, baseline is fine
        if pitstop_count == 0:
            return 40.0  # Needed but not found
        if pitstop_count >= 3:
            return 100.0
        if pitstop_count >= 1:
            return 80.0
        return 60.0

    def _score_time(self, duration: float, min_duration: float, max_duration: float) -> float:
        """Score time efficiency: faster routes score higher."""
        if max_duration <= min_duration:
            return 90.0  # All routes equal
        # Linear scaling: fastest = 100, slowest = 50
        ratio = (duration - min_duration) / (max_duration - min_duration)
        return max(50.0, 100.0 - ratio * 50.0)

    def generate_advantages_disadvantages(
        self,
        *,
        constraints: ConstraintProfile,
        hazards: list[HazardOnRoute],
        duration_seconds: float,
        min_duration: float,
        traffic_delay: Optional[int],
        traffic_available: bool,
        has_highway: bool,
        pitstop_count: int,
        is_fastest: bool,
    ) -> tuple[list[str], list[str], list[str]]:
        """
        Generate deterministic advantage/disadvantage/warning lists from actual data.
        The LLM does NOT generate these.
        """
        advantages: list[str] = []
        disadvantages: list[str] = []
        warnings: list[str] = []

        # --- Hazard analysis ---
        pothole_count = sum(1 for h in hazards if h.hazard.type == HazardType.POTHOLE)
        roadblock_count = sum(1 for h in hazards if h.hazard.type == HazardType.ROADBLOCK)
        construction_count = sum(1 for h in hazards if h.hazard.type == HazardType.CONSTRUCTION)
        unpaved_count = sum(1 for h in hazards if h.hazard.type == HazardType.UNPAVED_SEGMENT)

        if pothole_count == 0:
            advantages.append("No major pothole reports")
        else:
            disadvantages.append(f"{pothole_count} pothole report(s) along route")

        if roadblock_count == 0:
            advantages.append("No active roadblocks")
        else:
            warnings.append(f"{roadblock_count} active roadblock(s) on route")

        if construction_count > 0:
            disadvantages.append(f"{construction_count} construction zone(s)")

        if unpaved_count == 0 and constraints.avoid_unpaved:
            advantages.append("No unpaved road segments")
        elif unpaved_count > 0:
            disadvantages.append(f"{unpaved_count} unpaved road segment(s)")

        # --- Highway ---
        if not has_highway and constraints.avoid_highways:
            advantages.append("Avoids highways")
        elif has_highway and constraints.avoid_highways:
            disadvantages.append("Route includes highway segment(s)")

        # --- Traffic ---
        if traffic_available and traffic_delay is not None:
            if traffic_delay <= 60:
                advantages.append("Low traffic conditions")
            elif traffic_delay <= 300:
                pass  # Moderate, neutral
            else:
                disadvantages.append(f"Heavy traffic ({traffic_delay // 60} min delay)")

        # --- Time ---
        if is_fastest:
            advantages.append("Fastest route")
        elif min_duration > 0:
            extra = duration_seconds - min_duration
            if extra > 0:
                minutes = round(extra / 60)
                if minutes > 0:
                    disadvantages.append(f"{minutes} minute(s) slower than the fastest route")

        # --- Pitstops ---
        if pitstop_count > 0:
            advantages.append(f"{pitstop_count} relevant pitstop(s) available")

        return advantages, disadvantages, warnings
