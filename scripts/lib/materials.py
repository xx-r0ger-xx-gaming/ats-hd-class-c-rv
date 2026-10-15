"""Render-only material factory (Cycles + Eevee). Never used for exported game materials.

    mats = MaterialLibrary(paint_spec)      # paint_spec: {"base_color", "metallic", "roughness", ...}
    mats["paint"]                           # body paint, colour-matched to paint_spec (truck + camper)
    mats["glass"], mats["trim"], ...        # standard library, created lazily on first use
    mats.car_paint("pv_red", (0.4,0.02,0.02,1))   # extra paints (stripes, two-tone)
    mats.principled("my_mat", base_color=(..), roughness=.., metallic=..)

Standard keys (see KEYS): paint, paint_dark, glass (thin tinted pane: put it on a single face in
front of a hollow interior), glass_light (windshield/front side tint), glass_flush (opaque dark
glazing for pocket "floors" on solid bodies), glass_clear, interior, trim, trim_gloss, rubber, tire,
chrome, alloy, alloy_dark, steel, lamp_red, lamp_red_lens, lamp_amber, lamp_clear, led_white,
reflector, plate, underbody, frame, bed_liner, decal_black, fabric, wood, plastic_white.
Ground: asphalt, lane_white, lane_yellow, gravel, grass (built by lib/environment.py).

Every material created here gets mat["render_role"] = key so render scripts can find them.
"""
import bpy

KEYS = (
    "paint", "paint_dark", "glass", "glass_light", "glass_flush", "glass_clear", "interior", "trim", "trim_gloss", "rubber", "tire", "chrome",
    "alloy", "alloy_dark", "steel", "lamp_red", "lamp_red_lens", "lamp_amber", "lamp_clear",
    "led_white", "reflector", "plate", "underbody", "frame", "bed_liner", "decal_black", "fabric",
    "wood", "plastic_white", "glass_tint", "curtain", "canvas", "canvas_mesh", "seal",
)

DEFAULT_PAINT = {"base_color": [0.52, 0.54, 0.56, 1.0], "metallic": 0.55, "roughness": 0.32,
                 "clearcoat": 0.6, "clearcoat_roughness": 0.05}


def _new(name):
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    nt = mat.node_tree
    return mat, nt.nodes, nt.links, nt.nodes["Principled BSDF"]


def _set(b, **kw):
    names = {"base_color": "Base Color", "metallic": "Metallic", "roughness": "Roughness",
             "specular": "Specular", "clearcoat": "Clearcoat", "clearcoat_roughness": "Clearcoat Roughness",
             "sheen": "Sheen", "transmission": "Transmission", "ior": "IOR", "alpha": "Alpha",
             "emission": "Emission", "emission_strength": "Emission Strength", "coat": "Clearcoat",
             "anisotropic": "Anisotropic", "subsurface": "Subsurface"}
    for k, v in kw.items():
        if v is None:
            continue
        sock = b.inputs[names[k]]
        if k in ("base_color", "emission") and len(v) == 3:
            v = (*v, 1.0)
        sock.default_value = v


def _noise(nodes, links, scale, detail=6.0, coord="Object", rough=0.55):
    tc = nodes.new("ShaderNodeTexCoord")
    n = nodes.new("ShaderNodeTexNoise")
    n.inputs["Scale"].default_value = scale
    n.inputs["Detail"].default_value = detail
    n.inputs["Roughness"].default_value = rough
    links.new(tc.outputs[coord], n.inputs["Vector"])
    return n


def _bump(nodes, links, height_socket, strength, distance=0.01):
    bump = nodes.new("ShaderNodeBump")
    bump.inputs["Strength"].default_value = strength
    bump.inputs["Distance"].default_value = distance
    links.new(height_socket, bump.inputs["Height"])
    return bump


def _ramp(nodes, links, fac_socket, stops):
    r = nodes.new("ShaderNodeValToRGB")
    els = r.color_ramp.elements
    els[0].position, els[0].color = stops[0][0], _rgba(stops[0][1])
    els[1].position, els[1].color = stops[-1][0], _rgba(stops[-1][1])
    for pos, col in stops[1:-1]:
        e = els.new(pos)
        e.color = _rgba(col)
    links.new(fac_socket, r.inputs["Fac"])
    return r


