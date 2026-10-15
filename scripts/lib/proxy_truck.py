"""Render-only stand-in full-size pickup (original, generic and DEBADGED geometry).

Never exported, never packaged; context for preview renders only. It is not a game or
manufacturer model: only approximate published overall proportions of a full-size crew-cab
pickup. No logos, ovals, lettering or badges anywhere.

Two body types (spec["type"]):
  pickup       - 4-door crew cab, 5.5 ft bed with tailgate (spec["tailgate"]: closed | down |
                 removed), wheelbase ~3.68 m
  cab_chassis  - same cab/front end, no bed, longer wheelbase (default 4.3 m), exposed frame rails
                 behind the cab, optional dual rear wheels (spec["dual_rear_wheels"]) - the base for
                 a Class C motorhome body.

Construction: body panels are lofted cross-sections (tumblehome, shoulder crease, tuck-under),
bevelled caps, EXACT-boolean wheel arches and panel gaps, weighted normals for clean shading.
The greenhouse is a hollow shell with real window openings, tinted panes and a simple interior.

Truck-local frame while building: ground z = 0, +Y forward, y = 0 is 7 cm behind the cab back
(= the pickup bed front wall). build_truck() then moves everything so the variant mount point
is the world origin and returns TruckInfo (see its docstring).
"""
import math

import bmesh
import bpy
from mathutils import Vector

from lib.meshkit import (
    Part, annulus_prism, arc_band_x, bevel, bm_object, boolean_apply, box, build_prism, cylinder_x,
    cylinder_y, cylinder_z, finish_hard_surface, loft, oriented_box, prism_x, prism_y, revolve_x, rounded_poly,
    rounded_rect, sweep_arc_x,
)

COLLECTION = "preview_context"

DEFAULTS = {
    "type": "pickup",                 # pickup | cab_chassis
    "cab": "crew",                    # crew (4 doors) | regular (2 doors, cab 0.72 m shorter)
    "windshield_rake": None,          # horizontal run of the windshield; None -> 0.80 crew / 0.70 regular
    "body_hw": 0.99,                  # half body width at the shoulder (flares reach ~1.015)
    "cab_back_y": 0.07,
    "cowl_y": 2.20,                   # windshield base
    "front_y": 4.00,
    "front_axle_y": 2.94,
    "wheelbase": 3.68,                # pickup
    "cab_chassis_wheelbase": 4.30,    # used when type == cab_chassis (unless wheelbase_cc given)
    "rail_z": 1.44,                   # bed rail top above ground (pickup mount height)
    "belt_z": 1.43,
    "roof_z": 1.94,
    "rocker_z": 0.53,
    "bed_bottom_z": 0.68,
    "bed_length": 1.70,
    "tire_diameter": 0.82,            # 275/55R20 all-terrain
    "tire_width": 0.275,
    "rim_diameter": 0.508,            # 20 in
    "track": 1.70,
    "spokes": 6,                      # split spokes (2 blades each)
    "wheel_finish": "alloy_dark",     # material key for the wheel face
    "frame_top_z": None,              # None -> 0.62 pickup / 0.80 cab_chassis
    "frame_hw": 0.56,                 # outer face of the frame rails
    "frame_length_behind_cab": 3.30,  # cab_chassis: rails run from y = 0 to y = -this
    "dual_rear_wheels": False,
    "tailgate": "closed",             # pickup: closed | down (open, level with the bed floor) | removed
}


REGULAR_CAB_DELTA = 0.72


class TruckInfo(dict):
    """Truck facts in the VARIANT frame (origin = mount point, +Y forward, +Z up).

    type, mount_local (mount in truck-local coords), ground_z, roof_z, cab_back_y, front_y,
    front_axle_y, rear_axle_y, wheelbase, body_hw, track, tire_radius,
    pickup:      rail_z (=0), bed_length, bed_inner_hw, rail_outer_hw, tailgate_y (bed end), tailgate
    cab_chassis: frame_top_z (=0), frame_hw, frame_end_y, rear_track (outer tyre edge half width)
    objects: list of truck objects (not serialised).
    """


def make_spec(overrides=None):
    s = dict(DEFAULTS)
    s.update({k: v for k, v in (overrides or {}).items() if not k.startswith("_") and k not in ("source", "model")})
    if s["type"] not in ("pickup", "cab_chassis"):
        raise ValueError(f"truck type must be pickup|cab_chassis, got {s['type']}")
    if s["frame_top_z"] is None:
        s["frame_top_z"] = 0.62 if s["type"] == "pickup" else 0.80
    if s["type"] == "cab_chassis":
        s["wheelbase"] = s.get("wheelbase_cc") or s["cab_chassis_wheelbase"]
    if s["tailgate"] not in ("closed", "down", "removed"):
        raise ValueError(f"truck tailgate must be closed|down|removed, got {s['tailgate']}")
    if s["cab"] not in ("crew", "regular"):
        raise ValueError(f"truck cab must be crew|regular, got {s['cab']}")
    if s["cab"] == "regular":           # shorter cab: the front clip slides back, cab back stays put
        d = REGULAR_CAB_DELTA
        s["cowl_y"] -= d
        s["front_y"] -= d
        s["front_axle_y"] -= d
    s["b_pillar_y"] = s["cowl_y"] - 1.0 if s["cab"] == "crew" else None
    if s["windshield_rake"] is None:
        s["windshield_rake"] = 0.80 if s["cab"] == "crew" else 0.70
    return s


# ------------------------------------------------------------------ cross-sections

def side_dx(z, zb, zt, zs, tumble, ztuck, tuck, lip):
    """Inward offset of the body side at height z: tumblehome above the shoulder crease zs,
    tuck-under below ztuck, and a small outward lip exactly on the crease."""
    d = 0.0
    if z > zs:
        d += tumble * (z - zs) / max(zt - zs, 1e-6)
    if z < ztuck:
        d += tuck * ((ztuck - z) / max(ztuck - zb, 1e-6)) ** 2
    d -= lip * math.exp(-((z - zs) / 0.018) ** 2)
    if ztuck < z < zs:                      # slight outward bow of the door/bed-side panels
        d -= 0.008 * math.sin(math.pi * (z - ztuck) / (zs - ztuck))
    return d


def section(W, zb, zt, rt=0.05, rb=0.05, crown=0.0, zs=1.17, tumble=0.03, ztuck=0.70, tuck=0.04,
            lip=0.006):
    """Closed (x, z) body cross-section. Same vertex count for every parameter set, so stations
    loft cleanly. Starts at bottom centre, runs up the right side (+X), back down the left."""
    zs = min(max(zs, zb + rb + 0.08), zt - rt - 0.06)
    pts = []
    for i in range(4):                                         # bottom
        pts.append(((W - rb) * i / 4, zb))
    for i in range(5):                                         # bottom corner
        a = math.radians(-90 + 90 * i / 4)
        pts.append((W - rb + rb * math.cos(a), zb + rb + rb * math.sin(a)))
    lower = [zb + rb + (zs - 0.03 - zb - rb) * k / 5 for k in range(1, 6)]
    upper = [zs + 0.03 + (zt - rt - zs - 0.03) * k / 3 for k in range(0, 4)]
    for z in lower + [zs] + upper:
        pts.append((W, z))
    for i in range(1, 6):                                      # top corner
        a = math.radians(90 * i / 5)
        pts.append((W - rt + rt * math.cos(a), zt - rt + rt * math.sin(a)))
    for i in range(1, 6):                                      # top
        pts.append(((W - rt) * (1 - i / 5), zt))
    out = []
    for x, z in pts:
        x = x - side_dx(z, zb, zt, zs, tumble, ztuck, tuck, lip) * (x / W)
        w = min(max((z - (zt - rt)) / max(rt, 1e-6), 0.0), 1.0)
        z = z + crown * w * (1 - (x / W) ** 2)
        out.append((x, z))
    right = out
    left = [(-x, z) for x, z in reversed(right[1:-1])]
    return right + left


def surface_x(W, zb, zt, z, **kw):
    """Body-side x at height z for a section(W, zb, zt, **kw) (outer skin, right side)."""
    zs = min(max(kw.get("zs", 1.17), zb + kw.get("rb", 0.05) + 0.08), zt - kw.get("rt", 0.05) - 0.06)
    return W - side_dx(z, zb, zt, zs, kw.get("tumble", 0.03), kw.get("ztuck", 0.70), kw.get("tuck", 0.04),
                       kw.get("lip", 0.006))


def station_rings(stations):
    rings = []
    for y, kw in stations:
        rings.append([(x, y, z) for x, z in section(**kw)])
    return rings


def bevel_cap(bm, y, offset, seg=3):
    """Bevel the boundary of the planar end cap lying at y (rounds side/front corners)."""
    edges = [e for e in bm.edges if all(abs(v.co.y - y) < 1e-5 for v in e.verts)
             and len(e.link_faces) == 2]
    bevel(bm, edges, offset, seg)


# ------------------------------------------------------------------ body

class Geo:
    def __init__(self, s):
        self.s = s
        self.W = s["body_hw"]
        self.R = s["tire_diameter"] / 2
        self.rim_r = s["rim_diameter"] / 2
        self.y_fa = s["front_axle_y"]
        self.y_ra = s["front_axle_y"] - s["wheelbase"]
        self.arch_r = self.R + 0.065
        self.arch_z = self.R + 0.025
        self.track_hw = s["track"] / 2
        self.bed_rear = -s["bed_length"]
        self.pickup = s["type"] == "pickup"
        self.cab_kw = dict(zs=1.17, tumble=0.04, ztuck=0.72, tuck=0.045, lip=0.011)
        self.bed_kw = dict(zs=1.17, tumble=0.018, ztuck=0.80, tuck=0.035, lip=0.011)


