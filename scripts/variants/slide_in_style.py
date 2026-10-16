"""Slide-in style Class C coach (render-only, original geometry). Selected from class_c.py by
camper.style = "slide_in_exact" | "slide_in_styled"; style "rounded" keeps the original coach.

Hard-edged design language of a slide-in truck camper: one flat-sided side profile (rear wall,
floor, front wall under the cabover, flat cabover floor, raked nose with a front window, sloped
upper nose, flat roof) extruded across the width with only the side edges bevelled; framed RV
windows (dark aluminium frames, smoked glass, slider track, mullion), panel-gap doors/hatches,
tapered dark swoosh graphics, roof AC + vents, rear ladder, corner jacks.

Two coordinate spaces:
  design space  the slide-in's own layout (metres; body floor z = 0.045, cabover floor z = 0.698,
                roof z = 1.52, front wall y = 0.058, rear wall y = -2.344, nose y = 1.30, half
                width 1.08). Geometry built here goes through Space.T into
  coach space   the cab_chassis variant frame (origin = frame top, 7 cm behind the cab back):
                x * (half_width / 1.08), y and z * scale (1.4) anchored at the coach front wall
                (y 0.03) and the cabover floor (cabover_bottom_z 1.26). Style "exact" inserts a
                plug in y (at design y = -1.40, where nothing but the shell, graphics and trim
                cross) so the rear wall lands on rear_y; style "styled" instead lengthens the body
                in design space and adds its own Class C parts directly in coach space.

  slide_in_exact   the slide-in look scaled to the chassis: same profile, wing walls floating
                   above the duals on a narrow basement, rear entry door, corner jacks.
  slide_in_styled  same language with Class C proportions: full-width lower body down to the
                   skirt with squared wheel arches, longer cabover, curb-side entry door + awning,
                   rear bumper, ladder and lamps on the full-height rear wall.
"""
import math

import bmesh
from mathutils import Vector

from lib.meshkit import (
    Part, annulus_prism, bevel, bm_object, boolean_apply, box, build_prism, cylinder_x, cylinder_y,
    cylinder_z, finish_hard_surface, oriented_box, prism_x, rounded_rect,
)

TRUCK_TYPES = ("cab_chassis",)
DESCRIPTION = "Slide-in style hard-edged Class C coach (exact / styled)"

NAME = "class_c_si"
STYLES = ("slide_in_exact", "slide_in_styled")

# design-space layout of the slide-in style body
HW_N, Z0_N, ZT_N, ZC_N = 1.08, 0.045, 1.52, 0.6979
YB_N, YR_N, YN_N = 0.058, -2.3438, 1.30
BASE_END_N = -1.645                 # basement end (exact)
PLUG_CUT_N = -1.40                  # exact: length plug inserted here

POCKET = 0.20                       # window pocket depth (interior box behind the glass)
GLASS_D = -0.012                    # glass pane depth below the skin
DOOR = (-0.78, -0.16, 0.12, 1.38, 0.06)          # exact: rear entry door (u = x, v = z)
HATCH = (-1.92, -1.47, 0.12, 0.38, 0.035)        # exact: left storage hatch (u = y, v = z)


# ------------------------------------------------------------------ 2D helpers

def fillet_poly(pts):
    """[(u, v, r)] polygon (convex or concave corners) -> outline with every corner filleted."""
    out = []
    n = len(pts)
    for i in range(n):
        p0 = Vector(pts[i - 1][:2])
        p1 = Vector(pts[i][:2])
        p2 = Vector(pts[(i + 1) % n][:2])
        r = pts[i][2]
        a, b = (p0 - p1), (p2 - p1)
        la, lb = a.length, b.length
        a.normalize()
        b.normalize()
        ang = a.angle(b)
        if r <= 0 or abs(ang - math.pi) < 1e-3:
            out.append((p1.x, p1.y))
            continue
        t = min(r / math.tan(ang / 2), la * 0.45, lb * 0.45)
        rr = t * math.tan(ang / 2)
        s, e = p1 + a * t, p1 + b * t
        c = p1 + (a + b).normalized() * (rr / math.sin(ang / 2))
        a0 = math.atan2(s.y - c.y, s.x - c.x)
        a1 = math.atan2(e.y - c.y, e.x - c.x)
        da = (a1 - a0 + math.pi) % (2 * math.pi) - math.pi
        seg = max(2, min(8, int(rr / 0.03) + 2))
        for k in range(seg + 1):
            aa = a0 + da * k / seg
            out.append((c.x + rr * math.cos(aa), c.y + rr * math.sin(aa)))
    return out


def offset_rect(u0, u1, v0, v1, r, d, seg=4):
    return rounded_rect(u0 - d, u1 + d, v0 - d, v1 + d, max(r + d, 0.004), seg)


def u_outline(y0, y1, zb, zt, r, seg=6):
    """Open-bottom arch outline: up the rear edge, rounded top corners, down the front edge."""
    pts = [(y0, zb)]
    for i in range(seg + 1):
        a = math.pi - (math.pi / 2) * i / seg
        pts.append((y0 + r + r * math.cos(a), zt - r + r * math.sin(a)))
    for i in range(seg + 1):
        a = math.pi / 2 - (math.pi / 2) * i / seg
        pts.append((y1 - r + r * math.cos(a), zt - r + r * math.sin(a)))
    pts.append((y1, zb))
    return pts


# ------------------------------------------------------------------ spaces

