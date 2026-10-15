"""Render environment shared by render_preview.py and render_variants.py (render-only).

  env = load_render_config()                     # config/render.json
  sun = setup_world(env["hdri"])                 # HDRI world (sun disk clamped) + matching sun lamp
  add_ground(ground_z, env["ground"], col)       # road, lane lines, gravel shoulder, dry grass
  cam = place_camera(view_spec, bbox, ground_z)  # auto-framed camera with slight DOF
  configure_render(profile)                      # surface | surface-photo | gaming

World frame: variant origin at (0, 0, 0); the ground is at z = ground_z (< 0); the road runs
along Y, the vehicle drives toward +Y in the right-hand lane.
"""
import math
from pathlib import Path

import bmesh
import bpy
from mathutils import Matrix, Vector

from lib.common import PipelineError, load_json, repo_path

RENDER_CONFIG = "config/render.json"


def load_render_config(path=RENDER_CONFIG):
    return load_json(path)


# ------------------------------------------------------------------ HDRI world + sun

def hdri_path(hdri_cfg):
    p = repo_path(hdri_cfg["file"])
    if not p.is_file():
        raise PipelineError(
            f"HDRI missing: {p}\n  tools/ is ./tools unless ATS_TOOLS_DIR or config/tools.local.json say otherwise "
            f"(README 'Tools'); run scripts/fetch_tools.ps1 "
            f"(downloads {Path(hdri_cfg['file']).name} from Poly Haven, CC0, sha256-checked)")
    return p


def _sun_from_image(img, clamp):
    """Locate the sun in an equirect HDRI: direction (image space), irradiance above `clamp`, colour.

    Pixels brighter than `clamp` (luminance) are the sun disk; their excess radiance x solid angle
    is the irradiance the world loses when we clamp it, which the sun lamp gives back.
    """
    import numpy as np
    w, h = img.size
    px = np.empty(w * h * 4, dtype=np.float32)
    img.pixels.foreach_get(px)
    px = px.reshape(h, w, 4)[:, :, :3]
    lum = px @ np.array([0.2126, 0.7152, 0.0722], dtype=np.float32)
    mask = lum > clamp
    if not mask.any():
        raise PipelineError(f"no pixels above clamp {clamp} in HDRI: cannot find the sun")
    rows, cols = np.nonzero(mask)
    elev = (rows + 0.5) / h * math.pi - math.pi / 2          # row 0 = bottom
    d_omega = (2 * math.pi / w) * (math.pi / h) * np.cos(elev)
    excess = px[rows, cols] - (px[rows, cols] * (clamp / lum[rows, cols])[:, None])
    weights = (lum[rows, cols] - clamp) * d_omega
    u = (cols + 0.5) / w
    az = (0.5 - u) * 2 * math.pi                              # atan2(y, x) of the direction
    vec = np.stack([np.cos(elev) * np.cos(az), np.cos(elev) * np.sin(az), np.sin(elev)], axis=1)
    d = (vec * weights[:, None]).sum(axis=0)
    d /= np.linalg.norm(d)
    rgb = (excess * d_omega[:, None]).sum(axis=0)              # irradiance per channel (W/m^2 units)
    strength = float(rgb @ np.array([0.2126, 0.7152, 0.0722]))
    color = rgb / max(rgb.max(), 1e-9)
    return Vector(d.tolist()), strength, tuple(float(c) for c in color), int(mask.sum())


_SUN_CACHE = {}


