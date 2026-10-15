"""Shared bmesh/geometry helpers for the shell builder, the proxy truck and camper variants.

Blender-only (imports bpy/bmesh). Everything here is deterministic: no randomness, no selection
state, no operators that depend on UI context. Coordinates are metres, +Z up, +Y forward.

Main entry points for variant authors:
  Part                      - one mesh object assembled from primitives, material slots by key
  box / oriented_box        - (bevelled) boxes;  prism_x / prism_y - extrude a 2D profile
  cylinder_x / revolve_x    - wheels, tubes;     arc_band_x - fender lips / arches
  loft(part, rings, ...)    - skin equal-length rings (sections) into a closed solid
  rounded_rect(...)         - CCW rounded-rectangle outline (u, v)
  build_prism(bm, a, b)     - closed prism between two rings (window cutters)
  boolean_apply(obj, cutter_objs, op) - apply an EXACT boolean and keep the result as mesh
  cut_openings(obj, rings_out, rings_in, glass_key, wall_key, mats)
                             - generic window cutter: pockets/holes with glass floors + gasket walls
  finish_hard_surface(obj)  - auto smooth + weighted normals (clean shading after booleans)
  add_box_uv / new_object   - UV + object creation used by the exported shell
"""
import math

import bmesh
import bpy
from mathutils import Matrix, Vector


# ------------------------------------------------------------------ objects / UVs (shell export)

def add_box_uv(bm, name="UVMap"):
    """Deterministic box-projection UVs (metres, projected along each face's dominant normal axis).

    Placeholder mapping so SCS materials have a UV layer; real unwrap/texel density is a later phase.
    """
    uv_layer = bm.loops.layers.uv.get(name) or bm.loops.layers.uv.new(name)
    for face in bm.faces:
        n = face.normal
        ax = max(range(3), key=lambda i: abs(n[i]))
        u_i, v_i = [(1, 2), (0, 2), (0, 1)][ax]
        for loop in face.loops:
            co = loop.vert.co
            loop[uv_layer].uv = (co[u_i], co[v_i])


def new_object(name, bm, collection, materials, smooth_angle=None):
    """bmesh -> mesh object linked to collection (frees bm). Used by the exported shell."""
    bm.normal_update()
    add_box_uv(bm)
    mesh = bpy.data.meshes.new(name)
    bm.to_mesh(mesh)
    bm.free()
    for m in materials:
        mesh.materials.append(m)
    if smooth_angle is not None:
        for p in mesh.polygons:
            p.use_smooth = True
        mesh.use_auto_smooth = True
        mesh.auto_smooth_angle = math.radians(smooth_angle)
    obj = bpy.data.objects.new(name, mesh)
    collection.objects.link(obj)
    return obj


# ------------------------------------------------------------------ outlines / prisms

def rounded_rect(u0, u1, v0, v1, r, seg):
    """CCW outline (u right, v up) of a rounded rectangle; seg segments per 90-degree corner."""
    r = min(r, (u1 - u0) / 2 - 1e-4, (v1 - v0) / 2 - 1e-4)
    corners = [((u1 - r, v0 + r), -90), ((u1 - r, v1 - r), 0), ((u0 + r, v1 - r), 90), ((u0 + r, v0 + r), 180)]
    pts = []
    for (cu, cv), a0 in corners:
        for i in range(seg + 1):
            a = math.radians(a0 + 90 * i / seg)
            pts.append((cu + r * math.cos(a), cv + r * math.sin(a)))
    return pts


def rounded_poly(pts, r, seg):
    """Round every corner of a convex CCW polygon [(u, v)] with radius r (clamped per corner)."""
    out = []
    n = len(pts)
    for i in range(n):
        p0, p1, p2 = Vector(pts[i - 1]), Vector(pts[i]), Vector(pts[(i + 1) % n])
        a, b = (p0 - p1), (p2 - p1)
        la, lb = a.length, b.length
        a.normalize()
        b.normalize()
        ang = a.angle(b)
        t = r / math.tan(ang / 2)
        t = min(t, la * 0.45, lb * 0.45)
        rr = t * math.tan(ang / 2)
        s, e = p1 + a * t, p1 + b * t
        bis = (a + b).normalized()
        c = p1 + bis * (rr / math.sin(ang / 2))
        a0 = math.atan2(s.y - c.y, s.x - c.x)
        a1 = math.atan2(e.y - c.y, e.x - c.x)
        da = (a1 - a0 + math.pi) % (2 * math.pi) - math.pi
        for k in range(seg + 1):
            aa = a0 + da * k / seg
            out.append((c.x + rr * math.cos(aa), c.y + rr * math.sin(aa)))
    return out


