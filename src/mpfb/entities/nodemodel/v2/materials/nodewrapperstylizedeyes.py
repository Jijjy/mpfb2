"""Stylized eye material, STYLIZED_EYES (STYLIZED_SPEC.md section 5.2).

An eye material type next to MAKESKIN, GAMEENGINE and PROCEDURAL_EYES; it replaces none of
them. The material is one group node, "StylizedEyes" (node group MpfbStylizedEyes), wired to
the Material Output. The inputs of that group node are the stylized eye settings key set: the
eye presets in ui/presets/eyesettings read and write them as the group node's socket default
values (data/settings/eye_settings.stylized.json holds the shipped values).

Inside the group, a single Principled BSDF on one opaque mesh:

- Sclera: flat ScleraColor (0.92, 0.90, 0.88), darkened by ScleraEdgeDarkening toward the edge
  of the eyeball. No veins.
- Iris: a radial gradient from IrisInner (at the pupil) to IrisOuter, a dark limbal ring over
  the outer LimbalRingWidth (15%) of the iris radius, and a pupil of radius PupilSize (0.35) of
  the iris radius.
- Catchlight: a painted ellipse at the upper outer side of the iris, coloured CatchlightColor,
  also fed to the emission at CatchlightStrength (1.5), so it reads the same under any light.
- Shell: Roughness 0.05, Coat 0.5. No transmission, alpha stays 1.0 and is never linked.

The iris placement reads the eye UV layout the MakeHuman eye proxies share: one eye centred
at UV (0.295, 0.30), the other at (0.705, 0.70), eyeball radius 0.285 in UV units (the same
constants as the old procedural eyes). +V points up on both eyes, but the direction of +U
differs between the high-poly and low-poly eyes, so the outer side for the catchlight comes
from the sign of (object-space X of the point) * (object-space X of the UV tangent).

The high-poly eye also has, per eye, a closed outer shell (its cornea) that encloses the
eyeball, so it is all the camera sees. Its UVs are a small disc of its own, centred at
(0.9353, 0.0668), radius about 0.056, shared by both eyes and turned 45 degrees: UV (1, 1)
points up and UV (1, -1) points outward on both. A point on that disc is projected on those two axes
and scaled up to eyeball UV units, with SHELL_UV_RADIUS chosen so that, seen from the front,
the iris edge sits where it does on the high-poly eyeball inside the shell (0.38 of the eye's
radius at the default IrisSize), and its outer side is +X. The shell is painted opaque like the eyeball.
"""

import bpy

from .abstractmaterialwrapper import AbstractMaterialWrapper
from ..composites.abstractgroupwrapper import AbstractGroupWrapper

from .....services import LogService
_LOG = LogService.get_logger("material.stylizedeyes")

# Group input key that marks a material as stylized eyes. The eye presets, HumanService and
# MaterialService.identify_material check for it. The procedural eyes are marked by
# PROCEDURAL_EYES_MARKER_KEY instead; the two key sets do not overlap.
STYLIZED_EYES_MARKER_KEY = "IrisInner"
PROCEDURAL_EYES_MARKER_KEY = "IrisMinorColor"

EYE_CENTER_1 = [0.295, 0.30, 0.0]
EYE_CENTER_2 = [0.705, 0.70, 0.0]
EYEBALL_UV_RADIUS = 0.285

# Outer shell of the high-poly eye: UV disc centre, the UV distance under which a point is on
# it (no eyeball UV comes this close), and the shell UV distance that maps to
# EYEBALL_UV_RADIUS on the eyeball
SHELL_UV_CENTER = [0.9353, 0.0668, 0.0]
SHELL_UV_EXTENT = 0.07
SHELL_UV_RADIUS = 0.053
# Shell UV axes, outward (1, -1) and up (1, 1), normalised and scaled to eyeball UV units
_SHELL_AXIS = EYEBALL_UV_RADIUS / SHELL_UV_RADIUS / 2.0 ** 0.5

