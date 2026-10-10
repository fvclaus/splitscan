#!/usr/bin/env python3
"""Collect runtime notices and emit target-specific package provenance."""

from __future__ import annotations

import argparse
import base64
import ctypes
import hashlib
import importlib.metadata as metadata
import json
import os
import platform
import re
import shutil
import sys
import subprocess
from pathlib import Path
from typing import Any
import tomllib
import urllib.request

from packaging.requirements import Requirement
from packaging.tags import sys_tags
from packaging.utils import parse_wheel_filename

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from photo_splitter.version import __version__, validate_version

PACKAGE_NAMES = {
    "PyInstaller": "GPL-2.0-or-later WITH PyInstaller-exception",
    "PySide6-Essentials": "LGPL-3.0-or-later",
    "shiboken6": "LGPL-3.0-or-later",
    "numpy": "BSD-3-Clause",
    "opencv-python-headless": "Apache-2.0",
    "sentry-sdk": "MIT",
}
MANUAL_LICENSES = {
    "pyside6-essentials": "LGPL-3.0.txt",
    "shiboken6": "LGPL-3.0.txt",
}
LICENSE_FILE_RE = re.compile(r"(license|licence|copying|notice|copyright)", re.IGNORECASE)
NATIVE_SUFFIXES = {".dll", ".dylib", ".so", ".pyd", ".exe", ".framework"}
REQUIRED_DOCS = (
    ("LICENSE", ROOT / "LICENSE"),
    ("THIRD_PARTY_NOTICES.md", ROOT / "docs" / "THIRD_PARTY_NOTICES.md"),
    ("GPL-3.0.txt", ROOT / "docs" / "licenses" / "GPL-3.0.txt"),
    ("LGPL-3.0.txt", ROOT / "docs" / "licenses" / "LGPL-3.0.txt"),
    ("LGPL-2.1.txt", ROOT / "docs" / "licenses" / "LGPL-2.1.txt"),
    ("Python-PSF.txt", ROOT / "docs" / "licenses" / "Python-PSF.txt"),
)
FFMPEG_COMPONENTS = {
    "windows-x64": ("opencv_videoio_ffmpeg4110_64.dll", "FFmpeg 4.4.5", "LGPL-2.1"),
    "macos-x64": ("libavcodec.61.19.100.dylib", "FFmpeg 7.1.1", "LGPL-2.1"),
    "macos-arm64": ("libavcodec.61.19.100.dylib", "FFmpeg 7.1.1", "LGPL-2.1"),
    "linux-x64": (".so.59.37.100", "FFmpeg 5.1.6", "LGPL-2.1"),
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def is_native_file(path: Path) -> bool:
    if path.suffix.lower() in NATIVE_SUFFIXES or ".so." in path.name:
        return True
    with path.open("rb") as stream:
        magic = stream.read(4)
    return magic in {
        b"\x7fELF", b"\xfe\xed\xfa\xce", b"\xce\xfa\xed\xfe",
        b"\xfe\xed\xfa\xcf", b"\xcf\xfa\xed\xfe",
        b"\xca\xfe\xba\xbe", b"\xbe\xba\xfe\xca",
        b"\xca\xfe\xba\xbf", b"\xbf\xba\xfe\xca",
    } or magic[:2] == b"MZ"


def runtime_distributions() -> dict[str, metadata.Distribution]:
    installed = {canonical(dist.metadata["Name"]): dist for dist in metadata.distributions()}
    roots: list[str] = []
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    for raw in project.get("dependencies", []):
        requirement = Requirement(raw)
        if requirement.marker is None or requirement.marker.evaluate():
            roots.append(canonical(requirement.name))

    included: dict[str, metadata.Distribution] = {}
    queue = list(roots)
    while queue:
        name = queue.pop()
        if name in included:
            continue
        dist = installed.get(name)
        if dist is None:
            raise RuntimeError(f"Required runtime distribution {name!r} is not installed")
        included[name] = dist
        for raw in dist.requires or []:
            requirement = Requirement(raw)
            if requirement.marker is None or requirement.marker.evaluate():
                queue.append(canonical(requirement.name))

    for name in ("pyinstaller", "shiboken6"):
        if name not in included:
            dist = installed.get(name)
            if dist is None:
                raise RuntimeError(f"Required packaging distribution {name!r} is not installed")
            included[name] = dist
    return included


def source_provenance(dist: metadata.Distribution) -> dict[str, str]:
    name = dist.metadata["Name"]
    version = dist.version
    project_urls = dist.metadata.get_all("Project-URL") or []
    origin = next((entry.split(",", 1)[-1].strip() for entry in project_urls), "")
    if not origin:
        origin = dist.metadata.get("Home-page") or f"https://pypi.org/project/{name}/{version}/"
    index_url = f"https://pypi.org/pypi/{name}/{version}/json"
    request = urllib.request.Request(index_url, headers={"User-Agent": "SplitScan-license-audit/1.0"})
    with urllib.request.urlopen(request, timeout=30) as response:
        release = json.load(response)
    tags = list(sys_tags())
    tag_rank = {tag: index for index, tag in enumerate(tags)}
    wheels: list[tuple[int, dict[str, Any]]] = []
    for item in release.get("urls", []):
        if item.get("packagetype") != "bdist_wheel":
            continue
        try:
            _, _, _, wheel_tags = parse_wheel_filename(item["filename"])
        except ValueError:
            continue
        compatible = [tag_rank[tag] for tag in wheel_tags if tag in tag_rank]
        if compatible:
            wheels.append((min(compatible), item))
    if not wheels:
        raise RuntimeError(f"No compatible PyPI wheel provenance found for {name} {version}")
    _, wheel = min(wheels, key=lambda entry: entry[0])
    return {
        "type": "PyPI wheel; matching source distribution is in the corresponding-source archive",
        "project": origin,
        "versioned_index": f"https://pypi.org/project/{name}/{version}/",
        "wheel_filename": wheel["filename"],
        "wheel_url": wheel["url"],
        "wheel_sha256": wheel["digests"]["sha256"],
        "wheel_bytes": wheel["size"],
        "source_index": index_url,
    }


def license_paths(dist: metadata.Distribution) -> list[Path]:
    paths: list[Path] = []
    for item in dist.files or []:
        if LICENSE_FILE_RE.search(Path(str(item)).name) and Path(str(item)).suffix.lower() in {
            ".txt",
            ".md",
            ".rst",
            ".html",
            "",
        }:
            path = Path(dist.locate_file(item))
            if path.is_file():
                paths.append(path)
    return sorted(set(paths))


def installed_file_manifest(dist: metadata.Distribution) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    native: list[dict[str, str]] = []
    licenses: list[dict[str, str]] = []
    for item in dist.files or []:
        path = Path(dist.locate_file(item))
        if not path.is_file():
            continue
        relative = str(item).replace("\\", "/")
        record = {"path": relative, "sha256": sha256(path)}
        if is_native_file(path):
            expected = getattr(item, "hash", None)
            encoded = base64.urlsafe_b64encode(bytes.fromhex(record["sha256"])).decode().rstrip("=")
            if expected is None or expected.mode != "sha256" or expected.value != encoded:
                raise RuntimeError(f"Native wheel RECORD checksum mismatch or missing: {path}")
            native.append(record)
        if LICENSE_FILE_RE.search(Path(relative).name):
            licenses.append(record)
    return native, licenses


def create_inventory(outdir: Path, version: str, target: str) -> dict[str, Any]:
    version = validate_version(version)
    missing_docs = [str(path.relative_to(ROOT)) for _, path in REQUIRED_DOCS if not path.is_file()]
    if missing_docs:
        raise RuntimeError(f"Required notices or license texts are missing: {', '.join(missing_docs)}")

    notices_root = outdir / "THIRD_PARTY_NOTICES"
    notices_root.mkdir(parents=True, exist_ok=True)
    licenses_out = notices_root / "licenses"
    licenses_out.mkdir(exist_ok=True)
    for name, source in REQUIRED_DOCS:
        destination = notices_root / name if name.endswith(".md") else licenses_out / name
        shutil.copyfile(source, destination)

    dist_root = notices_root / "distributions"
    package_records: list[dict[str, Any]] = []
    for key, dist in sorted(runtime_distributions().items()):
        name = dist.metadata["Name"]
        license_expression = (
            dist.metadata.get("License-Expression")
            or PACKAGE_NAMES.get(name)
            or dist.metadata.get("License")
            or "NOASSERTION"
        )
        files = license_paths(dist)
        manual = MANUAL_LICENSES.get(key)
        if not files and not manual:
            raise RuntimeError(
                f"{name} {dist.version} has no redistributable license text; "
                "add an audited license-file mapping before packaging"
            )

        destination = dist_root / key
        destination.mkdir(parents=True, exist_ok=True)
        copied_licenses: list[dict[str, str]] = []
        for source in files:
            relative = Path(source.name)
            target_path = destination / relative
            if target_path.exists() and sha256(target_path) != sha256(source):
                target_path = destination / f"{source.parent.name}-{source.name}"
            shutil.copyfile(source, target_path)
            copied_licenses.append(
                {
                    "path": str(target_path.relative_to(notices_root)).replace("\\", "/"),
                    "sha256": sha256(target_path),
                    "origin": str(source),
                }
            )
        if manual:
            source = ROOT / "docs" / "licenses" / manual
            if not source.is_file():
                raise RuntimeError(f"Missing audited license text for {name}: {source}")
            target_path = destination / manual
            shutil.copyfile(source, target_path)
            copied_licenses.append(
                {
                    "path": str(target_path.relative_to(notices_root)).replace("\\", "/"),
                    "sha256": sha256(target_path),
                    "origin": "repository license mapping; verify against upstream package release",
                }
            )

        native_files, license_files = installed_file_manifest(dist)
        package_records.append(
            {
                "name": name,
                "version": dist.version,
                "license": license_expression,
                "provenance": source_provenance(dist),
                "license_texts": copied_licenses,
                "native_files": native_files,
                "license_files": license_files,
            }
        )

    python_license = licenses_out / "Python-PSF.txt"
    if not python_license.is_file():
        raise RuntimeError("Python runtime license text was not copied")

    inventory: dict[str, Any] = {
        "schema": 1,
        "application": "SplitScan",
        "version": version,
        "target": target,
        "python": {
            "version": platform.python_version(),
            "implementation": platform.python_implementation(),
            "license": "PSF-2.0",
            "source": f"https://www.python.org/downloads/release/python-{platform.python_version().replace('.', '')}/",
            "license_text": "licenses/Python-PSF.txt",
        },
        "distributions": package_records,
    }
    outdir.mkdir(parents=True, exist_ok=True)
    (outdir / "dependency-inventory.json").write_text(
        json.dumps(inventory, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return inventory


def inventory_bundle(root: Path, inventory: dict[str, Any]) -> None:
    """Record every packaged native object and trace known origins where possible."""
    known: dict[str, list[str]] = {}
    licenses = {dist["name"]: dist.get("license", "NOASSERTION")
                for dist in inventory["distributions"]}
    for dist in inventory["distributions"]:
        for file in dist["native_files"]:
            owners = known.setdefault(file["sha256"], [])
            if dist["name"] not in owners:
                owners.append(dist["name"])
    provenance = json.loads((root / "system-dependencies.json").read_text(encoding="utf-8"))
    collected = provenance.get("bundled_source_provenance", [])
    qtcore = __import__("PySide6.QtCore", fromlist=["qVersion"])
    if qtcore.qVersion() != "6.8.3":
        raise RuntimeError("Qt runtime does not match the corresponding-source version 6.8.3")

    native_paths = sorted(
        path
        for path in root.rglob("*")
        if path.is_file()
        and is_native_file(path)
    )
    records: list[dict[str, Any]] = []
    ffmpeg_paths: list[str] = []
    for path in native_paths:
        relative = str(path.relative_to(root)).replace("\\", "/")
        filename = path.name.lower()
        digest = sha256(path)
        owner = known.get(digest, [])
        source_records = [
            item for item in collected
            if Path(item["destination"]).name.lower() == filename
        ]
        source_hashes = {item["sha256"] for item in source_records}
        # PyInstaller rewrites Mach-O rpaths and ad-hoc signatures on macOS.
        if not owner and inventory["target"].startswith("macos-") and len(source_hashes) == 1:
            owner = known.get(next(iter(source_hashes)), [])
        if "opencv_videoio_ffmpeg" in filename or filename.startswith("libav") or filename.startswith(
            "libsw"
        ):
            ffmpeg_paths.append(relative)
            expected = FFMPEG_COMPONENTS.get(inventory["target"])
            ffmpeg_version = expected[1] if expected else "unverified FFmpeg build"
            if canonical("opencv-python-headless") not in {canonical(item) for item in owner}:
                raise RuntimeError(f"FFmpeg file is not traceable to the installed OpenCV wheel: {relative}")
            owner = [f"{ffmpeg_version} (LGPL-2.1; source in corresponding-source archive)"]
        if not owner:
            if relative in {"SplitScan", "SplitScan.exe", "Contents/MacOS/SplitScan"}:
                owner = ["PyInstaller bootloader (GPL with bootloader exception)"]
            elif source_records and all(
                Path(item["source"]).resolve().is_relative_to(Path(sys.base_prefix).resolve())
                for item in source_records
            ) and (digest in source_hashes or inventory["target"].startswith("macos-")):
                owner = ["Python runtime (PSF license)"]
            else:
                owner = ["Unresolved: native dependency mapping requires review"]
        records.append(
            {
                "path": relative,
                "sha256": digest,
                "source_provenance": source_records,
                "license_owner": owner,
                "mapped": len(owner) == 1 and not owner[0].startswith("Unresolved:"),
                "license_expression": [licenses.get(name, name) for name in owner],
                "replaceable_under_lgpl": any(
                    "lgpl" in licenses.get(name, name).lower() for name in owner
                ),
            }
        )

    expected_ffmpeg = FFMPEG_COMPONENTS.get(inventory["target"])
    if expected_ffmpeg is None:
        raise RuntimeError(f"No FFmpeg source/version mapping is recorded for {inventory['target']}")
    if not ffmpeg_paths or not any(
        expected_ffmpeg[0].lower() in Path(path).name.lower() for path in ffmpeg_paths
    ):
        raise RuntimeError(
            f"Packaged OpenCV FFmpeg library does not match the audited {expected_ffmpeg[1]} "
            f"marker for {inventory['target']}; found {ffmpeg_paths}"
        )

    unresolved = [record["path"] for record in records if not record["mapped"]]
    if unresolved:
        raise RuntimeError(
            "Native files have no known distribution/license mapping: " + ", ".join(unresolved)
        )
    ffmpeg_evidence = verify_ffmpeg(inventory["target"], root, ffmpeg_paths)
    linkage = native_linkage(root, native_paths, inventory["target"])
    system_dependencies_path = root / "system-dependencies.json"
    system_dependencies: dict[str, Any] = {
        "provided_by_target_os": [],
        "note": "Platform-provided dependencies are not redistributed with this application.",
    }
    if system_dependencies_path.is_file():
        system_dependencies = json.loads(system_dependencies_path.read_text(encoding="utf-8"))
    (root / "native-libraries.json").write_text(
        json.dumps(
            {
                "schema": 1,
                "target": inventory["target"],
                "version": inventory["version"],
                "native_files": records,
                "ffmpeg": {
                    "files": ffmpeg_paths,
                    "version": expected_ffmpeg[1],
                    "license": expected_ffmpeg[2],
                    "source_archive": f"ffmpeg-{expected_ffmpeg[1].split()[-1]}.tar.xz",
                    "source_is_included_in_corresponding_source_asset": True,
                    "runtime_evidence": ffmpeg_evidence,
                },
                "linkage": linkage,
                "system_dependencies": system_dependencies,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )


def verify_ffmpeg(target: str, root: Path, paths: list[str]) -> dict[str, str]:
        """Check actual FFmpeg version/license, rather than infer them from a soname."""
        expected = FFMPEG_COMPONENTS[target][1].split()[-1]
        if target == "windows-x64":
            payload = (root / paths[0]).read_bytes()
            if not re.search(rb"(?<![0-9.])" + re.escape(expected.encode()) + rb"(?![0-9.])", payload):
                raise RuntimeError(f"Windows FFmpeg wrapper lacks exact version evidence for {expected}")
            if b"LGPL version 2.1 or later" not in payload:
                raise RuntimeError("Windows FFmpeg wrapper lacks LGPL license evidence")
            return {"version": expected, "license": "LGPL version 2.1 or later",
                    "method": "exact embedded version and license in wheel-hash-verified wrapper"}
        # Importing cv2 loads its wheel-private FFmpeg dependencies before ctypes.
        __import__("cv2")
        dist = metadata.distribution("opencv-python-headless")
        codec = next(
            Path(dist.locate_file(item)) for item in dist.files or []
            if Path(str(item)).name.startswith("libavcodec")
        )
        library = ctypes.CDLL(str(codec))
        evidence = {}
        for label, symbol in (("version", "av_version_info"), ("configuration", "avcodec_configuration"),
                              ("license", "avcodec_license")):
            function = getattr(library, symbol)
            function.restype = ctypes.c_char_p
            evidence[label] = function().decode("utf-8")
        if evidence["version"] != expected or evidence["license"] != "LGPL version 2.1 or later":
            raise RuntimeError(f"FFmpeg runtime does not match audited source/license: {evidence}")
        if any(flag in evidence["configuration"] for flag in ("--enable-gpl", "--enable-nonfree")):
            raise RuntimeError(f"Unsupported FFmpeg licensing configuration: {evidence}")
        return evidence


def native_linkage(root: Path, paths: list[Path], target: str) -> list[dict[str, Any]]:
        """Record native loader imports and fail missing Linux shared-library resolution."""
        records = []
        bundled_names = {path.name.lower() for path in paths}
        for path in paths:
            if target.startswith("linux"):
                environment = {**os.environ, "LD_LIBRARY_PATH": str(root / "_internal")}
                result = subprocess.run(["ldd", str(path)], capture_output=True, text=True,
                                        check=False, env=environment)
                if "not found" in result.stdout:
                    raise RuntimeError(f"Unresolved native linkage for {path}: {result.stdout}")
                imports = result.stdout.strip().splitlines()
            elif target.startswith("macos"):
                result = subprocess.run(["otool", "-L", str(path)], capture_output=True, text=True, check=True)
                imports = result.stdout.strip().splitlines()[1:]
            else:
                import pefile
                image = pefile.PE(str(path), fast_load=True)
                image.parse_data_directories()
                imports = [
                    entry.dll.decode("ascii")
                    for entry in getattr(image, "DIRECTORY_ENTRY_IMPORT", [])
                ]
                image.close()
            records.append({
                "path": str(path.relative_to(root)).replace("\\", "/"),
                "loader_imports": imports,
                "bundled_import_names": sorted(
                    name for name in bundled_names if any(name in item.lower() for item in imports)
                ),
            })
        return records


def audit_bundle(outdir: Path, bundle: Path, version: str, target: str) -> dict[str, Any]:
    inventory = create_inventory(outdir, version, target)
    inventory_bundle(bundle, inventory)
    bundle_notices = bundle / "THIRD_PARTY_NOTICES"
    if bundle_notices.exists():
        shutil.rmtree(bundle_notices)
    shutil.copytree(outdir / "THIRD_PARTY_NOTICES", bundle_notices)
    shutil.copyfile(outdir / "dependency-inventory.json", bundle / "dependency-inventory.json")
    return inventory


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--outdir", type=Path, required=True)
    parser.add_argument("--bundle", type=Path)
    parser.add_argument("--version", default=__version__)
    parser.add_argument("--target", default=f"{platform.system().lower()}-{platform.machine().lower()}")
    args = parser.parse_args()

    inventory = create_inventory(args.outdir, args.version, args.target)
    if args.bundle:
        audit_bundle(args.outdir, args.bundle, args.version, args.target)
    print(f"Created dependency inventory for {args.target} {args.version}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
