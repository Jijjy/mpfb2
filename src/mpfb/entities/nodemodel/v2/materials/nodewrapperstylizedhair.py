"""Stylized hair material (STYLIZED_SPEC.md section 6).

A matte Principled BSDF whose look is painted into the albedo, not made by a specular highlight
(ticket 67: the glossy anisotropic version read as plastic on the solid CLUMP tubes):

- a root-to-tip colour gradient from HairRoot to HairTip, driven by the V coordinate of the
  cards UV map (V runs along the strand, 0 at the root, see HairCardService). By default the
  root is 25% darker than the tip.
- painted strand grooves: dark lines along the strand, STRAND_GROOVES of them across U (around
  a CLUMP tube, across a ribbon). U only enters through a cosine with a whole number of periods,
  so the lines meet at the tube seam (U 0 = U 1). Their phase wobbles with a noise on the object
  coordinates, which is seam free too, so each clump gets its own wavy lines.
- a painted highlight band across the strands near HIGHLIGHT_V, jittered by the same noise and
  broken up by the grooves: the gradient colour brightened by HIGHLIGHT_VALUE and lifted toward
  white, mixed into the albedo, so it is lit like the rest of the hair and does not shine
  or move with the view.
- contact and depth cues (ticket 71), multiplied over all of the above:
  - root shade: the first ROOT_SHADE_LENGTH of V darkens to ROOT_SHADE at the root, so locks read as growing out
    of the scalp, and the hair cap (all V 0) sits in that shade under the clumps.
  - cel crevice darkening: an Ambient Occlusion node (CREVICE_DISTANCE, works in Cycles and EEVEE) cut at
    CREVICE_THRESHOLD by a narrow smoothstep, so the gaps between locks and where hair meets the head go flat dark
    (CREVICE_SHADE) instead of a soft gradient.
- roughness 0.85, specular IOR level 0.2 and no anisotropy: the surface itself is matte.
- alpha only on the soft hairline: the hair cap writes HAIRLINE_ATTRIBUTE (0 inside, 1 on its outer border, see
  HairCardService), and alpha is 1 minus it, so the cap's dark rim fades over the skin as a contact shadow. Meshes
  without the attribute read 0 there and stay fully opaque; clump tubes and strays are always opaque.
"""

import math

from .abstractmaterialwrapper import AbstractMaterialWrapper

from .....services import LogService
_LOG = LogService.get_logger("material.stylizedhair")

# The UV map the hair cards are laid out on. This matches HairCardService.CARDS_UV_MAP; it is
# repeated here since the entities layer does not import the hair card service.
HAIR_UV_MAP = "UVMap"

# The root is this much of the tip colour (25% darker)
ROOT_DARKENING = 0.75

DEFAULT_HAIR_TIP = [0.30, 0.17, 0.09, 1.0]
DEFAULT_HAIR_ROOT = [DEFAULT_HAIR_TIP[0] * ROOT_DARKENING, DEFAULT_HAIR_TIP[1] * ROOT_DARKENING, DEFAULT_HAIR_TIP[2] * ROOT_DARKENING, 1.0]

ROUGHNESS = 0.85
SPECULAR = 0.2

# Painted strand grooves: how many lines across U (a whole number, so they meet at the tube seam),
# how dark the middle of a groove gets (0 none, 1 black), and how far the noise shifts them, in periods
STRAND_GROOVES = 8
GROOVE_DEPTH = 0.5
GROOVE_WOBBLE = 0.6
# Power on the groove profile: above 1 narrows the dark lines
GROOVE_SHARPNESS = 1.5
# Scale of the object-space noise that wobbles the grooves and the highlight band
WOBBLE_SCALE = 6.0

# Painted highlight band: centre along V, half width, how far the noise moves it along V, how much
# brighter than the gradient colour it is, how far that is then lifted toward white (so dark hair
# still gets a visible band), and how much of it shows at most
HIGHLIGHT_V = 0.3
HIGHLIGHT_WIDTH = 0.08
HIGHLIGHT_JITTER = 0.08
HIGHLIGHT_VALUE = 2.4
HIGHLIGHT_LIFT = 0.06
HIGHLIGHT_STRENGTH = 0.7

