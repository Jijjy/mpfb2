import bpy, os

from .. import LocationService
from .. import ObjectService
from .. import MaterialService
from .. import NodeService
from .. import HumanService
from .. import dynamic_import

GeneralObjectProperties = dynamic_import("mpfb.entities.objectproperties", "GeneralObjectProperties")


def _create_human_with_makeskin_material():
    td = LocationService.get_mpfb_test("testdata")
    matfile = os.path.join(td, "materials", "almost_all_textures.mhmat")
    MakeSkinMaterial = dynamic_import("mpfb.entities.material.makeskinmaterial", "MakeSkinMaterial")
    mhmat = MakeSkinMaterial()
    mhmat.populate_from_mhmat(matfile)

    obj = HumanService.create_human()
    assert obj

    name = ObjectService.random_name()
    obj.name = name
    MaterialService.create_empty_material(name + "Material", obj)
    blender_material = MaterialService.get_material(obj)
    assert blender_material

    mhmat.apply_node_tree(blender_material)

    node_tree = blender_material.node_tree
    assert node_tree

    return obj


def _create_human_with_layered_material():
    td = LocationService.get_mpfb_test("testdata")
    matfile = os.path.join(td, "materials", "almost_all_textures.mhmat")

    obj = HumanService.create_human()
    assert obj
    name = ObjectService.random_name()
    material = MaterialService.create_v2_skin_material(name, obj, mhmat_file=matfile)
    assert material

    return obj


def _create_object(with_material=False):
    name = ObjectService.random_name()
    mesh = bpy.data.meshes.new(name + "Mesh")
    obj = bpy.data.objects.new(name, mesh)
    if with_material:
        MaterialService.create_empty_material(name + "Material", obj)
    return obj


def test_materialservice_exists():
    """MaterialService"""
    assert MaterialService is not None, "MaterialService can be imported"


def test_create_empty_material():
    """MaterialService.create_empty_material()"""
    obj = _create_object()
    assert obj
    assert MaterialService.get_material(obj) is None
    name = ObjectService.random_name()
    material = MaterialService.create_empty_material(name)
    assert material
    assert MaterialService.get_material(obj) is None
    name = ObjectService.random_name()
    material = MaterialService.create_empty_material(name, obj)
    assert material
    assert MaterialService.get_material(obj)
    ObjectService.delete_object(obj)


def test_create_v2_skin_material():
    """MaterialService.create_v2_skin_material()"""
    basemesh = HumanService.create_human()
    assert basemesh
    name = ObjectService.random_name()
    material = MaterialService.create_v2_skin_material(name, basemesh)
    assert material
    assert MaterialService.get_material(basemesh)
    assert material == MaterialService.get_material(basemesh)
    mastercolor = NodeService.find_first_group_node_by_tree_name(material.node_tree, "MpfbSkinMasterColor")
    assert mastercolor
    assert MaterialService.identify_material(material) == "layered_skin"
    ObjectService.delete_object(basemesh)


def test_identify_material():
    obj = _create_human_with_makeskin_material()
    assert obj
    material = MaterialService.get_material(obj)
    assert MaterialService.identify_material(material) == "makeskin"
    ObjectService.delete_object(obj)


def test_identify_material_stylized_skin():
    """STYLIZED_SPEC.md 5.1/8: a STYLIZED skin made by HumanService is identified by its BloodTint input,
    serializes as STYLIZED and rebuilds with its settings; the other skin types are still made and told apart"""
    basemesh = HumanService.create_human()
    assert basemesh
    HumanService.set_character_skin(None, basemesh, skin_type="STYLIZED")
    material = MaterialService.get_material(basemesh)
    assert MaterialService.identify_material(material) == "stylized_skin"
    assert len(basemesh.material_slots) == 1
    human_info = HumanService._create_default_human_info_dict()
    HumanService._populate_human_info_with_skin_info(human_info, basemesh)
    assert human_info["skin_material_type"] == "STYLIZED"
    assert "BloodTint" in human_info["skin_material_settings"]["stylized"]
    human_info["skin_material_settings"]["stylized"]["BloodStrength"] = 0.5
    HumanService.set_character_skin(None, basemesh, skin_type="STYLIZED", slot_overrides=human_info["skin_material_settings"])
    group_node = NodeService.find_first_node_by_type_name(MaterialService.get_material(basemesh).node_tree, "ShaderNodeGroup")
    assert abs(group_node.inputs["BloodStrength"].default_value - 0.5) < 1e-6

    mhmat = os.path.join(LocationService.get_mpfb_test("testdata"), "materials", "almost_all_textures.mhmat")
    expected = {"MAKESKIN": "makeskin", "GAMEENGINE": "gameengine", "ENHANCED_SSS": "enhanced_skin", "LAYERED": "layered_skin"}
    for skin_type, material_type in expected.items():
        HumanService.set_character_skin(mhmat, basemesh, skin_type=skin_type, material_instances=False)
        assert MaterialService.identify_material(MaterialService.get_material(basemesh)) == material_type, skin_type
    ObjectService.delete_object(basemesh)


def test_add_focus_nodes_makeskin():
    obj = _create_human_with_makeskin_material()
    assert obj
    material = MaterialService.get_material(obj)
    # Test might look odd, but the logic is different with 2+ materials
    assert MaterialService.get_number_of_ink_layers(material) == 0
    MaterialService.add_focus_nodes(material)
    assert MaterialService.get_number_of_ink_layers(material) == 1
    MaterialService.add_focus_nodes(material)
    assert MaterialService.get_number_of_ink_layers(material) == 2
    MaterialService.add_focus_nodes(material)
    assert MaterialService.get_number_of_ink_layers(material) == 3
    ObjectService.delete_object(obj)


def test_add_focus_nodes_layeres():
    obj = _create_human_with_layered_material()
    assert obj
    material = MaterialService.get_material(obj)
    # Test might look odd, but the logic is different with 2+ materials
    assert MaterialService.get_number_of_ink_layers(material) == 0
    MaterialService.add_focus_nodes(material)
    assert MaterialService.get_number_of_ink_layers(material) == 1
    MaterialService.add_focus_nodes(material)
    assert MaterialService.get_number_of_ink_layers(material) == 2
    MaterialService.add_focus_nodes(material)
    assert MaterialService.get_number_of_ink_layers(material) == 3
    ObjectService.delete_object(obj)
