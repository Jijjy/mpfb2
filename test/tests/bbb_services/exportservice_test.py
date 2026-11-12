import bpy, os, json
from pytest import approx
from .. import ObjectService
from .. import HumanService
from .. import ExportService
from .. import FaceService
from .. import TargetService
from .. import LocationService

HUMAN_PRESET_DICT = {
        "clothes": [
            "female_casualsuit01/female_casualsuit01.mhclo"
        ],
        "color_adjustments": {},
        "eyebrows": "eyebrow001/eyebrow001.mhclo",
        "eyelashes": "eyelashes01/eyelashes01.mhclo",
        "eyes": "high-poly/high-poly.mhclo",
        "eyes_material_settings": {},
        "eyes_material_type": "PROCEDURAL_EYES",
        "hair": "long01/long01.mhclo",
        "phenotype": {
            "age": 0.5,
            "cupsize": 0.550000011920929,
            "firmness": 0.550000011920929,
            "gender": 0.0,
            "height": 0.5,
            "muscle": 0.5,
            "proportions": 0.5,
            "race": {
                "african": 0.0,
                "asian": 0.0,
                "caucasian": 1.0
            },
            "weight": 0.5
        },
        "proxy": "",
        "rig": "default",
        "skin_material_settings": {},
        "skin_material_type": "ENHANCED_SSS",
        "skin_mhmat": "middleage_caucasian_female/middleage_caucasian_female.mhmat",
        "targets": [
            {
                "target": "head-age-decr",
                "value": 1.0
            }
        ],
        "teeth": "",
        "tongue": ""
    }


def test_exportervice_exists():
    """ExportService"""
    assert ExportService is not None, "ExportService can be imported"

def create_sample_human():
    """Character to use in tests"""
    name = ObjectService.random_name()
    deserialization_settings = HumanService.get_default_deserialization_settings()
    human_info = HUMAN_PRESET_DICT.copy()
    human_info["name"] = name
    basemesh = HumanService.deserialize_from_dict(human_info, deserialization_settings)
    return basemesh

def remove_character_copy(character_copy):
    """Remove a character copy from the scene"""
    if character_copy is None:
        return
    if character_copy.parent is None:
        obj = character_copy
    else:
        obj = character_copy.parent

    for child in ObjectService.get_list_of_children(obj):
        ObjectService.delete_object(child)
    ObjectService.delete_object(obj)

def test_create_character_copy():
    """ExportService.create_character_copy()"""
    basemesh = create_sample_human()
    character_copy = ExportService.create_character_copy(basemesh)
    assert character_copy is not None, "Character copy created successfully"
    remove_character_copy(character_copy)

# def bake_shapekeys_modifiers_remove_helpers(basemesh, bake_shapekeys=True, bake_masks=False, bake_subdiv=False, remove_helpers=True, also_proxy=True):

def test_bake_modifiers():
    """ExportService.bake_modifiers_remove_helpers()"""
    basemesh = create_sample_human()
    character_copy = ExportService.create_character_copy(basemesh)
    new_basemesh = ObjectService.find_object_of_type_amongst_nearest_relatives(character_copy)

    has_mask_modifier = False
    has_subdiv_modifier = False

    for modifier in new_basemesh.modifiers:
        #print(modifier)
        if modifier.type == 'MASK':
            has_mask_modifier = True
        elif modifier.type == 'SUBSURF':
            has_subdiv_modifier = True

    assert has_mask_modifier
    assert has_subdiv_modifier

    TargetService.bake_targets(new_basemesh)

    ExportService.bake_modifiers_remove_helpers(
        new_basemesh,
        bake_masks=True,
        bake_subdiv=True,
        remove_helpers=False,
        also_proxy=False)

    has_mask_modifier = False
    has_subdiv_modifier = False

    for modifier in new_basemesh.modifiers:
        print(modifier)
        if modifier.type == 'MASK':
            has_mask_modifier = True
        elif modifier.type == 'SUBSURF':
            has_subdiv_modifier = True

    assert not has_mask_modifier
    assert not has_subdiv_modifier

    remove_character_copy(character_copy)


def test_bake_modifiers_with_shape_keys():
    """ExportService.bake_modifiers_remove_helpers() preserves shape keys"""
    basemesh = create_sample_human()
    character_copy = ExportService.create_character_copy(basemesh)
    new_basemesh = ObjectService.find_object_of_type_amongst_nearest_relatives(character_copy)

    # Load viseme shape keys so there are shape keys to preserve
    FaceService.load_targets(new_basemesh, load_microsoft_visemes=True)

    has_mask_modifier = False
    has_subdiv_modifier = False

    for modifier in new_basemesh.modifiers:
        if modifier.type == 'MASK':
            has_mask_modifier = True
        elif modifier.type == 'SUBSURF':
            has_subdiv_modifier = True

    assert has_mask_modifier, "Precondition: basemesh should have a MASK modifier"
    assert has_subdiv_modifier, "Precondition: basemesh should have a SUBSURF modifier"

    assert new_basemesh.data.shape_keys is not None, "Precondition: basemesh should have shape keys"
    sk_names_before = [kb.name for kb in new_basemesh.data.shape_keys.key_blocks if kb.name != "Basis"]
    assert len(sk_names_before) > 0, "Precondition: basemesh should have non-Basis shape keys"

    # Bake modifiers WITHOUT baking shape keys first (this used to raise NotImplementedError)
    ExportService.bake_modifiers_remove_helpers(
        new_basemesh,
        bake_masks=True,
        bake_subdiv=True,
        remove_helpers=False,
        also_proxy=False)

    has_mask_modifier = False
    has_subdiv_modifier = False

    for modifier in new_basemesh.modifiers:
        if modifier.type == 'MASK':
            has_mask_modifier = True
        elif modifier.type == 'SUBSURF':
            has_subdiv_modifier = True

    assert not has_mask_modifier, "MASK modifier should be gone after baking"
    assert not has_subdiv_modifier, "SUBSURF modifier should be gone after baking"

    assert new_basemesh.data.shape_keys is not None, "Shape keys should still exist after baking modifiers"
    sk_names_after = [kb.name for kb in new_basemesh.data.shape_keys.key_blocks if kb.name != "Basis"]
    for sk_name in sk_names_before:
        assert sk_name in sk_names_after, f"Shape key '{sk_name}' should survive modifier baking"

    remove_character_copy(character_copy)


