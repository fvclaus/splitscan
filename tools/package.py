#!/usr/bin/env python3
"""Build and smoke-test a native PyInstaller onedir release."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import shutil
import stat
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from tools.license_audit import audit_bundle, create_inventory
from tools.build_icons import write_icons
from photo_splitter.version import __version__, validate_version


def target_name() -> str:
    system = platform.system().lower()
    machine = platform.machine().lower()
    if system == "windows":
        return "windows-x64" if machine in {"amd64", "x86_64"} else f"windows-{machine}"
    if system == "darwin":
        arch = "arm64" if machine in {"arm64", "aarch64"} else "x64"
        return f"macos-{arch}"
    if system == "linux":
        return "linux-x64" if machine in {"x86_64", "amd64"} else f"linux-{machine}"
    raise RuntimeError(f"Unsupported native packaging platform: {system}/{machine}")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def windows_version_resource(version: str, path: Path) -> None:
    parts = version.split(".")
    release = [int(part) for part in parts[:3]]
    build = int(parts[-1].removeprefix("dev")) if ".dev" in version else 0
    numeric = tuple((release + [build])[:4])
    display_version = version.replace("'", "\\'")
    text = f"""VSVersionInfo(
  ffi=FixedFileInfo(
    filevers={numeric!r},
    prodvers={numeric!r},
    mask=0x3f,
    flags=0x0,
    OS=0x40004,
    fileType=0x1,
    subtype=0x0,
    date=(0, 0)
  ),
  kids=[
    StringFileInfo([
      StringTable(
        '040904B0',
        [
          StringStruct('CompanyName', 'fvclaus and SplitScan contributors'),
          StringStruct('FileDescription', 'SplitScan'),
          StringStruct('FileVersion', '{display_version}'),
          StringStruct('InternalName', 'SplitScan'),
          StringStruct('OriginalFilename', 'SplitScan.exe'),
          StringStruct('ProductName', 'SplitScan'),
          StringStruct('ProductVersion', '{display_version}')
        ]
      )
    ]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])
  ]
)
"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def archive_directory(directory: Path, archive_path: Path, target: str) -> None:
    archive_path.parent.mkdir(parents=True, exist_ok=True)
    if target.startswith("macos-"):
        subprocess.run(
            [
                "/usr/bin/ditto",
                "-c",
                "-k",
                "--sequesterRsrc",
                "--keepParent",
                str(directory),
                str(archive_path),
            ],
            check=True,
        )
        return
    with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for file in sorted(directory.rglob("*")):
            if not file.is_file():
                continue
            relative = file.relative_to(directory.parent)
            info = zipfile.ZipInfo(relative.as_posix())
            info.date_time = (2020, 1, 1, 0, 0, 0)
            mode = file.stat().st_mode
            info.external_attr = (stat.S_IFREG | stat.S_IMODE(mode)) << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, file.read_bytes())


