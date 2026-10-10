from __future__ import annotations

from dataclasses import dataclass, field
from typing import TypeAlias
from uuid import uuid4

Point: TypeAlias = tuple[float, float]
Corners: TypeAlias = tuple[Point, Point, Point, Point]

class OperationCancelled(Exception):
    """Raised at a processing-stage boundary when cancellation was requested."""


@dataclass(frozen=True)
class PhotoBoundary:
    corners: Corners
    confidence: float = 1.0
    selected: bool = True
    needs_review: bool = False
    user_confirmed: bool = False
    boundary_id: str = field(default_factory=lambda: str(uuid4()))

    def with_corners(self, corners: Corners) -> PhotoBoundary:
        return PhotoBoundary(
            corners=corners,
            confidence=1.0,
            selected=self.selected,
            needs_review=False,
            user_confirmed=True,
            boundary_id=self.boundary_id,
        )

    def confirmed(self) -> PhotoBoundary:
        return PhotoBoundary(
            corners=self.corners,
            confidence=self.confidence,
            selected=self.selected,
            needs_review=False,
            user_confirmed=True,
            boundary_id=self.boundary_id,
        )


@dataclass(frozen=True)
class DetectionSuccess:
    boundaries: tuple[PhotoBoundary, ...]
    diagnostics: tuple[str, ...] = ()
    status: str = field(default="success", init=False)


@dataclass(frozen=True)
class AmbiguousDetections:
    boundaries: tuple[PhotoBoundary, ...]
    reason: str
    diagnostics: tuple[str, ...] = ()
    status: str = field(default="ambiguous", init=False)


@dataclass(frozen=True)
class NoDetections:
    reason: str
    diagnostics: tuple[str, ...] = ()
    status: str = field(default="no_detections", init=False)


@dataclass(frozen=True)
class DetectionFailure:
    reason: str
    diagnostics: tuple[str, ...] = ()
    status: str = field(default="failure", init=False)


DetectionOutcome: TypeAlias = (
    DetectionSuccess | AmbiguousDetections | NoDetections | DetectionFailure
)
