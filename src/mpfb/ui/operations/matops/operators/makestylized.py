"""Operator for making an existing character stylized in one step."""

from .....services import LogService
from .....services import ObjectService
from .....services import HumanService
from ..... import ClassManager
from ....mpfboperator import MpfbOperator
from ....pollstrategy import pollstrategy, PollStrategy

_LOG = LogService.get_logger("matops.makestylized")


@pollstrategy(PollStrategy.ANY_MAKEHUMAN_OBJECT_ACTIVE)
class MPFB_OT_Make_Stylized_Operator(MpfbOperator):
    """Set stylization 1.0, the stylized skin and the stylized eyes together, and recolour teeth, tongue, brows and lashes"""
    bl_idname = "mpfb.make_stylized"
    bl_label = "Make stylized"
    bl_options = {'REGISTER', 'UNDO'}

    def get_logger(self):
        return _LOG

    def hardened_execute(self, context):
        basemesh = ObjectService.find_object_of_type_amongst_nearest_relatives(context.active_object)
        if basemesh is None:
            self.report({'ERROR'}, "Could not find the human's basemesh")
            return {'FINISHED'}

        HumanService.make_stylized(basemesh)

        self.report({'INFO'}, "The character is now stylized")
        return {'FINISHED'}


ClassManager.add_class(MPFB_OT_Make_Stylized_Operator)
