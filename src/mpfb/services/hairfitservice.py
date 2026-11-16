"""Fit groomed hair curves to the body they are put on.

Pack grooms are made on the default head. On another character the guides, once Surface Deform has carried their
roots onto this scalp, run through the scalp, neck and shoulders and some hang over the face; every child grown round
a guide copies its shape. Fixing the finished strands fails (pushed out they lie plastered on the skin, deleted they
leave bald patches), so the guides are fitted before the children are grown, and a light pass after the children
catches what the child spread puts back into the body.

The fit is a geometry nodes modifier, so it follows the body live: shape keys (macros), targets and the armature.
"""

import bpy

from .logservice import LogService
from .modifierservice import ModifierService

_LOG = LogService.get_logger("services.hairfitservice")

GUIDE_FIT_MODIFIER = "Fit Guides To Body"
STRAND_FIT_MODIFIER = "Fit Strands To Body"
FACE_MASK_ATTRIBUTE = "mpfb_hair_face"

# Guide fit: full distance off the skin after FADE metres of hair from the root, 0 at the root. The distance clears
# the child spread (Duplicate Hair Curves radius, 1 cm in the pack) so children round a guide on the neck stay outside.
GUIDE_OFFSET = 0.010
STRAND_OFFSET = 0.002
FADE_LENGTH = 0.05
# A guide with a point this close to the face (front of the face below the forehead) is dropped
FACE_DISTANCE = 0.03


