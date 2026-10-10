import sys

from PyInstaller.utils.hooks.qt import add_qt6_dependencies


hiddenimports, binaries, datas = add_qt6_dependencies(__file__)

if sys.platform == "win32":
    platform_plugins = {"qwindows.dll", "qoffscreen.dll"}
elif sys.platform == "darwin":
    platform_plugins = {"libqcocoa.dylib", "libqoffscreen.dylib"}
else:
    platform_plugins = {"libqxcb.so", "libqoffscreen.so"}

filtered = []
for source, destination, *rest in binaries:
    path = destination.replace("\\", "/").lower()
    filename = path.rsplit("/", 1)[-1]
    if "/plugins/platforms/" in path:
        if filename not in platform_plugins:
            continue
    elif "/plugins/imageformats/" in path and filename not in {"libqsvg.so", "qsvg.dll", "libqsvg.dylib"}:
        continue
    filtered.append((source, destination, *rest))
binaries = filtered
