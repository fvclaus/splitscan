#!/usr/bin/env python3
"""Fetch version-matched corresponding source archives for a release."""

from __future__ import annotations

import hashlib
import importlib.metadata as metadata
import json
import platform
import shutil
import sys
import tarfile
import urllib.error
import urllib.request
import zipfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from photo_splitter.version import validate_version

QT_SOURCE_VERSION = "6.8.3"
PYTHON_SOURCE_VERSION = "3.12.10"
USER_AGENT = "SplitScan-source-release/1.0 (https://github.com/fvclaus/splitscan)"


def fetch(url: str) -> tuple[bytes, str]:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=120) as response:
        if response.status != 200:
            raise RuntimeError(f"Unexpected HTTP status {response.status} downloading {url}")
        return response.read(), response.geturl()


def sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def pypi_sdist(name: str, version: str) -> tuple[str, str, str]:
    index_url = f"https://pypi.org/pypi/{name}/{version}/json"
    content, _ = fetch(index_url)
    metadata_json = json.loads(content)
    sources = [
        entry
        for entry in metadata_json.get("urls", [])
        if entry.get("packagetype") == "sdist"
    ]
    if len(sources) != 1:
        raise RuntimeError(
            f"Expected a single source archive for {name} {version}, found {len(sources)}"
        )
    source = sources[0]
    return source["url"], source["digests"]["sha256"], index_url


def archive_is_readable(path: Path) -> bool:
    if path.name.endswith((".tar.gz", ".tgz", ".tar.xz", ".tar.bz2")):
        with tarfile.open(path, "r:*") as archive:
            return next(iter(archive), None) is not None
    if path.suffix == ".zip":
        with zipfile.ZipFile(path) as archive:
            return archive.infolist()[:1] != []
    raise RuntimeError(f"Unsupported source archive format: {path.name}")


