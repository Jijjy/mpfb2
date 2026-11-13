"""Build and render the stylized demo characters (STYLIZED_SPEC.md, ticket ASJ4WF).

    blender -b -P tools/demo/make_demo.py -- [--no-render] [--samples N] [name ...]

or `mise run demo -- [name ...]`. Each character is one JSON file in tools/demo/characters/; no names
means all of them. For each character the script builds the human through the MPFB services, saves
<out>/<name>.blend and, unless --no-render, renders front, three-quarter and side views in Cycles and
EEVEE under the Stylized studio lighting into one contact sheet, <out>/<name>_sheet.png: Cycles on the
top row, EEVEE below, front / three-quarter / side from left to right. The single views stay next to it
as <out>/<name>_<engine>_<view>.png.

<out> is $MPFB_DEMO_OUT, else tools/demo/out.

A character file holds these keys; all but "name" are optional and default to DEFAULTS below:

    name        the output file name; defaults to the JSON file's stem
    macros      macro values over the default phenotype (gender, age, muscle, weight, height,
                proportions, cupsize, firmness, race: {african, asian, caucasian})
    stylization the Stylization slider, 0 to 2
    skin_tone   a swatch name from data/settings/skin_tones.json
    eyes        stylized eye settings over data/settings/eye_settings.stylized.json
    eyebrows, eyelashes, teeth, tongue, hair, shoes
                an asset name (the directory under the asset library's eyebrows/, hair/, clothes/, ...),
                or null for none
    clothes     a list of clothes asset names
    rig         a built-in rig name, or null for none
    pose        null, a pose name from data/poses/<rig>_fk/, or a path to a pose JSON relative to the
                character file (tools/demo/poses/ holds the demo poses)
"""
import copy
import json
import math
import os
import sys

import bpy
from mathutils import Vector

HERE = os.path.dirname(os.path.abspath(__file__))
CHARACTERS_DIR = os.path.join(HERE, "characters")

DEFAULTS = {
    "macros": {},
    "stylization": 1.0,
    "skin_tone": "Default",
    "eyes": {},
    "eyebrows": "eyebrow001",
    "eyelashes": "eyelashes01",
    "teeth": "teeth_base",
    "tongue": "tongue01",
    "hair": None,
    "clothes": [],
    "shoes": None,
    "rig": "default",
    "pose": None,
}
MACRO_KEYS = ("gender", "age", "muscle", "weight", "height", "proportions", "cupsize", "firmness", "race")
RACE_KEYS = ("african", "asian", "caucasian")
# (key, asset library subdirectory, object type for add_mhclo_asset)
BODYPARTS = (("eyebrows", "eyebrows", "Eyebrows"), ("eyelashes", "eyelashes", "Eyelashes"),
             ("teeth", "teeth", "Teeth"), ("tongue", "tongue", "Tongue"), ("hair", "hair", "Hair"))
EYES_ASSET = "high-poly"
# (name, camera yaw in degrees: 0 looks at the face, 90 at the character's left side)
VIEWS = (("front", 0.0), ("three_quarter", 35.0), ("side", 90.0))
ENGINES = ("CYCLES", "EEVEE")
RESOLUTION = (600, 900)


def _mpfb():
    """The MPFB package, by whatever name the extension repository gave it; enabled when it is not loaded."""
    for name, module in list(sys.modules.items()):
        if (name == "mpfb" or name.endswith(".mpfb")) and hasattr(module, "ClassManager"):
            return name
    import addon_utils
    addon_utils.enable("bl_ext.user_default.mpfb", default_set=True, persistent=True)
    return "bl_ext.user_default.mpfb"


def _import(module, *names):
    import importlib
    mod = importlib.import_module(_mpfb() + "." + module)
    return [getattr(mod, n) for n in names] if len(names) > 1 else getattr(mod, names[0])


def out_dir():
    """$MPFB_DEMO_OUT, else tools/demo/out."""
    return os.path.abspath(os.environ.get("MPFB_DEMO_OUT") or os.path.join(HERE, "out"))


def _settings(file_name):
    LocationService = _import("services", "LocationService")
    with open(os.path.join(LocationService.get_mpfb_data("settings"), file_name), encoding="utf-8") as f:
        return json.load(f)


