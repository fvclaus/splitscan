from __future__ import annotations

import json
import sys
import shutil
import uuid
import stat
import zipfile
import subprocess
from pathlib import Path
from collections.abc import Iterator

import pytest

from tools import download_sources, license_audit, verify_release_artifacts
from tools.build_mac_opencv import validate_image_only_build


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


def test_mac_rejects_live_ci_gpl_ffmpeg_build() -> None:
    with pytest.raises(RuntimeError, match="exclude the videoio module"):
        validate_image_only_build(
            "    To be built: core imgproc imgcodecs python3 videoio\n"
            "    FFMPEG: YES\n"
            "    avcodec: YES (61.19.100)\n"
            "    Extra dependencies: /opt/homebrew/Cellar/ffmpeg/7.1_3/lib/libavcodec.dylib\n"
        )


def test_mac_accepts_image_only_build() -> None:
    validate_image_only_build(
        "    To be built: core imgcodecs imgproc python3\n"
        "    Unavailable: videoio\n"
    )


def test_mac_rejects_ffmpeg_linkage(
    monkeypatch: pytest.MonkeyPatch, scratch_path: Path,
) -> None:
    library = scratch_path / "cv2.so"
    library.write_bytes(b"native")
    monkeypatch.setattr(license_audit.subprocess, "run", lambda *args, **kwargs: type(
        "Result", (), {"stdout":
            "cv2.so:\n\t@loader_path/libavcodec.61.dylib (compatibility version 61.0.0)\n"}
    )())
    with pytest.raises(RuntimeError, match="forbidden FFmpeg/Homebrew"):
        license_audit.native_linkage(scratch_path, [library], "macos-arm64")


def test_archive_native_checksum_follows_framework_symlink(tmp_path):
    path = tmp_path / "bundle.zip"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("SplitScan.app/QtCore/Versions/A/QtCore", b"native bytes")
        current = zipfile.ZipInfo("SplitScan.app/QtCore/Versions/Current")
        current.create_system = 3
        current.external_attr = (stat.S_IFLNK | 0o777) << 16
        archive.writestr(current, "A")
        link = zipfile.ZipInfo("SplitScan.app/QtCore/QtCore")
        link.create_system = 3
        link.external_attr = (stat.S_IFLNK | 0o777) << 16
        archive.writestr(link, "Versions/Current/QtCore")
    with zipfile.ZipFile(path) as archive:
        assert verify_release_artifacts.archive_file_bytes(
            archive, "SplitScan.app/QtCore/QtCore", "SplitScan.app"
        ) == b"native bytes"


@pytest.mark.parametrize("target", ["../../private", "/private", "link"])
def test_archive_checksum_rejects_escaping_or_cyclic_links(tmp_path, target):
    path = tmp_path / "bundle.zip"
    with zipfile.ZipFile(path, "w") as archive:
        link = zipfile.ZipInfo("SplitScan.app/link")
        link.create_system = 3
        link.external_attr = (stat.S_IFLNK | 0o777) << 16
        archive.writestr(link, target)
    with zipfile.ZipFile(path) as archive:
        with pytest.raises(RuntimeError, match="symlink"):
            verify_release_artifacts.archive_file_bytes(archive, "SplitScan.app/link", "SplitScan.app")


def test_release_verifier_runs_as_standalone_script(tmp_path):
    result = subprocess.run(
        [sys.executable, str(Path(verify_release_artifacts.__file__).resolve()), "--help"],
        cwd=tmp_path, capture_output=True, text=True, check=True,
    )
    assert "--version" in result.stdout