class World:
    """HDRI world + matching sun lamp; set_sun_azimuth() re-orients both together."""

    def __init__(self, hdri_cfg):
        path = hdri_path(hdri_cfg)
        self.cfg = hdri_cfg
        img = bpy.data.images.load(str(path), check_existing=True)
        clamp = hdri_cfg.get("sun_clamp", 20.0)
        key = (str(path), clamp)
        if key not in _SUN_CACHE:
            _SUN_CACHE[key] = _sun_from_image(img, clamp)
        self.d_img, irr, color, self.npx = _SUN_CACHE[key]
        self.az_img = math.degrees(math.atan2(self.d_img.x, self.d_img.y))

        world = bpy.data.worlds.new("hdri_world")
        world.use_nodes = True
        nodes, links = world.node_tree.nodes, world.node_tree.links
        bg = nodes["Background"]
        tc = nodes.new("ShaderNodeTexCoord")
        self.mapping = nodes.new("ShaderNodeMapping")
        env = nodes.new("ShaderNodeTexEnvironment")
        env.image = img
        env.interpolation = "Smart"
        links.new(tc.outputs["Generated"], self.mapping.inputs["Vector"])
        links.new(self.mapping.outputs["Vector"], env.inputs["Vector"])
        # darken(env, clamp) keeps the sky and removes the sun disk (the lamp replaces it)
        clampn = nodes.new("ShaderNodeMixRGB")
        clampn.blend_type = "DARKEN"
        clampn.inputs["Fac"].default_value = 1.0
        clampn.inputs["Color2"].default_value = (clamp, clamp, clamp, 1.0)
        links.new(env.outputs["Color"], clampn.inputs["Color1"])
        links.new(clampn.outputs["Color"], bg.inputs["Color"])
        self.strength = hdri_cfg.get("strength", 1.0)
        bg.inputs["Strength"].default_value = self.strength
        bpy.context.scene.world = world
        try:
            world.cycles.sampling_method = "MANUAL"
            world.cycles.sample_map_resolution = 2048
        except AttributeError:
            pass

        sun_data = bpy.data.lights.new("hdri_sun", "SUN")
        sun_data.energy = irr * self.strength * hdri_cfg.get("sun_scale", 1.0)
        sun_data.color = color
        sun_data.angle = math.radians(hdri_cfg.get("sun_angle_deg", 1.0))
        sun_data.use_contact_shadow = True
        sun_data.contact_shadow_distance = 0.4
        sun_data.contact_shadow_thickness = 0.05
        sun_data.shadow_cascade_max_distance = 40.0
        sun_data.shadow_cascade_count = 4
        sun_data.shadow_cascade_fade = 0.05
        sun_data.shadow_buffer_bias = 0.2
        self.sun = bpy.data.objects.new("hdri_sun", sun_data)
        bpy.context.scene.collection.objects.link(self.sun)
        if hdri_cfg.get("sun_azimuth_deg") is not None:
            self.set_sun_azimuth(hdri_cfg["sun_azimuth_deg"])
        else:
            self.set_rotation(hdri_cfg.get("rotation_deg", 0.0))

    def set_rotation(self, rot_deg):
        """Rotate the HDRI about Z. The mapping rotates the lookup vector, so a texel direction t is
        seen at world direction R(-rot) t; azimuth (clockwise from +Y) grows by rot."""
        rot = math.radians(rot_deg)
        self.rotation_deg = rot_deg
        self.mapping.inputs["Rotation"].default_value = (0.0, 0.0, rot)
        d = Matrix.Rotation(-rot, 3, "Z") @ self.d_img
        self.d_world = d
        self.sun.rotation_euler = (-d).to_track_quat("-Z", "Y").to_euler()

    def set_sun_azimuth(self, az_deg):
        self.set_rotation(az_deg - self.az_img)

    def info(self):
        d = self.d_world
        return {"hdri": str(self.cfg["file"]), "rotation_deg": round(self.rotation_deg, 2),
                "sun_elevation_deg": round(math.degrees(math.asin(max(-1, min(1, d.z)))), 2),
                "sun_azimuth_deg": round(math.degrees(math.atan2(d.x, d.y)) % 360, 2),
                "sun_strength": round(self.sun.data.energy, 3),
                "sun_color": [round(c, 3) for c in self.sun.data.color], "sun_pixels": self.npx,
                "world_strength": self.strength}


def setup_world(hdri_cfg):
    """Create the HDRI world + sun lamp (see World). Fails clearly if the HDRI is missing."""
    return World(hdri_cfg)


# ------------------------------------------------------------------ ground

def _mat(name):
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    return m, m.node_tree.nodes, m.node_tree.links, m.node_tree.nodes["Principled BSDF"]


def _tex_noise(nodes, links, coord, scale, detail=8.0, rough=0.6):
    n = nodes.new("ShaderNodeTexNoise")
    n.inputs["Scale"].default_value = scale
    n.inputs["Detail"].default_value = detail
    n.inputs["Roughness"].default_value = rough
    links.new(coord, n.inputs["Vector"])
    return n


