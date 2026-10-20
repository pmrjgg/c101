"""Pillow helpers: info, mask conventions, mask normalisation and fidelity post-processing.

Canonical mask (inside the server): a single-channel image where WHITE marks the
region to edit and BLACK the region to keep. Callers may hand in:

* L / RGB / P masks  -> luminance thresholded at 128 (>= 128 is "edit");
* RGBA / LA masks whose alpha has transparent pixels -> transparent = edit
  (the OpenAI convention), regardless of colour.

Adapters want one of three conventions:

* ``white-edit``        L PNG, white = edit           (most inpainting models)
* ``black-edit``        L PNG, black = edit           (Ideogram edit)
* ``alpha-transparent`` RGBA PNG, edit alpha 0, keep alpha 255 (OpenAI GPT Image)

Fidelity post-processing (deterministic, local; never a provider fallback):

* :func:`composite_preserving` - masked edits: ``out = src*(1-m) + result*m`` with
  the canonical mask feathered *inwards*, so pixels outside the mask are unchanged.
* :func:`transfer_alpha` - background removal: the model's alpha is put onto the
  ORIGINAL pixels; RGB drift inside the alpha is measured and reported.
* :func:`fit_to_size` / :func:`lanczos_resize` - exact output sizes (upscale).

A model result whose aspect ratio differs from the source (more than 2%) is never stretched
into the source frame: it is scaled to cover the frame and centre-cropped, and the stats say
``aspect_mismatch`` so the tools can warn. Inputs are normalised before any processing:
EXIF orientation is applied (:func:`normalize_raster_input`) and 16/32-bit greyscale is
scaled to 8 bits (:func:`to_8bit`) instead of being clipped.
"""

from __future__ import annotations

import io as _stdio
from collections.abc import Iterable
from typing import Any, Literal

from PIL import Image, ImageChops, ImageFilter, ImageOps, ImageStat

MaskConvention = Literal["white-edit", "black-edit", "alpha-transparent"]
MASK_CONVENTIONS: tuple[str, ...] = ("white-edit", "black-edit", "alpha-transparent")

# Pillow refuses absurdly large images by default; keep that guard but allow 8K x 8K.
Image.MAX_IMAGE_PIXELS = 8192 * 8192 * 2

# Mean absolute RGB difference (0-255) above which a "faithful" result is flagged as drifted.
DRIFT_WARN = 18.0
# Relative aspect-ratio difference above which a model result is not the source's framing.
ASPECT_TOLERANCE = 0.02
# Raster formats the routers accept as input images (OpenRouter input_references: png, jpeg,
# webp, gif; the OpenAI edits endpoint: png, webp, jpg). Anything else is re-encoded as PNG.
PROVIDER_INPUT_MIMES = frozenset({"image/png", "image/jpeg", "image/webp", "image/gif"})
EXIF_ORIENTATION = 0x0112


class MaskError(ValueError):
    """The mask cannot be used with the image as given."""


class ImageDataError(ValueError):
    """Bytes that should be an image are not a readable raster."""


def open_image(data: bytes) -> Image.Image:
    try:
        im = Image.open(_stdio.BytesIO(data))
        im.load()
    except Exception as exc:  # UnidentifiedImageError, truncated data, decompression bomb
        raise ImageDataError(f"not a readable raster image ({type(exc).__name__}: {exc})") from None
    return im


def image_size(data: bytes) -> tuple[int, int]:
    """Stored pixel size. Inputs reach the fidelity steps already upright (see
    :func:`normalize_raster_input`); use :func:`display_size` for a file as viewers show it."""
    try:
        with Image.open(_stdio.BytesIO(data)) as im:
            return im.size
    except Exception as exc:  # UnidentifiedImageError, truncated data, decompression bomb
        raise ImageDataError(f"not a readable raster image ({type(exc).__name__}: {exc})") from None


def exif_orientation(im: Image.Image) -> int:
    """The EXIF Orientation tag (1 = upright; 2-8 = mirrored / rotated), 1 when absent or invalid."""
    try:
        value = int(im.getexif().get(EXIF_ORIENTATION, 1) or 1)
    except Exception:
        return 1
    return value if 1 <= value <= 8 else 1