def load_character(path):
    """Read one character file, check its keys and values, and fill in DEFAULTS. Raises ValueError."""
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise ValueError(f"{path}: a character is a JSON object")
    unknown = set(data) - set(DEFAULTS) - {"name"}
    if unknown:
        raise ValueError(f"{path}: unknown keys {sorted(unknown)}")
    char = copy.deepcopy(DEFAULTS)
    char.update(data)
    char.setdefault("name", os.path.splitext(os.path.basename(path))[0])
    char["source"] = os.path.abspath(path)

    bad = set(char["macros"]) - set(MACRO_KEYS)
    if bad:
        raise ValueError(f"{path}: unknown macros {sorted(bad)}")
    bad = set(char["macros"].get("race", {})) - set(RACE_KEYS)
    if bad:
        raise ValueError(f"{path}: unknown races {sorted(bad)}")
    if not 0.0 <= float(char["stylization"]) <= 2.0:
        raise ValueError(f"{path}: stylization {char['stylization']} is outside 0 to 2")
    swatches = [s["name"] for s in _settings("skin_tones.json")["swatches"]]
    if char["skin_tone"] not in swatches:
        raise ValueError(f"{path}: skin_tone {char['skin_tone']!r} is not one of {swatches}")
    bad = set(char["eyes"]) - set(_settings("eye_settings.stylized.json"))
    if bad:
        raise ValueError(f"{path}: unknown eye settings {sorted(bad)}")
    if not isinstance(char["clothes"], list):
        raise ValueError(f"{path}: clothes is a list of asset names")
    if char["pose"] is not None and char["rig"] is None:
        raise ValueError(f"{path}: a pose needs a rig")
    return char


def list_characters(names=None, directory=CHARACTERS_DIR):
    """The character files in the directory, all or the named ones, sorted. Raises ValueError for a missing name."""
    available = sorted(os.path.splitext(f)[0] for f in os.listdir(directory) if f.endswith(".json"))
    if not names:
        names = available
    missing = [n for n in names if n not in available]
    if missing:
        raise ValueError(f"no character {missing}; there are {available}")
    return [os.path.join(directory, n + ".json") for n in names]


def _asset(name, subdir):
    AssetService = _import("services", "AssetService")
    path = AssetService.find_asset_absolute_path(name + ".mhclo", asset_subdir=subdir)
    if path is None:
        raise IOError(f"no {subdir} asset {name!r} in the asset library")
    return path


def _group_node(material):
    for node in material.node_tree.nodes:
        if node.type == "GROUP":
            return node
    raise ValueError(f"material {material.name} has no group node")


def _load_pose(char):
    pose = char["pose"]
    if pose.endswith(".json"):
        path = os.path.join(os.path.dirname(char["source"]), pose)
    else:
        LocationService = _import("services", "LocationService")
        path = os.path.join(LocationService.get_mpfb_data("poses"), char["rig"] + "_fk", pose + ".json")
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    data.setdefault("bone_translations", {})
    data.setdefault("skeleton_type", char["rig"])
    return data


def clear_scene():
    for obj in list(bpy.data.objects):
        bpy.data.objects.remove(obj, do_unlink=True)
    bpy.data.orphans_purge(do_recursive=True)


