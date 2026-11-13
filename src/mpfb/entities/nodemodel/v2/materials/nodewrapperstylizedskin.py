"""Stylized skin material, STYLIZED (STYLIZED_SPEC.md section 5.1).

One Principled BSDF with a painted, low-frequency albedo, so it renders in Cycles and EEVEE and
exports with no custom shader nodes. The material is one group node, "StylizedSkin" (node group
MpfbStylizedSkin), wired to the Material Output, with four image nodes beside it that feed the
group's map inputs:

- SkinTone: the base colour, sRGB (0.80, 0.60, 0.48). data/settings/skin_tones.json holds 12
  swatches for the UI.
- BloodMap: a painted grayscale mask of the warm areas. BloodTint (0.85, 0.35, 0.30) is mixed into
  SkinTone through it at BloodStrength 0.10. This replaces SSS for the warm look.
- CavityMap: baked AO. It is multiplied into the albedo at CavityStrength 0.15, and the cavity
  colour is BloodTint rather than black, so cavities read warm, not grey.
- Gradient: a vertical darkening of GradientStrength (4%) from the top of the head to the feet,
  read from the object's Generated coordinate Z (0 at the soles, 1 at the top of the head), so it
  follows the body whatever its height or scale.
- Roughness: the painted RoughnessMask maps 0..1 to RoughnessMin..RoughnessMax (0.4-0.6). The mask
  values are 0.75 for the body (0.55), 0.5 for the face (0.50) and 0.0 for the lips (0.40).
- Specular IOR Level 0.35, Subsurface Weight 0.05 with radius (1.0, 0.35, 0.2) x SubsurfaceScale.
  SubsurfaceScale is 0.5 cm in scene units; HumanService sets it from the human's scale factor.
- Normal: none. No normal map, no micro-normal, no pore noise (spec R1).
- Makeup: an optional sRGB decal mixed over the albedo by its alpha.

The textures come from data/textures/sty_*.png, 1024² and laid out in HM08's UVs. tools/hm08/make_sty_maps.py
makes the BloodMap, CavityMap and roughness mask from the HM08 base mesh with stylized-default at 1.0;
sty_makeup_none.png is an empty (transparent) decal. HM08's mpfb_* region textures are not read.
"""

import json, os

import bpy

from .abstractmaterialwrapper import AbstractMaterialWrapper
from ..composites.abstractgroupwrapper import AbstractGroupWrapper

from .....services import LogService
from .....services import LocationService
from .....services import NodeService
_LOG = LogService.get_logger("material.stylizedskin")

# Group input key that marks a material as stylized skin. MaterialService.identify_material and
# HumanService check for it.
STYLIZED_SKIN_MARKER_KEY = "BloodTint"

# Spec colours are sRGB; Blender colour sockets hold scene linear values.
SKIN_TONE_SRGB = [0.80, 0.60, 0.48]
BLOOD_TINT_SRGB = [0.85, 0.35, 0.30]

# 0.5 cm in metres: the subsurface radius scale for a human at scale factor 0.1 (one unit = 1 m)
SUBSURFACE_SCALE_METERS = 0.005

# The textures, by image node name: (file name in data/textures, colour space, group input fed by
# the Color output, group input fed by the Alpha output)
TEXTURES = {
    "BloodMap texture": ("sty_bloodmap.png", "Non-Color", "BloodMap", None),
    "CavityMap texture": ("sty_cavity.png", "Non-Color", "CavityMap", None),
    "Roughness mask texture": ("sty_roughness.png", "Non-Color", "RoughnessMask", None),
    "Makeup texture": ("sty_makeup_none.png", "sRGB", "Makeup", "MakeupAlpha"),
    }


def srgb_to_linear(rgb):
    """Convert sRGB components (0..1) to scene linear, as Blender's colour sockets store them."""
    return [c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in rgb]


def _linear_rgba(srgb):
    return srgb_to_linear(srgb) + [1.0]


def skin_tone_swatches():
    """The skin tone swatches of data/settings/skin_tones.json, as a list of (name, linear RGBA)."""
    file_name = os.path.join(LocationService.get_mpfb_data("settings"), "skin_tones.json")
    with open(file_name, "r", encoding="utf-8") as json_file:
        data = json.load(json_file)
    if data["color_space"] != "sRGB":
        raise ValueError("skin_tones.json must list sRGB colours, not " + str(data["color_space"]))
    return [(swatch["name"], _linear_rgba(swatch["color"])) for swatch in data["swatches"]]


DEFAULT_SETTINGS = {
    "SkinTone": _linear_rgba(SKIN_TONE_SRGB),
    "BloodMap": 0.0,
    "BloodTint": _linear_rgba(BLOOD_TINT_SRGB),
    "BloodStrength": 0.10,
    "CavityMap": 1.0,
    "CavityStrength": 0.15,
    "GradientStrength": 0.04,
    "RoughnessMask": 0.75,
    "RoughnessMin": 0.4,
    "RoughnessMax": 0.6,
    "SpecularIORLevel": 0.35,
    "SubsurfaceWeight": 0.05,
    "SubsurfaceRadius": [1.0, 0.35, 0.2],
    "SubsurfaceScale": SUBSURFACE_SCALE_METERS,
    "Makeup": [0.0, 0.0, 0.0, 1.0],
    "MakeupAlpha": 0.0
    }


