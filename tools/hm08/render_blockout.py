"""Blocking-out renders: OG HM08 default adult (grey, left) next to `stylized-default` (tan, right).

    blender -b --factory-startup -P tools/hm08/render_blockout.py -- <out_dir>

Writes, each with both figures labelled:
- front.png, three_quarter.png, side.png: full body
- face_front.png, face_three_quarter.png, face_side.png: head close-ups
- strength_front.png, strength_face.png: OG, the "subtle" preset (the first §6.1 table) and
  stylized-default side by side, to show how far the anime-leaning default moved
- density_face.png, density_torso.png: wireframe of OG HM08 at its own density, the stylized
  shape decimated to the old D2 budget (18k body tris, head and neck 4.5k) and to the current one
  (10k, head and neck 2k; lowered on PRXJX2). Head and rest are decimated separately to their
  §4.1 region budgets. The decimated mesh is only a preview of the density sty01 (§4) will have;
  sty01 itself is hand-built quads.
Workbench engine, no addon needed.
"""
import math
import os
import sys

import bpy

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import make_stylized_default as msd  # noqa: E402

# (body + head triangles at LOD0, of which head and neck): D2 and §4.1
OLD_BUDGET = (18000, 4500)  # before PRXJX2's "drop poly count substantially"
BUDGET = (10000, 2000)

out_dir = os.path.abspath(sys.argv[sys.argv.index("--") + 1] if "--" in sys.argv else ".")
os.makedirs(out_dir, exist_ok=True)

raw, faces = msd.load_mesh()
p0 = msd.default_adult(raw)
groups = msd.load_groups()
p1 = msd.build(p0, faces, groups, msd.load_weights(len(p0)))
p_subtle = msd.build(p0, faces, groups, msd.load_weights(len(p0)), "subtle")
body = set(groups["body"].tolist())
body_faces = [f for f in faces if all(v in body for v in f)]
# Eyeballs (the HM08 eye helpers, which the target moves with the sockets), so the eye openings
# do not read as empty holes. Kept out of the triangle counts.
eye_verts = set(groups["helper-l-eye"].tolist()) | set(groups["helper-r-eye"].tolist())
eye_faces = [f for f in faces if all(v in eye_verts for v in f)]

bpy.ops.wm.read_factory_settings(use_empty=True)
scene = bpy.context.scene
SUBTLE = (0.80, 0.50, 0.40, 1.0)
EYE = (0.92, 0.92, 0.9, 1.0)
GREY, TAN, WIRE = (0.55, 0.55, 0.55, 1.0), (0.85, 0.62, 0.48, 1.0), (0.05, 0.05, 0.07, 1.0)


def material(name, color):
    mat = bpy.data.materials.new(name)
    mat.diffuse_color = color
    return mat


def add_mesh(name, p, color, mesh_faces=None, eyes=True):
    verts = [(x, -z, y) for x, y, z in p]  # base.obj Y-up/+Z-forward to Blender Z-up/-Y
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata(verts, [], body_faces if mesh_faces is None else mesh_faces)
    mesh.shade_smooth()
    mesh.materials.append(material(name, color))
    obj = bpy.data.objects.new(name, mesh)
    scene.collection.objects.link(obj)
    if eyes:
        eye = add_mesh(name + "_eyes", p, EYE, eye_faces, eyes=False)
        eye.parent = obj
    return obj


def apply_modifier(obj, kind, **kw):
    mod = obj.modifiers.new(kind, kind)
    for k, v in kw.items():
        setattr(mod, k, v)
    dg = bpy.context.evaluated_depsgraph_get()
    mesh = bpy.data.meshes.new_from_object(obj.evaluated_get(dg))
    obj.modifiers.clear()
    obj.data = mesh
    return obj


def tri_count(obj):
    return sum(len(poly.vertices) - 2 for poly in obj.data.polygons)


def wire_copy(obj, thickness):
    wire = obj.copy()
    wire.data = obj.data.copy()
    wire.data.materials.clear()
    wire.data.materials.append(material(obj.name + "_wire", WIRE))
    scene.collection.objects.link(wire)
    mod = wire.modifiers.new("wire", "WIREFRAME")
    mod.thickness, mod.use_relative_offset, mod.use_even_offset = thickness, False, False
    mod.offset = 1.0
    return wire


def add_label(text, size):
    curve = bpy.data.curves.new(text, "FONT")
    curve.body, curve.size, curve.align_x = text, size, "CENTER"
    obj = bpy.data.objects.new(text, curve)
    obj.rotation_euler = (math.radians(90), 0.0, 0.0)
    obj.data.materials.append(material(text, (0.95, 0.95, 0.95, 1.0)))
    scene.collection.objects.link(obj)
    return obj


og = add_mesh("og_hm08", p0, GREY)
new = add_mesh("stylized_default", p1, TAN)
subtle = add_mesh("stylized_subtle", p_subtle, SUBTLE)
og_tris = tri_count(og)
# Head and neck: every face above the neck joint, so the region budget is checkable on its own.
neck_y = p0[groups["joint-neck"], 1].mean()
head_faces = [f for f in body_faces if p0[f, 1].min() > neck_y]
rest_faces = [f for f in body_faces if p0[f, 1].min() <= neck_y]
og_head_tris = sum(len(f) - 2 for f in head_faces)


