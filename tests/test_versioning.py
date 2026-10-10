from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from photo_splitter.version import DEVELOPMENT_VERSION, __version__, validate_version


ROOT = Path(__file__).resolve().parents[1]


def test_development_version_is_valid_and_shared_with_project_metadata() -> None:
    assert DEVELOPMENT_VERSION == "0.1.0.dev0"
    assert validate_version(__version__) == __version__

    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import importlib.metadata as m; print(m.version('photo-splitter'))",
        ],
        cwd=ROOT,
        env={**os.environ, "PYTHONPATH": str(ROOT / "src")},
        check=True,
        capture_output=True,
        text=True,
    )
    assert result.stdout.strip() == __version__


@pytest.mark.parametrize(
    "value",
    ["1.2.3", "0.0.1", "20.4.0", "1.2.3.dev0", "1.2.3.dev42"],
)
def test_version_validation_accepts_release_and_development_versions(value: str) -> None:
    assert validate_version(value) == value


@pytest.mark.parametrize(
    "value",
    ["v1.2.3", "1.2", "01.2.3", "1.2.3rc1", "1.2.3.dev-1", "../1.2.3", ""],
)
def test_version_validation_rejects_unexpected_versions(value: str) -> None:
    with pytest.raises(ValueError):
        validate_version(value)


def test_release_tag_must_be_valid_and_match_candidate() -> None:
    result = subprocess.run(
        [sys.executable, "tools/release.py", "validate-tag", "--tag", "v2.4.1"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    assert result.stdout.strip() == "2.4.1"

    rejected = subprocess.run(
        [sys.executable, "tools/release.py", "validate-tag", "--tag", "v2.4.1", "--candidate", "2.4.0"],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert rejected.returncode != 0
