# ------------------------------------------------------------------------------
# MPFB2 Extension by Klecer
# Author:       Tomáš Klecer
# Date:         19.10.2026
# University:   Brno University of Technology
# Supervisor:   Ing. Tomáš Chlubna, Ph.D.
# Description:  builders for the geometry node groups behind each hair cards generation mode
#               and meshes build in python for cluster-based modes
# ------------------------------------------------------------------------------
"""One geometry-nodes builder per ``cards_mode`` value (except CLUSTER_BOX and CLUMP, which build a static mesh in python).

Mode and strand-selection method change the node graph itself, so they only apply on regenerate.
Every other parameter is a live modifier input socket.
"""

import math
from collections.abc import Iterator
from typing import Any, TYPE_CHECKING

import bpy
from contextlib import contextmanager
from mathutils import Vector

if TYPE_CHECKING:
    import numpy as np

# Shared with hairproperties
CLUSTER_RIBBON_PROFILE_STEPS = 5

CARDS_MODE_TILES = "TILES"

CARDS_MODE_RIBBON = "RIBBON"

CARDS_MODE_SHELL = "SHELL"

CARDS_MODE_CLUSTER_BOX = "CLUSTER_BOX"

CARDS_MODE_CLUSTER_RIBBON = "CLUSTER_RIBBON"

CARDS_MODE_CLUMP = "CLUMP"

CARDS_MODE_ITEMS = [
    (CARDS_MODE_TILES, "Random tiles", "A quad is instanced on resampled points along each kept strand"),
    (CARDS_MODE_RIBBON, "Ribbon", "Each kept strand becomes a single continuous, taperable ribbon mesh"),
    (CARDS_MODE_SHELL, "Shell (volume)", "A single closed shell wrapped around the whole hairstyle, good for LODs"),
    (CARDS_MODE_CLUSTER_BOX, "Cluster boxes", "One flat oriented card per bundle of nearby strands, computed in python (PCA)"),
    (CARDS_MODE_CLUSTER_RIBBON, "Cluster ribbons", "One curved ribbon per bundle of nearby strands, following the bundle's average curve"),
    (CARDS_MODE_CLUMP, "Clumps", "One closed tapered tube per bundle of nearby strands, merged until the style fits the triangle budget"),
    ]

# Where the hair gets baked to.
BAKE_TARGET_CARDS = "CARDS" # generated card object

BAKE_TARGET_BODY_DIRECT = "BODY_DIRECT" # body geometry - hair baked onto skin texture

BAKE_TARGET_BODY_SHELL = "BODY_SHELL" # copy of body geometry hovering above skin

BAKE_TARGET_CUSTOM = "CUSTOM" # users own mesh

BAKE_TARGET_ITEMS = [
    (BAKE_TARGET_CARDS, "Hair cards", "Project the hair onto generated cards (the modes below)"),
    (BAKE_TARGET_BODY_DIRECT, "Body texture",
     "Project the hair straight onto the body and blend the result over the skin material."),
    (BAKE_TARGET_BODY_SHELL, "Body shell",
     "Projects hair onto duplicate of body faces the hair asset grows from (faces will be howering just above the skin)"),
    (BAKE_TARGET_CUSTOM, "Custom mesh",
     "Projects the hair onto your own modelled mesh picked from the scene (mesh needs its own UV layout)."
     "Nothing about the mesh is changed except that it gains the baked material."),
    ]

# How the hair is lit while it is baked.
LIGHT_MODE_FIXED = "FIXED"

LIGHT_MODE_BBOX = "BBOX"

LIGHT_MODE_NO_SHADOW = "NO_SHADOW"

LIGHT_MODE_ACROSS_STRANDS = "ACROSS_STRANDS"

LIGHT_MODE_SCENE = "SCENE"

LIGHT_MODE_ITEMS = [
    (LIGHT_MODE_FIXED, "Two lights, fixed offset",
     "Two point lights at a fixed offset from the character's origin"),
    (LIGHT_MODE_BBOX, "Two lights, from hair bounding box",
     "Two point lights placed from the hair's own bounding box"),
    (LIGHT_MODE_NO_SHADOW, "Two lights, no shadows",
     "As above, but the lights dont cast shadows."),
    (LIGHT_MODE_ACROSS_STRANDS, "Two lights, across the strands",
     "Two shadowless lights placed perpendicular to the main hair growth direction, so the hair is lit from the side."),
    (LIGHT_MODE_SCENE, "Current scene lighting",
     "Use the lights and the world already in the scene, as they are. No bake lights are added"),
    ]

# Full strength in watts per mode so they can use same scale in UI
LIGHT_MODE_BASE_ENERGY = {
    LIGHT_MODE_FIXED: 1000.0,
    LIGHT_MODE_BBOX: 200.0,
    LIGHT_MODE_NO_SHADOW: 10.0,
    LIGHT_MODE_ACROSS_STRANDS: 10.0,
    LIGHT_MODE_SCENE: 0.0,     # No lights added, scenes own lights keep their own strength
    }

BODY_BAKE_TARGETS = (BAKE_TARGET_BODY_DIRECT, BAKE_TARGET_BODY_SHELL)

SELECTION_METHOD_RANDOM = "RANDOM"

SELECTION_METHOD_EVERY_NTH = "EVERY_NTH"

SELECTION_METHOD_POISSON = "POISSON_SCALP"

SELECTION_METHOD_ITEMS = [
    (SELECTION_METHOD_RANDOM, "Random", "Each strand has an independent chance of becoming a card"),
    (SELECTION_METHOD_EVERY_NTH, "Even spacing", "Every Nth strand is kept"),
    (SELECTION_METHOD_POISSON, "Scalp sample points", "Strands nearest to an evenly distributed set of points on the scalp are kept"),
    ]

STRAND_BASED_MODES = (CARDS_MODE_TILES, CARDS_MODE_RIBBON)

CLUSTER_MODES = (CARDS_MODE_CLUSTER_BOX, CARDS_MODE_CLUSTER_RIBBON, CARDS_MODE_CLUMP)

# Cluster modes which build a finished mesh in python, with no generator node group
PYTHON_MESH_MODES = (CARDS_MODE_CLUSTER_BOX, CARDS_MODE_CLUMP)

# Clump tubes: ring sides at the root and at the last ring, tip ring radius as a fraction of the root one,
# and the smallest root radius (a single-strand clump has no spread)
CLUMP_ROOT_SIDES = 6

CLUMP_TIP_SIDES = 3

_CLUMP_TIP_RADIUS = 0.25

_CLUMP_MIN_RADIUS = 0.002
# Flat half-axis of a clump's cross-section as a fraction of the wide one (0.5: the 2:1 tube)
CLUMP_FLATTEN = 0.5
# Groom-side clumping. Guides are the hair before its node modifiers (children, curl, frizz) are applied.
# Nearest guides each guide's flow is averaged with, points a guide is resampled to, the largest angle between two
# guides' lie directions that still counts as one flow (wider is a parting), and the break distance: a strand's
# interpolation weight from a guide fades out as that guide lies between these many guide spacings from its nearest guide
_GUIDE_NEIGHBOURS = 6
_GUIDE_SAMPLES = 16
_GUIDE_MAX_ANGLE = math.radians(60.0)
_GUIDE_BREAK_DISTANCE = (2.0, 4.0)
# Hair cap: cuts per body edge, how far past the outermost strand root it reaches (metres) and border smoothing steps
_CLUMP_CAP_CUTS = 2
_CLUMP_CAP_REACH = 0.008
_CLUMP_CAP_BORDER_SMOOTHING = 4
# Soft hairline: the cap's HAIRLINE_ATTRIBUTE runs from 1 on its border to 0 this far inside (metres); the stylized hair
# shader fades the cap out over it. Same name as in nodewrapperstylizedhair.py (entities do not import services)
HAIRLINE_ATTRIBUTE = "mpfb_hairline"
_CLUMP_HAIRLINE_WIDTH = 0.01
# Stray strands: root radius (metres), and how far the tip drifts off its strand, as a fraction of the strand length
_STRAY_RADIUS = 0.0007
_STRAY_DRIFT = 0.12

# The UV map that the tiles / ribbon / cluster modes lay out and which the bake packs into the atlas
CARDS_UV_MAP = "UVMap"

_CARD_U_ATTRIBUTE = "_card_u"

_CARD_V_ATTRIBUTE = "_card_v"

CLUSTER_WIDTH_ATTRIBUTE = "cluster_half_width"

# Roots * clusters up to which k-means is run several times and the best run is kept.
# Above it a single run is made for performance reasons.
_KMEANS_RESTART_BUDGET = 2_000_000

# Max strands averaged per cluster, bigger clusters are strided down. More members do not change the average visibly
_MAX_MEMBERS_PER_BUNDLE = 200

# Roots are sampled for speed, more more samples would not bring much change to final mesh
_MAX_ROOT_SAMPLES = 4000

# Keeps the shell on the body when the body moves
BODY_SHELL_FOLLOW_MODIFIER_NAME = "Follow body"

# Attribute the store_shell_edge_fade() writes. The baked shader than multiplies it into the alpha
SHELL_EDGE_FADE_ATTRIBUTE = "mpfb_shell_edge_fade"