def build_character(char):
    """Build the character in the current scene; returns the basemesh."""
    HumanService, TargetService, MaterialService, NodeService, ObjectService, RigService = (
        _import("services", "HumanService", "TargetService", "MaterialService", "NodeService", "ObjectService",
                "RigService"))
    macros = TargetService.get_default_macro_info_dict()
    for key, value in char["macros"].items():
        if key == "race":
            macros["race"].update(value)
        else:
            macros[key] = value
    stylization = float(char["stylization"])
    basemesh = HumanService.create_human(macro_detail_dict=macros, stylization=stylization)
    basemesh.name = char["name"] + ".body"

    rig = None
    if char["rig"]:
        rig = HumanService.add_builtin_rig(basemesh, char["rig"], import_weights=True)
        rig.name = char["name"]
    HumanService.add_mhclo_asset(_asset(EYES_ASSET, "eyes"), basemesh, asset_type="Eyes", subdiv_levels=1,
                                 material_type="MAKESKIN")
    for key, subdir, asset_type in BODYPARTS:
        if char[key]:
            HumanService.add_mhclo_asset(_asset(char[key], subdir), basemesh, asset_type=asset_type, subdiv_levels=1,
                                         material_type="MAKESKIN")
    for name in char["clothes"] + ([char["shoes"]] if char["shoes"] else []):
        HumanService.add_mhclo_asset(_asset(name, "clothes"), basemesh, asset_type="Clothes", subdiv_levels=1,
                                     material_type="MAKESKIN")

    # Stylized skin, eyes and bodypart recolours; this sets the slider to 1 when it was below
    HumanService.make_stylized(basemesh)
    if abs(HumanService.get_stylization(basemesh) - stylization) > 1e-6:
        HumanService.set_stylization(basemesh, stylization)
        HumanService.refit(basemesh)

    skin = _group_node(MaterialService.get_material(basemesh))
    tone = dict(_import("entities.nodemodel.v2.materials.nodewrapperstylizedskin", "skin_tone_swatches")())
    NodeService.set_socket_default_values(skin, {"SkinTone": tone[char["skin_tone"]]})
    eyes = ObjectService.find_object_of_type_amongst_nearest_relatives(basemesh, "Eyes")
    eye_settings = _settings("eye_settings.stylized.json")
    eye_settings.update(char["eyes"])
    NodeService.set_socket_default_values(_group_node(MaterialService.get_material(eyes)), eye_settings)

    if rig is not None and char["pose"]:
        bpy.ops.object.select_all(action="DESELECT")
        bpy.context.view_layer.objects.active = rig
        rig.select_set(True)
        bpy.ops.object.mode_set(mode="POSE")
        RigService.set_pose_from_dict(rig, _load_pose(char))
        bpy.ops.object.mode_set(mode="OBJECT")
    return basemesh


def save_blend(char, directory):
    os.makedirs(directory, exist_ok=True)
    path = os.path.join(directory, char["name"] + ".blend")
    filepaths = bpy.context.preferences.filepaths
    save_version, filepaths.save_version = filepaths.save_version, 0  # no .blend1 next to it
    try:
        bpy.ops.wm.save_as_mainfile(filepath=path, copy=True, check_existing=False)
    finally:
        filepaths.save_version = save_version
    return path


def _bounds(basemesh):
    """World bounding box (min, max) of the basemesh and every visible mesh parented under the same root."""
    root = basemesh.parent or basemesh
    objects = [root] + list(root.children_recursive)
    lo, hi = Vector((1e9,) * 3), Vector((-1e9,) * 3)
    depsgraph = bpy.context.evaluated_depsgraph_get()
    for obj in objects:
        if obj.type != "MESH" or obj.hide_render:
            continue
        evaluated = obj.evaluated_get(depsgraph)
        for corner in evaluated.bound_box:
            p = evaluated.matrix_world @ Vector(corner)
            lo = Vector(map(min, lo, p))
            hi = Vector(map(max, hi, p))
    return lo, hi


def _set_engine(scene, engine, samples):
    if engine == "CYCLES":
        scene.render.engine = "CYCLES"
        scene.cycles.device = "CPU"
        scene.cycles.samples = samples
    else:
        ids = [e.identifier for e in bpy.types.RenderSettings.bl_rna.properties["engine"].enum_items]
        scene.render.engine = "BLENDER_EEVEE_NEXT" if "BLENDER_EEVEE_NEXT" in ids else "BLENDER_EEVEE"


