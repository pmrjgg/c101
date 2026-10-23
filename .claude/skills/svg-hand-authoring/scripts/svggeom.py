#!/usr/bin/env python3
"""Generate SVG path data for hand-written icons and illustrations. Stdlib only, deterministic.

Angles are degrees in SVG screen space: 0 = right (3 o'clock), 90 = down, 180 = left, 270 = up;
increasing angles turn clockwise on screen, which is arc sweep-flag 1.

Commands (print a `d` string, or points; --digits sets the precision, default 2)
  polygon CX CY R N [--rot -90]             regular polygon, first vertex at --rot (default: top)
  star CX CY R_OUT R_IN N [--rot -90]       N-pointed star alternating outer and inner radius
  circle CX CY R [--ccw]                    full circle as two half arcs (cw, or ccw for holes)
  ring CX CY R_OUT R_IN                     disc with a hole: outer cw + inner ccw (any fill-rule)
  arc CX CY R FROM TO                       M + A for the arc FROM -> TO (TO > FROM = clockwise)
  points CX CY R ANGLE...                   x,y of points on a circle at the given angles
  rrect X Y W H R                           rounded rectangle (R clamped to half the short side)
  pill X Y W H                              stadium: rrect with R = half the short side
  rpoly R X,Y X,Y X,Y...                    polygon with every corner filleted with radius R
  cross CX0 CY0 R0 CX1 CY1 R1               where two circles cross: points and their angles on each
  snap STROKE V...                          snap coordinates: odd stroke -> .5, even -> integer
Library use (functions on_circle, polygon, star, circle, ring, arc, arc_to, rrect, pill, fillet,
rpoly, circle_intersections, angle_of, snap):
    python3 -I -c 'import sys; sys.path.insert(0, sys.argv[1]); import svggeom as g; print(g.ring(12, 12, 9, 5))' DIR
"""
import argparse
import math
import sys

DIGITS = 2


def f(v):
    s = ("%.*f" % (DIGITS, v)).rstrip("0").rstrip(".")
    return "0" if s in ("-0", "") else s


def pt(x, y):
    return "%s %s" % (f(x), f(y))


def on_circle(cx, cy, r, deg):
    a = math.radians(deg)
    return cx + r * math.cos(a), cy + r * math.sin(a)


def polygon(cx, cy, r, n, rot=-90.0):
    return "M" + "L".join(pt(*on_circle(cx, cy, r, rot + 360.0 * i / n)) for i in range(n)) + "Z"


def star(cx, cy, r_out, r_in, n, rot=-90.0):
    return "M" + "L".join(pt(*on_circle(cx, cy, r_in if i % 2 else r_out, rot + 180.0 * i / n))
                          for i in range(2 * n)) + "Z"


def circle(cx, cy, r, ccw=False):
    s = 0 if ccw else 1
    return "M%sA%s %s 0 1 %d %sA%s %s 0 1 %d %sZ" % (
        pt(cx - r, cy), f(r), f(r), s, pt(cx + r, cy), f(r), f(r), s, pt(cx - r, cy))


def ring(cx, cy, r_out, r_in):
    return circle(cx, cy, r_out) + circle(cx, cy, r_in, ccw=True)


def arc(cx, cy, r, a0, a1):
    span = a1 - a0
    if abs(span) >= 360:
        raise ValueError("an arc cannot span 360 degrees: use circle")
    large, sweep = int(abs(span) > 180), int(span > 0)
    return "M%sA%s %s 0 %d %d %s" % (pt(*on_circle(cx, cy, r, a0)), f(r), f(r), large, sweep,
                                     pt(*on_circle(cx, cy, r, a1)))


def arc_to(cx, cy, r, a0, a1):
    """Only the A command from angle a0 to a1 (for chaining arcs of different circles)."""
    span = a1 - a0
    return "A%s %s 0 %d %d %s" % (f(r), f(r), int(abs(span) > 180), int(span > 0), pt(*on_circle(cx, cy, r, a1)))


def circle_intersections(c0, r0, c1, r1):
    """Crossing points of two circles (0 or 2), via a = (r0^2 - r1^2 + d^2) / 2d, h = sqrt(r0^2 - a^2)."""
    (x0, y0), (x1, y1) = c0, c1
    d = math.hypot(x1 - x0, y1 - y0)
    if d == 0 or d > r0 + r1 or d < abs(r0 - r1):
        return []
    a = (r0 * r0 - r1 * r1 + d * d) / (2 * d)
    h = math.sqrt(max(r0 * r0 - a * a, 0.0))
    xm, ym = x0 + a * (x1 - x0) / d, y0 + a * (y1 - y0) / d
    return [(xm + h * (y1 - y0) / d, ym - h * (x1 - x0) / d), (xm - h * (y1 - y0) / d, ym + h * (x1 - x0) / d)]


def angle_of(c, p):
    """Angle of point p around centre c, degrees 0..360 in SVG screen space."""
    return math.degrees(math.atan2(p[1] - c[1], p[0] - c[0])) % 360


