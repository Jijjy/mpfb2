import bpy
from pytest import approx
from .. import dynamic_import
from .. import ObjectService
from .. import NodeService
NodeWrapperStylizedHair = dynamic_import("mpfb.entities.nodemodel.v2.materials.nodewrapperstylizedhair", "NodeWrapperStylizedHair")


def test_stylized_hair_shader():
    """Spec section 9: root-to-tip gradient (root 15% darker), anisotropy 0.8 along the strand, roughness 0.45, no alpha."""
    node_tree = NodeService.create_node_tree(ObjectService.random_name())
    NodeWrapperStylizedHair.create_instance(node_tree)
    assert NodeWrapperStylizedHair.validate_tree_against_original_def(fail_hard=True, node_tree=node_tree)

    nodes = node_tree.nodes
    principled = nodes["Principled BSDF"]
    assert principled.inputs["Roughness"].default_value == approx(0.45)
    assert principled.inputs["Anisotropic"].default_value == approx(0.8)
    assert not principled.inputs["Alpha"].is_linked
    assert principled.inputs["Alpha"].default_value == approx(1.0)
    assert principled.inputs["Tangent"].links[0].from_node.name == "Strand tangent"
    assert nodes["Strand tangent"].direction_type == "UV_MAP"

    root = nodes["HairRoot"].outputs["Color"].default_value
    tip = nodes["HairTip"].outputs["Color"].default_value
    for channel in range(3):
        assert root[channel] == approx(tip[channel] * 0.85)

    # The gradient runs along V of the cards UV map, from HairRoot (V=0) to HairTip (V=1)
    mix_inputs = {socket.identifier: socket for socket in nodes["Root to tip"].inputs}
    assert mix_inputs["Factor_Float"].links[0].from_socket.name == "Y"
    assert mix_inputs["A_Color"].links[0].from_node.name == "HairRoot"
    assert mix_inputs["B_Color"].links[0].from_node.name == "HairTip"
    assert principled.inputs["Base Color"].links[0].from_node.name == "Root to tip"
    assert principled.outputs["BSDF"].links[0].to_node.name == "Material Output"
    NodeService.destroy_node_tree(node_tree)
