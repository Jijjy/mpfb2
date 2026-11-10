"""Blocking-out renders of `stylized-default` next to the HM08 default adult (grey, left).

    blender -b --factory-startup -P tools/hm08/render_blockout.py -- <out_dir>

Writes front.png, side.png, three_quarter.png, and face_front_<fig>.png /
face_three_quarter_<fig>.png close-ups for fig in hm08, stylized. Workbench engine, no addon needed.
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

raw, faces = msd.load_mesh()
p0 = msd.default_adult(raw)
groups = msd.load_groups()
p1 = msd.build(p0, faces, groups, msd.load_weights(len(p0)))
body = set(groups["body"].tolist())
body_faces = [f for f in faces if all(v in body for v in f)]

bpy.ops.wm.read_factory_settings(use_empty=True)
scene = bpy.context.scene


def add_figure(name, p, x_offset, color):
    verts = [(x, -z, y) for x, y, z in p]  # base.obj Y-up/+Z-forward to Blender Z-up/-Y
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata(verts, [], body_faces)
    mesh.shade_smooth()
    obj = bpy.data.objects.new(name, mesh)
    obj.location.x = x_offset
    scene.collection.objects.link(obj)
    mat = bpy.data.materials.new(name)
    mat.diffuse_color = color
    mesh.materials.append(mat)
    return obj


add_figure("hm08_default", p0, -6.0, (0.55, 0.55, 0.55, 1.0))
add_figure("stylized_default", p1, 6.0, (0.85, 0.62, 0.48, 1.0))

scene.render.engine = "BLENDER_WORKBENCH"
shading = scene.display.shading
shading.light = "STUDIO"
shading.color_type = "MATERIAL"
shading.show_cavity = True
shading.show_shadows = False
scene.render.resolution_x, scene.render.resolution_y = 1280, 720
scene.render.film_transparent = False
scene.world = bpy.data.worlds.new("w")
scene.world.color = (0.18, 0.18, 0.2)

cam = bpy.data.objects.new("cam", bpy.data.cameras.new("cam"))
cam.data.type = "ORTHO"
cam.data.ortho_scale = 35.0
scene.collection.objects.link(cam)
scene.camera = cam

cam.location = (0.0, -60.0, 0.3)
cam.rotation_euler = (math.radians(90), 0.0, 0.0)

# The figures turn in place; the camera stays put so both stay in frame.
VIEWS = [("front", 0.0, 0.0, 0.3, 35.0), ("three_quarter", 35.0, 0.0, 0.3, 35.0),
         ("side", 90.0, 0.0, 0.3, 35.0)]
for name, x in (("hm08", -6.0), ("stylized", 6.0)):
    VIEWS += [(f"face_front_{name}", 0.0, x, 7.7, 5.5), (f"face_three_quarter_{name}", 35.0, x, 7.7, 5.5)]

for label, yaw, x, z, scale in VIEWS:
    cam.location.x, cam.location.z = x, z
    cam.data.ortho_scale = scale
    for obj in scene.objects:
        if obj.type == "MESH":
            obj.rotation_euler = (0.0, 0.0, math.radians(yaw))
    scene.render.filepath = os.path.join(out_dir, f"{label}.png")
    bpy.ops.render.render(write_still=True)