def rrect(x, y, w, h, r):
    r = min(r, w / 2.0, h / 2.0)
    a = "A%s %s 0 0 1 " % (f(r), f(r))
    d = "M%s" % pt(x + r, y)
    d += ("H%s" % f(x + w - r) if w > 2 * r else "") + a + pt(x + w, y + r)
    d += ("V%s" % f(y + h - r) if h > 2 * r else "") + a + pt(x + w - r, y + h)
    d += ("H%s" % f(x + r) if w > 2 * r else "") + a + pt(x, y + h - r)
    d += ("V%s" % f(y + r) if h > 2 * r else "") + a + pt(x + r, y)
    return d + "Z"


def pill(x, y, w, h):
    return rrect(x, y, w, h, min(w, h) / 2.0)


def fillet(p0, p1, p2, r):
    """Tangent points and sweep for rounding corner p1 (between p0 and p2) with radius r."""
    u = (p0[0] - p1[0], p0[1] - p1[1])
    v = (p2[0] - p1[0], p2[1] - p1[1])
    lu, lv = math.hypot(*u), math.hypot(*v)
    u, v = (u[0] / lu, u[1] / lu), (v[0] / lv, v[1] / lv)
    theta = math.acos(max(-1.0, min(1.0, u[0] * v[0] + u[1] * v[1])))  # interior angle
    t = r / math.tan(theta / 2)                                        # tangent length
    if t > min(lu, lv) / 2 + 1e-9:
        raise ValueError("radius %g too large for a %.1f degree corner" % (r, math.degrees(theta)))
    a = (p1[0] + u[0] * t, p1[1] + u[1] * t)
    b = (p1[0] + v[0] * t, p1[1] + v[1] * t)
    sweep = 0 if u[0] * v[1] - u[1] * v[0] > 0 else 1
    return a, b, sweep


def rpoly(r, pts):
    d = ""
    for i, p in enumerate(pts):
        a, b, sweep = fillet(pts[i - 1], p, pts[(i + 1) % len(pts)], r)
        d += ("M" if i == 0 else "L") + pt(*a) + "A%s %s 0 0 %d %s" % (f(r), f(r), sweep, pt(*b))
    return d + "Z"


def snap(v, stroke):
    return math.floor(v) + 0.5 if int(round(stroke)) % 2 else float(round(v))


def main(argv=None):
    global DIGITS
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--digits", type=int, default=2)
    s = p.add_subparsers(dest="cmd", required=True)
    for name, args in (("polygon", "cx cy r n"), ("star", "cx cy r_out r_in n"), ("circle", "cx cy r"),
                       ("ring", "cx cy r_out r_in"), ("arc", "cx cy r a0 a1"), ("rrect", "x y w h r"),
                       ("pill", "x y w h")):
        x = s.add_parser(name)
        for an in args.split():
            x.add_argument(an, type=int if an == "n" else float)
        if name in ("polygon", "star"):
            x.add_argument("--rot", type=float, default=-90.0)
        if name == "circle":
            x.add_argument("--ccw", action="store_true")
    x = s.add_parser("points"); x.add_argument("cx", type=float); x.add_argument("cy", type=float)
    x.add_argument("r", type=float); x.add_argument("angles", type=float, nargs="+")
    x = s.add_parser("rpoly"); x.add_argument("r", type=float); x.add_argument("pts", nargs="+")
    x = s.add_parser("cross")
    for an in ("cx0", "cy0", "r0", "cx1", "cy1", "r1"):
        x.add_argument(an, type=float)
    x = s.add_parser("snap"); x.add_argument("stroke", type=float); x.add_argument("vals", type=float, nargs="+")
    a = p.parse_args(argv)
    DIGITS = a.digits
    try:
        if a.cmd == "polygon":
            print(polygon(a.cx, a.cy, a.r, a.n, a.rot))
        elif a.cmd == "star":
            print(star(a.cx, a.cy, a.r_out, a.r_in, a.n, a.rot))
        elif a.cmd == "circle":
            print(circle(a.cx, a.cy, a.r, a.ccw))
        elif a.cmd == "ring":
            print(ring(a.cx, a.cy, a.r_out, a.r_in))
        elif a.cmd == "arc":
            print(arc(a.cx, a.cy, a.r, a.a0, a.a1))
        elif a.cmd == "rrect":
            print(rrect(a.x, a.y, a.w, a.h, a.r))
        elif a.cmd == "pill":
            print(pill(a.x, a.y, a.w, a.h))
        elif a.cmd == "points":
            print(" ".join("%s,%s" % tuple(map(f, on_circle(a.cx, a.cy, a.r, t))) for t in a.angles))
        elif a.cmd == "rpoly":
            print(rpoly(a.r, [tuple(float(c) for c in q.split(",")) for q in a.pts]))
        elif a.cmd == "cross":
            c0, c1 = (a.cx0, a.cy0), (a.cx1, a.cy1)
            pts = circle_intersections(c0, a.r0, c1, a.r1)
            if not pts:
                raise ValueError("the circles do not cross")
            for q in pts:
                print("%s,%s  angle on circle 0: %.1f  on circle 1: %.1f" % (f(q[0]), f(q[1]), angle_of(c0, q), angle_of(c1, q)))
        elif a.cmd == "snap":
            print(" ".join(f(snap(v, a.stroke)) for v in a.vals))
    except ValueError as e:
        sys.stderr.write("error: %s\n" % e)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