class Space:
    """Design space -> coach space (see module docstring)."""

    def __init__(self, c):
        self.S = c.get("scale", 1.4)
        self.SX = c.get("half_width", 1.25) / HW_N
        self.yf = c.get("front_wall_y", 0.03)
        self.zc = c.get("cabover_bottom_z", 1.26)
        self.L = 0.0

    def y(self, y):
        return self.yf + self.S * (y - YB_N) - (self.L if y < PLUG_CUT_N else 0.0)

    def z(self, z):
        return self.zc + self.S * (z - ZC_N)

    def iy(self, y):                     # inverse, valid without a plug
        return YB_N + (y - self.yf) / self.S

    def iz(self, z):
        return ZC_N + (z - self.zc) / self.S

    def T(self, co):
        return Vector((co[0] * self.SX, self.y(co[1]), self.z(co[2])))


def to_coach_ob(ob, sp):
    me = ob.data
    for v in me.vertices:
        v.co = sp.T(v.co)
    me.update()


def to_coach_bm(bm, sp):
    for v in bm.verts:
        v.co = sp.T(v.co)


class Geo:
    """Design-space body numbers (hw, yr, z0, zc, ztop, yb, yn, nose faces) + coach-space copies."""

    def __init__(self, c, sp, ti):
        self.exact = c["style"] == "slide_in_exact"
        self.hw, self.zc, self.ztop, self.yb = HW_N, ZC_N, ZT_N, YB_N
        rear_y = c.get("rear_y", -4.20)
        if self.exact:
            self.yr, self.z0 = YR_N, Z0_N
            sp.L = sp.y(YR_N) - rear_y
        else:
            self.yr = sp.iy(rear_y)
            self.z0 = sp.iz(c.get("skirt_z", -0.30))
        self.yn = sp.iy(c["nose_y"]) if "nose_y" in c else YN_N
        self.ff0 = (self.yn - 0.06, self.zc + 0.18)
        self.ff1 = (self.yn, self.zc + 0.54)
        t = Vector((0.0, self.ff1[0] - self.ff0[0], self.ff1[1] - self.ff0[1])).normalized()
        self.fn = Vector((0.0, t.z, -t.y))
        self.sl0 = (self.yn, self.zc + 0.54)
        self.sl1 = (self.yn - 0.42, self.ztop)
        self.ti = ti
        self.sp = sp
        # coach space
        self.HW, self.YR, self.YF = c.get("half_width", 1.25), rear_y, sp.yf
        self.ZS, self.ZT = sp.z(self.z0), sp.z(self.ztop)
        self.k, self.kd = sp.S, sp.SX           # design -> coach scale (in-plane, depth)

    # design-space mappers (u, v, d) -> xyz
    def side(self, sgn):
        hw = self.hw
        return lambda u, v, d: Vector((sgn * (hw + d), u, v))

    def rear(self):
        yr = self.yr
        return lambda u, v, d: Vector((u, yr - d, v))

    def front(self):
        (y0, z0), (y1, z1), n = self.ff0, self.ff1, self.fn

        def m(u, v, d):
            y = y0 + (v - z0) * (y1 - y0) / (z1 - z0)
            return Vector((u, y, v)) + n * d
        return m

    # coach-space mappers
    def cside(self, sgn):
        hw = self.HW
        return lambda u, v, d: Vector((sgn * (hw + d), u, v))

    def crear(self):
        yr = self.YR
        return lambda u, v, d: Vector((u, yr - d, v))


def ring(mapper, outline, d):
    return [mapper(u, v, d) for u, v in outline]


def plate(part, mapper, outline, d0, d1, key):
    """Thin prism on a body surface: outline [(u, v)] between depths d0..d1 (d > 0 = outward)."""
    bm = part.bm
    faces = build_prism(bm, ring(mapper, outline, d0), ring(mapper, outline, d1))
    bmesh.ops.recalc_face_normals(bm, faces=faces)
    u, v = outline[0]
    out = mapper(u, v, 1.0) - mapper(u, v, 0.0)
    cap = faces[1] if d1 > d0 else faces[0]
    cap.normal_update()
    if cap.normal.dot(out) < 0:
        bmesh.ops.reverse_faces(bm, faces=faces)
    part.set_mat(faces, key)
    return faces


def frame_ring(part, mapper, outline_in, outline_out, d0, d1, key):
    faces = annulus_prism(part.bm, ring(mapper, outline_out, d0), ring(mapper, outline_out, d1),
                          ring(mapper, outline_in, d0), ring(mapper, outline_in, d1))
    part.set_mat(faces, key)
    return faces


# ------------------------------------------------------------------ materials

def setup_materials(c, mats):
    if "sl_gel" in mats:
        return
    mats.add("sl_gel", mats.principled(NAME + "_gelcoat", base_color=tuple(c.get("gelcoat", (0.80, 0.805, 0.79, 1.0))),
                                       roughness=0.26, specular=0.5, clearcoat=0.45, clearcoat_roughness=0.12))
    mats.add("sl_stripe", mats.principled(NAME + "_stripe", base_color=tuple(c.get("stripe", (0.055, 0.058, 0.062, 1.0))),
                                          roughness=0.45, specular=0.3))
    mats.add("sl_frame", mats.principled(NAME + "_frame", base_color=(0.018, 0.018, 0.02, 1.0),
                                         roughness=0.42, metallic=0.25))
    mats.add("sl_under", mats.principled(NAME + "_under", base_color=(0.11, 0.11, 0.105, 1.0), roughness=0.7))
    mats.add("sl_acwhite", mats.principled(NAME + "_ac", base_color=(0.70, 0.70, 0.68, 1.0),
                                           roughness=0.38, clearcoat=0.2))
    mats.add("sl_awning", mats.principled(NAME + "_awning", base_color=(0.05, 0.052, 0.055, 1.0),
                                          metallic=0.5, roughness=0.35))


