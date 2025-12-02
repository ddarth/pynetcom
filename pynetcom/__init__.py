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
__version__ = "0.1.6"

# Description
__doc__ = """
pynetcom - Python library for interacting with network devices and management systems
via REST API and CLI, supporting multiple vendors like Huawei, Nokia, and more.
"""

# Objects list, thats will be imported by default
# __all__ = ["RestNCE", "RestNSP", "NetconfClient", "EquipCLI", "NokiaEquipCLI", "HuaweiEquipCLI", "cli_caret"]
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
