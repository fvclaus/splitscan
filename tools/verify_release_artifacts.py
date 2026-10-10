#!/usr/bin/env python3
"""Fail a release publication unless all target and source assets verify."""

from __future__ import annotations

import argparse
import hashlib
import json
import posixpath
import stat
import sys
import zipfile
from pathlib import Path

TARGETS = ("windows-x64", "macos-x64", "macos-arm64", "linux-x64")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))
from photo_splitter.version import validate_version
from tools.build_mac_opencv import SOURCE_SHA256
LICENSE_PATHS = (
    "THIRD_PARTY_NOTICES/licenses/LGPL-3.0.txt",
    "THIRD_PARTY_NOTICES/licenses/GPL-3.0.txt",
    "THIRD_PARTY_NOTICES/licenses/LGPL-2.1.txt",
    "THIRD_PARTY_NOTICES/licenses/Python-PSF.txt",
)


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def archive_file_bytes(archive: zipfile.ZipFile, entry: str, bundle: str) -> bytes:
    visited = set()
    names = set(archive.namelist())
    while True:
        if entry in visited or len(visited) >= 40 or not entry.startswith(bundle + "/"):
            raise RuntimeError(f"Invalid or cyclic archive symlink: {entry}")
        visited.add(entry)
        parts = entry.split("/")
        link = None
        for index in range(1, len(parts) + 1):
            prefix = "/".join(parts[:index])
            if prefix in names and stat.S_ISLNK(archive.getinfo(prefix).external_attr >> 16):
                link = (prefix, parts[index:])
                break
        if link is None:
            if entry not in names:
                raise RuntimeError(f"Missing archive symlink target or file: {entry}")
            return archive.read(entry)
        prefix, suffix = link
        target = archive.read(prefix).decode("utf-8")
        if posixpath.isabs(target):
            raise RuntimeError(f"Absolute archive symlink: {entry}")
        entry = posixpath.normpath(posixpath.join(posixpath.dirname(prefix), target, *suffix))


def verify_binary(path: Path, target: str, version: str) -> None:
    expected_name = f"splitscan-{version}-{target}.zip"
    if path.name != expected_name:
        raise RuntimeError(f"Unexpected archive name: {path.name}; expected {expected_name}")
    checksum_path = path.with_suffix(path.suffix + ".sha256")
    expected_checksum = checksum_path.read_text(encoding="ascii").split()[0]
    actual_checksum = sha256(path.read_bytes())
    if actual_checksum != expected_checksum:
        raise RuntimeError(f"Checksum mismatch: {path.name}")

    with zipfile.ZipFile(path) as archive:
        names = set(archive.namelist())
        bundle = "SplitScan.app" if target.startswith("macos-") else "SplitScan"
        for required in (
            "build-manifest.json",
            "dependency-inventory.json",
            "native-libraries.json",
            "system-dependencies.json",
        ):
            entry = f"{bundle}/{required}"
            if entry not in names:
                raise RuntimeError(f"{path.name} is missing {entry}")
        for required in LICENSE_PATHS:
            entry = f"{bundle}/{required}"
            if entry not in names:
                raise RuntimeError(f"{path.name} is missing required notice {entry}")
        manifest = json.loads(archive.read(f"{bundle}/build-manifest.json"))
        inventory = json.loads(archive.read(f"{bundle}/dependency-inventory.json"))
        natives = json.loads(archive.read(f"{bundle}/native-libraries.json"))
        if manifest["version"] != version or inventory["version"] != version or natives["version"] != version:
            raise RuntimeError(f"Embedded version mismatch in {path.name}")
        if manifest["target"] != target or inventory["target"] != target or natives["target"] != target:
            raise RuntimeError(f"Embedded target mismatch in {path.name}")
        if any(not native.get("mapped") for native in natives["native_files"]):
            raise RuntimeError(f"Unmapped native component in {path.name}")
        for native in natives["native_files"]:
            entry = f"{bundle}/{native['path']}"
            if entry not in names or sha256(archive_file_bytes(archive, entry, bundle)) != native["sha256"]:
                raise RuntimeError(f"Native-file checksum mismatch: {entry}")
        if not natives.get("linkage") or not natives["ffmpeg"].get("runtime_evidence"):
            raise RuntimeError(f"Native linkage/runtime evidence missing from {path.name}")
        if target.startswith("macos-"):
            if natives["ffmpeg"].get("enabled") is not False or natives["ffmpeg"]["files"]:
                raise RuntimeError(f"Mac archive must not redistribute FFmpeg: {path.name}")
            opencv = next(item for item in inventory["distributions"]
                          if item["name"].lower().replace("_", "-") == "opencv-python-headless")
            if opencv["provenance"].get("source_sha256") != SOURCE_SHA256:
                raise RuntimeError(f"Mac archive lacks pinned OpenCV source-build provenance: {path.name}")


def verify_sources(path: Path, version: str) -> None:
    with zipfile.ZipFile(path) as archive:
        names = set(archive.namelist())
        if "source-materials.json" not in names or "README.txt" not in names:
            raise RuntimeError("Corresponding source archive lacks its manifest or explanation")
        manifest = json.loads(archive.read("source-materials.json"))
        if manifest.get("version") != version:
            raise RuntimeError("Corresponding-source archive does not match the release version")
        required = {
            "qt-everywhere-source",
            "pyside6-and-shiboken-source",
            "cpython-source",
            "ffmpeg-lgpl-4.4.5-source",
            "ffmpeg-lgpl-5.1.6-source",
            "mac-opencv-build-recipe/build_mac_opencv.py",
            "mac-opencv-build-recipe/requirements-mac-opencv.txt",
            "opencv-windows-ffmpeg-wrapper-source",
            "numpy",
            "opencv-python-headless",
            "pyinstaller",
            "sentry-sdk",
        }
        available = {item["name"].lower() for item in manifest.get("materials", [])}
        if not required.issubset(available):
            raise RuntimeError(f"Corresponding-source archive lacks required materials: {sorted(required - available)}")
        for item in manifest["materials"]:
            name = item["archive"]
            if name not in names:
                raise RuntimeError(f"Corresponding-source archive is missing {name}")
            if sha256(archive.read(name)) != item["sha256"]:
                raise RuntimeError(f"Source checksum mismatch: {name}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--version", required=True)
    args = parser.parse_args()
    args.version = validate_version(args.version)
    for target in TARGETS:
        verify_binary(args.directory / f"splitscan-{args.version}-{target}.zip", target, args.version)
    source_archive = args.directory / f"splitscan-v{args.version}-corresponding-source.zip"
    verify_sources(source_archive, args.version)
    print(f"Verified four native archives and version-matched sources for {args.version}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