def display_size(data: bytes) -> tuple[int, int]:
    """Size as viewers show the file: width and height swapped for EXIF orientations 5-8."""
    try:
        with Image.open(_stdio.BytesIO(data)) as im:
            w, h = im.size
            return (h, w) if exif_orientation(im) in (5, 6, 7, 8) else (w, h)
    except Exception as exc:
        raise ImageDataError(f"not a readable raster image ({type(exc).__name__}: {exc})") from None


def to_8bit(im: Image.Image) -> Image.Image:
    """16/32-bit greyscale (I;16*, I, F) scaled to an 8-bit L image; other modes unchanged.

    Pillow's convert('L'/'RGB') clips these modes instead of scaling them, which turns a
    16-bit image almost entirely white.
    """
    mode = im.mode
    if mode.startswith("I;16"):
        return im.convert("I").point(lambda v: v * (1 / 257)).convert("L")
    if mode == "I":
        hi = im.getextrema()[1]
        scale = 1.0 if hi <= 255 else (1 / 257 if hi <= 65535 else 255.0 / hi)
        return im.point(lambda v: v * scale).convert("L")
    if mode == "F":
        hi = im.getextrema()[1]
        scale = 255.0 if hi <= 1.0 else (1.0 if hi <= 255.0 else (1 / 257 if hi <= 65535 else 255.0 / hi))
        return im.point(lambda v: v * scale).convert("L")
    return im


def as_mode(im: Image.Image, mode: str) -> Image.Image:
    """``im.convert(mode)`` that scales high-bit-depth greyscale instead of clipping it."""
    im = to_8bit(im)
    return im if im.mode == mode else im.convert(mode)


def _png_ready(im: Image.Image) -> Image.Image:
    """A mode PNG can store (8-bit, keeping alpha when present)."""
    im = to_8bit(im)
    if im.mode in ("1", "L", "LA", "RGB", "RGBA", "P"):
        return im
    return im.convert("RGBA" if _alpha_channel(im) is not None else "RGB")


def to_png_bytes(im: Image.Image, **save: Any) -> bytes:
    buf = _stdio.BytesIO()
    im.save(buf, format="PNG", optimize=False, **save)
    return buf.getvalue()


def _alpha_channel(im: Image.Image) -> Image.Image | None:
    """Alpha channel if the image carries one (incl. palette transparency)."""
    if im.mode == "P" and "transparency" in im.info:
        im = im.convert("RGBA")
    if im.mode in ("RGBA", "LA", "PA"):
        return im.getchannel("A")
    if im.mode == "RGBa":
        return im.convert("RGBA").getchannel("A")
    return None


def has_alpha_channel(im: Image.Image) -> bool:
    return _alpha_channel(im) is not None


def has_transparency(data_or_image: bytes | Image.Image) -> bool:
    im = open_image(data_or_image) if isinstance(data_or_image, bytes) else data_or_image
    alpha = _alpha_channel(im)
    return alpha is not None and alpha.getextrema()[0] < 255


def image_info(data: bytes) -> dict[str, Any]:
    """Size (as displayed: EXIF orientation applied), mode, alpha, format and a few extras."""
    im = open_image(data)
    alpha = _alpha_channel(im)
    orientation = exif_orientation(im)
    w, h = (im.height, im.width) if orientation in (5, 6, 7, 8) else (im.width, im.height)
    info: dict[str, Any] = {
        "width": w,
        "height": h,
        "mode": im.mode,
        "format": im.format,
        "has_alpha": alpha is not None,
        "alpha_used": bool(alpha is not None and alpha.getextrema()[0] < 255),
    }
    if orientation != 1:
        info["exif_orientation"] = orientation
        info["stored_size"] = [im.width, im.height]
    if alpha is not None:
        hist = alpha.histogram()
        total = im.width * im.height or 1
        info["transparent_fraction"] = round(hist[0] / total, 4)
        info["opaque_fraction"] = round(hist[255] / total, 4)
    frames = getattr(im, "n_frames", 1)
    if frames and frames > 1:
        info["frames"] = frames
    dpi = im.info.get("dpi")
    if dpi:
        info["dpi"] = [round(float(v), 2) for v in dpi]
    if im.info.get("icc_profile"):
        info["icc_profile"] = True
    return info