def _socket_def(name, value, index):
    socket_class = "NodeSocketFloat"
    if isinstance(value, list):
        socket_class = "NodeSocketColor" if len(value) == 4 else "NodeSocketVector"
    return {"class": socket_class, "default_value": value, "identifier": "Socket_" + str(index), "name": name}


_ORIGINAL_NODE_DEF = {
    "attributes": {
        "location": {"class": "Vector", "name": "location", "value": [0.0, 0.0]},
        "width": {"class": "float", "name": "width", "value": 240.0}
        },
    "class": "MpfbStylizedSkin",
    "inputs": {name: _socket_def(name, value, index) for index, (name, value) in enumerate(DEFAULT_SETTINGS.items())},
    "outputs": {"BSDF": {"class": "NodeSocketShader", "default_value": None, "identifier": "BSDF", "name": "BSDF"}}
    }

_WHITE = [1.0, 1.0, 1.0, 1.0]
_BLACK = [0.0, 0.0, 0.0, 1.0]

# (class, name, attribute values, input socket values) of every node inside the group
_GROUP_NODES = [
    # Blood: SkinTone toward BloodTint where the BloodMap is painted
    ("ShaderNodeMath", "Blood amount", {"location": [-600.0, 500.0], "operation": "MULTIPLY", "use_clamp": True}, {}),
    ("ShaderNodeMix", "Blood", {"location": [-400.0, 500.0], "data_type": "RGBA", "clamp_factor": True}, {}),

    # Cavity: BloodTint in the cavities, white in the open, multiplied in at CavityStrength
    ("ShaderNodeMix", "Cavity tint", {"location": [-400.0, 250.0], "data_type": "RGBA", "clamp_factor": True}, {"B_Color": _WHITE}),
    ("ShaderNodeMix", "Cavity", {"location": [-200.0, 400.0], "data_type": "RGBA", "blend_type": "MULTIPLY", "clamp_factor": True}, {}),

    # Gradient: darken by GradientStrength * (1 - Z), Z running 0 at the feet to 1 at the head
    ("ShaderNodeTexCoord", "Texture Coordinate", {"location": [-800.0, 0.0]}, {}),
    ("ShaderNodeSeparateXYZ", "Generated XYZ", {"location": [-600.0, 0.0]}, {}),
    ("ShaderNodeMath", "Below head", {"location": [-400.0, 0.0], "operation": "SUBTRACT", "use_clamp": True}, {"Value": 1.0}),
    ("ShaderNodeMath", "Gradient amount", {"location": [-200.0, 0.0], "operation": "MULTIPLY", "use_clamp": True}, {}),
    ("ShaderNodeMix", "Gradient", {"location": [0.0, 350.0], "data_type": "RGBA", "blend_type": "MULTIPLY", "clamp_factor": True}, {"B_Color": _BLACK}),

    # Makeup decal over the albedo, by its alpha
    ("ShaderNodeMix", "Makeup", {"location": [200.0, 350.0], "data_type": "RGBA", "clamp_factor": True}, {}),

    ("ShaderNodeMapRange", "Roughness", {"location": [200.0, 0.0], "clamp": True}, {}),

    ("ShaderNodeBsdfPrincipled", "Principled BSDF", {"location": [500.0, 200.0], "subsurface_method": "RANDOM_WALK"}, {"Alpha": 1.0}),
    ]

_GROUP_LINKS = [
    ("Group Input", "BloodMap", "Blood amount", "Value"),
    ("Group Input", "BloodStrength", "Blood amount", "Value_001"),
    ("Blood amount", "Value", "Blood", "Factor_Float"),
    ("Group Input", "SkinTone", "Blood", "A_Color"),
    ("Group Input", "BloodTint", "Blood", "B_Color"),

    ("Group Input", "CavityMap", "Cavity tint", "Factor_Float"),
    ("Group Input", "BloodTint", "Cavity tint", "A_Color"),
    ("Group Input", "CavityStrength", "Cavity", "Factor_Float"),
    ("Blood", "Result_Color", "Cavity", "A_Color"),
    ("Cavity tint", "Result_Color", "Cavity", "B_Color"),

    ("Texture Coordinate", "Generated", "Generated XYZ", "Vector"),
    ("Generated XYZ", "Z", "Below head", "Value_001"),
    ("Below head", "Value", "Gradient amount", "Value"),
    ("Group Input", "GradientStrength", "Gradient amount", "Value_001"),
    ("Gradient amount", "Value", "Gradient", "Factor_Float"),
    ("Cavity", "Result_Color", "Gradient", "A_Color"),

    ("Gradient", "Result_Color", "Makeup", "A_Color"),
    ("Group Input", "Makeup", "Makeup", "B_Color"),
    ("Group Input", "MakeupAlpha", "Makeup", "Factor_Float"),

    ("Group Input", "RoughnessMask", "Roughness", "Value"),
    ("Group Input", "RoughnessMin", "Roughness", "To Min"),
    ("Group Input", "RoughnessMax", "Roughness", "To Max"),

    ("Makeup", "Result_Color", "Principled BSDF", "Base Color"),
    ("Roughness", "Result", "Principled BSDF", "Roughness"),
    ("Group Input", "SpecularIORLevel", "Principled BSDF", "Specular IOR Level"),
    ("Group Input", "SubsurfaceWeight", "Principled BSDF", "Subsurface Weight"),
    ("Group Input", "SubsurfaceRadius", "Principled BSDF", "Subsurface Radius"),
    ("Group Input", "SubsurfaceScale", "Principled BSDF", "Subsurface Scale"),
    ("Principled BSDF", "BSDF", "Group Output", "BSDF"),
    ]


