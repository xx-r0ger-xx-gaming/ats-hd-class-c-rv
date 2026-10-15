"""Compact Class C motorhome on the regular-cab cab-chassis proxy (render-only, original geometry).

Coach = two plan-ring lofts stacked in Z (cab_chassis variant frame, origin = frame top):
  lower body  z = skirt..cabover_bottom, y = rear..0.05 (stops at the cab back), rear wheel arch cut
  upper body  z = cabover_bottom..roof, extends forward over the cab roof as the cabover berth with a
              rounded nose; the wraparound front window is a band of faces on that loft.
Everything else (windows, door, hatches, graphics, lamps, roof units, awning, ladder, bumper, bike
rack and bikes) is low-poly overlay geometry a few mm proud of the shell. No logos or lettering.
"""
import math

import bmesh
import bpy
from mathutils import Vector

from lib.meshkit import (
    Part, add_weighted_normals, annulus_prism, arc_band_x, bm_object, boolean_apply, box, build_prism,
    cylinder_x, cylinder_y, cylinder_z, loft, oriented_box, rounded_rect, set_smooth,
)

TRUCK_TYPES = ("cab_chassis",)
DESCRIPTION = "Compact Class C motorhome (cabover berth) on the regular-cab cab-chassis"

P = "class_c"


# ------------------------------------------------------------------ materials

def _materials(mats):
    if "cc_fiber" not in mats:
        mats.add("cc_fiber", mats.car_paint(P + "_fiberglass", (0.80, 0.805, 0.79, 1), metallic=0.0,
                                            roughness=0.22, clearcoat=0.7, clearcoat_roughness=0.06,
                                            flake=0.0, dirt=0.35))
        mats.add("cc_gfx_dark", mats.principled(P + "_gfx_dark", base_color=(0.008, 0.0085, 0.009, 1),
                                                roughness=0.6, specular=0.15))
        mats.add("cc_gfx_grey", mats.principled(P + "_gfx_grey", base_color=(0.06, 0.063, 0.068, 1),
                                                roughness=0.6, specular=0.15))
        mats.add("cc_frame", mats.principled(P + "_frame", base_color=(0.045, 0.047, 0.05, 1), metallic=0.6,
                                             roughness=0.38, clearcoat=0.2))
        mats.add("cc_awning", mats.principled(P + "_awning", base_color=(0.05, 0.052, 0.055, 1),
                                              metallic=0.5, roughness=0.35))
        mats.add("cc_bike_a", mats.car_paint(P + "_bike_a", (0.35, 0.02, 0.015, 1), metallic=0.5,
                                             roughness=0.3, flake=0.1))
        mats.add("cc_bike_b", mats.car_paint(P + "_bike_b", (0.02, 0.09, 0.22, 1), metallic=0.5,
                                             roughness=0.3, flake=0.1))


# ------------------------------------------------------------------ plan rings

def plan_ring(z, hw, yb, yf, rb, rf, side_ys, seg=6, inset_front=0.0):
    """CCW plan outline at height z: rounded rear corners rb, rounded front corners rf, fixed number
    of interior points on each side (side_ys, clamped into the straight part) -> equal ring lengths."""
    lo, hi = yb + rb, yf - rf
    n = len(side_ys)
    ys = [max(lo + 0.002 * (i + 1), min(y, hi - 0.002 * (n - i))) for i, y in enumerate(side_ys)]
    pts = []

    def arc(cx, cy, r, a0, a1):
        for i in range(seg + 1):
            a = math.radians(a0 + (a1 - a0) * i / seg)
            pts.append((cx + r * math.cos(a), cy + r * math.sin(a)))

    arc(hw - rb, yb + rb, rb, 270, 360)
    pts += [(hw, y) for y in ys]
    arc(hw - rf, yf - rf, rf, 0, 90)
    arc(-hw + rf, yf - rf, rf, 90, 180)
    pts += [(-hw, y) for y in reversed(ys)]
    arc(-hw + rb, yb + rb, rb, 180, 270)
    out = []
    for x, y in pts:
        if inset_front:
            w = min(max((y - 0.05) / 0.35, 0.0), 1.0)
            x -= math.copysign(inset_front * w, x)
        out.append((x, y, z))
    return out


# ------------------------------------------------------------------ overlay helpers