def build_cab_body(g, mats, col):
    """Front clip + cab lower body: lofted stations, rounded nose, arches, panel gaps."""
    s, W = g.s, g.W
    zb, belt = s["rocker_z"], s["belt_z"]
    yb, yc, yf = s["cab_back_y"], s["cowl_y"], s["front_y"]
    kw = g.cab_kw
    st = [
        (yb, dict(W=W, zb=zb, zt=belt, rt=0.04, **kw)),
        (yc - 0.02, dict(W=W, zb=zb, zt=belt - 0.022, rt=0.045, crown=0.012, **kw)),
        (yf - 1.0, dict(W=W, zb=zb, zt=belt - 0.045, rt=0.05, crown=0.022, **kw)),
        (yf - 0.30, dict(W=W - 0.002, zb=zb, zt=belt - 0.065, rt=0.055, crown=0.024, **kw)),
        (yf - 0.10, dict(W=W - 0.010, zb=zb + 0.01, zt=belt - 0.080, rt=0.065, crown=0.022, **kw)),
        (yf - 0.03, dict(W=W - 0.022, zb=zb + 0.02, zt=belt - 0.098, rt=0.07, crown=0.018, **kw)),
        (yf, dict(W=W - 0.040, zb=zb + 0.03, zt=belt - 0.125, rt=0.07, crown=0.012, **kw)),
    ]
    p = Part("pv_cab_body", mats)
    _, faces = loft(p, station_rings(st), "paint")
    bevel_cap(p.bm, yb, 0.03, 3)
    bevel_cap(p.bm, yf, 0.035, 3)
    # cabin floor at belt height inside the greenhouse is interior trim, not paint
    gi = p.idx("interior")
    for f in p.bm.faces:
        c = f.calc_center_median()
        if f.normal.z > 0.9 and yb + 0.02 < c.y < yc - 0.04 and abs(c.x) < W - 0.06:
            f.material_index = gi
    body = p.finish(col, smooth=35)
    cutters = [arch_cutter(g, mats, col, g.y_fa, 0.62)]
    cutters.append(groove_cutter(g, mats, col, [
        # doors: front edge, B-pillar split, rear edge (vertical slabs, both sides)
        *[("y", y, 0.60, belt + 0.02) for y in (yc - 0.07, s["b_pillar_y"], yb + 0.06) if y is not None],
    ], hood=(yc + 0.02, yf, belt)))
    boolean_apply(body, cutters)
    finish_hard_surface(body, 35)
    return body


def arch_cutter(g, mats, col, y, inner_hw, bed=False):
    """Wheel-arch cutter: one cylinder per side covering only the outer body (no tunnel)."""
    bm = bmesh.new()
    p = Part("pv_arch_cut", mats)
    p.bm = bm
    for sgn in (-1, 1):
        x0, x1 = sorted((sgn * inner_hw, sgn * (g.W + 0.2)))
        cylinder_x(p, y, g.arch_z, g.arch_r, x0, x1, "underbody", seg=48)
    ob = bm_object("pv_arch_cut", bm, [mats[k] for k in p.slots], col)
    return ob


def groove_cutter(g, mats, col, slabs, hood=None, gap=0.0045, depth=0.035):
    """Thin slab cutters for panel gaps. slabs: ("y", y, z0, z1) vertical gaps on both sides."""
    p = Part("pv_gap_cut", mats)
    W = g.W
    for kind, y, z0, z1 in slabs:
        for sgn in (-1, 1):
            xa, xb = sorted((sgn * (W - depth), sgn * (W + 0.1)))
            box(p, (xa, y - gap / 2, z0), (xb, y + gap / 2, z1), "trim")
    if hood:
        y0, y1, belt = hood
        hx = W - 0.115
        for sgn in (-1, 1):                     # hood side shut lines along the top of the fenders
            xa, xb = sorted((sgn * (hx - gap / 2), sgn * (hx + gap / 2)))
            box(p, (xa, y0, belt - 0.2), (xb, y1 + 0.2, belt + 0.1), "trim")
        box(p, (-hx, y0 - gap / 2, belt - 0.12), (hx, y0 + gap / 2, belt + 0.1), "trim")   # cowl line
        zf = belt - 0.148                        # hood front edge across the nose
        box(p, (-hx, y1 - 0.2, zf - gap / 2), (hx, y1 + 0.2, zf + gap / 2), "trim")
    ob = bm_object("pv_gap_cut", p.bm, [mats[k] for k in p.slots], col)
    return ob


def build_bed(g, mats, col):
    """Pickup box: lofted sides continuing the cab section, tub cut, tailgate gaps, rear arches."""
    s, W = g.s, g.W
    zb, zt = s["bed_bottom_z"], s["rail_z"]
    y0, y1 = g.bed_rear, 0.0
    kw = g.bed_kw
    st = [(y0, dict(W=W, zb=zb, zt=zt, rt=0.022, **kw)),
          (y0 + 0.3, dict(W=W, zb=zb, zt=zt, rt=0.022, **kw)),
          (y1 - 0.3, dict(W=W, zb=zb, zt=zt, rt=0.022, **kw)),
          (y1, dict(W=W, zb=zb, zt=zt, rt=0.022, **kw))]
    p = Part("pv_bed", mats)
    loft(p, station_rings(st), "paint")
    bevel_cap(p.bm, y0, 0.035, 3)
    bevel_cap(p.bm, y1, 0.02, 2)
    bed = p.finish(col, smooth=35)
    inner = W - 0.15
    tub = Part("pv_tub_cut", mats)
    box(tub, (-inner, y0 + 0.055, zb + 0.24), (inner, y1 - 0.045, zt + 0.3), "bed_liner")
    tub_ob = bm_object("pv_tub_cut", tub.bm, [mats[k] for k in tub.slots], col)
    gp = Part("pv_tg_cut", mats)
    gap = 0.0045
    tg_hw = W - 0.17
    if s["tailgate"] == "closed":
        for sgn in (-1, 1):
            xa, xb = sorted((sgn * (tg_hw - gap / 2), sgn * (tg_hw + gap / 2)))
            box(gp, (xa, y0 - 0.1, zb + 0.06), (xb, y0 + 0.03, zt + 0.1), "trim")
        box(gp, (-tg_hw, y0 - 0.1, zb + 0.06 - gap / 2), (tg_hw, y0 + 0.03, zb + 0.06 + gap / 2), "trim")
        box(gp, (-tg_hw, y0 + 0.03 - gap / 2, zb + 0.06), (tg_hw, y0 + 0.03 + gap / 2, zt + 0.1), "trim")
    else:
        # tailgate opening: the gate panel is gone down to the bed floor; below it a short rear sill
        # (bed-floor end) stays, with the gate's lower shut line across it
        box(gp, (-tg_hw, y0 - 0.1, zb + 0.24), (tg_hw, y0 + 0.06, zt + 0.1), "bed_liner")
        box(gp, (-tg_hw, y0 - 0.1, zb + 0.06 - gap / 2), (tg_hw, y0 + 0.012, zb + 0.06 + gap / 2), "trim")
    gp_ob = bm_object("pv_tg_cut", gp.bm, [mats[k] for k in gp.slots], col)
    # fuel door (left side): ring-shaped groove cutter
    outline = rounded_rect(-0.62, -0.42, 1.05, 1.24, 0.03, 3)
    inner_ring = rounded_rect(-0.62 + gap, -0.42 - gap, 1.05 + gap, 1.24 - gap, 0.03 - gap, 3)
    fd = Part("pv_fuel_cut", mats)
    annulus_prism(fd.bm, [(-(W + 0.05), y, z) for y, z in outline], [(-(W - 0.02), y, z) for y, z in outline],
                  [(-(W + 0.05), y, z) for y, z in inner_ring], [(-(W - 0.02), y, z) for y, z in inner_ring],
                  fd.idx("trim"))
    fd_ob = bm_object("pv_fuel_cut", fd.bm, [mats[k] for k in fd.slots], col)
    boolean_apply(bed, [tub_ob, gp_ob, fd_ob, arch_cutter(g, mats, col, g.y_ra, inner - 0.02)])
    finish_hard_surface(bed, 35)
    objs = [bed]
    if s["tailgate"] == "down":
        objs.append(build_tailgate_down(g, mats, col, tg_hw))
    return objs


def build_tailgate_down(g, mats, col, tg_hw):
    """Open tailgate: hinged at the bed floor, lying level and rearward; liner up, paint outside,
    support cables to the bed pillars, handle on the (now lower) panel face."""
    s = g.s
    y0, zb, zt = g.bed_rear, s["bed_bottom_z"], s["rail_z"]
    ztop = zb + 0.24                     # flush with the bed floor
    th = 0.055
    length = zt - (zb + 0.06) - 0.01     # gate height when closed
    hw = tg_hw - 0.006
    p = Part("pv_tailgate", mats)
    box(p, (-hw, y0 - length, ztop - th), (hw, y0 + 0.002, ztop - 0.004), "paint", bev=0.012, seg=2)
    box(p, (-hw + 0.03, y0 - length + 0.03, ztop - 0.006), (hw - 0.03, y0 - 0.01, ztop), "bed_liner")
    box(p, (-0.13, y0 - length + 0.07, ztop - th - 0.012), (0.13, y0 - length + 0.115, ztop - th + 0.004),
        "trim", bev=0.006, seg=2)        # handle, now on the underside near the free edge
    for sgn in (-1, 1):                  # hinge barrels + support cables
        cylinder_x(p, y0 - 0.005, ztop - th / 2, 0.016, *sorted((sgn * (hw - 0.10), sgn * (hw - 0.02))),
                   "frame", seg=10)
        a = Vector((sgn * (hw - 0.01), y0 - length + 0.06, ztop - 0.01))
        b = Vector((sgn * (hw + 0.035), y0 + 0.03, zt - 0.10))
        ax = (b - a).normalized()
        side = ax.cross(Vector((0, 0, 1))).normalized()
        up = side.cross(ax).normalized()
        oriented_box(p, (a + b) / 2, (ax, side, up), ((b - a).length, 0.007, 0.007), "steel")
    return p.finish(col, smooth=40, weighted=True)


def plan_ring(hw, yb, yf, rb, rf, seg=4):
    """Rounded plan rectangle (x, y): rear corners radius rb, front corners rf; CCW from +X rear."""
    pts = []
    corners = [((hw - rb, yb + rb), -90, rb), ((hw - rf, yf - rf), 0, rf),
               ((-hw + rf, yf - rf), 90, rf), ((-hw + rb, yb + rb), 180, rb)]
    for (cx, cy), a0, r in corners:
        for i in range(seg + 1):
            a = math.radians(a0 + 90 * i / seg)
            pts.append((cx + r * math.cos(a), cy + r * math.sin(a)))
    return pts