def _ramp(nodes, links, fac, c0, c1, p0=0.3, p1=0.7):
    r = nodes.new("ShaderNodeValToRGB")
    e = r.color_ramp.elements
    e[0].position, e[0].color = p0, (*c0, 1)
    e[1].position, e[1].color = p1, (*c1, 1)
    links.new(fac, r.inputs["Fac"])
    return r


def _maprange(nodes, links, fac, lo, hi, a=0.0, b=1.0):
    m = nodes.new("ShaderNodeMapRange")
    m.inputs["From Min"].default_value = a
    m.inputs["From Max"].default_value = b
    m.inputs["To Min"].default_value = lo
    m.inputs["To Max"].default_value = hi
    links.new(fac, m.inputs["Value"])
    return m.outputs["Result"]


def _horizon_fade(mat, nodes, links, shader_out, r0, r1):
    """Fade the surface to transparent between radius r0..r1 (world XY distance) for camera rays,
    so the ground melts into the HDRI horizon instead of ending at a hard edge."""
    geo = nodes.new("ShaderNodeNewGeometry")
    sep = nodes.new("ShaderNodeSeparateXYZ")
    links.new(geo.outputs["Position"], sep.inputs["Vector"])
    vm = nodes.new("ShaderNodeCombineXYZ")
    links.new(sep.outputs["X"], vm.inputs["X"])
    links.new(sep.outputs["Y"], vm.inputs["Y"])
    ln = nodes.new("ShaderNodeVectorMath")
    ln.operation = "LENGTH"
    links.new(vm.outputs["Vector"], ln.inputs[0])
    fac = nodes.new("ShaderNodeMapRange")
    fac.inputs["From Min"].default_value = r0
    fac.inputs["From Max"].default_value = r1
    links.new(ln.outputs["Value"], fac.inputs["Value"])
    tr = nodes.new("ShaderNodeBsdfTransparent")
    mix = nodes.new("ShaderNodeMixShader")
    links.new(fac.outputs["Result"], mix.inputs["Fac"])
    links.new(shader_out, mix.inputs[1])
    links.new(tr.outputs["BSDF"], mix.inputs[2])
    out = nodes["Material Output"]
    links.new(mix.outputs["Shader"], out.inputs["Surface"])
    mat.blend_method = "HASHED"
    mat.shadow_method = "HASHED"


