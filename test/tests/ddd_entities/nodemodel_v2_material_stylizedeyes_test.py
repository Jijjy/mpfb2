import bpy
from pytest import approx
from .. import dynamic_import
from .. import ObjectService
from .. import NodeService
NodeWrapperStylizedEyes = dynamic_import("mpfb.entities.nodemodel.v2.materials.nodewrapperstylizedeyes", "NodeWrapperStylizedEyes")
NodeWrapperMpfbStylizedEyes = dynamic_import("mpfb.entities.nodemodel.v2.materials.nodewrapperstylizedeyes", "NodeWrapperMpfbStylizedEyes")


def test_stylized_eyes_shader():
    """Spec section 5.2: one group node carrying the eye settings key set, one opaque Principled
    BSDF with roughness 0.05 and coat 0.5, no transmission, no alpha, catchlight emission 1.5."""
    node_tree = NodeService.create_node_tree(ObjectService.random_name())
    NodeWrapperStylizedEyes.create_instance(node_tree)
    assert NodeWrapperStylizedEyes.validate_tree_against_original_def(fail_hard=True, node_tree=node_tree)
    assert NodeWrapperMpfbStylizedEyes.validate_tree_against_original_def(fail_hard=True)

    group_node = node_tree.nodes["StylizedEyes"]
    assert group_node.outputs["BSDF"].links[0].to_node.name == "Material Output"
    settings = NodeService.get_socket_default_values(group_node)
    assert list(settings["ScleraColor"])[:3] == approx([0.92, 0.90, 0.88])
    assert settings["PupilSize"] == approx(0.35)
    assert settings["LimbalRingWidth"] == approx(0.15)
    assert settings["CatchlightStrength"] == approx(1.5)
    assert settings["Roughness"] == approx(0.05)
    assert settings["Coat"] == approx(0.5)

    group_nodes = group_node.node_tree.nodes
    principled = group_nodes["Principled BSDF"]
    assert principled.inputs["Roughness"].links[0].from_socket.name == "Roughness"
    assert principled.inputs["Coat Weight"].links[0].from_socket.name == "Coat"
    assert principled.inputs["Emission Strength"].links[0].from_node.name == "Catchlight emission"
    assert not principled.inputs["Alpha"].is_linked
    assert principled.inputs["Alpha"].default_value == approx(1.0)
    assert not principled.inputs["Transmission Weight"].is_linked
    assert principled.inputs["Transmission Weight"].default_value == approx(0.0)
    assert not any(node.bl_idname == "ShaderNodeBsdfTransparent" for node in group_nodes)

    # The catchlight ellipse (iris-local units) overlaps the pupil edge, where white on black
    # reads, and stays inside the iris, clear of the limbal ring
    center_x = group_nodes["Catchlight X"].inputs[1].default_value
    center_y = group_nodes["Catchlight center"].inputs["Y"].default_value
    center_r = (center_x ** 2 + center_y ** 2) ** 0.5
    size = settings["CatchlightSize"]
    assert center_r - size < settings["PupilSize"] < center_r
    assert center_r + size < 1.0 - settings["LimbalRingWidth"]
    NodeService.destroy_node_tree(node_tree)
