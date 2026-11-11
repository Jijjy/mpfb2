from .....services import LogService
from ..... import ClassManager
from ....mpfboperator import MpfbOperator
from mathutils import Vector
import bpy

_LOG = LogService.get_logger("matops.operators.stylizedstudio")

# name, light type, location, energy (W), colour, size
_LIGHTS = [
    ("StudioKey", 'AREA', (2.5, -3.0, 3.0), 600.0, (1.0, 0.95, 0.88), 2.0),
    ("StudioFill", 'AREA', (-3.0, -2.5, 1.5), 150.0, (0.65, 0.78, 1.0), 3.0),
    ("StudioRim", 'AREA', (0.0, 3.5, 3.0), 900.0, (1.0, 1.0, 1.0), 1.0),
]

_TARGET = Vector((0.0, 0.0, 0.9))
_WORLD_NAME = "StudioGradientWorld"


def _build_gradient_world():
    """Vertical gradient, dark below to lighter above, lighting the scene softly."""
    world = bpy.data.worlds.get(_WORLD_NAME) or bpy.data.worlds.new(_WORLD_NAME)
    world.use_nodes = True
    tree = world.node_tree
    tree.nodes.clear()
    coord = tree.nodes.new("ShaderNodeTexCoord")
    sep = tree.nodes.new("ShaderNodeSeparateXYZ")
    remap = tree.nodes.new("ShaderNodeMath")
    ramp = tree.nodes.new("ShaderNodeValToRGB")
    bg = tree.nodes.new("ShaderNodeBackground")
    out = tree.nodes.new("ShaderNodeOutputWorld")
    # Generated coordinates of a world are the view direction; Z runs -1 .. 1, remapped to 0 .. 1
    remap.operation = 'MULTIPLY_ADD'
    remap.inputs[1].default_value = 0.5
    remap.inputs[2].default_value = 0.5
    ramp.color_ramp.elements[0].color = (0.04, 0.045, 0.06, 1.0)
    ramp.color_ramp.elements[1].color = (0.25, 0.30, 0.40, 1.0)
    links = tree.links
    links.new(coord.outputs["Generated"], sep.inputs["Vector"])
    links.new(sep.outputs["Z"], remap.inputs[0])
    links.new(remap.outputs["Value"], ramp.inputs["Fac"])
    links.new(ramp.outputs["Color"], bg.inputs["Color"])
    links.new(bg.outputs["Background"], out.inputs["Surface"])
    return world


class MPFB_OT_Stylized_Studio_Operator(MpfbOperator):
    """Add key, cool fill and rim lights and a gradient world, for look development"""
    bl_idname = "mpfb.stylized_studio"
    bl_label = "Stylized studio lighting"
    bl_options = {'REGISTER', 'UNDO'}

    def get_logger(self):
        return _LOG

    def hardened_execute(self, context):
        _LOG.enter()
        scene = context.scene
        for name, light_type, location, energy, color, size in _LIGHTS:
            # Re-running replaces the previous rig instead of stacking it
            old = bpy.data.objects.get(name)
            if old is not None:
                bpy.data.objects.remove(old, do_unlink=True)
            data = bpy.data.lights.get(name) or bpy.data.lights.new(name=name, type=light_type)
            data.type = light_type
            data.energy = energy
            data.color = color
            data.size = size
            obj = bpy.data.objects.new(name=name, object_data=data)
            scene.collection.objects.link(obj)
            obj.location = location
            obj.rotation_euler = (_TARGET - Vector(location)).to_track_quat('-Z', 'Y').to_euler()
        scene.world = _build_gradient_world()
        self.report({'INFO'}, "Stylized studio lighting added")
        return {'FINISHED'}


ClassManager.add_class(MPFB_OT_Stylized_Studio_Operator)
