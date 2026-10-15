"""One-off: extract the DRW wheel assemblies for the HD chassis-cab preview (render-only).

  blender --background --factory-startup --python-exit-code 1 --python scripts/extract_hd_wheels.py

Imports the chassis-cab box truck reference (tools/reference-hd-chassis/hd_drw_box_truck.glb, CC BY-SA 4.0,
see README "Credits"; ~2.35M faces, so this runs in its own Blender process), keeps only the four wheel
assemblies (front singles, rear duals: full-detail tyres (decimating them streaks the sidewalls), rims, hub caps), rotates them into the truck
frame (+Y forward, +X right, ground z = 0) with each origin at its tyre centre, drops all textures and saves
tools/reference-hd-chassis/hd_drw_wheels.blend for lib.proxy_truck.build_hd_chassis_reference. The output is
derived from a BY-SA model: it stays in tools/ (gitignored) and is never committed or packaged.
"""
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import bmesh  # noqa: E402
import bpy  # noqa: E402
from mathutils import Matrix, Vector  # noqa: E402

from lib.common import PipelineError, repo_path, run_main  # noqa: E402
from lib.proxy_truck import HD_CHASSIS_DIR, check_glb  # noqa: E402

SRC = HD_CHASSIS_DIR + "/hd_drw_box_truck.glb"
DST = HD_CHASSIS_DIR + "/hd_drw_wheels.blend"
TIRE_DECIMATE = 1.0          # < 1 decimates the tyres (smaller file; 0.12-0.35 left radial streaks on the sidewalls)
ROLES = {"aiStandardSurface7SG": "tire", "aiStandardSurface8SG": "rim", "aiStandardSurface9SG": "hub"}


def main():
    src, dst = repo_path(SRC), repo_path(DST)
    if not src.is_file():
        raise PipelineError(f"missing {src}: download the chassis-cab box truck (README 'Credits') as .glb")
    check_glb(src)
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=str(src))
    R = Matrix.Rotation(math.radians(90), 4, "Z")          # model front +X -> +Y
    groups = {}
    for ob in list(bpy.data.objects):
        if ob.type != "MESH" or not ob.material_slots or ob.material_slots[0].material is None:
            continue
        role = ROLES.get(ob.material_slots[0].material.name)
        if role is None:
            continue
        me = ob.data.copy()
        me.transform(R @ ob.matrix_world)
        c = sum((v.co for v in me.vertices), Vector()) / len(me.vertices)
        key = ("f" if c.y > 0 else "r") + ("R" if c.x > 0 else "L")
        if role == "tire" and TIRE_DECIMATE < 1.0:
            tmp = bpy.data.objects.new("tmp", me)
            bpy.context.scene.collection.objects.link(tmp)
            m = tmp.modifiers.new("d", "DECIMATE")
            m.ratio = TIRE_DECIMATE
            dg = bpy.context.evaluated_depsgraph_get()
            me = bpy.data.meshes.new_from_object(tmp.evaluated_get(dg))
            bpy.data.objects.remove(tmp)
        groups.setdefault(key, {}).setdefault(role, []).append(me)
    if sorted(groups) != ["fL", "fR", "rL", "rR"]:
        raise PipelineError(f"{src.name}: expected four wheel groups, got {sorted(groups)}")
    for o in list(bpy.data.objects):
        bpy.data.objects.remove(o)
    out = []
    for key, roles in sorted(groups.items()):
        bm = bmesh.new()
        mats = []
        for role, mes in roles.items():
            mat = bpy.data.materials.get("hdw_" + role) or bpy.data.materials.new("hdw_" + role)
            mats.append(mat)
            for me in mes:
                tmp = bmesh.new(); tmp.from_mesh(me)
                for f in tmp.faces:
                    f.material_index = len(mats) - 1
                t2 = bpy.data.meshes.new("_t"); tmp.to_mesh(t2); tmp.free()
                bm.from_mesh(t2); bpy.data.meshes.remove(t2)
        me = bpy.data.meshes.new("hdw_" + key)
        bm.to_mesh(me); bm.free()
        for m in mats:
            me.materials.append(m)
        tires = [me.vertices[i].co for p in me.polygons if me.materials[p.material_index].name == "hdw_tire" for i in p.vertices]
        lo = Vector([min(v[i] for v in tires) for i in range(3)]); hi = Vector([max(v[i] for v in tires) for i in range(3)])
        ctr = Vector(((lo.x + hi.x) / 2, (lo.y + hi.y) / 2, (lo.z + hi.z) / 2))
        me.transform(Matrix.Translation(-ctr))
        ob = bpy.data.objects.new("hdw_" + key, me)
        ob["axle"] = "front" if key[0] == "f" else "rear"
        ob["side"] = 1 if key[1] == "R" else -1
        ob["center_x"] = ctr.x; ob["axle_y"] = ctr.y; ob["axle_z"] = ctr.z
        ob["tire_diameter"] = hi.z - lo.z; ob["width"] = hi.x - lo.x
        bpy.context.scene.collection.objects.link(ob)
        out.append(ob)
        print(f"{ob.name}: faces {len(me.polygons)} centre {tuple(round(x, 3) for x in ctr)} dia {hi.z - lo.z:.3f} width {hi.x - lo.x:.3f}")
    for me in list(bpy.data.meshes):
        if me.users == 0:
            bpy.data.meshes.remove(me)
    for m in list(bpy.data.materials):
        if m.users == 0:
            bpy.data.materials.remove(m)
    for im in list(bpy.data.images):
        bpy.data.images.remove(im)

    dst.parent.mkdir(parents=True, exist_ok=True)
    bpy.ops.wm.save_as_mainfile(filepath=str(dst), compress=True)
    print("saved", dst)


if __name__ == "__main__":
    run_main(main)