def normalize_raster_input(data: bytes, mime: str | None) -> tuple[bytes, str, list[str]] | None:
    """Make a raster input safe for providers and for the local fidelity steps, or None if it is.

    * EXIF orientation 2-8 is applied (the pixels become upright, as viewers show the file), so
      sizes, masks, composites and the bytes a provider receives all match what the user sees;
    * formats the routers do not accept (TIFF, BMP, AVIF, HEIC, ICO, ...) become PNG.

    Re-encoding keeps the ICC profile; JPEG sources stay JPEG (quality 95, no chroma
    subsampling) so uploads stay small, everything else becomes PNG. Returns (bytes, mime,
    notes) of the new file.
    """
    im = open_image(data)
    notes: list[str] = []
    orientation = exif_orientation(im)
    if orientation != 1:
        im = ImageOps.exif_transpose(im)
        notes.append(f"EXIF orientation {orientation} applied: the image is processed upright ({im.width}x{im.height})")
    unsupported = (mime or "") not in PROVIDER_INPUT_MIMES
    if unsupported:
        notes.append(f"{mime or 'unknown format'} input re-encoded as PNG (routers accept PNG, JPEG, WebP and GIF)")
    if orientation == 1 and not unsupported:
        return None
    icc = im.info.get("icc_profile")
    if mime == "image/jpeg" and not unsupported and im.mode in ("L", "RGB", "CMYK"):
        buf = _stdio.BytesIO()
        save: dict[str, Any] = {"quality": 95, "subsampling": 0}
        if icc:
            save["icc_profile"] = icc
        im.save(buf, format="JPEG", **save)
        return buf.getvalue(), "image/jpeg", notes
    return to_png_bytes(_png_ready(im), **({"icc_profile": icc} if icc else {})), "image/png", notes


# --- masks ------------------------------------------------------------------------------------


def _threshold(gray: Image.Image, cut: int = 128) -> Image.Image:
    return gray.point(lambda v: 255 if v >= cut else 0, mode="L")


def canonical_mask(data_or_image: bytes | Image.Image) -> Image.Image:
    """Return an L image, 255 = edit, 0 = keep (see module docstring)."""
    im = open_image(data_or_image) if isinstance(data_or_image, bytes) else data_or_image
    alpha = _alpha_channel(im)
    if alpha is not None and alpha.getextrema()[0] < 255:
        # transparent (alpha < 128) = edit
        return _threshold(ImageOps.invert(alpha))  # invert: alpha 0 -> 255
    return _threshold(as_mode(im, "L"))


def check_dimensions(mask: Image.Image, size: tuple[int, int], resize: bool = False) -> Image.Image:
    if mask.size == tuple(size):
        return mask
    if resize:
        return mask.resize(tuple(size), Image.Resampling.NEAREST)
    raise MaskError(
        f"mask is {mask.width}x{mask.height} but the image is {size[0]}x{size[1]}; "
        "resize the mask to the image size, or pass resize_mask=true to resize it (nearest-neighbour)"
    )


def convert_canonical(mask_l: Image.Image, convention: str) -> Image.Image:
    """Canonical L (white = edit) -> adapter convention image."""
    match convention:
        case "white-edit":
            return mask_l
        case "black-edit":
            return ImageOps.invert(mask_l)
        case "alpha-transparent":
            # Edit area alpha 0, keep area alpha 255; RGB carries the same mask for viewers.
            rgba = Image.new("RGBA", mask_l.size, (0, 0, 0, 255))
            rgba.putalpha(ImageOps.invert(mask_l))
            return rgba
        case _:
            raise MaskError(f"unknown mask convention {convention!r}; expected one of {MASK_CONVENTIONS}")


