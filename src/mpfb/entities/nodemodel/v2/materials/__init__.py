from .abstractmaterialwrapper import AbstractMaterialWrapper

from .nodewrappergameengine import NodeWrapperGameEngine
from .nodewrapperstylizedhair import NodeWrapperStylizedHair
from .nodewrapperstylizedeyes import NodeWrapperStylizedEyes
from .nodewrapperstylizedskin import NodeWrapperStylizedSkin

MATERIAL_WRAPPERS = dict()
MATERIAL_WRAPPERS["Skin"] = None

__all__ = [
    "AbstractMaterialWrapper",
    "MATERIAL_WRAPPERS",
    "NodeWrapperGameEngine",
    "NodeWrapperStylizedHair",
    "NodeWrapperStylizedEyes",
    "NodeWrapperStylizedSkin"
    ]
