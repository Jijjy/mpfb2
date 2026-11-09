"""Stylized hair material (STYLIZED_SPEC.md section 9).

A single Principled BSDF fed by:

- a root-to-tip colour gradient from HairRoot to HairTip, driven by the V coordinate of the
  cards UV map (V runs along the strand, 0 at the root, see HairCardService). By default the
  root is 15% darker than the tip.
- an anisotropic sheen band: anisotropy 0.8, with the tangent taken from the cards UV map (V
  along the strand). Blender's microfacet anisotropy stretches the highlight along the tangent,
  and the UV tangent points along U, across the strand, so the highlight becomes a band across
  the hair. (A tangent along V would streak the highlight down the strands instead; checked
  by render, see ticket MUVBME.)
- roughness 0.45
- no alpha: the Alpha socket stays at 1.0 and is never linked.
"""

import bpy

from .abstractmaterialwrapper import AbstractMaterialWrapper

from .....services import LogService
_LOG = LogService.get_logger("material.stylizedhair")

# The UV map the hair cards are laid out on. This matches HairCardService.CARDS_UV_MAP; it is
# repeated here since the entities layer does not import the hair card service.
HAIR_UV_MAP = "UVMap"

# The root is this much of the tip colour (15% darker)
ROOT_DARKENING = 0.85

DEFAULT_HAIR_TIP = [0.30, 0.17, 0.09, 1.0]
DEFAULT_HAIR_ROOT = [DEFAULT_HAIR_TIP[0] * ROOT_DARKENING, DEFAULT_HAIR_TIP[1] * ROOT_DARKENING, DEFAULT_HAIR_TIP[2] * ROOT_DARKENING, 1.0]

ANISOTROPY = 0.8
ROUGHNESS = 0.45


def _node_def(node_class, name, location):
    return {
        "attribute_values": {"location": location},
        "class": node_class,
        "input_socket_values": {},
        "label": name,
        "name": name,
        "output_socket_values": {}
        }


_ORIGINAL_TREE_DEF = {
    "links": [
        {"from_node": "HairUV", "from_socket": "UV", "to_node": "Separate UV", "to_socket": "Vector"},
        {"from_node": "Separate UV", "from_socket": "Y", "to_node": "Root to tip", "to_socket": "Factor_Float"},
        {"from_node": "HairRoot", "from_socket": "Color", "to_node": "Root to tip", "to_socket": "A_Color"},
        {"from_node": "HairTip", "from_socket": "Color", "to_node": "Root to tip", "to_socket": "B_Color"},
        {"from_node": "Root to tip", "from_socket": "Result_Color", "to_node": "Principled BSDF", "to_socket": "Base Color"},
        {"from_node": "Strand tangent", "from_socket": "Tangent", "to_node": "Principled BSDF", "to_socket": "Tangent"},
        {"from_node": "Principled BSDF", "from_socket": "BSDF", "to_node": "Material Output", "to_socket": "Surface"}
        ],
    "nodes": [
        _node_def("ShaderNodeUVMap", "HairUV", [-800.0, 300.0]),
        _node_def("ShaderNodeSeparateXYZ", "Separate UV", [-600.0, 300.0]),
        _node_def("ShaderNodeRGB", "HairRoot", [-600.0, 150.0]),
        _node_def("ShaderNodeRGB", "HairTip", [-600.0, -50.0]),
        _node_def("ShaderNodeMix", "Root to tip", [-350.0, 200.0]),
        _node_def("ShaderNodeTangent", "Strand tangent", [-350.0, -150.0]),
        _node_def("ShaderNodeBsdfPrincipled", "Principled BSDF", [0.0, 300.0]),
        _node_def("ShaderNodeOutputMaterial", "Material Output", [400.0, 300.0])
        ]
    }


class _NodeWrapperStylizedHair(AbstractMaterialWrapper):

    def __init__(self):
        AbstractMaterialWrapper.__init__(self, "StylizedHair", _ORIGINAL_TREE_DEF)

    def setup_group_nodes(self, node_tree, nodes, mhmat=None):
        _LOG.debug("setup_group_nodes", mhmat)

        hair_tip = list(DEFAULT_HAIR_TIP)
        hair_root = list(DEFAULT_HAIR_ROOT)
        if mhmat:
            # A plain diffuse colour on the hair material is taken as the tip colour; the root
            # keeps the 15% darkening relative to it.
            diffuse_color = mhmat.get_value("diffuseColor")
            if diffuse_color:
                hair_tip = [float(diffuse_color[0]), float(diffuse_color[1]), float(diffuse_color[2]), 1.0]
                hair_root = [hair_tip[0] * ROOT_DARKENING, hair_tip[1] * ROOT_DARKENING, hair_tip[2] * ROOT_DARKENING, 1.0]

        def node(node_class_name, name, input_socket_values=None, attribute_values=None, output_socket_values=None):
            nodes[name] = AbstractMaterialWrapper.node(node_class_name, node_tree, name, label=name, input_socket_values=input_socket_values, attribute_values=attribute_values, output_socket_values=output_socket_values)

        def link(from_node, from_socket, to_node, to_socket):
            AbstractMaterialWrapper.create_link(node_tree, nodes[from_node], from_socket, nodes[to_node], to_socket)

        nodes["Material Output"].location = [400.0, 300.0]

        node("ShaderNodeUVMap", "HairUV", attribute_values={"location": [-800.0, 300.0], "uv_map": HAIR_UV_MAP})
        node("ShaderNodeSeparateXYZ", "Separate UV", attribute_values={"location": [-600.0, 300.0]})
        node("ShaderNodeRGB", "HairRoot", attribute_values={"location": [-600.0, 150.0]}, output_socket_values={"Color": hair_root})
        node("ShaderNodeRGB", "HairTip", attribute_values={"location": [-600.0, -50.0]}, output_socket_values={"Color": hair_tip})
        node("ShaderNodeMix", "Root to tip", attribute_values={"location": [-350.0, 200.0], "data_type": "RGBA", "clamp_factor": True})
        node("ShaderNodeTangent", "Strand tangent", attribute_values={"location": [-350.0, -150.0], "direction_type": "UV_MAP", "uv_map": HAIR_UV_MAP})
        node("ShaderNodeBsdfPrincipled", "Principled BSDF", attribute_values={"location": [0.0, 300.0]}, input_socket_values={
            "Roughness": ROUGHNESS,
            "Anisotropic": ANISOTROPY,
            "Alpha": 1.0
            })

        for tree_link in _ORIGINAL_TREE_DEF["links"]:
            link(tree_link["from_node"], tree_link["from_socket"], tree_link["to_node"], tree_link["to_socket"])


NodeWrapperStylizedHair = _NodeWrapperStylizedHair()