# Catchlight centre in iris-local units (iris radius = 1): outward and up, close enough to
# the pupil that the ellipse overlaps its edge (white on black reads at any size) and low
# enough that the upper lid of a neutral face does not cover it
CATCHLIGHT_OFFSET_OUT = 0.35
CATCHLIGHT_OFFSET_UP = 0.3
# Height of the catchlight ellipse relative to its width
CATCHLIGHT_ASPECT = 0.7

# Sclera darkening runs from this fraction of the eyeball radius to the edge
SCLERA_EDGE_START = 0.6

# Smoothstep band, in iris-local units, at the pupil and the iris border
EDGE_SOFTNESS = 0.03

DEFAULT_SETTINGS = {
    "ScleraColor": [0.92, 0.90, 0.88, 1.0],
    "ScleraEdgeDarkening": 0.25,
    "IrisInner": [0.30, 0.55, 0.80, 1.0],
    "IrisOuter": [0.08, 0.20, 0.45, 1.0],
    "IrisSize": 0.39,
    "LimbalRingColor": [0.02, 0.025, 0.04, 1.0],
    "LimbalRingWidth": 0.15,
    "PupilColor": [0.0, 0.0, 0.0, 1.0],
    "PupilSize": 0.35,
    "CatchlightColor": [1.0, 1.0, 1.0, 1.0],
    "CatchlightStrength": 1.5,
    "CatchlightSize": 0.28,
    "Roughness": 0.05,
    "Coat": 0.5
    }


def _socket_def(name, value, index):
    socket_class = "NodeSocketColor" if isinstance(value, list) else "NodeSocketFloat"
    return {"class": socket_class, "default_value": value, "identifier": "Socket_" + str(index), "name": name}


_ORIGINAL_NODE_DEF = {
    "attributes": {
        "location": {"class": "Vector", "name": "location", "value": [0.0, 0.0]},
        "width": {"class": "float", "name": "width", "value": 240.0}
        },
    "class": "MpfbStylizedEyes",
    "inputs": {name: _socket_def(name, value, index) for index, (name, value) in enumerate(DEFAULT_SETTINGS.items())},
    "outputs": {"BSDF": {"class": "NodeSocketShader", "default_value": None, "identifier": "BSDF", "name": "BSDF"}}
    }

