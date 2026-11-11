"""This file provides UI for saving/loading eye material settings"""

import os, bpy, shutil
from .... import ClassManager
from ....services import LogService
from ....services import LocationService
from ....services import SceneConfigSet
from ....services import UiService
from ....services import ObjectService
from ...abstractpanel import Abstract_Panel

_LOG = LogService.get_logger("ui.eyesettings")

_LOC = os.path.dirname(__file__)
EYE_SETTINGS_PROPERTIES_DIR = os.path.join(_LOC, "properties")
EYE_SETTINGS_PROPERTIES = SceneConfigSet.from_definitions_in_json_directory(EYE_SETTINGS_PROPERTIES_DIR, prefix="EYE_")

# Group input keys that tell the two eye material key sets apart: procedural eyes, stylized eyes
EYE_SETTINGS_MARKER_KEYS = ("IrisMinorColor", "IrisInner")

# Presets shipped in data/settings and copied to the user config dir when missing there
SHIPPED_EYE_SETTINGS = ("default", "stylized")

def _populate_settings(self, context):
    _LOG.enter()
    _LOG.trace("Context is scene", isinstance(context, bpy.types.Scene))
    available_settings = UiService.get_eye_settings_panel_list()
    if available_settings is None:
        available_settings = []
    return available_settings

_SETTINGS_LIST_PROP = {
    "type": "enum",
    "name": "available_settings",
    "description": "Available settings",
    "label": "Available settings",
    "default": 0
}
EYE_SETTINGS_PROPERTIES.add_property(_SETTINGS_LIST_PROP, _populate_settings)

class MPFB_PT_Eye_Settings_Panel(Abstract_Panel):
    """Panel for saving/loading eye material settings."""

    bl_label = "Eye material save files"
    bl_category = UiService.get_value("MATERIALSCATEGORY")
    bl_options = {'DEFAULT_CLOSED'}
    bl_parent_id = "MPFB_PT_Presets_Panel"

    def _load_save_box(self, scene, layout):
        _LOG.enter()
        EYE_SETTINGS_PROPERTIES.draw_properties(scene, layout, ["available_settings"])
        layout.operator('mpfb.eyesettings_apply_settings')
        layout.operator('mpfb.overwrite_eye_settings')
        EYE_SETTINGS_PROPERTIES.draw_properties(scene, layout, ["name"])
        layout.operator('mpfb.save_new_eye_settings')

    def draw(self, context):
        _LOG.enter()

        ensure_eye_settings_default_exists()

        if UiService.get_eye_settings_panel_list() is None:
            UiService.rebuild_eye_settings_panel_list()

        layout = self.layout
        scene = context.scene

        self._load_save_box(scene, self._create_box(layout, "Load/save presets", "MODIFIER"))

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        if not obj:
            return False

        if ObjectService.object_is_basemesh_or_body_proxy(obj):
            return True

        if ObjectService.object_is_skeleton(obj):
            return True

        if ObjectService.object_is_eyes(obj):
            return True

        return False

def ensure_eye_settings_default_exists():
    """Check that the json file with the default eye settings exists in the user config dir.
    If not, copy it from the data directory."""
    _LOG.enter()
    rebuild = False
    for name in SHIPPED_EYE_SETTINGS:
        file_name = "eye_settings." + name + ".json"
        user_json = LocationService.get_user_config(file_name)
        if not os.path.exists(user_json):
            _LOG.warn("The " + name + " eye settings do not exist. Will create at", user_json)
            template_json = os.path.join(LocationService.get_mpfb_data("settings"), file_name)
            if os.path.exists(template_json):
                _LOG.warn("Copying from", template_json)
                shutil.copy(template_json, user_json)
                rebuild = name != "default"
        else:
            _LOG.trace("Eye settings exist", name)
    if rebuild:
        # A list built before the copy would not offer the new preset
        if UiService.get_eye_settings_panel_list() is not None:
            UiService.rebuild_eye_settings_panel_list()
        if UiService.get_importer_eye_settings_panel_list() is not None:
            UiService.rebuild_importer_eye_settings_panel_list()

ClassManager.add_class(MPFB_PT_Eye_Settings_Panel)