def make_ground_materials(gcfg):
    fade0, fade1 = gcfg.get("fade_start", 120.0), gcfg.get("fade_end", 260.0)
    mats = {}

    # Asphalt: visible aggregate (two grain scales), macro patches, darker oil streak in the lane
    # centre, lighter polished tyre tracks, glossy tar crack-sealant lines, roughness variation.
    m, nodes, links, b = _mat("env_asphalt")
    tc = nodes.new("ShaderNodeTexCoord")
    co = tc.outputs["Object"]
    agg = nodes.new("ShaderNodeTexVoronoi")
    agg.inputs["Scale"].default_value = 160.0
    links.new(co, agg.inputs["Vector"])
    fine = _tex_noise(nodes, links, co, 700.0, 3.0, 0.6)
    patch = _tex_noise(nodes, links, co, 0.25, 6.0, 0.6)
    patch2 = _tex_noise(nodes, links, co, 1.6, 5.0, 0.55)
    stones = _ramp(nodes, links, agg.outputs["Distance"], (0.13, 0.125, 0.12), (0.055, 0.054, 0.053), 0.05, 0.45)
    finev = _ramp(nodes, links, fine.outputs["Fac"], (0.8, 0.8, 0.8), (1.15, 1.15, 1.15), 0.35, 0.65)
    tone = _ramp(nodes, links, patch.outputs["Fac"], (0.78, 0.78, 0.78), (1.2, 1.18, 1.15), 0.3, 0.72)
    tone2 = _ramp(nodes, links, patch2.outputs["Fac"], (0.88, 0.88, 0.88), (1.08, 1.08, 1.08), 0.35, 0.65)

    def mul(a, b_):
        n = nodes.new("ShaderNodeMixRGB")
        n.blend_type = "MULTIPLY"
        n.inputs["Fac"].default_value = 1.0
        links.new(a, n.inputs["Color1"])
        links.new(b_, n.inputs["Color2"])
        return n.outputs["Color"]

    col = mul(mul(mul(stones.outputs["Color"], finev.outputs["Color"]), tone.outputs["Color"]),
              tone2.outputs["Color"])
    sep = nodes.new("ShaderNodeSeparateXYZ")
    links.new(co, sep.inputs["Vector"])
    ax = nodes.new("ShaderNodeMath")
    ax.operation = "ABSOLUTE"
    links.new(sep.outputs["X"], ax.inputs[0])
    trk = nodes.new("ShaderNodeMath")          # distance to the nearest lane centre (x = 0, -3.6)
    trk.operation = "PINGPONG"
    links.new(ax.outputs[0], trk.inputs[0])
    trk.inputs[1].default_value = 1.8
    oil = _maprange(nodes, links, trk.outputs[0], 0.55, 0.0, 0.0, 0.4)
    off = nodes.new("ShaderNodeMath")
    off.operation = "SUBTRACT"
    links.new(trk.outputs[0], off.inputs[0])
    off.inputs[1].default_value = 0.85
    offa = nodes.new("ShaderNodeMath")
    offa.operation = "ABSOLUTE"
    links.new(off.outputs[0], offa.inputs[0])
    band = _maprange(nodes, links, offa.outputs[0], 0.45, 0.0, 0.0, 0.4)
    dark = nodes.new("ShaderNodeMixRGB")
    dark.blend_type = "MULTIPLY"
    links.new(oil, dark.inputs["Fac"])
    links.new(col, dark.inputs["Color1"])
    dark.inputs["Color2"].default_value = (0.55, 0.55, 0.55, 1)
    wear = nodes.new("ShaderNodeMixRGB")
    wear.blend_type = "MULTIPLY"
    links.new(band, wear.inputs["Fac"])
    links.new(dark.outputs["Color"], wear.inputs["Color1"])
    wear.inputs["Color2"].default_value = (1.25, 1.24, 1.22, 1)
    crk = nodes.new("ShaderNodeTexVoronoi")
    crk.feature = "DISTANCE_TO_EDGE"
    crk.inputs["Scale"].default_value = 0.12
    cw = nodes.new("ShaderNodeTexNoise")       # wobble the crack lines
    cw.inputs["Scale"].default_value = 3.0
    links.new(co, cw.inputs["Vector"])
    warp = nodes.new("ShaderNodeVectorMath")
    warp.operation = "MULTIPLY_ADD"
    links.new(cw.outputs["Color"], warp.inputs[0])
    warp.inputs[1].default_value = (0.25, 0.25, 0.0)
    links.new(co, warp.inputs[2])
    links.new(warp.outputs["Vector"], crk.inputs["Vector"])
    seal0 = _maprange(nodes, links, crk.outputs["Distance"], 0.55, 0.0, 0.0015, 0.0045)
    cm = _tex_noise(nodes, links, co, 0.6, 3.0, 0.5)         # only some cells are sealed
    cmask = _maprange(nodes, links, cm.outputs["Fac"], 0.0, 1.0, 0.48, 0.56)
    sm = nodes.new("ShaderNodeMath")
    sm.operation = "MULTIPLY"
    links.new(seal0, sm.inputs[0])
    links.new(cmask, sm.inputs[1])
    seal = sm.outputs[0]
    sealc = nodes.new("ShaderNodeMixRGB")
    links.new(seal, sealc.inputs["Fac"])
    links.new(wear.outputs["Color"], sealc.inputs["Color1"])
    sealc.inputs["Color2"].default_value = (0.025, 0.025, 0.025, 1)
    links.new(sealc.outputs["Color"], b.inputs["Base Color"])
    rough = _maprange(nodes, links, patch2.outputs["Fac"], 0.72, 0.95, 0.3, 0.7)
    rmix = nodes.new("ShaderNodeMix")
    rmix.data_type = "FLOAT"
    links.new(seal, rmix.inputs[0])
    links.new(rough, rmix.inputs[2])
    rmix.inputs[3].default_value = 0.35
    links.new(rmix.outputs[0], b.inputs["Roughness"])
    bump = nodes.new("ShaderNodeBump")
    bump.inputs["Strength"].default_value = 0.45
    bump.inputs["Distance"].default_value = 0.004
    links.new(agg.outputs["Distance"], bump.inputs["Height"])
    bump2 = nodes.new("ShaderNodeBump")
    bump2.inputs["Strength"].default_value = 0.2
    bump2.inputs["Distance"].default_value = 0.002
    links.new(fine.outputs["Fac"], bump2.inputs["Height"])
    links.new(bump.outputs["Normal"], bump2.inputs["Normal"])
    links.new(bump2.outputs["Normal"], b.inputs["Normal"])
    b.inputs["Specular"].default_value = 0.4
    _horizon_fade(m, nodes, links, b.outputs["BSDF"], gcfg.get("road_fade_start", 260.0),
                  gcfg.get("road_fade_end", 480.0))
    mats["asphalt"] = m

    def paint(name, c):
        m, nodes, links, b = _mat(name)
        tc = nodes.new("ShaderNodeTexCoord")
        n = _tex_noise(nodes, links, tc.outputs["Object"], 25.0, 6.0, 0.7)
        r = _ramp(nodes, links, n.outputs["Fac"], tuple(x * 0.7 for x in c), c, 0.35, 0.65)
        links.new(r.outputs["Color"], b.inputs["Base Color"])
        b.inputs["Roughness"].default_value = 0.6
        _horizon_fade(m, nodes, links, b.outputs["BSDF"], gcfg.get("road_fade_start", 260.0),
                      gcfg.get("road_fade_end", 480.0))
        return m

    mats["lane_white"] = paint("env_lane_white", (0.62, 0.62, 0.58))
    mats["lane_yellow"] = paint("env_lane_yellow", (0.62, 0.42, 0.06))

    # Gravel shoulder + dry grass, blended by a noisy distance from the road edge.
    m, nodes, links, b = _mat("env_verge")
    tc = nodes.new("ShaderNodeTexCoord")
    co = tc.outputs["Object"]
    gv = nodes.new("ShaderNodeTexVoronoi")
    gv.inputs["Scale"].default_value = 70.0
    links.new(co, gv.inputs["Vector"])
    gcol = _ramp(nodes, links, gv.outputs["Distance"], (0.09, 0.08, 0.065), (0.24, 0.21, 0.17), 0.0, 0.6)
    gn = _tex_noise(nodes, links, co, 2.0, 8.0, 0.65)
    grass_n = _tex_noise(nodes, links, co, 18.0, 10.0, 0.7)
    grass = _ramp(nodes, links, grass_n.outputs["Fac"], (0.16, 0.11, 0.05), (0.42, 0.31, 0.15), 0.3, 0.75)
    big = _tex_noise(nodes, links, co, 0.08, 4.0, 0.5)
    tint = _ramp(nodes, links, big.outputs["Fac"], (0.8, 0.82, 0.75), (1.1, 1.0, 0.85), 0.35, 0.65)
    gm = nodes.new("ShaderNodeMixRGB")
    gm.blend_type = "MULTIPLY"
    gm.inputs["Fac"].default_value = 1.0
    links.new(grass.outputs["Color"], gm.inputs["Color1"])
    links.new(tint.outputs["Color"], gm.inputs["Color2"])
    sep = nodes.new("ShaderNodeSeparateXYZ")
    links.new(co, sep.inputs["Vector"])
    ab = nodes.new("ShaderNodeMath")
    ab.operation = "ABSOLUTE"
    xs = nodes.new("ShaderNodeMath")
    xs.operation = "SUBTRACT"
    links.new(sep.outputs["X"], xs.inputs[0])
    xs.inputs[1].default_value = gcfg.get("road_center_x", -1.8)
    links.new(xs.outputs[0], ab.inputs[0])
    jit = nodes.new("ShaderNodeMath")
    jit.operation = "MULTIPLY_ADD"
    links.new(gn.outputs["Fac"], jit.inputs[0])
    jit.inputs[1].default_value = 2.5
    links.new(ab.outputs[0], jit.inputs[2])
    edge = gcfg.get("road_half_width", 3.9)
    mixf = _maprange(nodes, links, jit.outputs[0], 0.0, 1.0, edge + 2.2, edge + 3.6)
    mix = nodes.new("ShaderNodeMixRGB")
    links.new(mixf, mix.inputs["Fac"])
    links.new(gcol.outputs["Color"], mix.inputs["Color1"])
    links.new(gm.outputs["Color"], mix.inputs["Color2"])
    links.new(mix.outputs["Color"], b.inputs["Base Color"])
    b.inputs["Roughness"].default_value = 0.95
    b.inputs["Specular"].default_value = 0.25
    hb = nodes.new("ShaderNodeMixRGB")
    links.new(mixf, hb.inputs["Fac"])
    links.new(gv.outputs["Distance"], hb.inputs["Color1"])
    links.new(grass_n.outputs["Fac"], hb.inputs["Color2"])
    bump = nodes.new("ShaderNodeBump")
    bump.inputs["Strength"].default_value = 0.6
    bump.inputs["Distance"].default_value = 0.02
    links.new(hb.outputs["Color"], bump.inputs["Height"])
    links.new(bump.outputs["Normal"], b.inputs["Normal"])
    _horizon_fade(m, nodes, links, b.outputs["BSDF"], fade0, fade1)
    mats["verge"] = m
    return mats


