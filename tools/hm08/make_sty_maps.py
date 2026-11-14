"""Paint and bake the STYLIZED skin maps in HM08's UV layout (STYLIZED_SPEC.md 5.1, ticket EXWWXF).

    blender -b --factory-startup -P tools/hm08/make_sty_maps.py -- [out_dir]

out_dir defaults to src/mpfb/data/textures. Writes three 1024² grayscale PNGs:

- sty_bloodmap.png: the warm areas. Cheeks, nose tip, knuckles, elbows, knees, palms and soles are
  painted per vertex on the default adult (falloffs around landmarks taken from the joint
  vertex groups, palm/sole sides from the normals) and baked to UV with Cycles. Ears are a falloff
  around the centre of HM08's ear mask (mpfb_ears.jpg marks only the inner ear); lips and inner ears
  also come straight from HM08's region masks (mpfb_lips.jpg, mpfb_ears.jpg), already in these UVs.
- sty_cavity.png: ambient occlusion baked from the HM08 base mesh with MPFB's default macros and
  no shape target. White is open skin; the occlusion distance is short so it reads folds
  and creases, not the large-scale shadowing a light already gives.
- sty_roughness.png: the roughness mask the wrapper maps 0..1 to 0.4..0.6: body 0.75 (0.55),
  face 0.5 (0.50), lips 0.0 (0.40), from mpfb_face.jpg and mpfb_lips.jpg.

Only the body faces are baked; the helper geometry is left out.
"""
import os
import sys

import bpy
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import hm08mesh as msd  # noqa: E402

SIZE = 1024
AO_SAMPLES = 256
TEXTURES = os.path.join(msd.DATA, "textures")
out_dir = os.path.abspath(sys.argv[sys.argv.index("--") + 1]) if "--" in sys.argv[:-1] else TEXTURES
os.makedirs(out_dir, exist_ok=True)


def load_uvs():
    """Per face corner UV indices of base.obj and its vt list, in face order."""
    vts, corners = [], []
    with open(os.path.join(msd.DATA, "3dobjs", "base.obj")) as f:
        for line in f:
            if line.startswith("vt "):
                vts.append([float(x) for x in line.split()[1:3]])
            elif line.startswith("f "):
                corners.append([int(t.split("/")[1]) - 1 for t in line.split()[1:]])
    return np.array(vts), corners


def smoothstep(e0, e1, x):
    t = np.clip((x - e0) / (e1 - e0), 0.0, 1.0)
    return t * t * (3 - 2 * t)


def joint(p, groups, name):
    return p[groups["joint-" + name]].mean(axis=0)


def blob(p, centre, sigma):
    d2 = ((p - centre) ** 2).sum(axis=1)
    return np.exp(-d2 / (2 * sigma * sigma))


def blood_per_vertex(p, faces, groups, weights, nails_dorsal, ear_mask):
    """Blood weight 0..1 per vertex. p is in base.obj axes: x left/right, y up, z forward."""
    n = msd.vertex_normals(p, faces)
    body = groups["body"]
    height = p[body, 1].max() - p[body, 1].min()
    u = height / 100.0  # one percent of the body height
    blood = np.zeros(len(p))

    def add(w):
        np.maximum(blood, w, out=blood)

    head = msd.wsum(weights, r"^(head|jaw|oris|levator|risorius|orbicularis|oculi|special|temporalis)")
    # Nose tip: the most forward head vertex near the midline.
    near_mid = np.where((head > 0.5) & (np.abs(p[:, 0]) < 0.5 * u))[0]
    near_mid = np.intersect1d(near_mid, body)
    nose = p[near_mid[np.argmax(p[near_mid, 2])]]
    add(0.85 * blob(p, nose, 0.9 * u))
    # Cheeks: below and a little outside each eye, on the surface (the most forward head vertex there).
    mouth = joint(p, groups, "mouth")
    for side in "lr":
        eye = joint(p, groups, side + "-eye")
        target = np.array([eye[0] * 1.45, eye[1] - 0.9 * (eye[1] - mouth[1])])
        cand = np.intersect1d(np.where((head > 0.5) & (((p[:, :2] - target) ** 2).sum(axis=1) < (0.6 * u) ** 2))[0], body)
        cheek = p[cand[np.argmax(p[cand, 2])]]
        print(f"cheek {side} at {np.round(cheek, 2)}, nose tip at {np.round(nose, 2)}")
        add(0.75 * blob(p, cheek, 1.3 * u) * smoothstep(0.0, 0.5, n[:, 2]))
        # Ears: the whole outer ear, around the centre of HM08's ear mask on that side.
        on_side = np.where((ear_mask > 0.5) & (np.sign(p[:, 0]) == np.sign(eye[0])))[0]
        ear = p[on_side].mean(axis=0)
        add(0.7 * blob(p, ear, 1.6 * u) * smoothstep(0.75, 0.9, np.abs(p[:, 0]) / abs(ear[0])) * (head > 0.5))
    for side in "lr":
        s = "L" if side == "l" else "R"
        # Elbows (back of the arm) and knees (front of the leg).
        add(0.6 * blob(p, joint(p, groups, side + "-elbow"), 1.6 * u) * smoothstep(0.0, 0.6, -n[:, 2]))
        add(0.6 * blob(p, joint(p, groups, side + "-knee"), 2.2 * u) * smoothstep(0.0, 0.6, n[:, 2]))
        # Hands: knuckles on the back, the palm side all over.
        hand = msd.wsum(weights, rf"^(wrist|metacarpal\d|finger\d-\d)\.{s}$")
        dorsal = nails_dorsal["hand", side]
        facing = n @ dorsal
        for f in range(1, 6):
            for j in (2, 3):
                add(0.55 * blob(p, joint(p, groups, f"{side}-finger-{f}-{j}"), 0.5 * u) * smoothstep(0.1, 0.6, facing) * hand)
        add(0.7 * smoothstep(0.5, 0.9, hand) * smoothstep(0.0, 0.6, -facing))
        # Soles: the downward side of the foot and toes.
        foot = msd.wsum(weights, rf"^(foot|toe\d-\d)\.{s}$")
        add(0.7 * smoothstep(0.5, 0.9, foot) * smoothstep(0.2, 0.7, -n[:, 1]))
    return blood


