"""Blocking-out renders: OG HM08 default adult (grey, left) next to `stylized-default` (tan, right).

    blender -b --factory-startup -P tools/hm08/render_blockout.py -- <out_dir>

Writes, each with both figures labelled:
- front.png, three_quarter.png, side.png: full body
- face_front.png, face_three_quarter.png: head close-ups
- strength_front.png, strength_face.png: OG, stylized-default and the "bold" preview preset
  (about twice the §6.1 changes) side by side, to judge how strong the default should be
- density_face.png, density_torso.png: wireframe of OG HM08 at its own density next to the
  stylized shape decimated to the D2 LOD0 budget (18k body tris). The decimated mesh is only a
  preview of the density sty01 (§4) will have; sty01 itself is hand-built quads.
Workbench engine, no addon needed.
"""
import math
import os
import sys

import bpy

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import make_stylized_default as msd  # noqa: E402

BUDGET = 18000  # D2: body + head triangles at LOD0

out_dir = os.path.abspath(sys.argv[sys.argv.index("--") + 1] if "--" in sys.argv else ".")
os.makedirs(out_dir, exist_ok=True)

raw, faces = msd.load_mesh()
p0 = msd.default_adult(raw)
groups = msd.load_groups()
p1 = msd.build(p0, faces, groups, msd.load_weights(len(p0)))
p_bold = msd.build(p0, faces, groups, msd.load_weights(len(p0)), "bold")
body = set(groups["body"].tolist())
body_faces = [f for f in faces if all(v in body for v in f)]

bpy.ops.wm.read_factory_settings(use_empty=True)
scene = bpy.context.scene
BOLD = (0.80, 0.50, 0.40, 1.0)
GREY, TAN, WIRE = (0.55, 0.55, 0.55, 1.0), (0.85, 0.62, 0.48, 1.0), (0.05, 0.05, 0.07, 1.0)


def material(name, color):
    mat = bpy.data.materials.new(name)
    mat.diffuse_color = color
    return mat


def add_mesh(name, p, color):
    verts = [(x, -z, y) for x, y, z in p]  # base.obj Y-up/+Z-forward to Blender Z-up/-Y
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata(verts, [], body_faces)
    mesh.shade_smooth()
    mesh.materials.append(material(name, color))
    obj = bpy.data.objects.new(name, mesh)
    scene.collection.objects.link(obj)
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
bold = add_mesh("stylized_bold", p_bold, BOLD)
og_tris = tri_count(og)
low = add_mesh("stylized_budget", p1, TAN)
apply_modifier(low, "DECIMATE", ratio=BUDGET / og_tris, use_collapse_triangulate=False)
low_tris = tri_count(low)
low.data.shade_smooth()

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
og_l, new_l, bold_l = "OG: HM08 default adult", "NEW: stylized-default", "BOLD preview (~2x)"
dens_l = (f"OG: HM08, {og_tris:,} tris", f"NEW, decimated to {low_tris:,} tris")
pair = [(og, og_l), (new, new_l)]
trio = pair + [(bold, bold_l)]
dens = [(og, dens_l[0]), (low, dens_l[1])]
SHOTS = [
    ("front", pair, 12.0, 0.0, 0.3, 35.0, 9.0, 0.6, 0),
    ("three_quarter", pair, 12.0, 35.0, 0.3, 35.0, 9.0, 0.6, 0),
    ("side", pair, 12.0, 90.0, 0.3, 35.0, 9.0, 0.6, 0),
    ("face_front", pair, 3.4, 0.0, 7.8, 6.0, 9.15, 0.2, 0),
    ("face_three_quarter", pair, 3.4, 35.0, 7.8, 6.0, 9.15, 0.2, 0),
    ("strength_front", trio, 9.0, 20.0, 0.3, 35.0, 9.5, 0.55, 0),
    ("strength_face", trio, 3.0, 25.0, 8.0, 9.5, 9.6, 0.2, 0),
    ("density_face", dens, 3.4, 20.0, 7.8, 6.0, 9.05, 0.15, 0.006),
    ("density_torso", dens, 11.0, 20.0, 4.5, 16.0, 8.7, 0.3, 0.012),
]
figures = (og, new, low, bold)
for name, figs, spacing, yaw, z, ortho, lz, lsize, wire in SHOTS:
    shown = [obj for obj, _ in figs]
    for obj in figures:
        obj.hide_render = obj not in shown
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
print(f"og tris {og_tris}, budget preview tris {low_tris}")
