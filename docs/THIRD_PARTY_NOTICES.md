# Third-party notices

SplitScan's own source code and artwork are licensed under the MIT License in
the accompanying `LICENSE` file. That license does not replace or override
third-party terms.

Each native release includes `dependency-inventory.json`,
`native-libraries.json`, and the exact license texts available from its pinned
runtime distributions under `THIRD_PARTY_NOTICES/distributions/`. These files
identify package versions, package/source provenance, SHA-256 digests of
native files, and the license notice associated with each packaged native
file.

## Qt for Python and Qt

The PySide6-Essentials, Shiboken, and Qt libraries in the desktop application
are distributed under the applicable LGPL-3.0 terms. The included LGPL and
GPL license texts are in `THIRD_PARTY_NOTICES/licenses/`. The same GitHub
Release contains `splitscan-v<VERSION>-corresponding-source.zip`: it includes
the source archives for the matching Qt and Qt for Python releases, with
SHA-256 digests and origin URLs. Do not treat an upstream project homepage as
a substitute for that version-matched source asset.

The Qt libraries are kept as separate, dynamically loaded files in the
PyInstaller onedir layout. The `native-libraries.json` in each archive lists
their exact paths and hashes. A user exercising the LGPL replacement option
must replace the relevant shared libraries in place with interface-compatible
builds and preserve the recorded layout. On Windows and Linux the support
files are beside the launcher in `_internal/`; in macOS bundles they are
under `SplitScan.app/Contents/Frameworks/` and the paths recorded in the
manifest. Recheck the platform loader's library resolution after replacement.
macOS replacement can invalidate local ad-hoc signatures; see
[distribution instructions](DISTRIBUTION.md) for re-signing the modified
bundle. These instructions and the automated inventory are compliance
materials, not legal certification.

## Other included components

- NumPy is distributed under its BSD license and includes its own attribution
  and third-party license texts.
- OpenCV is distributed under Apache-2.0; the headless wheel's own third-party
  notices are included with its license files. Its platform wheel also
  bundles FFmpeg under LGPL-2.1. The corresponding-source asset includes the
  exact FFmpeg 4.4.5 (Windows), 7.1.1 (macOS), and 5.1.6 (Linux x64) releases
  mapped to the native libraries in these artifacts, plus the OpenCV
  third-party wrapper source/build metadata. `native-libraries.json` gives
  target-specific shared-library paths.
- Sentry's Python SDK is distributed under MIT.
- The Python runtime uses the Python Software Foundation License.
- The PyInstaller bootloader is distributed under GPL-2.0-or-later with the
  PyInstaller bootloader exception; its exact source release is included in
  the corresponding-source archive.

The inventory is generated from the versions and files in each native build.
It does not establish that every native component may be redistributed, and
it is not a substitute for reviewing the source archive, license texts, or
platform-specific system dependencies.
