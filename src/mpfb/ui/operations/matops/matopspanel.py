import os, bpy
from .... import ClassManager
from ....services import LogService
from ....services import LocationService
from ....services import ObjectService
from ....services import UiService
from ....services import MaterialService
from ...abstractpanel import Abstract_Panel

_LOG = LogService.get_logger("matops.matopspanel")


class MPFB_PT_MatopsPanel(Abstract_Panel):
    bl_label = "Material"
    bl_category = UiService.get_value("OPERATIONSCATEGORY")
    bl_options = {'DEFAULT_CLOSED'}
    bl_parent_id = "MPFB_PT_Operations_Panel"

    def _adjust(self, scene, layout):
        box = self.create_box(layout, "Adjust material")
        box.operator("mpfb.set_normalmap")

    def draw(self, context):
        _LOG.enter()

        layout = self.layout
        scene = context.scene

        self.create_box(layout, "Look development").operator("mpfb.stylized_studio")

        if context.active_object is None:
            return

        objtype = ObjectService.get_object_type(context.active_object)

        if not objtype or objtype == "Skeleton":
            return

        # material = MaterialService.get_material(context.active_object)
        # _LOG.dump("Material", (material, MaterialService.identify_material(material)))

        self._adjust(scene, layout)

ClassManager.add_class(MPFB_PT_MatopsPanel)
