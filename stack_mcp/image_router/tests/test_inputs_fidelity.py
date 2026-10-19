"""Regression tests: input normalisation (EXIF orientation, unsupported formats, 16-bit greyscale),
aspect-ratio mismatches in the fidelity steps, and detect-strategy box coordinates."""

from __future__ import annotations

import asyncio
import base64
import io
from pathlib import Path

from PIL import Image, ImageOps, ImageStat

from stack_mcp.image_router import tools
from stack_mcp.image_router.imaging import (
    composite_preserving,
    fit_to_size,
    image_info,
    lanczos_resize,
    normalize_boxes,
    normalize_mask_output,
    normalize_raster_input,
    to_8bit,
)
from stack_mcp.image_router.providers.base import parse_boxes

from .conftest import OPENROUTER_URL, open_png, payload_of, png_bytes, rgba_cutout
from .fakes import FakeOpenRouter, body_of, chain


def call(fn, **kwargs) -> tuple[bool, dict]:
    result = asyncio.run(fn(**kwargs))
    return bool(result.is_error), payload_of(result)


def phone_jpeg() -> bytes:
    """Stored 60x40 (landscape) with EXIF Orientation=6: viewers show it 40x60 (portrait).

    The red stripe on the stored left edge is at the TOP of the displayed image.
    """
    im = Image.new("RGB", (60, 40), (255, 255, 255))
    im.paste((255, 0, 0), (0, 0, 20, 40))
    exif = Image.Exif()
    exif[0x0112] = 6
    buf = io.BytesIO()
    im.save(buf, "JPEG", exif=exif.tobytes(), quality=95)
    return buf.getvalue()


def decode_ref(url: str) -> Image.Image:
    assert url.startswith("data:image/")
    return open_png(base64.b64decode(url.split(",", 1)[1]))


# --- EXIF orientation -----------------------------------------------------------------------------------


def test_exif_orientation_is_applied_to_inputs():
    data = phone_jpeg()
    info = image_info(data)
    assert (info["width"], info["height"]) == (40, 60) and info["exif_orientation"] == 6 and info["stored_size"] == [60, 40]
    fixed, mime, notes = normalize_raster_input(data, "image/jpeg")
    im = open_png(fixed)
    assert mime == "image/jpeg" and im.size == (40, 60) and im.getexif().get(0x0112) in (None, 1)
    assert im.getpixel((20, 3))[0] > 200 and im.getpixel((20, 3))[1] < 60  # red stripe on top, as displayed
    assert any("orientation 6" in n for n in notes)
    assert normalize_raster_input(png_bytes(), "image/png") is None  # nothing to do


def test_phone_photo_tools_work_in_display_orientation(stack_env, mock_http, isolated):
    (isolated / "phone.jpg").write_bytes(phone_jpeg())
    is_error, info = call(tools.image_info, image="phone.jpg")
    assert not is_error and (info["width"], info["height"]) == (40, 60)

    stack_env.set(IMAGE_UPSCALE_API="local")
    is_error, payload = call(tools.image_upscale, image="phone.jpg", scale=2)
    assert not is_error, payload
    out = open_png(Path(payload["files"][0]["path"]).read_bytes()).convert("RGB")
    assert out.size == (80, 120)  # portrait, like the input as the user sees it
    assert out.getpixel((40, 5))[1] < 80 and out.getpixel((40, 110)) == (255, 255, 255)  # stripe still on top
    assert any("orientation" in n for n in payload["notes"])

    # a mask drawn on the displayed (40x60) image is accepted; the provider receives upright bytes
    stack_env.configure("EDIT", OPENROUTER_URL, "krea/k3-edit")
    mask = Image.new("L", (40, 60), 0)
    mask.paste(255, (10, 30, 30, 50))
    mask.save(isolated / "mask.png")
    fake = FakeOpenRouter(png_bytes(40, 60, (0, 255, 0)))
    mock_http(chain(fake))
    is_error, payload = call(tools.image_edit, image="phone.jpg", instruction="paint it green", mask="mask.png", feather=0)
    assert not is_error, payload
    sent = decode_ref(body_of(fake.requests[0])["input_references"][0]["image_url"]["url"]).convert("RGB")
    assert sent.size == (40, 60)
    result = open_png(Path(payload["files"][0]["path"]).read_bytes()).convert("RGB")
    assert result.size == (40, 60)
    for xy in [(2, 2), (20, 5), (35, 58), (5, 40)]:  # outside the mask: the upright source, unchanged
        assert result.getpixel(xy) == sent.getpixel(xy)
    assert result.getpixel((20, 40)) == (0, 255, 0)