def sample_mask(name, vts):
    """Values of a data/textures region mask at the given UVs (nearest pixel)."""
    img = bpy.data.images.load(os.path.join(TEXTURES, name))
    w, h = img.size
    px = np.empty(w * h * 4, dtype=np.float32)
    img.pixels.foreach_get(px)
    px = px.reshape(h, w, 4)[:, :, 0]  # bottom-up, like UV v
    x = np.clip((vts[:, 0] * w).astype(int), 0, w - 1)
    y = np.clip((vts[:, 1] * h).astype(int), 0, h - 1)
    bpy.data.images.remove(img)
    return px[y, x]


def mask_pixels(name):
    """A data/textures region mask resampled to SIZE², bottom-up rows, values 0..1."""
    img = bpy.data.images.load(os.path.join(TEXTURES, name))
    img.colorspace_settings.name = "Non-Color"
    img.scale(SIZE, SIZE)
    px = np.empty(SIZE * SIZE * 4, dtype=np.float32)
    img.pixels.foreach_get(px)
    bpy.data.images.remove(img)
    return px.reshape(SIZE, SIZE, 4)[:, :, 0]


def vertex_mask(name, count, faces, corners, vts):
    """Per vertex: the highest value a region mask has at any of the vertex's face corners."""
    vals = sample_mask(name, vts)
    on = np.zeros(count)
    for face, uvs in zip(faces, corners):
        for v, t in zip(face, uvs):
            on[v] = max(on[v], vals[t])
    return on


def nails_dorsal_directions(p, faces, corners, vts, weights):
    """Back-of-hand and top-of-foot direction per side: the mean normal where the nail masks are."""
    n = msd.vertex_normals(p, faces)
    out = {}
    for limb, mask, pattern in (("hand", "mpfb_fingernails.jpg", r"^(finger\d-\d)\.{}$"),
                                ("foot", "mpfb_toenails.jpg", r"^(toe\d-\d)\.{}$")):
        on = vertex_mask(mask, len(p), faces, corners, vts)
        for side, s in (("l", "L"), ("r", "R")):
            w = (on > 0.5) * (msd.wsum(weights, pattern.format(s)) > 0.5)
            d = (n * w[:, None]).sum(axis=0)
            out[limb, side] = d / np.linalg.norm(d)
            print(f"{limb} {side} dorsal {np.round(out[limb, side], 2)} from {int(w.sum())} nail vertices")
    return out


def build_object(p, faces, corners, vts, body_faces, blood):
    mesh = bpy.data.meshes.new("hm08")
    mesh.from_pydata([tuple(v) for v in p], [], [faces[i] for i in body_faces])
    uv = mesh.uv_layers.new(name="UVMap")
    loop_uvs = np.array([vts[t] for i in body_faces for t in corners[i]], dtype=np.float32)
    uv.data.foreach_set("uv", loop_uvs.ravel())
    attr = mesh.color_attributes.new("blood", "FLOAT_COLOR", "POINT")
    cols = np.repeat(blood[:, None], 4, axis=1).astype(np.float32)
    cols[:, 3] = 1.0
    attr.data.foreach_set("color", cols.ravel())
    mesh.shade_smooth()
    obj = bpy.data.objects.new("hm08", mesh)
    bpy.context.scene.collection.objects.link(obj)
    return obj


def bake(obj, kind, name):
    """Bake kind (AO or EMIT) into a new SIZE² float image; returns its first channel, bottom-up."""
    img = bpy.data.images.new(name, SIZE, SIZE, float_buffer=True, alpha=False)
    img.colorspace_settings.name = "Non-Color"
    mat = obj.data.materials[0]
    tex = mat.node_tree.nodes["bake target"]
    tex.image = img
    mat.node_tree.nodes.active = tex
    bpy.ops.object.bake(type=kind, margin=16, margin_type="EXTEND", use_clear=True)
    px = np.empty(SIZE * SIZE * 4, dtype=np.float32)
    img.pixels.foreach_get(px)
    return px.reshape(SIZE, SIZE, 4)[:, :, 0].copy()


