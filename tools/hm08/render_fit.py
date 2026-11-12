"""Fit check of stylized-default at the macro corners (STYLIZED_SPEC 4.3, 7.4, phase 2).

    BLENDER_USER_RESOURCES=<dir with the mpfb extension and its asset packs> \
        blender -b -P tools/hm08/render_fit.py -- <out_dir>

For gender 0/1 x age young/old x weight min/max and stylization 0, 0.5, 1: a full human through
HumanService (default rig, clothes, shoes, hair, high-poly eyes, eyebrows, eyelashes, teeth), posed
(arms raised, elbows, hip and knee bent, head nodded and turned), rendered in Workbench front and face, and
measured. Eyes_out: eyeball vertices outside the skin that still have skin in front of them (pushed
through a lid); the plain Eyes share rises with lid coverage of a bigger eyeball and is not clipping
by itself. Clipping metric per asset: share of its posed vertices more than 2 mm inside the posed
body (signed against the nearest body face); for teeth, vertices more than 1 mm outside it. "No new
clipping" means the share at stylization 0.5 and 1 is no higher than at 0. Writes
<corner>_s<s>_{body,face}.png, fit.tsv, and prints the table.
"""
import math
import os
import sys

import bpy
from mathutils.bvhtree import BVHTree

from bl_ext.user_default.mpfb.services import HumanService, LocationService, TargetService

out_dir = os.path.abspath(sys.argv[sys.argv.index("--") + 1] if "--" in sys.argv else ".")
os.makedirs(out_dir, exist_ok=True)
data = LocationService.get_mpfb_data()
user_data = LocationService.get_user_data()


def asset(sub):
    for root in (user_data, data):
        p = os.path.join(root, sub)
        if os.path.exists(p):
            return p
    raise IOError(sub)


POSE = {"upperarm01.L": (0, 0, 55), "upperarm01.R": (0, 0, -55), "lowerarm01.L": (0, 0, 35),
        "lowerarm01.R": (0, 0, -35), "upperleg01.L": (-35, 0, 0), "lowerleg01.L": (60, 0, 0),
        "spine03": (10, 0, 0), "head": (10, 15, 0)}
STYLE = (0.0, 0.5, 1.0)


def corners():
    for g in (0.0, 1.0):
        for age_name, age in (("young", 0.5), ("old", 1.0)):
            for w_name, w in (("wmin", 0.0), ("wmax", 1.0)):
                yield f"g{g:g}_{age_name}_{w_name}", g, age, w


def build(g, age, w, s):
    macros = TargetService.get_default_macro_info_dict()
    macros.update(gender=g, age=age, weight=w)
    body = HumanService.create_human(macro_detail_dict=macros, stylization=s)
    rig = HumanService.add_builtin_rig(body, "default")
    parts = {}
    suit = "female_casualsuit01" if g < 0.5 else "male_casualsuit01"
    for kind, sub in (("Clothes", f"clothes/{suit}/{suit}.mhclo"), ("Shoes", "clothes/shoes01/shoes01.mhclo"),
                      ("Hair", "hair/short02/short02.mhclo"), ("Eyes", "eyes/high-poly/high-poly.mhclo"),
                      ("Eyebrows", "eyebrows/eyebrow001/eyebrow001.mhclo"),
                      ("Eyelashes", "eyelashes/eyelashes01/eyelashes01.mhclo"),
                      ("Teeth", "teeth/teeth_base/teeth_base.mhclo")):
        atype = "Clothes" if kind == "Shoes" else kind
        parts[kind] = HumanService.add_mhclo_asset(asset(sub), body, asset_type=atype, subdiv_levels=0,
                                                   material_type="NONE")
    bpy.context.view_layer.objects.active = rig
    for bone, rot in POSE.items():
        pb = rig.pose.bones[bone]
        pb.rotation_mode = "XYZ"
        pb.rotation_euler = tuple(math.radians(a) for a in rot)
    bpy.context.view_layer.update()
    return body, rig, parts


def posed_world(obj):
    dg = bpy.context.evaluated_depsgraph_get()
    ev = obj.evaluated_get(dg)
    mesh = ev.to_mesh()
    verts = [ev.matrix_world @ v.co for v in mesh.vertices]
    polys = [tuple(p.vertices) for p in mesh.polygons]
    ev.to_mesh_clear()
    return verts, polys


def body_tree(body):
    # The body surface only: helpers off, but no clothes delete-masks, so every asset vertex is tested.
    saved = [(m, m.show_viewport) for m in body.modifiers if m.type == "MASK"]
    for m, _ in saved:
        m.show_viewport = False
    verts, polys = posed_world(body)
    for m, v in saved:
        m.show_viewport = v
    vg = body.vertex_groups["body"].index
    inbody = {v.index for v in body.data.vertices if any(e.group == vg for e in v.groups)}
    polys = [p for p in polys if all(i in inbody for i in p)]
    return BVHTree.FromPolygons(verts, polys)


