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

from tools import build_mac_opencv, download_sources, license_audit, verify_release_artifacts
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


def test_mac_recipe_uses_uv_for_builder_wheel_and_runtime(monkeypatch, tmp_path):
    import hashlib
    from types import SimpleNamespace

    payload = b"pinned source archive"
    commands = []
    builders = []
    monkeypatch.setattr(build_mac_opencv, "ROOT", tmp_path)
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setenv("TMPDIR", str(tmp_path))
    monkeypatch.setattr(build_mac_opencv, "SOURCE_SHA256", hashlib.sha256(payload).hexdigest())
    monkeypatch.setattr(
        build_mac_opencv.urllib.request, "urlopen",
        lambda *args, **kwargs: SimpleNamespace(read=lambda: payload),
    )
    monkeypatch.setattr(build_mac_opencv.venv.EnvBuilder, "create", lambda self, path: builders.append(
        (path, self.with_pip)
    ))
    monkeypatch.setitem(sys.modules, "cv2", SimpleNamespace(
        getBuildInformation=lambda: "    To be built: core imgproc imgcodecs python3\n"
    ))
    (tmp_path / "requirements-mac-opencv.txt").write_text("numpy==2.2.6\n")

    def run(command, *, env, check):
        assert check
        commands.append(command)
        if command[:2] == ["uv", "build"]:
            assert env["ENABLE_HEADLESS"] == "1"
            assert "-DWITH_FFMPEG=OFF" in env["CMAKE_ARGS"]
            directory = Path(command[command.index("--out-dir") + 1])
            directory.mkdir()
            with zipfile.ZipFile(directory / "opencv_python_headless-4.11.0.86-test.whl", "w") as archive:
                archive.writestr("cv2/cv2.so", b"native image-only code")

    monkeypatch.setattr(build_mac_opencv.subprocess, "run", run)
    assert build_mac_opencv.main() == 0
    work = tmp_path / "build" / "mac-opencv"
    builder_python = str(work / "builder" / "bin" / "python")
    assert builders == [(work / "builder", False)]
    assert commands[0] == [
        "uv", "pip", "install", "--python", builder_python,
        "-r", str(tmp_path / "requirements-mac-opencv.txt"),
    ]
    assert commands[1] == [
        "uv", "build", "--python", builder_python, "--wheel", "--no-build-isolation",
        "--out-dir", str(work / "wheels"), str(work / "opencv-python-headless-4.11.0.86.tar.gz"),
    ]
    assert commands[2][:-1] == [
        "uv", "pip", "install", "--python", sys.executable, "--system", "--no-deps", "--reinstall",
    ]
    provenance = json.loads((work / "provenance.json").read_text())
    assert provenance["build_command"] == commands[1]
    assert provenance["native_files"][0]["path"] == "cv2/cv2.so"


def test_native_icons_render_shared_brand_mark(tmp_path):
    import struct
    from PySide6.QtGui import QImage
    from tools.build_icons import write_icons

    write_icons(tmp_path)
    ico = (tmp_path / "splitscan.ico").read_bytes()
    reserved, kind, count = struct.unpack_from("<HHH", ico)
    assert (reserved, kind, count) == (0, 1, 7)
    sizes = []
    for index in range(count):
        width, height, _, _, planes, depth, length, offset = struct.unpack_from(
            "<BBBBHHII", ico, 6 + 16 * index
        )
        width, height = width or 256, height or 256
        assert planes == 1 and depth == 32
        image = QImage.fromData(ico[offset:offset + length], "PNG")
        assert not image.isNull()
        assert (image.width(), image.height()) == (width, height)
        assert image.pixelColor(width // 8, height // 2).name() == "#286b58"
        # At small sizes, the white scan line blends with the green background.
        assert image.pixelColor(width // 2, height // 2).red() > 100
        assert image.pixelColor(0, 0).alpha() == 0
        sizes.append(width)
    assert sizes == [16, 24, 32, 48, 64, 128, 256]
    icns = (tmp_path / "splitscan.icns").read_bytes()
    assert icns[:4] == b"icns"
    assert struct.unpack_from(">I", icns, 4)[0] == len(icns)
    offset = 8
    for expected_kind, size in ((b"ic07", 128), (b"ic08", 256), (b"ic09", 512), (b"ic10", 1024)):
        assert icns[offset:offset + 4] == expected_kind
        length = struct.unpack_from(">I", icns, offset + 4)[0]
        image = QImage.fromData(icns[offset + 8:offset + length], "PNG")
        assert (image.width(), image.height()) == (size, size)
        offset += length
    assert offset == len(icns)


def test_pyinstaller_spec_wires_native_icon_files():
    import ast

    source = Path("build-config/splitscan.spec").read_text()
    tree = ast.parse(source)
    icon_arguments = {
        call.func.id: next(keyword.value for keyword in call.keywords if keyword.arg == "icon")
        for call in ast.walk(tree)
        if isinstance(call, ast.Call) and isinstance(call.func, ast.Name)
        and call.func.id in {"EXE", "BUNDLE"}
    }
    assert "splitscan.ico" in ast.unparse(icon_arguments["EXE"])
    assert "win32" in ast.unparse(icon_arguments["EXE"])
    assert "splitscan.icns" in ast.unparse(icon_arguments["BUNDLE"])


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


@pytest.mark.parametrize("installer", ["pyinstaller", "PyInstaller"])
def test_source_gate_accepts_normalized_distribution_names(tmp_path, installer):
    names = [
        "qt-everywhere-source", "pyside6-and-shiboken-source", "cpython-source",
        "ffmpeg-lgpl-4.4.5-source", "ffmpeg-lgpl-5.1.6-source",
        "mac-opencv-build-recipe/build_mac_opencv.py",
        "mac-opencv-build-recipe/requirements-mac-opencv.txt",
        "opencv-windows-ffmpeg-wrapper-source", "numpy", "opencv-python-headless",
        installer, "sentry-sdk",
    ]
    path = tmp_path / "sources.zip"
    materials = []
    with zipfile.ZipFile(path, "w") as archive:
        for index, name in enumerate(names):
            entry = f"source-{index}"
            archive.writestr(entry, b"source")
            materials.append({
                "name": name, "archive": entry,
                "sha256": verify_release_artifacts.sha256(b"source"),
            })
        archive.writestr("README.txt", "Sources")
        archive.writestr("source-materials.json", json.dumps({
            "version": "0.1.0", "materials": materials,
        }))
    verify_release_artifacts.verify_sources(path, "0.1.0")