def test_remove_background_accepts_upright_cutout_of_phone_photo(stack_env, mock_http, isolated):
    (isolated / "phone.jpg").write_bytes(phone_jpeg())
    stack_env.configure_cutout(OPENROUTER_URL, "m")
    mock_http(chain(FakeOpenRouter(rgba_cutout(40, 60))))
    is_error, payload = call(tools.image_remove_background, image="phone.jpg")
    assert not is_error and not any("aspect ratio" in w for w in payload["warnings"]), payload
    assert open_png(Path(payload["files"][0]["path"]).read_bytes()).size == (40, 60)


# --- formats the routers do not accept ---------------------------------------------------------------------


def test_tiff_and_bmp_inputs_are_sent_as_png(stack_env, mock_http, isolated):
    stack_env.configure("EDIT", OPENROUTER_URL, "m")
    src = Image.new("RGB", (12, 8), (10, 120, 200))
    src.save(isolated / "scan.tiff", "TIFF")
    src.save(isolated / "scan.bmp", "BMP")
    fake = FakeOpenRouter(png_bytes(12, 8))
    mock_http(chain(fake))
    for name in ("scan.tiff", "scan.bmp"):
        is_error, payload = call(tools.image_edit, image=name, instruction="x")
        assert not is_error, payload
        url = body_of(fake.requests[-1])["input_references"][0]["image_url"]["url"]
        assert url.startswith("data:image/png;base64,")
        assert decode_ref(url).convert("RGB").getpixel((3, 3)) == (10, 120, 200)
        assert any("re-encoded as PNG" in n for n in payload["notes"])


# --- 16-bit greyscale --------------------------------------------------------------------------------------


def gray16(w: int = 64, h: int = 32) -> bytes:
    im = Image.new("I;16", (w, h))
    for x in range(w):
        for y in range(h):
            im.putpixel((x, y), x * 1040)
    buf = io.BytesIO()
    im.save(buf, "PNG")
    return buf.getvalue()


def test_sixteen_bit_greyscale_is_scaled_not_clipped(stack_env, isolated):
    up = open_png(lanczos_resize(gray16(), (128, 64))).convert("L")
    mean = ImageStat.Stat(up).mean[0]
    white = up.histogram()[255] / (128 * 64)
    assert 110 < mean < 145 and white < 0.05, (mean, white)
    stack_env.set(IMAGE_UPSCALE_API="local")
    (isolated / "g16.png").write_bytes(gray16())
    is_error, payload = call(tools.image_upscale, image="g16.png", scale=2)
    assert not is_error and 110 < ImageStat.Stat(open_png(Path(payload["files"][0]["path"]).read_bytes()).convert("L")).mean[0] < 145


def test_composite_keeps_sixteen_bit_source_pixels_outside_the_mask():
    src = gray16()
    mask = Image.new("L", (64, 32), 0)
    mask.paste(255, (20, 8, 40, 24))
    out, _ = composite_preserving(src, png_bytes(64, 32, (0, 255, 0)), mask, feather=0)
    o = open_png(out).convert("RGB")
    raw = open_png(src)
    outside = [(x, y) for x in range(64) for y in range(32) if not (20 <= x < 40 and 8 <= y < 24)]
    # outside the mask: the 16-bit source scaled to 8 bits (v / 257), not clipped to white
    assert all(abs(o.getpixel(xy)[0] - raw.getpixel(xy) / 257) <= 1 for xy in outside)
    assert abs(to_8bit(raw).getpixel((63, 0)) - raw.getpixel((63, 0)) / 257) <= 1


# --- aspect-ratio mismatches ---------------------------------------------------------------------------------


def square_with_red_centre(size: int = 100) -> bytes:
    im = Image.new("RGB", (size, size), (0, 200, 0))
    im.paste((255, 0, 0), (40, 40, 60, 60))
    buf = io.BytesIO()
    im.save(buf, "PNG")
    return buf.getvalue()


def red_bbox(im: Image.Image) -> tuple[int, int, int, int]:
    rgb = im.convert("RGB")
    mask = Image.eval(rgb.split()[0], lambda v: 255 if v > 200 else 0)
    g = Image.eval(rgb.split()[1], lambda v: 255 if v < 60 else 0)
    from PIL import ImageChops

    return ImageChops.multiply(mask, g).getbbox()