# ------------------------------------------------------------------ layout

def window_lists(g):
    """(design-space windows, coach-space windows): (mapper, (u0, u1, v0, v1), mullion_u, k, kd)."""
    fz0, fz1 = g.ff0[1] + 0.09, g.ff1[1] - 0.08
    native = [(g.front(), (-0.56, 0.56, fz0, fz1), None, 1.0, 1.0)]
    coach = []
    if g.exact:
        for sgn in (-1, 1):
            s = g.side(sgn)
            native.append((s, (0.42, 0.92, g.zc + 0.21, g.zc + 0.53), None, 1.0, 1.0))
            native.append((s, (-1.18, -0.32, 0.78, 1.22), -0.75, 1.0, 1.0))
        native.append((g.rear(), (0.06, 0.46, 0.80, 1.16), None, 1.0, 1.0))
        native.append((g.rear(), (-0.66, -0.28, 0.86, 1.24), None, 1.0, 1.0))   # door window
    else:
        k, kd = g.k, g.kd
        for sgn in (-1, 1):
            s = g.cside(sgn)
            coach.append((s, (0.62, 1.32, 1.56, 2.00), None, k, kd))            # cabover
            coach.append((s, (-3.95, -3.35, 1.64, 2.02), None, k, kd))          # bedroom
            if sgn < 0:
                coach.append((s, (-1.80, -0.58, 1.20, 1.82), -1.19, k, kd))      # dinette
            else:
                coach.append((s, (-2.85, -1.85, 1.20, 1.82), -2.35, k, kd))      # lounge over the arch
                coach.append((s, (-0.97, -0.53, 1.24, 1.70), None, k, kd))       # door window
        coach.append((g.crear(), (-0.75, 0.15, 1.62, 2.02), None, k, kd))
    return native, coach


def door_c(g):
    return (-1.10, -0.40, g.ZS + 0.16, 1.92, 0.07)


def hatches_c(g):
    z0, z1 = g.ZS + 0.17, 0.42
    return [(-1, (-1.45, -0.80, z0, z1, 0.05)), (-1, (-0.62, -0.22, z0, z1, 0.05)),
            (-1, (-3.98, -3.10, z0, z1, 0.05)), (1, (-3.98, -3.25, z0, z1, 0.05))]


def arch_c(g):
    ti = g.ti
    y_ra = ti["rear_axle_y"]
    r = ti.get("rear_tire_radius", ti["tire_radius"])
    # opening 1.20 m long, top 8 cm above the tyre, 0.12 corners: >= ~7 cm clear of the tyre outline
    return y_ra - 0.60, y_ra + 0.60, ti["ground_z"] + 2 * r + 0.08, 0.12


ARCH_TRIM_W = 0.045                     # coach-space width of the squared arch trim


def arch_gaps_n(g):
    """Design-space y spans a lower-body strip must skip: each rear arch opening, with the strip ends
    tucked half way under the arch trim legs (empty on the exact style, which has no arch)."""
    if g.exact:
        return []
    y0, y1, _, _ = arch_c(g)
    h = ARCH_TRIM_W / 2
    return [(g.sp.iy(y0 - h), g.sp.iy(y1 + h))]


def split_span(a, b, gaps):
    """[a, b] minus the gap intervals, as a list of (u0, u1) pieces."""
    out = [(a, b)]
    for g0, g1 in gaps:
        nxt = []
        for u0, u1 in out:
            if g1 <= u0 or g0 >= u1:
                nxt.append((u0, u1))
                continue
            if g0 > u0:
                nxt.append((u0, g0))
            if g1 < u1:
                nxt.append((g1, u1))
        out = nxt
    return out


# ------------------------------------------------------------------ body

def cut_pockets(cbm, wins):
    for mapper, (u0, u1, v0, v1), _, k, kd in wins:
        ol = rounded_rect(u0, u1, v0, v1, 0.05 * k, 4)
        faces = build_prism(cbm, ring(mapper, ol, 0.08 * kd), ring(mapper, ol, -POCKET * kd), mat_index=2)
        bmesh.ops.recalc_face_normals(cbm, faces=faces)
        faces[0].material_index = 2
        faces[1].material_index = 0


def cut_groove(cbm, mapper, panel, k=1.0, kd=1.0):
    u0, u1, v0, v1, r = panel
    o = rounded_rect(u0, u1, v0, v1, r, 4)
    i = offset_rect(u0, u1, v0, v1, r, -0.006 * k)
    annulus_prism(cbm, ring(mapper, o, 0.05 * kd), ring(mapper, o, -0.018 * kd),
                  ring(mapper, i, 0.05 * kd), ring(mapper, i, -0.018 * kd), 1)