def prepare_mask(mask_data: bytes, image_size_wh: tuple[int, int], *, resize: bool = False) -> Image.Image:
    """Caller mask bytes -> canonical L mask of the image size (validated, non-empty)."""
    try:
        mask = canonical_mask(mask_data)
    except ImageDataError as exc:
        raise MaskError(f"mask is {exc}") from None
    mask = check_dimensions(mask, image_size_wh, resize)
    if mask.getextrema() == (0, 0):
        raise MaskError("mask selects nothing (no white / transparent pixels to edit)")
    return mask


def mask_for_provider(
    mask_data: bytes, image_size_wh: tuple[int, int], convention: str, *, resize: bool = False
) -> bytes:
    """Caller mask bytes -> PNG bytes in an adapter's convention, same size as the image."""
    return to_png_bytes(convert_canonical(prepare_mask(mask_data, image_size_wh, resize=resize), convention))


def normalize_mask_output(
    data: bytes, source_size: tuple[int, int] | None, *, invert: bool = False
) -> tuple[bytes, dict[str, Any]]:
    """Model mask output -> one white-on-black L PNG of the source size (white = object/region).

    Handles binary/greyscale masks, coloured previews on black (max channel, so a
    pure-blue overlay still counts) and RGBA cut-outs (opaque = object). The
    grey level is resized (bilinear) before thresholding at 128 so edges stay
    smooth; a model output of another aspect ratio is scaled to cover the source
    frame and centre-cropped (``aspect_mismatch`` in the stats), never stretched.
    Returns the PNG and stats (``binary_fraction`` < 0.8 means the model probably
    returned a picture rather than a mask).
    """
    im = open_image(data)
    alpha = _alpha_channel(im)
    if alpha is not None and alpha.getextrema()[0] < 255:
        gray = alpha  # opaque = object
    else:
        r, g, b = as_mode(im, "RGB").split()
        gray = ImageChops.lighter(ImageChops.lighter(r, g), b)
    hist = gray.histogram()
    total = gray.width * gray.height or 1
    binary_fraction = (sum(hist[:32]) + sum(hist[224:])) / total
    stats: dict[str, Any] = {"model_size": [im.width, im.height], "binary_fraction": round(binary_fraction, 3)}
    if source_size and gray.size != tuple(source_size):
        gray, mismatch = fit_image(gray, tuple(source_size), Image.Resampling.BILINEAR)
        stats["resized_to"] = list(source_size)
        if mismatch:
            stats["aspect_mismatch"] = True
    mask = _threshold(gray)
    if invert:
        mask = ImageOps.invert(mask)
    stats["white_fraction"] = round(mask.histogram()[255] / (mask.width * mask.height or 1), 4)
    return to_png_bytes(mask), stats


def union_masks(masks: list[bytes], source_size: tuple[int, int] | None) -> bytes:
    """Combine several normalised masks into one."""
    if not masks:
        raise MaskError("no masks to combine")
    acc: Image.Image | None = None
    for m in masks:
        im = as_mode(open_image(m), "L")
        if source_size and im.size != tuple(source_size):
            im = im.resize(tuple(source_size), Image.Resampling.NEAREST)
        acc = im if acc is None else ImageChops.lighter(acc, im)
    assert acc is not None
    return to_png_bytes(acc)


Box = tuple[float, float, float, float]


def normalize_boxes(boxes: list[Box], size: tuple[int, int]) -> tuple[list[Box], str]:
    """Detector boxes (x_min, y_min, x_max, y_max) -> 0-1 fractions, plus the coordinate space read.

    Boxes are asked for in 0-1, but vision models often answer in pixels or in 0-1000:

    * every value within [0, 1] (a little slack)         -> already fractions ("0-1");
    * x within the image width and y within its height    -> pixels ("pixels");
    * otherwise everything within 0-1000                  -> per-mille ("0-1000");
    * otherwise                                           -> pixels, clipped ("pixels (clipped)").

    Ambiguous replies (per-mille values that also fit in the image) are read as pixels; the
    space is reported so the caller can say how the reply was interpreted.
    """
    if not boxes:
        return [], "0-1"
    w, h = size
    values = [v for b in boxes for v in b]
    if min(values) >= -0.05 and max(values) <= 1.05:
        return list(boxes), "0-1"
    xs = [v for b in boxes for v in (b[0], b[2])]
    ys = [v for b in boxes for v in (b[1], b[3])]
    if max(xs) <= w * 1.02 and max(ys) <= h * 1.02:
        return [(x0 / w, y0 / h, x1 / w, y1 / h) for x0, y0, x1, y1 in boxes], "pixels"
    if max(values) <= 1000 * 1.02:
        return [tuple(v / 1000.0 for v in b) for b in boxes], "0-1000"  # type: ignore[misc]
    return [(x0 / w, y0 / h, x1 / w, y1 / h) for x0, y0, x1, y1 in boxes], "pixels (clipped)"