def test_no_superfluous_objects_after_bake_with_shape_keys():
    """ExportService.bake_modifiers_remove_helpers() leaves no extra objects when shape keys are present"""
    basemesh = create_sample_human()
    character_copy = ExportService.create_character_copy(basemesh)
    new_basemesh = ObjectService.find_object_of_type_amongst_nearest_relatives(character_copy)

    # Load viseme shape keys to exercise the shape-key-preserving code path
    FaceService.load_targets(new_basemesh, load_microsoft_visemes=True)

    objects_before = set(bpy.data.objects)
    armature_count_before = sum(1 for o in bpy.data.objects if o.type == 'ARMATURE')

    ExportService.bake_modifiers_remove_helpers(
        new_basemesh,
        bake_masks=True,
        bake_subdiv=True,
        remove_helpers=False,
        also_proxy=False)

    objects_after = set(bpy.data.objects)
    armature_count_after = sum(1 for o in bpy.data.objects if o.type == 'ARMATURE')

    extra_objects = objects_after - objects_before
    assert not extra_objects, \
        f"Baking modifiers left {len(extra_objects)} unexpected extra object(s): {[o.name for o in extra_objects]}"
    assert armature_count_after == armature_count_before, \
        f"Expected {armature_count_before} armature(s) after baking but found {armature_count_after}"

    remove_character_copy(character_copy)

def test_bake_stylized_skin_exports_plain_pbr(tmp_path):
    """ExportService.bake_stylized_skin(): a stylized character exports to glTF with one albedo for the body and no custom nodes"""
    import numpy as np
    from .. import MaterialService

    human_info = HUMAN_PRESET_DICT.copy()
    human_info["name"] = ObjectService.random_name()
    human_info["clothes"] = []
    human_info["hair"] = ""
    human_info["skin_material_type"] = "STYLIZED"
    basemesh = HumanService.deserialize_from_dict(human_info, HumanService.get_default_deserialization_settings())
    source_material = MaterialService.get_material(basemesh)
    assert MaterialService.identify_material(source_material) == "stylized_skin"

    character_copy = None
    try:
        character_copy = ExportService.create_character_copy(basemesh)
        new_basemesh = ObjectService.find_object_of_type_amongst_nearest_relatives(character_copy)
        albedos = ExportService.bake_stylized_skin(new_basemesh, destination=str(tmp_path))

        assert list(albedos.keys()) == [new_basemesh.name]
        albedo = albedos[new_basemesh.name]
        assert tuple(albedo.size) == (2048, 2048)
        assert os.path.dirname(bpy.path.abspath(albedo.filepath)) == str(tmp_path)

        # The baked albedo is the warm skin tone, not black
        pixels = np.empty(2048 * 2048 * 4, dtype=np.float32)
        albedo.pixels.foreach_get(pixels)
        rgb = pixels.reshape(-1, 4)[:, :3]
        covered = rgb[rgb.max(axis=1) > 0.05]
        assert len(covered) > 0.2 * 2048 * 2048
        assert covered[:, 0].mean() > covered[:, 2].mean() + 0.1

        material = MaterialService.get_material(new_basemesh)
        assert material is not source_material
        node_types = {node.type for node in material.node_tree.nodes}
        assert node_types == {"OUTPUT_MATERIAL", "BSDF_PRINCIPLED", "TEX_IMAGE"}
        principled = material.node_tree.nodes["Principled BSDF"]
        assert principled.inputs["Base Color"].links[0].from_node.image == albedo
        assert principled.inputs["Specular IOR Level"].default_value == approx(0.35)

        # The source character keeps its stylized skin
        assert MaterialService.identify_material(MaterialService.get_material(basemesh)) == "stylized_skin"

        ExportService.bake_modifiers_remove_helpers(new_basemesh, remove_helpers=True)
        ObjectService.deselect_and_deactivate_all()
        ObjectService.activate_blender_object(new_basemesh)
        gltf_path = str(tmp_path / "stylized.gltf")
        bpy.ops.export_scene.gltf(filepath=gltf_path, export_format='GLTF_SEPARATE', use_selection=True,
                                  export_animations=False, export_morph=False, export_skins=False)
        with open(gltf_path, "r", encoding="utf-8") as gltf_file:
            gltf = json.load(gltf_file)

        assert len(gltf["materials"]) == 1
        gltf_material = gltf["materials"][0]
        base_color_texture = gltf_material["pbrMetallicRoughness"]["baseColorTexture"]["index"]
        base_color_image = gltf["images"][gltf["textures"][base_color_texture]["source"]]
        assert "albedo" in base_color_image["uri"]
        assert len([image for image in gltf["images"] if "albedo" in image["uri"]]) == 1
        assert "metallicRoughnessTexture" in gltf_material["pbrMetallicRoughness"]
        for path in os.listdir(tmp_path):
            assert os.path.isfile(os.path.join(tmp_path, path))
    finally:
        remove_character_copy(character_copy)
        remove_character_copy(basemesh)
