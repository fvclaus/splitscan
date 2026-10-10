#!/usr/bin/env python3
"""Build image-only OpenCV for macOS, without GPL FFmpeg or Homebrew linkage."""

from __future__ import annotations

import hashlib
import json
import os
import platform
import re
import subprocess
import sys
import urllib.request
import venv
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VERSION = "4.11.0.86"
SOURCE_URL = (
    "https://files.pythonhosted.org/packages/36/2f/"
    "5b2b3ba52c864848885ba988f24b7f105052f68da9ab0e693cc7c25b0b30/"
    "opencv-python-headless-4.11.0.86.tar.gz"
)
SOURCE_SHA256 = "996eb282ca4b43ec6a3972414de0e2331f5d9cda2b41091a49739c19fb843798"
CMAKE_ARGS = (
    "-DWITH_FFMPEG=OFF", "-DWITH_GSTREAMER=OFF", "-DWITH_AVFOUNDATION=OFF",
    "-DBUILD_opencv_videoio=OFF", "-DBUILD_opencv_gapi=OFF",
    "-DBUILD_opencv_highgui=OFF", "-DWITH_QT=OFF", "-DWITH_GTK=OFF",
    "-DWITH_OPENEXR=OFF", "-DWITH_IPP=OFF", "-DWITH_LAPACK=OFF",
    "-DWITH_OPENCL=OFF", "-DWITH_EIGEN=OFF", "-DWITH_ITT=OFF",
    "-DBUILD_JPEG=ON", "-DBUILD_PNG=ON", "-DBUILD_TIFF=ON",
    "-DBUILD_WEBP=ON", "-DBUILD_OPENJPEG=ON", "-DBUILD_ZLIB=ON",
    "-DCMAKE_IGNORE_PREFIX_PATH=/opt/homebrew;/usr/local",
)


def validate_image_only_build(information: str) -> None:
    built = re.search(r"^\s*To be built:\s*(.*)$", information, re.MULTILINE)
    if built is None or "videoio" in built.group(1).split():
        raise RuntimeError("Custom Mac OpenCV must exclude the videoio module")
    if re.search(r"^\s*FFMPEG:\s*YES", information, re.MULTILINE):
        raise RuntimeError("GPL-capable FFmpeg must not be enabled in Mac OpenCV")
    if any(token in information for token in ("/opt/homebrew", "/Cellar/ffmpeg")):
        # The configured ignore-prefix flag itself can appear in build information.
        lines = [line for line in information.splitlines()
                 if "CMAKE_IGNORE_PREFIX_PATH" not in line]
        if any("/opt/homebrew" in line or "/Cellar/ffmpeg" in line for line in lines):
            raise RuntimeError("Custom Mac OpenCV unexpectedly uses Homebrew build dependencies")


def main() -> int:
    if sys.platform != "darwin":
        raise SystemExit("This native source build is only for macOS")
    work = ROOT / "build" / "mac-opencv"
    work.mkdir(parents=True, exist_ok=True)
    os.environ["TMPDIR"] = str(work)
    environment = {**os.environ, "TMPDIR": str(work)}
    payload = urllib.request.urlopen(SOURCE_URL, timeout=120).read()
    if hashlib.sha256(payload).hexdigest() != SOURCE_SHA256:
        raise RuntimeError("Pinned OpenCV source digest mismatch")
    source = work / "opencv-python-headless-4.11.0.86.tar.gz"
    source.write_bytes(payload)
    for old_wheel in (work / "wheels").glob("opencv_python_headless-*.whl"):
        old_wheel.unlink()
    builder = work / "builder"
    venv.EnvBuilder(with_pip=True).create(builder)
    python = builder / "bin" / "python"
    subprocess.run(
        [str(python), "-m", "pip", "install", "-r", str(ROOT / "requirements-mac-opencv.txt")],
        env=environment, check=True,
    )
    environment.update({
        "ENABLE_HEADLESS": "1", "ENABLE_CONTRIB": "0",
        "CMAKE_ARGS": " ".join(CMAKE_ARGS),
        "CMAKE_BUILD_PARALLEL_LEVEL": str(min(os.cpu_count() or 2, 4)),
        "MACOSX_DEPLOYMENT_TARGET": "12.0",
    })
    command = [str(python), "-m", "pip", "wheel", "--no-deps", "--no-build-isolation",
               "--wheel-dir", str(work / "wheels"), str(source)]
    subprocess.run(command, env=environment, check=True)
    wheels = list((work / "wheels").glob("opencv_python_headless-*.whl"))
    if len(wheels) != 1:
        raise RuntimeError("Expected exactly one locally compiled OpenCV wheel")
    wheel = wheels[0]
    subprocess.run(
        [sys.executable, "-m", "pip", "install", "--no-deps", "--force-reinstall", str(wheel)],
        env=environment, check=True,
    )
    import cv2
    information = cv2.getBuildInformation()
    validate_image_only_build(information)
    natives = []
    with zipfile.ZipFile(wheel) as archive:
        for name in archive.namelist():
            if name.endswith((".so", ".dylib")):
                natives.append({"path": name, "sha256": hashlib.sha256(archive.read(name)).hexdigest()})
    provenance = {
        "type": "locally compiled image-only OpenCV wheel from digest-pinned PyPI sdist",
        "version": VERSION, "target": f"macos-{'arm64' if platform.machine() == 'arm64' else 'x64'}",
        "source_url": SOURCE_URL, "source_sha256": SOURCE_SHA256,
        "wheel_filename": wheel.name, "wheel_sha256": hashlib.sha256(wheel.read_bytes()).hexdigest(),
        "cmake_args": list(CMAKE_ARGS), "build_command": command,
        "recipe": "tools/build_mac_opencv.py",
        "builder_requirements": (ROOT / "requirements-mac-opencv.txt").read_text(),
        "native_files": natives, "build_information": information,
        "ffmpeg": "disabled; videoio module not built",
    }
    (work / "provenance.json").write_text(json.dumps(provenance, indent=2) + "\n", encoding="utf-8")
    print("Built and validated image-only Mac OpenCV; FFmpeg disabled")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
