from __future__ import annotations

import json
import sys
import shutil
import uuid
from pathlib import Path
from collections.abc import Iterator

import pytest

from tools import download_sources, license_audit, verify_release_artifacts


@pytest.fixture
def scratch_path() -> Iterator[Path]:
    path = Path("build/packaging-tests") / uuid.uuid4().hex
    path.mkdir(parents=True)
    try:
        yield path
    finally:
        shutil.rmtree(path)


def test_development_candidate_runs_complete_artifact_gate(monkeypatch: pytest.MonkeyPatch) -> None:
    checked = []
    monkeypatch.setattr(sys, "argv", [
        "verify_release_artifacts.py", "--directory", "build/candidate",
        "--version", "0.1.0.dev42",
    ])
    monkeypatch.setattr(
        verify_release_artifacts, "verify_binary",
        lambda path, target, version: checked.append((target, version)),
    )
    monkeypatch.setattr(
        verify_release_artifacts, "verify_sources",
        lambda path, version: checked.append(("sources", version)),
    )
    assert verify_release_artifacts.main() == 0
    assert checked == [
        (target, "0.1.0.dev42") for target in verify_release_artifacts.TARGETS
    ] + [("sources", "0.1.0.dev42")]


def test_source_collection_accepts_development_candidate(
    monkeypatch: pytest.MonkeyPatch, scratch_path: Path,
) -> None:
    monkeypatch.setattr(sys, "argv", ["download_sources.py", "0.1.0.dev42"])
    monkeypatch.setattr(download_sources, "ROOT", scratch_path)
    monkeypatch.setattr(
        download_sources.metadata, "distribution",
        lambda name: type("Distribution", (), {"version": "wrong"})(),
    )
    with pytest.raises(RuntimeError, match="does not match corresponding-source"):
        download_sources.main()
    assert (scratch_path / "build/source-materials/0.1.0.dev42").is_dir()


def test_qt_filename_alone_is_not_license_provenance(
    scratch_path: Path,
) -> None:
    (scratch_path / "QtUnowned.so").write_bytes(b"unowned native file")
    codec = scratch_path / "libavcodec.so.59.37.100"
    codec.write_bytes(b"wheel native")
    (scratch_path / "system-dependencies.json").write_text(json.dumps({
        "bundled_source_provenance": [],
    }), encoding="utf-8")
    inventory = {
        "distributions": [{"name": "opencv-python-headless", "native_files": [
            {"path": codec.name, "sha256": license_audit.sha256(codec)},
        ]}],
        "version": "0.1.0.dev42", "target": "linux-x64",
    }
    with pytest.raises(RuntimeError, match="Native files have no known.*QtUnowned"):
        license_audit.inventory_bundle(scratch_path, inventory)
