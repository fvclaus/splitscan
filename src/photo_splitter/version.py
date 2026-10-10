"""Shared application and distribution version."""

from __future__ import annotations

import os
import re
import sys

DEVELOPMENT_VERSION = "0.1.0.dev0"
_VERSION_PATTERN = re.compile(
    r"(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)(?:\.dev(?:0|[1-9][0-9]*))?\Z"
)


def validate_version(value: str) -> str:
    """Return a supported PEP 440 version or reject an unsafe build value."""
    if not _VERSION_PATTERN.fullmatch(value):
        raise ValueError(
            f"Invalid SplitScan version {value!r}; expected MAJOR.MINOR.PATCH"
            " or MAJOR.MINOR.PATCH.devN"
        )
    return value


if getattr(sys, "frozen", False):
    try:
        from _splitscan_build_version import BUILD_VERSION
    except ImportError as error:
        raise RuntimeError("Frozen SplitScan build is missing its embedded version") from error
    __version__ = validate_version(BUILD_VERSION)
else:
    __version__ = validate_version(os.environ.get("SPLITSCAN_VERSION", DEVELOPMENT_VERSION))