def coverage(obj):
    """1 where a body face covers the texel, 0 elsewhere (an EMIT bake of white with no margin)."""
    mat = obj.data.materials[0]
    nodes = mat.node_tree.nodes
    nodes["emit"].inputs["Strength"].default_value = 1.0
    links = mat.node_tree.links
    for link in list(nodes["emit"].inputs["Color"].links):
        links.remove(link)
    nodes["emit"].inputs["Color"].default_value = (1, 1, 1, 1)
    img = bpy.data.images.new("coverage", SIZE, SIZE, float_buffer=True, alpha=False)
    nodes["bake target"].image = img
    bpy.ops.object.bake(type="EMIT", margin=0, use_clear=True)
    px = np.empty(SIZE * SIZE * 4, dtype=np.float32)
    img.pixels.foreach_get(px)
    return px.reshape(SIZE, SIZE, 4)[:, :, 0] > 0.5


def save_gray(values, file_name):
    """Write values (SIZE² bottom-up rows, 0..1) as an 8-bit grayscale PNG."""
    img = bpy.data.images.new(file_name, SIZE, SIZE, alpha=False)
    img.colorspace_settings.name = "Non-Color"
    rgba = np.ones((SIZE, SIZE, 4), dtype=np.float32)
    rgba[:, :, :3] = np.clip(values, 0.0, 1.0)[:, :, None]
    img.pixels.foreach_set(rgba.ravel())
    settings = bpy.context.scene.render.image_settings
    settings.file_format, settings.color_mode, settings.color_depth = "PNG", "BW", "8"
    settings.compression = 100
    path = os.path.join(out_dir, file_name)
    img.save_render(path, scene=bpy.context.scene)
    print("wrote", path)


def main():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    scene.render.engine = "CYCLES"
    scene.cycles.device = "CPU"
    scene.cycles.samples = AO_SAMPLES
    scene.view_settings.view_transform = "Standard"
    scene.display_settings.display_device = "sRGB"
    scene.sequencer_colorspace_settings.name = "Non-Color"
    scene.world = bpy.data.worlds.new("w")

    raw, faces = msd.load_mesh()
    vts, corners = load_uvs()
    groups = msd.load_groups()
    weights = msd.load_weights(len(raw))
    p = msd.default_adult(raw)
    body = set(groups["body"].tolist())
    body_faces = [i for i, f in enumerate(faces) if all(v in body for v in f)]

    dorsal = nails_dorsal_directions(p, faces, corners, vts, weights)
    ear_mask = vertex_mask("mpfb_ears.jpg", len(p), faces, corners, vts)
    blood = blood_per_vertex(p, faces, groups, weights, dorsal, ear_mask)
    height = p[groups["body"], 1].max() - p[groups["body"], 1].min()
    obj = build_object(p, faces, corners, vts, body_faces, blood)

    mat = bpy.data.materials.new("bake")
    mat.use_nodes = True
    nodes, links = mat.node_tree.nodes, mat.node_tree.links
    nodes.clear()
    out = nodes.new("ShaderNodeOutputMaterial")
    emit = nodes.new("ShaderNodeEmission")
    emit.name = "emit"
    attr = nodes.new("ShaderNodeAttribute")
    attr.attribute_name = "blood"
    links.new(attr.outputs["Color"], emit.inputs["Color"])
    links.new(emit.outputs["Emission"], out.inputs["Surface"])
    tex = nodes.new("ShaderNodeTexImage")
    tex.name = "bake target"
    obj.data.materials.append(mat)
    bpy.context.view_layer.objects.active = obj
    obj.select_set(True)

    # Occlusion reach: 4% of the body height, about 7 cm on an adult; folds, not body-scale shadow.
    scene.world.light_settings.distance = 0.04 * height
    ao = bake(obj, "AO", "ao")
    blood_baked = bake(obj, "EMIT", "blood")
    covered = coverage(obj)

    # AO: stretch so the open skin (95th percentile of covered texels) is white.
    open_skin = np.percentile(ao[covered], 95)
    ao = np.clip(ao / open_skin, 0.0, 1.0)
    ao[~covered & (ao == 0.0)] = 1.0  # unused texels past the bake margin: open
    print(f"AO: open skin {open_skin:.3f}, covered median {np.median(ao[covered]):.3f}, 2nd percentile {np.percentile(ao[covered], 2):.3f}")
    save_gray(ao, "sty_cavity.png")

    ears, lips, face = mask_pixels("mpfb_ears.jpg"), mask_pixels("mpfb_lips.jpg"), mask_pixels("mpfb_face.jpg")
    blood_map = np.maximum.reduce([blood_baked, 0.7 * ears, 0.9 * lips])
    print(f"blood: {100 * (blood_map[covered] > 0.2).mean():.1f}% of covered texels above 0.2")
    save_gray(blood_map, "sty_bloodmap.png")

    rough = 0.75 * (1 - face) + 0.5 * face
    rough = rough * (1 - lips)
    save_gray(rough, "sty_roughness.png")


main()