class Plane:
    """Maps (u, v, d) on a coach face to 3D. kind 'x': side face x = s*(hw + d), u = y, v = z.
    kind 'y': rear face y = y0 - d, u = x, v = z."""

    def __init__(self, kind, s, base):
        self.kind, self.s, self.base = kind, s, base

    def p(self, u, v, d):
        if self.kind == "x":
            return (self.s * (self.base + d), u, v)
        return (u, self.base - d, v)


def slab(part, pl, pts, d0, d1, key):
    bm = part.bm
    a = [bm.verts.new(pl.p(u, v, d0)) for u, v in pts]
    b = [bm.verts.new(pl.p(u, v, d1)) for u, v in pts]
    faces = [bm.faces.new(a), bm.faces.new(b[::-1])]
    n = len(a)
    for i in range(n):
        j = (i + 1) % n
        faces.append(bm.faces.new([a[i], a[j], b[j], b[i]]))
    bmesh.ops.recalc_face_normals(bm, faces=faces)
    part.set_mat(faces, key)
    return faces


def ring_band(part, pl, outer, inner, d0, d1, key):
    faces = annulus_prism(part.bm, [pl.p(u, v, d0) for u, v in outer], [pl.p(u, v, d1) for u, v in outer],
                          [pl.p(u, v, d0) for u, v in inner], [pl.p(u, v, d1) for u, v in inner])
    part.set_mat(faces, key)


POCKETS = []          # (plane, outline) of every window opening; cut into the coach after the details


def rv_window(part, pl, u0, u1, v0, v1, r=0.07, frame=0.035, divider=True):
    """RV window: proud satin-aluminium frame, rubber seal, smoked pane 14 mm in, interior pocket behind."""
    outer = rounded_rect(u0 - frame, u1 + frame, v0 - frame, v1 + frame, r + frame, 3)
    inner = rounded_rect(u0, u1, v0, v1, r, 3)
    seal_in = rounded_rect(u0 + 0.012, u1 - 0.012, v0 + 0.012, v1 - 0.012, max(r - 0.012, 0.01), 3)
    ring_band(part, pl, outer, inner, -0.004, 0.026, "cc_frame")
    ring_band(part, pl, inner, seal_in, -0.022, 0.004, "seal")
    bm = part.bm
    pane = bm.faces.new([bm.verts.new(pl.p(u, v, -0.014)) for u, v in inner])
    pane.normal_update()
    out = Vector(pl.p(u0, v0, 1.0)) - Vector(pl.p(u0, v0, 0.0))
    if pane.normal.dot(out) < 0:
        pane.normal_flip()
    part.set_mat([pane], "glass_tint")
    POCKETS.append((pl, inner))
    if divider and (u1 - u0) > 0.55:
        um = (u0 + u1) / 2
        slab(part, pl, [(um - 0.014, v0), (um + 0.014, v0), (um + 0.014, v1), (um - 0.014, v1)],
             -0.03, 0.022, "cc_frame")
        # slider track along the bottom of the glass
        slab(part, pl, [(u0, v0), (u1, v0), (u1, v0 + 0.02), (u0, v0 + 0.02)], -0.03, 0.006, "cc_frame")


