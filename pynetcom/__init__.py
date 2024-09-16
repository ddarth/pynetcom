# Import classes and functions

from pynetcom.rest_nce import RestNCE
from pynetcom.rest_nsp import RestNSP

# Library version
__version__ = "0.1.2"

# Description
__doc__ = """
pynetcom - Python library for interacting with network devices and management systems
via REST API and CLI, supporting multiple vendors like Huawei, Nokia, and more.
"""

# Objects list, thats will be imported by default
__all__ = ["RestNCE", "RestNSP"]
