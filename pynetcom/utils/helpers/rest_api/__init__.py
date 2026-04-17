"""
REST API helpers for network management systems.

Provides data providers for Nokia NSP and Huawei NCE with filtering capabilities.
Models follow IETF RFC 8345/8346 and OpenConfig standards.
"""

from pynetcom.utils.helpers.rest_api.base import RestNMSDataFilter
from pynetcom.utils.helpers.rest_api.nokia_nsp import NspDataProvider
from pynetcom.utils.helpers.rest_api.huawei_nce import NceDataProvider
from pynetcom.utils.helpers.rest_api.data_containers import (
    BaseAlarm,
    BaseInterface,
    BaseLink,
    BaseNode,
    BaseTerminationPoint,
    NspAlarm,
    NspNode,
    NceAlarm,
    NceIgpLink,
    NceInterface,
    NceLink,
    NceNode,
    NceTerminationPoint,
)

__all__ = [
    'RestNMSDataFilter',
    'NspDataProvider',
    'NceDataProvider',
    'BaseAlarm',
    'BaseInterface',
    'BaseLink',
    'BaseNode',
    'BaseTerminationPoint',
    'NspAlarm',
    'NspNode',
    'NceAlarm',
    'NceIgpLink',
    'NceInterface',
    'NceLink',
    'NceNode',
    'NceTerminationPoint',
]