def _plane(col, name, x0, x1, y0, y1, z, mat, nx=1, ny=1):
    bm = bmesh.new()
    bmesh.ops.create_grid(bm, x_segments=nx, y_segments=ny, size=0.5)
    for v in bm.verts:
        v.co = Vector((x0 + (v.co.x + 0.5) * (x1 - x0), y0 + (v.co.y + 0.5) * (y1 - y0), z))
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    me.materials.append(mat)
    ob = bpy.data.objects.new(name, me)
    col.objects.link(ob)
    return ob


def _disk(col, name, radius, z, mat, seg=96):
    bm = bmesh.new()
    bmesh.ops.create_circle(bm, cap_ends=True, segments=seg, radius=radius)
    for v in bm.verts:
        v.co.z = z
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    me.materials.append(mat)
    ob = bpy.data.objects.new(name, me)
    col.objects.link(ob)
    return ob


def add_ground(ground_z, gcfg, col):
    """Two-lane road along Y (yellow dashed centre line, white edge lines), gravel shoulder,
    dry-grass verge on a large disk that fades into the HDRI horizon."""
    m = make_ground_materials(gcfg)
    cx = gcfg.get("road_center_x", -1.8)
    hw = gcfg.get("road_half_width", 3.9)
    L = gcfg.get("road_length", 500.0)
    _plane(col, "env_road", cx - hw, cx + hw, -L, L, ground_z, m["asphalt"])
    _disk(col, "env_verge", gcfg.get("disk_radius", 300.0), ground_z - 0.03, m["verge"])
    lw = 0.12
    for s in (-1, 1):
        x = cx + s * (hw - 0.25)
        _plane(col, f"env_edge_line_{'l' if s < 0 else 'r'}", x - lw / 2, x + lw / 2, -L, L, ground_z + 0.002,
               m["lane_white"])
    dash, gap = 3.0, 9.0
    n = int(gcfg.get("dash_range", 200.0) / (dash + gap))
    for i in range(-n, n + 1):
        y = i * (dash + gap) + gcfg.get("dash_phase", 1.0)
        _plane(col, f"env_dash_{i + n:03d}", cx - lw / 2, cx + lw / 2, y, y + dash, ground_z + 0.002,
               m["lane_yellow"])
    return m