# Root shade: how far along V it reaches and how dark the very root is (multiplier)
ROOT_SHADE_LENGTH = 0.2
ROOT_SHADE = 0.45
# Cel crevice darkening: occlusion ray length (metres), the AO value at the cut, half the width of the cut, and the
# multiplier in the crevices
CREVICE_DISTANCE = 0.02
CREVICE_THRESHOLD = 0.55
CREVICE_SOFTNESS = 0.08
CREVICE_SHADE = 0.4

# Point attribute the hair cap carries: 1 at its outer border, 0 from HAIRLINE_WIDTH inside (HairCardService writes it)
HAIRLINE_ATTRIBUTE = "mpfb_hairline"


def _node_def(node_class, name, location):
    return {
        "attribute_values": {"location": location},
        "class": node_class,
        "input_socket_values": {},
        "label": name,
        "name": name,
        "output_socket_values": {}
        }


def _link(from_node, from_socket, to_node, to_socket):
    return {"from_node": from_node, "from_socket": from_socket, "to_node": to_node, "to_socket": to_socket}


_ORIGINAL_TREE_DEF = {
    "links": [
        # Root-to-tip gradient
        _link("HairUV", "UV", "Separate UV", "Vector"),
        _link("Separate UV", "Y", "Root to tip", "Factor_Float"),
        _link("HairRoot", "Color", "Root to tip", "A_Color"),
        _link("HairTip", "Color", "Root to tip", "B_Color"),
        # Noise on object coordinates: wobbles the grooves and the band, seam free
        _link("Wobble coordinates", "Object", "Wobble noise", "Vector"),
        _link("Wobble noise", "Fac", "Groove wobble", "Value"),
        # Grooves: dark = ((1 - cos(2 pi (n U + wobble))) / 2)^2, shade = 1 - depth * dark
        _link("Separate UV", "X", "Groove phase", "Value"),
        _link("Groove wobble", "Value", "Groove phase", "Value_002"),
        _link("Groove phase", "Value", "Groove angle", "Value"),
        _link("Groove angle", "Value", "Groove cosine", "Value"),
        _link("Groove cosine", "Value", "Groove profile", "Value"),
        _link("Groove profile", "Value", "Groove sharpen", "Value"),
        _link("Groove sharpen", "Value", "Groove shade", "Value"),
        _link("Root to tip", "Result_Color", "Grooved", "A_Color"),
        _link("Groove shade", "Value", "Grooved", "B_Color"),
        # Highlight band: smooth bump in V around a jittered centre, cut by the grooves
        _link("Wobble noise", "Fac", "Band centre", "Value"),
        _link("Separate UV", "Y", "Band offset", "Value"),
        _link("Band centre", "Value", "Band offset", "Value_001"),
        _link("Band offset", "Value", "Band distance", "Value"),
        _link("Band distance", "Value", "Band", "Value"),
        _link("Band", "Result", "Band strength", "Value"),
        _link("Groove shade", "Value", "Band strength", "Value_001"),
        _link("Root to tip", "Result_Color", "Highlight colour", "Color"),
        _link("Band strength", "Value", "Highlight", "Factor_Float"),
        _link("Grooved", "Result_Color", "Highlight", "A_Color"),
        _link("Highlight colour", "Color", "Highlight lift", "A_Color"),
        _link("Highlight lift", "Result_Color", "Highlight", "B_Color"),
        # Contact and depth: root shade times the cel cut of the ambient occlusion, multiplied over the albedo
        _link("Separate UV", "Y", "Root shade", "Value"),
        _link("Crevice AO", "AO", "Crevice cut", "Value"),
        _link("Root shade", "Result", "Contact shade", "Value"),
        _link("Crevice cut", "Result", "Contact shade", "Value_001"),
        _link("Highlight", "Result_Color", "Shaded", "A_Color"),
        _link("Contact shade", "Value", "Shaded", "B_Color"),
        _link("Shaded", "Result_Color", "Principled BSDF", "Base Color"),
        # Soft hairline: the cap fades out over its border
        _link("Hairline", "Fac", "Hairline alpha", "Value_001"),
        _link("Hairline alpha", "Value", "Principled BSDF", "Alpha"),
        _link("Principled BSDF", "BSDF", "Material Output", "Surface")
        ],
    "nodes": [
        _node_def("ShaderNodeUVMap", "HairUV", [-1600.0, 300.0]),
        _node_def("ShaderNodeSeparateXYZ", "Separate UV", [-1400.0, 300.0]),
        _node_def("ShaderNodeRGB", "HairRoot", [-1400.0, 650.0]),
        _node_def("ShaderNodeRGB", "HairTip", [-1400.0, 450.0]),
        _node_def("ShaderNodeMix", "Root to tip", [-1100.0, 550.0]),
        _node_def("ShaderNodeTexCoord", "Wobble coordinates", [-1600.0, -100.0]),
        _node_def("ShaderNodeTexNoise", "Wobble noise", [-1400.0, -100.0]),
        _node_def("ShaderNodeMath", "Groove wobble", [-1200.0, 50.0]),
        _node_def("ShaderNodeMath", "Groove phase", [-1000.0, 150.0]),
        _node_def("ShaderNodeMath", "Groove angle", [-850.0, 150.0]),
        _node_def("ShaderNodeMath", "Groove cosine", [-700.0, 150.0]),
        _node_def("ShaderNodeMath", "Groove profile", [-550.0, 150.0]),
        _node_def("ShaderNodeMath", "Groove sharpen", [-400.0, 150.0]),
        _node_def("ShaderNodeMath", "Groove shade", [-250.0, 150.0]),
        _node_def("ShaderNodeMix", "Grooved", [-50.0, 450.0]),
        _node_def("ShaderNodeMath", "Band centre", [-1200.0, -250.0]),
        _node_def("ShaderNodeMath", "Band offset", [-1000.0, -250.0]),
        _node_def("ShaderNodeMath", "Band distance", [-850.0, -250.0]),
        _node_def("ShaderNodeMapRange", "Band", [-700.0, -250.0]),
        _node_def("ShaderNodeMath", "Band strength", [-450.0, -250.0]),
        _node_def("ShaderNodeHueSaturation", "Highlight colour", [-450.0, 650.0]),
        _node_def("ShaderNodeMix", "Highlight lift", [-250.0, 650.0]),
        _node_def("ShaderNodeMix", "Highlight", [150.0, 350.0]),
        _node_def("ShaderNodeMapRange", "Root shade", [-700.0, -500.0]),
        _node_def("ShaderNodeAmbientOcclusion", "Crevice AO", [-900.0, -750.0]),
        _node_def("ShaderNodeMapRange", "Crevice cut", [-700.0, -750.0]),
        _node_def("ShaderNodeMath", "Contact shade", [-450.0, -600.0]),
        _node_def("ShaderNodeMix", "Shaded", [350.0, 350.0]),
        _node_def("ShaderNodeAttribute", "Hairline", [150.0, -100.0]),
        _node_def("ShaderNodeMath", "Hairline alpha", [350.0, -100.0]),
        _node_def("ShaderNodeBsdfPrincipled", "Principled BSDF", [600.0, 300.0]),
        _node_def("ShaderNodeOutputMaterial", "Material Output", [950.0, 300.0])
        ]
    }