class Greenhouse:
    """Planar-sided cab upper: x half width, front (windshield) and back y vary linearly with z."""

    def __init__(self, g):
        s = g.s
        self.z0, self.z1 = s["belt_z"], s["roof_z"] - 0.05
        self.hw0, self.hw1 = 0.955, 0.80
        self.yf0, self.yf1 = s["cowl_y"], s["cowl_y"] - s["windshield_rake"]
        self.yb0, self.yb1 = s["cab_back_y"] + 0.02, s["cab_back_y"] + 0.08
        self.rf0, self.rf1 = 0.10, 0.12
        self.rb0, self.rb1 = 0.05, 0.08
        self.roof = s["roof_z"]
        self.bp = s["b_pillar_y"]

    def t(self, z):
        return (z - self.z0) / (self.z1 - self.z0)

    def hw(self, z):
        return self.hw0 + (self.hw1 - self.hw0) * self.t(z)

    def yf(self, z):
        return self.yf0 + (self.yf1 - self.yf0) * self.t(z)

    def yb(self, z):
        return self.yb0 + (self.yb1 - self.yb0) * self.t(z)

    def rf(self, z):
        return self.rf0 + (self.rf1 - self.rf0) * self.t(z)

    def rb(self, z):
        return self.rb0 + (self.rb1 - self.rb0) * self.t(z)

    def ring(self, z):
        return [(x, y, z) for x, y in plan_ring(self.hw(z), self.yb(z), self.yf(z), self.rb(z), self.rf(z))]

    def side_n(self, sgn):
        return Vector((sgn * (self.z1 - self.z0), 0.0, self.hw0 - self.hw1)).normalized()

    def front_n(self):
        return Vector((0.0, self.z1 - self.z0, self.yf0 - self.yf1)).normalized()

    def back_n(self):
        return Vector((0.0, -(self.z1 - self.z0), self.yb1 - self.yb0)).normalized()

    def side_pt(self, sgn, y, z, off):
        return Vector((sgn * self.hw(z), y, z)) + self.side_n(sgn) * off

    def front_pt(self, x, z, off):
        return Vector((x, self.yf(z), z)) + self.front_n() * off

    def back_pt(self, x, z, off):
        return Vector((x, self.yb(z), z)) + self.back_n() * off

    def windows(self):
        """[(kind, sgn, outline 2D, glass_key)]: side outlines in (y, z), front/back in (x, z)."""
        out = []
        za, zt = self.z0 + 0.045, self.z1 - 0.035
        for sgn in (-1, 1):
            fe = lambda z: self.yf(z) - self.rf(z) - 0.06  # noqa: E731  A-pillar follows the rake
            rb_ = lambda z: self.yb(z) + self.rb(z) + (0.20 if self.bp else 0.12)  # noqa: E731
            if self.bp is None:          # regular cab: one door window
                one = [(rb_(za), za), (fe(za), za), (fe(zt), zt), (rb_(zt), zt)]
                out.append(("side", sgn, rounded_poly(one, 0.035, 3), "glass_light"))
                continue
            front = [(self.bp + 0.045, za), (fe(za), za), (fe(zt), zt), (self.bp + 0.045, zt)]
            out.append(("side", sgn, rounded_poly(front, 0.035, 3), "glass_light"))
            rear = [(rb_(za), za), (self.bp - 0.045, za), (self.bp - 0.045, zt), (rb_(zt), zt)]
            out.append(("side", sgn, rounded_poly(rear, 0.035, 3), "glass"))
        wz0, wz1 = self.z0 + 0.04, self.z1 - 0.025
        hw = lambda z: self.hw(z) - self.rf(z) - 0.03  # noqa: E731
        ws = [(-hw(wz0), wz0), (hw(wz0), wz0), (hw(wz1), wz1), (-hw(wz1), wz1)]
        out.append(("front", 0, rounded_poly(ws, 0.06, 4), "glass_light"))
        rz0, rz1 = self.z0 + 0.07, self.z1 - 0.06
        hb = lambda z: self.hw(z) - self.rb(z) - 0.12  # noqa: E731
        rw = [(-hb(rz0), rz0), (hb(rz0), rz0), (hb(rz1), rz1), (-hb(rz1), rz1)]
        out.append(("back", 0, rounded_poly(rw, 0.05, 3), "glass"))
        return out

    def map(self, kind, sgn, pts, off):
        if kind == "side":
            return [self.side_pt(sgn, y, z, off) for y, z in pts]
        if kind == "front":
            return [self.front_pt(x, z, off) for x, z in pts]
        return [self.back_pt(x, z, off) for x, z in pts]


def build_greenhouse(g, mats, col):
    gh = Greenhouse(g)
    p = Part("pv_greenhouse", mats)
    z0 = gh.z0 - 0.03
    levels = [z0, gh.z1]
    rings = [gh.ring(z) for z in levels]
    # rounded roof edge: shrink + rise over a few rings, then a crowned cap
    for k, (dz, dw) in enumerate(((0.024, 0.012), (0.040, 0.034), (0.048, 0.07))):
        hw, yb, yf = gh.hw1 - dw, gh.yb1 + dw * 1.2, gh.yf1 - dw * 1.6
        rings.append([(x, y, gh.z1 + dz) for x, y in plan_ring(hw, yb, yf, gh.rb1 + dw, gh.rf1 + dw)])
    vr, faces = loft(p, rings, "paint", cap_start=False, cap_end=True)
    bm = p.bm
    bmesh.ops.solidify(bm, geom=bm.faces[:], thickness=0.03)
    centre = Vector((0.0, (gh.yb0 + gh.yf0) / 2, gh.z0 + 0.25))
    ii = p.idx("interior")
    for f in bm.faces:
        if f.normal.dot(centre - f.calc_center_median()) > 0:
            f.material_index = ii
    ob = p.finish(col, smooth=40)
    # window openings (through), black gasket walls
    cut = bmesh.new()
    for kind, sgn, pts, _key in gh.windows():
        faces = build_prism(cut, gh.map(kind, sgn, pts, 0.08), gh.map(kind, sgn, pts, -0.12), 0)
        bmesh.ops.recalc_face_normals(cut, faces=faces)
    cutter = bm_object("pv_gh_cut", cut, [mats["trim"]], col)
    boolean_apply(ob, cutter)
    finish_hard_surface(ob, 40)
    # glass panes
    objs = [ob]
    panes = Part("pv_cab_glass", mats)
    for kind, sgn, pts, key in gh.windows():
        ring = gh.map(kind, sgn, pts, -0.006)
        f = panes.bm.faces.new([panes.bm.verts.new(v) for v in ring])
        f.normal_update()
        outward = gh.side_n(sgn) if kind == "side" else (gh.front_n() if kind == "front" else gh.back_n())
        if f.normal.dot(outward) < 0:
            f.normal_flip()
        panes.set_mat([f], key)
    objs.append(panes.finish(col, smooth=0))
    # trim: gloss-black B-pillar appliques, belt mouldings
    t = Part("pv_cab_trim", mats)
    for sgn in (-1, 1):
        n = gh.side_n(sgn)
        up = n.cross(Vector((0, 1, 0))).normalized()
        if up.z < 0:
            up = -up
        zc = (gh.z0 + gh.z1) / 2
        if gh.bp is not None:
            c = gh.side_pt(sgn, gh.bp, zc - 0.005, 0.004)
            oriented_box(t, c, (Vector((0, 1, 0)), up, n), (0.105, gh.z1 - gh.z0 - 0.05, 0.008), "trim_gloss",
                         bev=0.003)
        # belt moulding along the bottom of the side glass
        zb = gh.z0 + 0.012
        y0, y1 = gh.yb(zb) + 0.15, gh.yf(zb) - 0.10
        c = gh.side_pt(sgn, (y0 + y1) / 2, zb, 0.006)
        oriented_box(t, c, (Vector((0, 1, 0)), up, n), (y1 - y0, 0.022, 0.014), "trim", bev=0.004)
    # cowl panel + parked wipers along the windshield base
    zc = gh.z0 + 0.006
    box(t, (-gh.hw0 + 0.12, gh.yf(zc) + 0.005, gh.z0 - 0.012), (gh.hw0 - 0.12, gh.yf0 + 0.13, gh.z0 + 0.004),
        "trim", bev=0.006)
    fn = gh.front_n()
    for xc in (-0.36, 0.30):
        c = gh.front_pt(xc, gh.z0 + 0.05, 0.012)
        up = Vector((1, 0, 0)).cross(fn).normalized()
        oriented_box(t, c, (Vector((1, 0, 0)), up, fn), (0.62, 0.016, 0.012), "trim", bev=0.004)
    objs.append(t.finish(col, smooth=40))
    objs.append(build_interior(g, gh, mats, col))
    return objs, gh


def build_interior(g, gh, mats, col):
    """Low-detail cabin seen through the glass: dash, seats + headrests, wheel, mirror."""
    p = Part("pv_interior", mats)
    belt = gh.z0
    yd = gh.yf0 - 0.10
    # dash: profile follows the windshield so nothing pokes through the glass
    wf = lambda z: gh.yf(z) - 0.05  # noqa: E731
    prof = [(gh.yf0 - 0.65, belt - 0.06), (wf(belt - 0.06) + 0.05, belt - 0.06), (wf(belt + 0.10), belt + 0.10),
            (wf(belt + 0.13) - 0.10, belt + 0.15), (gh.yf0 - 0.58, belt + 0.15)]
    prism_x(p, prof, -0.88, 0.88, "interior")
    rows = (gh.yf0 - 1.15, gh.yf0 - 1.90) if gh.bp is not None else (gh.yf0 - 1.15,)
    for sy in rows:                                      # front (+ rear) rows
        front_row = sy == rows[0]
        for sx in ((-0.42, 0.42) if front_row else (-0.45, 0.0, 0.45)):
            w = 0.48 if front_row else 0.42
            box(p, (sx - w / 2, sy - 0.10, belt - 0.25), (sx + w / 2, sy + 0.06, belt + 0.12), "fabric",
                bev=0.05, seg=3)
            box(p, (sx - 0.13, sy - 0.08, belt + 0.16), (sx + 0.13, sy + 0.04, belt + 0.31), "fabric",
                bev=0.04, seg=3)
            box(p, (sx - 0.012, sy - 0.03, belt + 0.11), (sx + 0.012, sy, belt + 0.17), "chrome")
    # steering wheel (left-hand drive), tilted ring
    ring = revolve_x(p, 0, 0, [(-0.018, 0.17), (0.018, 0.17), (0.018, 0.195), (-0.018, 0.195)], "trim",
                     seg=28)
    vs = list({v for f in ring for v in f.verts})
    for v in vs:
        co = v.co.copy()
        # ring lies in the YZ plane around X; rotate so it faces the driver (axis ~ -Y, tilted)
        x, y, z = co
        a = math.radians(62)
        v.co = Vector((y, -x * math.cos(a) - z * math.sin(a), -x * math.sin(a) + z * math.cos(a)))
        v.co += Vector((-0.42, yd - 0.50, belt + 0.12))
    # rear-view mirror
    box(p, (-0.13, gh.yf(gh.z1) - 0.10, gh.z1 - 0.10), (0.13, gh.yf(gh.z1) - 0.06, gh.z1 - 0.04), "trim",
        bev=0.012)
    return p.finish(col, smooth=40)