def budget_mesh(name, budget):
    """p1 with the head and the rest decimated apart to their budgets, joined into one mesh."""
    verts, polys, tris = [], [], []
    for part, faces_, target in (("head", head_faces, budget[1]),
                                 ("rest", rest_faces, budget[0] - budget[1])):
        obj = add_mesh(f"{name}_{part}", p1, TAN, faces_, eyes=False)
        ratio = target / sum(len(f) - 2 for f in faces_)
        apply_modifier(obj, "DECIMATE", ratio=ratio, use_symmetry=True, symmetry_axis="X")
        base = len(verts)
        verts += [tuple(v.co) for v in obj.data.vertices]
        polys += [[base + i for i in poly.vertices] for poly in obj.data.polygons]
        tris.append(tri_count(obj))
        bpy.data.objects.remove(obj)
    obj = add_mesh(name, p1, TAN)
    obj.data.clear_geometry()
    obj.data.from_pydata(verts, [], polys)
    obj.data.shade_smooth()
    return obj, sum(tris), tris[0]


low_old, old_tris, old_head = budget_mesh("stylized_budget_old", OLD_BUDGET)
low, low_tris, low_head = budget_mesh("stylized_budget", BUDGET)

scene.render.engine = "BLENDER_WORKBENCH"
shading = scene.display.shading
shading.light, shading.color_type = "STUDIO", "MATERIAL"
shading.show_cavity, shading.show_shadows = True, False
scene.render.resolution_x, scene.render.resolution_y = 1280, 720
scene.world = bpy.data.worlds.new("w")
scene.world.color = (0.18, 0.18, 0.2)

cam = bpy.data.objects.new("cam", bpy.data.cameras.new("cam"))
cam.data.type = "ORTHO"
cam.rotation_euler = (math.radians(90), 0.0, 0.0)
scene.collection.objects.link(cam)
scene.camera = cam

# (file, [(figure, label)], spacing, yaw, camera z, ortho, label z, label size, wire thickness)
og_l, new_l, subtle_l = "OG: HM08 default adult", "NEW: stylized-default", "first 6.1 (subtle)"
dens_f = [(og, f"OG: HM08, head {og_head_tris:,} tris"), (low_old, f"old budget: head {old_head:,}"),
          (low, f"NEW budget: head {low_head:,}")]
dens_t = [(og, f"OG: HM08, {og_tris:,} tris"), (low_old, f"old budget: {old_tris:,}"),
          (low, f"NEW budget: {low_tris:,}")]
pair = [(og, og_l), (new, new_l)]
trio = [(og, og_l), (subtle, subtle_l), (new, new_l)]
SHOTS = [
    ("front", pair, 12.0, 0.0, 0.3, 35.0, 9.0, 0.6, 0),
    ("three_quarter", pair, 12.0, 35.0, 0.3, 35.0, 9.0, 0.6, 0),
    ("side", pair, 12.0, 90.0, 0.3, 35.0, 9.0, 0.6, 0),
    ("face_front", pair, 3.4, 0.0, 7.8, 6.0, 9.15, 0.2, 0),
    ("face_three_quarter", pair, 3.4, 35.0, 7.8, 6.0, 9.15, 0.2, 0),
    ("face_side", pair, 3.0, 90.0, 7.8, 7.0, 9.15, 0.2, 0),
    ("strength_front", trio, 9.0, 20.0, 0.3, 35.0, 9.5, 0.55, 0),
    ("strength_face", trio, 3.0, 25.0, 8.0, 9.5, 9.6, 0.2, 0),
    ("density_face", dens_f, 3.0, 20.0, 7.9, 9.0, 9.2, 0.16, 0.005),
    ("density_torso", dens_t, 10.0, 20.0, 4.5, 30.0, 10.5, 0.45, 0.012),
]
figures = (og, new, low_old, low, subtle)
for name, figs, spacing, yaw, z, ortho, lz, lsize, wire in SHOTS:
    shown = [obj for obj, _ in figs]
    for obj in figures:
        obj.hide_render = obj not in shown
        for child in obj.children:
            child.hide_render = obj.hide_render
    extras = []
    for i, (obj, text) in enumerate(figs):
        x = (i - (len(figs) - 1) / 2) * spacing
        obj.location.x = x
        obj.rotation_euler = (0.0, 0.0, math.radians(yaw))
        label = add_label(text, lsize)
        label.location = (x, -20.0, lz)
        extras.append(label)
        if wire:
            extras.append(wire_copy(obj, wire))
    cam.location = (0.0, -60.0, z)
    cam.data.ortho_scale = ortho
    scene.render.filepath = os.path.join(out_dir, f"{name}.png")
    bpy.ops.render.render(write_still=True)
    for obj in extras:
        bpy.data.objects.remove(obj)
print(f"og tris {og_tris} (head {og_head_tris}), old budget {old_tris} (head {old_head}), "
      f"budget {low_tris} (head {low_head})")
