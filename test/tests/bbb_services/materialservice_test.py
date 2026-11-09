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


def test_identify_material():
    obj = _create_human_with_makeskin_material()
    assert obj
    material = MaterialService.get_material(obj)
    assert MaterialService.identify_material(material) == "makeskin"
    ObjectService.delete_object(obj)


def test_identify_material_stylized_skin():
    """A STYLIZED skin made by HumanService is identified by its BloodTint input and serializes as STYLIZED"""
    basemesh = HumanService.create_human()
    assert basemesh
    HumanService.set_character_skin(None, basemesh, skin_type="STYLIZED")
    material = MaterialService.get_material(basemesh)
    assert MaterialService.identify_material(material) == "stylized_skin"
    human_info = HumanService._create_default_human_info_dict()
    HumanService._populate_human_info_with_skin_info(human_info, basemesh)
    assert human_info["skin_material_type"] == "STYLIZED"
    assert "BloodTint" in human_info["skin_material_settings"]["stylized"]
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


def test_only_stylized_skin_can_be_created():
    """HumanService.set_character_skin() -- STYLIZED is the only skin type (STYLIZED_SPEC.md 11)"""
    import pytest
    basemesh = HumanService.create_human()
    assert basemesh
    for skin_type in ["ENHANCED", "ENHANCED_SSS", "LAYERED", "MAKESKIN", "GAMEENGINE"]:
        with pytest.raises(ValueError):
            HumanService.set_character_skin(None, basemesh, skin_type=skin_type)
    HumanService.set_character_skin(None, basemesh, skin_type="STYLIZED")
    assert MaterialService.identify_material(MaterialService.get_material(basemesh)) == "stylized_skin"
    ObjectService.delete_object(basemesh)