# ------------------------------------------------------------------ front / rear / side details

def build_front(g, mats, col):
    """Tall boxy front: framed mesh grille, signature bar linking the headlamps, LED C-signature
    headlamps, wrap-around bumper with intake and fog lamps, valance, skid plate. No emblem."""
    s, W = g.s, g.W
    yf, belt = s["front_y"], s["belt_z"]
    p = Part("pv_front", mats)
    zt = belt - 0.16                      # top of grille / lamps, just under the hood edge
    gx, gz0 = 0.56, 0.80
    outline = rounded_rect(-gx, gx, gz0, zt, 0.04, 3)
    inner = rounded_rect(-gx + 0.045, gx - 0.045, gz0 + 0.04, zt - 0.04, 0.025, 3)
    annulus_prism(p.bm, [(u, yf + 0.045, v) for u, v in outline], [(u, yf - 0.05, v) for u, v in outline],
                  [(u, yf + 0.045, v) for u, v in inner], [(u, yf - 0.05, v) for u, v in inner],
                  p.idx("alloy_dark"))
    bevel(p.bm, [e for e in p.bm.edges if all(v.co.y > yf + 0.04 for v in e.verts)], 0.012, 2)
    gr = [(u, yf + 0.005, v) for u, v in inner]
    f = p.bm.faces.new([p.bm.verts.new(v) for v in gr])
    f.material_index = p.idx("grille")
    f.normal_update()
    if f.normal.y < 0:
        f.normal_flip()
    # signature bar across the grille, linking the lamps
    box(p, (-gx + 0.02, yf - 0.01, 1.13), (gx - 0.02, yf + 0.065, 1.185), "alloy", bev=0.016, seg=3)
    for sgn in (-1, 1):
        x0, x1 = sorted((sgn * (gx + 0.008), sgn * (W - 0.03)))
        hz0, hz1 = 1.075, zt
        box(p, (x0, yf - 0.06, hz0), (x1, yf + 0.035, hz1), "trim_gloss", bev=0.02, seg=3)
        # wrap-around: the lamp continues onto the fender side
        xs_l = surface_x(W, s["rocker_z"], belt, (hz0 + hz1) / 2, **g.cab_kw)
        a, b = sorted((sgn * (xs_l - 0.05), sgn * (xs_l + 0.004)))
        box(p, (a, yf - 0.13, hz0 + 0.05), (b, yf + 0.0, hz1 - 0.008), "lamp_clear", bev=0.012, seg=2)
        a, b = sorted((sgn * (xs_l - 0.01), sgn * (xs_l + 0.007)))
        box(p, (a, yf - 0.14, hz1 - 0.035), (b, yf - 0.01, hz1 - 0.022), "led_white")
        box(p, (x0 + 0.012, yf + 0.03, hz0 + 0.012), (x1 - 0.012, yf + 0.037, hz1 - 0.012), "lamp_clear",
            bev=0.006)
        cz = (hz0 + hz1) / 2 - 0.01
        cylinder_y(p, sgn * (gx + 0.115), cz, 0.046, yf + 0.03, yf + 0.045, "reflector", seg=24)
        cylinder_y(p, sgn * (gx + 0.115), cz, 0.032, yf + 0.04, yf + 0.052, "trim_gloss", seg=24)
        a, b = sorted((sgn * (gx + 0.19), sgn * (W - 0.07)))
        box(p, (a, yf + 0.033, cz - 0.04), (b, yf + 0.042, cz + 0.035), "reflector", bev=0.008)
        xo, xi = sgn * (W - 0.045), sgn * (gx + 0.03)
        a, b = sorted((xi, xo))
        box(p, (a, yf + 0.036, hz1 - 0.03), (b, yf + 0.046, hz1 - 0.018), "led_white")       # top
        a2, b2 = sorted((xo - sgn * 0.013, xo))
        box(p, (a2, yf + 0.036, hz0 + 0.02), (b2, yf + 0.046, hz1 - 0.018), "led_white")     # outer
        a3, b3 = sorted((sgn * (gx + 0.2), xo))
        box(p, (a3, yf + 0.036, hz0 + 0.018), (b3, yf + 0.046, hz0 + 0.03), "led_white")     # bottom
        xm = sgn * (surface_x(W, s["rocker_z"], belt, 1.08, **g.cab_kw) + 0.002)
        a, b = sorted((xm - sgn * 0.01, xm))
        box(p, (a, yf - 0.30, 1.07), (b, yf - 0.17, 1.10), "lamp_amber", bev=0.004)
    # bumper: wrap-around face, centre intake, fog lamp pockets
    prof = [(yf + 0.10, 0.49), (yf + 0.125, 0.58), (yf + 0.12, 0.72), (yf + 0.085, 0.795),
            (yf - 0.05, 0.795), (yf - 0.05, 0.49)]
    vs = prism_x(p, prof, -(W - 0.02), W - 0.02, "alloy")
    for v in vs:
        ax = abs(v.co.x)
        if ax > W - 0.30:
            v.co.y -= ((ax - (W - 0.30)) / 0.28) ** 2 * 0.14
    bevel(p.bm, list({e for v in vs for e in v.link_edges}), 0.02, 3)
    box(p, (-0.40, yf + 0.06, 0.60), (0.40, yf + 0.13, 0.675), "trim", bev=0.012)
    box(p, (-0.38, yf + 0.07, 0.61), (0.38, yf + 0.133, 0.665), "grille")
    for sgn in (-1, 1):
        a, b = sorted((sgn * 0.64, sgn * 0.78))
        box(p, (a, yf + 0.05, 0.585), (b, yf + 0.128, 0.67), "trim", bev=0.02, seg=2)
        cylinder_y(p, sgn * 0.71, 0.627, 0.032, yf + 0.10, yf + 0.13, "reflector", seg=20)
        cylinder_y(p, sgn * 0.71, 0.627, 0.024, yf + 0.12, yf + 0.134, "lamp_clear", seg=20)
        a, b = sorted((sgn * 0.52, sgn * 0.58))
        box(p, (a, yf + 0.06, 0.34), (b, yf + 0.16, 0.41), "steel", bev=0.008)            # tow hooks
    vprof = [(yf + 0.10, 0.49), (yf + 0.05, 0.34), (yf - 0.20, 0.31), (yf - 0.20, 0.49)]
    vv = prism_x(p, vprof, -(W - 0.12), W - 0.12, "trim")
    bevel(p.bm, list({e for v in vv for e in v.link_edges}), 0.015, 2)
    box(p, (-0.50, yf - 0.40, 0.29), (0.50, yf + 0.06, 0.32), "steel", bev=0.01)        # skid plate
    return p.finish(col, smooth=40, weighted=True)


def _prism_x_bm(part, profile_yz, x0, x1, key):
    return prism_x(part, profile_yz, x0, x1, key)


def build_sides(g, mats, col, gh):
    """Mirrors, door handles, step bars, wheel-arch lips/flares, rocker cladding."""
    s, W = g.s, g.W
    belt, zb = s["belt_z"], s["rocker_z"]
    p = Part("pv_sides", mats)
    X, Y, Z = Vector((1, 0, 0)), Vector((0, 1, 0)), Vector((0, 0, 1))
    xs_h = surface_x(W, zb, belt, 1.30, **g.cab_kw)
    for sgn in (-1, 1):
        # door handles (body colour) with a black recess behind
        handles = (s["b_pillar_y"] + 0.22, s["cab_back_y"] + 0.29) if s["b_pillar_y"] else (s["cab_back_y"] + 0.30,)
        for yc in handles:
            box(p, (min(sgn * xs_h, sgn * (xs_h - 0.004)) - 0.0, yc - 0.10, 1.285),
                (max(sgn * xs_h, sgn * (xs_h - 0.004)), yc + 0.10, 1.325), "trim", bev=0.006)
            oriented_box(p, Vector((sgn * (xs_h + 0.014), yc, 1.305)), (X, Y, Z), (0.03, 0.18, 0.034), "paint",
                         bev=0.012, seg=3)
        # mirror: sail at the A-pillar foot, arm, housing (black cap), glass facing back, turn signal
        my = gh.yf0 - 0.20
        xb = sgn * (gh.hw0 + 0.0)
        a, b = sorted((xb, xb + sgn * 0.07))
        box(p, (a, my - 0.10, belt + 0.005), (b, my + 0.08, belt + 0.12), "trim", bev=0.015)
        a, b = sorted((xb + sgn * 0.05, xb + sgn * 0.17))
        box(p, (a, my - 0.04, belt + 0.06), (b, my + 0.03, belt + 0.10), "trim", bev=0.012)
        hc = Vector((sgn * (gh.hw0 + 0.26), my - 0.02, belt + 0.18))
        before = set(p.bm.verts)
        oriented_box(p, hc, (X, Y, Z), (0.22, 0.13, 0.27), "trim", bev=0.05, seg=4)
        for v in set(p.bm.verts) - before:
            k = (v.co.z - hc.z) / 0.135
            v.co.x += sgn * 0.025 * k                     # wider at the top (towing-style)
            if v.co.y > hc.y:
                v.co.y += 0.03 * max(0.0, 1 - abs(v.co.x - hc.x) / 0.11)   # rounded nose
        oriented_box(p, hc + Vector((0, -0.066, 0)), (X, Y, Z), (0.19, 0.006, 0.235), "chrome", bev=0.02, seg=3)
        oriented_box(p, hc + Vector((sgn * 0.01, 0.0, -0.13)), (X, Y, Z), (0.16, 0.08, 0.012), "lamp_amber",
                     bev=0.004)
        # tubular-look running board (flat step with rounded nose)
        y0 = (g.y_ra + g.arch_r + 0.10) if g.pickup else (s["cab_back_y"] + 0.02)
        y1 = g.y_fa - g.arch_r - 0.08
        xo = sgn * (W + 0.03)
        xi = sgn * (W - 0.20)
        prof = rounded_poly(sorted_ccw([(xi, 0.40), (xo, 0.40), (xo, 0.455), (xi, 0.455)]), 0.02, 3)
        prism_y(p, prof, y0, y1, "trim")
        for yy in (y0 + 0.25, (y0 + y1) / 2, y1 - 0.25):
            a, b = sorted((sgn * (W - 0.32), sgn * (W - 0.15)))
            box(p, (a, yy - 0.03, 0.43), (b, yy + 0.03, zb + 0.03), "frame")
        # rocker cladding (black, thin) under the doors
        xr = surface_x(W, zb, belt, zb + 0.08, **g.cab_kw)
        a, b = sorted((sgn * (xr - 0.04), sgn * (xr + 0.006)))
        box(p, (a, s["cab_back_y"] + 0.02, zb - 0.01), (b, gh.yf0 - 0.10, zb + 0.07), "trim", bev=0.008)
        # arch lips (body colour) + liners
        axles = [(g.y_fa, s["rocker_z"], g.cab_kw, s["belt_z"])]
        if g.pickup:
            axles.append((g.y_ra, s["bed_bottom_z"], g.bed_kw, s["rail_z"]))
        for ya, zbb, kw, ztop in axles:
            amin = math.degrees(math.asin(max(-1.0, min(1.0, (zbb - g.arch_z) / g.arch_r)))) + 1.5
            xsurf = surface_x(W, zbb, ztop, g.arch_z + g.arch_r * 0.7, **kw)
            sec = [(sgn * (xsurf - 0.05), -0.002), (sgn * (xsurf + 0.012), -0.002), (sgn * (xsurf + 0.024), 0.012),
                   (sgn * (xsurf + 0.024), 0.035), (sgn * (xsurf + 0.008), 0.055), (sgn * (xsurf - 0.05), 0.055)]
            if sgn < 0:
                sec = sec[::-1]
            sweep_arc_x(p, ya, g.arch_z, g.arch_r, amin, 180 - amin, sec, "paint", seg=36)
            arc_band_x(p, ya, g.arch_z, g.arch_r - 0.006, g.arch_r + 0.002, amin - 1, 181 - amin,
                       *sorted((sgn * 0.62, sgn * (xsurf - 0.03))), "underbody", seg=36)
    return p.finish(col, smooth=40, weighted=True)


