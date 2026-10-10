from PyInstaller.utils.hooks.qt import ensure_single_qt_bindings_package, get_qt_library_info


ensure_single_qt_bindings_package("PySide6")
library_info = get_qt_library_info("PySide6")
seen = set()
for module_info in (*library_info.python_modules.values(), *library_info.shared_libraries.values()):
    if id(module_info) in seen:
        continue
    seen.add(id(module_info))
    if module_info.module == "QtGui":
        module_info.plugins[:] = ["imageformats", "platforms"]
    elif module_info.module in {"QtWidgets", "QtNetwork"}:
        module_info.plugins[:] = []

hiddenimports = ["PySide6.support.deprecated"]