def build_prism(bm, ring_a, ring_b, mat_index=0):
    """Closed prism between two equal-length rings (caps + sides) appended to bm."""
    va = [bm.verts.new(p) for p in ring_a]
    vb = [bm.verts.new(p) for p in ring_b]
    faces = [bm.faces.new(va), bm.faces.new(vb[::-1])]
    n = len(va)
    for i in range(n):
        j = (i + 1) % n
        faces.append(bm.faces.new([va[i], va[j], vb[j], vb[i]]))
    for f in faces:
        f.material_index = mat_index
    return faces


def annulus_prism(bm, outer_a, outer_b, inner_a, inner_b, mat_index=0):
    """Closed ring-shaped prism (e.g. a panel-gap groove around a door): outer/inner rings at both ends."""
    oa = [bm.verts.new(p) for p in outer_a]
    ob = [bm.verts.new(p) for p in outer_b]
    ia = [bm.verts.new(p) for p in inner_a]
    ib = [bm.verts.new(p) for p in inner_b]
    n = len(oa)
    faces = []
    for i in range(n):
        j = (i + 1) % n
        faces.append(bm.faces.new([oa[i], oa[j], ob[j], ob[i]]))
        faces.append(bm.faces.new([ia[j], ia[i], ib[i], ib[j]]))
        faces.append(bm.faces.new([oa[j], oa[i], ia[i], ia[j]]))
        faces.append(bm.faces.new([ob[i], ob[j], ib[j], ib[i]]))
    for f in faces:
        f.material_index = mat_index
    bmesh.ops.recalc_face_normals(bm, faces=faces)
    return faces


def add_box(bm, center, axes, size, mat_index, bevel=0.0):
    """Oriented box: axes = (ax, ay, az) unit vectors, size = full extents along them."""
    res = bmesh.ops.create_cube(bm, size=1.0)
    verts = res["verts"]
    for v in verts:
        lx, ly, lz = v.co
        v.co = center + axes[0] * lx * size[0] + axes[1] * ly * size[1] + axes[2] * lz * size[2]
    faces = list({f for v in verts for f in v.link_faces})
    for f in faces:
        f.material_index = mat_index
    if bevel > 0:
        edges = list({e for v in verts for e in v.link_edges})
        bmesh.ops.bevel(bm, geom=edges, offset=bevel, segments=2, profile=0.5,
                        affect="EDGES", clamp_overlap=True)


# ------------------------------------------------------------------ Part (multi-material object builder)

class Part:
    """One mesh object being assembled from several primitives; material slots by key.

    `mats` is anything indexable by key (dict or lib.materials.MaterialLibrary).
    """

    def __init__(self, name, mats):
        self.name, self.mats = name, mats
        self.bm = bmesh.new()
        self.slots = []

    def idx(self, key):
        if key not in self.slots:
            self.slots.append(key)
        return self.slots.index(key)

    def set_mat(self, faces, key):
        i = self.idx(key)
        for f in faces:
            f.material_index = i

    def finish(self, collection, smooth=35, weighted=False, uv=True):
        bm = self.bm
        bm.normal_update()
        if uv:
            add_box_uv(bm)
        me = bpy.data.meshes.new(self.name)
        bm.to_mesh(me)
        bm.free()
        for k in self.slots:
            me.materials.append(self.mats[k])
        ob = bpy.data.objects.new(self.name, me)
        collection.objects.link(ob)
        if smooth:
            set_smooth(ob, smooth)
            if weighted:
                add_weighted_normals(ob)
        return ob


def set_smooth(ob, angle=35):
    me = ob.data
    for p in me.polygons:
        p.use_smooth = True
    me.use_auto_smooth = True
    me.auto_smooth_angle = math.radians(angle)