# (class, name, attribute values, input socket values) of every node inside the group
_GROUP_NODES = [
    # Where on the eye: offset from the nearer eye centre, in iris-local units
    ("ShaderNodeTexCoord", "Texture Coordinate", {"location": [-1800.0, 200.0]}, {}),
    ("ShaderNodeCombineXYZ", "Center 1", {"location": [-1800.0, -100.0]}, {"X": EYE_CENTER_1[0], "Y": EYE_CENTER_1[1], "Z": 0.0}),
    ("ShaderNodeCombineXYZ", "Center 2", {"location": [-1800.0, -280.0]}, {"X": EYE_CENTER_2[0], "Y": EYE_CENTER_2[1], "Z": 0.0}),
    ("ShaderNodeVectorMath", "Distance 1", {"location": [-1600.0, 0.0], "operation": "DISTANCE"}, {}),
    ("ShaderNodeVectorMath", "Distance 2", {"location": [-1600.0, -180.0], "operation": "DISTANCE"}, {}),
    ("ShaderNodeMath", "Nearer is 2", {"location": [-1400.0, -60.0], "operation": "GREATER_THAN"}, {}),
    ("ShaderNodeMix", "Nearest center", {"location": [-1400.0, -240.0], "data_type": "VECTOR", "clamp_factor": True}, {}),
    ("ShaderNodeVectorMath", "Eyeball offset", {"location": [-1200.0, 0.0], "operation": "SUBTRACT"}, {}),
    ("ShaderNodeVectorMath", "Shell offset", {"location": [-1600.0, 400.0], "operation": "SUBTRACT"}, {"Vector_001": SHELL_UV_CENTER}),
    ("ShaderNodeVectorMath", "Shell distance", {"location": [-1400.0, 500.0], "operation": "LENGTH"}, {}),
    ("ShaderNodeMath", "On shell", {"location": [-1200.0, 500.0], "operation": "LESS_THAN"}, {"Value_001": SHELL_UV_EXTENT}),
    ("ShaderNodeVectorMath", "Shell out", {"location": [-1400.0, 350.0], "operation": "DOT_PRODUCT"}, {"Vector_001": [_SHELL_AXIS, -_SHELL_AXIS, 0.0]}),
    ("ShaderNodeVectorMath", "Shell up", {"location": [-1400.0, 200.0], "operation": "DOT_PRODUCT"}, {"Vector_001": [_SHELL_AXIS, _SHELL_AXIS, 0.0]}),
    ("ShaderNodeCombineXYZ", "Shell scaled", {"location": [-1200.0, 300.0]}, {"Z": 0.0}),
    ("ShaderNodeMix", "Offset", {"location": [-1000.0, 200.0], "data_type": "VECTOR", "clamp_factor": True}, {}),
    ("ShaderNodeMath", "Iris radius", {"location": [-1200.0, -200.0], "operation": "MULTIPLY"}, {"Value_001": EYEBALL_UV_RADIUS}),
    ("ShaderNodeMath", "Iris inverse", {"location": [-1000.0, -200.0], "operation": "DIVIDE"}, {"Value": 1.0}),
    ("ShaderNodeVectorMath", "Iris local", {"location": [-800.0, 0.0], "operation": "SCALE"}, {}),
    ("ShaderNodeVectorMath", "Iris r", {"location": [-600.0, 0.0], "operation": "LENGTH"}, {}),
    ("ShaderNodeMath", "Eye r", {"location": [-600.0, -200.0], "operation": "MULTIPLY"}, {}),

    # Iris gradient, limbal ring, pupil
    ("ShaderNodeMath", "Limbal start", {"location": [-400.0, 600.0], "operation": "SUBTRACT"}, {"Value": 1.0}),
    ("ShaderNodeMapRange", "Iris gradient pos", {"location": [-200.0, 800.0], "clamp": True}, {}),
    ("ShaderNodeMix", "Iris gradient", {"location": [0.0, 800.0], "data_type": "RGBA", "clamp_factor": True}, {}),
    ("ShaderNodeMath", "Limbal soft end", {"location": [-200.0, 550.0], "operation": "MULTIPLY_ADD"}, {"Value_001": 0.5}),
    ("ShaderNodeMapRange", "Limbal mask", {"location": [0.0, 550.0], "interpolation_type": "SMOOTHSTEP", "clamp": True}, {}),
    ("ShaderNodeMix", "With limbal ring", {"location": [200.0, 700.0], "data_type": "RGBA", "clamp_factor": True}, {}),
    ("ShaderNodeMath", "Pupil edge", {"location": [0.0, 350.0], "operation": "ADD"}, {"Value_001": EDGE_SOFTNESS}),
    ("ShaderNodeMapRange", "Pupil mask", {"location": [200.0, 400.0], "interpolation_type": "SMOOTHSTEP", "clamp": True}, {}),
    ("ShaderNodeMix", "Iris and pupil", {"location": [400.0, 600.0], "data_type": "RGBA", "clamp_factor": True}, {}),

    # Sclera with a soft darker edge, and the iris border
    ("ShaderNodeMapRange", "Sclera edge", {"location": [0.0, 150.0], "interpolation_type": "SMOOTHSTEP", "clamp": True}, {"From Min": SCLERA_EDGE_START, "From Max": 1.0}),
    ("ShaderNodeMath", "Sclera darkening", {"location": [200.0, 150.0], "operation": "MULTIPLY"}, {}),
    ("ShaderNodeMix", "Sclera", {"location": [400.0, 250.0], "data_type": "RGBA", "clamp_factor": True}, {"B_Color": [0.0, 0.0, 0.0, 1.0]}),
    ("ShaderNodeMapRange", "Iris mask", {"location": [400.0, 0.0], "interpolation_type": "SMOOTHSTEP", "clamp": True}, {"From Min": 1.0, "From Max": 1.0 + EDGE_SOFTNESS}),
    ("ShaderNodeMix", "Eye color", {"location": [600.0, 400.0], "data_type": "RGBA", "clamp_factor": True}, {}),

    # Catchlight: which way is out, then an ellipse in iris-local units
    ("ShaderNodeTangent", "UV tangent", {"location": [-1200.0, -600.0], "direction_type": "UV_MAP"}, {}),
    ("ShaderNodeVectorTransform", "Tangent to object", {"location": [-1000.0, -600.0], "vector_type": "VECTOR", "convert_from": "WORLD", "convert_to": "OBJECT"}, {}),
    ("ShaderNodeSeparateXYZ", "Tangent XYZ", {"location": [-800.0, -600.0]}, {}),
    ("ShaderNodeSeparateXYZ", "Position XYZ", {"location": [-800.0, -800.0]}, {}),
    ("ShaderNodeMath", "Outward", {"location": [-600.0, -650.0], "operation": "MULTIPLY"}, {}),
    ("ShaderNodeMath", "Outward sign", {"location": [-400.0, -650.0], "operation": "SIGN"}, {}),
    ("ShaderNodeMix", "Outward side", {"location": [-300.0, -800.0], "data_type": "FLOAT", "clamp_factor": True}, {"B_Float": 1.0}),
    ("ShaderNodeMath", "Catchlight X", {"location": [-200.0, -650.0], "operation": "MULTIPLY"}, {"Value_001": CATCHLIGHT_OFFSET_OUT}),
    ("ShaderNodeCombineXYZ", "Catchlight center", {"location": [0.0, -650.0]}, {"Y": CATCHLIGHT_OFFSET_UP, "Z": 0.0}),
    ("ShaderNodeVectorMath", "Catchlight offset", {"location": [200.0, -500.0], "operation": "SUBTRACT"}, {}),
    ("ShaderNodeMath", "Catchlight height", {"location": [0.0, -850.0], "operation": "MULTIPLY"}, {"Value_001": CATCHLIGHT_ASPECT}),
    ("ShaderNodeCombineXYZ", "Catchlight radii", {"location": [200.0, -800.0]}, {"Z": 1.0}),
    ("ShaderNodeVectorMath", "Catchlight scaled", {"location": [400.0, -600.0], "operation": "DIVIDE"}, {}),
    ("ShaderNodeVectorMath", "Catchlight distance", {"location": [600.0, -600.0], "operation": "LENGTH"}, {}),
    ("ShaderNodeMapRange", "Catchlight mask", {"location": [800.0, -600.0], "interpolation_type": "SMOOTHSTEP", "clamp": True}, {"From Min": 0.8, "From Max": 1.0, "To Min": 1.0, "To Max": 0.0}),
    ("ShaderNodeMix", "Base color", {"location": [1000.0, 300.0], "data_type": "RGBA", "clamp_factor": True}, {}),
    ("ShaderNodeMath", "Catchlight emission", {"location": [1000.0, -400.0], "operation": "MULTIPLY"}, {}),

    ("ShaderNodeBsdfPrincipled", "Principled BSDF", {"location": [1300.0, 200.0]}, {"Alpha": 1.0, "Transmission Weight": 0.0}),
    ]