def entry_door(part, pl, s, u0, u1, v0, v1, win, r=0.05):
    """Entry door skin with a window opening, paddle handle + lock, hinges and a folding step."""
    wu0, wu1, wv0, wv1, wr = win
    fr = 0.025
    inner = rounded_rect(u0, u1, v0, v1, r, 3)
    outer = rounded_rect(u0 - 0.012, u1 + 0.012, v0 - 0.012, v1 + 0.012, r + 0.012, 3)
    hole = rounded_rect(wu0 - fr, wu1 + fr, wv0 - fr, wv1 + fr, wr + fr, 3)
    ring_band(part, pl, outer, inner, -0.003, 0.007, "trim")
    ring_band(part, pl, inner, hole, -0.003, 0.009, "cc_fiber")
    rv_window(part, pl, wu0, wu1, wv0, wv1, r=wr, frame=fr, divider=False)
    # paddle handle in a black bezel + key cylinder above it (latch side = u1)
    um, vm = u1 - 0.10, v0 + 0.98
    slab(part, pl, rounded_rect(um - 0.05, um + 0.05, vm - 0.075, vm + 0.075, 0.02, 2), 0.006, 0.02, "trim_gloss")
    slab(part, pl, rounded_rect(um - 0.032, um + 0.032, vm - 0.05, vm + 0.012, 0.012, 2), 0.016, 0.032, "chrome")
    slab(part, pl, rounded_rect(um - 0.012, um + 0.012, vm + 0.028, vm + 0.052, 0.01, 2), 0.016, 0.03, "chrome")
    # hinges on the front edge
    for vv in (v0 + 0.25, v1 - 0.30):
        slab(part, pl, rounded_rect(u0 - 0.02, u0 + 0.03, vv, vv + 0.10, 0.008, 1), 0.006, 0.02, "steel")
    # folding entry step: two ribbed aluminium treads on brackets, under the door
    x0 = s * pl.base
    zt = v0 - 0.30
    for k in range(2):
        a, b = sorted((x0 + s * (0.04 + 0.21 * k), x0 + s * (0.04 + 0.21 * k + 0.20)))
        zk = zt + 0.16 * (1 - k)
        box(part, (a, u0 + 0.06, zk - 0.03), (b, u1 - 0.06, zk), "alloy", bev=0.006)
        for kk in range(6):
            yy = u0 + 0.10 + kk * (u1 - u0 - 0.20) / 5
            box(part, (a + 0.01, yy - 0.006, zk), (b - 0.01, yy + 0.006, zk + 0.006), "alloy")
    for uu in (u0 + 0.08, u1 - 0.08):
        a, b = sorted((x0 - s * 0.03, x0 + s * 0.45))
        box(part, (a, uu - 0.012, zt - 0.05), (b, uu + 0.012, zt - 0.03), "frame", bev=0.004)
        a, b = sorted((x0 - s * 0.03, x0 + s * 0.03))
        box(part, (a, uu - 0.015, zt - 0.05), (b, uu + 0.015, v0 - 0.02), "frame", bev=0.004)


def window_band_trim(part, ring_at, z0, z1, y_min):
    """Depth for the wraparound cabover glass: a deep eyebrow over it and a sill under it.
    ring_at(z) -> closed plan ring [(x, y, z)]; only the nose part (y > y_min) is used."""
    def strip(z, off_in, off_out, za, zb):
        ring = ring_at(z)
        n = len(ring)
        pts = []
        for i in range(n):
            a, b = Vector(ring[i - 1][:2]), Vector(ring[(i + 1) % n][:2])
            t = (b - a).normalized()
            pts.append((Vector(ring[i][:2]), Vector((t.y, -t.x)), ring[i][1] > y_min))
        k0 = next(i for i in range(n) if pts[i][2] and not pts[i - 1][2])
        run = []
        i = k0
        while pts[i % n][2] and len(run) < n:
            run.append(pts[i % n])
            i += 1
        return [[(p.x + nrm.x * o, p.y + nrm.y * o, zz) for o, zz in
                 ((off_in, za), (off_out, za), (off_out, zb), (off_in, zb))] for p, nrm, _ in run]
    for secs in (strip(z1 + 0.02, -0.02, 0.055, z1 + 0.002, z1 + 0.04),
                 strip(z0 - 0.02, -0.02, 0.035, z0 - 0.035, z0 - 0.002)):
        # sections run along the nose: transpose into 4 long rings (closed section, capped ends)
        bm = part.bm
        vs = [[bm.verts.new(q) for q in sec] for sec in secs]
        faces = []
        for A, B in zip(vs, vs[1:]):
            for j in range(4):
                k = (j + 1) % 4
                faces.append(bm.faces.new([A[j], A[k], B[k], B[j]]))
        faces.append(bm.faces.new(vs[0][::-1]))
        faces.append(bm.faces.new(vs[-1]))
        bmesh.ops.recalc_face_normals(bm, faces=faces)
        part.set_mat(faces, "cc_frame")