def sorted_ccw(pts):
    c = Vector((sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts)))
    return sorted(pts, key=lambda p: math.atan2(p[1] - c.y, p[0] - c.x))


def build_rear(g, mats, col):
    """Pickup rear: tail lamps, tailgate handle/camera, rear bumper with step pad, blank plate."""
    s, W = g.s, g.W
    y0, zb, zt = g.bed_rear, s["bed_bottom_z"], s["rail_z"]
    p = Part("pv_rear", mats)
    for sgn in (-1, 1):
        xo = surface_x(W, zb, zt, 1.2, **g.bed_kw)
        a, b = sorted((sgn * (xo - 0.155), sgn * (xo + 0.004)))
        box(p, (a, y0 - 0.012, 0.96), (b, y0 + 0.07, 1.41), "lamp_red_lens", bev=0.016, seg=3)
        # C-shaped LED signature + reverse lamp
        ai, bi = sorted((sgn * (xo - 0.13), sgn * (xo - 0.02)))
        box(p, (ai, y0 - 0.016, 1.355), (bi, y0 - 0.008, 1.375), "lamp_red")
        box(p, (ai, y0 - 0.016, 0.995), (bi, y0 - 0.008, 1.015), "lamp_red")
        ac, bc = sorted((sgn * (xo - 0.13), sgn * (xo - 0.11)))
        box(p, (ac, y0 - 0.016, 1.0), (bc, y0 - 0.008, 1.37), "lamp_red")
        ar, br = sorted((sgn * (xo - 0.10), sgn * (xo - 0.035)))
        box(p, (ar, y0 - 0.017, 1.15), (br, y0 - 0.008, 1.22), "lamp_clear", bev=0.004)
    if s["tailgate"] == "closed":
        box(p, (-0.13, y0 - 0.02, zt - 0.115), (0.13, y0 + 0.01, zt - 0.07), "trim", bev=0.01, seg=2)  # handle
        box(p, (-0.025, y0 - 0.024, zt - 0.10), (0.025, y0 - 0.015, zt - 0.08), "trim_gloss")            # camera
    # bumper
    yb0, yb1 = y0 - 0.20, y0 + 0.03
    prof = [(yb0, 0.47), (yb0 - 0.015, 0.55), (yb0, 0.70), (yb1, 0.72), (yb1, 0.47)]
    vs = _prism_x_bm(p, prof, -(W - 0.015), W - 0.015, "chrome")
    for v in vs:
        ax = abs(v.co.x)
        if ax > W - 0.22:
            v.co.y += ((ax - (W - 0.22)) / 0.2) ** 2 * 0.07
    bevel(p.bm, list({e for v in vs for e in v.link_edges}), 0.015, 3)
    box(p, (-0.55, yb0 - 0.01, 0.695), (0.55, yb1 - 0.02, 0.728), "trim", bev=0.006)         # step pad
    for sgn in (-1, 1):
        a, b = sorted((sgn * (W - 0.20), sgn * (W - 0.05)))
        box(p, (a, yb0 + 0.01, 0.699), (b, yb1 - 0.03, 0.726), "trim", bev=0.005)
    box(p, (-0.175, yb0 - 0.03, 0.52), (0.175, yb0 + 0.01, 0.66), "trim", bev=0.008)          # plate pocket
    box(p, (-0.155, yb0 - 0.032, 0.535), (0.155, yb0 - 0.02, 0.645), "plate", bev=0.006)
    box(p, (-(W - 0.06), yb0 + 0.02, 0.42), (W - 0.06, yb1, 0.48), "trim", bev=0.015)        # valance
    box(p, (-0.045, yb0 - 0.13, 0.385), (0.045, yb0 + 0.25, 0.455), "frame", bev=0.006)       # hitch
    cylinder_x(p, yb0 - 0.105, 0.42, 0.011, -0.07, 0.07, "steel", seg=12)
    return p.finish(col, smooth=40, weighted=True)


# ------------------------------------------------------------------ chassis

def build_chassis(g, mats, col):
    s = g.s
    p = Part("pv_chassis", mats)
    ft = s["frame_top_z"]
    fh = 0.22 if not g.pickup else 0.20
    fw = s["frame_hw"]
    y_end = (g.bed_rear - 0.10) if g.pickup else -s["frame_length_behind_cab"]
    y_front = s["front_y"] - 0.30
    for sgn in (-1, 1):                         # C-channel rails (web + flanges, opening inward)
        xo, xi = sgn * fw, sgn * (fw - 0.008)
        box(p, (min(xo, xi), y_end, ft - fh), (max(xo, xi), y_front, ft), "frame")
        for zf in (ft - 0.008, ft - fh):
            a, b = sorted((sgn * fw, sgn * (fw - 0.07)))
            box(p, (a, y_end, zf), (b, y_front, zf + 0.008), "frame")
    n_cross = 5 if not g.pickup else 3
    for k in range(n_cross):
        yc = y_end + 0.03 + k * (min(0.0, y_front) - y_end - 0.06) / max(n_cross - 1, 1)
        box(p, (-fw + 0.01, yc - 0.04, ft - fh + 0.04), (fw - 0.01, yc + 0.04, ft - 0.04), "frame")
    box(p, (-fw - 0.01, y_end - 0.01, ft - fh), (fw + 0.01, y_end + 0.06, ft), "frame")      # end crossmember
    # rear axle: housing, diff, leaf springs, shocks
    ra = g.y_ra
    dual = s["dual_rear_wheels"] and not g.pickup
    hw_axle = g.track_hw + (0.20 if dual else 0.0)
    cylinder_x(p, ra, g.R, 0.055, -hw_axle + 0.12, hw_axle - 0.12, "frame", seg=20)
    sph = bmesh.ops.create_uvsphere(p.bm, u_segments=20, v_segments=12, radius=0.15)
    for v in sph["verts"]:
        v.co = Vector((v.co.x * 0.9 + 0.08, v.co.y + ra, v.co.z * 0.85 + g.R))
    p.set_mat(list({f for v in sph["verts"] for f in v.link_faces}), "frame")
    cylinder_y(p, 0.08, g.R, 0.045, ra, ra + 0.75, "frame", seg=16)             # driveshaft stub
    for sgn in (-1, 1):
        xs = sgn * (fw - 0.035)
        for k, t in enumerate((0.022, 0.018, 0.016)):
            zc = ft - fh - 0.045 - k * 0.022
            box(p, (xs - 0.035, ra - 0.70 + k * 0.12, zc - t / 2), (xs + 0.035, ra + 0.70 - k * 0.12, zc + t / 2),
                "frame")
        box(p, (xs - 0.04, ra - 0.05, g.R - 0.06), (xs + 0.04, ra + 0.05, ft - fh - 0.04), "frame")
        cylinder_x(p, ra + 0.18, (g.R + ft) / 2 - 0.05, 0.025, *sorted((xs - sgn * 0.09, xs - sgn * 0.05)),
                   "steel", seg=12)
    # front suspension/axle (dark), fuel tank, exhaust
    cylinder_x(p, g.y_fa, g.R, 0.05, -g.track_hw + 0.12, g.track_hw - 0.12, "frame", seg=16)
    if g.pickup:
        box(p, (0.10, -0.10, ft - fh - 0.18), (fw - 0.08, 0.95, ft - fh + 0.04), "underbody", bev=0.03)
        cylinder_z(p, 0.0, g.bed_rear + 0.48, g.R - 0.03, 0.36, 0.60, "tire", seg=32)  # spare, flat
    else:
        box(p, (-fw + 0.08, -1.00, ft - fh - 0.16), (fw - 0.08, -0.15, ft - fh + 0.02), "underbody",
            bev=0.03)
    ex_end = (g.bed_rear - 0.05) if g.pickup else (y_end + 0.6)
    cylinder_y(p, fw + 0.05, 0.40, 0.035, ex_end, 2.2, "steel", seg=14)
    cylinder_y(p, fw + 0.05, 0.40, 0.042, ex_end - 0.01, ex_end + 0.12, "chrome", seg=14)
    # under-cab floor pan (blocks sky leaking under the body)
    box(p, (-0.95, s["cab_back_y"] - 0.02, s["rocker_z"] + 0.02), (0.95, s["front_y"] - 0.35, s["rocker_z"] + 0.04),
        "underbody")
    box(p, (-0.70, g.y_fa - 0.45, 0.36), (0.70, s["front_y"] - 0.15, 0.62), "underbody", bev=0.03)
    return p.finish(col, smooth=40)


