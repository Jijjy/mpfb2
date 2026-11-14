"""tools/demo/make_demo.py: the character JSON loader, and one character built and saved into target/tmp."""
import json
import os
import shutil
import sys

import bpy
import pytest
from pytest import approx

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
OUT = os.path.join(REPO, "target", "tmp", "demo_characters_test")
sys.path.insert(0, os.path.join(REPO, "tools", "demo"))
import make_demo  # noqa: E402


@pytest.fixture
def out_dir():
    shutil.rmtree(OUT, ignore_errors=True)
    os.makedirs(OUT)
    yield OUT
    shutil.rmtree(OUT, ignore_errors=True)


def _write(directory, name, data):
    path = os.path.join(directory, name + ".json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f)
    return path


def test_loader_fills_defaults_and_rejects_bad_values(out_dir):
    paths = make_demo.list_characters()
    assert os.path.join(make_demo.CHARACTERS_DIR, "default.json") in paths
    for path in paths:
        make_demo.load_character(path)
    char = make_demo.load_character(_write(out_dir, "plain", {"skin_tone": "Tan"}))
    assert char["name"] == "plain"
    assert char["skin_tone"] == "Tan"
    assert char["eyebrows"] == make_demo.DEFAULTS["eyebrows"]
    assert char["rig"] == "default" and char["hair"] is None
    for bad in ({"colour": 1}, {"skin_tone": "Green"}, {"macros": {"wings": 1}}, {"eyes": {"Glow": 1}},
                {"rig": None, "pose": "t-pose"}):
        with pytest.raises(ValueError):
            make_demo.load_character(_write(out_dir, "bad", bad))
    with pytest.raises(ValueError):
        make_demo.list_characters(["no-such-character"])


def test_builds_and_saves_one_character(out_dir):
    HumanService = make_demo._import("services", "HumanService")
    MaterialService = make_demo._import("services", "MaterialService")
    swatches = dict(make_demo._import("entities.nodemodel.v2.materials.nodewrapperstylizedskin",
                                      "skin_tone_swatches")())
    source = _write(out_dir, "probe", {"macros": {"gender": 1.0}, "skin_tone": "Tan", "eyes": {"IrisSize": 0.45},
                                       "pose": os.path.join(make_demo.HERE, "poses", "relaxed.json")})
    char = make_demo.load_character(source)
    basemesh = make_demo.build_character(char)
    assert HumanService.has_stylized_skin(basemesh)
    skin = make_demo._group_node(MaterialService.get_material(basemesh))
    assert list(skin.inputs["SkinTone"].default_value) == approx(swatches["Tan"])
    children = {child.name: child for child in basemesh.parent.children}
    eyes = children["probe.high-poly"]
    assert make_demo._group_node(MaterialService.get_material(eyes)).inputs["IrisSize"].default_value == approx(0.45)
    for name in ("probe.eyebrow001", "probe.eyelashes01", "probe.teeth_base", "probe.tongue01"):
        assert name in children
    rig = basemesh.parent
    assert rig.type == "ARMATURE"
    assert rig.pose.bones["upperarm01.L"].rotation_euler.z == approx(-0.55)
    path = make_demo.save_blend(char, out_dir)
    assert os.path.getsize(path) > 0
    assert not os.path.exists(path + "1")
    assert bpy.data.filepath != path


def test_curve_hair_form(out_dir):
    """The {"pack", "blend", "cards", "color"} hair form: checked by the loader, converted to clump cards with the
    stylized hair material, the curves hidden. The build needs the hair-editor asset pack, from which it grooms the
    demo styles into a user blend and takes the bob from there."""
    char = make_demo.load_character(_write(out_dir, "curly", {"hair": {"pack": "short_hedgehog"}}))
    assert char["hair"] == {"pack": "short_hedgehog", "blend": None, "cards": {"cards_mode": "CLUMP"}, "color": None}
    for bad in ({"pack": "x", "style": 1}, {"cards": {}}, {"pack": "x", "cards": {"cards_mode": "TILES"}},
                {"pack": "x", "cards": {"cards_wings": 1}}, {"pack": "x", "cards": {"cards_cluster_count": 1}},
                {"pack": "x", "color": [2, 0, 0]}, {"pack": "x", "cards": {"cards_clump_width": 9.0}},
                {"pack": "x", "blend": "hair.txt"}, 7):
        with pytest.raises(ValueError):
            make_demo.load_character(_write(out_dir, "bad", {"hair": bad}))

    HairEditorService = make_demo._import("services.haireditorservices", "HairEditorService")
    if HairEditorService.get_hair_blend_path() is None:
        pytest.skip("the hair-editor asset pack is not installed")
    MaterialService = make_demo._import("services", "MaterialService")
    hp = make_demo._import("ui.haireditorpanel.hairproperties", "HAIR_PROPERTIES")
    blend = make_demo._groom().groom(os.path.join(out_dir, "demo_hair.blend"))
    char = make_demo.load_character(_write(out_dir, "curly", {
        "rig": None, "pose": None,
        "hair": {"pack": "demo_bob", "blend": blend,
                 "cards": {"cards_cluster_count": 12, "cards_clump_max_tris": 3000, "cards_clump_width": 2.0},
                 "color": [0.5, 0.2, 0.1]}}))
    basemesh = make_demo.build_character(char)
    hair = [o for o in basemesh.children if o.get("mpfb_pack_asset") == "demo_bob" and o.type == "CURVES"]
    assert len(hair) == 1 and hair[0].hide_render
    assert hp.get_value(f"{hair[0].name}_cards_mode", entity_reference=basemesh) == "CLUMP"
    assert hp.get_value(f"{hair[0].name}_cards_cluster_count", entity_reference=basemesh) == 12
    assert hp.get_value(f"{hair[0].name}_cards_clump_width", entity_reference=basemesh) == approx(2.0)
    cards = bpy.data.objects[hair[0].name + "_cards"]
    assert cards.type == "MESH" and not cards.hide_render and len(cards.data.polygons) > 0
    assert len(cards.data.polygons) <= 3000
    assert not cards.modifiers
    nodes = MaterialService.get_material(cards).node_tree.nodes
    assert list(nodes["HairTip"].outputs["Color"].default_value) == approx([0.5, 0.2, 0.1, 1.0])
    assert list(nodes["HairRoot"].outputs["Color"].default_value) == approx([0.425, 0.17, 0.085, 1.0])