def build_body(g, sp, mats, col):
    yr, yb, yn, z0, zc, zt = g.yr, g.yb, g.yn, g.z0, g.zc, g.ztop
    prof = fillet_poly([
        (yr, z0, 0.05),
        (yb, z0, 0.03),
        (yb, zc, 0.06),                           # concave corner under the cabover
        (yn - 0.40, zc, 0.12),
        (g.ff0[0], g.ff0[1], 0.10),
        (g.ff1[0], g.ff1[1], 0.16),
        (yn - 0.42, zt, 0.34),
        (yr, zt, 0.09),
    ])
    p = Part(f"{NAME}_body", mats)
    vs = prism_x(p, prof, -g.hw, g.hw, "sl_gel")
    bm = p.bm
    cap_edges = list({e for v in vs for e in v.link_edges if abs(e.verts[0].co.x - e.verts[1].co.x) < 1e-6})
    bevel(bm, cap_edges, 0.065, 3)
    bm.normal_update()
    p.set_mat([f for f in bm.faces if f.normal.z < -0.55], "sl_under")
    body = p.finish(col, smooth=35)
    to_coach_ob(body, sp)

    native, coach = window_lists(g)
    cbm = bmesh.new()
    cut_pockets(cbm, native)
    if g.exact:
        cut_groove(cbm, g.rear(), DOOR)
        cut_groove(cbm, g.side(-1), HATCH)
    to_coach_bm(cbm, sp)
    cut_pockets(cbm, coach)
    if not g.exact:
        cut_groove(cbm, g.cside(1), door_c(g), g.k, g.kd)
        for sgn, h in hatches_c(g):
            cut_groove(cbm, g.cside(sgn), h, g.k, g.kd)
        y0, y1, ztop_a, r = arch_c(g)
        ol = u_outline(y0, y1, g.ZS - 0.25, ztop_a, r)
        for sgn in (-1, 1):
            faces = build_prism(cbm, [(sgn * (g.HW + 0.3), u, v) for u, v in ol],
                                [(sgn * 0.62, u, v) for u, v in ol], mat_index=3)
            bmesh.ops.recalc_face_normals(cbm, faces=faces)
    cutter = bm_object(f"{NAME}_cut", cbm, [mats["curtain"], mats["sl_frame"], mats["interior"], mats["sl_under"]], col)
    boolean_apply(body, cutter)
    finish_hard_surface(body, 35)
    return body


# ------------------------------------------------------------------ design-space details

def stripes(g, p):
    top0, drop = (0.86, 0.58) if g.exact else (0.70, 0.62)
    for sgn in (-1, 1):
        s = g.side(sgn)
        y0, ytip, n = g.yr + 0.075, -0.30, 40

        def top_a(t):
            return top0 - drop * t ** 1.15

        def th_a(t):
            return 0.15 * (1 - t) ** 0.85

        for top, th in ((top_a, th_a),
                        (lambda t: top_a(t) - th_a(t) - 0.032 * (1 - t), lambda t: 0.042 * (1 - t) ** 0.85)):
            ts = [i / n for i in range(n + 1)]
            upper = [(y0 + (ytip - y0) * t, top(t)) for t in ts]
            lower = [(y0 + (ytip - y0) * t, top(t) - th(t)) for t in ts[:-1]]
            plate(p, s, upper + lower[::-1], -0.003, 0.004, "sl_stripe")
        # thin cabover line, widening toward the nose
        n2 = 8
        ye = g.yn - 0.28
        ys = [0.20 + (ye - 0.20) * i / n2 for i in range(n2 + 1)]
        zb = g.zc + 0.09
        upper = [(y, zb + 0.016 + 0.03 * ((y - 0.20) / (ye - 0.20)) ** 1.5) for y in ys]
        lower = [(y, zb) for y in ys]
        plate(p, s, lower + upper[::-1], -0.003, 0.004, "sl_stripe")
    # rear: a band at the swoosh height (either side of the door on the exact style)
    r = g.rear()
    spans = ((-g.hw + 0.075, DOOR[0] - 0.04), (0.50, g.hw - 0.075)) if g.exact else ((-g.hw + 0.075, g.hw - 0.075),)
    for u0, u1 in spans:
        plate(p, r, [(u0, top0 - 0.15), (u1, top0 - 0.15), (u1, top0 - 0.01), (u0, top0 - 0.01)], -0.003, 0.004,
              "sl_stripe")
        plate(p, r, [(u0, top0 - 0.215), (u1, top0 - 0.215), (u1, top0 - 0.182), (u0, top0 - 0.182)], -0.003, 0.004,
              "sl_stripe")


def windows_trim(p, wins):
    for mapper, (u0, u1, v0, v1), mull, k, kd in wins:
        r = 0.05 * k
        ol = rounded_rect(u0, u1, v0, v1, r, 4)
        outer = offset_rect(u0, u1, v0, v1, r, 0.035 * k)
        inner = offset_rect(u0, u1, v0, v1, r, -0.004 * k)
        frame_ring(p, mapper, inner, outer, -0.004 * kd, 0.014 * kd, "sl_frame")
        bm = p.bm
        pane = bm.faces.new([bm.verts.new(q) for q in ring(mapper, ol, GLASS_D * kd)])
        pane.normal_update()
        u_, v_ = ol[0]
        if pane.normal.dot(mapper(u_, v_, 1.0) - mapper(u_, v_, 0.0)) < 0:
            pane.normal_flip()
        p.set_mat([pane], "glass_tint")
        frame_ring(p, mapper, offset_rect(u0, u1, v0, v1, r, -0.012 * k), inner, (GLASS_D - 0.004) * kd,
                   0.002 * kd, "seal")
        if mull is not None:
            w = 0.012 * k
            plate(p, mapper, [(mull - w, v0), (mull + w, v0), (mull + w, v1), (mull - w, v1)], -0.03 * kd,
                  0.008 * kd, "sl_frame")
        plate(p, mapper, [(u0, v0), (u1, v0), (u1, v0 + 0.018 * k), (u0, v0 + 0.018 * k)], -0.03 * kd,
              0.004 * kd, "sl_frame")