def build_cab_back_extras(g, mats, col):
    """cab_chassis only: cab back panel trim so the exposed back reads as a real cab."""
    s = g.s
    p = Part("pv_cab_back", mats)
    yb = s["cab_back_y"]
    box(p, (-0.60, yb - 0.01, 0.62), (0.60, yb + 0.005, 0.70), "trim", bev=0.005)
    return p.finish(col, smooth=40)


# ------------------------------------------------------------------ wheels

def build_wheel(g, mats, col, name, y, xc, side, width=None, finish="alloy_dark", inner=False):
    """20 in split-spoke alloy + all-terrain tyre (tread blocks, shoulder lugs, sidewall ribs),
    brake rotor/caliper behind the spokes. side = +1 right / -1 left (face looks outward)."""
    p = Part(name, mats)
    R, rr = g.R, g.rim_r
    w = width or g.s["tire_width"]
    xo, xi = xc + side * w / 2, xc - side * w / 2
    x0, x1 = sorted((xi, xo))
    # --- tyre carcass (closed revolve): bead -> bulged sidewall -> shoulder -> tread base
    tb = R - 0.013
    prof = [(x0 + 0.012, rr + 0.012), (x0 + 0.004, rr + 0.05), (x0 - 0.004, rr + 0.10), (x0 - 0.002, tb - 0.05),
            (x0 + 0.010, tb - 0.012), (x0 + 0.03, tb), (x1 - 0.03, tb), (x1 - 0.010, tb - 0.012),
            (x1 + 0.002, tb - 0.05), (x1 + 0.004, rr + 0.10), (x1 - 0.004, rr + 0.05), (x1 - 0.012, rr + 0.012)]
    revolve_x(p, y, R, prof, "tire", seg=72)
    # --- tread blocks: 2 shoulder + 2 staggered centre per pitch
    n = 46
    rad_axis = lambda a: Vector((0, math.cos(a), math.sin(a)))  # noqa: E731
    tan_axis = lambda a: Vector((0, -math.sin(a), math.cos(a)))  # noqa: E731
    Xv = Vector((1, 0, 0))
    for i in range(n):
        a = 2 * math.pi * i / n
        a2 = a + math.pi / n
        for (xa, xb, aa, h) in (
                (x0 - 0.004, x0 + 0.075, a, 0.016), (x1 - 0.075, x1 + 0.004, a2, 0.016),
                (x0 + 0.085, xc - 0.008, a2, 0.014), (xc + 0.008, x1 - 0.085, a, 0.014)):
            c = Vector((((xa + xb) / 2), y, R)) + rad_axis(aa) * (tb + h / 2 - 0.004)
            oriented_box(p, c, (Xv, rad_axis(aa), tan_axis(aa)), (xb - xa, h + 0.008, 2 * math.pi * R / n * 0.62),
                         "tire", bev=0.003, seg=1)
        # shoulder lugs running down the outer sidewall
        for xs, sgn in ((x0, -1), (x1, 1)):
            if sgn != side and not inner:
                continue
            c = Vector((xs + sgn * 0.002, y, R)) + rad_axis(a) * (tb - 0.03)
            oriented_box(p, c, (Xv, rad_axis(a), tan_axis(a)), (0.012, 0.035, 2 * math.pi * R / n * 0.45),
                         "tire", bev=0.003, seg=1)
    # --- rim: barrel + outer lip (revolve, open) in the wheel finish
    face = xo - side * 0.03
    lip = [(face + side * 0.006, rr + 0.012), (face + side * 0.004, rr - 0.004), (face - side * 0.012, rr - 0.02),
           (face - side * 0.03, rr - 0.025), (xi + side * 0.03, rr - 0.025), (xi + side * 0.03, rr - 0.04)]
    revolve_x(p, y, R, lip, finish, seg=64, closed=False)
    # barrel interior (dark) so the gaps between spokes read as depth
    cylinder_x(p, y, R, rr - 0.03, *sorted((face - side * 0.16, face - side * 0.155)), "underbody", seg=48)
    # brake rotor + caliper
    cylinder_x(p, y, R, 0.175, *sorted((face - side * 0.11, face - side * 0.085)), "steel", seg=40)
    ca = math.radians(150 if side > 0 else 150)
    cc = Vector((face - side * 0.075, y, R)) + Vector((0, math.cos(ca), math.sin(ca))) * 0.155
    oriented_box(p, cc, (Xv, rad_axis(ca), tan_axis(ca)), (0.05, 0.07, 0.16), "trim_gloss", bev=0.01)
    # hub, centre cap (plain, no logo), lug nuts
    cylinder_x(p, y, R, 0.085, *sorted((face - side * 0.06, face - side * 0.025)), finish, seg=32, bev=0.01)
    cylinder_x(p, y, R, 0.042, *sorted((face - side * 0.03, face - side * 0.015)), "trim_gloss", seg=24,
               bev=0.006)
    for k in range(6):
        a = 2 * math.pi * k / 6 + math.pi / 6
        cy, cz = y + 0.066 * math.cos(a), R + 0.066 * math.sin(a)
        cylinder_x(p, cy, cz, 0.0105, *sorted((face - side * 0.04, face - side * 0.02)), "chrome", seg=6)
    # split spokes: concave (outer end at the lip plane, inner end recessed)
    ns = g.s["spokes"]
    r_in, r_out = 0.08, rr - 0.018
    for k in range(ns):
        base = 2 * math.pi * k / ns + math.pi / 2
        for d in (-1, 1):
            a = base + d * math.radians(7.5)
            ra_ = rad_axis(a)
            # spoke centre line from (r_in, recessed) to (r_out, face)
            p_in = Vector((face - side * 0.035, y, R)) + ra_ * r_in
            p_out = Vector((face - side * 0.004, y, R)) + rad_axis(base + d * math.radians(4.0)) * r_out
            mid = (p_in + p_out) / 2
            axis = (p_out - p_in).normalized()
            tang = axis.cross(Xv).normalized()
            nrm = tang.cross(axis).normalized()
            oriented_box(p, mid, (axis, tang, nrm), ((p_out - p_in).length + 0.01, 0.022, 0.03), finish,
                         bev=0.007, seg=2)
    ob = p.finish(col, smooth=40)
    return ob


# ------------------------------------------------------------------ assembly

def build_truck(spec, mats, collection=None):
    """Build the stand-in truck. spec: dict (see DEFAULTS / make_spec). mats: MaterialLibrary.

    Returns TruckInfo (variant frame). All truck objects are linked to `collection` (created as
    'preview_context' if None) and moved so the mount point is at the world origin.
    """
    if collection is None:
        collection = bpy.data.collections.new(COLLECTION)
        bpy.context.scene.collection.children.link(collection)
    src = (spec or {}).get("source", "procedural")
    if src == "hd_reference":
        return build_hd_chassis_reference(spec, mats, collection)
    if src != "procedural":
        raise ValueError(f"truck source must be procedural|hd_reference, got {src}")
    s = make_spec(spec)
    g = Geo(s)
    mats.ground_z = -(s["rail_z"] if g.pickup else s["frame_top_z"])   # world z of the road (dirt)
    mats.add("grille", _grille_material(mats))
    objs = [build_cab_body(g, mats, collection)]
    gh_objs, gh = build_greenhouse(g, mats, collection)
    objs += gh_objs
    objs += [build_front(g, mats, collection), build_sides(g, mats, collection, gh),
             build_chassis(g, mats, collection)]
    if g.pickup:
        objs += build_bed(g, mats, collection)
        objs.append(build_rear(g, mats, collection))
    else:
        objs.append(build_cab_back_extras(g, mats, collection))
    for sgn, sd in ((-1, "l"), (1, "r")):
        objs.append(build_wheel(g, mats, collection, f"pv_wheel_f{sd}", g.y_fa, sgn * g.track_hw, sgn,
                                finish=s["wheel_finish"]))
        if s["dual_rear_wheels"] and not g.pickup:
            w = 0.245
            for k, off in enumerate((-(w / 2 + 0.015), (w / 2 + 0.015))):
                xc = sgn * (g.track_hw + 0.20 + off)
                objs.append(build_wheel(g, mats, collection, f"pv_wheel_r{sd}{k}", g.y_ra, xc, sgn, width=w,
                                        finish=s["wheel_finish"], inner=(k == 0)))
        else:
            objs.append(build_wheel(g, mats, collection, f"pv_wheel_r{sd}", g.y_ra, sgn * g.track_hw, sgn,
                                    finish=s["wheel_finish"]))
    mount = Vector((0.0, 0.0, s["rail_z"] if g.pickup else s["frame_top_z"]))
    for ob in objs:
        ob.location -= mount
    info = TruckInfo(
        type=s["type"], mount_local=list(mount), ground_z=-mount.z, roof_z=s["roof_z"] - mount.z,
        cab_back_y=s["cab_back_y"], front_y=s["front_y"], front_axle_y=g.y_fa, rear_axle_y=g.y_ra,
        wheelbase=s["wheelbase"], body_hw=g.W, track=s["track"], tire_radius=g.R, spec=s,
    )
    if g.pickup:
        info.update(rail_z=0.0, bed_length=s["bed_length"], bed_inner_hw=g.W - 0.15,
                    rail_outer_hw=surface_x(g.W, s["bed_bottom_z"], s["rail_z"], s["rail_z"] - 0.03, **g.bed_kw),
                    tailgate_y=g.bed_rear, tailgate=s["tailgate"])
    else:
        dual = s["dual_rear_wheels"]
        info.update(frame_top_z=0.0, frame_hw=s["frame_hw"], frame_end_y=-s["frame_length_behind_cab"],
                    rear_track=(g.track_hw + (0.20 + 0.245 + 0.015 if dual else s["tire_width"] / 2)))
    info["objects"] = objs
    return info


