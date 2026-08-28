#!/usr/bin/env python
"""Build ``desktop/assets/algametrix.icns`` from the Windows icon.

    python scripts/make_icns.py

macOS wants an ``.icns`` where Windows wants an ``.ico``, and Apple's own tool
for making one (``iconutil``) runs only on macOS. This writes the container
directly, so the same icon can be produced on any machine and the two platforms
cannot drift into showing different marks.

**One source, two containers.** Every layer comes from
``desktop/assets/algametrix.ico``, which already holds real 16, 32, 48, 64, 128
and 256 px renderings. A size the .ico has is copied out of it rather than
resampled, so whatever tuning went into the small sizes survives.

**It stops at 256 px.** That is the largest real rendering that exists; there is
no vector master. Writing 512 and 1024 px entries would mean upscaling, which
invents detail macOS can invent for itself when it needs it. The set below is
what ``iconutil`` emits for an .iconset containing everything up to
``icon_256x256`` - complete for the Dock, the Finder and the app switcher, and
honest about where it ends.

The file format: the 8-byte header ``icns`` + total length, then one chunk per
entry, each of them a 4-byte type, a big-endian length that counts its own
8-byte header, and a PNG. PNG payloads in these types are what current
``iconutil`` writes, and macOS has read them since 10.7.
"""

from __future__ import annotations

import io
import struct
import sys
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "desktop" / "assets" / "algametrix.ico"
TARGET = ROOT / "desktop" / "assets" / "algametrix.icns"

#: ``(chunk type, pixel size)``, in the order ``iconutil`` writes them. Two
#: entries are 256 px on purpose: ``ic13`` is 128 pt at 2x and ``ic08`` is 256 pt
#: at 1x, and macOS picks between them by the display, not by the pixel count.
ENTRIES = (
    (b"icp4", 16),     # icon_16x16
    (b"ic11", 32),     # icon_16x16@2x
    (b"icp5", 32),     # icon_32x32
    (b"ic12", 64),     # icon_32x32@2x
    (b"ic07", 128),    # icon_128x128
    (b"ic13", 256),    # icon_128x128@2x
    (b"ic08", 256),    # icon_256x256
)


def _layers(path: Path) -> dict[int, Image.Image]:
    """Every square RGBA rendering the .ico actually contains, by pixel size."""
    ico = Image.open(path)
    out: dict[int, Image.Image] = {}
    for width, height in sorted(ico.info.get("sizes", [])):
        if width != height:
            continue
        ico.size = (width, height)
        ico.load()
        out[width] = ico.convert("RGBA").copy()
    if not out:
        raise SystemExit(f"{path} holds no square icon layer")
    return out


def _at(layers: dict[int, Image.Image], size: int) -> Image.Image:
    """The layer at ``size``, resampled from the largest one if it is missing."""
    if size in layers:
        return layers[size]
    return layers[max(layers)].resize((size, size), Image.LANCZOS)


def build(source: Path = SOURCE, target: Path = TARGET) -> Path:
    layers = _layers(source)
    chunks: list[bytes] = []
    for kind, size in ENTRIES:
        buf = io.BytesIO()
        # optimize=True and no ancillary chunks: the same input gives the same
        # bytes on every machine, so the committed .icns can be regenerated and
        # compared rather than taken on trust.
        _at(layers, size).save(buf, format="PNG", optimize=True)
        payload = buf.getvalue()
        chunks.append(kind + struct.pack(">I", len(payload) + 8) + payload)

    body = b"".join(chunks)
    target.write_bytes(b"icns" + struct.pack(">I", len(body) + 8) + body)
    return target


def main() -> int:
    out = build()
    sizes = ", ".join(f"{kind.decode()}:{size}" for kind, size in ENTRIES)
    print(f"wrote {out.relative_to(ROOT)}  ({out.stat().st_size:,} bytes; {sizes})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
