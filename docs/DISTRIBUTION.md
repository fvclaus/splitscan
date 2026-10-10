# Native distribution and replacement guide

SplitScan releases are built as PyInstaller **onedir** applications on native
GitHub-hosted runners:

| Archive | Target |
| --- | --- |
| `splitscan-<version>-windows-x64.zip` | Windows x64; run `SplitScan.exe` |
| `splitscan-<version>-macos-x64.zip` | macOS Intel; open `SplitScan.app` |
| `splitscan-<version>-macos-arm64.zip` | macOS Apple Silicon; open `SplitScan.app` |
| `splitscan-<version>-linux-x64.zip` | Linux x64; run `./SplitScan` |

The Linux build runs on Ubuntu 22.04 (glibc 2.35). It is tested on that runner,
not certified for every distribution; systems must provide compatible glibc
and desktop/display libraries. The applications include Python, Qt, and other
Python runtime dependencies, so users do not install Python separately.

The application/window icon and header use the same green SplitScan scan-line mark
from `src/photo_splitter/assets/splitscan.svg`. Packaging renders that SVG into
multi-resolution Windows ICO and macOS ICNS resources using `tools/build_icons.py`;
Linux taskbars receive the icon through Qt's window icon. Rebuild the native archive
to update executable/bundle icons. A previously pinned shortcut may retain an OS-cached
icon and need to be unpinned and pinned again after replacing the application.

Every archive contains `LICENSE`, `THIRD_PARTY_NOTICES/`,
`dependency-inventory.json`, and `native-libraries.json`. The inventory
records versions, source locations, license-text provenance, and SHA-256
hashes for packaged native files. A release also provides
`splitscan-v<version>-corresponding-source.zip` with version-matched upstream
source archives, their official origins, and hashes. The sources are
downloaded from the Python, Qt, Qt for Python, FFmpeg, OpenCV, and PyPI
project distribution sites and published only as assets of the same GitHub
Release. They include the FFmpeg source versions used by OpenCV's target
wheels (LGPL-2.1), the Windows FFmpeg wrapper source, and the PyInstaller
bootloader source.

## Replacing LGPL libraries

The onedir format keeps Qt and Shiboken shared libraries outside the
application executable. The target-specific `native-libraries.json` maps
each bundled native library to its path and license owner. Replace only
libraries offered under the applicable LGPL terms, using a compatible build
with the same ABI and preserving the package's relative directory layout.
Do not replace unrelated components based solely on a filename.

- **Windows:** extract the ZIP and replace files at their manifest paths below
  `_internal/`, then launch `SplitScan.exe` from the extracted directory.
- **macOS:** replace the manifest-listed files in the `.app` bundle, generally
  under `Contents/Frameworks/`. Since the app is unsigned, Gatekeeper may show
  an unidentified-developer warning. Use Finder's per-app **Open** flow only
  if you trust the downloaded release. After changing a bundle, apply a local
  ad-hoc signature if macOS requires one:
  `codesign --force --deep --sign - SplitScan.app`.
- **Linux:** replace the manifest-listed files below `_internal/`; keep the
  launcher and support tree together and run `./SplitScan`.

The Windows and Linux OpenCV FFmpeg libraries are LGPL-2.1 components. Their replaceable
paths are listed in `native-libraries.json` (commonly under
`_internal/opencv_python_headless.libs/` on Linux, `cv2/.dylibs/` in macOS
bundles, or `cv2/` on Windows). Their exact source version for each target is
identified in the `ffmpeg` entry of that manifest and in the same-release
corresponding-source archive. macOS deliberately does **not** use the PyPI
OpenCV wheels: the audited ARM wheel links GPLv3 Homebrew FFmpeg 7.1.
Both Mac architectures instead compile the digest-pinned OpenCV 4.11.0.86
source distribution with FFmpeg and the entire videoio module disabled.
Only core, image-processing, image-codec, and Python modules are built; this
application reads still images and does not need video decoding.

`tools/build_mac_opencv.py` and `requirements-mac-opencv.txt` define the native
recipe and pinned builder environment. Run
`python tools/build_mac_opencv.py` on each Mac before `python tools/package.py`.
The recipe requires `uv` on PATH: it installs the builder dependencies, builds the
wheel with `uv build --no-build-isolation`, and installs it into the Python interpreter
running the recipe. The builder environment does not require pip.
The dependency inventory embeds the actual local wheel digest, original
sdist URL/digest, native-file hashes, CMake arguments, and runtime build
information rather than attributing the custom binary to a downloaded wheel.
The source asset includes the OpenCV sdist and both recipe files. Missing or
mismatched receipts, enabled FFmpeg/videoio, and FFmpeg/Homebrew loader imports
fail packaging; this does not relabel a GPL binary as LGPL.

The release archives are not signed/notarized. Do not disable operating
system-wide security protections. A replacement can fail if it is not
ABI-compatible or the platform loader resolves a different library; inspect
the manifest and the platform's loader diagnostics. System libraries supplied
by the operating system are not part of the replaceable bundle. These notes
describe the intended bundle layout but do not certify legal compliance.

The `source-materials` and build workflows fail if the pinned source archive
cannot be retrieved, if the source version does not match the build, if
required license material is missing, or if the native-file inventory leaves
a library without a known distribution/license owner. Automated checks are
not legal advice or legal certification.

Branch pushes and pull requests run the same four native builds, source-material
downloads, and final archive verification as tags, using a nonpublishing
`0.1.0.dev<run-number>` candidate. Manual candidates also run the complete gate.
Only a successful `vMAJOR.MINOR.PATCH` tag push can publish a GitHub Release,
and publication depends on the completed `validate-release` gate.

GitHub Actions uses pinned uv 0.12.3 to install dependencies into the pinned
Python 3.12.10 interpreter supplied by `actions/setup-python`. `uv pip install`
preserves the existing requirements-file and project dependency pins; it does not
use `uv.lock`. Tests and packaging run directly with that interpreter, so no
automatic project sync replaces the custom macOS OpenCV wheel before packaging.

Native ownership is matched by installed-distribution content hashes, not by
generic Qt/OpenCV filename guesses. The inventory preserves PyInstaller's
original source paths and hashes (macOS rewrites loader paths/signatures),
records loader linkage, and checks Qt's runtime version and FFmpeg's actual
version/license evidence against corresponding sources. A filename or ABI
number alone does not establish the FFmpeg source patch version.