def hatch(part, pl, u0, u1, v0, v1, r=0.04, handle=True, gap_key="trim"):
    """Exterior panel (door / storage compartment): white skin, dark perimeter seam, latch."""
    inner = rounded_rect(u0, u1, v0, v1, r, 2)
    outer = rounded_rect(u0 - 0.012, u1 + 0.012, v0 - 0.012, v1 + 0.012, r + 0.012, 2)
    ring_band(part, pl, outer, inner, -0.003, 0.007, gap_key)
    slab(part, pl, inner, -0.003, 0.009, "cc_fiber")
    if handle:
        um = u1 - 0.09 if (u1 - u0) < 0.9 else (u0 + u1) / 2
        vm = (v0 + v1) / 2 if (v1 - v0) < 0.8 else v0 + 0.95
        slab(part, pl, rounded_rect(um - 0.04, um + 0.04, vm - 0.022, vm + 0.022, 0.01, 1), 0.006, 0.022,
             "chrome")


def bezier(a, c, b, t):
    return tuple((1 - t) ** 2 * a[i] + 2 * (1 - t) * t * c[i] + t * t * b[i] for i in range(2))


def blade(a, c, b, w0, w1, n=10):
    """Tapered swept band (u, v) from a to b via control c; width w0 -> w1 (normal to the curve)."""
    top, bot = [], []
    for k in range(n + 1):
        t = k / n
        p = bezier(a, c, b, t)
        q = bezier(a, c, b, min(t + 0.01, 1.0))
        p0 = bezier(a, c, b, max(t - 0.01, 0.0))
        d = Vector((q[0] - p0[0], q[1] - p0[1])).normalized()
        nrm = Vector((-d.y, d.x))
        w = (w0 + (w1 - w0) * t) / 2
        top.append((p[0] + nrm.x * w, p[1] + nrm.y * w))
        bot.append((p[0] - nrm.x * w, p[1] - nrm.y * w))
    pts = bot + top[::-1]
    # dedupe a zero-width tip
    out = []
    for p in pts:
        if not out or (abs(p[0] - out[-1][0]) + abs(p[1] - out[-1][1])) > 1e-5:
            out.append(p)
    return out


def tube(part, p, q, t, key, up=Vector((0, 1, 0))):
    p, q = Vector(p), Vector(q)
    axis = (q - p)
    ln = axis.length
    axis.normalize()
    tang = axis.cross(up)
    if tang.length < 1e-6:
        tang = axis.cross(Vector((1, 0, 0)))
    tang.normalize()
    nrm = tang.cross(axis).normalized()
    oriented_box(part, (p + q) / 2, (axis, tang, nrm), (ln + t * 0.6, t, t), key)


def torus_y(part, cx, cy, cz, R, r, key, seg=20, mseg=6):
    bm = part.bm
    rings = []
    for i in range(seg):
        a = 2 * math.pi * i / seg
        ca, sa = math.cos(a), math.sin(a)
        ring = []
        for j in range(mseg):
            b = 2 * math.pi * j / mseg
            rr = R + r * math.cos(b)
            ring.append(bm.verts.new((cx + rr * ca, cy + r * math.sin(b), cz + rr * sa)))
        rings.append(ring)
    faces = []
    for i in range(seg):
        A, B = rings[i], rings[(i + 1) % seg]
        for j in range(mseg):
            k = (j + 1) % mseg
            faces.append(bm.faces.new([A[j], A[k], B[k], B[j]]))
    bmesh.ops.recalc_face_normals(bm, faces=faces)
    part.set_mat(faces, key)


# ------------------------------------------------------------------ build