def main() -> int:
    if len(sys.argv) != 2:
        raise SystemExit("usage: tools/download_sources.py <release-version>")
    version = validate_version(sys.argv[1])
    output = ROOT / "build" / "source-materials" / version
    if output.exists():
        shutil.rmtree(output)
    output.mkdir(parents=True)
    materials: list[dict[str, Any]] = []

    core = metadata.distribution("PySide6-Essentials").version
    shiboken = metadata.distribution("shiboken6").version
    if core != QT_SOURCE_VERSION or shiboken != QT_SOURCE_VERSION:
        raise RuntimeError(
            f"Pinned PySide/Shiboken Qt version {core}/{shiboken} does not match "
            f"corresponding-source version {QT_SOURCE_VERSION}"
        )
    qtcore = __import__("PySide6.QtCore", fromlist=["qVersion"])
    if qtcore.qVersion() != QT_SOURCE_VERSION:
        raise RuntimeError(f"Qt runtime {qtcore.qVersion()} is not {QT_SOURCE_VERSION}")
    if platform.python_version() != PYTHON_SOURCE_VERSION:
        raise RuntimeError(
            f"Build Python {platform.python_version()} does not match source release "
            f"{PYTHON_SOURCE_VERSION}"
        )

    official_archives = [
        (
            "qt-everywhere-source",
            f"https://download.qt.io/archive/qt/6.8/{QT_SOURCE_VERSION}/single/"
            f"qt-everywhere-src-{QT_SOURCE_VERSION}.tar.xz",
        ),
        (
            "pyside6-and-shiboken-source",
            f"https://download.qt.io/official_releases/QtForPython/pyside6/"
            f"PySide6-{QT_SOURCE_VERSION}-src/"
            f"pyside-setup-everywhere-src-{QT_SOURCE_VERSION}.tar.xz",
        ),
        (
            "cpython-source",
            f"https://www.python.org/ftp/python/{PYTHON_SOURCE_VERSION}/"
            f"Python-{PYTHON_SOURCE_VERSION}.tgz",
        ),
        ("ffmpeg-lgpl-4.4.5-source", "https://ffmpeg.org/releases/ffmpeg-4.4.5.tar.xz"),
        ("ffmpeg-lgpl-5.1.6-source", "https://ffmpeg.org/releases/ffmpeg-5.1.6.tar.xz"),
        ("ffmpeg-lgpl-7.1.1-source", "https://ffmpeg.org/releases/ffmpeg-7.1.1.tar.xz"),
        (
            "opencv-windows-ffmpeg-wrapper-source",
            "https://codeload.github.com/opencv/opencv_3rdparty/tar.gz/"
            "02a08baa7b8d330364c35477ba50524db8e4d335",
        ),
    ]
    for label, url in official_archives:
        payload, final_url = fetch(url)
        filename = url.rsplit("/", 1)[-1]
        if "/tar.gz/" in url:
            filename += ".tar.gz"
        destination = output / filename
        destination.write_bytes(payload)
        if not archive_is_readable(destination):
            raise RuntimeError(f"Downloaded source archive is empty or unreadable: {final_url}")
        materials.append(
            {
                "name": label,
                "version": {
                    "cpython-source": PYTHON_SOURCE_VERSION,
                    "ffmpeg-lgpl-4.4.5-source": "4.4.5",
                    "ffmpeg-lgpl-5.1.6-source": "5.1.6",
                    "ffmpeg-lgpl-7.1.1-source": "7.1.1",
                    "opencv-windows-ffmpeg-wrapper-source": "02a08baa7b8d330364c35477ba50524db8e4d335",
                }.get(label, QT_SOURCE_VERSION),
                "origin": final_url,
                "archive": filename,
                "sha256": sha256(payload),
                "bytes": len(payload),
            }
        )

    for distribution in sorted(
        (
            metadata.distribution(name)
            for name in (
                "numpy",
                "opencv-python-headless",
                "PyInstaller",
                "sentry-sdk",
            )
        ),
        key=lambda item: item.metadata["Name"].lower(),
    ):
        name = distribution.metadata["Name"]
        package_version = distribution.version
        url, expected_hash, index_url = pypi_sdist(name, package_version)
        payload, final_url = fetch(url)
        actual_hash = sha256(payload)
        if actual_hash != expected_hash:
            raise RuntimeError(
                f"PyPI source digest mismatch for {name} {package_version}: {actual_hash}"
            )
        filename = url.rsplit("/", 1)[-1]
        destination = output / filename
        destination.write_bytes(payload)
        if not archive_is_readable(destination):
            raise RuntimeError(f"Downloaded source archive is empty or unreadable: {final_url}")
        materials.append(
            {
                "name": name,
                "version": package_version,
                "origin": final_url,
                "source_index": index_url,
                "archive": filename,
                "sha256": actual_hash,
                "bytes": len(payload),
            }
        )

    manifest = {
        "schema": 1,
        "application": "SplitScan",
        "version": version,
        "description": (
            "Version-matched corresponding-source archives for distributed Python, Qt, "
            "Qt for Python, Shiboken, PyInstaller, NumPy, OpenCV, FFmpeg, and Sentry components."
        ),
        "materials": materials,
    }
    (output / "source-materials.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    (output / "README.txt").write_text(
        "SplitScan corresponding source materials\n"
        f"Application release: {version}\n\n"
        "Each source archive is version-matched, downloaded from its listed official "
        "origin, and SHA-256 recorded in source-materials.json. Qt and Qt for Python "
        "sources are included for LGPL replaceability and source access, including the "
        "FFmpeg versions used by the target OpenCV wheels. No application "
        "source is sent to these upstream hosts; these files are only downloaded and "
        "then distributed as an asset of the same SplitScan GitHub Release.\n",
        encoding="utf-8",
    )
    archive_path = ROOT / "build" / f"splitscan-v{version}-corresponding-source.zip"
    with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_STORED) as archive:
        for path in sorted(output.iterdir()):
            archive.write(path, arcname=path.name)
    print(f"Created {archive_path} ({archive_path.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, urllib.error.URLError, KeyError, ValueError, RuntimeError) as error:
        print(f"source materials failed: {error}", file=sys.stderr)
        raise SystemExit(1) from error