def white_fraction(mask_png: bytes) -> float:
    m = as_mode(open_image(mask_png), "L")
    return round(m.histogram()[255] / (m.width * m.height or 1), 4)


def boxes_to_mask(size: tuple[int, int], boxes: Iterable[tuple[float, float, float, float]]) -> bytes:
    """Normalised (0-1) boxes (x_min, y_min, x_max, y_max) -> white-on-black L PNG."""
    from PIL import ImageDraw

    w, h = size
    im = Image.new("L", (w, h), 0)
    draw = ImageDraw.Draw(im)
    for x0, y0, x1, y1 in boxes:
        x0, x1 = sorted((max(0.0, min(1.0, x0)), max(0.0, min(1.0, x1))))
        y0, y1 = sorted((max(0.0, min(1.0, y0)), max(0.0, min(1.0, y1))))
        draw.rectangle(
            (round(x0 * w), round(y0 * h), max(round(x0 * w), round(x1 * w) - 1), max(round(y0 * h), round(y1 * h) - 1)),
            fill=255,
        )
    return to_png_bytes(im)


# --- fidelity post-processing -------------------------------------------------------------


def feathered_mask(mask_l: Image.Image, feather: float) -> Image.Image:
    """Feather a binary mask INWARDS only: pixels outside the mask stay exactly 0.

    The ramp is about ``feather`` px wide (Gaussian sigma = feather / 2), from ~50% at the
    mask edge to 100% inside; nothing outside the mask is ever blended.
    """
    if feather <= 0:
        return mask_l
    blurred = mask_l.filter(ImageFilter.GaussianBlur(radius=feather / 2.0))
    return ImageChops.darker(mask_l, blurred)


def aspect_mismatch(target: tuple[int, int], actual: tuple[int, int], tolerance: float = ASPECT_TOLERANCE) -> bool:
    """True when ``actual`` (w, h) has another aspect ratio than ``target`` (relative difference)."""
    tr, ar = target[0] / target[1], actual[0] / actual[1]
    return abs(tr - ar) / tr > tolerance


def fit_cover(im: Image.Image, size: tuple[int, int], resample: Image.Resampling) -> Image.Image:
    """Scale ``im`` (keeping its aspect ratio) to cover ``size`` and centre-crop the overflow."""
    tw, th = size
    scale = max(tw / im.width, th / im.height)
    nw, nh = max(tw, round(im.width * scale)), max(th, round(im.height * scale))
    if (nw, nh) != im.size:
        im = im.resize((nw, nh), resample)
    left, top = (nw - tw) // 2, (nh - th) // 2
    return im.crop((left, top, left + tw, top + th))


def fit_image(im: Image.Image, size: tuple[int, int], resample: Image.Resampling) -> tuple[Image.Image, bool]:
    """``im`` at exactly ``size``: a plain resize when the aspect ratios agree (within 2%),
    else cover + centre-crop so nothing is stretched. Returns (image, aspect_mismatch)."""
    size = (int(size[0]), int(size[1]))
    if im.size == size:
        return im, False
    if aspect_mismatch(size, im.size):
        return fit_cover(im, size, resample), True
    return im.resize(size, resample), False


