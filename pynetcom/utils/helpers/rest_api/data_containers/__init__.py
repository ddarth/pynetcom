"""
Data containers for REST API responses.

Models follow IETF/OpenConfig standards:
- BaseNode (RFC 8345), BaseLink (RFC 8345), BaseTerminationPoint (RFC 8345)
- BaseInterface (OpenConfig), BaseAlarm
"""

from pynetcom.utils.helpers.rest_api.data_containers.base import (
    BaseAlarm,
    BaseInterface,
    BaseLink,
    BaseNode,
    BaseTerminationPoint,
)
from pynetcom.utils.helpers.rest_api.data_containers.nokia_nsp import (
    NspAlarm,
    NspInterface,
    NspNode,
)
from pynetcom.utils.helpers.rest_api.data_containers.huawei_nce import (
    NceAlarm,
    NceIgpLink,
    NceInterface,
    NceLink,
    NceNode,
    NceTerminationPoint,
)

__all__ = [
    'BaseAlarm',
    'BaseInterface',
    'BaseLink',
    'BaseNode',
    'BaseTerminationPoint',
    'NspAlarm',
    'NspInterface',
    'NspNode',
    'NceAlarm',
    'NceIgpLink',
    'NceInterface',
    'NceLink',
    'NceNode',
    'NceTerminationPoint',
]
