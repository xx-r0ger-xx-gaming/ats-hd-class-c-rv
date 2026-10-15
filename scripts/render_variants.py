"""Render camper variants, each on its own stand-in truck. Render-only; nothing is saved or exported.

  blender --background --factory-startup --python-exit-code 1 --python scripts/render_variants.py -- \
      --variant v1_shell [--variant other ...] | --all
      [--profile surface|surface-photo|gaming] [--views rear34,side,front34] [--no-sheet]
      [--set camper.state="closed" ...] [--suffix _closed]
      [--save-blend build/variants/<name>.blend]   (debug: save the staged scene, single variant)

Poses: a variant config may list "renders": [{"suffix": "", "set": {}}, {"suffix": "_closed",
"set": {"camper.state": "closed"}}]; each entry is rendered as <name><suffix>_<view>.png.
--set key.path=value (repeatable, value JSON-parsed, plain string if not valid JSON) and/or
--suffix replace that list with a single pose built from the command line.

Per variant (config/variants/<name>.json):
  1. builds the proxy truck (lib/proxy_truck.py, pickup or cab_chassis per cfg["truck"]),
  2. calls variants.<camper.module>.build(cfg, collection, mats) with the colour-matched library,
  3. stages HDRI world + sun, road and ground (config/render.json),
  4. renders each view to renders/variants/<name>_<view>.png (auto-framed cameras),
then rebuilds renders/variants/contact_sheet.png from every <name>_<view>.png present.
A render is not proof of a working mod.
"""
import copy
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import bpy  # noqa: E402

import variants  # noqa: E402
from lib.common import (  # noqa: E402
    REPO_ROOT, PipelineError, load_json, make_parser, repo_path, run_main, script_args, sha256_file,
    write_run_record,
)
from lib.contact_sheet import make_contact_sheet  # noqa: E402
from lib.environment import (  # noqa: E402
    add_ground, configure_render, load_render_config, place_camera, resolve_profile, setup_world,
    world_bbox,
)
from lib.materials import MaterialLibrary  # noqa: E402
from lib.proxy_truck import build_truck  # noqa: E402

VARIANT_DIR = "config/variants"
OUT_DIR = "renders/variants"
DEFAULT_VIEWS = ("rear34", "side", "front34")


def resolve_ref(ref):
    """'path/to.json#a.b.c' -> value; dicts pass through."""
    if isinstance(ref, dict):
        return ref
    path, _, keys = ref.partition("#")
    val = load_json(path)
    for k in filter(None, keys.split(".")):
        if k not in val:
            raise PipelineError(f"paint reference {ref}: key '{k}' not found")
        val = val[k]
    return val


def parse_value(text):
    try:
        return json.loads(text)
    except ValueError:
        return text


def parse_sets(items):
    """['a.b=1', 'c="x"'] -> {'a.b': 1, 'c': 'x'}."""
    out = {}
    for item in items:
        key, eq, val = item.partition("=")
        if not eq or not key.strip():
            raise PipelineError(f"--set expects key.path=value, got {item!r}")
        out[key.strip()] = parse_value(val)
    return out


def apply_sets(cfg, sets):
    """Set dotted keys in cfg (creating intermediate dicts). Returns cfg."""
    for path, val in (sets or {}).items():
        keys = path.split(".")
        node = cfg
        for k in keys[:-1]:
            if not isinstance(node.get(k), dict):
                node[k] = {}
            node = node[k]
        node[keys[-1]] = copy.deepcopy(val)
    return cfg


def poses_for(cfg):
    """Pose list from cfg["renders"] (default: one pose, no suffix, no overrides)."""
    poses = cfg.get("renders") or [{"suffix": "", "set": {}}]
    for p in poses:
        if not isinstance(p, dict) or not isinstance(p.get("set", {}), dict):
            raise PipelineError(f"variant {cfg.get('name')}: bad 'renders' entry {p!r}")
    return [{"suffix": p.get("suffix", ""), "set": dict(p.get("set", {}))} for p in poses]