def mean_abs_diff(a: Image.Image, b: Image.Image, mask: Image.Image | None = None) -> float:
    """Mean absolute RGB difference (0-255), optionally only where ``mask`` is non-zero."""
    a_rgb, b_rgb = as_mode(a, "RGB"), as_mode(b, "RGB")
    if b_rgb.size != a_rgb.size:
        b_rgb, _ = fit_image(b_rgb, a_rgb.size, Image.Resampling.LANCZOS)
    diff = ImageChops.difference(a_rgb, b_rgb)
    if mask is not None:
        if mask.getbbox() is None:
            return 0.0
        stat = ImageStat.Stat(diff, mask=mask)
    else:
        stat = ImageStat.Stat(diff)
    return round(sum(stat.mean) / 3.0, 3)


def composite_preserving(
    src_data: bytes, result_data: bytes, mask_l: Image.Image, feather: float = 1.5
) -> tuple[bytes, dict[str, Any]]:
    """Masked-edit fidelity: fit the result to the source and composite through the mask.

    ``out = src*(1-m) + result*m`` with ``m`` the canonical mask feathered inwards, so
    every pixel outside the mask is byte-identical to the source (16-bit greyscale sources:
    identical to their 8-bit scaling). A result of another aspect ratio is scaled to cover
    the source and centre-cropped, never stretched; ``stats['aspect_mismatch']`` says so.
    """
    src = open_image(src_data)
    res = open_image(result_data)
    keep_alpha = has_alpha_channel(src) or has_alpha_channel(res)
    mode = "RGBA" if keep_alpha else "RGB"
    src_c = as_mode(src, mode)
    res_c = as_mode(res, mode)
    stats: dict[str, Any] = {"model_size": [res.width, res.height]}
    if res_c.size != src_c.size:
        res_c, mismatch = fit_image(res_c, src_c.size, Image.Resampling.LANCZOS)
        stats["resized_to"] = [src_c.width, src_c.height]
        if mismatch:
            stats["aspect_mismatch"] = True
            stats["fit"] = "cover-crop"
    if mask_l.size != src_c.size:
        mask_l = mask_l.resize(src_c.size, Image.Resampling.NEAREST)
    keep = ImageOps.invert(mask_l)
    stats["drift_outside_mask"] = mean_abs_diff(src_c, res_c, keep)
    stats["change_inside_mask"] = mean_abs_diff(src_c, res_c, mask_l)
    m = feathered_mask(mask_l, feather)
    out = Image.composite(res_c, src_c, m)
    stats["feather_px"] = feather
    return to_png_bytes(out), stats


def transfer_alpha(src_data: bytes, result_data: bytes) -> tuple[bytes | None, dict[str, Any]]:
    """Background-removal fidelity: the model's alpha on the ORIGINAL pixels.

    Returns (png, stats). ``png`` is None when the result has no alpha or a
    different composition (aspect ratio), in which case the caller keeps the model
    output and warns. ``stats['drift']`` is the mean abs RGB difference inside the
    alpha between the model's pixels and the original's.
    """
    src = open_image(src_data)
    res = open_image(result_data)
    alpha = _alpha_channel(res)
    stats: dict[str, Any] = {"model_size": [res.width, res.height]}
    if alpha is None or alpha.getextrema()[0] == 255:
        stats["reason"] = "model output has no transparency"
        return None, stats
    if aspect_mismatch(src.size, res.size):
        stats["reason"] = f"model output aspect ratio {res.width}x{res.height} differs from the source {src.width}x{src.height}"
        stats["aspect_mismatch"] = True
        return None, stats
    if alpha.size != src.size:
        alpha = alpha.resize(src.size, Image.Resampling.BILINEAR)
    res_rgb = as_mode(res, "RGB")
    if res_rgb.size != src.size:
        res_rgb = res_rgb.resize(src.size, Image.Resampling.LANCZOS)
    inside = _threshold(alpha)
    stats["drift"] = mean_abs_diff(src, res_rgb, inside)
    stats["opaque_fraction"] = round(inside.histogram()[255] / (src.width * src.height or 1), 4)
    out = as_mode(src, "RGBA")
    src_alpha = _alpha_channel(src)
    out.putalpha(ImageChops.multiply(alpha, src_alpha) if src_alpha is not None else alpha)
    return to_png_bytes(out), stats