def _grille_material(mats):
    """Dark gloss hex/mesh grille insert (procedural, no emblem)."""
    mat = bpy.data.materials.new("rv_grille")
    mat.use_nodes = True
    nt = mat.node_tree
    nodes, links = nt.nodes, nt.links
    b = nodes["Principled BSDF"]
    tc = nodes.new("ShaderNodeTexCoord")
    vor = nodes.new("ShaderNodeTexVoronoi")
    vor.feature = "DISTANCE_TO_EDGE"
    vor.inputs["Scale"].default_value = 28.0
    vor.inputs["Randomness"].default_value = 0.0
    links.new(tc.outputs["Object"], vor.inputs["Vector"])
    ramp = nodes.new("ShaderNodeValToRGB")
    ramp.color_ramp.elements[0].position = 0.06
    ramp.color_ramp.elements[0].color = (0.0, 0.0, 0.0, 1)
    ramp.color_ramp.elements[1].position = 0.09
    ramp.color_ramp.elements[1].color = (1, 1, 1, 1)
    links.new(vor.outputs["Distance"], ramp.inputs["Fac"])
    mix = nodes.new("ShaderNodeMixRGB")
    mix.inputs["Color1"].default_value = (0.12, 0.12, 0.13, 1)     # web (lit edge)
    mix.inputs["Color2"].default_value = (0.004, 0.004, 0.004, 1)  # holes
    links.new(ramp.outputs["Color"], mix.inputs["Fac"])
    links.new(mix.outputs["Color"], b.inputs["Base Color"])
    bump = nodes.new("ShaderNodeBump")
    bump.inputs["Strength"].default_value = 0.8
    bump.inputs["Distance"].default_value = 0.01
    links.new(ramp.outputs["Color"], bump.inputs["Height"])
    links.new(bump.outputs["Normal"], b.inputs["Normal"])
    b.inputs["Metallic"].default_value = 0.6
    b.inputs["Roughness"].default_value = 0.3
    return mat


# ------------------------------------------------------------------ HD chassis-cab reference (downloaded models)
#
# truck {"type": "cab_chassis", "source": "hd_reference"}: a 1999-2007-generation heavy-duty regular-cab
# pickup (CC BY 4.0, see README "Credits") cut behind the cab, debadged, plates removed, repainted with
# mats["paint"]; DRW wheel assemblies (front singles + rear duals) taken from a CC BY-SA 4.0 chassis-cab
# box truck derived from the same model and saved to a small .blend by scripts/extract_hd_wheels.py;
# procedural frame, rear axle and leaf springs. Both files live in tools/ (gitignored), never committed,
# exported or packaged. Object names below are those of the glTF import of the exact Sketchfab download.

def _import_reference(path, collection):
    from lib.common import PipelineError
    before = set(bpy.data.objects)
    res = bpy.ops.import_scene.gltf(filepath=str(path))
    if "FINISHED" not in res:
        raise PipelineError(f"glTF import failed for {path}: {res}")
    new = [o for o in bpy.data.objects if o not in before]
    meshes = []
    for ob in new:
        for c in list(ob.users_collection):
            c.objects.unlink(ob)
        if ob.type != "MESH":
            continue
        if ob.data.users > 1:
            ob.data = ob.data.copy()
        mw = ob.matrix_world.copy()
        ob.parent = None
        ob.data.transform(mw)
        ob.matrix_world.identity()
        collection.objects.link(ob)
        meshes.append(ob)
    for ob in new:
        if ob.type != "MESH":
            bpy.data.objects.remove(ob)
    if not meshes:
        raise PipelineError(f"{path}: no meshes imported")
    return meshes


def _verts_world(objs, pred=None):
    out = []
    for ob in objs:
        if pred is not None and not pred(ob):
            continue
        out += [v.co.copy() for v in ob.data.vertices]
    return out


def _ray(scene, dg, origin, direction, dist=20.0):
    hit, loc, nrm, idx, ob, _ = scene.ray_cast(dg, Vector(origin), Vector(direction).normalized(), distance=dist)
    return loc if hit else None


def _delete_faces(ob, pred):
    """Delete faces whose material index / centre match pred(face_material, centre)."""
    bm = bmesh.new()
    bm.from_mesh(ob.data)
    mats_ = [s.material for s in ob.material_slots]
    dead = [f for f in bm.faces
            if pred(mats_[f.material_index] if f.material_index < len(mats_) else None, f.calc_center_median())]
    if dead:
        bmesh.ops.delete(bm, geom=dead, context="FACES")
        bm.to_mesh(ob.data)
    bm.free()
    return len(dead)


def _cut_behind(ob, y_cut):
    """Bisect at y = y_cut, delete everything behind it and cap the cut openings."""
    bm = bmesh.new()
    bm.from_mesh(ob.data)
    geom = bm.verts[:] + bm.edges[:] + bm.faces[:]
    res = bmesh.ops.bisect_plane(bm, geom=geom, dist=1e-5, plane_co=(0, y_cut, 0), plane_no=(0, 1, 0),
                                 clear_outer=False, clear_inner=True)
    cut_edges = [e for e in res["geom_cut"] if isinstance(e, bmesh.types.BMEdge)]
    bm.edges.ensure_lookup_table()
    boundary = [e for e in cut_edges if e.is_valid and e.is_boundary]
    if boundary:
        filled = bmesh.ops.holes_fill(bm, edges=boundary, sides=0)
        for f in filled["faces"]:
            f.normal_update()
            if f.normal.y < 0:          # caps face rearward (they are seen from behind)
                f.normal_flip()
    n = len(bm.faces)
    bm.to_mesh(ob.data)
    bm.free()
    return n


def _rear_chassis(mats, collection, x0, y_cut, y_end, frame_top, fw, y_new, z_ax, hw_axle, name="pv_hd_chassis"):
    """Procedural frame behind a cut cab: C-channel rails + crossmembers from y_end to just under the
    cab, rear axle housing, diff, leaf springs, shocks, driveshaft, fuel tank and exhaust. Model-local coordinates (ground z = 0, +Y forward, rails centred on x0)."""
    p = Part(name, mats)
    fh = 0.22
    y_front = y_cut + 0.25                                   # rails run on under the cab (hidden)
    for sgn in (-1, 1):
        xo, xi = x0 + sgn * fw, x0 + sgn * (fw - 0.008)
        box(p, (min(xo, xi), y_end, frame_top - fh), (max(xo, xi), y_front, frame_top), "frame")
        for zf in (frame_top - 0.008, frame_top - fh):
            a, b = sorted((x0 + sgn * fw, x0 + sgn * (fw - 0.07)))
            box(p, (a, y_end, zf), (b, y_front, zf + 0.008), "frame")
    for kx in range(5):
        yc = y_end + 0.03 + kx * (y_cut - 0.10 - y_end - 0.06) / 4
        box(p, (x0 - fw + 0.01, yc - 0.04, frame_top - fh + 0.04), (x0 + fw - 0.01, yc + 0.04, frame_top - 0.04), "frame")
    box(p, (x0 - fw - 0.01, y_end - 0.01, frame_top - fh), (x0 + fw + 0.01, y_end + 0.06, frame_top), "frame")
    cylinder_x(p, y_new, z_ax, 0.055, x0 - hw_axle + 0.12, x0 + hw_axle - 0.12, "frame", seg=20)
    sph = bmesh.ops.create_uvsphere(p.bm, u_segments=20, v_segments=12, radius=0.15)
    for v in sph["verts"]:
        v.co = Vector((x0 + v.co.x * 0.9 + 0.08, v.co.y + y_new, v.co.z * 0.85 + z_ax))
    p.set_mat(list({f for v in sph["verts"] for f in v.link_faces}), "frame")
    cylinder_y(p, x0 + 0.08, z_ax + 0.02, 0.045, y_new, y_cut + 0.4, "frame", seg=16)          # driveshaft
    for sgn in (-1, 1):
        xs_ = x0 + sgn * (fw - 0.035)
        for kk, t in enumerate((0.022, 0.018, 0.016)):
            zc = frame_top - fh - 0.045 - kk * 0.022
            box(p, (xs_ - 0.035, y_new - 0.70 + kk * 0.12, zc - t / 2), (xs_ + 0.035, y_new + 0.70 - kk * 0.12, zc + t / 2),
                "frame")
        box(p, (xs_ - 0.04, y_new - 0.05, z_ax - 0.06), (xs_ + 0.04, y_new + 0.05, frame_top - fh - 0.04), "frame")
        cylinder_x(p, y_new + 0.18, (z_ax + frame_top) / 2 - 0.05, 0.025, *sorted((xs_ - sgn * 0.09, xs_ - sgn * 0.05)),
                   "steel", seg=12)
    # fuel tank between the rails behind the axle, exhaust along the right rail ending ahead of the duals
    box(p, (x0 - fw + 0.10, y_end + 0.35, frame_top - fh - 0.24), (x0 + fw - 0.10, y_new - 0.75, frame_top - fh + 0.02),
        "underbody", bev=0.04)
    xe = x0 + fw - 0.12
    cylinder_y(p, xe, frame_top - fh - 0.08, 0.04, y_new + 0.85, y_cut + 0.30, "steel", seg=14)
    cylinder_x(p, y_new + 0.85, frame_top - fh - 0.08, 0.04, xe - 0.02, x0 + fw + 0.10, "steel", seg=14)
    return p.finish(collection, smooth=40)