def add_weighted_normals(ob, weight=50):
    """Weighted-normal modifier: large flat faces dominate, so booleans/bevels shade cleanly."""
    if not ob.data.use_auto_smooth:
        set_smooth(ob, 35)
    m = ob.modifiers.new("weighted_normals", "WEIGHTED_NORMAL")
    m.keep_sharp = True
    m.weight = weight
    m.mode = "FACE_AREA"
    return m


def finish_hard_surface(ob, angle=35):
    set_smooth(ob, angle)
    add_weighted_normals(ob)
    return ob


def bevel(bm, edges, offset, segments=2, profile=0.5, mat_index=None):
    """Bevel edges. New faces get mat_index, or (default) the material of the face they replace
    most (bmesh otherwise gives them slot 0)."""
    edges = [e for e in edges if e.is_valid]
    if not edges or offset <= 0:
        return []
    if mat_index is None:
        from collections import Counter
        cnt = Counter(f.material_index for e in edges for f in e.link_faces)
        mat_index = cnt.most_common(1)[0][0] if cnt else 0
    res = bmesh.ops.bevel(bm, geom=edges, offset=offset, segments=segments, profile=profile,
                          affect="EDGES", clamp_overlap=True, material=mat_index)
    for f in res["faces"]:
        f.material_index = mat_index
    return res["faces"]


def faces_of(verts):
    return list({f for v in verts for f in v.link_faces})


def edges_of(verts):
    return list({e for v in verts for e in v.link_edges})


def solidify(bm, faces, thickness):
    """Thicken faces (bmesh solidify); positive thickness goes against the normals."""
    return bmesh.ops.solidify(bm, geom=faces, thickness=thickness)


# ------------------------------------------------------------------ primitives

def box(part, lo, hi, key, bev=0.0, seg=2):
    bm = part.bm
    res = bmesh.ops.create_cube(bm, size=1.0)
    vs = res["verts"]
    for v in vs:
        v.co = Vector(tuple(hi[i] if v.co[i] > 0 else lo[i] for i in range(3)))
    part.set_mat(faces_of(vs), key)
    bevel(bm, edges_of(vs), bev, seg)
    return vs


def oriented_box(part, center, axes, size, key, bev=0.0, seg=2):
    bm = part.bm
    vs = bmesh.ops.create_cube(bm, size=1.0)["verts"]
    for v in vs:
        lx, ly, lz = v.co
        v.co = center + axes[0] * lx * size[0] + axes[1] * ly * size[1] + axes[2] * lz * size[2]
    part.set_mat(faces_of(vs), key)
    bevel(bm, edges_of(vs), bev, seg)
    return vs


def _prism(part, ring_a, ring_b, key):
    bm = part.bm
    a = [bm.verts.new(p) for p in ring_a]
    b = [bm.verts.new(p) for p in ring_b]
    faces = [bm.faces.new(a), bm.faces.new(b[::-1])]
    n = len(a)
    for i in range(n):
        j = (i + 1) % n
        faces.append(bm.faces.new([a[i], a[j], b[j], b[i]]))
    bmesh.ops.recalc_face_normals(bm, faces=faces)
    part.set_mat(faces, key)
    return a + b


def prism_x(part, profile_yz, x0, x1, key):
    """Extrude a side-profile polygon (y, z) across x0..x1; returns its verts."""
    return _prism(part, [(x0, y, z) for y, z in profile_yz], [(x1, y, z) for y, z in profile_yz], key)


def prism_y(part, profile_xz, y0, y1, key):
    """Extrude a cross-section polygon (x, z) along y0..y1; returns its verts."""
    return _prism(part, [(x, y0, z) for x, z in profile_xz], [(x, y1, z) for x, z in profile_xz], key)


def prism_z(part, profile_xy, z0, z1, key):
    """Extrude a plan polygon (x, y) over z0..z1; returns its verts."""
    return _prism(part, [(x, y, z0) for x, y in profile_xy], [(x, y, z1) for x, y in profile_xy], key)