def rear_top_lamps(g, p):
    r = g.rear()
    hw, zt = g.hw, g.ztop
    for sgn in (-1, 1):
        uc = sgn * (hw - 0.12)
        plate(p, r, rounded_rect(uc - 0.035, uc + 0.035, zt - 0.11, zt - 0.075, 0.01, 2), 0.0, 0.02, "lamp_red_lens")
    for u in (-0.12, 0.0, 0.12):     # ID lamp bar
        plate(p, r, rounded_rect(u - 0.03, u + 0.03, zt - 0.11, zt - 0.08, 0.01, 2), 0.0, 0.02, "lamp_red_lens")


def rear_details_exact(g, p):
    r = g.rear()
    hw, yr, zt = g.hw, g.yr, g.ztop
    plate(p, r, rounded_rect(-0.255, -0.205, 0.66, 0.80, 0.015, 2), 0.0, 0.02, "chrome")
    plate(p, r, rounded_rect(-0.25, -0.21, 0.83, 0.87, 0.015, 2), 0.0, 0.015, "sl_frame")
    for z in (0.30, 0.75, 1.20):
        plate(p, r, [(-0.80, z), (-0.74, z), (-0.74, z + 0.07), (-0.80, z + 0.07)], 0.0, 0.012, "sl_frame")
    for z in (0.42, 0.92):
        cylinder_y(p, -0.08, z, 0.012, yr + 0.01, yr - 0.06, "chrome", seg=8)
    cylinder_z(p, -0.08, yr - 0.06, 0.014, 0.40, 0.94, "chrome", seg=10)
    plate(p, r, rounded_rect(-0.52, -0.42, 1.43, 1.47, 0.012, 2), 0.0, 0.03, "plastic_white")
    plate(p, r, rounded_rect(-0.51, -0.43, 1.432, 1.444, 0.004, 1), 0.02, 0.031, "lamp_clear")
    for sgn in (-1, 1):
        ua, ub = sorted((sgn * (hw - 0.22), sgn * (hw - 0.09)))
        plate(p, r, rounded_rect(ua, ub, 0.11, 0.47, 0.02, 2), 0.0, 0.018, "sl_frame")
        plate(p, r, rounded_rect(ua + 0.012, ub - 0.012, 0.29, 0.455, 0.012, 2), 0.01, 0.03, "lamp_red_lens")
        plate(p, r, rounded_rect(ua + 0.012, ub - 0.012, 0.19, 0.28, 0.012, 2), 0.01, 0.03, "lamp_amber")
        plate(p, r, rounded_rect(ua + 0.012, ub - 0.012, 0.125, 0.18, 0.012, 2), 0.01, 0.03, "lamp_clear")
    ly = yr - 0.075
    for x in (0.60, 0.90):
        cylinder_z(p, x, ly, 0.016, 0.40, zt + 0.10, "alloy", seg=10)
        cylinder_y(p, x, zt + 0.10, 0.016, ly, yr + 0.26, "alloy", seg=10)
        cylinder_z(p, x, yr + 0.26, 0.016, zt - 0.01, zt + 0.10, "alloy", seg=10)
        for z in (0.48, 1.30):
            cylinder_y(p, x, z, 0.011, yr + 0.01, ly, "alloy", seg=8)
    for k in range(5):
        cylinder_x(p, ly, 0.52 + k * 0.215, 0.013, 0.60, 0.90, "alloy", seg=8)
    box(p, (DOOR[0] + 0.04, yr + 0.02, -0.11), (DOOR[1] - 0.04, yr + 0.30, -0.02), "sl_frame", bev=0.008)
    box(p, (DOOR[0] + 0.06, yr - 0.005, -0.10), (DOOR[1] - 0.06, yr + 0.02, -0.03), "steel")


def side_details(g, p):
    zt, zc = g.ztop, g.zc
    for sgn in (-1, 1):
        s = g.side(sgn)
        zb = g.z0 + 0.01
        for u0, u1 in split_span(g.yr + 0.07, g.yb - 0.02, arch_gaps_n(g)):     # skirt trim, cut at the arch
            plate(p, s, [(u0, zb), (u1, zb), (u1, zb + 0.03), (u0, zb + 0.03)], -0.004, 0.01, "sl_frame")
        plate(p, s, [(g.yr + 0.07, zt - 0.085), (g.yn - 0.42, zt - 0.085), (g.yn - 0.42, zt - 0.06),
                     (g.yr + 0.07, zt - 0.06)], -0.004, 0.012, "sl_frame")
        plate(p, s, rounded_rect(1.16, 1.22, zc + 0.20, zc + 0.24, 0.01, 2), 0.0, 0.018, "lamp_amber")
        plate(p, s, rounded_rect(g.yr + 0.12, g.yr + 0.18, zt - 0.13, zt - 0.09, 0.01, 2), 0.0, 0.018,
              "lamp_red_lens")
        if g.exact:
            plate(p, s, rounded_rect(-0.62, -0.56, 0.12, 0.16, 0.01, 2), 0.0, 0.016, "lamp_amber")
    if not g.exact:
        return
    s = g.side(-1)
    u0, u1, v0, v1, _ = HATCH
    plate(p, s, rounded_rect((u0 + u1) / 2 - 0.03, (u0 + u1) / 2 + 0.03, v0 + 0.05, v0 + 0.09, 0.01, 2),
          0.0, 0.014, "chrome")
    plate(p, s, [(u0 + 0.03, v1 - 0.03), (u1 - 0.03, v1 - 0.03), (u1 - 0.03, v1 - 0.012), (u0 + 0.03, v1 - 0.012)],
          0.0, 0.01, "sl_frame")
    plate(p, s, rounded_rect(-1.30, -1.20, 0.14, 0.24, 0.015, 2), 0.0, 0.012, "plastic_white")
    plate(p, s, rounded_rect(-1.27, -1.23, 0.17, 0.21, 0.01, 2), 0.0, 0.02, "sl_frame")
    fridge_vents(p, g.side(1), [(-1.92, -1.47, 0.12, 0.36), (-1.92, -1.47, 1.25, 1.40)], 1.0, 1.0)