# ------------------------------------------------------------------ camera

def world_bbox(objects):
    bpy.context.view_layer.update()          # matrix_world is stale after moving objects
    lo = Vector((1e9, 1e9, 1e9))
    hi = Vector((-1e9, -1e9, -1e9))
    for ob in objects:
        if ob.type != "MESH" or ob.hide_render:
            continue
        for c in ob.bound_box:
            w = ob.matrix_world @ Vector(c)
            lo = Vector(map(min, lo, w))
            hi = Vector(map(max, hi, w))
    return lo, hi


def place_camera(spec, bbox, ground_z, aspect=16 / 9, name="render_cam"):
    """Auto-framed camera.

    spec: azimuth_deg (camera position around the vehicle; 0 = in front (+Y), 90 = right (+X),
    180 = behind, 270 = left), height (m above ground), lens (mm), target ([x, y, z] in the variant
    frame, or null = bbox centre), target_height (m above ground, overrides target z), margin
    (fraction of frame kept empty around the bbox), fstop (DOF, null = off), distance (fixed m,
    skips auto-fit), shift_y (lens shift).
    """
    lo, hi = bbox
    centre = (lo + hi) / 2
    t = Vector(spec["target"]) if spec.get("target") else centre.copy()
    if "target_height" in spec:
        t.z = ground_z + spec["target_height"]
    az = math.radians(spec["azimuth_deg"])
    horiz = Vector((math.sin(az), math.cos(az), 0.0))
    cam_z = ground_z + spec.get("height", 1.5)
    data = bpy.data.cameras.new(name)
    data.lens = spec.get("lens", 40)
    data.sensor_width = 36
    data.sensor_fit = "HORIZONTAL"
    data.clip_start, data.clip_end = 0.1, 3000
    data.shift_y = spec.get("shift_y", 0.0)
    cam = bpy.data.objects.new(name, data)
    bpy.context.scene.collection.objects.link(cam)

    corners = [Vector((x, y, z)) for x in (lo.x, hi.x) for y in (lo.y, hi.y) for z in (lo.z, hi.z)]
    half_w = 18.0 / data.lens
    half_h = half_w / aspect
    margin = spec.get("margin", 0.08)

    def fits(dist):
        loc = t + horiz * dist
        loc.z = cam_z
        rot = (t - loc).to_track_quat("-Z", "Y").to_matrix()
        inv = rot.transposed()
        for c in corners:
            p = inv @ (c - loc)
            if p.z >= -0.05:
                return False, loc, rot
            sx = p.x / -p.z / half_w
            sy = p.y / -p.z / half_h - data.shift_y * 2 * aspect
            if abs(sx) > 1 - margin or abs(sy) > 1 - margin:
                return False, loc, rot
        return True, loc, rot

    if spec.get("distance"):
        _, loc, rot = fits(spec["distance"])
    else:
        a, b = 1.0, 200.0
        for _ in range(40):
            mid = (a + b) / 2
            if fits(mid)[0]:
                b = mid
            else:
                a = mid
        _, loc, rot = fits(b)
    cam.location = loc
    cam.rotation_euler = rot.to_euler()
    if spec.get("fstop"):
        data.dof.use_dof = True
        data.dof.focus_distance = (t - loc).length
        data.dof.aperture_fstop = spec["fstop"]
    bpy.context.scene.camera = cam
    return {"location": [round(c, 3) for c in loc], "target": [round(c, 3) for c in t],
            "lens": data.lens, "distance": round((t - loc).length, 3), "fstop": spec.get("fstop")}