def cylinder_x(part, cy, cz, r, x0, x1, key, seg=32, bev=0.0, bev_seg=2):
    bm = part.bm
    res = bmesh.ops.create_cone(bm, cap_ends=True, cap_tris=False, segments=seg,
                                radius1=r, radius2=r, depth=abs(x1 - x0))
    vs = res["verts"]
    m = Matrix.Translation(((x0 + x1) / 2, cy, cz)) @ Matrix.Rotation(math.radians(90), 4, "Y")
    bmesh.ops.transform(bm, matrix=m, verts=vs)
    part.set_mat(faces_of(vs), key)
    if bev:
        rim_edges = [e for e in edges_of(vs) if all(abs(math.hypot(v.co.y - cy, v.co.z - cz) - r) < 1e-4
                                                     for v in e.verts)
                     and abs(e.verts[0].co.x - e.verts[1].co.x) < 1e-6]
        bevel(bm, rim_edges, bev, bev_seg)
    return vs


def cylinder_y(part, cx, cz, r, y0, y1, key, seg=24):
    """Tube/rod along Y (frame tubes, step bars, exhaust)."""
    bm = part.bm
    res = bmesh.ops.create_cone(bm, cap_ends=True, cap_tris=False, segments=seg,
                                radius1=r, radius2=r, depth=abs(y1 - y0))
    vs = res["verts"]
    m = Matrix.Translation((cx, (y0 + y1) / 2, cz)) @ Matrix.Rotation(math.radians(-90), 4, "X")
    bmesh.ops.transform(bm, matrix=m, verts=vs)
    part.set_mat(faces_of(vs), key)
    return vs


def cylinder_z(part, cx, cy, r, z0, z1, key, seg=24):
    bm = part.bm
    res = bmesh.ops.create_cone(bm, cap_ends=True, cap_tris=False, segments=seg,
                                radius1=r, radius2=r, depth=abs(z1 - z0))
    vs = res["verts"]
    bmesh.ops.translate(bm, vec=(cx, cy, (z0 + z1) / 2), verts=vs)
    part.set_mat(faces_of(vs), key)
    return vs


def arc_band_x(part, cy, cz, r0, r1, a0, a1, x0, x1, key, seg=16):
    """Annular arc (angles in degrees, 0 = +Y, 90 = up) extruded over x0..x1 - a fender lip."""
    bm = part.bm
    rings = []
    for i in range(seg + 1):
        a = math.radians(a0 + (a1 - a0) * i / seg)
        dy, dz = math.cos(a), math.sin(a)
        rings.append([bm.verts.new((x, cy + r * dy, cz + r * dz)) for x, r in
                      ((x0, r0), (x1, r0), (x1, r1), (x0, r1))])
    faces = []
    for i in range(seg):
        A, B = rings[i], rings[i + 1]
        for j in range(4):
            k = (j + 1) % 4
            faces.append(bm.faces.new([A[j], A[k], B[k], B[j]]))
    faces.append(bm.faces.new(rings[0]))
    faces.append(bm.faces.new(rings[-1][::-1]))
    bmesh.ops.recalc_face_normals(bm, faces=faces)
    part.set_mat(faces, key)
    return faces


def sweep_arc_x(part, cy, cz, radius, a0, a1, section_xr, key, seg=24):
    """Sweep a closed cross-section [(x, dr)] around an arc about the X axis (rounded fender flares).

    dr is the radial offset from `radius`; angles in degrees (0 = +Y, 90 = up).
    """
    bm = part.bm
    rings = []
    for i in range(seg + 1):
        a = math.radians(a0 + (a1 - a0) * i / seg)
        dy, dz = math.cos(a), math.sin(a)
        rings.append([bm.verts.new((x, cy + (radius + dr) * dy, cz + (radius + dr) * dz))
                      for x, dr in section_xr])
    faces = []
    n = len(section_xr)
    for i in range(seg):
        A, B = rings[i], rings[i + 1]
        for j in range(n):
            k = (j + 1) % n
            faces.append(bm.faces.new([A[j], A[k], B[k], B[j]]))
    faces.append(bm.faces.new(rings[0]))
    faces.append(bm.faces.new(rings[-1][::-1]))
    bmesh.ops.recalc_face_normals(bm, faces=faces)
    part.set_mat(faces, key)
    return faces


