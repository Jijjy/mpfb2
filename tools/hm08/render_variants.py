"""Sign-off renders of stylized-default across gender and age (STYLIZED_SPEC 4.3, 7.6).

    blender -b --factory-startup -P tools/hm08/render_variants.py -- <out_dir>

For age young and child, gender 0, 0.5, 1: the OG HM08 body (grey) next to the shipped target applied
at weight 1.0 (young) or 0.5 (child, the 4.3 age fade) (tan). Writes <age>_front.png,
<age>_three_quarter.png, <age>_face.png, <age>_face_side.png and prints head/height ratios.
Workbench engine, no addon needed.
"""
import math
import os
import sys

import bpy
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import make_stylized_default as msd  # noqa: E402

out_dir = os.path.abspath(sys.argv[sys.argv.index("--") + 1] if "--" in sys.argv else ".")
os.makedirs(out_dir, exist_ok=True)

AGES = {"young": 1.0, "child": 0.5}  # age fade of the stylization weight, 4.3
GENDERS = (0.0, 0.5, 1.0)
raw, faces = msd.load_mesh()
groups = msd.load_groups()
weights = msd.load_weights(len(raw))
body = set(groups["body"].tolist())
body_faces = [f for f in faces if all(v in body for v in f)]
eye_verts = set(groups["helper-l-eye"].tolist()) | set(groups["helper-r-eye"].tolist())
eye_faces = [f for f in faces if all(v in eye_verts for v in f)]


def macro_body(gender, age):
    p = raw.copy()
    for name, w in (("female", 1 - gender), ("male", gender)):
        if w == 0:
            continue
        msd.apply_target(p, f"macrodetails/universal-{name}-{age}-averagemuscle-averageweight", w)
        for race in ("african", "asian", "caucasian"):
            msd.apply_target(p, f"macrodetails/{race}-{name}-{age}", w / 3)
    return p


bpy.ops.wm.read_factory_settings(use_empty=True)
scene = bpy.context.scene
EYE, GREY, TAN = (0.92, 0.92, 0.9, 1.0), (0.55, 0.55, 0.55, 1.0), (0.85, 0.62, 0.48, 1.0)


def material(name, color):
    mat = bpy.data.materials.new(name)
    mat.diffuse_color = color
    return mat


def add_mesh(name, p, color, mesh_faces=None, eyes=True):
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata([(x, -z, y) for x, y, z in p], [], body_faces if mesh_faces is None else mesh_faces)
    mesh.shade_smooth()
    mesh.materials.append(material(name, color))
    obj = bpy.data.objects.new(name, mesh)
    scene.collection.objects.link(obj)
    if eyes:
        add_mesh(name + "_eyes", p, EYE, eye_faces, eyes=False).parent = obj
    return obj


def add_label(text, size):
    curve = bpy.data.curves.new(text, "FONT")
    curve.body, curve.size, curve.align_x = text, size, "CENTER"
    obj = bpy.data.objects.new(text, curve)
    obj.rotation_euler = (math.radians(90), 0.0, 0.0)
    obj.data.materials.append(material(text, (0.95, 0.95, 0.95, 1.0)))
    scene.collection.objects.link(obj)
    return obj


scene.render.engine = "BLENDER_WORKBENCH"
shading = scene.display.shading
shading.light, shading.color_type = "STUDIO", "MATERIAL"
shading.show_cavity, shading.show_shadows = True, False
scene.render.resolution_x, scene.render.resolution_y = 1920, 720
scene.world = bpy.data.worlds.new("w")
scene.world.color = (0.18, 0.18, 0.2)
cam = bpy.data.objects.new("cam", bpy.data.cameras.new("cam"))
cam.data.type = "ORTHO"
cam.rotation_euler = (math.radians(90), 0.0, 0.0)
scene.collection.objects.link(cam)
scene.camera = cam

for age, fade in AGES.items():
    figs = []  # (obj, label, x-order)
    tops, bottoms = [], []
    for g in GENDERS:
        p0 = macro_body(g, age)
        p1 = p0.copy()
        msd.apply_target(p1, "stylization/stylized-default", fade)
        r0, h0, t0 = msd.measure(p0, groups, weights)
        r1, h1, t1 = msd.measure(p1, groups, weights)
        print(f"{age} gender {g}: OG head/height {r0:.4f} ({1 / r0:.2f} heads), stylized "
              f"{r1:.4f} ({1 / r1:.2f} heads), height {t0:.2f} -> {t1:.2f} dm")
        figs.append((add_mesh(f"og_{age}_{g}", p0, GREY), f"OG g={g:g}", p0[:, 1].max()))
        figs.append((add_mesh(f"new_{age}_{g}", p1, TAN), f"stylized g={g:g}", p1[:, 1].max()))
        tops.append(p0[:, 1].max())
        bottoms.append(p0[:, 1].min())
    top, bottom = max(tops), min(bottoms)  # decimetres
    tall = top - bottom
    # (name, yaw, camera z, spacing, label size). ortho_scale spans the render width, so the visible
    # height is 0.375 of it.
    mid = (top + bottom) / 2
    shots = [("front", 0.0, mid, tall * 0.5, tall * 0.04),
             ("three_quarter", 35.0, mid, tall * 0.5, tall * 0.04),
             ("face", 0.0, top - tall * 0.08, tall * 0.2, tall * 0.012),
             ("face_side", 90.0, top - tall * 0.08, tall * 0.2, tall * 0.012)]
    for name, yaw, z, spacing, lsize in shots:
        ortho = 6 * spacing * 1.02
        extras = []
        for i, (obj, text, ymax) in enumerate(figs):
            x = (i - (len(figs) - 1) / 2) * spacing
            obj.location.x = x
            obj.location.z = (top - ymax) if name.startswith("face") else 0.0  # heads level in close-ups
            obj.rotation_euler = (0.0, 0.0, math.radians(yaw))
            label = add_label(text, lsize)
            label.location = (x, -20.0, z + ortho * 0.375 * 0.43)
            extras.append(label)
        cam.location = (0.0, -60.0, z)
        cam.data.ortho_scale = ortho
        scene.render.filepath = os.path.join(out_dir, f"{age}_{name}.png")
        bpy.ops.render.render(write_still=True)
        for o in extras:
            bpy.data.objects.remove(o)
    for obj, _, _ in figs:
        for c in obj.children:
            bpy.data.objects.remove(c)
        bpy.data.objects.remove(obj)