# ------------------------------------------------------------------ render settings

def configure_render(profile):
    """Apply a render profile from config/render.json (keys documented there)."""
    scene = bpy.context.scene
    r = scene.render
    r.resolution_x, r.resolution_y = profile["resolution"]
    r.resolution_percentage = profile.get("resolution_percentage", 100)
    r.image_settings.file_format = "PNG"
    r.image_settings.color_mode = "RGB"
    r.film_transparent = False
    r.engine = profile["engine"]
    if profile["engine"] == "BLENDER_EEVEE":
        ee = scene.eevee
        ee.taa_render_samples = profile["samples"]
        ee.use_soft_shadows = True
        ee.shadow_cascade_size = profile.get("shadow_cascade_size", "4096")
        ee.shadow_cube_size = "1024"
        ee.use_shadow_high_bitdepth = True
        ee.use_gtao = True
        ee.gtao_distance = 0.8
        ee.gtao_factor = 1.2
        ee.use_gtao_bent_normals = True
        ee.use_ssr = True
        ee.use_ssr_refraction = True
        ee.use_ssr_halfres = False
        ee.ssr_quality = 0.75
        ee.ssr_thickness = 0.05
        ee.use_bloom = profile.get("bloom", True)
        ee.bloom_threshold = 1.2
        ee.bloom_intensity = 0.03
        ee.bloom_radius = 4.0
        ee.gi_diffuse_bounces = 2
        ee.use_motion_blur = False
        ee.bokeh_max_size = 40
    elif profile["engine"] == "CYCLES":
        c = scene.cycles
        c.device = profile.get("device", "CPU")
        c.samples = profile["samples"]
        c.use_adaptive_sampling = profile.get("adaptive", True)
        c.adaptive_threshold = profile.get("adaptive_threshold", 0.02)
        c.adaptive_min_samples = profile.get("adaptive_min_samples", 0)
        c.use_denoising = profile.get("denoise", True)
        c.denoiser = "OPENIMAGEDENOISE"
        c.denoising_input_passes = "RGB_ALBEDO_NORMAL"
        c.denoising_prefilter = "ACCURATE"
        c.seed = 0
        c.max_bounces = profile.get("max_bounces", 8)
        c.diffuse_bounces = profile.get("diffuse_bounces", 3)
        c.glossy_bounces = profile.get("glossy_bounces", 4)
        c.transmission_bounces = 6
        c.transparent_max_bounces = 8
        c.caustics_reflective = False
        c.caustics_refractive = False
        c.blur_glossy = profile.get("filter_glossy", 0.5)
        c.sample_clamp_indirect = profile.get("clamp_indirect", 10.0)
        c.use_light_tree = True
        r.use_persistent_data = True
        c.tile_size = 2048
        scene.render.threads_mode = "AUTO"
    else:
        raise PipelineError(f"unsupported render engine {profile['engine']}")
    if profile.get("post"):
        setup_post(scene, profile)
    vs = scene.view_settings
    vs.view_transform = profile.get("view_transform", "Filmic")
    vs.look = profile.get("look", "Medium High Contrast")
    vs.exposure = profile.get("exposure", 0.0)
    vs.gamma = 1.0
    scene.display_settings.display_device = "sRGB"
    r.filter_size = profile.get("filter_size", 1.5)
    return profile


