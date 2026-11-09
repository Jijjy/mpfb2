import bpy
from pytest import approx
from .. import dynamic_import
from .. import ObjectService
from .. import NodeService
from .. import MaterialService
NodeWrapperStylizedSkin = dynamic_import("mpfb.entities.nodemodel.v2.materials.nodewrapperstylizedskin", "NodeWrapperStylizedSkin")
NodeWrapperMpfbStylizedSkin = dynamic_import("mpfb.entities.nodemodel.v2.materials.nodewrapperstylizedskin", "NodeWrapperMpfbStylizedSkin")
skin_tone_swatches = dynamic_import("mpfb.entities.nodemodel.v2.materials.nodewrapperstylizedskin", "skin_tone_swatches")
srgb_to_linear = dynamic_import("mpfb.entities.nodemodel.v2.materials.nodewrapperstylizedskin", "srgb_to_linear")


def test_stylized_skin_shader():
    """Spec section 7.1: one group node with the skin inputs and their defaults, one Principled BSDF,
    the five sty01 maps feeding the group, 12 skin tone swatches, identified as stylized_skin."""
    material = bpy.data.materials.new(ObjectService.random_name())
    material.use_nodes = True
    node_tree = material.node_tree
    NodeWrapperStylizedSkin.create_instance(node_tree)
    assert NodeWrapperStylizedSkin.validate_tree_against_original_def(fail_hard=True, node_tree=node_tree)
    assert NodeWrapperMpfbStylizedSkin.validate_tree_against_original_def(fail_hard=True)
    assert MaterialService.identify_material(material) == "stylized_skin"

    group_node = node_tree.nodes["StylizedSkin"]
    assert group_node.outputs["BSDF"].links[0].to_node.name == "Material Output"
    settings = NodeService.get_socket_default_values(group_node)
    assert list(settings["SkinTone"])[:3] == approx(srgb_to_linear([0.80, 0.60, 0.48]))
    assert list(settings["BloodTint"])[:3] == approx(srgb_to_linear([0.85, 0.35, 0.30]))
    assert settings["BloodStrength"] == approx(0.25)
    assert settings["CavityStrength"] == approx(0.4)
    assert settings["GradientStrength"] == approx(0.12)
    assert (settings["RoughnessMin"], settings["RoughnessMax"]) == approx((0.4, 0.6))
    assert settings["SpecularIORLevel"] == approx(0.35)
    assert settings["SubsurfaceWeight"] == approx(0.05)
    assert list(group_node.inputs["SubsurfaceRadius"].default_value) == approx([1.0, 0.35, 0.2])
    for name in ["BloodMap", "CavityMap", "RoughnessMask", "NormalMap", "Makeup", "MakeupAlpha"]:
        image_node = group_node.inputs[name].links[0].from_node
        assert image_node.bl_idname == "ShaderNodeTexImage" and image_node.image is not None

    group_nodes = group_node.node_tree.nodes
    assert [node.bl_idname for node in group_nodes].count("ShaderNodeBsdfPrincipled") == 1
    principled = group_nodes["Principled BSDF"]
    for socket in ["Base Color", "Roughness", "Specular IOR Level", "Subsurface Weight", "Subsurface Radius", "Normal"]:
        assert principled.inputs[socket].is_linked

    swatches = skin_tone_swatches()
    assert len(swatches) == 12
    assert list(settings["SkinTone"]) == approx(dict(swatches)["Default"])
    bpy.data.materials.remove(material)