def _tree_def(node_names, links):
    return {
        "links": [{"from_node": link[0], "from_socket": link[1], "to_node": link[2], "to_socket": link[3]} for link in links],
        "nodes": [{"name": name} for name in node_names]
        }


_GROUP_TREE_DEF = _tree_def([node_def[1] for node_def in _GROUP_NODES] + ["Group Input", "Group Output"], _GROUP_LINKS)


def _material_links():
    links = [("StylizedSkin", "BSDF", "Material Output", "Surface")]
    for node_name, (_file, _colorspace, color_input, alpha_input) in TEXTURES.items():
        links.append((node_name, "Color", "StylizedSkin", color_input))
        if alpha_input:
            links.append((node_name, "Alpha", "StylizedSkin", alpha_input))
    return links


_MATERIAL_LINKS = _material_links()

_ORIGINAL_TREE_DEF = _tree_def(["StylizedSkin", "Material Output"] + list(TEXTURES.keys()), _MATERIAL_LINKS)


class _NodeWrapperMpfbStylizedSkin(AbstractGroupWrapper):
    """The MpfbStylizedSkin node group, whose inputs are the skin settings."""

    def __init__(self):
        AbstractGroupWrapper.__init__(self, _ORIGINAL_NODE_DEF, _GROUP_TREE_DEF)

    def setup_group_nodes(self, node_tree, nodes, mhmat=None):
        _LOG.enter()

        nodes["Group Input"].location = [-1100.0, 0.0]
        nodes["Group Output"].location = [800.0, 200.0]

        for node_class, name, attribute_values, input_socket_values in _GROUP_NODES:
            nodes[name] = AbstractGroupWrapper.node(node_class, node_tree, name, label=name, attribute_values=attribute_values, input_socket_values=input_socket_values or None)

        for from_node, from_socket, to_node, to_socket in _GROUP_LINKS:
            AbstractGroupWrapper.create_link(node_tree, nodes[from_node], from_socket, nodes[to_node], to_socket)


NodeWrapperMpfbStylizedSkin = _NodeWrapperMpfbStylizedSkin()


class _NodeWrapperStylizedSkin(AbstractMaterialWrapper):

    def __init__(self):
        AbstractMaterialWrapper.__init__(self, "StylizedSkin", _ORIGINAL_TREE_DEF)

    def setup_group_nodes(self, node_tree, nodes, mhmat=None):
        _LOG.enter()
        if mhmat:
            # The skin .mhmat files describe photo textures; the stylized skin is painted from the
            # group inputs and the sty_* maps instead, so nothing is read from them.
            _LOG.debug("Not reading the mhmat for stylized skin", mhmat)

        nodes["Material Output"].location = [400.0, 300.0]
        nodes["StylizedSkin"] = NodeWrapperMpfbStylizedSkin.create_instance(node_tree, name="StylizedSkin", label="Stylized skin", attribute_values={"location": [0.0, 300.0], "width": 240.0})

        textures_dir = LocationService.get_mpfb_data("textures")
        y_position = 500.0
        for node_name, (file_name, colorspace, _color_input, _alpha_input) in TEXTURES.items():
            nodes[node_name] = AbstractMaterialWrapper.node("ShaderNodeTexImage", node_tree, node_name, label=node_name, attribute_values={"location": [-400.0, y_position]})
            NodeService.set_image_in_image_node(nodes[node_name], os.path.join(textures_dir, file_name), colorspace=colorspace)
            if nodes[node_name].image is None:
                raise IOError("Stylized skin texture is missing: " + file_name)
            y_position -= 280.0

        for from_node, from_socket, to_node, to_socket in _MATERIAL_LINKS:
            AbstractMaterialWrapper.create_link(node_tree, nodes[from_node], from_socket, nodes[to_node], to_socket)


NodeWrapperStylizedSkin = _NodeWrapperStylizedSkin()