def _rgba(c):
    if isinstance(c, (int, float)):
        return (c, c, c, 1.0)
    return (*c, 1.0) if len(c) == 3 else tuple(c)


def _value_ramp(nodes, links, fac_socket, lo, hi):
    """Map a 0..1 factor to lo..hi (Map Range)."""
    m = nodes.new("ShaderNodeMapRange")
    m.inputs["To Min"].default_value = lo
    m.inputs["To Max"].default_value = hi
    links.new(fac_socket, m.inputs["Value"])
    return m.outputs["Result"]


class MaterialLibrary:
    """Lazy material dictionary; see module docstring for keys."""

    def __init__(self, paint_spec=None, prefix="rv_"):
        self.paint_spec = dict(DEFAULT_PAINT, **(paint_spec or {}))
        self.prefix = prefix
        self.ground_z = None      # set by build_truck (world z of the road) -> enables road dust
        self._cache = {}

    def __contains__(self, key):
        return key in KEYS or key in self._cache

    def __getitem__(self, key):
        if key not in self._cache:
            maker = getattr(self, "_m_" + key, None)
            if maker is None:
                raise KeyError(f"unknown material key '{key}' (known: {', '.join(KEYS)})")
            mat = maker(self.prefix + key)
            mat["render_role"] = key
            self._cache[key] = mat
        return self._cache[key]

    def get(self, key, default=None):
        try:
            return self[key]
        except KeyError:
            return default

    def add(self, key, mat):
        """Register a custom material so Part(..., mats) can use it by key."""
        mat["render_role"] = key
        self._cache[key] = mat
        return mat

    # ---------------------------------------------------------- public factories

    def principled(self, name, **kw):
        mat, nodes, links, b = _new(name)
        _set(b, **kw)
        if "base_color" in kw:
            mat.diffuse_color = _rgba(kw["base_color"])
        return mat

    def car_paint(self, name, base_color, metallic=0.6, roughness=0.3, clearcoat=1.0,
                  clearcoat_roughness=0.03, flake=0.25, flake_scale=2500.0, dirt=0.0):
        """Metallic base + clearcoat; metallic flake via a fine voronoi normal perturbation, a whisper
        of orange peel on the coat. flake=0 gives a solid (non-metallic) paint look."""
        mat, nodes, links, b = _new(name)
        bc = _rgba(base_color)
        _set(b, base_color=bc, metallic=metallic, roughness=roughness, clearcoat=clearcoat,
             clearcoat_roughness=clearcoat_roughness, specular=0.5)
        if flake > 0:
            tc = nodes.new("ShaderNodeTexCoord")
            vor = nodes.new("ShaderNodeTexVoronoi")
            vor.inputs["Scale"].default_value = flake_scale
            links.new(tc.outputs["Object"], vor.inputs["Vector"])
            # random flake orientations -> normal map with tiny strength
            sep = nodes.new("ShaderNodeMixRGB")
            sep.blend_type = "MIX"
            sep.inputs["Fac"].default_value = flake
            sep.inputs["Color1"].default_value = (0.5, 0.5, 1.0, 1.0)
            links.new(vor.outputs["Color"], sep.inputs["Color2"])
            nmap = nodes.new("ShaderNodeNormalMap")
            nmap.inputs["Strength"].default_value = 0.08
            links.new(sep.outputs["Color"], nmap.inputs["Color"])
            links.new(nmap.outputs["Normal"], b.inputs["Normal"])
            # flakes also vary the base brightness a touch
            hsv = nodes.new("ShaderNodeHueSaturation")
            hsv.inputs["Color"].default_value = bc
            links.new(_value_ramp(nodes, links, vor.outputs["Distance"], 1.08, 0.94), hsv.inputs["Value"])
            links.new(hsv.outputs["Color"], b.inputs["Base Color"])
            # flakes = tiny mirrors: per-cell roughness spread gives the base coat its sparkle
            links.new(_value_ramp(nodes, links, vor.outputs["Distance"], roughness * 0.55, roughness * 1.25),
                      b.inputs["Roughness"])
        if dirt > 0 and self.ground_z is not None:
            self._add_dirt(nodes, links, b, bc, roughness, clearcoat, dirt)
        peel = _noise(nodes, links, 180.0, 2.0)
        bump = _bump(nodes, links, peel.outputs["Fac"], 0.015, 0.002)
        links.new(bump.outputs["Normal"], b.inputs["Clearcoat Normal"])
        if clearcoat > 0.05:
            self._add_coat(nodes, links, b, clearcoat, clearcoat_roughness, bump.outputs["Normal"])
        mat.diffuse_color = bc
        mat.metallic = metallic
        mat.roughness = roughness
        return mat

    def _add_coat(self, nodes, links, b, strength, rough, normal):
        """Real clearcoat: a sharp dielectric glossy layer (IOR 1.5 Fresnel) over the base shader.
        Principled's own Clearcoat lobe is too weak to read as wet paint; this mirrors the HDRI."""
        out = nodes["Material Output"]
        gl = nodes.new("ShaderNodeBsdfGlossy")
        gl.distribution = "GGX"
        gl.inputs["Roughness"].default_value = max(min(rough, 0.2), 0.0)
        links.new(normal, gl.inputs["Normal"])
        fr = nodes.new("ShaderNodeFresnel")
        fr.inputs["IOR"].default_value = 1.5
        links.new(normal, fr.inputs["Normal"])
        k = nodes.new("ShaderNodeMath")
        k.operation = "MULTIPLY"
        k.use_clamp = True
        k.inputs[1].default_value = strength
        links.new(fr.outputs["Fac"], k.inputs[0])
        mix = nodes.new("ShaderNodeMixShader")
        links.new(k.outputs[0], mix.inputs["Fac"])
        links.new(b.outputs["BSDF"], mix.inputs[1])
        links.new(gl.outputs["BSDF"], mix.inputs[2])
        links.new(mix.outputs["Shader"], out.inputs["Surface"])
        b.inputs["Clearcoat"].default_value = min(b.inputs["Clearcoat"].default_value, 0.3)

    def _add_dirt(self, nodes, links, b, bc, roughness, clearcoat, amount):
        """Road dust on the lower body: fades out ~0.9 m above the road (world Z), noisy edge."""
        src = b.inputs["Base Color"].links[0].from_socket if b.inputs["Base Color"].is_linked else None
        geo = nodes.new("ShaderNodeNewGeometry")
        sep = nodes.new("ShaderNodeSeparateXYZ")
        links.new(geo.outputs["Position"], sep.inputs["Vector"])
        g = self.ground_z
        h = nodes.new("ShaderNodeMapRange")
        h.inputs["From Min"].default_value = g + 0.15
        h.inputs["From Max"].default_value = g + 1.05
        h.inputs["To Min"].default_value = 1.0
        h.inputs["To Max"].default_value = 0.0
        links.new(sep.outputs["Z"], h.inputs["Value"])
        n = nodes.new("ShaderNodeTexNoise")
        n.inputs["Scale"].default_value = 3.0
        n.inputs["Detail"].default_value = 10.0
        n.inputs["Roughness"].default_value = 0.65
        links.new(geo.outputs["Position"], n.inputs["Vector"])
        nr = nodes.new("ShaderNodeMapRange")
        nr.inputs["From Min"].default_value = 0.35
        nr.inputs["From Max"].default_value = 0.65
        links.new(n.outputs["Fac"], nr.inputs["Value"])
        m1 = nodes.new("ShaderNodeMath")
        m1.operation = "MULTIPLY"
        links.new(h.outputs["Result"], m1.inputs[0])
        links.new(nr.outputs["Result"], m1.inputs[1])
        m2 = nodes.new("ShaderNodeMath")
        m2.operation = "MULTIPLY"
        m2.use_clamp = True
        links.new(m1.outputs[0], m2.inputs[0])
        m2.inputs[1].default_value = amount
        mix = nodes.new("ShaderNodeMixRGB")
        links.new(m2.outputs[0], mix.inputs["Fac"])
        if src is not None:
            links.new(src, mix.inputs["Color1"])
        else:
            mix.inputs["Color1"].default_value = bc
        mix.inputs["Color2"].default_value = (0.30, 0.255, 0.19, 1.0)
        links.new(mix.outputs["Color"], b.inputs["Base Color"])
        for sock, lo, hi in (("Roughness", roughness, 0.75), ("Clearcoat", clearcoat, 0.15),
                             ("Metallic", b.inputs["Metallic"].default_value, 0.0)):
            mr = nodes.new("ShaderNodeMapRange")
            mr.inputs["To Min"].default_value = lo
            mr.inputs["To Max"].default_value = hi
            links.new(m2.outputs[0], mr.inputs["Value"])
            links.new(mr.outputs["Result"], b.inputs[sock])

    def paint_from_spec(self, name, spec):
        return self.car_paint(name, spec["base_color"], metallic=max(spec.get("metallic", 0.0), 0.0),
                              roughness=spec.get("render_roughness", spec.get("roughness", 0.3)),
                              clearcoat=max(spec.get("clearcoat", 0.0), 0.8),
                              clearcoat_roughness=spec.get("clearcoat_roughness", 0.03),
                              flake=spec.get("flake", 0.25 if spec.get("metallic", 0.0) > 0.2 else 0.0),
                              dirt=spec.get("dirt", 0.65))

    # ---------------------------------------------------------- standard library

    def _m_paint(self, name):
        return self.paint_from_spec(name, self.paint_spec)

    def _m_paint_dark(self, name):
        return self.car_paint(name, (0.02, 0.022, 0.025, 1), metallic=0.4, roughness=0.35, flake=0.15)

    def thin_glass(self, name, tint, reflect=1.0):
        """Single-face glazing: tinted Transparent mixed with a sharp Glossy by Fresnel (IOR 1.5).
        Works in Cycles and Eevee (alpha blend); shadows pass through (tinted)."""
        mat = bpy.data.materials.new(name)
        mat.use_nodes = True
        nt = mat.node_tree
        nodes, links = nt.nodes, nt.links
        nodes.remove(nodes["Principled BSDF"])
        out = nodes["Material Output"]
        tr = nodes.new("ShaderNodeBsdfTransparent")
        tr.inputs["Color"].default_value = _rgba(tint)
        gl = nodes.new("ShaderNodeBsdfGlossy")
        gl.inputs["Roughness"].default_value = 0.0
        gl.inputs["Color"].default_value = (reflect, reflect, reflect, 1)
        fr = nodes.new("ShaderNodeFresnel")
        fr.inputs["IOR"].default_value = 1.52
        mix = nodes.new("ShaderNodeMixShader")
        links.new(fr.outputs["Fac"], mix.inputs["Fac"])
        links.new(tr.outputs["BSDF"], mix.inputs[1])
        links.new(gl.outputs["BSDF"], mix.inputs[2])
        links.new(mix.outputs["Shader"], out.inputs["Surface"])
        mat.blend_method = "BLEND"
        mat.shadow_method = "HASHED"
        mat.use_backface_culling = False
        mat.show_transparent_back = True
        mat.diffuse_color = (*_rgba(tint)[:3], 0.5)
        return mat

    def _m_glass_tint(self, name):
        """Camper glazing over a real interior pocket: smoked (~13 % transmission), crisp reflections.
        A small reflectance floor on top of Fresnel keeps sky/horizon reflections visible head-on."""
        mat = self.thin_glass(name, (0.125, 0.135, 0.14), reflect=1.0)
        nodes, links = mat.node_tree.nodes, mat.node_tree.links
        fr = next(n for n in nodes if n.bl_idname == "ShaderNodeFresnel")
        mix = next(n for n in nodes if n.bl_idname == "ShaderNodeMixShader")
        fr.inputs["IOR"].default_value = 1.6
        m = nodes.new("ShaderNodeMapRange")
        m.inputs["To Min"].default_value = 0.12
        m.inputs["To Max"].default_value = 1.0
        links.new(fr.outputs["Fac"], m.inputs["Value"])
        links.new(m.outputs["Result"], mix.inputs["Fac"])
        return mat

    def _m_curtain(self, name):
        """Interior behind camper glass: pleated warm-grey curtain fabric (diagonal object-space bands
        so pleats show on side and end walls alike)."""
        mat, nodes, links, b = _new(name)
        tc = nodes.new("ShaderNodeTexCoord")
        wave = nodes.new("ShaderNodeTexWave")
        wave.wave_type = "BANDS"
        wave.bands_direction = "DIAGONAL"
        wave.inputs["Scale"].default_value = 9.0
        wave.inputs["Distortion"].default_value = 1.5
        links.new(tc.outputs["Object"], wave.inputs["Vector"])
        col = _ramp(nodes, links, wave.outputs["Fac"], [(0.0, (0.07, 0.065, 0.058)), (1.0, (0.20, 0.19, 0.17))])
        links.new(col.outputs["Color"], b.inputs["Base Color"])
        bump = _bump(nodes, links, wave.outputs["Fac"], 0.5, 0.01)
        links.new(bump.outputs["Normal"], b.inputs["Normal"])
        _set(b, roughness=0.9, sheen=0.6, specular=0.2)
        mat.diffuse_color = (0.14, 0.13, 0.12, 1)
        return mat

    def canvas_material(self, name, color, wrinkle=1.0):
        """Tent canvas: woven micro bump, larger soft wrinkles, slight colour mottling and sheen."""
        mat, nodes, links, b = _new(name)
        weave = _noise(nodes, links, 900.0, 2.0)
        tc = nodes.new("ShaderNodeTexCoord")
        chk = nodes.new("ShaderNodeTexChecker")
        chk.inputs["Scale"].default_value = 450.0
        links.new(tc.outputs["Object"], chk.inputs["Vector"])
        wr = _noise(nodes, links, 7.0, 4.0, rough=0.5)
        wr2 = _noise(nodes, links, 22.0, 2.0)
        add = nodes.new("ShaderNodeMath")
        add.operation = "ADD"
        links.new(wr.outputs["Fac"], add.inputs[0])
        links.new(wr2.outputs["Fac"], add.inputs[1])
        b1 = _bump(nodes, links, add.outputs[0], 0.35 * wrinkle, 0.03)
        b2 = _bump(nodes, links, chk.outputs["Fac"], 0.12, 0.0006)
        links.new(b1.outputs["Normal"], b2.inputs["Normal"])
        b3 = _bump(nodes, links, weave.outputs["Fac"], 0.1, 0.0008)
        links.new(b2.outputs["Normal"], b3.inputs["Normal"])
        links.new(b3.outputs["Normal"], b.inputs["Normal"])
        c = _rgba(color)
        dark = tuple(v * 0.75 for v in c[:3])
        lite = tuple(min(v * 1.25, 1.0) for v in c[:3])
        mot = _noise(nodes, links, 3.0, 3.0)
        cr = _ramp(nodes, links, mot.outputs["Fac"], [(0.3, dark), (0.7, lite)])
        links.new(cr.outputs["Color"], b.inputs["Base Color"])
        _set(b, roughness=0.88, sheen=0.8, specular=0.25)
        mat.diffuse_color = c
        return mat

    def _m_canvas(self, name):
        return self.canvas_material(name, (0.055, 0.058, 0.045))

    def _m_canvas_mesh(self, name):
        """No-see-um mesh window: fine dark grid with a soft sheen."""
        mat, nodes, links, b = _new(name)
        tc = nodes.new("ShaderNodeTexCoord")
        chk = nodes.new("ShaderNodeTexChecker")
        chk.inputs["Scale"].default_value = 1400.0
        links.new(tc.outputs["Object"], chk.inputs["Vector"])
        bump = _bump(nodes, links, chk.outputs["Fac"], 0.25, 0.0004)
        links.new(bump.outputs["Normal"], b.inputs["Normal"])
        _set(b, base_color=(0.004, 0.004, 0.0045, 1), roughness=0.6, specular=0.3, sheen=0.25)
        mat.diffuse_color = (0.006, 0.006, 0.007, 1)
        return mat

    def _m_seal(self, name):
        """Window/door rubber seal: black EPDM, satin."""
        return self.principled(name, base_color=(0.008, 0.008, 0.009, 1), roughness=0.45, specular=0.45)

    def _m_glass(self, name):
        return self.thin_glass(name, (0.10, 0.11, 0.115))

    def _m_glass_light(self, name):
        return self.thin_glass(name, (0.42, 0.45, 0.46))

    def _m_interior(self, name):
        """Dark grey cabin trim/headliner."""
        return self.principled(name, base_color=(0.035, 0.034, 0.033, 1), roughness=0.8, sheen=0.3)

    def _m_glass_flush(self, name):
        """Tinted privacy glass, opaque (glazing sits on closed solids): dark, sharp, fresnel reflection."""
        mat, nodes, links, b = _new(name)
        _set(b, base_color=(0.006, 0.007, 0.008, 1), roughness=0.0, specular=0.9, metallic=0.0,
             clearcoat=1.0, clearcoat_roughness=0.0)
        mat.diffuse_color = (0.01, 0.012, 0.015, 1)
        mat.roughness = 0.02
        return mat

    def _m_glass_clear(self, name):
        mat, nodes, links, b = _new(name)
        _set(b, base_color=(0.9, 0.93, 0.95, 1), roughness=0.0, transmission=1.0, ior=1.5)
        mat.blend_method = "BLEND"
        mat.use_screen_refraction = True
        mat.show_transparent_back = False
        return mat

    def _m_trim(self, name):
        """Satin black textured plastic (bumpers, cladding, gaskets, mirror caps)."""
        mat, nodes, links, b = _new(name)
        n = _noise(nodes, links, 900.0, 3.0)
        bump = _bump(nodes, links, n.outputs["Fac"], 0.12, 0.001)
        links.new(bump.outputs["Normal"], b.inputs["Normal"])
        _set(b, base_color=(0.012, 0.012, 0.013, 1), roughness=0.55, specular=0.4)
        mat.diffuse_color = (0.012, 0.012, 0.013, 1)
        return mat

    def _m_trim_gloss(self, name):
        return self.principled(name, base_color=(0.006, 0.006, 0.007, 1), roughness=0.12, clearcoat=0.6)

    def _m_rubber(self, name):
        return self.principled(name, base_color=(0.01, 0.01, 0.01, 1), roughness=0.8, specular=0.3)

    def _m_tire(self, name):
        """Rubber with dusty variation and micro bump; roughness varies, sidewall reads dark grey."""
        mat, nodes, links, b = _new(name)
        n = _noise(nodes, links, 40.0, 8.0)
        col = _ramp(nodes, links, n.outputs["Fac"], [(0.35, (0.016, 0.016, 0.016)), (0.75, (0.034, 0.032, 0.03))])
        links.new(col.outputs["Color"], b.inputs["Base Color"])
        links.new(_value_ramp(nodes, links, n.outputs["Fac"], 0.62, 0.86), b.inputs["Roughness"])
        fine = _noise(nodes, links, 1500.0, 2.0)
        bump = _bump(nodes, links, fine.outputs["Fac"], 0.2, 0.001)
        links.new(bump.outputs["Normal"], b.inputs["Normal"])
        _set(b, specular=0.35)
        mat.diffuse_color = (0.02, 0.02, 0.02, 1)
        return mat

    def _m_chrome(self, name):
        return self.principled(name, base_color=(0.90, 0.91, 0.93, 1), metallic=1.0, roughness=0.07)

    def _m_alloy(self, name):
        """Brushed/machined aluminium (anisotropic-ish via stretched noise in roughness)."""
        mat, nodes, links, b = _new(name)
        tc = nodes.new("ShaderNodeTexCoord")
        mp = nodes.new("ShaderNodeMapping")
        mp.inputs["Scale"].default_value = (600.0, 4.0, 4.0)
        links.new(tc.outputs["Object"], mp.inputs["Vector"])
        n = nodes.new("ShaderNodeTexNoise")
        n.inputs["Scale"].default_value = 1.0
        links.new(mp.outputs["Vector"], n.inputs["Vector"])
        links.new(_value_ramp(nodes, links, n.outputs["Fac"], 0.12, 0.26), b.inputs["Roughness"])
        _set(b, base_color=(0.80, 0.81, 0.83, 1), metallic=1.0, anisotropic=0.5, clearcoat=0.3)
        mat.diffuse_color = (0.7, 0.7, 0.72, 1)
        return mat

    def _m_alloy_dark(self, name):
        """Painted gunmetal wheel finish (metallic paint + coat)."""
        return self.car_paint(name, (0.07, 0.075, 0.08, 1), metallic=0.75, roughness=0.32, clearcoat=0.7,
                              clearcoat_roughness=0.08, flake=0.2)

    def _m_steel(self, name):
        return self.principled(name, base_color=(0.45, 0.45, 0.46, 1), metallic=1.0, roughness=0.38)

    def _lamp(self, name, color, strength, rough=0.08):
        mat, nodes, links, b = _new(name)
        _set(b, base_color=color, emission=color, emission_strength=strength, roughness=rough,
             clearcoat=1.0, clearcoat_roughness=0.02, specular=0.6)
        mat.diffuse_color = _rgba(color)
        return mat

    def _m_lamp_red(self, name):
        return self._lamp(name, (0.75, 0.02, 0.012, 1), 4.0)

    def _m_lamp_red_lens(self, name):
        """Unlit red outer lens: deep red, glossy."""
        return self._lamp(name, (0.32, 0.008, 0.006, 1), 0.25, rough=0.05)

    def _m_lamp_amber(self, name):
        return self._lamp(name, (0.8, 0.32, 0.02, 1), 0.3)

    def _m_lamp_clear(self, name):
        """Clear headlamp lens over a reflector: glossy pale grey-blue."""
        return self.principled(name, base_color=(0.55, 0.58, 0.62, 1), metallic=0.85, roughness=0.06,
                               clearcoat=1.0, clearcoat_roughness=0.0)

    def _m_led_white(self, name):
        return self._lamp(name, (0.95, 0.97, 1.0, 1), 6.0)

    def _m_reflector(self, name):
        return self.principled(name, base_color=(0.85, 0.86, 0.88, 1), metallic=1.0, roughness=0.12)

    def _m_plate(self, name):
        return self.principled(name, base_color=(0.80, 0.80, 0.78, 1), roughness=0.45, metallic=0.2)

    def _m_underbody(self, name):
        return self.principled(name, base_color=(0.012, 0.012, 0.013, 1), roughness=0.9)

    def _m_frame(self, name):
        """Black e-coated frame steel: semi-gloss."""
        return self.principled(name, base_color=(0.015, 0.015, 0.016, 1), roughness=0.4, metallic=0.3)

    def _m_bed_liner(self, name):
        mat, nodes, links, b = _new(name)
        n = _noise(nodes, links, 300.0, 4.0)
        bump = _bump(nodes, links, n.outputs["Fac"], 0.35, 0.002)
        links.new(bump.outputs["Normal"], b.inputs["Normal"])
        _set(b, base_color=(0.018, 0.018, 0.019, 1), roughness=0.85)
        return mat

    def _m_decal_black(self, name):
        return self.principled(name, base_color=(0.01, 0.01, 0.011, 1), roughness=0.3, clearcoat=0.8)

    def _m_fabric(self, name):
        return self.principled(name, base_color=(0.03, 0.03, 0.032, 1), roughness=0.95, sheen=0.5)

    def _m_wood(self, name):
        return self.principled(name, base_color=(0.35, 0.22, 0.12, 1), roughness=0.5)

    def _m_plastic_white(self, name):
        return self.principled(name, base_color=(0.78, 0.78, 0.76, 1), roughness=0.35, clearcoat=0.3)


def game_role_map(mats):
    """Map exported-shell material roles (mat['camper_role']) to library materials."""
    return {"body_paint": mats["paint"], "glass": mats["glass"], "trim": mats["trim"],
            "lamp": mats["lamp_red_lens"]}


def upgrade_game_materials(objects, mats):
    """Render-only: swap game materials (by camper_role) for render materials on given objects.

    Changes only the in-memory scene; render scripts never save the .blend.
    """
    roles = game_role_map(mats)
    for ob in objects:
        if ob.type != "MESH":
            continue
        for slot in ob.material_slots:
            m = slot.material
            if m is not None and m.get("camper_role") in roles:
                slot.link = "OBJECT"
                slot.material = roles[m["camper_role"]]
