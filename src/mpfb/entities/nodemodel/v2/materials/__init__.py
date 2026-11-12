from .abstractmaterialwrapper import AbstractMaterialWrapper

from .nodewrapperskin import NodeWrapperSkin
from .nodewrappergameengine import NodeWrapperGameEngine
from .nodewrapperstylizedeyes import NodeWrapperStylizedEyes
from .nodewrapperstylizedskin import NodeWrapperStylizedSkin

MATERIAL_WRAPPERS = dict()
MATERIAL_WRAPPERS["Skin"] = None

__all__ = [
    "AbstractMaterialWrapper",
    "MATERIAL_WRAPPERS",
    "NodeWrapperSkin",
    "NodeWrapperGameEngine",
    "NodeWrapperStylizedEyes",
    "NodeWrapperStylizedSkin"
    ]