_LOCATIONS = {node["name"]: node["attribute_values"]["location"] for node in _ORIGINAL_TREE_DEF["nodes"]}


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
            attribute_values = dict(attribute_values or {})
            attribute_values["location"] = _LOCATIONS[name]
            nodes[name] = AbstractMaterialWrapper.node(node_class_name, node_tree, name, label=name, input_socket_values=input_socket_values, attribute_values=attribute_values, output_socket_values=output_socket_values)

        def math_node(name, operation, *values):
            inputs = {identifier: value for identifier, value in zip(("Value", "Value_001", "Value_002"), values) if value is not None}
            node("ShaderNodeMath", name, input_socket_values=inputs, attribute_values={"operation": operation})

        def link(from_node, from_socket, to_node, to_socket):
            AbstractMaterialWrapper.create_link(node_tree, nodes[from_node], from_socket, nodes[to_node], to_socket)

        nodes["Material Output"].location = _LOCATIONS["Material Output"]

        node("ShaderNodeUVMap", "HairUV", attribute_values={"uv_map": HAIR_UV_MAP})
        node("ShaderNodeSeparateXYZ", "Separate UV")
        node("ShaderNodeRGB", "HairRoot", output_socket_values={"Color": hair_root})
        node("ShaderNodeRGB", "HairTip", output_socket_values={"Color": hair_tip})
        node("ShaderNodeMix", "Root to tip", attribute_values={"data_type": "RGBA", "clamp_factor": True})

        node("ShaderNodeTexCoord", "Wobble coordinates")
        node("ShaderNodeTexNoise", "Wobble noise", input_socket_values={"Scale": WOBBLE_SCALE, "Detail": 1.0, "Roughness": 0.5})
        # Noise is about 0.5 on average: centre it so the wobble shifts both ways
        math_node("Groove wobble", "MULTIPLY_ADD", None, GROOVE_WOBBLE, -0.5 * GROOVE_WOBBLE)
        math_node("Groove phase", "MULTIPLY_ADD", None, float(STRAND_GROOVES), None)
        math_node("Groove angle", "MULTIPLY", None, 2.0 * math.pi)
        math_node("Groove cosine", "COSINE")
        math_node("Groove profile", "MULTIPLY_ADD", None, -0.5, 0.5)
        math_node("Groove sharpen", "POWER", None, GROOVE_SHARPNESS)
        math_node("Groove shade", "MULTIPLY_ADD", None, -GROOVE_DEPTH, 1.0)
        node("ShaderNodeMix", "Grooved", input_socket_values={"Factor_Float": 1.0}, attribute_values={"data_type": "RGBA", "blend_type": "MULTIPLY"})

        math_node("Band centre", "MULTIPLY_ADD", None, HIGHLIGHT_JITTER, HIGHLIGHT_V - 0.5 * HIGHLIGHT_JITTER)
        math_node("Band offset", "SUBTRACT")
        math_node("Band distance", "ABSOLUTE")
        node("ShaderNodeMapRange", "Band", input_socket_values={"From Min": 0.0, "From Max": HIGHLIGHT_WIDTH, "To Min": HIGHLIGHT_STRENGTH, "To Max": 0.0},
             attribute_values={"data_type": "FLOAT", "interpolation_type": "SMOOTHSTEP", "clamp": True})
        # Scaled by the groove shade so the grooves cut through the band
        math_node("Band strength", "MULTIPLY")
        node("ShaderNodeHueSaturation", "Highlight colour", input_socket_values={"Value": HIGHLIGHT_VALUE, "Saturation": 1.3})
        node("ShaderNodeMix", "Highlight lift", input_socket_values={"Factor_Float": HIGHLIGHT_LIFT, "B_Color": [1.0, 1.0, 1.0, 1.0]},
             attribute_values={"data_type": "RGBA"})
        node("ShaderNodeMix", "Highlight", attribute_values={"data_type": "RGBA", "clamp_factor": True})

        node("ShaderNodeMapRange", "Root shade", input_socket_values={"From Min": 0.0, "From Max": ROOT_SHADE_LENGTH, "To Min": ROOT_SHADE, "To Max": 1.0},
             attribute_values={"data_type": "FLOAT", "interpolation_type": "SMOOTHSTEP", "clamp": True})
        node("ShaderNodeAmbientOcclusion", "Crevice AO", input_socket_values={"Distance": CREVICE_DISTANCE}, attribute_values={"samples": 16})
        node("ShaderNodeMapRange", "Crevice cut", input_socket_values={
            "From Min": CREVICE_THRESHOLD - CREVICE_SOFTNESS, "From Max": CREVICE_THRESHOLD + CREVICE_SOFTNESS,
            "To Min": CREVICE_SHADE, "To Max": 1.0},
             attribute_values={"data_type": "FLOAT", "interpolation_type": "SMOOTHSTEP", "clamp": True})
        math_node("Contact shade", "MULTIPLY")
        node("ShaderNodeMix", "Shaded", input_socket_values={"Factor_Float": 1.0}, attribute_values={"data_type": "RGBA", "blend_type": "MULTIPLY"})
        node("ShaderNodeAttribute", "Hairline", attribute_values={"attribute_type": "GEOMETRY", "attribute_name": HAIRLINE_ATTRIBUTE})
        math_node("Hairline alpha", "SUBTRACT", 1.0, None)

        node("ShaderNodeBsdfPrincipled", "Principled BSDF", input_socket_values={
            "Roughness": ROUGHNESS,
            "Specular IOR Level": SPECULAR,
            "Anisotropic": 0.0,
            })

        for tree_link in _ORIGINAL_TREE_DEF["links"]:
            link(tree_link["from_node"], tree_link["from_socket"], tree_link["to_node"], tree_link["to_socket"])


NodeWrapperStylizedHair = _NodeWrapperStylizedHair()
