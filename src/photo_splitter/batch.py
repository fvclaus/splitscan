from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path


class ScanOutcome(Enum):
    EXPORTED = "exported"
    SKIPPED = "skipped"
    FAILED = "failed"


def natural_sort_key(path: Path) -> list[tuple[int, int | str]]:
    """Sort key that orders `scan-2` before `scan-10`, ignoring case."""
    return [
        (0, int(part)) if part.isdigit() else (1, part.casefold())
        for part in re.split(r"(\d+)", path.name)
        if part
    ]


@dataclass
class Batch:
    paths: tuple[Path, ...]
    index: int = 0
    outcomes: dict[int, ScanOutcome] = field(default_factory=dict)
    photos_exported: int = 0
    failures: dict[int, str] = field(default_factory=dict)

    @classmethod
    def from_paths(cls, paths: list[Path]) -> Batch:
        return cls(tuple(sorted(paths, key=natural_sort_key)))

    @property
    def current(self) -> Path:
        return self.paths[self.index]

    @property
    def total(self) -> int:
        return len(self.paths)

    @property
    def is_last(self) -> bool:
        return self.index == self.total - 1

    @property
    def remaining(self) -> int:
        return self.total - self.index - 1

    def count(self, outcome: ScanOutcome) -> int:
        return sum(value is outcome for value in self.outcomes.values())

    def outcome_of(self, index: int) -> ScanOutcome | None:
        return self.outcomes.get(index)

    def names(self, outcome: ScanOutcome) -> list[str]:
        return [
            self.paths[index].name
            for index, value in sorted(self.outcomes.items())
            if value is outcome
        ]

    def record_exported(self, photos: int) -> None:
        self.outcomes[self.index] = ScanOutcome.EXPORTED
        self.photos_exported += photos

    def record_skipped(self) -> None:
        self.outcomes[self.index] = ScanOutcome.SKIPPED

    def record_failed(self, reason: str) -> None:
        self.outcomes[self.index] = ScanOutcome.FAILED
        self.failures[self.index] = reason

    def advance(self) -> Path | None:
        if self.is_last:
            return None
        self.index += 1
        return self.current
