import bpy
from pytest import approx
from .. import dynamic_import
from .. import ObjectService
from .. import NodeService
NodeWrapperStylizedHair = dynamic_import("mpfb.entities.nodemodel.v2.materials.nodewrapperstylizedhair", "NodeWrapperStylizedHair")


def _source(node, identifier):
    return {socket.identifier: socket for socket in node.inputs}[identifier].links[0].from_node.name


def test_stylized_hair_shader():
    """Spec section 6 / ticket 67: matte (no anisotropic sheen), root-to-tip gradient (root 15% darker) with painted
    strand grooves and a painted highlight band in the albedo, no alpha."""
    node_tree = NodeService.create_node_tree(ObjectService.random_name())
    NodeWrapperStylizedHair.create_instance(node_tree)
    assert NodeWrapperStylizedHair.validate_tree_against_original_def(fail_hard=True, node_tree=node_tree)

    nodes = node_tree.nodes
    principled = nodes["Principled BSDF"]
    assert principled.inputs["Roughness"].default_value >= 0.8
    assert principled.inputs["Anisotropic"].default_value == approx(0.0)
    assert not principled.inputs["Tangent"].is_linked
    assert not principled.inputs["Alpha"].is_linked
    assert principled.inputs["Alpha"].default_value == approx(1.0)
    assert principled.outputs["BSDF"].links[0].to_node.name == "Material Output"

    root = nodes["HairRoot"].outputs["Color"].default_value
    tip = nodes["HairTip"].outputs["Color"].default_value
    for channel in range(3):
        assert root[channel] == approx(tip[channel] * 0.85)

    # The gradient runs along V of the cards UV map, from HairRoot (V=0) to HairTip (V=1)
    mix_inputs = {socket.identifier: socket for socket in nodes["Root to tip"].inputs}
    assert mix_inputs["Factor_Float"].links[0].from_socket.name == "Y"
    assert mix_inputs["A_Color"].links[0].from_node.name == "HairRoot"
    assert mix_inputs["B_Color"].links[0].from_node.name == "HairTip"

    # Albedo: gradient times the groove shade, then the highlight band mixed over it
    assert principled.inputs["Base Color"].links[0].from_node.name == "Highlight"
    assert _source(nodes["Highlight"], "A_Color") == "Grooved"
    assert _source(nodes["Highlight"], "B_Color") == "Highlight lift"
    assert _source(nodes["Highlight lift"], "A_Color") == "Highlight colour"
    assert _source(nodes["Highlight"], "Factor_Float") == "Band strength"
    assert nodes["Grooved"].blend_type == "MULTIPLY"
    assert _source(nodes["Grooved"], "A_Color") == "Root to tip"
    assert _source(nodes["Grooved"], "B_Color") == "Groove shade"
    # Grooves vary across U with a whole number of periods, so they meet at the tube seam
    phase = nodes["Groove phase"]
    assert phase.inputs[0].links[0].from_socket.name == "X"
    assert float(phase.inputs[1].default_value).is_integer()
    # The band is placed along V
    assert _source(nodes["Band offset"], "Value") == "Separate UV"
    assert nodes["Band offset"].inputs[0].links[0].from_socket.name == "Y"
    NodeService.destroy_node_tree(node_tree)
