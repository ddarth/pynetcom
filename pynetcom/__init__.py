# Import classes and functions

from pynetcom.rest_nce import RestNCE, NCEAuthenticationError
from pynetcom.rest_nsp import RestNSP
from pynetcom.netconf_client import NetconfClient
from pynetcom import utils

# REST API helpers
from pynetcom.utils.helpers.rest_api import (
    RestNMSDataFilter,
    NspDataProvider,
    NceDataProvider,
)

# from pynetcom.cli_client import EquipCLI, NokiaEquipCLI, HuaweiEquipCLI, cli_caret

# Library version
__version__ = "0.2.0"

# Description
__doc__ = """
pynetcom - Python library for interacting with network devices and management systems
via REST API and CLI, supporting multiple vendors like Huawei, Nokia, and more.

Data models follow IETF RFC 8345/8346 and OpenConfig standards:
- BaseNode (RFC 8345): network element
- BaseLink (RFC 8345): network link (source/dest terminology)
- BaseTerminationPoint (RFC 8345): port/interface
- BaseInterface (OpenConfig): L3 router interface with IPv4
- BaseAlarm: alarm data
"""

__all__ = [
    "RestNCE",
    "RestNSP",
    "NetconfClient",
    "utils",
    "RestNMSDataFilter",
    "NspDataProvider",
    "NceDataProvider",
    "NCEAuthenticationError",
]