def revolve_x(part, cy, cz, profile_xr, key, seg=40, closed=True):
    """Revolve an (x, radius) profile around the axis parallel to X through (cy, cz).

    closed=True treats the profile as a closed loop (solid ring); False leaves it open (a surface).
    Returns the list of rings (each a list of verts) so callers can assign materials per band.
    """
    bm = part.bm
    rings = []
    for i in range(seg):
        a = 2 * math.pi * i / seg
        ca, sa = math.cos(a), math.sin(a)
        rings.append([bm.verts.new((x, cy + r * ca, cz + r * sa)) for x, r in profile_xr])
    faces = []
    n = len(profile_xr)
    for i in range(seg):
        A, B = rings[i], rings[(i + 1) % seg]
        for j in range(n if closed else n - 1):
            k = (j + 1) % n
            faces.append(bm.faces.new([A[j], A[k], B[k], B[j]]))
    bmesh.ops.recalc_face_normals(bm, faces=faces)
    part.set_mat(faces, key)
    return faces


def loft(part, rings, key, cap_start=True, cap_end=True, closed=True):
    """Skin equal-length point rings into a surface (closed loop sections, optional end caps)."""
    bm = part.bm
    vr = [[bm.verts.new(p) for p in ring] for ring in rings]
    faces = []
    n = len(rings[0])
    for i in range(len(vr) - 1):
        A, B = vr[i], vr[i + 1]
        for j in range(n if closed else n - 1):
            k = (j + 1) % n
            faces.append(bm.faces.new([A[j], A[k], B[k], B[j]]))
    if cap_start:
        faces.append(bm.faces.new(vr[0][::-1]))
    if cap_end:
        faces.append(bm.faces.new(vr[-1]))
    bmesh.ops.recalc_face_normals(bm, faces=faces)
    part.set_mat(faces, key)
    return vr, faces


# ------------------------------------------------------------------ booleans / window cutter

def _tmp_object(name, bm, materials, collection):
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    for m in materials:
        me.materials.append(m)
    ob = bpy.data.objects.new(name, me)
    collection.objects.link(ob)
    return ob


def boolean_apply(obj, cutters, op="DIFFERENCE", material_mode="TRANSFER", remove_cutters=True):
    """Apply EXACT boolean(s) to obj's mesh in place (modifier evaluated, then baked into the data).

    cutters: object or list of objects. Existing modifiers on obj are evaluated too, so call this
    before adding display-only modifiers (weighted normals).
    """
    if not isinstance(cutters, (list, tuple)):
        cutters = [cutters]
    for c in cutters:
        mod = obj.modifiers.new("bool_" + c.name, "BOOLEAN")
        mod.operation = op
        mod.solver = "EXACT"
        mod.use_self = True          # cutters are often several overlapping primitives
        mod.use_hole_tolerant = True
        mod.material_mode = material_mode
        mod.object = c
    dg = bpy.context.evaluated_depsgraph_get()
    ev = obj.evaluated_get(dg)
    me = bpy.data.meshes.new_from_object(ev, preserve_all_data_layers=True, depsgraph=dg)
    old = obj.data
    obj.modifiers.clear()
    obj.data = me
    me.name = old.name
    if old.users == 0:
        bpy.data.meshes.remove(old)
    if remove_cutters:
        for c in cutters:
            cm = c.data
            bpy.data.objects.remove(c)
            if cm.users == 0:
                bpy.data.meshes.remove(cm)
    return obj


def cut_openings(obj, openings, mats, collection, glass_key="glass", wall_key="trim"):
    """Generic window cutter. openings = [(ring_outside, ring_inside)] point lists of equal length.

    Each opening becomes a prism from ring_outside to ring_inside. If ring_inside ends inside the
    solid you get a recessed pocket whose floor is `glass_key` (flush glazing); if it passes through
    the wall you get a real hole. Pocket/hole walls get `wall_key` (black gasket).
    """
    if not openings:
        return obj
    bm = bmesh.new()
    for ring_o, ring_i in openings:
        faces = build_prism(bm, ring_o, ring_i, mat_index=1)
        bmesh.ops.recalc_face_normals(bm, faces=faces)
        # caps: first two faces from build_prism -> glass on the inner cap (pocket floor).
        faces[0].material_index = 1
        faces[1].material_index = 0
    cutter = _tmp_object(obj.name + "_cut", bm, [mats[glass_key], mats[wall_key]], collection)
    return boolean_apply(obj, cutter, "DIFFERENCE", "TRANSFER")


def bm_object(name, bm, materials, collection):
    """Plain bmesh -> object (no UVs/smoothing); for temporary cutters."""
    return _tmp_object(name, bm, materials, collection)