def app_directory(distpath: Path, target: str) -> Path:
    result = distpath / ("SplitScan.app" if target.startswith("macos-") else "SplitScan")
    if not result.exists():
        raise RuntimeError(f"PyInstaller did not produce the expected onedir application: {result}")
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--version", default=__version__)
    parser.add_argument("--target", default=target_name())
    args = parser.parse_args()
    version = validate_version(args.version)
    actual_target = target_name()
    if args.target != actual_target:
        raise SystemExit(f"Native target mismatch: requested {args.target}, runner is {actual_target}")

    build_root = ROOT / "build" / "native" / version / actual_target
    distpath = build_root / "dist"
    workpath = build_root / "pyinstaller-work"
    compliance = build_root / "compliance"
    generated_version_dir = build_root / "generated"
    if build_root.exists():
        shutil.rmtree(build_root)
    build_root.mkdir(parents=True)
    generated_version_dir.mkdir(parents=True)
    (generated_version_dir / "_splitscan_build_version.py").write_text(
        f"BUILD_VERSION = {version!r}\n", encoding="utf-8"
    )
    write_icons(generated_version_dir / "icons")

    environment = os.environ.copy()
    environment["SPLITSCAN_VERSION"] = version
    environment["SPLITSCAN_COMPLIANCE_DIR"] = str(compliance)
    environment["SPLITSCAN_GENERATED_VERSION_DIR"] = str(generated_version_dir)
    resource = build_root / "windows-version.txt"
    if platform.system() == "Windows":
        windows_version_resource(version, resource)
        environment["SPLITSCAN_VERSION_RESOURCE"] = str(resource)

    create_inventory(compliance, version, actual_target)
    previous_environment = {
        key: os.environ.get(key)
        for key in (
            "SPLITSCAN_VERSION",
            "SPLITSCAN_COMPLIANCE_DIR",
            "SPLITSCAN_GENERATED_VERSION_DIR",
            "SPLITSCAN_VERSION_RESOURCE",
        )
    }
    os.environ.update(
        {
            key: value
            for key, value in environment.items()
            if key in previous_environment and value is not None
        }
    )
    try:
        from PyInstaller.__main__ import run as run_pyinstaller

        run_pyinstaller(
            [
                "--noconfirm",
                "--clean",
                "--distpath",
                str(distpath),
                "--workpath",
                str(workpath),
                "build-config/splitscan.spec",
            ]
        )
    finally:
        for key, previous in previous_environment.items():
            if previous is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = previous
    application = app_directory(distpath, actual_target)
    system_dependency_report = compliance / "system-dependencies.json"
    if not system_dependency_report.is_file():
        raise RuntimeError("PyInstaller did not record operating-system dependencies")
    shutil.copyfile(system_dependency_report, application / "system-dependencies.json")
    audit_bundle(compliance, application, version, actual_target)

    executable = application / "Contents" / "MacOS" / "SplitScan" if actual_target.startswith("macos-") else (
        application / "SplitScan.exe" if actual_target.startswith("windows-") else application / "SplitScan"
    )
    smoke_environment = environment.copy()
    smoke_environment["QT_QPA_PLATFORM"] = "offscreen"
    smoke_environment.pop("SENTRY_DSN", None)
    result = subprocess.run(
        [str(executable), "--smoke-test"],
        cwd=application,
        env=smoke_environment,
        check=False,
        capture_output=True,
        text=True,
        timeout=90,
    )
    if result.returncode:
        raise RuntimeError(
            "Frozen smoke test failed with exit code "
            f"{result.returncode}\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )

    native_manifest = application / "native-libraries.json"
    if not native_manifest.is_file():
        raise RuntimeError("Native dependency/license mapping was not generated")
    manifest = json.loads(native_manifest.read_text(encoding="utf-8"))
    unresolved = [
        item["path"]
        for item in manifest["native_files"]
        if not item.get("mapped")
    ]
    if unresolved:
        raise RuntimeError(f"Unresolved native libraries: {', '.join(unresolved)}")

    build_manifest = {
        "schema": 1,
        "application": "SplitScan",
        "version": version,
        "target": actual_target,
        "source_commit": os.environ.get("GITHUB_SHA", "local"),
        "release_tag": os.environ.get("GITHUB_REF_NAME", ""),
        "python": platform.python_version(),
        "platform": platform.platform(),
        "architecture": platform.machine(),
        "pyinstaller": __import__("importlib.metadata", fromlist=["version"]).version(
            "pyinstaller"
        ),
        "linux_baseline": "Ubuntu 22.04 / glibc 2.35" if actual_target == "linux-x64" else None,
        "dependency_inventory": "dependency-inventory.json",
        "native_inventory": "native-libraries.json",
        "release_build": ".dev" not in version,
    }
    (application / "build-manifest.json").write_text(
        json.dumps(build_manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    archive_name = f"splitscan-{version}-{actual_target}.zip"
    archive_path = ROOT / "build" / "artifacts" / archive_name
    archive_directory(application, archive_path, actual_target)
    checksum_path = archive_path.with_suffix(archive_path.suffix + ".sha256")
    checksum_path.write_text(f"{sha256(archive_path)}  {archive_path.name}\n", encoding="ascii")
    print(f"Built and smoke-tested {archive_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