def fridge_vents(p, s, rects, k, kd):
    for u0, u1, v0, v1 in rects:
        plate(p, s, rounded_rect(u0, u1, v0, v1, 0.02 * k, 2), -0.003 * kd, 0.012 * kd, "plastic_white")
        nl = max(2, int((v1 - v0) / (0.04 * k)))
        for i in range(nl):
            vv = v0 + 0.025 * k + i * (v1 - v0 - 0.05 * k) / max(nl - 1, 1)
            w = 0.008 * k
            plate(p, s, [(u0 + 0.03 * k, vv - w), (u1 - 0.03 * k, vv - w), (u1 - 0.03 * k, vv + w),
                         (u0 + 0.03 * k, vv + w)], 0.0, 0.016 * kd, "sl_frame")


def front_details(g, p):
    (y0, z0), (y1, z1) = g.sl0, g.sl1
    t = Vector((0.0, y1 - y0, z1 - z0)).normalized()
    n = Vector((0.0, -t.z, t.y))
    if n.y < 0:
        n = -n
    ax = (Vector((1, 0, 0)), t, n)
    base = Vector((0.0, y0, z0)) + t * 0.13
    for u in (-0.16, 0.0, 0.16):
        oriented_box(p, base + Vector((u, 0, 0)) + n * 0.006, ax, (0.06, 0.035, 0.018), "lamp_amber", bev=0.004)
    for sgn in (-1, 1):
        oriented_box(p, base + Vector((sgn * (g.hw - 0.14), 0, 0)) + n * 0.006, ax, (0.06, 0.035, 0.018),
                     "lamp_amber", bev=0.004)
    f = g.front()
    zt = g.ff1[1] - 0.04
    plate(p, f, [(-0.62, zt), (0.62, zt), (0.62, zt + 0.02), (-0.62, zt + 0.02)], -0.004, 0.03, "sl_frame")


def roof(g, p):
    zt = g.ztop
    prof = fillet_poly([(-1.32, zt, 0.0), (-0.38, zt, 0.0), (-0.38, zt + 0.12, 0.06),
                        (-0.58, zt + 0.25, 0.10), (-1.26, zt + 0.25, 0.06), (-1.32, zt + 0.20, 0.03)])
    vs = prism_x(p, prof, -0.37, 0.37, "sl_acwhite")
    edges = list({e for v in vs for e in v.link_edges if abs(e.verts[0].co.x - e.verts[1].co.x) < 1e-6
                  and min(e.verts[0].co.z, e.verts[1].co.z) > zt + 0.01})
    bevel(p.bm, edges, 0.04, 2)
    for sgn in (-1, 1):
        x = sgn * 0.37
        box(p, (min(x, x + sgn * 0.006), -1.20, zt + 0.05), (max(x, x + sgn * 0.006), -0.62, zt + 0.17), "sl_frame")
        for k in range(5):
            z = zt + 0.065 + k * 0.023
            box(p, (min(x, x + sgn * 0.012), -1.20, z), (max(x, x + sgn * 0.012), -0.62, z + 0.008), "sl_acwhite")
    for yc in (0.55, -1.80):
        box(p, (-0.21, yc - 0.21, zt - 0.01), (0.21, yc + 0.21, zt + 0.045), "plastic_white", bev=0.01)
        ang = math.radians(9)
        t = Vector((0, math.cos(ang), -math.sin(ang)))
        n = Vector((0, math.sin(ang), math.cos(ang)))
        c = Vector((0, yc, zt + 0.045 + 0.04))
        oriented_box(p, c, (Vector((1, 0, 0)), t, n), (0.38, 0.40, 0.025), "trim_gloss", bev=0.008)
    box(p, (-g.hw + 0.06, g.yr - 0.012, zt - 0.085), (g.hw - 0.06, g.yr + 0.01, zt - 0.06), "sl_frame")


def jacks(g, p):
    hw = g.hw
    for yc in (g.yb - 0.16, g.yr + 0.12):
        for sgn in (-1, 1):
            xs = sorted((sgn * (hw - 0.01), sgn * (hw + 0.035)))
            box(p, (xs[0], yc - 0.07, 0.12), (xs[1], yc + 0.07, 0.78), "sl_frame", bev=0.006)
            xc = sgn * (hw + 0.08)
            cylinder_z(p, xc, yc, 0.032, 0.02, 0.80, "sl_frame", seg=12)
            cylinder_z(p, xc, yc, 0.024, -0.14, 0.02, "steel", seg=12)
            box(p, (xc - 0.055, yc - 0.055, -0.16), (xc + 0.055, yc + 0.055, -0.14), "sl_frame", bev=0.004)
            box(p, (xc - 0.045, yc - 0.045, 0.80), (xc + 0.045, yc + 0.045, 0.88), "sl_frame", bev=0.008)
            cylinder_x(p, yc, 0.84, 0.009, xc, xc + sgn * 0.08, "steel", seg=8)
            for z in (0.18, 0.70):
                box(p, (min(xc, sgn * (hw + 0.03)), yc - 0.02, z), (max(xc, sgn * (hw + 0.03)), yc + 0.02, z + 0.04),
                    "sl_frame")