def test_composite_does_not_stretch_another_aspect_ratio():
    src = Image.new("RGB", (300, 100), (50, 50, 50))
    buf = io.BytesIO()
    src.save(buf, "PNG")
    mask = Image.new("L", (300, 100), 255)
    out, stats = composite_preserving(buf.getvalue(), square_with_red_centre(), mask, feather=0)
    assert stats["aspect_mismatch"] is True and stats["fit"] == "cover-crop"
    x0, y0, x1, y1 = red_bbox(open_png(out))
    assert abs((x1 - x0) - (y1 - y0)) <= 2  # the square stays square (stretching made it 60x20)


def test_fit_to_size_and_mask_normalisation_do_not_stretch():
    data, stats = fit_to_size(square_with_red_centre(), (300, 100))
    assert stats["aspect_mismatch"] is True and open_png(data).size == (300, 100)
    x0, y0, x1, y1 = red_bbox(open_png(data))
    assert abs((x1 - x0) - (y1 - y0)) <= 2
    _, mstats = normalize_mask_output(png_bytes(100, 100, (255, 255, 255)), (300, 100))
    assert mstats["aspect_mismatch"] is True
    _, ok = normalize_mask_output(png_bytes(200, 200, (255, 255, 255)), (100, 100))
    assert "aspect_mismatch" not in ok


def test_tools_warn_about_aspect_mismatch(stack_env, mock_http, isolated):
    (isolated / "wide.png").write_bytes(png_bytes(300, 100, (50, 50, 50)))
    Image.new("L", (300, 100), 255).save(isolated / "all.png")
    for op in ("EDIT", "UPSCALE", "SEGMENT"):
        stack_env.configure(op, OPENROUTER_URL, "m")
    mock_http(chain(FakeOpenRouter(square_with_red_centre())))
    checks = [
        call(tools.image_edit, image="wide.png", instruction="x", mask="all.png"),
        call(tools.image_upscale, image="wide.png", scale=2),
        call(tools.image_segment, image="wide.png", prompt="the thing"),
    ]
    for is_error, payload in checks:
        assert not is_error, payload
        assert any("another aspect ratio" in w and "100x100" in w for w in payload["warnings"]), payload["warnings"]


# --- detect strategy coordinates -------------------------------------------------------------------------------


def test_normalize_boxes_reads_pixels_and_per_mille():
    assert normalize_boxes([(0.1, 0.2, 0.3, 0.4)], (400, 200)) == ([(0.1, 0.2, 0.3, 0.4)], "0-1")
    boxes, space = normalize_boxes([(120, 40, 260, 160)], (400, 200))
    assert space == "pixels" and boxes == [(0.3, 0.2, 0.65, 0.8)]
    boxes, space = normalize_boxes([(100, 200, 900, 800)], (400, 300))
    assert space == "0-1000" and boxes == [(0.1, 0.2, 0.9, 0.8)]
    # Gemini's native box_2d is [y_min, x_min, y_max, x_max] in per-mille
    assert parse_boxes({"objects": [{"box_2d": [200, 100, 800, 900]}]}) == [(0.1, 0.2, 0.9, 0.8)]


def test_detect_strategy_with_pixel_coordinates(stack_env, mock_http, isolated):
    stack_env.configure("SEGMENT", OPENROUTER_URL, "openai/gpt-5.4", params={"strategy": "detect"})
    (isolated / "src.png").write_bytes(png_bytes(400, 200))
    fake = FakeOpenRouter(chat='{"objects":[{"x_min":120,"y_min":40,"x_max":260,"y_max":160}]}')
    mock_http(chain(fake))
    is_error, payload = call(tools.image_segment, image="src.png", prompt="car")
    assert not is_error, payload
    assert "400x200 pixels" in body_of(fake.requests[0])["messages"][0]["content"][0]["text"]
    stats = payload["mask_stats"]
    assert stats["coordinates"] == "pixels" and 0.2 < stats["white_fraction"] < 0.3
    out = open_png(Path(payload["files"][0]["path"]).read_bytes())
    assert out.getpixel((190, 100)) == 255 and out.getpixel((50, 100)) == 0
    assert any("pixels coordinates" in n for n in payload["notes"])
    fake.chat = '{"objects":[{"x_min":5000,"y_min":5000,"x_max":6000,"y_max":6000}]}'
    is_error, payload = call(tools.image_segment, image="src.png", prompt="car")
    assert not is_error and payload["mask_stats"]["white_fraction"] == 0.0
    assert any("cover none" in w for w in payload["warnings"])


def test_exif_display_size_helper_matches_transpose():
    data = phone_jpeg()
    up = ImageOps.exif_transpose(Image.open(io.BytesIO(data)))
    from stack_mcp.image_router.imaging import display_size

    assert display_size(data) == up.size
