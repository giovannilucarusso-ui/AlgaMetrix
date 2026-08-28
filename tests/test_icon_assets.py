"""The macOS icon is the Windows icon, in the container macOS reads.

``desktop/assets/algametrix.icns`` is committed rather than built during
packaging, so it has to be checked like any other committed artifact: that it is
a valid icns, that it holds the sizes the Dock and the Finder ask for, and above
all that its pixels are the ones in ``algametrix.ico``. Two platforms showing
two different marks is the failure this prevents, and it is one nobody notices
until a screenshot goes into a paper.

The comparison is on image content, never on bytes. A different Pillow release
may encode the same pixels into a different PNG, and a test that failed for that
would be measuring the encoder rather than the icon.
"""

from __future__ import annotations

import importlib.util
import io
import struct
from pathlib import Path

import pytest

from PIL import Image, ImageChops

ROOT = Path(__file__).resolve().parents[1]
ICO = ROOT / "desktop" / "assets" / "algametrix.ico"
ICNS = ROOT / "desktop" / "assets" / "algametrix.icns"


def _load_maker():
    spec = importlib.util.spec_from_file_location(
        "make_icns", ROOT / "scripts" / "make_icns.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


make_icns = _load_maker()


def _entries(path: Path) -> list[tuple[bytes, Image.Image]]:
    """``(chunk type, image)`` for every entry, parsed from the file itself."""
    raw = path.read_bytes()
    assert raw[:4] == b"icns", "not an icns file"
    assert struct.unpack(">I", raw[4:8])[0] == len(raw), (
        "the length in the header does not match the file")
    out = []
    offset = 8
    while offset < len(raw):
        kind = raw[offset:offset + 4]
        length = struct.unpack(">I", raw[offset + 4:offset + 8])[0]
        assert 8 < length <= len(raw) - offset, f"chunk {kind!r} has a bad length"
        out.append((kind, Image.open(io.BytesIO(raw[offset + 8:offset + length]))))
        offset += length
    return out


def test_the_icns_is_committed_and_parses():
    assert ICNS.exists(), "run python scripts/make_icns.py"
    entries = _entries(ICNS)
    assert [k for k, _ in entries] == [k for k, _ in make_icns.ENTRIES]
    for (kind, image), (_, size) in zip(entries, make_icns.ENTRIES):
        assert image.format == "PNG", f"{kind!r} is not a PNG payload"
        assert image.size == (size, size), kind


def test_pillow_reads_it_back_as_an_icns():
    """An independent reader agrees it is an icon, at the sizes and scales meant."""
    with Image.open(ICNS) as im:
        assert im.format == "ICNS"
        # (points, points, scale): 16 and 32 at 1x and 2x, 128 at 1x and 2x, 256.
        assert sorted(im.info["sizes"]) == [
            (16, 16, 1), (16, 16, 2), (32, 32, 1), (32, 32, 2),
            (128, 128, 1), (128, 128, 2), (256, 256, 1),
        ]


def test_every_layer_is_the_windows_icon_at_that_size():
    ico_layers = make_icns._layers(ICO)
    for kind, image in _entries(ICNS):
        size = image.size[0]
        if size not in ico_layers:
            continue                      # derived by resampling; nothing to compare
        diff = ImageChops.difference(image.convert("RGBA"), ico_layers[size])
        assert diff.getbbox() is None, (
            f"the {size}px layer of the .icns differs from the .ico's; the two "
            "platforms would show different icons")


def test_rebuilding_reproduces_the_committed_icon(tmp_path):
    """What the script makes now is the icon in the repository."""
    rebuilt = make_icns.build(ICO, tmp_path / "algametrix.icns")
    committed = _entries(ICNS)
    fresh = _entries(rebuilt)
    assert [k for k, _ in fresh] == [k for k, _ in committed]
    for (kind, a), (_, b) in zip(fresh, committed):
        diff = ImageChops.difference(a.convert("RGBA"), b.convert("RGBA"))
        assert diff.getbbox() is None, (
            f"{kind.decode()} in the committed .icns is not what make_icns.py "
            "produces; regenerate it")


def test_the_spec_picks_the_icon_by_platform():
    """One spec, both containers - and neither hard-coded to the other's."""
    spec = (ROOT / "AlgaMetrix.spec").read_text(encoding="utf-8")
    assert "algametrix.icns' if MACOS else 'desktop/assets/algametrix.ico'" in spec
    # UPX rewrites Mach-O headers and breaks the signature an Apple Silicon
    # bundle needs to launch at all.
    assert "USE_UPX = not MACOS" in spec


@pytest.mark.parametrize("name", ["macos-release.yml", "windows-release.yml"])
def test_the_release_workflows_name_their_platform(name):
    """Three builds land on one release page; every asset says which it is."""
    text = (ROOT / ".github" / "workflows" / name).read_text(encoding="utf-8")
    platform = "macos" if name.startswith("macos") else "windows"
    assert f"SHA256SUMS-{platform}" in text
    assert f"smoke-{platform}" in text