_GROUP_LINKS = [
    ("Texture Coordinate", "UV", "Distance 1", "Vector"),
    ("Center 1", "Vector", "Distance 1", "Vector_001"),
    ("Texture Coordinate", "UV", "Distance 2", "Vector"),
    ("Center 2", "Vector", "Distance 2", "Vector_001"),
    ("Distance 1", "Value", "Nearer is 2", "Value"),
    ("Distance 2", "Value", "Nearer is 2", "Value_001"),
    ("Nearer is 2", "Value", "Nearest center", "Factor_Float"),
    ("Center 1", "Vector", "Nearest center", "A_Vector"),
    ("Center 2", "Vector", "Nearest center", "B_Vector"),
    ("Texture Coordinate", "UV", "Eyeball offset", "Vector"),
    ("Nearest center", "Result_Vector", "Eyeball offset", "Vector_001"),
    ("Texture Coordinate", "UV", "Shell offset", "Vector"),
    ("Shell offset", "Vector", "Shell distance", "Vector"),
    ("Shell distance", "Value", "On shell", "Value"),
    ("Shell offset", "Vector", "Shell out", "Vector"),
    ("Shell offset", "Vector", "Shell up", "Vector"),
    ("Shell out", "Value", "Shell scaled", "X"),
    ("Shell up", "Value", "Shell scaled", "Y"),
    ("On shell", "Value", "Offset", "Factor_Float"),
    ("Eyeball offset", "Vector", "Offset", "A_Vector"),
    ("Shell scaled", "Vector", "Offset", "B_Vector"),
    ("Group Input", "IrisSize", "Iris radius", "Value"),
    ("Iris radius", "Value", "Iris inverse", "Value_001"),
    ("Offset", "Result_Vector", "Iris local", "Vector"),
    ("Iris inverse", "Value", "Iris local", "Scale"),
    ("Iris local", "Vector", "Iris r", "Vector"),
    ("Iris r", "Value", "Eye r", "Value"),
    ("Group Input", "IrisSize", "Eye r", "Value_001"),

    ("Group Input", "LimbalRingWidth", "Limbal start", "Value_001"),
    ("Iris r", "Value", "Iris gradient pos", "Value"),
    ("Group Input", "PupilSize", "Iris gradient pos", "From Min"),
    ("Limbal start", "Value", "Iris gradient pos", "From Max"),
    ("Iris gradient pos", "Result", "Iris gradient", "Factor_Float"),
    ("Group Input", "IrisInner", "Iris gradient", "A_Color"),
    ("Group Input", "IrisOuter", "Iris gradient", "B_Color"),
    ("Group Input", "LimbalRingWidth", "Limbal soft end", "Value"),
    ("Limbal start", "Value", "Limbal soft end", "Value_002"),
    ("Iris r", "Value", "Limbal mask", "Value"),
    ("Limbal start", "Value", "Limbal mask", "From Min"),
    ("Limbal soft end", "Value", "Limbal mask", "From Max"),
    ("Limbal mask", "Result", "With limbal ring", "Factor_Float"),
    ("Iris gradient", "Result_Color", "With limbal ring", "A_Color"),
    ("Group Input", "LimbalRingColor", "With limbal ring", "B_Color"),
    ("Group Input", "PupilSize", "Pupil edge", "Value"),
    ("Iris r", "Value", "Pupil mask", "Value"),
    ("Group Input", "PupilSize", "Pupil mask", "From Min"),
    ("Pupil edge", "Value", "Pupil mask", "From Max"),
    ("Pupil mask", "Result", "Iris and pupil", "Factor_Float"),
    ("Group Input", "PupilColor", "Iris and pupil", "A_Color"),
    ("With limbal ring", "Result_Color", "Iris and pupil", "B_Color"),

    ("Eye r", "Value", "Sclera edge", "Value"),
    ("Sclera edge", "Result", "Sclera darkening", "Value"),
    ("Group Input", "ScleraEdgeDarkening", "Sclera darkening", "Value_001"),
    ("Sclera darkening", "Value", "Sclera", "Factor_Float"),
    ("Group Input", "ScleraColor", "Sclera", "A_Color"),
    ("Iris r", "Value", "Iris mask", "Value"),
    ("Iris mask", "Result", "Eye color", "Factor_Float"),
    ("Iris and pupil", "Result_Color", "Eye color", "A_Color"),
    ("Sclera", "Result_Color", "Eye color", "B_Color"),

    ("UV tangent", "Tangent", "Tangent to object", "Vector"),
    ("Tangent to object", "Vector", "Tangent XYZ", "Vector"),
    ("Texture Coordinate", "Object", "Position XYZ", "Vector"),
    ("Tangent XYZ", "X", "Outward", "Value"),
    ("Position XYZ", "X", "Outward", "Value_001"),
    ("Outward", "Value", "Outward sign", "Value"),
    ("On shell", "Value", "Outward side", "Factor_Float"),
    ("Outward sign", "Value", "Outward side", "A_Float"),
    ("Outward side", "Result_Float", "Catchlight X", "Value"),
    ("Catchlight X", "Value", "Catchlight center", "X"),
    ("Iris local", "Vector", "Catchlight offset", "Vector"),
    ("Catchlight center", "Vector", "Catchlight offset", "Vector_001"),
    ("Group Input", "CatchlightSize", "Catchlight height", "Value"),
    ("Group Input", "CatchlightSize", "Catchlight radii", "X"),
    ("Catchlight height", "Value", "Catchlight radii", "Y"),
    ("Catchlight offset", "Vector", "Catchlight scaled", "Vector"),
    ("Catchlight radii", "Vector", "Catchlight scaled", "Vector_001"),
    ("Catchlight scaled", "Vector", "Catchlight distance", "Vector"),
    ("Catchlight distance", "Value", "Catchlight mask", "Value"),
    ("Catchlight mask", "Result", "Base color", "Factor_Float"),
    ("Eye color", "Result_Color", "Base color", "A_Color"),
    ("Group Input", "CatchlightColor", "Base color", "B_Color"),
    ("Catchlight mask", "Result", "Catchlight emission", "Value"),
    ("Group Input", "CatchlightStrength", "Catchlight emission", "Value_001"),

    ("Base color", "Result_Color", "Principled BSDF", "Base Color"),
    ("Group Input", "Roughness", "Principled BSDF", "Roughness"),
    ("Group Input", "Coat", "Principled BSDF", "Coat Weight"),
    ("Group Input", "CatchlightColor", "Principled BSDF", "Emission Color"),
    ("Catchlight emission", "Value", "Principled BSDF", "Emission Strength"),
    ("Principled BSDF", "BSDF", "Group Output", "BSDF"),
    ]