class HairFitService():
    """Builds and attaches the fit-to-body modifiers of a hair curves object. All methods are static."""

    def __init__(self) -> None:
        raise RuntimeError("You should not instance HairFitService. Use its static methods instead.")

    @staticmethod
    def is_fit_modifier(modifier: bpy.types.Modifier) -> bool:
        """True for the guide fit, which belongs with the attachment (the guides as they lie on this body)."""
        return modifier.type == 'NODES' and modifier.name.startswith(GUIDE_FIT_MODIFIER)

    @staticmethod
    def write_face_mask(basemesh: bpy.types.Object) -> int:
        """Mark the face (front of the head from the chin to the lower forehead) in a point attribute on the basemesh.

        The mask is picked on the basis shape, i.e. by topology, so it stays the face whatever macros and targets do
        to the body later. Landmarks are the eye and mouth joint cubes, so no length in it is absolute.
        Returns the number of face vertices.
        """
        _LOG.enter()
        mesh = basemesh.data
        groups = {group.name: group.index for group in basemesh.vertex_groups}

        def centroid(name):
            index = groups.get(name)
            if index is None:
                return None
            points = [v.co for v in mesh.vertices if any(g.group == index and g.weight > 0.5 for g in v.groups)]
            if not points:
                return None
            return sum((p for p in points), points[0] * 0) / len(points)

        eye_l, eye_r, mouth = centroid("joint-l-eye"), centroid("joint-r-eye"), centroid("joint-mouth")
        values = [0.0] * len(mesh.vertices)
        if eye_l is None or eye_r is None or mouth is None:
            _LOG.warn("No eye or mouth joints on the basemesh, so no face is masked", basemesh.name)
        else:
            eyes = (eye_l + eye_r) / 2
            drop = eyes.z - mouth.z
            half_width = abs(eye_l.x - eye_r.x) / 2 * 2.3
            top, bottom = eyes.z + 0.55 * drop, mouth.z - 1.3 * drop
            head = {groups[name] for name in ("head", "jaw") if name in groups}
            for v in mesh.vertices:
                co = v.co
                if v.normal.y < -0.35 and abs(co.x - eyes.x) < half_width and bottom < co.z < top \
                        and co.y < eyes.y + drop and (not head or any(g.group in head for g in v.groups)):
                    values[v.index] = 1.0
        attribute = mesh.attributes.get(FACE_MASK_ATTRIBUTE)
        if attribute is None:
            attribute = mesh.attributes.new(FACE_MASK_ATTRIBUTE, "FLOAT", "POINT")
        attribute.data.foreach_set("value", values)
        count = int(sum(values))
        _LOG.debug("Face mask vertices", count)
        return count

    @staticmethod
    def fit_to_body(hair_obj: bpy.types.Object, basemesh: bpy.types.Object) -> None:
        """Add the guide fit after the modifiers that attach the curves to the body, and the strand fit at the end.

        Idempotent: existing fit modifiers on the object are reused and moved into place.
        """
        _LOG.enter()
        if hair_obj.type != "CURVES":
            return
        HairFitService.write_face_mask(basemesh)
        group = HairFitService._node_group(f"{hair_obj.name}_fit_to_body")

        def attaches(modifier):
            node_group = getattr(modifier, "node_group", None)
            return modifier.type == 'SURFACE_DEFORM' or (
                node_group is not None and any(n.bl_idname == 'GeometryNodeDeformCurvesOnSurface' for n in node_group.nodes))

        for name, offset, drop_face in ((GUIDE_FIT_MODIFIER, GUIDE_OFFSET, True), (STRAND_FIT_MODIFIER, STRAND_OFFSET, False)):
            modifier = hair_obj.modifiers.get(name) or hair_obj.modifiers.new(name, "NODES")
            modifier.node_group = group
            HairFitService._set_input(modifier, "Body", basemesh)
            HairFitService._set_input(modifier, "Offset", offset)
            HairFitService._set_input(modifier, "Fade Length", FADE_LENGTH)
            HairFitService._set_input(modifier, "Drop Face", drop_face)
            HairFitService._set_input(modifier, "Face Distance", FACE_DISTANCE)

        names = [m.name for m in hair_obj.modifiers]
        guide_index = 0
        for index, modifier in enumerate(hair_obj.modifiers):
            if attaches(modifier):
                guide_index = index + 1
        current = names.index(GUIDE_FIT_MODIFIER)
        hair_obj.modifiers.move(current, guide_index if guide_index <= current else guide_index - 1)
        names = [m.name for m in hair_obj.modifiers]
        hair_obj.modifiers.move(names.index(STRAND_FIT_MODIFIER), len(names) - 1)

    @staticmethod
    def _set_input(modifier, name, value):
        for item in modifier.node_group.interface.items_tree:
            if item.item_type == "SOCKET" and item.in_out == "INPUT" and item.name == name:
                ModifierService.set_node_group_input(modifier, item.identifier, value)
                return
        raise KeyError(name)

    @staticmethod
    def _node_group(name: str) -> bpy.types.NodeTree:
        """The fit node group: drop face guides, then walk each curve from the root, moving every point by its original
        segment from the moved point before it and pushing it out along the skin normal to the faded offset.

        Walking from the root keeps a curve that enters the body on the side it came from (a per-point push sends the
        part past the middle of the neck out of the far side, so locks cross under the chin), and carries the rest of
        the curve along with the push instead of folding it onto the skin.
        """
        group = bpy.data.node_groups.get(name)
        if group is not None:
            return group
        group = bpy.data.node_groups.new(name, "GeometryNodeTree")
        face = group.interface
        face.new_socket("Geometry", in_out="INPUT", socket_type="NodeSocketGeometry")
        face.new_socket("Body", in_out="INPUT", socket_type="NodeSocketObject")
        for socket_name, default in (("Offset", GUIDE_OFFSET), ("Fade Length", FADE_LENGTH), ("Face Distance", FACE_DISTANCE)):
            socket = face.new_socket(socket_name, in_out="INPUT", socket_type="NodeSocketFloat")
            socket.default_value = default
            socket.min_value = 0.0
            socket.subtype = "DISTANCE"
        face.new_socket("Drop Face", in_out="INPUT", socket_type="NodeSocketBool")
        face.new_socket("Geometry", in_out="OUTPUT", socket_type="NodeSocketGeometry")

        nodes, links = group.nodes, group.links

        def node(kind, **settings):
            n = nodes.new(kind)
            for key, value in settings.items():
                setattr(n, key, value)
            return n

        def link(a, b):
            links.new(a, b)

        def vector(op, a, b=None):
            n = node("ShaderNodeVectorMath", operation=op)
            link(a, n.inputs[0])
            if b is not None:
                link(b, n.inputs[1])
            return n.outputs["Value"] if op in ("DOT_PRODUCT", "LENGTH") else n.outputs["Vector"]

        def math(op, a, b):
            n = node("ShaderNodeMath", operation=op)
            for i, x in enumerate((a, b)):
                if isinstance(x, (int, float)):
                    n.inputs[i].default_value = x
                else:
                    link(x, n.inputs[i])
            return n.outputs[0]

        def compare(op, a, b, data_type="FLOAT"):
            n = node("FunctionNodeCompare", operation=op, data_type=data_type)
            offset = 0
            for i, x in enumerate((a, b)):
                if isinstance(x, (int, float)):
                    n.inputs[offset + i].default_value = x
                else:
                    link(x, n.inputs[offset + i])
            return n.outputs[0]

        def on_body(position):
            """Nearest body point and its normal for a position (both in the hair's space)."""
            proximity = node("GeometryNodeProximity", target_element="FACES")
            link(body, proximity.inputs["Geometry"])
            link(position, proximity.inputs["Sample Position"])
            normal = node("GeometryNodeSampleNearestSurface", data_type="FLOAT_VECTOR")
            link(body, normal.inputs["Mesh"])
            link(node("GeometryNodeInputNormal").outputs[0], normal.inputs["Value"])
            link(position, normal.inputs["Sample Position"])
            return proximity.outputs["Position"], proximity.outputs["Distance"], normal.outputs["Value"]

        inputs = node("NodeGroupInput")
        output = node("NodeGroupOutput")
        info = node("GeometryNodeObjectInfo", transform_space="RELATIVE")
        link(inputs.outputs["Body"], info.inputs["Object"])
        body = info.outputs["Geometry"]
        position = node("GeometryNodeInputPosition").outputs[0]

        # Face: a guide with any point near masked skin goes, whole
        near, distance, _normal = on_body(position)
        mask = node("GeometryNodeSampleNearestSurface", data_type="FLOAT")
        link(body, mask.inputs["Mesh"])
        attribute = node("GeometryNodeInputNamedAttribute", data_type="FLOAT")
        attribute.inputs["Name"].default_value = FACE_MASK_ATTRIBUTE
        link(attribute.outputs[0], mask.inputs["Value"])
        on_face = node("FunctionNodeBooleanMath", operation="AND")
        link(compare("LESS_THAN", distance, inputs.outputs["Face Distance"]), on_face.inputs[0])
        link(compare("GREATER_THAN", mask.outputs[0], 0.5), on_face.inputs[1])
        any_on_face = node("GeometryNodeFieldOnDomain", domain="CURVE", data_type="FLOAT")
        link(math("MULTIPLY", on_face.outputs[0], 1.0), any_on_face.inputs[0])
        drop = node("FunctionNodeBooleanMath", operation="AND")
        link(compare("GREATER_THAN", any_on_face.outputs[0], 0.0005), drop.inputs[0])
        link(inputs.outputs["Drop Face"], drop.inputs[1])
        delete = node("GeometryNodeDeleteGeometry", domain="CURVE")
        link(inputs.outputs["Geometry"], delete.inputs["Geometry"])
        link(drop.outputs[0], delete.inputs["Selection"])

        # Original shape and arc length from the root, kept for the walk
        store_shape = node("GeometryNodeStoreNamedAttribute", data_type="FLOAT_VECTOR", domain="POINT")
        store_shape.inputs["Name"].default_value = "mpfb_fit_original"
        link(delete.outputs[0], store_shape.inputs["Geometry"])
        link(position, store_shape.inputs["Value"])
        store_length = node("GeometryNodeStoreNamedAttribute", data_type="FLOAT", domain="POINT")
        store_length.inputs["Name"].default_value = "mpfb_fit_length"
        link(store_shape.outputs[0], store_length.inputs["Geometry"])
        link(node("GeometryNodeSplineParameter").outputs["Length"], store_length.inputs["Value"])

        count = node("GeometryNodeAttributeStatistic", domain="CURVE")
        link(store_length.outputs[0], count.inputs["Geometry"])
        link(node("GeometryNodeSplineLength").outputs["Point Count"], count.inputs["Attribute"])

        repeat_in = node("GeometryNodeRepeatInput")
        repeat_out = node("GeometryNodeRepeatOutput")
        repeat_in.pair_with_output(repeat_out)
        link(count.outputs["Max"], repeat_in.inputs["Iterations"])
        link(store_length.outputs[0], repeat_in.inputs["Geometry"])
        walking = repeat_in.outputs["Geometry"]

        # The point at index iteration + 1 of every curve moves this round; the root stays
        index = node("GeometryNodeInputIndex").outputs[0]
        previous = math("SUBTRACT", index, 1)
        selected = compare("EQUAL", node("GeometryNodeSplineParameter").outputs["Index"],
                           math("ADD", repeat_in.outputs["Iteration"], 1), "INT")
        original = node("GeometryNodeInputNamedAttribute", data_type="FLOAT_VECTOR")
        original.inputs["Name"].default_value = "mpfb_fit_original"

        def sample_previous(value):
            sample = node("GeometryNodeSampleIndex", data_type="FLOAT_VECTOR", domain="POINT")
            link(walking, sample.inputs["Geometry"])
            link(value, sample.inputs["Value"])
            link(previous, sample.inputs["Index"])
            return sample.outputs[0]

        segment = vector("SUBTRACT", original.outputs[0], sample_previous(original.outputs[0]))
        candidate = vector("ADD", sample_previous(position), segment)
        surface, _distance, normal = on_body(candidate)
        height = vector("DOT_PRODUCT", vector("SUBTRACT", candidate, surface), normal)
        length = node("GeometryNodeInputNamedAttribute", data_type="FLOAT")
        length.inputs["Name"].default_value = "mpfb_fit_length"
        fade = node("ShaderNodeMapRange", clamp=True)
        link(length.outputs[0], fade.inputs["Value"])
        link(inputs.outputs["Fade Length"], fade.inputs["From Max"])
        fade.inputs["To Min"].default_value = 0.0
        link(inputs.outputs["Offset"], fade.inputs["To Max"])
        push = math("MAXIMUM", math("SUBTRACT", fade.outputs["Result"], height), 0.0)
        scaled = node("ShaderNodeVectorMath", operation="SCALE")
        link(normal, scaled.inputs[0])
        link(push, scaled.inputs["Scale"])
        moved = node("GeometryNodeSetPosition")
        link(walking, moved.inputs["Geometry"])
        link(selected, moved.inputs["Selection"])
        link(vector("ADD", candidate, scaled.outputs["Vector"]), moved.inputs["Position"])
        link(moved.outputs[0], repeat_out.inputs["Geometry"])

        result = repeat_out.outputs["Geometry"]
        for attribute_name in ("mpfb_fit_original", "mpfb_fit_length"):
            clean = node("GeometryNodeRemoveAttribute")
            clean.inputs["Name"].default_value = attribute_name
            link(result, clean.inputs["Geometry"])
            result = clean.outputs[0]
        link(result, output.inputs["Geometry"])
        return group
