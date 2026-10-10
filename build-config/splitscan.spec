# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path
import os
import json
import subprocess
import sys
import sysconfig
import hashlib

from PyInstaller.utils.hooks import collect_data_files


root = Path.cwd()
compliance_dir = Path(os.environ["SPLITSCAN_COMPLIANCE_DIR"])
version = os.environ["SPLITSCAN_VERSION"]
version_resource = os.environ.get("SPLITSCAN_VERSION_RESOURCE")
generated_version_dir = Path(os.environ["SPLITSCAN_GENERATED_VERSION_DIR"])

datas = collect_data_files("photo_splitter")
for source in sorted((compliance_dir / "THIRD_PARTY_NOTICES").rglob("*")):
    if source.is_file():
        relative = source.relative_to(compliance_dir)
        datas.append(
            (
                str(source),
                str(relative.parent),
            )
        )
datas.append((str(root / "LICENSE"), "."))


def is_within(path, parent):
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False

a = Analysis(
    [str(root / "src" / "photo_splitter" / "app.py")],
    pathex=[str(root / "src"), str(generated_version_dir)],
    binaries=[],
    datas=datas,
    hiddenimports=[
        "PySide6.QtCore",
        "PySide6.QtGui",
        "PySide6.QtWidgets",
        "_splitscan_build_version",
    ],
    hookspath=[str(root / "build-config" / "hooks")],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets"],
    noarchive=False,
    optimize=0,
)

python_roots = {
    Path(sys.prefix).resolve(),
    Path(sys.base_prefix).resolve(),
    Path(sysconfig.get_path("purelib")).resolve(),
    Path(sysconfig.get_path("platlib")).resolve(),
}
bundled_binaries = []
bundled_sources = []
system_binaries = []
for binary in a.binaries:
    source = Path(binary[1]).resolve()
    if any(is_within(source, python_root) for python_root in python_roots):
        bundled_binaries.append(binary)
        bundled_sources.append({
            "destination": binary[0],
            "source": str(source),
            "sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        })
    else:
        package = ""
        if sys.platform.startswith("linux"):
            ownership = subprocess.run(
                ["dpkg-query", "-S", str(source)],
                check=False,
                capture_output=True,
                text=True,
            )
            package = ownership.stdout.strip().split(":", 1)[0] if ownership.returncode == 0 else ""
        package_version = ""
        if package:
            version_result = subprocess.run(
                ["dpkg-query", "-W", "-f=${Version}", package.split()[0]],
                check=False,
                capture_output=True,
                text=True,
            )
            if version_result.returncode == 0:
                package_version = version_result.stdout.strip()
        system_binaries.append(
            {
                "destination": binary[0],
                "source": str(source),
                "os_package": package or "operating-system runtime",
                "os_package_version": package_version,
                "distributed": False,
            }
        )
a.binaries = bundled_binaries
(compliance_dir / "system-dependencies.json").write_text(
    json.dumps(
        {
            "target": sys.platform,
            "provided_by_target_os": system_binaries,
            "bundled_source_provenance": bundled_sources,
            "note": "These files are resolved from the target OS and are not in the application archive.",
        },
        indent=2,
        sort_keys=True,
    )
    + "\n",
    encoding="utf-8",
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="SplitScan",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    version=version_resource,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="SplitScan",
)
if sys.platform == "darwin":
    app = BUNDLE(
        coll,
        name="SplitScan.app",
        icon=None,
        bundle_identifier="org.keepsake.splitscan",
        info_plist={
            "CFBundleName": "SplitScan",
            "CFBundleDisplayName": "SplitScan",
            "CFBundleShortVersionString": version,
            "CFBundleVersion": version,
            "LSMinimumSystemVersion": "12.0",
        },
    )