HD_CHASSIS_DIR = "tools/reference-hd-chassis"
HD_CHASSIS_DEFAULTS = {
    "model": HD_CHASSIS_DIR + "/hd_regular_cab_pickup.glb",
    "wheels": HD_CHASSIS_DIR + "/hd_drw_wheels.blend",
    "overall_length": 5.74,           # pickup bumper to bumper (the model is ~9 % oversize; body width -> 2.03 m)
    "wheelbase_cc": 4.19,             # 165 in, the long 1-ton DRW chassis-cab wheelbase
    "frame_length_behind_cab": 4.15,
    "frame_top_z": 0.80,
    "frame_hw": 0.43,
    "dual_rear_wheels": True,
    # used to locate the front axle, then removed with the other wheel parts (DRW wheels replace them)
    "front_tire_objects": ["Object_87", "Object_88", "Object_93", "Object_94", "Object_95", "Object_96"],
    # grille oval (chrome ring + script, blue fill; the fill object also holds the tailgate oval),
    # tailgate oval, fender model/series badges, door engine badges (red + white lettering)
    "debadge_objects": ["Object_53", "Object_38", "Object_58", "Object_46", "Object_47", "Object_68",
                        "Object_97"],
    # licence plates + front plate bracket, roof antenna (pokes into the cabover), front wheels/hubs/discs
    "remove_objects": ["Object_3", "Object_4", "Object_5", "Object_36", "Object_80", "Object_6",
                       "Object_37", "Object_72", "Object_74", "Object_76", "Object_77"],
    # extra non-paint faces removed by region: [[x0, y0, z0], [x1, y1, z1]] in the normalised model
    # frame before the mount shift; x is compared as |x| so one box covers both sides
    "badge_boxes": [[[0.90, 1.36, 1.07], [1.10, 1.61, 1.17]],     # fender badge backing
                    [[0.90, 1.00, 0.80], [1.10, 1.29, 0.875]],    # door badge backing
                    [[0.00, 2.718, 0.947], [0.097, 2.76, 1.029]]], # oval mount boss on the grille face
    "paint_materials": ["carpaint"],
    "material_map": {"black": "trim", "chrome": "chrome", "mirror": "chrome", "clearglass": "glass_clear",
                     "windowglass": "glass_light", "orangeglass": "lamp_amber", "redglass": "lamp_red_lens",
                     "interior": "interior", "material_15": "alloy", "brakedisk": "steel", "tire": "tire",
                     "white": "plastic_white", "material": "trim"},
    "wheel_material_map": {"hdw_tire": "tire", "hdw_rim": "alloy", "hdw_hub": "chrome"},
}


def check_glb(path):
    """Fail unless path is a binary glTF 2.0 file whose header length matches the file and whose first
    chunk is JSON. Returns the parsed JSON chunk."""
    import json
    import struct

    from lib.common import PipelineError
    size = path.stat().st_size
    with open(path, "rb") as f:
        head = f.read(20)
        if len(head) < 20:
            raise PipelineError(f"{path}: too short for a .glb")
        magic, ver, length = struct.unpack("<4sII", head[:12])
        clen, ctype = struct.unpack("<I4s", head[12:20])
        if magic != b"glTF" or ver != 2 or length != size or ctype != b"JSON":
            raise PipelineError(f"{path}: not a valid glTF 2.0 binary (magic {magic!r}, version {ver}, "
                                f"header length {length} vs file {size}, chunk {ctype!r})")
        try:
            meta = json.loads(f.read(clen))
        except ValueError as e:
            raise PipelineError(f"{path}: glTF JSON chunk does not parse: {e}") from e
    if meta.get("asset", {}).get("version") != "2.0":
        raise PipelineError(f"{path}: glTF asset version {meta.get('asset', {}).get('version')!r}, need 2.0")
    return meta


def _base_name(mat):
    head, dot, tail = mat.name.rpartition(".")
    return head if dot and tail.isdigit() and len(tail) == 3 else mat.name


def _remove_object(ob):
    me = ob.data
    bpy.data.objects.remove(ob)
    if me is not None and me.users == 0:
        bpy.data.meshes.remove(me)


def build_hd_chassis_reference(spec, mats, collection):
    """HD regular-cab chassis cab with dual rear wheels from the two downloaded references.
    Returns TruckInfo (cab_chassis contract, variant frame: origin = frame top, 7 cm behind the cab)."""
    from mathutils import Matrix

    from lib.common import PipelineError, repo_path
    s = dict(HD_CHASSIS_DEFAULTS)
    s.update({k: v for k, v in spec.items() if not k.startswith("_")})
    if s.get("type", "cab_chassis") != "cab_chassis":
        raise PipelineError("hd_reference truck: type must be cab_chassis")
    path, wpath = repo_path(s["model"]), repo_path(s["wheels"])
    for p_, what in ((path, "regular-cab pickup .glb"),
                     (wpath, "DRW wheel .blend; build it with scripts/extract_hd_wheels.py")):
        if not p_.is_file():
            raise PipelineError(f"HD chassis reference missing: {p_} ({what}). See README 'Credits'; "
                                f"or use --set truck.source=procedural.")
    check_glb(path)
    wb = s["wheelbase_cc"]
    frame_top, fw = s["frame_top_z"], s["frame_hw"]
    objs = _import_reference(path, collection)

    # ---- normalise: centre x, front toward +Y (model front is at its -Y end), metres, ground z = 0
    vs = _verts_world(objs)
    lo = Vector(tuple(min(v[i] for v in vs) for i in range(3)))
    hi = Vector(tuple(max(v[i] for v in vs) for i in range(3)))
    k = s["overall_length"] / (hi.y - lo.y)
    M = (Matrix.Scale(k, 4) @ Matrix.Rotation(math.pi, 4, "Z")
         @ Matrix.Translation((-(lo.x + hi.x) / 2, -(lo.y + hi.y) / 2, -lo.z)))
    for ob in objs:
        ob.data.transform(M)
        ob.data.update()
    byname = {o.name: o for o in objs}
    missing = [n for n in s["front_tire_objects"] + s["debadge_objects"] + s["remove_objects"] if n not in byname]
    if missing:
        raise PipelineError(f"hd_reference: objects {missing} not in {path.name} (a different download?)")
    ft = _verts_world([byname[n] for n in s["front_tire_objects"]])
    y_fa = (min(v.y for v in ft) + max(v.y for v in ft)) / 2

    # ---- debadge, plates, antenna, original wheels
    gone = set(s["debadge_objects"] + s["remove_objects"] + s["front_tire_objects"])
    for n in gone:
        _remove_object(byname[n])
    objs = [byname[n] for n in byname if n not in gone]
    removed = 0
    paint = set(s["paint_materials"])
    for bx in s["badge_boxes"]:
        lo_b, hi_b = Vector(bx[0]), Vector(bx[1])
        for ob in objs:
            removed += _delete_faces(ob, lambda m, c: (m is None or _base_name(m) not in paint)
                                     and all(lo_b[i] <= (abs(c[i]) if i == 0 else c[i]) <= hi_b[i] for i in range(3)))

    # ---- measure: roof, cab back (rays over the bed rails)
    bpy.context.view_layer.update()
    scene = bpy.context.scene
    dg = bpy.context.evaluated_depsgraph_get()
    tops = [_ray(scene, dg, (0.0, y / 20, 5.0), (0, 0, -1)) for y in range(-2, 25)]
    tops = [h.z for h in tops if h is not None]
    if not tops:
        raise PipelineError("hd_reference: cab roof not found")
    roof = max(tops)
    hits = []
    for ix in range(-7, 8):
        for iz in range(0, 7):
            h = _ray(scene, dg, (ix * 0.1, -1.5, 1.30 + (roof - 0.10 - 1.30) * iz / 6), (0, 1, 0), dist=3.0)
            if h is not None and h.y > -1.0:
                hits.append(h.y)
    if not hits:
        raise PipelineError("hd_reference: cab back not found")
    cab_back = min(hits)
    y_cut = cab_back - 0.012
    faces = 0
    keep = []
    for ob in objs:
        faces += _cut_behind(ob, y_cut)
        if len(ob.data.polygons):
            keep.append(ob)
        else:
            _remove_object(ob)
    objs = keep

    # ---- DRW wheel assemblies (front singles, rear duals) from the extracted .blend
    with bpy.data.libraries.load(str(wpath), link=False) as (src, dst):
        dst.objects = [n for n in src.objects if n.startswith("hdw_")]
    wheels = [o for o in dst.objects if o is not None]
    if sorted(o.get("axle", "") for o in wheels) != ["front", "front", "rear", "rear"]:
        raise PipelineError(f"{wpath.name}: expected 2 front + 2 rear wheel assemblies")
    y_ra = y_fa - wb
    for ob in wheels:
        collection.objects.link(ob)
        yy = y_fa if ob["axle"] == "front" else y_ra
        ob.data.transform(Matrix.Translation((ob["center_x"], yy, ob["tire_diameter"] / 2)))
        ob.matrix_world.identity()
        for slot in ob.material_slots:
            slot.material = mats[s["wheel_material_map"][_base_name(slot.material)]]
        for pl in ob.data.polygons:
            pl.use_smooth = True
    front = next(o for o in wheels if o["axle"] == "front")
    rear = next(o for o in wheels if o["axle"] == "rear")
    tire_r = front["tire_diameter"] / 2
    track = 2 * abs(front["center_x"])
    rear_track = abs(rear["center_x"]) + rear["width"] / 2

    y_end = y_cut - s["frame_length_behind_cab"]
    chassis = _rear_chassis(mats, collection, 0.0, y_cut, y_end, frame_top, fw, y_ra, tire_r,
                            abs(rear["center_x"]), name="pv_hd_chassis")

    # ---- materials: shared body paint, render library for everything else
    unmapped = set()
    for ob in objs:
        for slot in ob.material_slots:
            m = slot.material
            if m is None:
                continue
            b = _base_name(m)
            if b in paint:
                slot.material = mats["paint"]
            elif b in s["material_map"]:
                slot.material = mats[s["material_map"][b]]
            else:
                unmapped.add(b)
    if unmapped:
        raise PipelineError(f"hd_reference: unmapped model materials {sorted(unmapped)}")
    objs += wheels + [chassis]

    # ---- shift: origin = frame top, centred, 7 cm behind the cab back
    oy = cab_back - 0.07
    for ob in objs:
        ob.data.transform(Matrix.Translation((0.0, -oy, 0.0)))
        ob.location.z -= frame_top
    mats.ground_z = -frame_top
    info = TruckInfo(
        type="cab_chassis", source="hd_reference", mount_local=[0.0, 0.0, frame_top], ground_z=-frame_top,
        roof_z=roof - frame_top, cab_back_y=0.07, front_y=max(v.y for v in _verts_world(objs)) - 0.0,
        front_axle_y=y_fa - oy, rear_axle_y=y_ra - oy, wheelbase=wb, body_hw=1.01,
        track=track, tire_radius=tire_r, spec=s,
        frame_top_z=0.0, frame_hw=fw, frame_end_y=y_end - oy, rear_track=rear_track, axle_z=tire_r - frame_top,
    )
    info["objects"] = objs
    print(f"[hd chassis] {path.name}: scale {k:.5f}, {faces} faces after cut, removed {len(gone)} objects + "
          f"{removed} badge faces; roof {roof:.3f}, cab back {cab_back:.3f}, front axle {y_fa:.3f} "
          f"(front axle to cab back {y_fa - cab_back:.3f}), wheelbase {wb:.2f}, tyre r {tire_r:.3f}, "
          f"front track {track:.3f}, rear outer half width {rear_track:.3f}")
    return info
