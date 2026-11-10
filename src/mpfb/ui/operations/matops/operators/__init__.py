from .....services import LogService
_LOG = LogService.get_logger("matops.init")
_LOG.trace("initializing material operators")

from .setnormalmap import MPFB_OT_Set_Normalmap_Operator

__all__ = [
    "MPFB_OT_Set_Normalmap_Operator"
    ]