def _resample_ready(im: Image.Image) -> Image.Image:
    """8-bit L / LA / RGB / RGBA (Lanczos needs one of these; high bit depths are scaled)."""
    im = to_8bit(im)
    if im.mode not in ("RGB", "RGBA", "L", "LA"):
        im = im.convert("RGBA" if _alpha_channel(im) is not None else "RGB")
    return im


def lanczos_resize(data: bytes, size: tuple[int, int]) -> bytes:
    """Resize to exactly ``size`` with Lanczos, keeping alpha; returns PNG.

    Same-aspect only (an upscale of the source); see :func:`fit_to_size` for model outputs.
    """
    im = _resample_ready(open_image(data))
    if im.size != tuple(size):
        im = im.resize(tuple(size), Image.Resampling.LANCZOS)
    return to_png_bytes(im)


def reattach_alpha(src_data: bytes, result_data: bytes) -> tuple[bytes | None, dict[str, Any]]:
    """Upscale fidelity for RGBA sources: the source's alpha, Lanczos-scaled, on the model's RGB.

    Most upscalers return opaque RGB, flattening a transparent source. Returns (png, stats) with
    ``png`` None when nothing needs doing (the source has no transparency, or the result kept its
    own alpha) or when the compositions differ (aspect ratio), with ``stats['reason']``.
    """
    src = open_image(src_data)
    src_alpha = _alpha_channel(src)
    if src_alpha is None or src_alpha.getextrema()[0] == 255:
        return None, {"reason": "source has no transparency"}
    res = open_image(result_data)
    res_alpha = _alpha_channel(res)
    if res_alpha is not None and res_alpha.getextrema()[0] < 255:
        return None, {"reason": "model output kept its alpha"}
    if aspect_mismatch(src.size, res.size):
        return None, {"reason": f"output {res.width}x{res.height} differs in aspect from the source {src.width}x{src.height}"}
    rgba = res.convert("RGB").convert("RGBA")
    rgba.putalpha(src_alpha.resize(res.size, Image.Resampling.LANCZOS))
    return to_png_bytes(rgba), {"alpha": "reattached", "from": list(src.size), "to": list(res.size)}


def fit_to_size(result_data: bytes, size: tuple[int, int]) -> tuple[bytes, dict[str, Any]]:
    """Exact output size for upscales: Lanczos-fit the model output when it differs.

    A result of another aspect ratio is scaled to cover the target and centre-cropped (not
    stretched) and ``stats['aspect_mismatch']`` is set.
    """
    res = open_image(result_data)
    stats: dict[str, Any] = {"model_size": [res.width, res.height]}
    if res.size == tuple(size) and res.format == "PNG" and res.mode in ("RGB", "RGBA", "L", "LA", "P", "1"):
        return result_data, stats
    im = _resample_ready(res)
    if im.size != tuple(size):
        stats["resized_to"] = list(size)
        im, mismatch = fit_image(im, tuple(size), Image.Resampling.LANCZOS)
        if mismatch:
            stats["aspect_mismatch"] = True
            stats["fit"] = "cover-crop"
    return to_png_bytes(im), stats


def upscale_drift(src_data: bytes, result_data: bytes) -> float:
    """How far an upscale strays from the source: compare at the source resolution."""
    src = open_image(src_data)
    res, _ = fit_image(as_mode(open_image(result_data), "RGB"), src.size, Image.Resampling.LANCZOS)
    return mean_abs_diff(src, res)


def ensure_png_rgba(data: bytes) -> bytes:
    """Any raster -> RGBA PNG (keeps existing alpha)."""
    return to_png_bytes(as_mode(open_image(data), "RGBA"))


def ensure_png(data: bytes) -> bytes:
    """Any raster -> PNG, preserving alpha when present (high bit depths scaled to 8 bits)."""
    im = open_image(data)
    if im.format == "PNG":
        return data
    return to_png_bytes(_png_ready(im))


def mask_png_rgb(mask_l: Image.Image) -> bytes:
    """A canonical mask as an RGB PNG (for adapters that take masks as plain input images)."""
    return to_png_bytes(mask_l.convert("RGB"))
