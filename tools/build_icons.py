"""Render the shared SplitScan brand mark into native executable/bundle icons."""

from __future__ import annotations

import struct
from pathlib import Path

from PySide6.QtCore import QBuffer, QIODevice
from PySide6.QtGui import QImage, QPainter
from PySide6.QtSvg import QSvgRenderer

ROOT = Path(__file__).resolve().parents[1]


def write_icons(directory: Path) -> None:
    renderer = QSvgRenderer(str(ROOT / "src/photo_splitter/assets/splitscan.svg"))
    if not renderer.isValid():
        raise RuntimeError("Could not load the SplitScan application icon.")

    def png(size: int) -> bytes:
        image = QImage(size, size, QImage.Format.Format_ARGB32)
        image.fill(0)
        painter = QPainter(image)
        renderer.render(painter)
        painter.end()
        buffer = QBuffer()
        buffer.open(QIODevice.OpenModeFlag.WriteOnly)
        if not image.save(buffer, "PNG"):
            raise RuntimeError(f"Could not encode the {size}px application icon.")
        return bytes(buffer.data())

    directory.mkdir(parents=True, exist_ok=True)
    sizes = (16, 24, 32, 48, 64, 128, 256)
    images = [png(size) for size in sizes]
    offset = 6 + 16 * len(sizes)
    entries = []
    for size, image in zip(sizes, images):
        entries.append(struct.pack(
            "<BBBBHHII", size % 256, size % 256, 0, 0, 1, 32, len(image), offset
        ))
        offset += len(image)
    (directory / "splitscan.ico").write_bytes(
        struct.pack("<HHH", 0, 1, len(sizes)) + b"".join(entries) + b"".join(images)
    )
    chunks = []
    for kind, size in ((b"ic07", 128), (b"ic08", 256), (b"ic09", 512), (b"ic10", 1024)):
        image = png(size)
        chunks.append(kind + struct.pack(">I", 8 + len(image)) + image)
    payload = b"".join(chunks)
    (directory / "splitscan.icns").write_bytes(b"icns" + struct.pack(">I", 8 + len(payload)) + payload)