def setup_post(scene, profile):
    """Photographic finishing in the compositor: soft glare on lamps, faint lateral chromatic
    aberration, gentle vignette. Strengths from profile['post'] (dict) or defaults."""
    post = profile["post"] if isinstance(profile["post"], dict) else {}
    scene.use_nodes = True
    scene.render.use_compositing = True
    nt = scene.node_tree
    for n in list(nt.nodes):
        nt.nodes.remove(n)
    L = nt.links
    rl = nt.nodes.new("CompositorNodeRLayers")
    glare = nt.nodes.new("CompositorNodeGlare")
    glare.glare_type = "FOG_GLOW"
    glare.quality = "HIGH"
    glare.threshold = post.get("glare_threshold", 1.5)
    glare.mix = post.get("glare_mix", -0.85)
    glare.size = 7
    lens = nt.nodes.new("CompositorNodeLensdist")
    lens.use_fit = True
    lens.inputs["Distort"].default_value = post.get("distortion", 0.0)
    lens.inputs["Dispersion"].default_value = post.get("dispersion", 0.006)
    mask = nt.nodes.new("CompositorNodeEllipseMask")
    mask.width, mask.height = 1.05, 1.05
    blur = nt.nodes.new("CompositorNodeBlur")
    blur.use_relative = True
    blur.factor_x = blur.factor_y = 35.0
    blur.filter_type = "GAUSS"
    lift = nt.nodes.new("CompositorNodeMath")            # mask 0..1 -> (1 - v)..1
    lift.operation = "MULTIPLY_ADD"
    v = post.get("vignette", 0.22)
    lift.inputs[1].default_value = v
    lift.inputs[2].default_value = 1.0 - v
    lift.use_clamp = True
    mul = nt.nodes.new("CompositorNodeMixRGB")
    mul.blend_type = "MULTIPLY"
    mul.inputs["Fac"].default_value = 1.0
    comp = nt.nodes.new("CompositorNodeComposite")
    L.new(rl.outputs["Image"], glare.inputs["Image"])
    L.new(glare.outputs["Image"], lens.inputs["Image"])
    L.new(mask.outputs["Mask"], blur.inputs["Image"])
    L.new(blur.outputs["Image"], lift.inputs[0])
    L.new(lens.outputs["Image"], mul.inputs[1])
    L.new(lift.outputs[0], mul.inputs[2])
    L.new(mul.outputs["Image"], comp.inputs["Image"])


def resolve_profile(render_cfg, name):
    profiles = render_cfg["profiles"]
    if name not in profiles:
        raise PipelineError(f"unknown render profile '{name}' (have {', '.join(sorted(profiles))})")
    return dict(profiles[name])