# ------------------------------------------------------------------ coach-space parts

def rear_bumper(g, q, low):
    """Rear bumper + hitch receiver at the coach rear; `low` = bumper top z."""
    yr = g.YR
    box(q, (-1.08, yr - 0.14, low - 0.16), (1.08, yr + 0.02, low), "sl_frame", bev=0.02)
    box(q, (-0.045, yr - 0.30, low - 0.25), (0.045, yr + 0.30, low - 0.16), "frame", bev=0.008, seg=1)


def exact_chassis_parts(g, sp, q):
    """Narrow basement down between the duals (like the slide-in's in-bed basement), bumper on brackets."""
    z0c = sp.z(Z0_N)
    ye = sp.y(BASE_END_N)
    bhw = 0.66
    box(q, (-bhw, ye, -0.12), (bhw, 0.0, z0c + 0.015), "sl_gel", bev=0.02)
    box(q, (-bhw + 0.01, ye - 0.015, -0.115), (bhw - 0.01, ye + 0.02, -0.04), "rubber", bev=0.008)
    box(q, (-bhw + 0.01, ye - 0.008, 0.06), (bhw - 0.01, ye + 0.01, 0.10), "sl_stripe")
    for sgn in (-1, 1):
        a_, b_ = sorted((sgn * (bhw - 0.08), sgn * (bhw - 0.22)))
        box(q, (a_, ye - 0.015, 0.15), (b_, ye + 0.01, 0.23), "lamp_red_lens", bev=0.006)
    rear_bumper(g, q, -0.22)
    fe = g.ti.get("frame_end_y", g.YR)
    for sgn in (-1, 1):
        a_, b_ = sorted((sgn * 0.36, sgn * 0.44))
        box(q, (a_, g.YR - 0.02, -0.24), (b_, fe + 0.06, -0.04), "frame", bev=0.004)


