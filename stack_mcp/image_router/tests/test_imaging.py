"""Mask conventions, dimension checks and output normalisation."""

from __future__ import annotations

import io

import pytest
from PIL import Image

from stack_mcp.image_router.imaging import (
    MaskError,
    boxes_to_mask,
    canonical_mask,
    composite_preserving,
    convert_canonical,
    ensure_png_rgba,
    feathered_mask,
    fit_to_size,
    has_transparency,
    image_info,
    lanczos_resize,
    mask_for_provider,
    normalize_mask_output,
    transfer_alpha,
    union_masks,
)

from .conftest import pattern_png, png_bytes, rgba_cutout


def _img(data: bytes) -> Image.Image:
    im = Image.open(io.BytesIO(data))
    im.load()
    return im


def _half_mask(mode: str = "L", w: int = 8, h: int = 8) -> bytes:
    """Left half white (edit), right half black (keep)."""
    im = Image.new(mode, (w, h), 0 if mode == "L" else (0, 0, 0))
    for x in range(w // 2):
        for y in range(h):
            im.putpixel((x, y), 255 if mode == "L" else (255, 255, 255))
    buf = io.BytesIO()
    im.save(buf, format="PNG")
    return buf.getvalue()


def test_canonical_from_grayscale_and_rgb():
    for mode in ("L", "RGB"):
        m = canonical_mask(_half_mask(mode))
        assert m.mode == "L"
        assert m.getpixel((0, 0)) == 255 and m.getpixel((7, 0)) == 0


def test_canonical_threshold_at_128():
    im = Image.new("L", (2, 1))
    im.putpixel((0, 0), 127)
    im.putpixel((1, 0), 128)
    m = canonical_mask(im)
    assert m.getpixel((0, 0)) == 0  # keep
    assert m.getpixel((1, 0)) == 255  # edit


def test_canonical_from_rgba_transparent_means_edit():
    im = Image.new("RGBA", (4, 4), (0, 0, 0, 255))  # opaque black everywhere (keep)
    im.putpixel((1, 1), (0, 0, 0, 0))  # transparent pixel -> edit, colour irrelevant
    im.putpixel((2, 2), (255, 255, 255, 255))  # opaque white: still keep in alpha mode
    m = canonical_mask(im)
    assert m.getpixel((1, 1)) == 255
    assert m.getpixel((2, 2)) == 0
    assert m.getpixel((0, 0)) == 0


def test_rgba_without_transparency_falls_back_to_luminance():
    im = Image.new("RGBA", (2, 1), (0, 0, 0, 255))
    im.putpixel((1, 0), (255, 255, 255, 255))
    m = canonical_mask(im)
    assert (m.getpixel((0, 0)), m.getpixel((1, 0))) == (0, 255)


def test_provider_conventions():
    canon = canonical_mask(_half_mask())
    white = convert_canonical(canon, "white-edit")
    black = convert_canonical(canon, "black-edit")
    alpha = convert_canonical(canon, "alpha-transparent")
    assert white.getpixel((0, 0)) == 255 and white.getpixel((7, 0)) == 0
    assert black.getpixel((0, 0)) == 0 and black.getpixel((7, 0)) == 255  # inverted
    assert alpha.mode == "RGBA"
    assert alpha.getpixel((0, 0))[3] == 0  # edit area fully transparent
    assert alpha.getpixel((7, 0))[3] == 255  # keep area opaque


def test_mask_for_provider_round_trip_png():
    out = mask_for_provider(_half_mask(), (8, 8), "alpha-transparent")
    im = _img(out)
    assert im.format == "PNG" and im.mode == "RGBA" and im.size == (8, 8)
    assert has_transparency(out)


def test_dimension_mismatch_is_rejected_with_hint():
    with pytest.raises(MaskError) as exc:
        mask_for_provider(_half_mask(w=8, h=8), (16, 16), "white-edit")
    assert "resize_mask=true" in str(exc.value)
    assert "8x8" in str(exc.value) and "16x16" in str(exc.value)


def test_dimension_resize_uses_nearest_and_stays_binary():
    out = mask_for_provider(_half_mask(w=8, h=8), (16, 12), "white-edit", resize=True)
    im = _img(out)
    assert im.size == (16, 12)
    assert set(im.getextrema()) <= {0, 255}
    assert im.getpixel((0, 0)) == 255 and im.getpixel((15, 0)) == 0


def test_empty_mask_rejected():
    with pytest.raises(MaskError, match="selects nothing"):
        mask_for_provider(png_bytes(4, 4, 0, "L"), (4, 4), "white-edit")


def test_unknown_convention():
    with pytest.raises(MaskError):
        convert_canonical(canonical_mask(_half_mask()), "purple-edit")


def test_normalize_mask_output_from_cutout_and_colour_preview():
    data, stats = normalize_mask_output(rgba_cutout(8, 8), (8, 8))
    m = _img(data)
    assert m.mode == "L" and m.getpixel((4, 4)) == 255 and m.getpixel((0, 0)) == 0
    assert stats["binary_fraction"] == 1.0
    # a pure-blue preview on black still counts as "object" (max channel, not luminance)
    blue = Image.new("RGB", (4, 4), (0, 0, 0))
    blue.putpixel((1, 1), (0, 0, 255))
    buf = io.BytesIO()
    blue.save(buf, format="PNG")
    data2, stats2 = normalize_mask_output(buf.getvalue(), (8, 8))
    m2 = _img(data2)
    assert m2.size == (8, 8) and m2.getpixel((2, 2)) == 255 and m2.getpixel((7, 7)) == 0
    assert stats2["resized_to"] == [8, 8]
    assert sum(m2.histogram()[1:255]) == 0  # resized grey levels are thresholded back to binary
    inv, _ = normalize_mask_output(buf.getvalue(), (4, 4), invert=True)
    inv_im = _img(inv)
    assert inv_im.getpixel((1, 1)) == 0 and inv_im.getpixel((0, 0)) == 255


def test_normalize_mask_flags_pictures():
    _, stats = normalize_mask_output(pattern_png(32, 32), (32, 32))
    assert stats["binary_fraction"] < 0.8


def test_union_masks():
    a, _ = normalize_mask_output(_half_mask(), (8, 8))
    b, _ = normalize_mask_output(png_bytes(8, 8, (255, 255, 255)), (8, 8))
    u = _img(union_masks([a, b], (8, 8)))
    assert u.getextrema() == (255, 255)


def test_boxes_to_mask():
    m = _img(boxes_to_mask((20, 10), [(0.5, 0.0, 1.0, 0.5), (1.2, -1, 1.5, 0)]))  # 2nd box is clipped away
    assert m.getpixel((10, 0)) == 255 and m.getpixel((19, 4)) == 255
    assert m.getpixel((9, 0)) == 0 and m.getpixel((10, 5)) == 0


def test_feather_is_inward_only():
    m = Image.new("L", (20, 20), 0)
    m.paste(255, (5, 5, 15, 15))
    f = feathered_mask(m, 2.0)
    assert f.getpixel((4, 10)) == 0 and f.getpixel((0, 0)) == 0  # outside stays exactly 0
    assert 0 < f.getpixel((5, 10)) < 255 and f.getpixel((10, 10)) == 255


def test_composite_preserving_keeps_outside_pixels():
    src = pattern_png(24, 16)
    m = Image.new("L", (24, 16), 0)
    m.paste(255, (6, 4, 18, 12))
    out, stats = composite_preserving(src, png_bytes(48, 32, (0, 255, 0)), m, feather=1.0)
    o, s = _img(out).convert("RGB"), _img(src).convert("RGB")
    assert o.size == (24, 16)
    for x in range(24):
        for y in range(16):
            if not (6 <= x < 18 and 4 <= y < 12):
                assert o.getpixel((x, y)) == s.getpixel((x, y))
    assert o.getpixel((12, 8)) == (0, 255, 0)
    assert stats["resized_to"] == [24, 16] and stats["drift_outside_mask"] > 0


def test_transfer_alpha_onto_original_pixels_and_drift():
    src = pattern_png(16, 16)
    out, stats = transfer_alpha(src, rgba_cutout(32, 32, color=tuple(_img(src).convert("RGB").getpixel((8, 8)))))
    o = _img(out)
    assert o.mode == "RGBA" and o.size == (16, 16)
    assert o.getpixel((8, 8))[:3] == _img(src).convert("RGB").getpixel((8, 8)) and o.getpixel((8, 8))[3] == 255
    assert o.getpixel((0, 0))[3] == 0
    assert stats["drift"] >= 0 and 0 < stats["opaque_fraction"] < 1
    none, why = transfer_alpha(src, png_bytes(16, 16))
    assert none is None and "no transparency" in why["reason"]
    none, why = transfer_alpha(src, rgba_cutout(32, 16))
    assert none is None and "aspect ratio" in why["reason"]


def test_lanczos_and_fit_to_size():
    up = _img(lanczos_resize(rgba_cutout(8, 6), (20, 15)))
    assert up.size == (20, 15) and up.mode == "RGBA"
    data, stats = fit_to_size(png_bytes(10, 10), (30, 30))
    assert _img(data).size == (30, 30) and stats["resized_to"] == [30, 30]


def test_image_info_alpha_fields():
    info = image_info(rgba_cutout(8, 8))
    assert info["width"] == 8 and info["has_alpha"] and info["alpha_used"] and info["format"] == "PNG"
    assert info["transparent_fraction"] == 0.75
    info = image_info(png_bytes(4, 4))
    assert not info["has_alpha"] and not info["alpha_used"] and info["mode"] == "RGB"


def test_ensure_png_rgba_from_jpeg():
    buf = io.BytesIO()
    Image.new("RGB", (5, 3), (10, 20, 30)).save(buf, format="JPEG")
    out = _img(ensure_png_rgba(buf.getvalue()))
    assert out.format == "PNG" and out.mode == "RGBA" and out.size == (5, 3)