def poke_out(tree, obj):
    """Share of the asset's posed vertices more than 1 mm outside the body that also have body surface
    in front of them along -y: geometry pushed through the lids rather than seen through the opening."""
    verts, _ = posed_world(obj)
    bad = 0
    for v in verts:
        hit = tree.find_nearest(v)
        if hit[0] is not None and (v - hit[0]).dot(hit[1]) > 0.001:
            bad += tree.ray_cast(v + hit[1] * 0.0005, (0.0, -1.0, 0.0), 0.2)[0] is not None
    return bad / max(1, len(verts))


def clipping(tree, obj, exposed):
    """Share of the asset's posed vertices more than 2 mm inside the body, or for teeth (exposed) the
    share with no body surface in front of them along -y (poking through the closed lips)."""
    verts, _ = posed_world(obj)
    bad = 0
    for v in verts:
        if exposed:
            bad += tree.ray_cast(v, (0.0, -1.0, 0.0), 0.2)[0] is None
            continue
        hit = tree.find_nearest(v)
        if hit[0] is not None:
            bad += (v - hit[0]).dot(hit[1]) < -0.002
    return bad / max(1, len(verts))


COLORS = {"Clothes": (0.35, 0.55, 0.75, 1), "Shoes": (0.25, 0.25, 0.25, 1), "Hair": (0.45, 0.3, 0.15, 1),
          "Eyes": (0.95, 0.95, 0.9, 1), "Eyebrows": (0.15, 0.1, 0.05, 1), "Eyelashes": (0.05, 0.05, 0.05, 1),
          "Teeth": (1.0, 0.2, 0.2, 1)}


rows = []
ONLY = os.environ.get("FIT_ONLY")  # one corner name, e.g. g0_young_wmin, for a quick run
for name, g, age, w in corners():
    if ONLY and name != ONLY:
        continue
    for s in STYLE:
        bpy.ops.wm.read_homefile(use_empty=True)
        scene = bpy.context.scene
        scene.render.engine = "BLENDER_WORKBENCH"
        shading = scene.display.shading
        shading.light, shading.color_type, shading.show_cavity = "STUDIO", "OBJECT", True
        body, rig, parts = build(g, age, w, s)
        tree = body_tree(body)
        fit = {k: clipping(tree, o, k == "Teeth") for k, o in parts.items()}
        fit["Eyes_out"] = poke_out(tree, parts["Eyes"])
        verts, _ = posed_world(body)
        zmax = max(v.z for v in verts)
        body.color = (0.85, 0.62, 0.48, 1)
        for k, o in parts.items():
            o.color = COLORS[k]
        ev, _ = posed_world(parts["Eyes"])
        eye_l = [v for v in ev if v.x > 0]
        eye = sum(eye_l, ev[0] * 0) / len(eye_l)
        row = dict(corner=name, s=s, height=zmax, **fit)
        rows.append(row)
        print("FIT", name, s, " ".join(f"{k}={v:.4f}" for k, v in fit.items()), flush=True)
        cam = bpy.data.objects.new("cam", bpy.data.cameras.new("cam"))
        cam.data.type = "ORTHO"
        cam.rotation_euler = (math.radians(90), 0.0, 0.0)
        scene.collection.objects.link(cam)
        scene.camera = cam
        for shot, x, z, ortho, rx, ry in (("body", 0.0, zmax * 0.5, zmax * 1.1, 400, 720),
                                          ("face", eye.x - 0.032, eye.z - 0.02, 0.26, 400, 400),
                                          ("eye", eye.x, eye.z, 0.07, 400, 300)):
            cam.location = (x, -10.0, z)
            cam.data.ortho_scale = ortho
            scene.render.resolution_x, scene.render.resolution_y = rx, ry
            scene.render.filepath = os.path.join(out_dir, f"{name}_s{s:g}_{shot}.png")
            bpy.ops.render.render(write_still=True)

keys = ["Clothes", "Shoes", "Hair", "Eyes", "Eyes_out", "Eyebrows", "Eyelashes", "Teeth"]
with open(os.path.join(out_dir, "fit.tsv"), "w") as f:
    f.write("\t".join(["corner", "s", "height"] + keys) + "\n")
    for r in rows:
        f.write("\t".join([r["corner"], f"{r['s']:g}", f"{r['height']:.3f}"] + [f"{r[k]:.4f}" for k in keys]) + "\n")
worse = []
for name in sorted({r["corner"] for r in rows}):
    base = next(r for r in rows if r["corner"] == name and r["s"] == 0.0)
    for r in rows:
        if r["corner"] == name and r["s"] > 0:
            worse += [f"{name} s={r['s']:g} {k} {base[k]:.4f}->{r[k]:.4f}" for k in keys if r[k] > base[k] + 0.002]
print("NEW CLIPPING (share +0.2% over s=0):", "; ".join(worse) or "none")