def styled_parts(g, q):
    HW, ZS, ZT, YR, k, kd = g.HW, g.ZS, g.ZT, g.YR, g.k, g.kd
    ti = g.ti
    _, coach = window_lists(g)
    windows_trim(q, coach)
    # squared wheel-arch trim
    y0, y1, za, r = arch_c(g)
    w = ARCH_TRIM_W
    inner = u_outline(y0, y1, ZS, za, r)
    outer = u_outline(y0 - w, y1 + w, ZS, za + w, r + w)
    for sgn in (-1, 1):
        plate(q, g.cside(sgn), outer + inner[::-1], -0.004, 0.018, "sl_frame")
    # entry door (curb side): paddle handle + lock, hinges, grab handle, porch light, stowed step
    s = g.cside(1)
    u0, u1, v0, v1, _ = door_c(g)
    um, vm = u1 - 0.10, v0 + 1.02
    plate(q, s, rounded_rect(um - 0.035, um + 0.035, vm - 0.10, vm + 0.10, 0.02, 2), 0.0, 0.025, "chrome")
    plate(q, s, rounded_rect(um - 0.025, um + 0.025, vm + 0.14, vm + 0.19, 0.015, 2), 0.0, 0.02, "sl_frame")
    for z in (v0 + 0.30, v0 + 1.00, v1 - 0.30):
        plate(q, s, [(u0 - 0.03, z), (u0 + 0.05, z), (u0 + 0.05, z + 0.10), (u0 - 0.03, z + 0.10)], 0.0, 0.014,
              "sl_frame")
    plate(q, s, rounded_rect(-0.33, -0.29, 0.45, 1.35, 0.018, 2), 0.0, 0.045, "chrome")
    plate(q, s, rounded_rect(-1.27, -1.15, 1.82, 1.88, 0.015, 2), 0.0, 0.04, "plastic_white")
    plate(q, s, rounded_rect(-1.26, -1.16, 1.83, 1.845, 0.005, 1), 0.03, 0.041, "lamp_clear")
    box(q, (HW - 0.32, u0 + 0.06, ZS - 0.15), (HW - 0.01, u1 - 0.06, ZS + 0.005), "sl_frame", bev=0.008)
    box(q, (HW - 0.02, u0 + 0.08, ZS - 0.14), (HW + 0.006, u1 - 0.08, ZS - 0.02), "steel")
    # storage hatches: lock + hinge strip
    for sgn, (h0, h1, hv0, hv1, _) in hatches_c(g):
        sm = g.cside(sgn)
        hm = (h0 + h1) / 2
        plate(q, sm, rounded_rect(hm - 0.04, hm + 0.04, hv0 + 0.07, hv0 + 0.12, 0.012, 2), 0.0, 0.018, "chrome")
        plate(q, sm, [(h0 + 0.04, hv1 - 0.04), (h1 - 0.04, hv1 - 0.04), (h1 - 0.04, hv1 - 0.017),
                      (h0 + 0.04, hv1 - 0.017)], 0.0, 0.012, "sl_frame")
    # fridge vents (curb), shore power (road), low side markers
    fridge_vents(q, s, [(-1.48, -1.18, ZS + 0.18, 0.32), (-1.48, -1.18, 1.30, 1.45)], k, kd)
    sr = g.cside(-1)
    plate(q, sr, rounded_rect(-3.04, -2.90, ZS + 0.20, ZS + 0.34, 0.02, 2), 0.0, 0.014, "plastic_white")
    plate(q, sr, rounded_rect(-3.00, -2.94, ZS + 0.24, ZS + 0.30, 0.012, 2), 0.0, 0.024, "sl_frame")
    for sgn in (-1, 1):
        sm = g.cside(sgn)
        plate(q, sm, rounded_rect(-0.18, -0.10, ZS + 0.22, ZS + 0.28, 0.012, 2), 0.0, 0.02, "lamp_amber")
        plate(q, sm, rounded_rect(YR + 0.12, YR + 0.20, ZS + 0.22, ZS + 0.28, 0.012, 2), 0.0, 0.02, "lamp_red_lens")
    # rear wall: tail lamps (low corners), plate, ladder
    rr = g.crear()
    lv0 = ZS + 0.10

    def lv(vn):
        return lv0 + (vn - 0.11) * k
    for sgn in (-1, 1):
        ua, ub = sorted((sgn * (HW - 0.255), sgn * (HW - 0.104)))
        e = 0.014
        plate(q, rr, rounded_rect(ua, ub, lv(0.11), lv(0.47), 0.025, 2), 0.0, 0.02, "sl_frame")
        plate(q, rr, rounded_rect(ua + e, ub - e, lv(0.29), lv(0.455), 0.014, 2), 0.01, 0.034, "lamp_red_lens")
        plate(q, rr, rounded_rect(ua + e, ub - e, lv(0.19), lv(0.28), 0.014, 2), 0.01, 0.034, "lamp_amber")
        plate(q, rr, rounded_rect(ua + e, ub - e, lv(0.125), lv(0.18), 0.014, 2), 0.01, 0.034, "lamp_clear")
    plate(q, rr, rounded_rect(-0.22, 0.22, ZS + 0.20, ZS + 0.42, 0.02, 1), -0.003, 0.012, "plate")
    ly = YR - 0.105
    for x in (0.45, 0.80):
        cylinder_z(q, x, ly, 0.019, ZS + 0.05, ZT + 0.14, "alloy", seg=10)
        cylinder_y(q, x, ZT + 0.14, 0.019, ly, YR + 0.36, "alloy", seg=10)
        cylinder_z(q, x, YR + 0.36, 0.019, ZT - 0.01, ZT + 0.14, "alloy", seg=10)
        for z in (ZS + 0.15, 1.30, 2.15):
            cylinder_y(q, x, z, 0.013, YR + 0.01, ly, "alloy", seg=8)
    z = ZS + 0.30
    while z < ZT - 0.05:
        cylinder_x(q, ly, z, 0.016, 0.45, 0.80, "alloy", seg=8)
        z += 0.30
    rear_bumper(g, q, ZS + 0.04)
    for sgn in (-1, 1):
        box(q, (sgn * 1.0 - 0.2, ti["rear_axle_y"] - 0.66, ti["ground_z"] + 0.18),
            (sgn * 1.0 + 0.2, ti["rear_axle_y"] - 0.64, ZS + 0.02), "rubber")
    # awning (curb side), roll under the roof cap, arms down the wall
    xa, za = HW + 0.085, ZT - 0.30
    ya0, ya1 = -3.20, -0.20
    cylinder_y(q, xa, za, 0.075, ya0, ya1, "sl_awning", seg=16)
    box(q, (xa - 0.06, ya0 - 0.02, za - 0.13), (xa + 0.06, ya1 + 0.02, za - 0.05), "sl_awning")
    for y in (ya0 + 0.08, ya1 - 0.06):
        cylinder_y(q, xa, za, 0.08, y - 0.03, y + 0.03, "sl_frame", seg=16)
        box(q, (HW + 0.005, y - 0.025, ZS + 0.22), (HW + 0.045, y + 0.025, za - 0.05), "sl_frame", bev=0.006, seg=1)


# ------------------------------------------------------------------ build

def build(cfg, collection, mats):
    c = cfg["camper"]
    if c.get("style") not in STYLES:
        raise ValueError(f"slide_in_style: camper.style must be one of {STYLES}")
    setup_materials(c, mats)
    sp = Space(c)
    g = Geo(c, sp, cfg["truck_info"])
    objs = [build_body(g, sp, mats, collection)]

    p = Part(f"{NAME}_details", mats)            # design space, mapped to the coach below
    native, _ = window_lists(g)
    stripes(g, p)
    windows_trim(p, native)
    rear_top_lamps(g, p)
    side_details(g, p)
    front_details(g, p)
    roof(g, p)
    if g.exact:
        rear_details_exact(g, p)
        jacks(g, p)
    pob = p.finish(collection, smooth=35)
    to_coach_ob(pob, sp)
    objs.append(pob)

    q = Part(f"{NAME}_parts", mats)              # coach space
    if g.exact:
        exact_chassis_parts(g, sp, q)
    else:
        styled_parts(g, q)
    objs.append(q.finish(collection, smooth=35))
    tris = sum(len(pl.vertices) - 2 for o in objs for pl in o.data.polygons)
    print(f"[{NAME}] style={c['style']} plug={sp.L:.3f} nose_y={sp.y(g.yn):.3f} roof_z={g.ZT:.3f} "
          f"skirt_z={g.ZS:.3f} triangles={tris}")
    return objs