def render_character(char, basemesh, directory, samples=48):
    """Render the views in both engines under the studio lighting and write the contact sheet. Returns its path."""
    bpy.ops.mpfb.stylized_studio()
    if bpy.data.objects.get("StudioKey") is None:
        raise RuntimeError("mpfb.stylized_studio added no lights")
    scene = bpy.context.scene
    scene.render.resolution_x, scene.render.resolution_y = RESOLUTION
    scene.render.resolution_percentage = 100
    scene.render.film_transparent = False
    scene.view_settings.view_transform = "AgX" if "AgX" in [
        i.identifier for i in scene.view_settings.bl_rna.properties["view_transform"].enum_items] else "Filmic"
    cam = bpy.data.objects.get("DemoCamera") or bpy.data.objects.new("DemoCamera", bpy.data.cameras.new("DemoCamera"))
    if cam.name not in scene.collection.objects:
        scene.collection.objects.link(cam)
    scene.camera = cam
    cam.data.lens = 50.0
    lo, hi = _bounds(basemesh)
    centre = (lo + hi) / 2
    height = hi.z - lo.z
    # Frame the height with a margin. The sensor fit is AUTO, so the sensor width spans the longer side of
    # the frame, here its height.
    cam.data.sensor_fit = "AUTO"
    distance = height * 1.12 * cam.data.lens / cam.data.sensor_width + max(hi.y - lo.y, hi.x - lo.x) / 2
    shots = []
    for engine in ENGINES:
        _set_engine(scene, engine, samples)
        row = []
        for view, yaw in VIEWS:
            a = math.radians(yaw)
            # yaw 0 is in front (-Y); positive yaw swings toward the character's left (+X)
            cam.location = centre + Vector((math.sin(a) * distance, -math.cos(a) * distance, 0.0))
            cam.rotation_euler = (centre - cam.location).to_track_quat("-Z", "Y").to_euler()
            path = os.path.join(directory, f"{char['name']}_{engine}_{view}.png")
            scene.render.filepath = path
            bpy.ops.render.render(write_still=True)
            row.append(path)
        shots.append(row)
    return contact_sheet(shots, os.path.join(directory, char["name"] + "_sheet.png"))


def contact_sheet(rows, path, gap=8):
    """Tile equally sized images, a list of rows of paths, into one PNG with a dark gap between them."""
    import numpy as np
    images = [[bpy.data.images.load(p) for p in row] for row in rows]
    w, h = images[0][0].size
    n_rows, n_cols = len(images), max(len(r) for r in images)
    sheet_w, sheet_h = n_cols * w + (n_cols + 1) * gap, n_rows * h + (n_rows + 1) * gap
    pixels = np.empty((sheet_h, sheet_w, 4), dtype=np.float32)
    pixels[:] = (0.02, 0.02, 0.02, 1.0)
    for r, row in enumerate(images):
        # Blender's pixel rows run bottom-up, so the first row of images goes at the top
        y = sheet_h - (r + 1) * (h + gap)
        for c, image in enumerate(row):
            if tuple(image.size) != (w, h):
                raise ValueError(f"{image.filepath} is {tuple(image.size)}, not {(w, h)}")
            tile = np.empty(w * h * 4, dtype=np.float32)
            image.pixels.foreach_get(tile)
            x = gap + c * (w + gap)
            pixels[y:y + h, x:x + w] = tile.reshape(h, w, 4)
    sheet = bpy.data.images.new("demo_sheet", sheet_w, sheet_h, alpha=True)
    sheet.colorspace_settings.name = images[0][0].colorspace_settings.name
    sheet.pixels.foreach_set(pixels.ravel())
    sheet.filepath_raw = path
    sheet.file_format = "PNG"
    sheet.save()
    for row in images:
        for image in row:
            bpy.data.images.remove(image)
    bpy.data.images.remove(sheet)
    return path


def make(char, directory, render=True, samples=48):
    """Clear the scene, build one character, save its .blend and, when asked, render its contact sheet."""
    clear_scene()
    basemesh = build_character(char)
    blend = save_blend(char, directory)
    print(f"DEMO {char['name']}: saved {blend}")
    if render:
        sheet = render_character(char, basemesh, directory, samples)
        print(f"DEMO {char['name']}: contact sheet {sheet}")
    return basemesh


def main(argv):
    render, samples, names = True, 48, []
    args = iter(argv)
    for arg in args:
        if arg == "--no-render":
            render = False
        elif arg == "--samples":
            samples = int(next(args))
        else:
            names.append(arg)
    directory = out_dir()
    characters = [load_character(p) for p in list_characters(names)]
    for char in characters:
        make(char, directory, render, samples)


if __name__ == "__main__":
    main(sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else [])