def load_variant(name, sets=None):
    cfg = apply_sets(load_json(f"{VARIANT_DIR}/{name}.json"), sets)
    for key in ("camper", "truck"):
        if key not in cfg:
            raise PipelineError(f"{VARIANT_DIR}/{name}.json: missing '{key}'")
    if "module" not in cfg["camper"]:
        raise PipelineError(f"{VARIANT_DIR}/{name}.json: camper.module missing")
    cfg.setdefault("name", name)
    cfg["paint_spec"] = resolve_ref(cfg.get("paint", {"base_color": [0.52, 0.54, 0.56, 1.0]}))
    return cfg


def all_variants():
    """Every config/variants/*.json except reference configs whose name starts with '_'."""
    return sorted(p.stem for p in repo_path(VARIANT_DIR).glob("*.json") if not p.stem.startswith("_"))


def new_collection(name):
    col = bpy.data.collections.new(name)
    bpy.context.scene.collection.children.link(col)
    return col


def stage_variant(name, rcfg, profile, sets=None):
    """Fresh scene with truck + camper + environment. Returns (cfg, truck_info, camper objs, world)."""
    bpy.ops.wm.read_factory_settings(use_empty=True)
    cfg = load_variant(name, sets)
    mats = MaterialLibrary(cfg["paint_spec"])
    info = build_truck(cfg["truck"], mats, new_collection("truck"))
    build, truck_types = variants.get(cfg["camper"]["module"])
    if info["type"] not in truck_types:
        raise PipelineError(f"variant {name}: camper module {cfg['camper']['module']} supports "
                            f"{truck_types}, truck is {info['type']}")
    vcfg = dict(cfg)
    vcfg["truck_info"] = {k: v for k, v in info.items() if k != "objects"}
    col = new_collection(f"camper_{name}")
    objs = build(vcfg, col, mats)
    if not isinstance(objs, (list, tuple)):
        raise PipelineError(f"variant {name}: build() must return a list of objects")
    stray = [o.name for o in objs if col not in o.users_collection]
    if stray:
        raise PipelineError(f"variant {name}: objects not linked to the given collection: {stray[:5]}")
    world = setup_world(rcfg["hdri"])
    add_ground(info["ground_z"], rcfg["ground"], new_collection("environment"))
    configure_render(profile)
    return cfg, info, list(objs), world


def render_variant(name, rcfg, profile_name, views, save_blend=None, sets=None, suffix=""):
    profile = resolve_profile(rcfg, profile_name)
    out_name = f"{name}{suffix}"
    t_build = time.time()
    cfg, info, objs, world = stage_variant(name, rcfg, profile, sets)
    build_s = round(time.time() - t_build, 2)
    bbox = world_bbox(info["objects"] + objs)
    out_dir = repo_path(OUT_DIR)
    out_dir.mkdir(parents=True, exist_ok=True)
    results = []
    for view in views:
        if view not in rcfg["views"]:
            raise PipelineError(f"unknown view '{view}' (have {', '.join(k for k in rcfg['views'] if k[0] != '_')})")
        spec = dict(rcfg["views"][view])
        spec.update(cfg.get("cameras", {}).get(view, {}))
        if not profile.get("dof"):
            spec["fstop"] = None
        world.set_sun_azimuth(spec.get("sun_azimuth_deg", rcfg["hdri"].get("sun_azimuth_deg", 200.0)))
        cam = place_camera(spec, bbox, info["ground_z"], name=f"cam_{view}")
        out = out_dir / f"{out_name}_{view}.png"
        bpy.context.scene.render.filepath = str(out)
        t0 = time.time()
        bpy.ops.render.render(write_still=True)
        secs = round(time.time() - t0, 2)
        if not out.is_file():
            raise PipelineError(f"render produced no file at {out}")
        cam_ob = bpy.context.scene.camera
        if save_blend is None:
            bpy.data.objects.remove(cam_ob)
        results.append({"view": view, "seconds": secs, "camera": cam, "sun": world.info(),
                        "output": str(out.relative_to(REPO_ROOT)), "output_sha256": sha256_file(out)})
        print(f"[{out_name}] {view}: {secs}s -> {out}")
    if save_blend:
        p = repo_path(save_blend)
        p.parent.mkdir(parents=True, exist_ok=True)
        bpy.ops.wm.save_as_mainfile(filepath=str(p), compress=True)
    tris = sum(sum(len(pl.vertices) - 2 for pl in o.data.polygons) for o in info["objects"] + objs
               if o.type == "MESH")
    rec = write_run_record("render_variants", {
        "blender": bpy.app.version_string, "variant": name, "output_name": out_name, "suffix": suffix,
        "set": sets or {}, "profile": profile_name, "settings": profile,
        "truck": {k: v for k, v in info.items() if k not in ("objects",)}, "build_seconds": build_s,
        "scene_triangles": tris, "views": results,
    })
    print(f"[{out_name}] record {rec}")
    return results


