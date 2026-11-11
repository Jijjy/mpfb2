import bpy
from .. import dynamic_import
from ._helpers import MockOperatorBase

MPFB_OT_Stylized_Studio_Operator = dynamic_import("mpfb.ui.operations.matops.operators.stylizedstudio", "MPFB_OT_Stylized_Studio_Operator")

def test_studio_adds_three_lights_and_world():
    names = ("StudioKey", "StudioFill", "StudioRim")
    for _ in range(2):  # second run must replace, not stack
        mockself = MockOperatorBase()
        assert MPFB_OT_Stylized_Studio_Operator.hardened_execute(mockself, bpy.context) == {'FINISHED'}
    try:
        for n in names:
            assert bpy.context.scene.objects[n].type == 'LIGHT'
        assert len([o for o in bpy.context.scene.objects if o.name.startswith("Studio")]) == 3
        assert bpy.context.scene.world.name.startswith("StudioGradientWorld")
    finally:
        for n in names:
            bpy.data.objects.remove(bpy.data.objects[n], do_unlink=True)
