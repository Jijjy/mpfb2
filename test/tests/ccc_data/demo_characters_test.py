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
                {"stylization": 3}, {"rig": None, "pose": "t-pose"}):
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
    assert HumanService.get_stylization(basemesh) == approx(1.0)
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
