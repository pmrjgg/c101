"""Output-size arithmetic shared by the adapters: ratios, presets, tiers and size constraints.

Model catalogs describe output geometry in one (or more) of these ways:

* explicit presets - ``sizes: ["1024x1024", "1536x1024", "auto"]``;
* aspect ratios    - ``aspect_ratios: ["1:1", "16:9", ...]`` (the provider picks the pixels);
* resolution tiers - ``resolutions: ["1k", "2k"]``;
* constraints      - ``size_constraints: {multiple_of, min_edge, max_edge, max_ratio,
  min_pixels, max_pixels}``: any WxH meeting them is accepted (GPT Image 2/2.5).

These helpers pick or compute a legal size that keeps a requested aspect ratio, so a request
is never silently turned into another shape or a lower resolution.
"""

from __future__ import annotations

import math
import re
from collections.abc import Mapping
from dataclasses import dataclass
from fractions import Fraction
from typing import Any

# Long edge of the usual resolution tiers.
TIER_LONG_EDGE = {"512": 512, "768": 768, "1k": 1024, "1.5k": 1536, "2k": 2048, "4k": 4096}
_SIZE_RE = re.compile(r"\s*(\d+)\s*[xX]\s*(\d+)\s*")
_RATIO_RE = re.compile(r"\s*(\d+(?:\.\d+)?)\s*[:xX]\s*(\d+(?:\.\d+)?)\s*")


def parse_size(text: str | None) -> tuple[int, int] | None:
    m = _SIZE_RE.fullmatch(text or "")
    if not m or not int(m.group(1)) or not int(m.group(2)):
        return None
    return int(m.group(1)), int(m.group(2))


def parse_ratio(text: str | None) -> float | None:
    m = _RATIO_RE.fullmatch(text or "")
    if not m or float(m.group(2)) == 0 or float(m.group(1)) == 0:
        return None
    return float(m.group(1)) / float(m.group(2))


def ratio_terms(text: str | None) -> tuple[int, int] | None:
    """'16:9' -> (16, 9); '19.5:9' -> (13, 6); '1920x1080' -> (16, 9)."""
    m = _RATIO_RE.fullmatch(text or "")
    if not m:
        return None
    f = Fraction(m.group(1)) / Fraction(m.group(2)) if float(m.group(2)) else None
    if not f:
        return None
    return f.numerator, f.denominator


def terms_of(w: int, h: int) -> tuple[int, int]:
    g = math.gcd(int(w), int(h)) or 1
    return int(w) // g, int(h) // g


def tier_long_edge(text: str | None) -> int | None:
    return TIER_LONG_EDGE.get((text or "").strip().lower())


def ratio_distance(a: float, b: float) -> float:
    return abs(math.log(a / b))


def nearest_ratio(options: list[str], target: float) -> str | None:
    """The option (aspect ratio or WxH string) whose ratio is closest to ``target`` ('auto' skipped)."""
    scored = [(ratio_distance(r, target), i, o) for i, o in enumerate(options) if (r := parse_ratio(o))]
    return min(scored)[2] if scored else None


def presets(options: list[str]) -> list[tuple[int, int]]:
    return [wh for o in options if (wh := parse_size(o))]


def nearest_preset(options: list[str], ratio: float, *, area: float | None = None, long_edge: int | None = None) -> str | None:
    """The WxH preset with the closest ratio; ties (within 1%) go to the closest area / long edge."""
    sizes = presets(options)
    if not sizes:
        return None
    best = min(ratio_distance(w / h, ratio) for w, h in sizes)
    close = [(w, h) for w, h in sizes if ratio_distance(w / h, ratio) <= best + 0.01]

    def key(wh: tuple[int, int]) -> tuple[float, float]:
        w, h = wh
        k1 = abs(math.log(max(w, h) / long_edge)) if long_edge else 0.0
        k2 = abs(math.log((w * h) / area)) if area else 0.0
        return (k1, k2)

    w, h = min(close, key=key)
    return f"{w}x{h}"


