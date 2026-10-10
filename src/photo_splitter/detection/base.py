from __future__ import annotations

from typing import Protocol

import numpy as np

from photo_splitter.domain import DetectionOutcome


class PhotoDetector(Protocol):
    def detect(self, image: np.ndarray, threshold: int = 18) -> DetectionOutcome: ...