def build_sheet(views):
    out_dir = repo_path(OUT_DIR)
    names = sorted({p.stem.rsplit("_", 1)[0] for p in out_dir.glob("*.png")
                    if p.stem != "contact_sheet" and p.stem.rsplit("_", 1)[-1] in views
                    and not p.stem.startswith("_")})
    rows = []
    for n in names:
        rows.append((n, {v: (out_dir / f"{n}_{v}.png") if (out_dir / f"{n}_{v}.png").is_file() else None
                         for v in views}))
    if not rows:
        return None
    out = out_dir / "contact_sheet.png"
    make_contact_sheet(rows, list(views), out)
    print(f"contact sheet {out} ({len(rows)} variants)")
    return out


def main():
    p = make_parser("Render camper variants on the proxy truck")
    p.add_argument("--variant", action="append", default=[])
    p.add_argument("--all", action="store_true")
    p.add_argument("--profile", default="surface")
    p.add_argument("--views", default=",".join(DEFAULT_VIEWS))
    p.add_argument("--no-sheet", action="store_true")
    p.add_argument("--save-blend")
    p.add_argument("--set", dest="sets", action="append", default=[], metavar="KEY.PATH=VALUE",
                   help="override a variant config key (value JSON-parsed); repeatable")
    p.add_argument("--suffix", default=None, help="output name suffix, e.g. _closed")
    args = p.parse_args(script_args())
    cli_sets = parse_sets(args.sets)
    names = all_variants() if args.all else args.variant
    if not names:
        raise PipelineError("give --variant NAME (repeatable) or --all")
    rcfg = load_render_config()
    views = [v.strip() for v in args.views.split(",") if v.strip()]
    jobs = []
    for n in names:
        base = load_variant(n)
        if cli_sets or args.suffix is not None:
            poses = [{"suffix": args.suffix or "", "set": cli_sets}]
        else:
            poses = poses_for(base)
        for pose in poses:
            cfg_views = load_variant(n, pose["set"]).get("views") or views
            vlist = [v for v in views if v in cfg_views] if args.views != ",".join(DEFAULT_VIEWS) else cfg_views
            jobs.append((n, pose, vlist))
    t_all = time.time()
    for n, pose, vlist in jobs:
        render_variant(n, rcfg, args.profile, vlist, args.save_blend if len(jobs) == 1 else None,
                       sets=pose["set"], suffix=pose["suffix"])
    print(f"rendered {len(jobs)} pose(s) in {round(time.time() - t_all, 1)}s")
    if not args.no_sheet:
        build_sheet(DEFAULT_VIEWS)


# Blender runs --python scripts with __name__ == "__main__"; importing this module only defines helpers.
if __name__ == "__main__":
    run_main(main)