class HairCardService():
    """Building the hair cards: geometry node groups for the generated modes, and meshes computed in python. All methods are static methods."""

    def __init__(self) -> None:
        raise RuntimeError("You should not instance HairCardService. Use its static methods instead.")

    @staticmethod
    def light_base_energy(mode: str) -> float:
        """Watts per light at strength 1.0 for the given mode."""
        return LIGHT_MODE_BASE_ENERGY.get(mode, 200.0)

    @staticmethod
    def _new_group(name: str) -> bpy.types.NodeTree:
        node_group = bpy.data.node_groups.new(name, 'GeometryNodeTree')
        interface = node_group.interface
        interface.new_socket('Geometry', in_out='INPUT', socket_type='NodeSocketGeometry')
        interface.new_socket('Geometry', in_out='OUTPUT', socket_type='NodeSocketGeometry')
        for node in list(node_group.nodes):
            node_group.nodes.remove(node)
        node_group.nodes.new('NodeGroupInput')
        node_group.nodes.new('NodeGroupOutput')
        return node_group

    @staticmethod
    def _add_input(node_group: bpy.types.NodeTree, socket_name: str, socket_type: str, default: Any = None, value_range: tuple[float, float] | None = None) -> Any:
        socket = node_group.interface.new_socket(socket_name, in_out='INPUT', socket_type=socket_type)
        if default is not None:
            socket.default_value = default
        if value_range is not None and hasattr(socket, "min_value"):
            socket.min_value = value_range[0]
            socket.max_value = value_range[1]
        return socket

    @staticmethod
    def _group_input_node(node_group: bpy.types.NodeTree) -> bpy.types.Node:
        return next(n for n in node_group.nodes if n.bl_idname == 'NodeGroupInput')

    @staticmethod
    def _use_voxel_size(node: bpy.types.Node) -> None:
        """Use a voxel size instead of voxel count.

        Blender 4.2 keeps that choice on the node.
        Later versions expose it as a socket.
        """
        socket = node.inputs.get("Resolution Mode")
        if socket is not None:
            socket.default_value = "Size"
        else:
            node.resolution_mode = "VOXEL_SIZE"

    @staticmethod
    def _enabled_socket(sockets: Any, name: str) -> bpy.types.NodeSocket:
        """The live socket of this name.

        Blender 5.1 keeps every data-type variant in collection and disables the unused ones.
        Blender 5.2 leaves only the live socket, so index which was ok on 5.1 is out of range.
        """
        enabled = [socket for socket in sockets if socket.name == name and socket.enabled]
        if enabled:
            return enabled[0]
        for socket in sockets:
            if socket.name == name:
                return socket
        raise KeyError(name)

    @staticmethod
    def _strand_root_position(node_group: bpy.types.NodeTree, location: tuple[float, float]) -> bpy.types.NodeSocket:
        """Where each strand grows out of the scalp.

        A plain Position on the curve domain is averaged over the strand.
        """
        nodes = node_group.nodes
        links = node_group.links

        curve_index = nodes.new('GeometryNodeInputIndex')
        curve_index.location = (location[0] - 360, location[1])

        points_of_curve = nodes.new('GeometryNodePointsOfCurve')
        points_of_curve.location = (location[0] - 180, location[1])
        points_of_curve.inputs['Sort Index'].default_value = 0
        links.new(curve_index.outputs['Index'], points_of_curve.inputs['Curve Index'])

        position = nodes.new('GeometryNodeInputPosition')
        position.location = (location[0] - 180, location[1] - 120)

        root = nodes.new('GeometryNodeFieldAtIndex')
        root.data_type = 'FLOAT_VECTOR'
        root.domain = 'POINT'
        root.location = location
        links.new(position.outputs['Position'], root.inputs['Value'])
        links.new(points_of_curve.outputs['Point Index'], root.inputs['Index'])
        return root.outputs['Value']

    @staticmethod
    def _build_strand_selection(node_group: bpy.types.NodeTree, selection_method: str, basemesh: bpy.types.Object | None,
                                density_socket: str = 'Density', density_default: float = 0.01) -> bpy.types.NodeSocket:
        """Build the part of the graph which decides which curves are kept as cards.

        Returns the boolean output socket meaning "delete this curve", going into a Delete Geometry Selection input.
        """
        nodes = node_group.nodes
        links = node_group.links
        group_in = HairCardService._group_input_node(node_group)

        HairCardService._add_input(node_group, density_socket, 'NodeSocketFloat', density_default, (0.0, 1.0))
        HairCardService._add_input(node_group, 'Seed', 'NodeSocketInt', 0, (0, 9999))
        HairCardService._add_input(node_group, 'Weight vertex group', 'NodeSocketString', "")

        random_value = nodes.new('FunctionNodeRandomValue')
        random_value.data_type = 'FLOAT'
        random_value.location = (-1400, -300)
        links.new(group_in.outputs['Seed'], random_value.inputs['Seed'])

        # The weight map is a vertex group painted on the basemesh, so it is sampled there at the point nearest to each strand
        named_attr = nodes.new('GeometryNodeInputNamedAttribute')
        named_attr.data_type = 'FLOAT'
        named_attr.location = (-1620, -80)
        links.new(group_in.outputs['Weight vertex group'], named_attr.inputs['Name'])

        # Unset or misspelled vertex group means a neutral weight of 1.0
        weight_switch = nodes.new('GeometryNodeSwitch')
        weight_switch.input_type = 'FLOAT'
        weight_switch.location = (-1400, -80)
        links.new(named_attr.outputs['Exists'], weight_switch.inputs[0])
        weight_switch.inputs[1].default_value = 1.0  # False branch: no vertex group, neutral weight
        links.new(named_attr.outputs['Attribute'], weight_switch.inputs[2])  # True branch: painted weight

        weight = weight_switch.outputs[0]
        if basemesh is not None:
            weight_source = nodes.new('GeometryNodeObjectInfo')
            weight_source.location = (-1400, 40)
            weight_source.inputs['Object'].default_value = basemesh
            weight_source.transform_space = 'RELATIVE'

            strand_position = HairCardService._strand_root_position(node_group, (-1400, -240))

            # The switch above is evaluated in the sampled mesh context, so the lookup happens against the basemesh
            sample_weight = nodes.new('GeometryNodeSampleNearestSurface')
            sample_weight.data_type = 'FLOAT'
            sample_weight.location = (-1180, -80)
            links.new(weight_source.outputs['Geometry'], sample_weight.inputs['Mesh'])
            links.new(weight_switch.outputs[0], sample_weight.inputs['Value'])
            links.new(strand_position, sample_weight.inputs['Sample Position'])
            weight = sample_weight.outputs['Value']

        effective_density = nodes.new('ShaderNodeMath')
        effective_density.operation = 'MULTIPLY'
        effective_density.location = (-960, -180)
        links.new(group_in.outputs[density_socket], effective_density.inputs[0])
        links.new(weight, effective_density.inputs[1])

        if selection_method == SELECTION_METHOD_EVERY_NTH:
            HairCardService._add_input(node_group, 'Jitter', 'NodeSocketFloat', 0.15, (0.0, 1.0))

            index_node = nodes.new('GeometryNodeInputIndex')
            index_node.location = (-1400, 150)

            density_clamped = nodes.new('ShaderNodeClamp')
            density_clamped.location = (-960, 150)
            links.new(effective_density.outputs[0], density_clamped.inputs[0])
            density_clamped.inputs[1].default_value = 0.001  # Min
            density_clamped.inputs[2].default_value = 1.0  # Max

            inv_density = nodes.new('ShaderNodeMath')
            inv_density.operation = 'DIVIDE'
            inv_density.location = (-780, 150)
            inv_density.inputs[0].default_value = 1.0
            links.new(density_clamped.outputs[0], inv_density.inputs[1])

            step = nodes.new('ShaderNodeMath')
            step.operation = 'ROUND'
            step.location = (-600, 150)
            links.new(inv_density.outputs[0], step.inputs[0])

            index_mod = nodes.new('ShaderNodeMath')
            index_mod.operation = 'MODULO'
            index_mod.location = (-420, 150)
            links.new(index_node.outputs['Index'], index_mod.inputs[0])
            links.new(step.outputs[0], index_mod.inputs[1])

            on_grid = nodes.new('FunctionNodeCompare')
            on_grid.data_type = 'FLOAT'
            on_grid.operation = 'LESS_THAN'
            on_grid.location = (-240, 150)
            links.new(index_mod.outputs[0], on_grid.inputs[0])
            on_grid.inputs[1].default_value = 1.0

            # Extra random inclusion on top of the grid, so the pattern is not repetetive
            jitter_mul = nodes.new('ShaderNodeMath')
            jitter_mul.operation = 'MULTIPLY'
            jitter_mul.location = (-420, 20)
            links.new(group_in.outputs['Jitter'], jitter_mul.inputs[0])
            links.new(effective_density.outputs[0], jitter_mul.inputs[1])

            jitter_extra = nodes.new('FunctionNodeCompare')
            jitter_extra.data_type = 'FLOAT'
            jitter_extra.operation = 'LESS_THAN'
            jitter_extra.location = (-240, 20)
            links.new(HairCardService._enabled_socket(random_value.outputs, "Value"), jitter_extra.inputs[0])
            links.new(jitter_mul.outputs[0], jitter_extra.inputs[1])

            keep = nodes.new('FunctionNodeBooleanMath')
            keep.operation = 'OR'
            keep.location = (-60, 100)
            links.new(on_grid.outputs['Result'], keep.inputs[0])
            links.new(jitter_extra.outputs['Result'], keep.inputs[1])

            delete_selection = nodes.new('FunctionNodeBooleanMath')
            delete_selection.operation = 'NOT'
            delete_selection.location = (120, 100)
            links.new(keep.outputs[0], delete_selection.inputs[0])
            return delete_selection.outputs[0]

        if selection_method == SELECTION_METHOD_POISSON and basemesh is not None:
            HairCardService._add_input(node_group, 'Poisson radius', 'NodeSocketFloat', 0.02, (0.001, 0.2))

            scalp_info = nodes.new('GeometryNodeObjectInfo')
            scalp_info.location = (-1400, 420)
            scalp_info.inputs['Object'].default_value = basemesh
            scalp_info.transform_space = 'RELATIVE'

            distribute = nodes.new('GeometryNodeDistributePointsOnFaces')
            distribute.distribute_method = 'POISSON'  # also enables the Density Max/Factor sockets below
            distribute.location = (-1180, 420)
            links.new(scalp_info.outputs['Geometry'], distribute.inputs['Mesh'])
            distribute.inputs['Density Max'].default_value = 6000.0
            links.new(effective_density.outputs[0], distribute.inputs['Density Factor'])
            links.new(group_in.outputs['Seed'], distribute.inputs['Seed'])

            root_position = HairCardService._strand_root_position(node_group, (-960, 420))

            proximity = nodes.new('GeometryNodeProximity')
            proximity.target_element = 'POINTS'
            proximity.location = (-780, 420)
            links.new(distribute.outputs['Points'], proximity.inputs['Geometry'])
            links.new(root_position, proximity.inputs['Sample Position'])

            near_scalp_sample = nodes.new('FunctionNodeCompare')
            near_scalp_sample.data_type = 'FLOAT'
            near_scalp_sample.operation = 'LESS_THAN'
            near_scalp_sample.location = (-600, 420)
            links.new(proximity.outputs['Distance'], near_scalp_sample.inputs[0])
            links.new(group_in.outputs['Poisson radius'], near_scalp_sample.inputs[1])

            delete_selection = nodes.new('FunctionNodeBooleanMath')
            delete_selection.operation = 'NOT'
            delete_selection.location = (-420, 420)
            links.new(near_scalp_sample.outputs['Result'], delete_selection.inputs[0])
            return delete_selection.outputs[0]

        # Default / fallback: independent random draw per strand, weighted by the vertex group
        compare = nodes.new('FunctionNodeCompare')
        compare.data_type = 'FLOAT'
        compare.operation = 'GREATER_THAN'
        compare.location = (-600, -300)
        links.new(HairCardService._enabled_socket(random_value.outputs, "Value"), compare.inputs[0])
        links.new(effective_density.outputs[0], compare.inputs[1])
        return compare.outputs['Result']

    @staticmethod
    def _build_cluster_blend(node_group: bpy.types.NodeTree, geometry_socket: bpy.types.NodeSocket, location: tuple[float, float]) -> bpy.types.NodeSocket:
        """Blend each kept strand points towards the points of its nearest neighbouring strand.

        A pairwise blend with the nearest strand from the other half of the strand pool.
        """
        nodes = node_group.nodes
        links = node_group.links
        group_in = HairCardService._group_input_node(node_group)

        HairCardService._add_input(node_group, 'Cluster strength', 'NodeSocketFloat', 0.0, (0.0, 1.0))

        def parity(loc):
            """Split strands into evens and odds.

            The nearest point is taken from the other group, so it cannot be a point of this strand.
            """
            curve_of_point = nodes.new('GeometryNodeCurveOfPoint')
            curve_of_point.location = (loc[0] - 180, loc[1])
            bucket = nodes.new('ShaderNodeMath')
            bucket.operation = 'MODULO'
            bucket.location = loc
            links.new(curve_of_point.outputs['Curve Index'], bucket.inputs[0])
            bucket.inputs[1].default_value = 2.0
            return bucket.outputs[0]

        def as_int(value_socket, loc):
            to_int = nodes.new('FunctionNodeFloatToInt')
            to_int.rounding_mode = 'FLOOR'
            to_int.location = loc
            links.new(value_socket, to_int.inputs[0])
            return to_int.outputs[0]

        # Proximity cannot read curve geometry, so the strands are handed over as point cloud.
        # The parity is captured on the point domain to survive the conversion.
        own_parity = as_int(parity((location[0] - 700, location[1] - 100)), (location[0] - 540, location[1] - 100))

        capture = nodes.new('GeometryNodeCaptureAttribute')
        capture.domain = 'POINT'
        capture.location = (location[0] - 360, location[1] - 100)
        capture.capture_items.new('INT', "strand_parity")
        links.new(geometry_socket, capture.inputs[0])
        links.new(own_parity, HairCardService._enabled_socket(capture.inputs, "strand_parity"))

        strand_points = nodes.new('GeometryNodeCurveToPoints')
        strand_points.mode = 'EVALUATED'
        strand_points.location = (location[0] - 160, location[1] - 100)
        links.new(capture.outputs[0], strand_points.inputs['Curve'])

        other_parity = nodes.new('ShaderNodeMath')
        other_parity.operation = 'SUBTRACT'
        other_parity.location = (location[0] - 360, location[1] - 260)
        other_parity.inputs[0].default_value = 1.0
        links.new(parity((location[0] - 540, location[1] - 260)), other_parity.inputs[1])

        position = nodes.new('GeometryNodeInputPosition')
        position.location = (location[0] - 160, location[1] + 40)

        proximity = nodes.new('GeometryNodeProximity')
        proximity.target_element = 'POINTS'
        proximity.location = (location[0] + 260, location[1] - 40)
        links.new(strand_points.outputs['Points'], proximity.inputs['Geometry'])
        links.new(HairCardService._enabled_socket(capture.outputs, "strand_parity"), proximity.inputs['Group ID'])
        links.new(position.outputs['Position'], proximity.inputs['Sample Position'])
        links.new(as_int(other_parity.outputs[0], (location[0] - 160, location[1] - 260)),
                  proximity.inputs['Sample Group ID'])

        # No partner strand to pull towards - keep the point where it is
        effective_strength = nodes.new('ShaderNodeMath')
        effective_strength.operation = 'MULTIPLY'
        effective_strength.location = (location[0] + 440, location[1] + 120)
        links.new(group_in.outputs['Cluster strength'], effective_strength.inputs[0])
        links.new(proximity.outputs['Is Valid'], effective_strength.inputs[1])

        mix = nodes.new('ShaderNodeMix')
        mix.data_type = 'VECTOR'
        mix.location = (location[0] + 440, location[1] - 40)
        # inputs[0] is scalar Factor. inputs[1] is disabled unless factor_mode is 'NON_UNIFORM'
        links.new(effective_strength.outputs[0], mix.inputs[0])  # Factor (scalar)
        links.new(position.outputs['Position'], mix.inputs[4])  # A (vector variant)
        links.new(proximity.outputs['Position'], mix.inputs[5])  # B (vector variant)

        set_position = nodes.new('GeometryNodeSetPosition')
        set_position.location = (location[0] + 620, location[1] - 40)
        links.new(capture.outputs[0], set_position.inputs['Geometry'])
        links.new(mix.outputs[1], set_position.inputs['Position'])  # Result (vector variant)

        return set_position.outputs['Geometry']

    @staticmethod
    def _build_offset(node_group: bpy.types.NodeTree, geometry_socket: bpy.types.NodeSocket, basemesh: bpy.types.Object | None, location: tuple[float, float]) -> bpy.types.NodeSocket:
        """Push every point away from the scalp by the live "Offset" input.

        The direction is basemesh surface normal at the nearest point. Without basemesh it falls back to curve normal.
        """
        nodes = node_group.nodes
        links = node_group.links
        group_in = HairCardService._group_input_node(node_group)

        HairCardService._add_input(node_group, 'Offset', 'NodeSocketFloat', 0.0, (0.0, 0.1))

        if basemesh is not None:
            scalp_info = nodes.new('GeometryNodeObjectInfo')
            scalp_info.location = (location[0] - 540, location[1] - 160)
            scalp_info.inputs['Object'].default_value = basemesh
            scalp_info.transform_space = 'RELATIVE'

            scalp_normal = nodes.new('GeometryNodeInputNormal')
            scalp_normal.location = (location[0] - 540, location[1] - 320)

            position = nodes.new('GeometryNodeInputPosition')
            position.location = (location[0] - 540, location[1] - 400)

            sample_scalp = nodes.new('GeometryNodeSampleNearestSurface')
            sample_scalp.data_type = 'FLOAT_VECTOR'
            sample_scalp.location = (location[0] - 360, location[1] - 220)
            links.new(scalp_info.outputs['Geometry'], sample_scalp.inputs['Mesh'])
            links.new(scalp_normal.outputs['Normal'], sample_scalp.inputs['Value'])
            links.new(position.outputs['Position'], sample_scalp.inputs['Sample Position'])
            direction = sample_scalp.outputs['Value']
        else:
            curve_normal = nodes.new('GeometryNodeInputNormal')
            curve_normal.location = (location[0] - 360, location[1] - 220)
            direction = curve_normal.outputs['Normal']

        normalize = nodes.new('ShaderNodeVectorMath')
        normalize.operation = 'NORMALIZE'
        normalize.location = (location[0] - 180, location[1] - 220)
        links.new(direction, normalize.inputs[0])

        offset_vec = nodes.new('ShaderNodeVectorMath')
        offset_vec.operation = 'SCALE'
        offset_vec.location = (location[0] - 180, location[1] - 120)
        links.new(normalize.outputs[0], offset_vec.inputs[0])
        links.new(group_in.outputs['Offset'], offset_vec.inputs['Scale'])

        offset_pos = nodes.new('GeometryNodeSetPosition')
        offset_pos.location = location
        links.new(geometry_socket, offset_pos.inputs['Geometry'])
        links.new(offset_vec.outputs[0], offset_pos.inputs['Offset'])
        return offset_pos.outputs['Geometry']

    @staticmethod
    def _capture_per_curve_random_vector(node_group: bpy.types.NodeTree, geometry_socket: bpy.types.NodeSocket, location: tuple[float, float]) -> tuple[bpy.types.NodeSocket, bpy.types.NodeSocket]:
        """One random 0..1 vector per curve (constant along all of a strand points).

        Returns (geometry_output_socket, vector_attribute_output_socket).
        """
        nodes = node_group.nodes
        links = node_group.links
        group_in = HairCardService._group_input_node(node_group)

        index_node = nodes.new('GeometryNodeInputIndex')
        index_node.location = (location[0] - 200, location[1] - 60)

        random_value = nodes.new('FunctionNodeRandomValue')
        random_value.data_type = 'FLOAT_VECTOR'
        random_value.location = (location[0], location[1] - 60)
        links.new(group_in.outputs['Seed'], HairCardService._enabled_socket(random_value.inputs, "Seed"))
        links.new(index_node.outputs['Index'], HairCardService._enabled_socket(random_value.inputs, "ID"))

        capture = nodes.new('GeometryNodeCaptureAttribute')
        capture.domain = 'CURVE'
        capture.location = (location[0] + 200, location[1])
        capture.capture_items.new('VECTOR', "per_curve_random")
        links.new(geometry_socket, capture.inputs[0])
        links.new(HairCardService._enabled_socket(random_value.outputs, "Value"), HairCardService._enabled_socket(capture.inputs, "per_curve_random"))
        return capture.outputs[0], HairCardService._enabled_socket(capture.outputs, "per_curve_random")

    @staticmethod
    def build_tiles_node_group(group_name: str, selection_method: str, basemesh: bpy.types.Object | None) -> bpy.types.NodeTree:
        node_group = HairCardService._new_group(group_name)
        nodes = node_group.nodes
        links = node_group.links
        group_in = HairCardService._group_input_node(node_group)
        group_out = next(n for n in nodes if n.bl_idname == 'NodeGroupOutput')
        group_in.location = (-2200, 0)
        group_out.location = (1400, 0)

        delete_selection = HairCardService._build_strand_selection(node_group, selection_method, basemesh)

        delete = nodes.new('GeometryNodeDeleteGeometry')
        delete.domain = 'CURVE'
        delete.location = (-800, 0)
        links.new(group_in.outputs['Geometry'], delete.inputs['Geometry'])
        links.new(delete_selection, delete.inputs['Selection'])

        blended = HairCardService._build_cluster_blend(node_group, delete.outputs['Geometry'], (-600, -700))

        HairCardService._add_input(node_group, 'Segments', 'NodeSocketInt', 8, (2, 64))
        resample = nodes.new('GeometryNodeResampleCurve')
        resample.location = (-360, 0)
        links.new(blended, resample.inputs['Curve'])
        links.new(group_in.outputs['Segments'], resample.inputs['Count'])

        offset_geometry = HairCardService._build_offset(node_group, resample.outputs['Curve'], basemesh, (0, 0))

        HairCardService._add_input(node_group, 'Card width', 'NodeSocketFloat', 0.03, (0.001, 0.5))
        HairCardService._add_input(node_group, 'Card length', 'NodeSocketFloat', 0.03, (0.001, 0.5))
        HairCardService._add_input(node_group, 'Width random', 'NodeSocketFloat', 0.0, (0.0, 1.0))
        HairCardService._add_input(node_group, 'Length random', 'NodeSocketFloat', 0.0, (0.0, 1.0))
        HairCardService._add_input(node_group, 'Tilt random', 'NodeSocketFloat', 0.0, (0.0, 1.0))
        HairCardService._add_input(node_group, 'Scale', 'NodeSocketFloat', 1.0, (0.01, 5.0))

        points_geometry, variation_vector = HairCardService._capture_per_curve_random_vector(node_group, offset_geometry, (-360, 500))
        separate_rand = nodes.new('ShaderNodeSeparateXYZ')
        separate_rand.location = (-160, 500)
        links.new(variation_vector, separate_rand.inputs[0])

        def _signed_jitter(component_socket, amount_socket, loc):
            signed = nodes.new('ShaderNodeMath')
            signed.operation = 'SUBTRACT'
            signed.location = loc
            links.new(component_socket, signed.inputs[0])
            signed.inputs[1].default_value = 0.5
            scaled = nodes.new('ShaderNodeMath')
            scaled.operation = 'MULTIPLY'
            scaled.location = (loc[0] + 160, loc[1])
            links.new(signed.outputs[0], scaled.inputs[0])
            links.new(amount_socket, scaled.inputs[1])
            factor = nodes.new('ShaderNodeMath')
            factor.operation = 'ADD'
            factor.location = (loc[0] + 320, loc[1])
            factor.inputs[0].default_value = 1.0
            links.new(scaled.outputs[0], factor.inputs[1])
            return factor.outputs[0]

        width_factor = _signed_jitter(separate_rand.outputs[0], group_in.outputs['Width random'], (60, 620))
        length_factor = _signed_jitter(separate_rand.outputs[1], group_in.outputs['Length random'], (60, 480))
        tilt_factor = _signed_jitter(separate_rand.outputs[2], group_in.outputs['Tilt random'], (60, 340))

        # Grid is a fixed 1x1 quad, sizing happens in Instance on Points Scale.
        grid = nodes.new('GeometryNodeMeshGrid')
        grid.inputs['Vertices X'].default_value = 2
        grid.inputs['Vertices Y'].default_value = 2
        grid.inputs['Size X'].default_value = 1.0
        grid.inputs['Size Y'].default_value = 1.0
        grid.location = (620, 550)

        # Tile UVs come from the Grid node: U across the quad, V along the strand
        tile_uv = nodes.new('GeometryNodeStoreNamedAttribute')
        tile_uv.data_type = 'FLOAT2'
        tile_uv.domain = 'CORNER'
        tile_uv.inputs['Name'].default_value = CARDS_UV_MAP
        tile_uv.location = (800, 700)
        links.new(grid.outputs['Mesh'], tile_uv.inputs['Geometry'])
        links.new(grid.outputs['UV Map'], tile_uv.inputs['Value'])

        width_final = nodes.new('ShaderNodeMath')
        width_final.operation = 'MULTIPLY'
        width_final.location = (420, 620)
        links.new(group_in.outputs['Card width'], width_final.inputs[0])
        links.new(width_factor, width_final.inputs[1])

        length_final = nodes.new('ShaderNodeMath')
        length_final.operation = 'MULTIPLY'
        length_final.location = (420, 480)
        links.new(group_in.outputs['Card length'], length_final.inputs[0])
        links.new(length_factor, length_final.inputs[1])

        width_scaled = nodes.new('ShaderNodeMath')
        width_scaled.operation = 'MULTIPLY'
        width_scaled.location = (600, 620)
        links.new(width_final.outputs[0], width_scaled.inputs[0])
        links.new(group_in.outputs['Scale'], width_scaled.inputs[1])

        length_scaled = nodes.new('ShaderNodeMath')
        length_scaled.operation = 'MULTIPLY'
        length_scaled.location = (600, 480)
        links.new(length_final.outputs[0], length_scaled.inputs[0])
        links.new(group_in.outputs['Scale'], length_scaled.inputs[1])

        card_scale = nodes.new('ShaderNodeCombineXYZ')
        card_scale.location = (800, 550)
        links.new(width_scaled.outputs[0], card_scale.inputs['X'])
        links.new(length_scaled.outputs[0], card_scale.inputs['Y'])
        links.new(group_in.outputs['Scale'], card_scale.inputs['Z'])

        tangent = nodes.new('GeometryNodeInputTangent')
        tangent.location = (0, 200)
        normal2 = nodes.new('GeometryNodeInputNormal')
        normal2.location = (0, 100)

        # Tilt: rotation of the card around its strand by up to +/- 90 degrees. tilt_factor is 1.0 +/- amount/2
        tilt_signed = nodes.new('ShaderNodeMath')
        tilt_signed.operation = 'SUBTRACT'
        tilt_signed.location = (240, 340)
        links.new(tilt_factor, tilt_signed.inputs[0])
        tilt_signed.inputs[1].default_value = 1.0

        tilt_radians = nodes.new('ShaderNodeMath')
        tilt_radians.operation = 'MULTIPLY'
        tilt_radians.location = (420, 340)
        links.new(tilt_signed.outputs[0], tilt_radians.inputs[0])
        tilt_radians.inputs[1].default_value = math.pi

        tilt_rotation = nodes.new('FunctionNodeAxisAngleToRotation')
        tilt_rotation.location = (240, 200)
        links.new(tangent.outputs['Tangent'], tilt_rotation.inputs['Axis'])
        links.new(tilt_radians.outputs[0], tilt_rotation.inputs['Angle'])

        tilted_axis = nodes.new('FunctionNodeRotateVector')
        tilted_axis.location = (440, 200)
        links.new(normal2.outputs['Normal'], tilted_axis.inputs['Vector'])
        links.new(tilt_rotation.outputs['Rotation'], tilted_axis.inputs['Rotation'])

        align_length = nodes.new('FunctionNodeAlignRotationToVector')
        align_length.axis = 'Y'
        align_length.pivot_axis = 'AUTO'
        align_length.location = (640, 380)
        links.new(tangent.outputs['Tangent'], align_length.inputs['Vector'])

        align_face = nodes.new('FunctionNodeAlignRotationToVector')
        align_face.axis = 'Z'
        align_face.pivot_axis = 'Y'
        align_face.location = (820, 380)
        links.new(align_length.outputs['Rotation'], align_face.inputs['Rotation'])
        links.new(tilted_axis.outputs['Vector'], align_face.inputs['Vector'])

        instance = nodes.new('GeometryNodeInstanceOnPoints')
        instance.location = (1000, 0)
        links.new(points_geometry, instance.inputs['Points'])
        links.new(tile_uv.outputs['Geometry'], instance.inputs['Instance'])
        links.new(align_face.outputs['Rotation'], instance.inputs['Rotation'])
        links.new(card_scale.outputs['Vector'], instance.inputs['Scale'])

        realize = nodes.new('GeometryNodeRealizeInstances')
        realize.location = (1200, 0)
        links.new(instance.outputs['Instances'], realize.inputs['Geometry'])
        links.new(realize.outputs['Geometry'], group_out.inputs['Geometry'])

        return node_group

    @staticmethod
    def _build_tip_extension(node_group: bpy.types.NodeTree, curve_socket: bpy.types.NodeSocket, location: tuple[float, float]) -> bpy.types.NodeSocket:
        """Push the last point of every curve out along its own tangent. Returns the curve socket.

        Extending the card past the strand tip gives the bake somewhere to put the last bit of hair.
        Blender 5.1 has no Extend Curves node - the endpoint is moved along its tangent instead.
        """
        nodes = node_group.nodes
        links = node_group.links
        group_in = HairCardService._group_input_node(node_group)
        x, y = location

        HairCardService._add_input(node_group, 'Extend tip', 'NodeSocketFloat', 0.0, (0.0, 0.1))

        endpoint = nodes.new('GeometryNodeCurveEndpointSelection')
        endpoint.location = (x, y + 120)
        endpoint.inputs['Start Size'].default_value = 0
        endpoint.inputs['End Size'].default_value = 1

        tangent = nodes.new('GeometryNodeInputTangent')
        tangent.location = (x, y - 60)

        offset = nodes.new('ShaderNodeVectorMath')
        offset.operation = 'SCALE'
        offset.location = (x + 180, y - 60)
        links.new(tangent.outputs['Tangent'], offset.inputs[0])
        links.new(group_in.outputs['Extend tip'], offset.inputs['Scale'])

        set_position = nodes.new('GeometryNodeSetPosition')
        set_position.location = (x + 360, y)
        links.new(curve_socket, set_position.inputs['Geometry'])
        links.new(endpoint.outputs['Selection'], set_position.inputs['Selection'])
        links.new(offset.outputs['Vector'], set_position.inputs['Offset'])
        return set_position.outputs['Geometry']

    @staticmethod
    def _build_ribbon_shape(node_group: bpy.types.NodeTree, curve_socket: bpy.types.NodeSocket, basemesh: bpy.types.Object | None, base_width_socket: bpy.types.NodeSocket | None = None,
                            location: tuple[float, float] = (0, 0), profile_steps: int = 16) -> bpy.types.NodeSocket:
        """Turn a set of curves into taperable, twistable ribbon cards with hair-aligned UVs.

        Shared by RIBBON (one card per strand) and CLUSTER_RIBBON (one card per cluster).
        Returns the mesh output socket.

        ``base_width_socket`` optionally replaces the flat "Card width" input with a per-curve width.
        """
        nodes = node_group.nodes
        links = node_group.links
        group_in = HairCardService._group_input_node(node_group)
        x, y = location

        HairCardService._add_input(node_group, 'Profile steps', 'NodeSocketInt', profile_steps, (2, 64))
        resample = nodes.new('GeometryNodeResampleCurve')
        resample.location = (x - 360, y)
        links.new(curve_socket, resample.inputs['Curve'])
        links.new(group_in.outputs['Profile steps'], resample.inputs['Count'])

        extended = HairCardService._build_tip_extension(node_group, resample.outputs['Curve'], (x - 360, y - 300))
        offset_geometry = HairCardService._build_offset(node_group, extended, basemesh, (x, y))

        # Taper: the ribbon narrows towards the tip according to "Taper" (0 = uniform, 1 = to a point)
        if base_width_socket is None:
            HairCardService._add_input(node_group, 'Card width', 'NodeSocketFloat', 0.03, (0.001, 0.5))
        HairCardService._add_input(node_group, 'Taper', 'NodeSocketFloat', 0.3, (0.0, 1.0))
        spline_param = nodes.new('GeometryNodeSplineParameter')
        spline_param.location = (x, y + 260)

        taper_amount = nodes.new('ShaderNodeMath')
        taper_amount.operation = 'MULTIPLY'
        taper_amount.location = (x + 180, y + 260)
        links.new(spline_param.outputs['Factor'], taper_amount.inputs[0])
        links.new(group_in.outputs['Taper'], taper_amount.inputs[1])

        taper_factor = nodes.new('ShaderNodeMath')
        taper_factor.operation = 'SUBTRACT'
        taper_factor.location = (x + 360, y + 260)
        taper_factor.inputs[0].default_value = 1.0
        links.new(taper_amount.outputs[0], taper_factor.inputs[1])

        # Width of the ribbon at this point along the strand.
        ribbon_width = nodes.new('ShaderNodeMath')
        ribbon_width.operation = 'MULTIPLY'
        ribbon_width.location = (x + 540, y + 200)
        links.new(base_width_socket or group_in.outputs['Card width'], ribbon_width.inputs[0])
        links.new(taper_factor.outputs[0], ribbon_width.inputs[1])

        # Twist: a progressive rotation of the ribbon along strand
        HairCardService._add_input(node_group, 'Twist', 'NodeSocketFloat', 0.0, (-4.0, 4.0))
        twist_turns = nodes.new('ShaderNodeMath')
        twist_turns.operation = 'MULTIPLY'
        twist_turns.location = (x + 180, y - 140)
        links.new(group_in.outputs['Twist'], twist_turns.inputs[0])
        twist_turns.inputs[1].default_value = 2.0 * math.pi

        twist_angle = nodes.new('ShaderNodeMath')
        twist_angle.operation = 'MULTIPLY'
        twist_angle.location = (x + 360, y - 140)
        links.new(spline_param.outputs['Factor'], twist_angle.inputs[0])
        links.new(twist_turns.outputs[0], twist_angle.inputs[1])

        set_tilt = nodes.new('GeometryNodeSetCurveTilt')
        set_tilt.location = (x + 900, y)
        links.new(offset_geometry, set_tilt.inputs['Curve'])
        links.new(twist_angle.outputs[0], set_tilt.inputs['Tilt'])

        # UVs: V along the strand, U across the ribbon, the same as tiles and cluster boxes (the atlas packs cards that way).
        # Curve to Mesh carries point attributes of both inputs (V on curve, U on profile).
        store_along = nodes.new('GeometryNodeStoreNamedAttribute')
        store_along.data_type = 'FLOAT'
        store_along.domain = 'POINT'
        store_along.inputs['Name'].default_value = _CARD_V_ATTRIBUTE
        store_along.location = (x + 1080, y)
        links.new(set_tilt.outputs['Curve'], store_along.inputs['Geometry'])
        links.new(spline_param.outputs['Factor'], store_along.inputs['Value'])

        # Unit-long profile, so Scale is card width in metres
        profile = nodes.new('GeometryNodeCurvePrimitiveLine')
        profile.location = (x + 720, y - 320)
        profile.inputs['Start'].default_value = (-0.5, 0.0, 0.0)
        profile.inputs['End'].default_value = (0.5, 0.0, 0.0)

        profile_param = nodes.new('GeometryNodeSplineParameter')
        profile_param.location = (x + 720, y - 460)

        store_across = nodes.new('GeometryNodeStoreNamedAttribute')
        store_across.data_type = 'FLOAT'
        store_across.domain = 'POINT'
        store_across.inputs['Name'].default_value = _CARD_U_ATTRIBUTE
        store_across.location = (x + 900, y - 320)
        links.new(profile.outputs['Curve'], store_across.inputs['Geometry'])
        links.new(profile_param.outputs['Factor'], store_across.inputs['Value'])

        curve_to_mesh = nodes.new('GeometryNodeCurveToMesh')
        curve_to_mesh.location = (x + 1260, y - 100)
        links.new(store_across.outputs['Geometry'], curve_to_mesh.inputs['Profile Curve'])
        # Unit-long profile, so this factor is the card width in metres.
        # 4.2 has no Scale input and uses radius instead with a fraction of milimeter
        scale_input = curve_to_mesh.inputs.get('Scale')
        if scale_input is not None:
            links.new(store_along.outputs['Geometry'], curve_to_mesh.inputs['Curve'])
            links.new(ribbon_width.outputs[0], scale_input)
        else:
            set_radius = nodes.new('GeometryNodeSetCurveRadius')
            set_radius.location = (x + 1080, y + 160)
            links.new(store_along.outputs['Geometry'], set_radius.inputs['Curve'])
            links.new(ribbon_width.outputs[0], set_radius.inputs['Radius'])
            links.new(set_radius.outputs['Curve'], curve_to_mesh.inputs['Curve'])

        return HairCardService._store_card_uvs(node_group, curve_to_mesh.outputs['Mesh'], (x + 1500, y))

    @staticmethod
    def _store_card_uvs(node_group: bpy.types.NodeTree, mesh_socket: bpy.types.NodeSocket, location: tuple[float, float]) -> bpy.types.NodeSocket:
        """Combine the scratch U/V attributes left by _build_ribbon_shape() into UV map."""
        nodes = node_group.nodes
        links = node_group.links

        read_u = nodes.new('GeometryNodeInputNamedAttribute')
        read_u.data_type = 'FLOAT'
        read_u.inputs['Name'].default_value = _CARD_U_ATTRIBUTE
        read_u.location = (location[0] - 360, location[1] - 200)

        read_v = nodes.new('GeometryNodeInputNamedAttribute')
        read_v.data_type = 'FLOAT'
        read_v.inputs['Name'].default_value = _CARD_V_ATTRIBUTE
        read_v.location = (location[0] - 360, location[1] - 340)

        uv = nodes.new('ShaderNodeCombineXYZ')
        uv.location = (location[0] - 180, location[1] - 260)
        links.new(read_u.outputs['Attribute'], uv.inputs['X'])
        links.new(read_v.outputs['Attribute'], uv.inputs['Y'])

        store_uv = nodes.new('GeometryNodeStoreNamedAttribute')
        store_uv.data_type = 'FLOAT2'
        store_uv.domain = 'CORNER'
        store_uv.inputs['Name'].default_value = CARDS_UV_MAP
        store_uv.location = location
        links.new(mesh_socket, store_uv.inputs['Geometry'])
        links.new(uv.outputs['Vector'], store_uv.inputs['Value'])

        # Remove scratch attributes
        geometry = store_uv.outputs['Geometry']
        for index, name in enumerate((_CARD_U_ATTRIBUTE, _CARD_V_ATTRIBUTE)):
            remove = nodes.new('GeometryNodeRemoveAttribute')
            remove.location = (location[0] + 180 + index * 180, location[1])
            remove.inputs['Name'].default_value = name
            links.new(geometry, remove.inputs['Geometry'])
            geometry = remove.outputs['Geometry']
        return geometry

    @staticmethod
    def build_ribbon_node_group(group_name: str, selection_method: str, basemesh: bpy.types.Object | None) -> bpy.types.NodeTree:
        node_group = HairCardService._new_group(group_name)
        nodes = node_group.nodes
        links = node_group.links
        group_in = HairCardService._group_input_node(node_group)
        group_out = next(n for n in nodes if n.bl_idname == 'NodeGroupOutput')
        group_in.location = (-2000, 0)
        group_out.location = (2100, 0)

        delete_selection = HairCardService._build_strand_selection(node_group, selection_method, basemesh)

        delete = nodes.new('GeometryNodeDeleteGeometry')
        delete.domain = 'CURVE'
        delete.location = (-800, 0)
        links.new(group_in.outputs['Geometry'], delete.inputs['Geometry'])
        links.new(delete_selection, delete.inputs['Selection'])

        blended = HairCardService._build_cluster_blend(node_group, delete.outputs['Geometry'], (-600, -500))

        links.new(HairCardService._build_ribbon_shape(node_group, blended, basemesh), group_out.inputs['Geometry'])
        return node_group

    @staticmethod
    def build_cluster_ribbon_node_group(group_name: str, basemesh: bpy.types.Object | None) -> bpy.types.NodeTree:
        """Shape the pre-averaged cluster poly-lines from build_cluster_ribbon_mesh() into ribbon cards.

        No strand selection here, the input is already one poly-line per cluster (bundle).
        "Width from cluster" scales each card by the cluster thickness.
        """
        node_group = HairCardService._new_group(group_name)
        nodes = node_group.nodes
        links = node_group.links
        group_in = HairCardService._group_input_node(node_group)
        group_out = next(n for n in nodes if n.bl_idname == 'NodeGroupOutput')
        group_in.location = (-1200, 0)
        group_out.location = (2100, 0)

        to_curve = nodes.new('GeometryNodeMeshToCurve')
        to_curve.location = (-1000, 0)
        links.new(group_in.outputs['Geometry'], to_curve.inputs['Mesh'])

        HairCardService._add_input(node_group, 'Card width', 'NodeSocketFloat', 0.03, (0.001, 0.5))
        HairCardService._add_input(node_group, 'Width from cluster', 'NodeSocketFloat', 0.6, (0.0, 1.0))

        measured = nodes.new('GeometryNodeInputNamedAttribute')
        measured.data_type = 'FLOAT'
        measured.inputs['Name'].default_value = CLUSTER_WIDTH_ATTRIBUTE
        measured.location = (-1000, -300)

        measured_width = nodes.new('ShaderNodeMath')
        measured_width.operation = 'MULTIPLY'
        measured_width.location = (-820, -300)
        links.new(measured.outputs['Attribute'], measured_width.inputs[0])
        measured_width.inputs[1].default_value = 2.0  # stored as a half width

        base_width = nodes.new('ShaderNodeMix')
        base_width.data_type = 'FLOAT'
        base_width.location = (-640, -300)
        links.new(group_in.outputs['Width from cluster'], base_width.inputs[0])  # Factor
        links.new(group_in.outputs['Card width'], base_width.inputs[2])  # A (float variant)
        links.new(measured_width.outputs[0], base_width.inputs[3])  # B (float variant)

        # Fewer profile steps than plain ribbon - the input is already a smooth resampled average
        mesh = HairCardService._build_ribbon_shape(node_group, to_curve.outputs['Curve'], basemesh,
                                   base_width_socket=base_width.outputs[0],
                                   profile_steps=CLUSTER_RIBBON_PROFILE_STEPS)
        links.new(mesh, group_out.inputs['Geometry'])
        return node_group

    @staticmethod
    def _build_shell_hug(node_group: bpy.types.NodeTree, shell_socket: bpy.types.NodeSocket, curves_socket: bpy.types.NodeSocket, location: tuple[float, float]) -> bpy.types.NodeSocket:
        """Pull every shell vertex towards the nearest actual hair point by the "Hug strands" amount.

        0: Shell is just raw isosurface inflated by the strand radius 
        1: Shell sits on the outermost strands

        Vertices with no hair near them keep their position, since Is Valid gates the blend.
        """
        nodes = node_group.nodes
        links = node_group.links
        group_in = HairCardService._group_input_node(node_group)

        HairCardService._add_input(node_group, 'Hug strands', 'NodeSocketFloat', 0.7, (0.0, 1.0))

        # Proximity cannot read curve geometry, so the strands are handed over as a point cloud
        strand_points = nodes.new('GeometryNodeCurveToPoints')
        strand_points.mode = 'EVALUATED'
        strand_points.location = (location[0] - 360, location[1])
        links.new(curves_socket, strand_points.inputs['Curve'])

        position = nodes.new('GeometryNodeInputPosition')
        position.location = (location[0] - 360, location[1] - 160)

        proximity = nodes.new('GeometryNodeProximity')
        proximity.target_element = 'POINTS'
        proximity.location = (location[0] - 160, location[1])
        links.new(strand_points.outputs['Points'], proximity.inputs['Geometry'])
        links.new(position.outputs['Position'], proximity.inputs['Sample Position'])

        strength = nodes.new('ShaderNodeMath')
        strength.operation = 'MULTIPLY'
        strength.location = (location[0] + 20, location[1] + 140)
        links.new(group_in.outputs['Hug strands'], strength.inputs[0])
        links.new(proximity.outputs['Is Valid'], strength.inputs[1])

        mix = nodes.new('ShaderNodeMix')
        mix.data_type = 'VECTOR'
        mix.location = (location[0] + 20, location[1])
        links.new(strength.outputs[0], mix.inputs[0])  # Factor (scalar)
        links.new(position.outputs['Position'], mix.inputs[4])  # A (vector variant)
        links.new(proximity.outputs['Position'], mix.inputs[5])  # B (vector variant)

        set_position = nodes.new('GeometryNodeSetPosition')
        set_position.location = (location[0] + 220, location[1])
        links.new(shell_socket, set_position.inputs['Geometry'])
        links.new(mix.outputs[1], set_position.inputs['Position'])  # Result (vector variant)
        return set_position.outputs['Geometry']

    @staticmethod
    def _build_shell_base(node_group: bpy.types.NodeTree, basemesh: bpy.types.Object | None) -> bpy.types.NodeSocket:
        """Thin the strands, turn them into a volume and back into a smoothed mesh shell.

        Points to Volume puts a sphere of "Strand radius" around every sampled strand point, so the hull is inflated by that radius.
        "Strand samples" allows a smaller radius without beading
        "Hug strands" pulls the shell onto the hair.
        Smoothing keeps the hugging from creating creases.
        """
        nodes = node_group.nodes
        links = node_group.links
        group_in = HairCardService._group_input_node(node_group)

        delete_selection = HairCardService._build_strand_selection(
            node_group, SELECTION_METHOD_RANDOM, basemesh,
            density_socket='Volume density', density_default=0.05)
        delete = nodes.new('GeometryNodeDeleteGeometry')
        delete.domain = 'CURVE'
        delete.location = (-800, 0)
        links.new(group_in.outputs['Geometry'], delete.inputs['Geometry'])
        links.new(delete_selection, delete.inputs['Selection'])

        HairCardService._add_input(node_group, 'Strand samples', 'NodeSocketInt', 32, (2, 128))
        resample = nodes.new('GeometryNodeResampleCurve')
        resample.location = (-600, 0)
        links.new(group_in.outputs['Strand samples'], resample.inputs['Count'])
        links.new(delete.outputs['Geometry'], resample.inputs['Curve'])

        HairCardService._add_input(node_group, 'Voxel size', 'NodeSocketFloat', 0.008, (0.001, 0.05))
        HairCardService._add_input(node_group, 'Strand radius', 'NodeSocketFloat', 0.015, (0.001, 0.05))
        to_volume = nodes.new('GeometryNodePointsToVolume')
        to_volume.location = (-360, 0)
        HairCardService._use_voxel_size(to_volume)
        links.new(resample.outputs['Curve'], to_volume.inputs['Points'])
        links.new(group_in.outputs['Voxel size'], to_volume.inputs['Voxel Size'])
        links.new(group_in.outputs['Strand radius'], to_volume.inputs['Radius'])

        HairCardService._add_input(node_group, 'Adaptivity', 'NodeSocketFloat', 0.3, (0.0, 1.0))
        to_mesh = nodes.new('GeometryNodeVolumeToMesh')
        to_mesh.location = (-160, 0)
        HairCardService._use_voxel_size(to_mesh)
        links.new(to_volume.outputs['Volume'], to_mesh.inputs['Volume'])
        links.new(group_in.outputs['Voxel size'], to_mesh.inputs['Voxel Size'])
        links.new(group_in.outputs['Adaptivity'], to_mesh.inputs['Adaptivity'])

        hugged = HairCardService._build_shell_hug(node_group, to_mesh.outputs['Mesh'], resample.outputs['Curve'], (300, -420))

        HairCardService._add_input(node_group, 'Smooth iterations', 'NodeSocketInt', 2, (0, 5))
        index_switch = nodes.new('GeometryNodeIndexSwitch')
        index_switch.data_type = 'GEOMETRY'
        index_switch.location = (600, 0)
        links.new(group_in.outputs['Smooth iterations'], index_switch.inputs['Index'])

        stage_geometry = hugged
        links.new(stage_geometry, index_switch.inputs[1])  # stage 0 = no smoothing
        for iteration in range(1, 6):
            if len(index_switch.index_switch_items) < iteration + 1:
                index_switch.index_switch_items.new()
            blur = nodes.new('GeometryNodeBlurAttribute')
            blur.data_type = 'FLOAT_VECTOR'
            blur.location = (60 + iteration * 80, 200 + iteration * 40)
            position = nodes.new('GeometryNodeInputPosition')
            position.location = (blur.location[0] - 140, blur.location[1])
            links.new(position.outputs['Position'], blur.inputs[0])
            blur.inputs[1].default_value = 1  # Iterations (single blur pass per stage, chained)
            set_pos = nodes.new('GeometryNodeSetPosition')
            set_pos.location = (blur.location[0] + 140, blur.location[1])
            links.new(stage_geometry, set_pos.inputs['Geometry'])
            links.new(blur.outputs[0], set_pos.inputs['Position'])
            stage_geometry = set_pos.outputs['Geometry']
            links.new(stage_geometry, index_switch.inputs[iteration + 1])

        return index_switch.outputs['Output']

    @staticmethod
    def build_shell_node_group(group_name: str, basemesh: bpy.types.Object | None = None) -> bpy.types.NodeTree:
        node_group = HairCardService._new_group(group_name)
        nodes = node_group.nodes
        links = node_group.links
        group_out = next(n for n in nodes if n.bl_idname == 'NodeGroupOutput')
        group_out.location = (1400, 0)

        shell_geometry = HairCardService._build_shell_base(node_group, basemesh)
        links.new(shell_geometry, group_out.inputs['Geometry'])
        return node_group

    @staticmethod
    def _kmeans_roots(roots: "np.ndarray", cluster_count: int, seed: int, iterations: int = 12, restarts: int | None = None) -> tuple["np.ndarray", int]:
        """K-means over strand root positions, seeded for reproducibility.

        Starts from k-means++ centres (each next centre is picked with a probability growing with its squared distance
        from the centres picked so far) and keeps the best of a few runs.
        """
        import numpy as np

        rng = np.random.RandomState(seed)
        cluster_count = min(cluster_count, len(roots))
        if restarts is None:
            restarts = 3 if len(roots) * cluster_count <= _KMEANS_RESTART_BUDGET else 1

        def assign(centers):
            """Nearest centre per root and the distance to it, in chunks to keep the distance matrix small."""
            out = np.empty(len(roots), dtype=np.int64)
            nearest = np.empty(len(roots), dtype=np.float64)
            for start in range(0, len(roots), 4096):
                block = roots[start:start + 4096]
                distances = np.linalg.norm(block[:, None, :] - centers[None, :, :], axis=2)
                out[start:start + 4096] = np.argmin(distances, axis=1)
                nearest[start:start + 4096] = distances.min(axis=1)
            return out, nearest

        def starting_centers():
            centers = np.empty((cluster_count, roots.shape[1]), dtype=np.float64)
            centers[0] = roots[rng.randint(0, len(roots))]
            closest = np.linalg.norm(roots - centers[0], axis=1) ** 2
            for index in range(1, cluster_count):
                total = closest.sum()
                # Every root already on centre (duplicate roots)
                pick = rng.randint(0, len(roots)) if total <= 0.0 else rng.choice(len(roots), p=closest / total)
                centers[index] = roots[pick]
                closest = np.minimum(closest, np.linalg.norm(roots - centers[index], axis=1) ** 2)
            return centers

        best = None
        for _run in range(max(1, restarts)):
            centers = starting_centers()
            for _ in range(iterations):
                assignments, _nearest = assign(centers)
                for cluster_index in range(cluster_count):
                    members = roots[assignments == cluster_index]
                    if len(members) > 0:
                        centers[cluster_index] = members.mean(axis=0)
                    else:
                        # Re-seed empty clusters from a random strand
                        centers[cluster_index] = roots[rng.randint(0, len(roots))]
            assignments, nearest = assign(centers)
            spread = float((nearest ** 2).sum())
            if best is None or spread < best[0]:
                best = (spread, assignments)
        return best[1], cluster_count

    @staticmethod
    def _evaluated_curves(hair_obj: bpy.types.Object, depsgraph: bpy.types.Depsgraph | None = None) -> bpy.types.Curves:
        """The hair curves as the viewport shows them (with the grooming stack applied).

        Falls back to the raw data if the evaluated object carries no curves.
        """
        if depsgraph is None:
            depsgraph = bpy.context.evaluated_depsgraph_get()
        try:
            evaluated = hair_obj.evaluated_get(depsgraph)
        except Exception:
            return hair_obj.data
        data = getattr(evaluated, "data", None)
        if isinstance(data, bpy.types.Curves) and len(data.curves) > 0:
            return data
        return hair_obj.data

    @staticmethod
    def _read_clustered_strands(hair_obj: bpy.types.Object, cluster_count: int, min_strands: int, seed: int, depsgraph: bpy.types.Depsgraph | None) -> dict[str, Any] | None:
        """Reads the evaluated groom into numpy and groups strands into clusters by their roots.

        Returns None if there is not enough hair to form a single cluster, otherwise a dict with the flat point positions,
        per-curve point ranges, roots, tips, the cluster assignment and the cluster count.
        """
        import numpy as np

        curves = HairCardService._evaluated_curves(hair_obj, depsgraph)
        curve_count = len(curves.curves)
        if curve_count == 0 or curve_count < min_strands:
            return None

        flat_positions = np.empty(len(curves.points) * 3, dtype=np.float64)
        curves.points.foreach_get('position', flat_positions)
        positions = flat_positions.reshape(-1, 3)

        first_index = np.empty(curve_count, dtype=np.int64)
        point_count = np.empty(curve_count, dtype=np.int64)
        curves.curves.foreach_get('first_point_index', first_index)
        curves.curves.foreach_get('points_length', point_count)

        roots = positions[first_index]
        tips = positions[first_index + point_count - 1]
        assignments, actual_cluster_count = HairCardService._kmeans_roots(roots, cluster_count, seed)

        return {
            "positions": positions,
            "first_index": first_index,
            "point_count": point_count,
            "roots": roots,
            "tips": tips,
            "assignments": assignments,
            "cluster_count": actual_cluster_count,
            }

    @staticmethod
    def _bundle_members(clustered: dict[str, Any], cluster_index: int, min_strands: int) -> "np.ndarray | None":
        """Indices of the strands in one cluster strided down to a sane number if they are too many, None if too few."""
        import numpy as np

        members = np.nonzero(clustered["assignments"] == cluster_index)[0]
        if len(members) < min_strands:
            return None
        if len(members) > _MAX_MEMBERS_PER_BUNDLE:
            stride = len(members) // _MAX_MEMBERS_PER_BUNDLE
            members = members[::stride][:_MAX_MEMBERS_PER_BUNDLE]
        return members

    @staticmethod
    def _bundle_mean_curve(clustered: dict[str, Any], members: "np.ndarray", target: "np.ndarray") -> "np.ndarray | None":
        """The members' strands resampled by arc length onto the ``target`` parameters (0..1) and averaged. None if no strand has length."""
        import numpy as np

        positions = clustered["positions"]
        first_index = clustered["first_index"]
        point_count = clustered["point_count"]
        accumulator = np.zeros((len(target), 3), dtype=np.float64)
        used = 0
        for member in members:
            start = first_index[member]
            count = point_count[member]
            if count < 2:
                continue
            strand = positions[start:start + count]
            # Resample by arc length, so points bunched up at the root do not drag the average towards the scalp
            steps = np.linalg.norm(np.diff(strand, axis=0), axis=1)
            travelled = np.concatenate(([0.0], np.cumsum(steps)))
            if travelled[-1] <= 0.0:
                continue
            parameter = travelled / travelled[-1]
            for axis in range(3):
                accumulator[:, axis] += np.interp(target, parameter, strand[:, axis])
            used += 1
        return accumulator / used if used else None

    @staticmethod
    def build_cluster_ribbon_mesh(hair_obj: bpy.types.Object, cluster_count: int, min_strands: int, seed: int, samples: int, depsgraph: bpy.types.Depsgraph | None = None) -> bpy.types.Mesh | None:
        """Build one averaged poly-line per cluster of nearby strands as a base for ribbon card.

        Member strands are resampled onto a common 0..1 parameter before being averaged.
        Each cluster also records how far its strands spread out at root, so the node group can use it for card width.

        Returns bpy.types.Mesh (mesh of edge chains), or None if no cluster qualified.
        """
        import numpy as np

        clustered = HairCardService._read_clustered_strands(hair_obj, cluster_count, min_strands, seed, depsgraph)
        if clustered is None:
            return None

        roots = clustered["roots"]

        samples = max(2, int(samples))
        target = np.linspace(0.0, 1.0, samples)

        averaged = []
        half_widths = []
        for cluster_index in range(clustered["cluster_count"]):
            members = HairCardService._bundle_members(clustered, cluster_index, min_strands)
            if members is None:
                continue

            mean_curve = HairCardService._bundle_mean_curve(clustered, members, target)
            if mean_curve is None:
                continue
            averaged.append(mean_curve)

            member_roots = roots[members]
            spread = member_roots - member_roots.mean(axis=0)
            half_widths.append(float(np.sqrt((spread ** 2).sum(axis=1).mean())))

        if not averaged:
            return None

        vertices = np.concatenate(averaged, axis=0)
        edges = []
        for bundle in range(len(averaged)):
            base = bundle * samples
            edges.extend((base + step, base + step + 1) for step in range(samples - 1))

        mesh = bpy.data.meshes.new(f"{hair_obj.name}_cluster_ribbons")
        mesh.from_pydata([tuple(v) for v in vertices], edges, [])
        mesh.update()

        # Stored per point because Mesh to Curve keeps point attributes
        width_attribute = mesh.attributes.new(CLUSTER_WIDTH_ATTRIBUTE, 'FLOAT', 'POINT')
        width_attribute.data.foreach_set(
            'value', np.repeat(np.array(half_widths, dtype=np.float32), samples))

        return mesh

    @staticmethod
    def build_cluster_box_mesh(hair_obj: bpy.types.Object, cluster_count: int, min_strands: int, seed: int, depsgraph: bpy.types.Depsgraph | None = None) -> bpy.types.Mesh | None:
        """Build one oriented quad per cluster of nearby strands.

        Strand roots are grouped with k-means
        PCA over the member points gives the card axes: the longest is the length (following root-tip direction), the next is the width and the flattest is the face normal.
        The result is a static mesh, that only changes on "Regenerate".

        Returns a bpy.types.Mesh, or None if there were not enough strands to form a single cluster.
        """
        import numpy as np

        clustered = HairCardService._read_clustered_strands(hair_obj, cluster_count, min_strands, seed, depsgraph)
        if clustered is None:
            return None

        positions = clustered["positions"]
        first_index = clustered["first_index"]
        point_count = clustered["point_count"]
        roots = clustered["roots"]
        tips = clustered["tips"]
        actual_cluster_count = clustered["cluster_count"]

        verts = []
        faces = []
        uvs = []

        for cluster_index in range(actual_cluster_count):
            member_curve_indices = HairCardService._bundle_members(clustered, cluster_index, min_strands)
            if member_curve_indices is None:
                continue

            member_point_ranges = [
                (first_index[i], first_index[i] + point_count[i]) for i in member_curve_indices
                ]
            member_points = np.concatenate([positions[start:end] for start, end in member_point_ranges], axis=0)
            if len(member_points) < 3:
                continue

            centroid = member_points.mean(axis=0)
            centered = member_points - centroid
            covariance = (centered.T @ centered) / len(centered)
            eigvals, eigvecs = np.linalg.eigh(covariance)
            # eigh() returns ascending eigenvalues - the last column is the length axis, the first the flattest one (card normal)
            length_axis = eigvecs[:, 2]
            width_axis = eigvecs[:, 1]
            normal_axis = eigvecs[:, 0]

            flow = (tips[member_curve_indices] - roots[member_curve_indices]).mean(axis=0)
            if np.dot(length_axis, flow) < 0:
                length_axis = -length_axis

            length_proj = centered @ length_axis
            width_proj = centered @ width_axis
            length_center = (length_proj.max() + length_proj.min()) / 2.0
            width_center = (width_proj.max() + width_proj.min()) / 2.0
            half_length = max((length_proj.max() - length_proj.min()) / 2.0, 1e-5)
            half_width = max((width_proj.max() - width_proj.min()) / 2.0, 1e-5)

            card_center = centroid + length_center * length_axis + width_center * width_axis

            # Wind the corners so that the face normal matches normal_axis
            winding_normal = np.cross(length_axis, width_axis)
            corner_order = ((-1, -1), (1, -1), (1, 1), (-1, 1))
            if np.dot(winding_normal, normal_axis) < 0:
                corner_order = tuple(reversed(corner_order))

            base_index = len(verts)
            for length_sign, width_sign in corner_order:
                corner = card_center + length_sign * half_length * length_axis + width_sign * half_width * width_axis
                verts.append(tuple(corner))
                # V along the cluster length, U across its width
                uvs.append(((width_sign + 1) / 2.0, (length_sign + 1) / 2.0))
            faces.append((base_index, base_index + 1, base_index + 2, base_index + 3))

        if not faces:
            return None

        mesh = bpy.data.meshes.new(f"{hair_obj.name}_cluster_boxes")
        mesh.from_pydata(verts, [], faces)
        mesh.update()

        uv_layer = mesh.uv_layers.new(name="UVMap")
        for loop in mesh.loops:
            uv_layer.data[loop.index].uv = uvs[loop.vertex_index]

        return mesh

    @staticmethod
    def clump_ring_sides(ring_count: int) -> list[int]:
        """Side count of each ring of a clump tube, from CLUMP_ROOT_SIDES at the root down to CLUMP_TIP_SIDES at the last ring."""
        ring_count = max(2, int(ring_count))
        span = CLUMP_ROOT_SIDES - CLUMP_TIP_SIDES
        return [int(math.floor(CLUMP_ROOT_SIDES - span * ring / (ring_count - 1) + 0.5)) for ring in range(ring_count)]

    @staticmethod
    def clump_ring_fractions(side_count: int) -> list[float]:
        """Where the vertices of a clump ring sit, as fractions of a full turn from the wide axis.

        Every ring has a vertex at both ends of its wide axis (0 and 0.5), whatever its side count, so the face-on width
        of the tube does not jump where the side count drops. The other vertices are spread evenly over the two halves,
        the odd one going to the first half.
        """
        side_count = max(3, int(side_count))
        extra = side_count - 2
        first_half = (extra + 1) // 2
        second_half = extra - first_half
        fractions = [0.0]
        fractions.extend(0.5 * (k + 1) / (first_half + 1) for k in range(first_half))
        fractions.append(0.5)
        fractions.extend(0.5 + 0.5 * (k + 1) / (second_half + 1) for k in range(second_half))
        return fractions

    @staticmethod
    def clump_ring_shape(side_count: int, next_count: int, morph: float) -> list[tuple[float, float, float]]:
        """The vertices of one clump ring as (turn fraction, wide, flat), on a unit 2:1 ellipse (wide 1, flat 0.5).

        At ``morph`` 0 the ring is the ``side_count`` polygon of ``clump_ring_fractions`` on the ellipse. As ``morph``
        goes to 1 it turns into the ``next_count`` polygon: the vertices that stay slide along the ellipse to that
        polygon's corners and the ones that go move onto its edges. A run of rings with one side count is morphed
        towards the next count over its length, so the tube's outline does not jump where the side count drops.
        """
        source = HairCardService.clump_ring_fractions(side_count)
        if next_count >= side_count or morph <= 0.0:
            return [(f, math.cos(2.0 * math.pi * f), 0.5 * math.sin(2.0 * math.pi * f)) for f in source]
        target = HairCardService.clump_ring_fractions(next_count) + [1.0]
        morph = min(1.0, morph)

        def on_ellipse(f):
            return math.cos(2.0 * math.pi * f), 0.5 * math.sin(2.0 * math.pi * f)

        # Both layouts have corners at 0 and 0.5; match the inner corners of each half, then spread the rest
        # evenly along the target edge between the matched corners on either side
        def halves(fractions):
            first = [i for i, f in enumerate(fractions) if 0.0 < f < 0.5]
            second = [i for i, f in enumerate(fractions) if 0.5 < f < 1.0]
            return first, second

        source_halves = halves(source)
        target_halves = halves(target[:-1])
        anchors = {0: 0, source.index(0.5): target.index(0.5), len(source): len(target) - 1}
        for source_inner, target_inner in zip(source_halves, target_halves):
            p, q = len(source_inner), len(target_inner)
            for j in range(q):
                anchors[source_inner[int(math.floor((j + 1) * (p + 1) / (q + 1) + 0.5)) - 1]] = target_inner[j]
        corners = sorted(anchors)

        ring = []
        for k, f in enumerate(source):
            if k in anchors:
                fraction = f + (target[anchors[k]] - f) * morph
                ring.append((fraction, *on_ellipse(fraction)))
                continue
            below = max(c for c in corners if c < k)
            above = min(c for c in corners if c > k)
            weight = (k - below) / (above - below)
            low, high = target[anchors[below]], target[anchors[above]]
            end_fraction = low + (high - low) * weight
            (lx, ly), (hx, hy) = on_ellipse(low), on_ellipse(high)
            end_x, end_y = lx + (hx - lx) * weight, ly + (hy - ly) * weight
            fraction = f + (end_fraction - f) * morph
            x, y = on_ellipse(fraction)
            ring.append((fraction, x + (end_x - x) * morph, y + (end_y - y) * morph))
        return ring

    @staticmethod
    def clump_triangle_count(ring_count: int) -> int:
        """Triangles in one clump tube: the root cap fan, the strips between rings and the tip fan to the apex."""
        sides = HairCardService.clump_ring_sides(ring_count)
        return (sides[0] - 2) + sum(lower + upper for lower, upper in zip(sides, sides[1:])) + sides[-1]

    @staticmethod
    def _merge_nearest_clusters(clustered: dict[str, Any], max_clusters: int) -> None:
        """Merge the two clusters with the nearest root centroids until at most ``max_clusters`` remain.

        Rewrites ``clustered["assignments"]``. Merged-away labels are left without members. With groom-side clumps
        (``read_groom_clumps``), only clumps whose mean lie directions are within ``_GUIDE_MAX_ANGLE`` and that hold no
        two sides of a parting pair merge while any such pair is left, so a parting stays open unless the budget allows
        nothing else.
        """
        import numpy as np

        assignments = clustered["assignments"].copy()
        roots = clustered["roots"]
        labels = [int(label) for label in np.unique(assignments)]
        if len(labels) <= max_clusters:
            return
        centroids = np.array([roots[assignments == label].mean(axis=0) for label in labels])
        sizes = np.array([np.count_nonzero(assignments == label) for label in labels], dtype=np.float64)
        lies = conflict = None
        if "strand_guides" in clustered:
            strand_lie = clustered["guide_lie"][clustered["strand_guides"][np.arange(len(assignments)), np.argmax(clustered["strand_weights"], axis=1)]]
            lies = np.array([strand_lie[assignments == label].sum(axis=0) for label in labels])
            # Clumps holding the two sides of a parting pair
            position = {label: index for index, label in enumerate(labels)}
            conflict = np.zeros((len(labels), len(labels)), dtype=bool)
            label_position = np.full(int(assignments.max()) + 1, -1, dtype=np.int64)
            label_position[list(position)] = list(position.values())
            pairs = np.asarray(clustered["guide_partings"], dtype=np.int64).reshape(-1, 2)
            guide_clumps = np.asarray(clustered["guide_clumps"], dtype=np.int64)
            pair_clumps = guide_clumps[pairs]
            pair_clumps[pair_clumps > len(label_position) - 1] = -1
            pair_positions = np.where(pair_clumps >= 0, label_position[np.maximum(pair_clumps, 0)], -1)
            pair_positions = pair_positions[(pair_positions >= 0).all(axis=1)]
            conflict[pair_positions[:, 0], pair_positions[:, 1]] = True
            conflict[pair_positions[:, 1], pair_positions[:, 0]] = True

        while len(labels) > max_clusters:
            distances = ((centroids[:, None, :] - centroids[None, :, :]) ** 2).sum(axis=2)
            np.fill_diagonal(distances, np.inf)
            if lies is not None:
                units = lies / np.maximum(np.linalg.norm(lies, axis=1), 1e-12)[:, None]
                same_flow = distances.copy()
                same_flow[(units @ units.T < math.cos(_GUIDE_MAX_ANGLE)) | conflict] = np.inf
                if np.isfinite(same_flow).any():
                    distances = same_flow
            keep, gone = sorted(np.unravel_index(np.argmin(distances), distances.shape))
            total = sizes[keep] + sizes[gone]
            centroids[keep] = (centroids[keep] * sizes[keep] + centroids[gone] * sizes[gone]) / total
            sizes[keep] = total
            if lies is not None:
                lies[keep] += lies[gone]
                lies = np.delete(lies, gone, axis=0)
                conflict[keep] |= conflict[gone]
                conflict[:, keep] |= conflict[:, gone]
                conflict = np.delete(np.delete(conflict, gone, axis=0), gone, axis=1)
            assignments[assignments == labels[gone]] = labels[keep]
            del labels[gone]
            centroids = np.delete(centroids, gone, axis=0)
            sizes = np.delete(sizes, gone)

        clustered["assignments"] = assignments

    @staticmethod
    def _nearest(points: "np.ndarray", references: "np.ndarray", count: int) -> tuple["np.ndarray", "np.ndarray"]:
        """Indices of and distances to the ``count`` nearest references of each point, nearest first, in chunks."""
        import numpy as np

        count = min(count, len(references))
        indices = np.empty((len(points), count), dtype=np.int64)
        distances = np.empty((len(points), count), dtype=np.float64)
        for start in range(0, len(points), 2048):
            block = points[start:start + 2048]
            squared = ((block[:, None, :] - references[None, :, :]) ** 2).sum(axis=2)
            if count < len(references):
                part = np.argpartition(squared, count - 1, axis=1)[:, :count]
            else:
                part = np.broadcast_to(np.arange(count), (len(block), count)).copy()
            part_distances = np.take_along_axis(squared, part, axis=1)
            order = np.argsort(part_distances, axis=1)
            indices[start:start + 2048] = np.take_along_axis(part, order, axis=1)
            distances[start:start + 2048] = np.sqrt(np.take_along_axis(part_distances, order, axis=1))
        return indices, distances

    @staticmethod
    def _resample_curves(positions: "np.ndarray", first_index: "np.ndarray", point_count: "np.ndarray", samples: int) -> "np.ndarray":
        """Every curve resampled by arc length onto ``samples`` evenly spaced points, as (curves, samples, 3).

        A curve with one point or no length repeats its first point.
        """
        import numpy as np

        target = np.linspace(0.0, 1.0, samples)
        out = np.empty((len(first_index), samples, 3), dtype=np.float64)
        for index, (start, count) in enumerate(zip(first_index, point_count)):
            strand = positions[start:start + count]
            travelled = np.concatenate(([0.0], np.cumsum(np.linalg.norm(np.diff(strand, axis=0), axis=1))))
            if count < 2 or travelled[-1] <= 0.0:
                out[index] = strand[0]
                continue
            parameter = travelled / travelled[-1]
            for axis in range(3):
                out[index, :, axis] = np.interp(target, parameter, strand[:, axis])
        return out

    @staticmethod
    def _read_curves(curves: bpy.types.Curves) -> tuple["np.ndarray", "np.ndarray", "np.ndarray"]:
        """Flat point positions (points, 3), first point index and point count per curve."""
        import numpy as np

        flat_positions = np.empty(len(curves.points) * 3, dtype=np.float64)
        curves.points.foreach_get('position', flat_positions)
        first_index = np.empty(len(curves.curves), dtype=np.int64)
        point_count = np.empty(len(curves.curves), dtype=np.int64)
        curves.curves.foreach_get('first_point_index', first_index)
        curves.curves.foreach_get('points_length', point_count)
        return flat_positions.reshape(-1, 3), first_index, point_count

    @staticmethod
    def read_guides(hair_obj: bpy.types.Object, samples: int = _GUIDE_SAMPLES) -> "np.ndarray | None":
        """The groom's guides: the hair as attached to the body (Surface Deform, i.e. node groups with a Deform Curves
        on Surface node) but without its other node modifiers (which grow the children, cut them and add curl, frizz
        and noise), each resampled by arc length to ``samples`` points.

        Those node modifiers are switched off for one evaluation and switched back on. Returns (guides, samples, 3) in
        hair local space, or None if there is no such modifier (the strands are their own guides) or no guide curves.
        """
        def attaches(modifier):
            group = modifier.node_group
            return group is not None and any(node.bl_idname == 'GeometryNodeDeformCurvesOnSurface' for node in group.nodes)

        node_modifiers = [modifier for modifier in hair_obj.modifiers
                          if modifier.type == 'NODES' and modifier.show_viewport and not attaches(modifier)]
        if not node_modifiers:
            return None
        for modifier in node_modifiers:
            modifier.show_viewport = False
        try:
            bpy.context.view_layer.update()
            curves = HairCardService._evaluated_curves(hair_obj, bpy.context.evaluated_depsgraph_get())
            if len(curves.curves) == 0:
                return None
            positions, first_index, point_count = HairCardService._read_curves(curves)
        finally:
            for modifier in node_modifiers:
                modifier.show_viewport = True
            bpy.context.view_layer.update()
        return HairCardService._resample_curves(positions, first_index, point_count, samples)

    @staticmethod
    def guide_lie_directions(guides: "np.ndarray") -> "np.ndarray":
        """Unit direction from each guide's root to its middle point (to its tip if the middle sits on the root)."""
        import numpy as np

        lie = guides[:, guides.shape[1] // 2] - guides[:, 0]
        short = np.linalg.norm(lie, axis=1) < 1e-9
        lie[short] = guides[short, -1] - guides[short, 0]
        return lie / np.maximum(np.linalg.norm(lie, axis=1), 1e-12)[:, None]

    @staticmethod
    def guide_neighbours(guides: "np.ndarray", count: int = _GUIDE_NEIGHBOURS) -> dict[str, "np.ndarray"]:
        """Each guide's ``count`` nearest guides by root, and which of them share its flow.

        Returns {"nearest": (G, k) indices, "same_flow": (G, k) bools (lie directions within ``_GUIDE_MAX_ANGLE``: a
        wider angle is a parting), "break": (G, k) weights (1 within the inner break distance, 0 past the outer, smooth
        between), "spacing": the median distance from a guide to its nearest guide, "lie": (G, 3) lie directions}.
        """
        import numpy as np

        roots = guides[:, 0]
        lie = HairCardService.guide_lie_directions(guides)
        nearest, distances = HairCardService._nearest(roots, roots, int(count) + 1)
        # Drop each guide itself (first, at distance 0, unless roots coincide: then drop whichever is itself)
        own = nearest == np.arange(len(roots))[:, None]
        own[~own.any(axis=1), -1] = True
        keep = ~own
        nearest = nearest[keep].reshape(len(roots), -1)
        distances = distances[keep].reshape(len(roots), -1)
        positive = distances[:, 0][distances[:, 0] > 0.0] if nearest.shape[1] else np.zeros(0)
        spacing = float(np.median(positive)) if len(positive) else 0.0
        same_flow = (lie[:, None, :] * lie[nearest]).sum(axis=2) >= math.cos(_GUIDE_MAX_ANGLE)
        return {"nearest": nearest, "same_flow": same_flow, "break": HairCardService._break_weight(distances, spacing),
                "spacing": spacing, "lie": lie}

    @staticmethod
    def _break_weight(distances: "np.ndarray", spacing: float) -> "np.ndarray":
        """1 up to the inner break distance, 0 past the outer, smoothstep between (both in guide spacings)."""
        import numpy as np

        if spacing <= 0.0:
            return np.ones_like(distances)
        inner, outer = (spacing * factor for factor in _GUIDE_BREAK_DISTANCE)
        fade = np.clip((outer - distances) / (outer - inner), 0.0, 1.0)
        return fade * fade * (3.0 - 2.0 * fade)

    @staticmethod
    def smooth_guide_flow(guides: "np.ndarray", neighbours: dict[str, "np.ndarray"], passes: int) -> "np.ndarray":
        """Average each guide's segment directions with its neighbours' that share its flow, ``passes`` times.

        Each pass is half its own direction, half the mean of its ``neighbours`` (``guide_neighbours``) that share its
        flow, so a guide across a parting does not pull. Roots and segment lengths are kept; the guide is rebuilt from
        the root. Returns new guides.
        """
        import numpy as np

        if passes < 1 or len(guides) < 2:
            return guides.copy()
        nearest = neighbours["nearest"]
        weights = neighbours["same_flow"].astype(np.float64)
        total = weights.sum(axis=1)
        segments = np.diff(guides, axis=1)
        lengths = np.linalg.norm(segments, axis=2)
        directions = segments / np.maximum(lengths, 1e-12)[:, :, None]
        for _pass in range(int(passes)):
            pulled = (directions[nearest] * weights[:, :, None, None]).sum(axis=1) / np.maximum(total, 1e-12)[:, None, None]
            mixed = np.where((total > 0.0)[:, None, None], 0.5 * directions + 0.5 * pulled, directions)
            norms = np.linalg.norm(mixed, axis=2)
            # A segment whose neighbours point straight back keeps its own direction
            directions = np.where((norms > 1e-6)[:, :, None], mixed / np.maximum(norms, 1e-12)[:, :, None], directions)
        roots = guides[:, 0]
        steps = np.cumsum(directions * lengths[:, :, None], axis=1)
        return np.concatenate((roots[:, None, :], roots[:, None, :] + steps), axis=1)

    @staticmethod
    def guide_clumps(guides: "np.ndarray", neighbours: dict[str, "np.ndarray"], cluster_count: int, seed: int) -> "np.ndarray":
        """A clump ID per guide: k-means over the guide roots, then each cluster split where a parting runs through it.

        Within a cluster, guides are joined to their nearest neighbours that share their flow, most alike first, and
        two groups are never joined if a guide in one and a near guide in the other differ in flow (a parting pair), so
        a chain of small turns cannot carry a group across a parting either. Every group is its own clump. IDs run
        0..n-1.
        """
        import numpy as np

        labels, _count = HairCardService._kmeans_roots(guides[:, 0], cluster_count, seed)
        parent = np.arange(len(guides))

        def find(index):
            while parent[index] != index:
                parent[index] = parent[parent[index]]
                index = parent[index]
            return index

        nearest = neighbours["nearest"]
        lie = neighbours["lie"]
        # Each group root -> the roots of the groups it holds a parting pair with, kept current on every union
        conflicts: dict[int, set[int]] = {}
        for a, b in HairCardService.guide_parting_pairs(neighbours):
            if a != b:
                conflicts.setdefault(a, set()).add(b)
                conflicts.setdefault(b, set()).add(a)
        joined = neighbours["same_flow"] & (labels[nearest] == labels[:, None])
        guide_index, column = np.nonzero(joined)
        alike = (lie[guide_index] * lie[nearest[guide_index, column]]).sum(axis=1)
        for order in np.argsort(-alike, kind="stable"):
            first, second = find(guide_index[order]), find(nearest[guide_index[order], column[order]])
            if first == second or second in conflicts.get(first, ()):
                continue
            keep, gone = min(first, second), max(first, second)
            parent[gone] = keep
            moved = conflicts.pop(gone, None)
            if moved:
                for other in moved:
                    other_set = conflicts[other]
                    other_set.discard(gone)
                    other_set.add(keep)
                conflicts.setdefault(keep, set()).update(moved)
        components = np.array([find(index) for index in range(len(guides))])
        return np.unique(components, return_inverse=True)[1].astype(np.int64)

    @staticmethod
    def guide_parting_pairs(neighbours: dict[str, "np.ndarray"]) -> list[tuple[int, int]]:
        """Pairs of near guides (``guide_neighbours``) whose lie directions differ by more than ``_GUIDE_MAX_ANGLE``."""
        import numpy as np

        guide_index, column = np.nonzero(~neighbours["same_flow"])
        return [(int(a), int(neighbours["nearest"][a, c])) for a, c in zip(guide_index, column)]

    @staticmethod
    def strand_guide_weights(roots: "np.ndarray", guides: "np.ndarray", neighbours: dict[str, "np.ndarray"]) -> tuple["np.ndarray", "np.ndarray"]:
        """Each strand's three guides and its weights on them, from the strand's root.

        Barycentric weights in the triangle of the three nearest guide roots (the root projected onto its plane,
        negative weights clamped), restricted to guides sharing the nearest guide's flow (no blending across a parting)
        and faded by the break distance between the nearest guide and the others. Weights sum to 1; a strand outside
        every usable triangle follows its nearest guide alone. Returns ((N, 3) guide indices, (N, 3) weights).
        """
        import numpy as np

        guide_roots = guides[:, 0]
        indices, _distances = HairCardService._nearest(roots, guide_roots, 3)
        if indices.shape[1] < 3:
            weights = np.zeros(indices.shape)
            weights[:, 0] = 1.0
            return indices, weights
        a, b, c = (guide_roots[indices[:, column]] for column in range(3))
        v0, v1, v2 = b - a, c - a, roots - a
        d00, d01, d11 = (v0 * v0).sum(1), (v0 * v1).sum(1), (v1 * v1).sum(1)
        d20, d21 = (v2 * v0).sum(1), (v2 * v1).sum(1)
        denominator = d00 * d11 - d01 * d01
        usable = np.abs(denominator) > 1e-18
        safe = np.where(usable, denominator, 1.0)
        on_b = (d11 * d20 - d01 * d21) / safe
        on_c = (d00 * d21 - d01 * d20) / safe
        weights = np.clip(np.stack((1.0 - on_b - on_c, on_b, on_c), axis=1), 0.0, None)
        weights[~usable] = 0.0

        lie = neighbours["lie"]
        same_flow = (lie[indices] * lie[indices[:, :1]]).sum(axis=2) >= math.cos(_GUIDE_MAX_ANGLE)
        spread = np.linalg.norm(guide_roots[indices] - guide_roots[indices[:, :1]], axis=2)
        weights *= same_flow * HairCardService._break_weight(spread, neighbours["spacing"])
        total = weights.sum(axis=1)
        alone = total <= 1e-12
        weights[alone] = (1.0, 0.0, 0.0)
        total[alone] = 1.0
        return indices, weights / total[:, None]

    @staticmethod
    def _carry_flow(positions: "np.ndarray", first_index: "np.ndarray", point_count: "np.ndarray", guides: "np.ndarray",
                    flowed: "np.ndarray", strand_guides: "np.ndarray", strand_weights: "np.ndarray") -> "np.ndarray":
        """The strands turned the way the flow pass turned their guides.

        Each strand segment is turned by the rotation that took each of its guides' segment at the same distance from the
        root (the guide's last segment past its end) to that segment's flowed direction, blended by the strand's guide
        weights. A strand keeps its root and segment lengths, so a child shorter or curlier than its guides keeps its
        own length and curl. Returns new flat positions.
        """
        import numpy as np

        curve_of_point = np.repeat(np.arange(len(first_index)), point_count)
        segments = np.zeros_like(positions)
        segments[1:] = np.diff(positions, axis=0)
        segments[first_index] = 0.0
        lengths = np.linalg.norm(segments, axis=1)
        travelled = np.cumsum(lengths)
        travelled -= travelled[first_index][curve_of_point]
        midway = travelled - 0.5 * lengths

        guide_segments = np.diff(guides, axis=1)
        guide_step = np.linalg.norm(guide_segments, axis=2).sum(axis=1) / (guides.shape[1] - 1)
        before = guide_segments / np.maximum(np.linalg.norm(guide_segments, axis=2), 1e-12)[:, :, None]
        after = np.diff(flowed, axis=1)
        after /= np.maximum(np.linalg.norm(after, axis=2), 1e-12)[:, :, None]
        # Rotation taking ``before`` to ``after``: v c + u x v + u (u.v) / (1 + c), with u = before x after, c = before.after
        axis = np.cross(before, after)
        cosine = (before * after).sum(axis=2)
        opposite = cosine <= -1.0 + 1e-6
        axis[opposite] = 0.0
        cosine[opposite] = 1.0

        turned = np.zeros_like(segments)
        for column in range(strand_guides.shape[1]):
            guide = strand_guides[curve_of_point, column]
            segment = np.clip((midway / np.maximum(guide_step[guide], 1e-12)).astype(np.int64), 0, guides.shape[1] - 2)
            u = axis[guide, segment]
            c = cosine[guide, segment][:, None]
            rotated = segments * c + np.cross(u, segments) + u * (u * segments).sum(axis=1)[:, None] / (1.0 + c)
            turned += strand_weights[curve_of_point, column][:, None] * rotated
        norms = np.linalg.norm(turned, axis=1)
        turned = np.where((norms > 1e-12)[:, None], turned * (lengths / np.maximum(norms, 1e-12))[:, None], segments)
        turned[first_index] = positions[first_index]
        rebuilt = np.cumsum(turned, axis=0)
        # Restart the running sum at every root
        offsets = rebuilt[first_index] - positions[first_index]
        return rebuilt - offsets[curve_of_point]

    @staticmethod
    def read_groom_clumps(hair_obj: bpy.types.Object, cluster_count: int, min_strands: int, seed: int,
                          depsgraph: bpy.types.Depsgraph | None, flow_passes: int = 0) -> dict[str, Any] | None:
        """The evaluated strands with a clump ID each, assigned on the groom side, and the guides' flow carried onto them.

        Guides (``read_guides``; the strands themselves when the hair has no node modifiers) get ``flow_passes`` of
        ``smooth_guide_flow`` over their nearest guides, about one clump's worth (guides / ``cluster_count``, at least
        ``_GUIDE_NEIGHBOURS``), and a clump ID each (``guide_clumps``). Every strand takes its weights on three guides
        (``strand_guide_weights``), its clump ID from the guide it weighs most and the weighted change the flow pass
        made to those guides (``_carry_flow``). Returns the dict of ``_read_clustered_strands`` with "assignments" the
        per-strand clump ID (strand positions already flowed), plus "guides" (flowed), "guide_lie", "guide_clumps",
        "guide_partings" (``guide_parting_pairs``), "strand_guides" and "strand_weights"; None if there are fewer than
        ``min_strands`` strands.
        """
        import numpy as np

        curves = HairCardService._evaluated_curves(hair_obj, depsgraph)
        curve_count = len(curves.curves)
        if curve_count == 0 or curve_count < min_strands:
            return None
        positions, first_index, point_count = HairCardService._read_curves(curves)
        roots = positions[first_index]

        guides = HairCardService.read_guides(hair_obj)
        if guides is None:
            guides = HairCardService._resample_curves(positions, first_index, point_count, _GUIDE_SAMPLES)
        neighbours = HairCardService.guide_neighbours(guides)
        flowed = guides
        if flow_passes > 0:
            # Each pass reaches about one clump's worth of guides, whatever the guide density
            reach = max(_GUIDE_NEIGHBOURS, int(round(len(guides) / max(1, cluster_count))))
            flow_neighbours = neighbours if reach == _GUIDE_NEIGHBOURS else HairCardService.guide_neighbours(guides, reach)
            flowed = HairCardService.smooth_guide_flow(guides, flow_neighbours, int(flow_passes))
        guide_clump = HairCardService.guide_clumps(guides, neighbours, cluster_count, seed)
        strand_guides, strand_weights = HairCardService.strand_guide_weights(roots, guides, neighbours)
        rows = np.arange(len(roots))
        assignments = guide_clump[strand_guides[rows, np.argmax(strand_weights, axis=1)]]

        if flow_passes > 0:
            positions = HairCardService._carry_flow(positions, first_index, point_count, guides, flowed, strand_guides, strand_weights)

        return {
            "positions": positions,
            "first_index": first_index,
            "point_count": point_count,
            "roots": roots,
            "tips": positions[first_index + point_count - 1],
            "assignments": assignments,
            "cluster_count": int(assignments.max()) + 1,
            "guides": flowed,
            "guide_lie": neighbours["lie"],
            "guide_clumps": guide_clump,
            "guide_partings": HairCardService.guide_parting_pairs(neighbours),
            "strand_guides": strand_guides,
            "strand_weights": strand_weights,
            }

    @staticmethod
    def _lay_clumps_on_scalp(clumps: list, surface_obj: bpy.types.Object, hair_obj: bpy.types.Object, roots: "np.ndarray", target: "np.ndarray",
                             ring_radius: list[float], flatten: float, cap_offset: float, hug: float,
                             depsgraph: bpy.types.Depsgraph | None) -> "tuple[np.ndarray, list[tuple[int, ...]]] | None":
        """Keep the clump curves on and outside the scalp, and cut the hair cap.

        For each clump (entries [curve, minor axis, root radius, scalp normal], all in hair local space) the root goes
        to ``cap_offset`` above the skin (half sunk into the cap) and the curve is rebuilt from it segment by segment,
        each keeping its length. Over the first stretch (``hug``, a fraction of the curve's parameter, with a smooth
        falloff) each segment is turned into the scalp's tangent plane (one standing straight out falls downwards) and
        its end lowered to one half-thickness above the cap; past it the segments keep their direction. No point ends
        up under that floor: it is pushed out along the surface normal. The scalp normal at the root is stored in
        the entry. Returns the cap (``_cut_hair_cap``) around the strand ``roots``, or None without a cap.
        """
        import numpy as np
        from mathutils.bvhtree import BVHTree

        to_surface = surface_obj.matrix_world.inverted() @ hair_obj.matrix_world
        to_hair = to_surface.inverted()
        to_hair_rotation = to_hair.to_3x3()
        thickness = max(0.01, float(flatten))
        cap_offset = max(0.0, float(cap_offset))
        hug = max(0.0, float(hug))

        with HairCardService._evaluated_surface(surface_obj, depsgraph) as mesh:
            allowed = HairCardService._body_face_indices(surface_obj, mesh)
            polygons = [tuple(polygon.vertices) for polygon in mesh.polygons
                        if allowed is None or polygon.index in allowed]
            tree = BVHTree.FromPolygons([vertex.co for vertex in mesh.vertices], polygons, all_triangles=False, epsilon=0.0)

            down = Vector((0.0, 0.0, -1.0))
            for clump in clumps:
                curve, _minor, root_radius, _normal = clump
                original = [to_surface @ Vector(tuple(point)) for point in curve]
                location, root_normal, _face, _distance = tree.find_nearest(original[0])
                if location is None:
                    continue
                laid = [location + root_normal * cap_offset]
                for index in range(1, len(original)):
                    segment = original[index] - original[index - 1]
                    floor = cap_offset + root_radius * ring_radius[index] * thickness
                    parameter = float(target[index])
                    weight = 0.0
                    if hug > 0.0 and parameter < hug:
                        x = parameter / hug
                        weight = 1.0 - x * x * (3.0 - 2.0 * x)
                    if weight > 0.0:
                        # Turn the segment into the scalp's tangent plane (same length); one standing straight out
                        # falls the way gravity takes it along the scalp
                        _location, normal, _face, _distance = tree.find_nearest(laid[-1])
                        along = segment - normal * segment.dot(normal)
                        if along.length < 0.2 * segment.length:
                            along = along + (down - normal * down.dot(normal)) * segment.length
                        if along.length > 1e-12:
                            segment = segment.lerp(along.normalized() * segment.length, weight)
                    position = laid[-1] + segment
                    location, normal, _face, _distance = tree.find_nearest(position)
                    if location is not None:
                        height = (position - location).dot(normal)
                        wanted = max(height + (floor - height) * weight, floor)
                        position = position + normal * (wanted - height)
                    laid.append(position)
                clump[0] = np.array([tuple(to_hair @ point) for point in laid])
                clump[3] = np.array((to_hair_rotation @ root_normal).normalized())

            if cap_offset <= 0.0:
                return None
            cap_faces = HairCardService._fur_bearing_faces_in(mesh, surface_obj, hair_obj, 1, depsgraph)
            if not cap_faces:
                return None
            return HairCardService._cut_hair_cap(mesh, cap_faces, tree, roots, to_surface, cap_offset)

    @staticmethod
    def _cut_hair_cap(mesh: bpy.types.Mesh, cap_faces: set[int], tree: Any, roots: "np.ndarray", to_surface: Any,
                      cap_offset: float) -> "tuple[np.ndarray, list[tuple[int, ...]], np.ndarray] | None":
        """The hair cap: ``cap_faces`` of the body ``mesh`` cut ``_CLUMP_CAP_CUTS`` times, every face further than
        ``_CLUMP_CAP_REACH`` from the nearest strand root dropped, the border smoothed so the hairline is not a staircase
        of body faces, and every vertex put ``cap_offset`` above the body along its normal (``tree``: BVH of the body).

        Each vertex also gets its hairline value: 1 on the border, falling linearly to 0 at ``_CLUMP_HAIRLINE_WIDTH``
        from the nearest border vertex.

        Returns (vertices in hair local space, faces, hairline values) or None if nothing is left.
        """
        import bmesh
        import numpy as np
        from mathutils.kdtree import KDTree

        root_tree = KDTree(len(roots))
        for index, root in enumerate(roots):
            root_tree.insert(to_surface @ Vector(tuple(root)), index)
        root_tree.balance()

        bm = bmesh.new()
        try:
            new_verts = {}
            for face in sorted(cap_faces):
                corners = []
                for index in mesh.polygons[face].vertices:
                    if index not in new_verts:
                        new_verts[index] = bm.verts.new(mesh.vertices[index].co)
                    corners.append(new_verts[index])
                bm.faces.new(corners)
            bmesh.ops.subdivide_edges(bm, edges=list(bm.edges), cuts=_CLUMP_CAP_CUTS, use_grid_fill=True)
            for vert in bm.verts:
                location, _normal, _face, _distance = tree.find_nearest(vert.co)
                if location is not None:
                    vert.co = location
            far = [face for face in bm.faces if root_tree.find(face.calc_center_median())[2] > _CLUMP_CAP_REACH]
            bmesh.ops.delete(bm, geom=far, context='FACES')
            loose = [vert for vert in bm.verts if not vert.link_faces]
            bmesh.ops.delete(bm, geom=loose, context='VERTS')
            if not bm.faces:
                return None

            # Round off the staircase: each border vertex moves to the mean of its border neighbours, back on the body
            for _step in range(_CLUMP_CAP_BORDER_SMOOTHING):
                moved = {}
                for vert in bm.verts:
                    if not vert.is_boundary:
                        continue
                    neighbours = [edge.other_vert(vert).co for edge in vert.link_edges if edge.is_boundary]
                    if len(neighbours) == 2:
                        moved[vert] = (vert.co + neighbours[0] + neighbours[1]) / 3.0
                for vert, co in moved.items():
                    location, _normal, _face, _distance = tree.find_nearest(co)
                    vert.co = location if location is not None else co

            to_hair = to_surface.inverted()
            bm.verts.index_update()
            cap_verts = []
            for vert in bm.verts:
                location, normal, _face, _distance = tree.find_nearest(vert.co)
                lifted = vert.co + normal * cap_offset if location is not None else vert.co
                cap_verts.append(tuple(to_hair @ lifted))
            faces = [tuple(vert.index for vert in face.verts) for face in bm.faces]
            border = [vert.co.copy() for vert in bm.verts if vert.is_boundary]
            hairline = np.zeros(len(cap_verts))
            if border:
                border_tree = KDTree(len(border))
                for index, co in enumerate(border):
                    border_tree.insert(co, index)
                border_tree.balance()
                for vert in bm.verts:
                    distance = border_tree.find(vert.co)[2]
                    hairline[vert.index] = max(0.0, 1.0 - distance / _CLUMP_HAIRLINE_WIDTH)
        finally:
            bm.free()
        return np.array(cap_verts), faces, hairline

    @staticmethod
    def build_clump_mesh(hair_obj: bpy.types.Object, cluster_count: int, min_strands: int, seed: int, samples: int, max_tris: int,
                         depsgraph: bpy.types.Depsgraph | None = None, width: float = 1.0,
                         tip_radius: float = _CLUMP_TIP_RADIUS, flatten: float = CLUMP_FLATTEN,
                         flow_passes: int = 0, surface_obj: bpy.types.Object | None = None, cap_offset: float = 0.0,
                         hug: float = 0.0, strays: int = 0) -> bpy.types.Mesh | None:
        """Build one closed, tapered tube per clump of nearby strands.

        Each clump follows its members' averaged curve
        (``samples`` points: one ring per point, the last point is the closed tip). Rings go from 6 sides at the root
        to 3 at the last ring. Every ring has a vertex at both ends of its wide axis, and each run of rings morphs into the
        next side count over its length (``clump_ring_shape``), so the outline does not notch where the count drops.
        The cross-section is flattened 2:1 along the clump's PCA minor axis, and the frame is
        carried along the curve by parallel transport, so a curve that winds through space twists the tube with it.
        Clumps with the nearest roots are merged until the whole style is at most ``max_tris`` triangles.
        A clump's root radius is the spread of its members' roots times ``width``; it narrows linearly to
        ``tip_radius`` times that at the last ring.

        ``flatten`` is the cross-section's flat half-axis as a fraction of its wide one: 0.5 is the 2:1 tube, lower
        values give flat lens-section ribbons that tile where they overlap.
        Strands are grouped by their clump IDs from the groom side (``read_groom_clumps``): guides are clustered and
        split at partings, and each strand follows the guide it weighs most. ``flow_passes`` times, each guide's
        direction is averaged with its same-flow neighbours' before clumping (``smooth_guide_flow``), and the strands
        follow their guides, so short styles sweep one way instead of pointing every way while partings stay open.
        Merging for the budget joins clumps that share a flow first.
        With a ``surface_obj`` (the body), the flat axis starts along the scalp normal, so a ribbon lies broad face down,
        and every curve point is kept outside the scalp. ``hug`` (a fraction of the curve length) pulls the first stretch
        of each clump down onto the scalp, its root half sunk into the cap. A ``cap_offset`` above 0 adds a hair cap:
        the body faces the hair grows from (``_fur_bearing_faces_in``, one ring dilated), lifted that far off the skin, in
        the same mesh and material (V 0, the root colour), so no bare scalp shows between clumps. The cap is not counted
        against ``max_tris``. The cap's ``HAIRLINE_ATTRIBUTE`` (point float) rises from 0 inside to 1 on its border, for
        the shader's soft hairline; it is 0 on everything else.
        ``strays`` thin three-sided tubes follow single strands picked by ``seed``, drifting off them towards the tip, so
        a few fly-aways break the clumps' outline. Each stray moves with the nearest clump when the clumps are laid on the
        scalp. They are not counted against ``max_tris``.

        Returns bpy.types.Mesh, or None if no clump qualified or one clump alone does not fit in ``max_tris``.
        """
        import numpy as np

        ring_count = max(2, int(samples) - 1)
        while ring_count > 2 and HairCardService.clump_triangle_count(ring_count) > max_tris:
            ring_count -= 1
        tris_per_clump = HairCardService.clump_triangle_count(ring_count)
        if tris_per_clump > max_tris:
            return None

        clustered = HairCardService.read_groom_clumps(hair_obj, cluster_count, min_strands, seed, depsgraph, int(flow_passes))
        if clustered is None:
            return None
        HairCardService._merge_nearest_clusters(clustered, max(1, int(max_tris) // tris_per_clump))

        positions = clustered["positions"]
        first_index = clustered["first_index"]
        point_count = clustered["point_count"]
        roots = clustered["roots"]
        sides = HairCardService.clump_ring_sides(ring_count)
        # Each run of rings with one side count morphs towards the next count, reaching it at the run's last ring
        shapes = []
        for ring, count in enumerate(sides):
            run_start = ring
            while run_start > 0 and sides[run_start - 1] == count:
                run_start -= 1
            run_end = ring
            while run_end + 1 < ring_count and sides[run_end + 1] == count:
                run_end += 1
            next_count = sides[run_end + 1] if run_end + 1 < ring_count else count
            shapes.append(HairCardService.clump_ring_shape(count, next_count, (ring - run_start + 1) / (run_end - run_start + 1)))
        # Turn fractions per ring, with the seam (1.0) appended so side == sides[ring] is vertex 0 again
        fractions = [[vertex[0] for vertex in shape] + [1.0] for shape in shapes]
        target = np.linspace(0.0, 1.0, ring_count + 1)

        verts = []
        faces = []
        loop_uvs = []

        def add_face(corners):
            # corners are (vertex index, u, v)
            faces.append(tuple(corner[0] for corner in corners))
            loop_uvs.extend((corner[1], corner[2]) for corner in corners)

        # Every clump's averaged curve, root thickness and PCA minor axis first: the scalp lay needs all curves at once
        clumps = []
        for cluster_index in range(clustered["cluster_count"]):
            members = HairCardService._bundle_members(clustered, cluster_index, min_strands)
            if members is None:
                continue
            curve = HairCardService._bundle_mean_curve(clustered, members, target)
            if curve is None:
                continue
            member_points = np.concatenate([positions[first_index[i]:first_index[i] + point_count[i]] for i in members], axis=0)
            centered = member_points - member_points.mean(axis=0)
            _eigvals, eigvecs = np.linalg.eigh(centered.T @ centered)
            member_roots = roots[members]
            spread = member_roots - member_roots.mean(axis=0)
            root_radius = max(float(np.sqrt((spread ** 2).sum(axis=1).mean())) * width, _CLUMP_MIN_RADIUS)
            clumps.append([curve, eigvecs[:, 0], root_radius, None])
        unlaid = [clump[0].copy() for clump in clumps]

        ring_radius = [1.0 - (1.0 - tip_radius) * ring / (ring_count - 1) for ring in range(ring_count)] + [tip_radius]
        flat_scale = max(0.01, float(flatten)) / CLUMP_FLATTEN
        hairline = []
        if surface_obj is not None and clumps:
            cap = HairCardService._lay_clumps_on_scalp(clumps, surface_obj, hair_obj, roots, target, ring_radius,
                                                       flatten, cap_offset, hug, depsgraph)
            if cap is not None:
                cap_verts, cap_faces, cap_hairline = cap
                base = len(verts)
                verts.extend(tuple(co) for co in cap_verts)
                hairline.extend(float(value) for value in cap_hairline)
                for polygon in cap_faces:
                    add_face(tuple((base + index, 0.5, 0.0) for index in polygon))

        for curve, minor_axis, root_radius, scalp_normal in clumps:
            tangents = np.gradient(curve, axis=0)
            lengths = np.linalg.norm(tangents, axis=1)
            if lengths.min() <= 1e-9:
                continue
            tangents = tangents / lengths[:, None]

            # Broad face down on the scalp when it is known, else across the clump's flattest spread
            flat_source = scalp_normal if scalp_normal is not None else minor_axis
            flat_axis = flat_source - np.dot(flat_source, tangents[0]) * tangents[0]
            if np.linalg.norm(flat_axis) < 1e-6:
                # Minor axis along the strands: any direction across the root tangent will do
                helper = np.array((1.0, 0.0, 0.0)) if abs(tangents[0][0]) < 0.9 else np.array((0.0, 1.0, 0.0))
                flat_axis = np.cross(tangents[0], helper)
            flat_axis /= np.linalg.norm(flat_axis)

            ring_starts = []
            for ring in range(ring_count):
                tangent = tangents[ring]
                if ring > 0:
                    # Parallel transport of the previous frame: the twist comes from the curve's own torsion
                    flat_axis = flat_axis - np.dot(flat_axis, tangent) * tangent
                    flat_axis /= np.linalg.norm(flat_axis)
                # n x T, so the angle runs counter-clockwise about the tangent and the faces below point outwards
                wide_axis = np.cross(flat_axis, tangent)
                radius = root_radius * ring_radius[ring]
                ring_starts.append(len(verts))
                for _fraction, wide, flat in shapes[ring]:
                    point = curve[ring] + radius * wide * wide_axis + radius * flat * flat_scale * flat_axis
                    verts.append(tuple(point))
            apex = len(verts)
            verts.append(tuple(curve[-1]))

            def corner(ring, side):
                # side == sides[ring] is the seam: vertex 0 again, but with u = 1
                return (ring_starts[ring] + side % sides[ring], fractions[ring][side], target[ring])

            # Root cap, facing back along the strands
            for side in range(1, sides[0] - 1):
                add_face((corner(0, 0), corner(0, side + 1), corner(0, side)))

            # Strips between rings with different side counts: walk both rings by their angle
            for ring in range(ring_count - 1):
                lower_count, upper_count = sides[ring], sides[ring + 1]
                lower = upper = 0
                while lower < lower_count or upper < upper_count:
                    if upper == upper_count or (lower < lower_count and fractions[ring][lower + 1] <= fractions[ring + 1][upper + 1]):
                        add_face((corner(ring, lower), corner(ring, lower + 1), corner(ring + 1, upper)))
                        lower += 1
                    else:
                        add_face((corner(ring, lower), corner(ring + 1, upper + 1), corner(ring + 1, upper)))
                        upper += 1

            last = ring_count - 1
            for side in range(sides[last]):
                apex_u = 0.5 * (fractions[last][side] + fractions[last][side + 1])
                add_face((corner(last, side), corner(last, side + 1), (apex, apex_u, 1.0)))

        if strays > 0 and clumps:
            HairCardService._add_strays(clustered, clumps, unlaid, target, int(strays), seed, verts, add_face)

        if not faces:
            return None

        mesh = bpy.data.meshes.new(f"{hair_obj.name}_clumps")
        mesh.from_pydata(verts, [], faces)
        mesh.update()

        uv_layer = mesh.uv_layers.new(name=CARDS_UV_MAP)
        uv_layer.data.foreach_set('uv', np.array(loop_uvs, dtype=np.float32).ravel())
        mesh.polygons.foreach_set('use_smooth', np.ones(len(mesh.polygons), dtype=bool))
        values = np.zeros(len(verts), dtype=np.float32)
        values[:len(hairline)] = hairline
        mesh.attributes.new(HAIRLINE_ATTRIBUTE, 'FLOAT', 'POINT').data.foreach_set('value', values)
        mesh.update()

        return mesh

    @staticmethod
    def _add_strays(clustered: dict[str, Any], clumps: list, unlaid: list, target: "np.ndarray", count: int, seed: int,
                    verts: list, add_face: Any) -> None:
        """Append ``count`` stray strands to ``verts`` / ``add_face`` (see ``build_clump_mesh``).

        Each is a strand of ``clustered`` (picked by ``seed`` among those at least half as long as the longest)
        resampled to ``target``, shifted point by point as far as its nearest clump (by root, in ``unlaid``) moved
        when laid on the scalp, and drifted off sideways by up to ``_STRAY_DRIFT`` of its length at the tip. The tube has
        three sides of ``_STRAY_RADIUS`` at the root, narrowing to a point; UVs as on the clumps (V 0 at the root).
        """
        import numpy as np

        positions = clustered["positions"]
        first_index = clustered["first_index"]
        point_count = clustered["point_count"]
        lengths = np.array([np.linalg.norm(np.diff(positions[first:first + n], axis=0), axis=1).sum() if n > 1 else 0.0
                            for first, n in zip(first_index, point_count)])
        if lengths.size == 0 or lengths.max() <= 0.0:
            return
        candidates = np.nonzero(lengths >= 0.5 * lengths.max())[0]
        rng = np.random.default_rng(seed + 7919)
        picked = rng.choice(candidates, size=min(count, len(candidates)), replace=False)
        clump_roots = np.array([curve[0] for curve in unlaid])
        sides = 3
        for strand in picked:
            first, n = int(first_index[strand]), int(point_count[strand])
            points = positions[first:first + n]
            steps = np.linalg.norm(np.diff(points, axis=0), axis=1)
            along = np.concatenate(([0.0], np.cumsum(steps))) / max(steps.sum(), 1e-9)
            curve = np.stack([np.interp(target, along, points[:, axis]) for axis in range(3)], axis=1)
            nearest = int(np.argmin(np.linalg.norm(clump_roots - curve[0], axis=1)))
            curve = curve + (clumps[nearest][0] - unlaid[nearest])
            tangents = np.gradient(curve, axis=0)
            norms = np.linalg.norm(tangents, axis=1)
            if norms.min() <= 1e-9:
                continue
            tangents /= norms[:, None]
            helper = np.array((0.0, 0.0, 1.0)) if abs(tangents[0][2]) < 0.9 else np.array((1.0, 0.0, 0.0))
            side_axis = np.cross(tangents[0], helper)
            side_axis /= np.linalg.norm(side_axis)
            angle = rng.uniform(0.0, 2.0 * math.pi)
            drift_axis = math.cos(angle) * side_axis + math.sin(angle) * np.cross(tangents[0], side_axis)
            curve = curve + np.outer(target ** 2, drift_axis) * (_STRAY_DRIFT * lengths[strand])

            rings = len(curve) - 1
            ring_starts = []
            normal_axis = side_axis
            for ring in range(rings):
                tangent = tangents[ring]
                normal_axis = normal_axis - np.dot(normal_axis, tangent) * tangent
                normal_axis /= np.linalg.norm(normal_axis)
                binormal = np.cross(tangent, normal_axis)
                radius = _STRAY_RADIUS * (1.0 - target[ring])
                ring_starts.append(len(verts))
                for side in range(sides):
                    turn = 2.0 * math.pi * side / sides
                    verts.append(tuple(curve[ring] + radius * (math.cos(turn) * normal_axis + math.sin(turn) * binormal)))
            apex = len(verts)
            verts.append(tuple(curve[-1]))
            for ring in range(rings):
                for side in range(sides):
                    u0, u1 = side / sides, (side + 1) / sides
                    a, b = ring_starts[ring] + side, ring_starts[ring] + (side + 1) % sides
                    if ring + 1 < rings:
                        c, d = ring_starts[ring + 1] + (side + 1) % sides, ring_starts[ring + 1] + side
                        add_face(((a, u0, target[ring]), (b, u1, target[ring]), (c, u1, target[ring + 1]), (d, u0, target[ring + 1])))
                    else:
                        add_face(((a, u0, target[ring]), (b, u1, target[ring]), (apex, 0.5 * (u0 + u1), 1.0)))

    @staticmethod
    @contextmanager
    def _evaluated_surface(surface_obj: bpy.types.Object, depsgraph: bpy.types.Depsgraph | None = None) -> Iterator[bpy.types.Mesh]:
        """The body mesh as it appears on screen (hidden helpers, applied morphs etc.), for the duration of the block."""
        if depsgraph is None:
            depsgraph = bpy.context.evaluated_depsgraph_get()
        evaluated = surface_obj.evaluated_get(depsgraph)
        try:
            yield evaluated.to_mesh()
        finally:
            evaluated.to_mesh_clear()

    @staticmethod
    def _body_face_indices(surface_obj: bpy.types.Object, mesh: bpy.types.Mesh) -> set[int] | None:
        """The faces of ``mesh`` that are actual body surface (None if can't be determined)."""
        criteria = []
        for modifier in surface_obj.modifiers:
            if modifier.type != 'MASK' or not modifier.vertex_group:
                continue
            group = surface_obj.vertex_groups.get(modifier.vertex_group)
            if group is not None:
                criteria.append((group.index, modifier.invert_vertex_group))
        if not criteria:
            return None

        allowed = None
        for group_index, inverted in criteria:
            member = [any(group.group == group_index for group in vertex.groups)
                      for vertex in mesh.vertices]
            # Normal mask keeps face only if all its corners belong to the group, inverted drops it if any is
            kept = {polygon.index for polygon in mesh.polygons
                    if (not any(member[i] for i in polygon.vertices) if inverted
                        else all(member[i] for i in polygon.vertices))}
            allowed = kept if allowed is None else (allowed & kept)
        return allowed

    @staticmethod
    def _fur_bearing_faces_in(mesh: bpy.types.Mesh, surface_obj: bpy.types.Object, hair_obj: bpy.types.Object, face_dilation: int, depsgraph: bpy.types.Depsgraph | None = None) -> set[int]:
        """Which faces of an already opened evaluated body mesh the hair asset grows out of."""
        import numpy as np
        from mathutils.bvhtree import BVHTree

        curves = HairCardService._evaluated_curves(hair_obj, depsgraph)
        if len(curves.curves) == 0:
            return set()

        positions = np.empty(len(curves.points) * 3, dtype=np.float64)
        curves.points.foreach_get('position', positions)
        positions = positions.reshape(-1, 3)
        first_index = np.empty(len(curves.curves), dtype=np.int64)
        curves.curves.foreach_get('first_point_index', first_index)
        roots = positions[first_index]
        if len(roots) > _MAX_ROOT_SAMPLES:
            roots = roots[::len(roots) // _MAX_ROOT_SAMPLES]

        allowed = HairCardService._body_face_indices(surface_obj, mesh)

        # Roots and mesh are in different local spaces
        to_surface_local = surface_obj.matrix_world.inverted() @ hair_obj.matrix_world
        tree = BVHTree.FromPolygons([vertex.co for vertex in mesh.vertices],
                                    [tuple(polygon.vertices) for polygon in mesh.polygons],
                                    all_triangles=False, epsilon=0.0)
        faces = set()
        for root in roots:
            _location, _normal, index, _distance = tree.find_nearest(to_surface_local @ Vector(tuple(root)))
            if index is not None:
                faces.add(index)
        if allowed is not None:
            faces &= allowed

        for _ring in range(max(0, int(face_dilation))):
            faces = HairCardService._grow_face_set(mesh, faces)
            if allowed is not None:
                faces &= allowed
        return faces

    @staticmethod
    def _fur_bearing_faces(surface_obj: bpy.types.Object, hair_obj: bpy.types.Object, face_dilation: int, depsgraph: bpy.types.Depsgraph | None = None) -> set[int]:
        """Indices of the evaluated body faces the hair asset grows out of.

        Used only for counting and measuring as indices are only valid for the evaluated mesh.
        """
        with HairCardService._evaluated_surface(surface_obj, depsgraph) as mesh:
            return HairCardService._fur_bearing_faces_in(mesh, surface_obj, hair_obj, face_dilation, depsgraph)

    @staticmethod
    def _grow_face_set(mesh: bpy.types.Mesh, faces: set[int]) -> set[int]:
        """The given faces plus every face sharing a vertex with them."""
        wanted_vertices = set()
        for index in faces:
            wanted_vertices.update(mesh.polygons[index].vertices)
        grown = set(faces)
        for polygon in mesh.polygons:
            if polygon.index in grown:
                continue
            if wanted_vertices.intersection(polygon.vertices):
                grown.add(polygon.index)
        return grown

    @staticmethod
    def build_body_shell_mesh(surface_obj: bpy.types.Object, hair_obj: bpy.types.Object, face_dilation: int, depsgraph: bpy.types.Depsgraph | None = None) -> bpy.types.Mesh | None:
        """A mesh holding just the body faces the asset grows from, with its UVs renormalised.

        Cut out of the body as it currently appears (_evaluated_surface).
        Body UV layout is kept, but normalised uniformly onto patch bounding box, so patch uses whole texture.

        Returns a bpy.types.Mesh, or None if the asset does not appear to grow from this surface.
        """
        import bmesh

        with HairCardService._evaluated_surface(surface_obj, depsgraph) as surface_mesh:
            faces = HairCardService._fur_bearing_faces_in(surface_mesh, surface_obj, hair_obj, face_dilation, depsgraph)
            if not faces:
                return None

            mesh = None
            bm = bmesh.new()
            try:
                bm.from_mesh(surface_mesh)
                bm.faces.ensure_lookup_table()
                doomed = [face for face in bm.faces if face.index not in faces]
                if doomed:
                    bmesh.ops.delete(bm, geom=doomed, context='FACES')
                if not bm.faces:
                    return None

                # Shape key layers of evaluated mesh are dropped, shell follows the body through Surface Deform
                shape_layers = bm.verts.layers.shape
                for name in list(shape_layers.keys()):
                    shape_layers.remove(shape_layers[name])

                uv_layer = bm.loops.layers.uv[0] if bm.loops.layers.uv else None
                if uv_layer is not None:
                    coordinates = [loop[uv_layer].uv for face in bm.faces for loop in face.loops]
                    min_u = min(uv.x for uv in coordinates)
                    min_v = min(uv.y for uv in coordinates)
                    extent = max(max(uv.x for uv in coordinates) - min_u,
                                 max(uv.y for uv in coordinates) - min_v)
                    if extent > 1e-6:
                        for uv in coordinates:
                            uv.x = (uv.x - min_u) / extent
                            uv.y = (uv.y - min_v) / extent

                mesh = bpy.data.meshes.new(f"{hair_obj.name}_body_shell")
                bm.to_mesh(mesh)
            finally:
                bm.free()

        mesh.update()
        return mesh

    @staticmethod
    def hair_extent_above_surface(surface_obj: bpy.types.Object, hair_obj: bpy.types.Object, depsgraph: bpy.types.Depsgraph | None = None, samples: int = 4000) -> float:
        """How far out of the body the hair reaches, in metres, or 0.0 if it cannot be measured.

        Used to start the body shell bake rays far enough out to capture the whole length of the fur.
        Points sampled for speed.
        """
        import numpy as np
        from mathutils.bvhtree import BVHTree

        curves = HairCardService._evaluated_curves(hair_obj, depsgraph)
        if len(curves.curves) == 0:
            return 0.0

        positions = np.empty(len(curves.points) * 3, dtype=np.float64)
        curves.points.foreach_get('position', positions)
        positions = positions.reshape(-1, 3)
        if len(positions) > samples:
            positions = positions[::len(positions) // samples]

        with HairCardService._evaluated_surface(surface_obj, depsgraph) as mesh:
            tree = BVHTree.FromPolygons([vertex.co for vertex in mesh.vertices],
                                        [tuple(polygon.vertices) for polygon in mesh.polygons],
                                        all_triangles=False, epsilon=0.0)
            to_surface_local = surface_obj.matrix_world.inverted() @ hair_obj.matrix_world
            furthest = 0.0
            for position in positions:
                _location, _normal, index, distance = tree.find_nearest(
                    to_surface_local @ Vector(tuple(position)))
                if index is not None and distance is not None:
                    furthest = max(furthest, distance)
        return float(furthest)

    @staticmethod
    @contextmanager
    def body_held_at_rest_pose(rig: bpy.types.Object | None) -> Iterator[None]:
        """Hold the character in its rest pose for the duration of the block.

        ``surfacedeform_bind`` silently refuses to bind (``is_bound`` stays False) while the armature is posed,
        and a shell cut from a posed body would store the posed shape as its rest shape.

        A rig of None, or one already at rest, makes this a no-op.
        """
        if rig is None or rig.data.pose_position == 'REST':
            yield
            return
        previous = rig.data.pose_position
        rig.data.pose_position = 'REST'
        try:
            bpy.context.view_layer.update()
            yield
        finally:
            rig.data.pose_position = previous
            bpy.context.view_layer.update()

    @staticmethod
    def weight_body_shell_to_rig(shell_obj: bpy.types.Object, surface_obj: bpy.types.Object, rig: bpy.types.Object | None) -> bool:
        """Give shell the bone weights of the body, so that it exports as skinned geometry.

        The shell vertices are body vertices, so the body weights apply verbatim and are already in the mesh.
        Only the vertex group names are missing, they are recreated in the surface object order.

        Only works for a shell cut after the rig was added, MPFB loads the bone weights onto the body together with the rig.
        """
        from .rigservice import RigService

        if rig is None:
            return False

        existing = {group.name for group in shell_obj.vertex_groups}
        for group in surface_obj.vertex_groups:
            if group.name not in existing:
                shell_obj.vertex_groups.new(name=group.name)

        # Same call used in clothes path. move_to_top puts the armature ahead of the Surface Deform added next
        RigService.ensure_armature_modifier(shell_obj, rig)
        return True

    @staticmethod
    def body_shell_is_weighted_to(shell_obj: bpy.types.Object | None, rig: bpy.types.Object | None) -> bool:
        """Whether this shell would deform with the given rig on its own."""
        if shell_obj is None or rig is None:
            return False
        return any(modifier.type == 'ARMATURE' and modifier.object == rig
                   for modifier in shell_obj.modifiers)

    @staticmethod
    def bind_body_shell_to_body(context: bpy.types.Context, shell_obj: bpy.types.Object, surface_obj: bpy.types.Object) -> bool:
        """Tie the shell back to the body surface it was cut from. Returns whether succeeded.

        Surface Deform binds against the evaluated body, so the shell follows shape keys, targets and the armature.

        It has to be placed after armature modifier (armature only carries export weights).
        """
        from .objectservice import ObjectService

        follow = shell_obj.modifiers.new(name=BODY_SHELL_FOLLOW_MODIFIER_NAME, type='SURFACE_DEFORM')
        follow.target = surface_obj
        try:
            with context.temp_override(object=shell_obj, active_object=shell_obj,
                                       selected_objects=[shell_obj],
                                       selected_editable_objects=[shell_obj]):
                bpy.ops.object.surfacedeform_bind(modifier=follow.name)
        except Exception:
            ObjectService.deselect_and_deactivate_all()
            ObjectService.activate_blender_object(shell_obj)
            try:
                bpy.ops.object.surfacedeform_bind(modifier=follow.name)
            except Exception:
                pass
        if not follow.is_bound:
            # Unbound Surface Deform does nothing, so its removed. Shell stays static
            shell_obj.modifiers.remove(follow)
            return False
        return True

    @staticmethod
    def store_shell_edge_fade(mesh: bpy.types.Mesh, width_in_rings: int) -> bool:
        """Write a 0..1 weight per vertex: 0 on the patch border, 1 once ``width_in_rings`` faces in.

        The shell is a patch with a hard border, this lets the baked shader fade out on the rim of the shell.

        Returns True if fade weight was written. A closed patch (no border) or a width of zero leaves the mesh untouched.
        """
        import bmesh

        width = max(0, int(width_in_rings))
        if width == 0:
            return False

        bm = bmesh.new()
        try:
            bm.from_mesh(mesh)
            bm.verts.ensure_lookup_table()

            # A border edge has one face in the patch, its vertices are the outer rim
            frontier = {vertex.index for edge in bm.edges if len(edge.link_faces) == 1
                        for vertex in edge.verts}
            if not frontier or len(frontier) == len(bm.verts):
                return False

            # BFS over edges - distance in face rings
            distance = {index: 0 for index in frontier}
            current = frontier
            for ring in range(1, width + 1):
                nxt = set()
                for index in current:
                    for edge in bm.verts[index].link_edges:
                        other = edge.other_vert(bm.verts[index]).index
                        if other not in distance:
                            distance[other] = ring
                            nxt.add(other)
                if not nxt:
                    break
                current = nxt

            attribute = mesh.attributes.get(SHELL_EDGE_FADE_ATTRIBUTE)
            if attribute is None:
                attribute = mesh.attributes.new(SHELL_EDGE_FADE_ATTRIBUTE, 'FLOAT', 'POINT')
            for index in range(len(mesh.vertices)):
                # Vertices the search never reached are further in than the fade width (opaque), the rest ramps linearly to zero
                attribute.data[index].value = min(1.0, distance.get(index, width) / float(width))
            mesh.update()
            return True
        finally:
            bm.free()

    @staticmethod
    def build_body_shell_node_group(group_name: str) -> bpy.types.NodeTree:
        """Float the duplicated body faces off the skin, along a smoothed normal.

        Normals are blurred first, so the offset does not self-intersect on concave parts of the body (e.g. armpit, behind the ear).
        """
        node_group = HairCardService._new_group(group_name)
        nodes = node_group.nodes
        links = node_group.links
        group_in = HairCardService._group_input_node(node_group)
        group_out = next(n for n in nodes if n.bl_idname == 'NodeGroupOutput')
        group_in.location = (-800, 0)
        group_out.location = (400, 0)

        HairCardService._add_input(node_group, 'Height', 'NodeSocketFloat', 0.006, (0.0, 0.2))
        HairCardService._add_input(node_group, 'Normal smoothing', 'NodeSocketInt', 3, (0, 20))

        normal = nodes.new('GeometryNodeInputNormal')
        normal.location = (-600, -200)

        blur = nodes.new('GeometryNodeBlurAttribute')
        blur.data_type = 'FLOAT_VECTOR'
        blur.location = (-420, -200)
        links.new(normal.outputs['Normal'], blur.inputs[0])
        links.new(group_in.outputs['Normal smoothing'], blur.inputs[1])

        normalize = nodes.new('ShaderNodeVectorMath')
        normalize.operation = 'NORMALIZE'
        normalize.location = (-240, -200)
        links.new(blur.outputs[0], normalize.inputs[0])

        offset = nodes.new('ShaderNodeVectorMath')
        offset.operation = 'SCALE'
        offset.location = (-60, -200)
        links.new(normalize.outputs[0], offset.inputs[0])
        links.new(group_in.outputs['Height'], offset.inputs['Scale'])

        set_position = nodes.new('GeometryNodeSetPosition')
        set_position.location = (180, 0)
        links.new(group_in.outputs['Geometry'], set_position.inputs['Geometry'])
        links.new(offset.outputs[0], set_position.inputs['Offset'])

        links.new(set_position.outputs['Geometry'], group_out.inputs['Geometry'])
        return node_group