@dataclass(frozen=True, slots=True)
class SizeConstraints:
    multiple_of: int = 1
    min_edge: float = 1.0
    max_edge: float = math.inf
    max_ratio: float = math.inf
    min_pixels: float = 0.0
    max_pixels: float = math.inf

    @classmethod
    def from_mapping(cls, d: Mapping[str, Any] | None) -> SizeConstraints | None:
        if not isinstance(d, Mapping) or not d:
            return None

        def num(key: str, default: float) -> float:
            try:
                v = float(d.get(key))  # type: ignore[arg-type]
            except (TypeError, ValueError):
                return default
            return v if v > 0 else default

        return cls(
            multiple_of=max(1, int(num("multiple_of", 1))),
            min_edge=num("min_edge", 1.0),
            max_edge=num("max_edge", math.inf),
            max_ratio=num("max_ratio", math.inf),
            min_pixels=num("min_pixels", 0.0),
            max_pixels=num("max_pixels", math.inf),
        )

    def problems(self, w: int, h: int) -> list[str]:
        out = []
        m = self.multiple_of
        if w % m or h % m:
            out.append(f"not a multiple of {m}")
        if min(w, h) < self.min_edge:
            out.append(f"edge below {self.min_edge:g}")
        if max(w, h) > self.max_edge:
            out.append(f"edge above {self.max_edge:g}")
        if max(w, h) / min(w, h) > self.max_ratio + 1e-9:
            out.append(f"aspect ratio beyond {self.max_ratio:g}:1")
        if w * h < self.min_pixels:
            out.append(f"fewer than {self.min_pixels:,.0f} pixels")
        if w * h > self.max_pixels:
            out.append(f"more than {self.max_pixels:,.0f} pixels")
        return out

    def meets(self, w: int, h: int) -> bool:
        return not self.problems(w, h)

    def _scaled(self, w: float, h: float) -> tuple[float, float]:
        """(w, h) scaled (ratio kept) into the pixel and edge bounds."""
        r = w / h
        area = min(max(w * h, self.min_pixels), self.max_pixels)
        w, h = math.sqrt(area * r), math.sqrt(area / r)
        if max(w, h) > self.max_edge:
            s = self.max_edge / max(w, h)
            w, h = w * s, h * s
        if min(w, h) < self.min_edge:
            s = self.min_edge / min(w, h)
            w, h = w * s, h * s
        return w, h

    def snap(self, w: float, h: float, terms: tuple[int, int] | None = None) -> tuple[int, int]:
        """A legal WxH close to (w, h): ratio kept exactly when ``terms`` (p, q) allow it, else as
        closely as the multiple_of grid permits."""
        r = w / h
        if r > self.max_ratio:
            r, terms = self.max_ratio, None
        elif 1 / r > self.max_ratio:
            r, terms = 1 / self.max_ratio, None
        if r != w / h:
            w = math.sqrt(w * h * r)
            h = w / r
        tw, th = self._scaled(w, h)
        m = self.multiple_of
        if terms:
            p, q = terms
            step = math.lcm(m // math.gcd(m, p), m // math.gcd(m, q))
            k0 = tw / p
            base = max(step, math.floor(k0 / step + 0.5) * step)  # half up: never banker's rounding
            candidates = {base, base - step, base + step, base - 2 * step, base + 2 * step}
            for k in sorted(candidates, key=lambda k: (abs(k - k0), -k)):  # ties: the larger size
                if k > 0 and self.meets(p * k, q * k) and abs(p * k - tw) / tw <= 0.25:
                    return p * k, q * k

        def rnd(x: float) -> int:
            return max(m, math.floor(x / m + 0.5) * m)

        W, H = rnd(tw), rnd(th)
        for _ in range(512):
            problems = self.problems(W, H)
            if not problems:
                break
            too_big = W * H > self.max_pixels or max(W, H) > self.max_edge
            too_small = W * H < self.min_pixels or min(W, H) < self.min_edge
            if too_big:
                if (W / H > r and W > m) or H <= m:
                    W -= m
                else:
                    H -= m
            elif too_small:
                if W / H < r:
                    W += m
                else:
                    H += m
            elif max(W, H) / min(W, H) > self.max_ratio:
                if W < H:
                    W += m
                else:
                    H += m
            else:
                break
        return W, H


def size_for_ratio(ratio: float, long_edge: float) -> tuple[float, float]:
    return (long_edge, long_edge / ratio) if ratio >= 1 else (long_edge * ratio, long_edge)
