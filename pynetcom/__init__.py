# Import classes and functions

from pynetcom.rest_nce import RestNCE, NCEAuthenticationError
from pynetcom.rest_nsp import RestNSP
from pynetcom.netconf_client import NetconfClient
from pynetcom.services_client import ServicesClient
from pynetcom import utils

# REST API helpers
from pynetcom.utils.helpers.rest_api import (
    RestNMSDataFilter,
    NspDataProvider,
    NceDataProvider,
)

# Service-layer data containers (OpenConfig-aligned)
from pynetcom.utils.helpers.netconf.rpc_data_containers.services import (
    NetworkInstance,
    ConnectionPoint,
    Endpoint,
    LocalEndpoint,
    RemoteEndpoint,
    Fdb,
    MacTable,
    MacEntry,
    Neighbor,
    L3Interface,
    BgpRoute,
    NetworkInstanceType,
    EndpointType,
    MacEntryType,
    MacSourceType,
    NeighborOrigin,
)

# Diagnostic-actions data containers (ping / traceroute)
from pynetcom.utils.helpers.netconf.rpc_data_containers.ping import (
    PingRequest,
    PingProbe,
    PingResult,
)
from pynetcom.utils.helpers.netconf.rpc_data_containers.traceroute import (
    TracerouteRequest,
    TracerouteProbe,
    TracerouteHop,
    TracerouteResult,
)
from pynetcom.exceptions import NetconfActionNotAuthorized

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
    "ServicesClient",
    "utils",
    "RestNMSDataFilter",
    "NspDataProvider",
    "NceDataProvider",
    "NCEAuthenticationError",
    # Service-layer (OpenConfig-aligned) data containers
    "NetworkInstance",
    "ConnectionPoint",
    "Endpoint",
    "LocalEndpoint",
    "RemoteEndpoint",
    "Fdb",
    "MacTable",
    "MacEntry",
    "Neighbor",
    "L3Interface",
    "BgpRoute",
    "NetworkInstanceType",
    "EndpointType",
    "MacEntryType",
    "MacSourceType",
    "NeighborOrigin",
    # Diagnostic actions
    "PingRequest",
    "PingProbe",
    "PingResult",
    "TracerouteRequest",
    "TracerouteProbe",
    "TracerouteHop",
    "TracerouteResult",
    "NetconfActionNotAuthorized",
]