def _tree_def(node_names, links):
    return {
        "links": [{"from_node": link[0], "from_socket": link[1], "to_node": link[2], "to_socket": link[3]} for link in links],
        "nodes": [{"name": name} for name in node_names]
        }


_GROUP_TREE_DEF = _tree_def([node_def[1] for node_def in _GROUP_NODES] + ["Group Input", "Group Output"], _GROUP_LINKS)

_ORIGINAL_TREE_DEF = _tree_def(["StylizedEyes", "Material Output"], [("StylizedEyes", "BSDF", "Material Output", "Surface")])


class _NodeWrapperMpfbStylizedEyes(AbstractGroupWrapper):
    """The MpfbStylizedEyes node group, whose inputs are the eye settings key set."""

    def __init__(self):
        AbstractGroupWrapper.__init__(self, _ORIGINAL_NODE_DEF, _GROUP_TREE_DEF)

    def setup_group_nodes(self, node_tree, nodes, mhmat=None):
        _LOG.enter()

        nodes["Group Input"].location = [-2100.0, 0.0]
        nodes["Group Output"].location = [1600.0, 200.0]

        for node_class, name, attribute_values, input_socket_values in _GROUP_NODES:
            nodes[name] = AbstractGroupWrapper.node(node_class, node_tree, name, label=name, attribute_values=attribute_values, input_socket_values=input_socket_values or None)

        for from_node, from_socket, to_node, to_socket in _GROUP_LINKS:
            AbstractGroupWrapper.create_link(node_tree, nodes[from_node], from_socket, nodes[to_node], to_socket)


NodeWrapperMpfbStylizedEyes = _NodeWrapperMpfbStylizedEyes()


class _NodeWrapperStylizedEyes(AbstractMaterialWrapper):

    def __init__(self):
        AbstractMaterialWrapper.__init__(self, "StylizedEyes", _ORIGINAL_TREE_DEF)

    def setup_group_nodes(self, node_tree, nodes, mhmat=None):
        _LOG.enter()
        if mhmat:
            # The eye .mhmat files describe a textured iris; the stylized eyes are painted from
            # the settings key set instead, so nothing is read from them.
            _LOG.debug("Not reading the mhmat for stylized eyes", mhmat)

        nodes["Material Output"].location = [400.0, 300.0]
        nodes["StylizedEyes"] = NodeWrapperMpfbStylizedEyes.create_instance(node_tree, name="StylizedEyes", label="Stylized eyes", attribute_values={"location": [0.0, 300.0], "width": 240.0})
        AbstractMaterialWrapper.create_link(node_tree, nodes["StylizedEyes"], "BSDF", nodes["Material Output"], "Surface")


NodeWrapperStylizedEyes = _NodeWrapperStylizedEyes()