def build(cfg, collection, mats):
    c = cfg["camper"]
    ti = cfg["truck_info"]
    _materials(mats)
    POCKETS.clear()
    hw = c.get("half_width", 1.25)
    yb = c.get("rear_y", -3.98)
    zs = c.get("skirt_z", -0.30)
    zr = c.get("roof_z", 2.48)
    zc = c.get("cabover_bottom_z", max(ti["roof_z"] + 0.08, 1.20))
    ds = c.get("door_side", -1)
    yfw = 0.05                                   # coach front wall (cab back is at 0.07)
    y_ra = ti["rear_axle_y"]
    z_ax = ti["ground_z"] + ti["tire_radius"]
    rb = 0.16
    dz = zc - 1.22                               # cabover features were laid out for cabover_bottom_z 1.22
    ry = yb + 3.98                               # rear-end features were laid out for rear_y -3.98
    objs = []

    # ---------------- lower body (beside / behind the cab), rear wheel arches cut out
    side_lo = [-3.2 + ry, -2.4, -1.6, -0.8, -0.2]
    lo_rings = [(zs, 0.03), (zs + 0.03, 0.0), (zs + 0.14, 0.0), (zc, 0.0)]
    rings = []
    for z, ins in lo_rings:
        rings.append(plan_ring(z, hw - ins, yb + ins, yfw, rb, 0.04, side_lo))
    lower = Part(P + "_body_lower", mats)
    _, faces = loft(lower, rings, "cc_fiber")
    for f in faces:
        if f.calc_center_median().z < zs + 0.14 - 1e-4:
            lower.set_mat([f], "trim")
    lower_ob = lower.finish(collection, smooth=40, weighted=False)
    cut = Part(P + "_archcut", mats)
    for sgn in (-1, 1):
        cylinder_x(cut, y_ra, z_ax, 0.58, sgn * 0.45, sgn * (hw + 0.3), "underbody", seg=28)
    cut_ob = cut.finish(collection, smooth=0, uv=False)
    boolean_apply(lower_ob, cut_ob)
    add_weighted_normals(lower_ob)
    objs.append(lower_ob)

    # ---------------- upper body + cabover nose (z-stacked plan rings)
    # (z, front y, inset all-round (roof edge), inset front-only (cabover underside edge))
    zw0, zw1 = 1.60 + dz, 2.00 + dz               # wraparound window band
    nose = [(zc, 1.42, 0, 0.07), (zc + 0.03, 1.56, 0, 0.025), (zc + 0.10, 1.67, 0, 0.0),
            (1.45 + dz, 1.75, 0, 0), (zw0 - 0.03, 1.785, 0, 0), (zw0, 1.79, 0, 0), (1.80 + dz, 1.78, 0, 0),
            (zw1, 1.73, 0, 0), (zw1 + 0.03, 1.72, 0, 0), (2.15 + dz, 1.66, 0, 0), (2.27 + dz, 1.56, 0, 0),
            (zr - 0.12, 1.43, 0.012, 0), (zr - 0.06, 1.28, 0.035, 0), (zr, 1.08, 0.08, 0)]
    yw = 0.98                                     # rear edge of the wraparound glass on the sides
    side_up = [-3.2 + ry, -2.4, -1.6, -0.8, 0.0, 0.05, 0.5, yw - 0.04, yw]
    rings = [plan_ring(z, hw - ia, yb + ia, yf, rb, 0.52, side_up, inset_front=inf)
             for z, yf, ia, inf in nose]
    upper = Part(P + "_body_upper", mats)
    _, faces = loft(upper, rings, "cc_fiber")
    for f in faces:
        cc = f.calc_center_median()
        if abs(f.normal.z) > 0.9:
            continue
        if zw0 < cc.z < zw1 and cc.y > yw:
            upper.set_mat([f], "glass_flush")
        elif zw0 - 0.03 < cc.z < zw1 + 0.03 and cc.y > yw - 0.04:
            upper.set_mat([f], "trim")
    upper_ob = upper.finish(collection, smooth=40, weighted=False)
    objs.append(upper_ob)

    def nose_y(z):
        for (z0, y0, *_), (z1, y1, *_) in zip(nose, nose[1:]):
            if z0 <= z <= z1:
                return y0 + (y1 - y0) * (z - z0) / (z1 - z0)
        return nose[-1][1]

    # ---------------- details on the shell
    d = Part(P + "_details", mats)
    gx = Part(P + "_graphics", mats)          # decals: trimmed by the window cutter below
    for s in (-1, 1):
        pl = Plane("x", s, hw)
        door = s == ds
        # cabover side window just behind the wraparound glass
        rv_window(d, pl, 0.28, 0.74, 1.64 + dz, 1.96 + dz, r=0.06, divider=False)
        if door:
            rv_window(d, pl, -2.62, -1.42, 0.98, 1.72)          # lounge window over the arch
            rv_window(d, pl, -3.72 + ry, -3.12 + ry, 1.06, 1.66)  # rear bedroom window
            # entry door with window + grab handle + folding step
            entry_door(d, pl, s, -0.98, -0.30, zs + 0.17, 1.86, (-0.86, -0.42, 1.18, 1.66, 0.08))
            slab(d, pl, rounded_rect(-0.24, -0.20, 0.55, 1.35, 0.018, 2), 0.0, 0.045, "chrome")
            for u0, u1, v1 in ((-1.50, -1.08, 0.48), (-3.84 + ry, -3.06 + ry, 0.48)):
                hatch(d, pl, u0, u1, zs + 0.18, v1)
        else:
            rv_window(d, pl, -2.40, -1.40, 1.00, 1.66)
            rv_window(d, pl, -3.66 + ry, -3.10 + ry, 1.06, 1.60)
            rv_window(d, pl, -0.70, -0.20, 1.16, 1.62, divider=False)
            for u0, u1, v1 in ((-1.50, -0.92, 0.48), (-0.72, -0.12, 0.48), (-3.86 + ry, -3.00 + ry, 0.48)):
                hatch(d, pl, u0, u1, zs + 0.18, v1)
        # wheel arch trim
        arc_band_x(d, y_ra, z_ax, 0.575, 0.62, 12, 168, s * (hw - 0.01), s * (hw + 0.018), "trim", seg=16)
        # side marker lamps (amber front, red rear), roof-edge drip rail
        slab(d, pl, rounded_rect(-0.10, 0.0, zs + 0.24, zs + 0.29, 0.015, 1), 0.0, 0.02, "lamp_amber")
        slab(d, pl, rounded_rect(yb + 0.18, yb + 0.28, zs + 0.24, zs + 0.29, 0.015, 1), 0.0, 0.02,
             "lamp_red_lens")
        slab(d, pl, rounded_rect(0.85, 0.95, 1.40 + dz, 1.45 + dz, 0.015, 1), 0.0, 0.02, "lamp_amber")
        slab(d, pl, [(yb + 0.20, zr - 0.15), (0.9, zr - 0.15), (0.9, zr - 0.13), (yb + 0.20, zr - 0.13)],
             -0.003, 0.016, "trim")
        # original graphics: tapered swept blades, dark + grey, rising toward the front
        g = [((yb + 0.08, 0.02), (-2.6, 0.10), (-0.55, 1.30), 0.62, 0.0, "cc_gfx_dark"),
             ((yb + 0.08, 0.78), (-3.0, 0.92), (-1.9, 1.42), 0.26, 0.0, "cc_gfx_grey"),
             ((yb + 0.08, 1.45), (-3.3, 1.55), (-2.7, 1.95), 0.12, 0.0, "cc_gfx_dark"),
             ((-1.95, zs + 0.70), (-0.9, zs + 0.85), (0.02, 0.95), 0.20, 0.03, "cc_gfx_dark"),
             ((-0.1, 1.38), (0.45, 1.42), (1.35, 1.52), 0.07, 0.0, "cc_gfx_grey")]
        for a, cpt, b, w0, w1, key in g:
            slab(gx, pl, blade(a, cpt, b, w0, w1, 12), -0.002, 0.004, key)

    # cabover front: amber clearance lamps above the windshield band, lower nose marker
    for x in (-0.48, -0.24, 0.0, 0.24, 0.48):
        y = nose_y(2.16 + dz)
        box(d, (x - 0.05, y - 0.03, 2.145 + dz), (x + 0.05, y + 0.012, 2.175 + dz), "lamp_amber", bev=0.008, seg=1)
    for x in (-0.95, 0.95):
        y = nose_y(1.45 + dz)
        box(d, (x - 0.06, y - 0.05, 1.43 + dz), (x + 0.06, y + 0.008, 1.47 + dz), "lamp_amber", bev=0.008, seg=1)

    # rear face
    pr = Plane("y", -1, yb)
    rv_window(d, pr, -0.80, 0.10, 1.20, 1.72, r=0.07)
    for x0, x1 in ((-1.06, -0.92), (0.92, 1.06)):
        slab(d, pr, rounded_rect(x0, x1, zs + 0.30, zs + 0.95, 0.03, 2), -0.003, 0.03, "lamp_red_lens")
        slab(d, pr, rounded_rect(x0, x1, zs + 0.98, zs + 1.12, 0.03, 2), -0.003, 0.03, "lamp_clear")
        slab(d, pr, rounded_rect(x0, x1, zs + 0.20, zs + 0.27, 0.02, 1), -0.003, 0.025, "lamp_amber")
    for x in (-0.18, 0.0, 0.18, -1.0, 1.0):
        slab(d, pr, rounded_rect(x - 0.04, x + 0.04, zr - 0.20, zr - 0.16, 0.012, 1), -0.003, 0.02,
             "lamp_red_lens")
    for a, cpt, b, w0, w1, key in (((-1.05, 0.10), (-0.4, 0.15), (0.75, 0.95), 0.50, 0.0, "cc_gfx_dark"),
                                   ((-1.05, 0.72), (-0.6, 0.80), (-0.05, 1.08), 0.18, 0.0, "cc_gfx_grey")):
        slab(gx, pr, blade(a, cpt, b, w0, w1, 12), -0.002, 0.004, key)
    # spare-plate box / license plate recess (blank plate, no text)
    slab(d, pr, rounded_rect(-0.20, 0.20, zs + 0.18, zs + 0.40, 0.02, 1), -0.003, 0.012, "plate")
    # ladder (rear, curb side)
    for x in (0.66, 1.00):
        box(d, (x - 0.016, yb - 0.075, 0.30), (x + 0.016, yb - 0.045, zr + 0.06), "steel", bev=0.006, seg=1)
        box(d, (x - 0.016, yb - 0.075, zr + 0.03), (x + 0.016, yb + 0.30, zr + 0.06), "steel", bev=0.006, seg=1)
        for z in (0.40, 1.30, 2.25):
            box(d, (x - 0.012, yb - 0.06, z - 0.02), (x + 0.012, yb + 0.01, z + 0.02), "steel")
    for k in range(8):
        cylinder_x(d, yb - 0.06, 0.48 + k * 0.27, 0.014, 0.66, 1.00, "steel", seg=8)

    # rear bumper, hitch receiver, mud flaps
    box(d, (-1.08, yb - 0.14, zs - 0.12), (1.08, yb + 0.02, zs + 0.04), "trim", bev=0.02)
    box(d, (-0.045, yb - 0.30, zs - 0.21), (0.045, yb + 0.30, zs - 0.12), "frame", bev=0.008, seg=1)
    for sgn in (-1, 1):
        box(d, (sgn * 1.02 - 0.22, y_ra - 0.62, ti["ground_z"] + 0.18),
            (sgn * 1.02 + 0.22, y_ra - 0.60, zs + 0.02), "rubber")

    # roof: two AC units, vents, skylight, awning on the door side
    for y0, key in ((-1.95, "plastic_white"), (0.30, "cc_gfx_dark")):
        box(d, (-0.38, y0, zr - 0.01), (0.38, y0 + 0.98, zr + 0.24), key, bev=0.07, seg=3)
        for k in range(5):
            yy = y0 + 0.16 + k * 0.16
            box(d, (-0.39, yy, zr + 0.04), (0.39, yy + 0.05, zr + 0.16), "trim")
    for y in (-3.30 + ry, -0.70):
        box(d, (-0.20, y, zr - 0.01), (0.20, y + 0.40, zr + 0.06), "plastic_white", bev=0.02, seg=1)
        box(d, (-0.17, y + 0.03, zr + 0.06), (0.17, y + 0.37, zr + 0.12), "trim_gloss", bev=0.02, seg=1)
    box(d, (0.35, -3.0 + ry, zr - 0.01), (0.85, -2.5 + ry, zr + 0.08), "glass_flush", bev=0.03, seg=2)
    xa = ds * (hw + 0.085)
    cylinder_y(d, xa, zr - 0.25, 0.075, -3.02, -0.14, "cc_awning", seg=16)
    box(d, (xa - 0.06, -3.04, zr - 0.38), (xa + 0.06, -0.12, zr - 0.30), "cc_awning")
    for y in (-2.92, -0.16):
        cylinder_y(d, xa, zr - 0.25, 0.08, y - 0.03, y + 0.03, "trim", seg=16)
        xs0, xs1 = sorted((ds * (hw + 0.005), ds * (hw + 0.045)))
        box(d, (xs0, y - 0.025, zs + 0.22), (xs1, y + 0.025, zr - 0.30), "trim", bev=0.006, seg=1)
    window_band_trim(d, lambda z: plan_ring(z, hw, yb, nose_y(z), rb, 0.52, side_up), zw0, zw1, yw - 0.02)
    objs.append(d.finish(collection, smooth=40, weighted=True))

    # interior pockets behind every window (curtain back wall, dark side walls), both body halves
    cbm = bmesh.new()
    for pl, ol in POCKETS:
        faces = build_prism(cbm, [pl.p(u, v, 0.06) for u, v in ol], [pl.p(u, v, -0.16) for u, v in ol], mat_index=1)
        bmesh.ops.recalc_face_normals(cbm, faces=faces)
        faces[1].material_index = 0
    cutter = bm_object(P + "_window_cut", cbm, [mats["curtain"], mats["interior"]], collection)
    gx_ob = gx.finish(collection, smooth=0)
    objs.append(gx_ob)
    for ob in (lower_ob, upper_ob, gx_ob):
        ob.modifiers.clear()
        boolean_apply(ob, cutter, remove_cutters=False)
        set_smooth(ob, 40)
        add_weighted_normals(ob)
    me = cutter.data
    bpy.data.objects.remove(cutter)
    bpy.data.meshes.remove(me)

    # ---------------- bike rack + bikes (hitch mounted, behind the bumper)
    if c.get("bikes", 2):
        b = Part(P + "_bikes", mats)
        ym = yb - 0.48
        zrk = zs - 0.165
        box(b, (-0.035, ym, zrk - 0.035), (0.035, yb - 0.28, zrk + 0.035), "trim", bev=0.006, seg=1)
        box(b, (-0.035, ym - 0.035, zrk - 0.035), (0.035, ym + 0.035, 0.42), "trim", bev=0.006, seg=1)
        arm_z = 0.40
        for x in (-0.28, 0.28):
            box(b, (x - 0.02, ym - 0.42, arm_z - 0.02), (x + 0.02, ym + 0.03, arm_z + 0.02), "trim")
        box(b, (-0.30, ym - 0.03, arm_z - 0.02), (0.30, ym + 0.03, arm_z + 0.02), "trim")
        for k in range(min(int(c.get("bikes", 2)), 2)):
            yb_ = ym - 0.14 - k * 0.20
            flip = 1 if k == 0 else -1
            ox = 0.05 * flip
            wc = arm_z - 0.50                     # wheel centre z (top tube rests on the arms)
            R = 0.33

            def P2(x, z):
                return (ox + flip * x, yb_, wc + z)
            key = "cc_bike_a" if k == 0 else "cc_bike_b"
            for wx in (-0.52, 0.52):
                torus_y(b, ox + flip * wx, yb_, wc, R, 0.022, "tire", seg=22, mseg=6)
                torus_y(b, ox + flip * wx, yb_, wc, R - 0.04, 0.012, "alloy_dark", seg=22, mseg=4)
                cylinder_y(b, ox + flip * wx, wc, 0.03, yb_ - 0.05, yb_ + 0.05, "steel", seg=8)
            rr, bb, st, ht, hb, fr = (P2(-0.52, 0), P2(-0.06, -0.04), P2(-0.17, 0.50), P2(0.38, 0.50),
                                      P2(0.42, 0.36), P2(0.52, 0))
            for p0, p1, t in ((rr, bb, 0.022), (rr, st, 0.018), (bb, st, 0.032), (st, ht, 0.032),
                              (bb, hb, 0.038), (hb, ht, 0.04), (hb, fr, 0.024)):
                tube(b, p0, p1, t, key)
            tube(b, st, P2(-0.20, 0.62), 0.024, "steel")
            box(b, (st[0] - 0.13 if flip > 0 else st[0] - 0.05, yb_ - 0.04, wc + 0.62),
                (st[0] + 0.05 if flip > 0 else st[0] + 0.13, yb_ + 0.04, wc + 0.66), "rubber", bev=0.015, seg=1)
            tube(b, ht, P2(0.36, 0.64), 0.026, "steel")
            box(b, (ox + flip * 0.36 - 0.02, yb_ - 0.30, wc + 0.63), (ox + flip * 0.36 + 0.02, yb_ + 0.30,
                                                                   wc + 0.66), "trim")
            cylinder_x(b, yb_, wc - 0.03, 0.08, bb[0] - 0.01, bb[0] + 0.01, "steel", seg=12)
        objs.append(b.finish(collection, smooth=40))

    tris = sum(len(ob.data.loop_triangles) if ob.data.calc_loop_triangles() is None else 0 for ob in objs)
    print(f"[class_c] coach objects={len(objs)} triangles={tris}")
    return objs
